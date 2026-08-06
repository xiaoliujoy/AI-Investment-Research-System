#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Belief Execution Engine（信念兑现引擎）—— 多账户 A/B/C/D + 信念兑现率 统一视图

输入：
  - 股票成交 tonghuashun_stock_trade (233 fills)  + stock_daily (真实 OHLC)
  - 期货成交 tonghuashun_futures_trade (2586 fills) + commodity_daily (主力连续, 仅 au/ag/cu 有收盘)
  - MT5 既有结论（硬编码，来自 trading_discipline_engine 已验证分析，210 笔）

MFE 口径（关键约束，见代码内注释）：
  - 股票：stock_daily 有 open/high/low/close → 真实 MFE（可靠）
  - 期货线性合约：具体合约已过期，本地/TDX/westock 均无历史 OHLC →
        au/ag/cu 用 commodity_daily 主力连续「日线收盘」做 MFE 保守近似
        （close <= 真实高低点，故为有利波动的下界；换月跳空未修正）
        其余品种(si/ps/FG/PK/jm)与期权：无路径数据 → A/B/C/D = N/A，仅给经济画像
  - 这是「诚实 NULL > 伪精确」下的诚实近似，报告中明确标注。

A/B/C/D 定义（与 trading_discipline_engine.abcd_analysis 一致）：
  A 方向错(mfe<=0)  B 方向对且 capture>=0.5  C 方向对提前小赚  D 方向对倒亏
  三指标：逻辑存活率=方向正确率；利润捕获率=方向正确者 capture 中位；提前退出率=(C+D)/方向正确
  信念兑现率 = 方向对且 capture>=0.5 / 方向对
"""
import os, json, sqlite3, statistics, re

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "database", "vibe_research.db")
OUT = os.path.join(HERE, "..", "..", "mt5_raw", "execution_intelligence.json")

# 期货品种 -> 合约乘数(元/价格点/手)
MULT = {"au": 1000, "ag": 15, "cu": 5, "si": 5, "ps": 3, "FG": 20, "PK": 10, "jm": 60}
# 期货品种 -> commodity_daily 主力连续 symbol（仅 au/ag/cu 有数据）
CONT = {"au": "AU0", "ag": "AG0", "cu": "CU0"}

OPT_RE = re.compile(r'^[a-zA-Z]+\d+[CP]\d+$')


def _con():
    return sqlite3.connect(DB)


def _norm(d):
    d = str(d)
    if "-" in d:
        return d
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


# ---------------------------------------------------------------------------
# Round-trip 重建（FIFO）
# ---------------------------------------------------------------------------
def reconstruct(fills, kind):
    """fills: list of dict(date, bs, oc, price, lots, net_pnl[期货], cost[股票], key)
    kind='stock' -> op in {证券买入,证券卖出}; kind='futures' -> bs in {买,卖}, oc in {开,平*}
    股票净盈亏 = (exit-entry)*lots - 开仓费 - 平仓费；期货净盈亏 = 成交单 net_pnl(权威)。
    """
    open_stack = {}
    rts = []
    for f in sorted(fills, key=lambda x: (x["date"], x.get("seq", 0))):
        key = f["key"]
        if kind == "stock":
            is_open = f["bs"] == "证券买入"
            direction_open = "long"
        else:
            is_open = f["oc"] == "开"
            direction_open = "long" if f["bs"] == "买" else "short"
        if is_open:
            open_stack.setdefault(key, []).append({
                "date": f["date"], "price": f["price"], "remaining": f["lots"],
                "direction": direction_open,
                "open_cost": f.get("cost", 0.0), "open_qty": f["lots"],
                "open_net": (f.get("net_pnl") or 0.0) if kind == "futures" else 0.0,
            })
        else:
            need = f["lots"]
            fill_pnl = f.get("net_pnl")
            fill_cost = f.get("cost", 0.0)
            while need > 1e-9 and open_stack.get(key):
                lot = open_stack[key][0]
                matched = min(need, lot["remaining"])
                share = matched / f["lots"] if f["lots"] else 0
                open_cost_alloc = lot["open_cost"] * (matched / lot["open_qty"]) if lot["open_qty"] else 0
                close_cost_alloc = fill_cost * share
                if kind == "futures":
                    # 期货 net_pnl：开仓单带开仓现金流(期货=开仓费/期权=±权利金)，
                    # 平仓单带平仓已实现盈亏。round-trip 净盈亏 = 平仓 + 开仓(按配比)，
                    # 总和才能回到权威数(-72,490.81)，否则期权漏扣权利金。
                    np = (fill_pnl or 0.0) * share + lot["open_net"] * (matched / lot["open_qty"]) if lot["open_qty"] else 0
                else:
                    np = (f["price"] - lot["price"]) * matched - open_cost_alloc - close_cost_alloc
                rts.append({
                    "key": key,
                    "direction": lot["direction"],
                    "entry_date": lot["date"],
                    "entry_price": lot["price"],
                    "exit_date": f["date"],
                    "exit_price": f["price"],
                    "lots": matched,
                    "net_pnl": np,
                    "is_option": f.get("is_option", False),
                })
                lot["remaining"] -= matched
                need -= matched
                if lot["remaining"] <= 1e-9:
                    open_stack[key].pop(0)
    return rts


# ---------------------------------------------------------------------------
# MFE 计算
# ---------------------------------------------------------------------------
def _load_stock_bars(codes):
    c = _con()
    out = {}
    for code in codes:
        rows = c.execute(
            "SELECT date,open,high,low,close FROM stock_daily WHERE code=? ORDER BY date",
            (code,)).fetchall()
        out[code] = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
    c.close()
    return out


def _load_cont_bars():
    c = _con()
    out = {}
    for sym in set(CONT.values()):
        rows = c.execute(
            "SELECT date,close FROM commodity_daily WHERE symbol=? ORDER BY date",
            (sym,)).fetchall()
        out[sym] = [(r[0], r[1]) for r in rows]
    c.close()
    return out


def mfe_stock(rt, bars):
    """真实 MFE（high/low）。rt 多头。"""
    code = rt["key"]
    if code not in bars:
        return None, None
    ed, xd = rt["entry_date"], rt["exit_date"]
    lo, hi = [], []
    for date, o, h, l, c in bars[code]:
        if ed <= date <= xd:
            hi.append(h); lo.append(l)
    if not hi:
        return None, None
    mfe = max(hi) - rt["entry_price"]          # 有利波动
    mae = rt["entry_price"] - min(lo)           # 不利波动
    return mfe, mae


def mfe_futures_proxy(rt, cont_bars):
    """期货 MFE 保守近似：用主力连续「日线收盘」。
    仅 au/ag/cu 有数据；其余返回 None。close<=真实高低点 → 有利波动下界。"""
    prod = re.match(r'^([a-zA-Z]+)\d+', rt["key"])
    if not prod:
        return None, None
    prod = prod.group(1)
    if prod not in CONT:
        return None, None
    sym = CONT[prod]
    if sym not in cont_bars:
        return None, None
    ed, xd = rt["entry_date"], rt["exit_date"]
    closes = [cl for date, cl in cont_bars[sym] if ed <= date <= xd]
    if not closes:
        return None, None
    if rt["direction"] == "long":
        mfe = max(closes) - rt["entry_price"]
        mae = rt["entry_price"] - min(closes)
    else:
        mfe = rt["entry_price"] - min(closes)
        mae = max(closes) - rt["entry_price"]
    return mfe, mae


# ---------------------------------------------------------------------------
# 分类 + 聚合
# ---------------------------------------------------------------------------
def classify(rt, mfe, mae, mult=1.0):
    """返回 (cls, cap)。cls in {A,B,C,D,None}; cap = net_pnl/(mfe*mult*lots)。"""
    if mfe is None:
        return None, None
    lots = rt["lots"]
    mfe_ccy = mfe * mult * lots
    if mfe_ccy <= 1e-9:
        return "A", None
    cap = rt["net_pnl"] / mfe_ccy if mfe_ccy else 0
    if cap >= 0.5:
        return "B", cap
    if rt["net_pnl"] >= 0:
        return "C", cap
    return "D", cap


def aggregate(round_trips_with_cls):
    """round_trips_with_cls: list of (rt, cls, cap)"""
    rts = [(rt, cls, cap) for rt, cls, cap in round_trips_with_cls if cls is not None]
    total = len(rts)
    A = B = C = D = 0
    dc = []  # 方向正确
    caps = []
    for rt, cls, cap in rts:
        if cls == "A": A += 1
        elif cls == "B": B += 1; dc.append(rt); caps.append(cap)
        elif cls == "C": C += 1; dc.append(rt); caps.append(cap)
        elif cls == "D": D += 1; dc.append(rt); caps.append(cap)
    n_dc = len(dc)
    out = {
        "total": total,
        "A": A, "B": B, "C": C, "D": D,
        "direction_correct": n_dc,
        "thesis_survival_rate": n_dc / total if total else 0,
        "cd_rate": (C + D) / total if total else 0,
        "premature_exit_rate": (C + D) / n_dc if n_dc else 0,
        "capture_median": statistics.median(caps) if caps else 0,
        "belief_fulfillment_rate": B / n_dc if n_dc else 0,
        "belief_target_40_need": (int(0.40 * n_dc) - B) if n_dc else 0,
    }
    return out


# ---------------------------------------------------------------------------
# 经济画像（不依赖 MFE，全部合约可用）
# ---------------------------------------------------------------------------
def economic_profile(rts):
    wins = [r for r in rts if r["net_pnl"] > 0]
    losses = [r for r in rts if r["net_pnl"] <= 0]
    gross_win = sum(r["net_pnl"] for r in wins)
    gross_loss = abs(sum(r["net_pnl"] for r in losses))
    hold_days = []
    for r in rts:
        try:
            from datetime import date
            d0 = date.fromisoformat(_norm(r["entry_date"]))
            d1 = date.fromisoformat(_norm(r["exit_date"]))
            hold_days.append((d1 - d0).days)
        except Exception:
            pass
    same_day = sum(1 for h in hold_days if h == 0)
    return {
        "n": len(rts),
        "win_n": len(wins),
        "loss_n": len(losses),
        "win_rate": len(wins) / len(rts) if rts else 0,
        "net_pnl": sum(r["net_pnl"] for r in rts),
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "avg_win": gross_win / len(wins) if wins else 0,
        "avg_loss": (sum(r["net_pnl"] for r in losses) / len(losses)) if losses else 0,
        "avg_hold_days": statistics.mean(hold_days) if hold_days else 0,
        "same_day_rate": same_day / len(hold_days) if hold_days else 0,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run():
    c = _con()
    # ---- 期货 fills ----
    frows = c.execute(
        "SELECT trade_date,instrument,bs,oc,price,lots,net_pnl FROM tonghuashun_futures_trade"
    ).fetchall()
    fut_fills = []
    for i, (td, inst, bs, oc, price, lots, np) in enumerate(frows):
        fut_fills.append({
            "date": _norm(td), "key": inst, "bs": bs, "oc": oc,
            "price": float(price), "lots": float(lots), "net_pnl": float(np or 0),
            "is_option": bool(OPT_RE.match(inst)), "seq": i,
        })
    # ---- 股票 fills ----
    srows = c.execute(
        "SELECT trade_date,code,op,price,qty,fee,stamp,other FROM tonghuashun_stock_trade"
    ).fetchall()
    stock_fills = []
    for i, (td, code, op, price, qty, fee, stamp, other) in enumerate(srows):
        cost = float(fee or 0) + float(stamp or 0) + float(other or 0)
        stock_fills.append({
            "date": _norm(td), "key": code, "bs": op, "oc": "开" if op == "证券买入" else "平",
            "price": float(price), "lots": float(qty), "net_pnl": None, "cost": cost,
            "is_option": False, "seq": i,
        })
    c.close()

    # ---- 重建 ----
    fut_rts = reconstruct(fut_fills, "futures")
    stock_rts = reconstruct(stock_fills, "stock")

    # ---- 加载价格 ----
    stock_codes = sorted(set(r["key"] for r in stock_rts))
    stock_bars = _load_stock_bars(stock_codes)
    cont_bars = _load_cont_bars()

    # ---- 股票 ABCD ----
    stock_cls = []
    for r in stock_rts:
        mfe, mae = mfe_stock(r, stock_bars)
        cls, cap = classify(r, mfe, mae, mult=1.0)
        stock_cls.append((r, cls, cap))
    stock_abcd = aggregate(stock_cls)
    stock_econ = economic_profile(stock_rts)

    # ---- 期货 ABCD（仅 au/ag/cu 近似；其余 N/A）----
    fut_cls = []
    fut_na = 0
    for r in fut_rts:
        prod = re.match(r'^([a-zA-Z]+)\d+', r["key"])
        prod = prod.group(1) if prod else ""
        if r["is_option"] or prod not in MULT:
            fut_na += 1
            continue
        mfe, mae = mfe_futures_proxy(r, cont_bars)
        cls, cap = classify(r, mfe, mae, mult=MULT.get(prod, 1))
        fut_cls.append((r, cls, cap))
        if cls is None:
            fut_na += 1
    fut_abcd = aggregate(fut_cls)
    fut_econ = economic_profile(fut_rts)
    # 期权单独经济
    opt_rts = [r for r in fut_rts if r["is_option"]]
    opt_econ = economic_profile(opt_rts)
    # 期货按品种经济
    by_prod = {}
    for r in fut_rts:
        p = r["key"] if r["is_option"] else re.match(r'^([a-zA-Z]+)\d+', r["key"]).group(1)
        by_prod.setdefault(p, []).append(r)
    fut_by_prod = {p: economic_profile(v) for p, v in by_prod.items()}

    # ---- MT5 既有（硬编码，来自已验证分析）----
    mt5 = {
        "abcd": {
            "total": 210, "A": 14, "B": 23, "C": 40, "D": 133,
            "direction_correct": 196, "thesis_survival_rate": 0.933,
            "cd_rate": 0.823, "premature_exit_rate": 0.883,
            "capture_median": -0.69, "belief_fulfillment_rate": 0.117,
            "belief_target_40_need": 55,
        },
        "econ": {"net_pnl": 9.01,
                 "note": "既有 MT5 全账户分析(225笔 manual)，净 +9.01 USD；XAUUSD 210笔 A/B/C/D 已验证"},
        "source": "既有 MT5 XAUUSD 分析(210笔, 已验证)",
    }

    result = {
        "stock": {"abcd": stock_abcd, "econ": stock_econ, "mfe_source": "stock_daily 真实OHLC(可靠)",
                  "n_roundtrip": len(stock_rts)},
        "futures": {"abcd": fut_abcd, "econ": fut_econ, "opt_econ": opt_econ,
                    "by_product": fut_by_prod, "mfe_source": "commodity_daily 主力连续日线收盘(保守近似, 仅au/ag/cu)",
                    "n_roundtrip": len(fut_rts), "n_abcd_available": len(fut_cls),
                    "n_abcd_na": fut_na},
        "mt5": mt5,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def _pct(x):
    return f"{x*100:.1f}%"


def _print(result):
    s = result["stock"]; f = result["futures"]; m = result["mt5"]
    print("\n" + "=" * 64)
    print("  执行智能 · 多账户 A/B/C/D + 信念兑现率")
    print("=" * 64)
    print("\n【股票】 round-trips=%d  MFE源: %s" % (s["n_roundtrip"], s["mfe_source"]))
    a = s["abcd"]
    print("  A方向错   %3d (%s) | B方向对盈利 %3d (%s)" % (a["A"], _pct(a["A"]/a["total"]), a["B"], _pct(a["B"]/a["total"])))
    print("  C方向对小赚 %2d (%s) | D方向对倒亏 %3d (%s)" % (a["C"], _pct(a["C"]/a["total"]), a["D"], _pct(a["D"]/a["total"])))
    print("  逻辑存活率 %s | 利润捕获率(中位) %.2f | 提前退出率 %s" % (
        _pct(a["thesis_survival_rate"]), a["capture_median"], _pct(a["premature_exit_rate"])))
    print("  ★ 信念兑现率 %s (目标40%%需再+B %d 笔)" % (_pct(a["belief_fulfillment_rate"]), a["belief_target_40_need"]))
    e = s["econ"]
    print("  经济: 胜率 %s 盈亏比PF=%s 净 %+.0f 均持仓%.1f天 同日平仓率 %s" % (
        _pct(e["win_rate"]), (f'{e["profit_factor"]:.2f}' if e["profit_factor"] else 'NA'),
        e["net_pnl"], e["avg_hold_days"], _pct(e["same_day_rate"])))

    print("\n【期货】 round-trips=%d (ABCD可用=%d, N/A=%d)" % (f["n_roundtrip"], f["n_abcd_available"], f["n_abcd_na"]))
    print("  MFE源: %s" % f["mfe_source"])
    if f["abcd"]["total"]:
        a = f["abcd"]
        print("  A %3d(%s) B %3d(%s) C %3d(%s) D %3d(%s)" % (
            a["A"], _pct(a["A"]/a["total"]), a["B"], _pct(a["B"]/a["total"]),
            a["C"], _pct(a["C"]/a["total"]), a["D"], _pct(a["D"]/a["total"])))
        print("  逻辑存活率 %s | 利润捕获率(中位) %.2f | 提前退出率 %s" % (
            _pct(a["thesis_survival_rate"]), a["capture_median"], _pct(a["premature_exit_rate"])))
        print("  ★ 信念兑现率(近似) %s" % _pct(a["belief_fulfillment_rate"]))
    e = f["econ"]
    print("  经济(全部合约): 胜率 %s PF=%s 净 %+.0f 均持仓%.1f天 同日平仓率 %s" % (
        _pct(e["win_rate"]), (f'{e["profit_factor"]:.2f}' if e["profit_factor"] else 'NA'),
        e["net_pnl"], e["avg_hold_days"], _pct(e["same_day_rate"])))
    print("  期权经济: 净 %+.0f (n=%d)" % (f["opt_econ"]["net_pnl"], f["opt_econ"]["n"]))
    print("  按品种净盈亏:")
    for p, pe in sorted(f["by_product"].items(), key=lambda x: x[1]["net_pnl"]):
        print("    %-5s 净 %+9.0f  胜率 %s  PF=%s  笔数 %d" % (
            p, pe["net_pnl"], _pct(pe["win_rate"]),
            (f'{pe["profit_factor"]:.2f}' if pe["profit_factor"] else 'NA'), pe["n"]))

    print("\n【MT5 既有】 210笔 方向正确率 %s 信念兑现率 %s C+D %s 利润捕获率(中位) %.2f" % (
        _pct(m["abcd"]["thesis_survival_rate"]), _pct(m["abcd"]["belief_fulfillment_rate"]),
        _pct(m["abcd"]["cd_rate"]), m["abcd"]["capture_median"]))

    print("\n" + "=" * 64)
    print("  统一视图 · 跨账户稳定行为")
    print("=" * 64)
    print("  账户        方向正确率   信念兑现率   C+D%    净盈亏")
    print("  股票(可靠)  %s    %s   %s  %+9.0f" % (
        _pct(s["abcd"]["thesis_survival_rate"]), _pct(s["abcd"]["belief_fulfillment_rate"]),
        _pct(s["abcd"]["cd_rate"]), s["econ"]["net_pnl"]))
    print("  期货(近似)  %s    %s   %s  %+9.0f" % (
        _pct(f["abcd"]["thesis_survival_rate"]) if f["abcd"]["total"] else 'NA',
        _pct(f["abcd"]["belief_fulfillment_rate"]) if f["abcd"]["total"] else 'NA',
        _pct(f["abcd"]["cd_rate"]) if f["abcd"]["total"] else 'NA', f["econ"]["net_pnl"]))
    print("  MT5(可靠)   %s    %s   %s  %+9.0f" % (
        _pct(m["abcd"]["thesis_survival_rate"]), _pct(m["abcd"]["belief_fulfillment_rate"]),
        _pct(m["abcd"]["cd_rate"]), m["econ"]["net_pnl"]))
    print("\n  结论: 股票+MT5 两账户(可靠口径)方向正确率均高、信念兑现率均低 →")
    print("        漏损在执行/持有层, 非判断层。期货经济亏损(-7.25万)与高同日平仓率")
    print("        一致指向同一瓶颈: 拿不住/高频scalp/提前平。")
    print("=" * 64)


if __name__ == "__main__":
    r = run()
    _print(r)
