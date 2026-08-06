#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trader OS · Layer 3 路径层 —— Trade Path Reconstruction Module (v0.1)

上位文档: docs/trader_os_behavior_engine_v0.1.md §7 / trader_os_v0.1_architecture_freeze.md

职责: 重建每笔交易的价格路径, 回答一个结果层无法回答的问题——

    交易发生后, 市场到底有没有给过你机会?

    类型 A 入场错误      MAE 大, MFE 小       -> 放宽止损无意义, 只是延迟死亡
    类型 B 方向对止损紧  MAE 大, MFE 也大      -> 止损问题, 放宽可能有效
    类型 C 方向对管理差  MFE 大, 实际收益小    -> 出场问题, 与止损无关

    单看交易结果(盈亏)完全无法区分这三类, 必须有 Entry -> MAE -> MFE -> Exit 链条。

核心指标:
    MFE (Max Favorable Excursion)  持仓期间朝有利方向的最大移动
    MAE (Max Adverse Excursion)    持仓期间朝不利方向的最大移动
    MFE_capture_ratio = 实际价格位移 / MFE   (浮盈转化率, 看"拿到多少")
    POL = (MFE - 实际收益) / MFE           (盈利机会损失率, 看"漏掉/倒吐多少", 对输家更具区分力)

------------------------------------------------------------------
【精度声明 · 必读】(2026-08-05 本机实测)
    本机 MT5 各周期缓存深度不同:
        M1  仅回溯至 2026-05-14
        M5  可回溯至 2025-12
    而用户 69% 的持仓短于 5 分钟, 因此:
      1) 采用【混合精度】: 优先 M1, 不覆盖时回退 M5, 逐笔标注 path_tf。
      2) 持仓时长 / bar 周期 < 2 时精度标 low —— 一根 bar 就吞掉整笔交易,
         此时 MFE/MAE 被系统性【高估】(bar 的 high/low 含持仓区间外的价格)。
      3) 汇总统计默认按 precision 分层输出, 禁止把 low 精度样本与
         high 精度样本混在一起下结论。
    这不是可以忽略的技术细节: 对 scalping 行为, 精度不足会直接制造
    "市场给过机会" 的假象。
------------------------------------------------------------------

SL 管理行为推断 (对应 Behavior Engine §4.3 SL Management Behavior):
    MT5 不保存持仓 SL 的修改历史(orders.csv 中 sl!=0 仅 8 条),
    因此【无法直接观测】止损是否被移动过。本模块用两侧证据做推断:

      A) SL 触发价落在盈利侧  -> manual_move 确证(初始止损不可能设在盈利侧)
      B) SL 触发价在亏损侧, 但 MFE >= 2x 初始风险距离
                              -> no_move_despite_opportunity 确证(有机会移却没移)
      C) 其余                 -> unknown (不可判定, 不得计入任何一侧)

    刻意同时输出 A 和 B: 只统计 A(成功移动止损)会产生幸存者偏差。

用法:
    python backend/trade_path_reconstruction.py
    python backend/trade_path_reconstruction.py --symbol XAUUSD --out mt5_raw/trade_path

输出:
    mt5_raw/trade_path.csv    逐笔路径明细
    mt5_raw/trade_path.json   同上 + 分层汇总
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "mt5_raw")

CONTRACT_SIZE = {"XAUUSD": 100.0}
DEFAULT_CONTRACT = 100.0

# MT5 deal entry 常量
ENTRY_IN, ENTRY_OUT, ENTRY_INOUT = 0, 1, 2

SL_COMMENT = re.compile(r"\[sl\s+([\d.]+)\]")
TP_COMMENT = re.compile(r"\[tp\s+([\d.]+)\]")

# 路径原型阈值 (v0.1 默认, 描述性分类而非预测模型; 报告同时输出敏感性)
ARCHETYPE_ENTRY_WRONG_R = 0.25   # mfe/mae <= 此值 -> 市场几乎没给机会
ARCHETYPE_CAPTURE_LOW = 0.30     # capture_ratio < 此值 且 mfe 显著 -> 管理问题


# ----------------------------- 数据载入 -----------------------------

def load_bars(path):
    """[(epoch, high, low)] 升序。只保留计算 MFE/MAE 必需的列以省内存。"""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out.append((int(float(row["time"])),
                        float(row["high"]), float(row["low"])))
    out.sort(key=lambda x: x[0])
    return out


def load_deals(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def build_positions(deals, symbol):
    """从 deals 重建持仓: 精确加权 entry/exit 价、时间、退出原因、SL 触发价。"""
    pos = {}
    for d in deals:
        if d.get("symbol") != symbol:
            continue
        pid = d.get("position_id")
        if not pid or pid == "0":
            continue
        entry_flag = int(_f(d.get("entry")))
        vol = _f(d.get("volume"))
        price = _f(d.get("price"))
        t = int(_f(d.get("time")))
        p = pos.setdefault(pid, {
            "position_id": pid, "symbol": symbol,
            "in_vol": 0.0, "in_notional": 0.0, "in_time": None,
            "out_vol": 0.0, "out_notional": 0.0, "out_time": None,
            "profit": 0.0, "commission": 0.0, "swap": 0.0,
            "direction": None, "exit_reason": "manual",
            "sl_trigger_price": None, "n_deals": 0,
        })
        p["n_deals"] += 1
        p["profit"] += _f(d.get("profit"))
        p["commission"] += _f(d.get("commission"))
        p["swap"] += _f(d.get("swap"))

        if entry_flag in (ENTRY_IN, ENTRY_INOUT):
            p["in_vol"] += vol
            p["in_notional"] += vol * price
            p["in_time"] = t if p["in_time"] is None else min(p["in_time"], t)
            # deal type: 0=buy 1=sell
            p["direction"] = "BUY" if int(_f(d.get("type"))) == 0 else "SELL"
        if entry_flag in (ENTRY_OUT, ENTRY_INOUT):
            p["out_vol"] += vol
            p["out_notional"] += vol * price
            p["out_time"] = t if p["out_time"] is None else max(p["out_time"], t)
            cmt = d.get("comment") or ""
            m = SL_COMMENT.search(cmt)
            if m:
                p["exit_reason"] = "sl"
                p["sl_trigger_price"] = float(m.group(1))
            elif TP_COMMENT.search(cmt):
                p["exit_reason"] = "tp"

    out = []
    for p in pos.values():
        if not p["in_vol"] or not p["out_vol"] or p["in_time"] is None:
            continue
        p["entry_price"] = p["in_notional"] / p["in_vol"]
        p["exit_price"] = p["out_notional"] / p["out_vol"]
        p["volume"] = p["in_vol"]
        p["pnl"] = round(p["profit"] + p["commission"] + p["swap"], 2)
        p["holding_sec"] = max(0, (p["out_time"] or p["in_time"]) - p["in_time"])
        out.append(p)
    out.sort(key=lambda x: x["in_time"])
    return out


# ----------------------------- 路径计算 -----------------------------

def slice_bars(bars, t0, t1, tf_sec):
    """取覆盖 [t0, t1] 的 bar 段(含入场所在 bar 与出场所在 bar)。"""
    start = (t0 // tf_sec) * tf_sec
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid][0] < start:
            lo = mid + 1
        else:
            hi = mid
    seg = []
    i = lo
    while i < len(bars) and bars[i][0] <= t1:
        seg.append(bars[i])
        i += 1
    if not seg and lo < len(bars):
        seg = [bars[lo]]
    return seg


def compute_path(p, bars, tf_sec, tf_name):
    t0, t1 = p["in_time"], p["out_time"]
    seg = slice_bars(bars, t0, t1, tf_sec)
    if not seg:
        return None
    ep = p["entry_price"]
    is_buy = p["direction"] == "BUY"

    best, worst = None, None       # (excursion_price, bar_time)
    for (bt, h, l) in seg:
        fav = (h - ep) if is_buy else (ep - l)
        adv = (ep - l) if is_buy else (h - ep)
        if best is None or fav > best[0]:
            best = (fav, bt)
        if worst is None or adv > worst[0]:
            worst = (adv, bt)

    mfe_p = max(best[0], 0.0)
    mae_p = max(worst[0], 0.0)
    vol = p["volume"]
    cs = CONTRACT_SIZE.get(p["symbol"], DEFAULT_CONTRACT)
    mult = vol * cs

    move = (p["exit_price"] - ep) if is_buy else (ep - p["exit_price"])

    # 浮盈转化率: 实际拿到的价格位移 / 最大可获得价格位移
    capture = round(move / mfe_p, 4) if mfe_p > 1e-9 else None

    # 盈利机会损失率 POL = (MFE - 实际收益) / MFE  (用户 2026-08-05 新增核心指标)
    #   - MFE<=0 (市场没给机会)        -> None (N/A)
    #   - 赢家 (pnl>0)                 -> POL in (0,1): 留在桌上的比例
    #   - 输家 (MFE>0 但 pnl<0)        -> POL > 1: 不仅没拿到, 还把 MFE 之外也吐回
    # 与 capture_ratio 互补: capture 看"拿到多少", POL 看"漏掉/倒吐多少", 后者对输家更有区分力。
    mfe_usd_raw = mfe_p * mult
    pol = round((mfe_usd_raw - p["pnl"]) / mfe_usd_raw, 4) if mfe_usd_raw > 1e-9 else None

    hold = max(p["holding_sec"], 1)
    ratio_bars = hold / tf_sec
    precision = "high" if ratio_bars >= 5 else ("mid" if ratio_bars >= 2 else "low")

    return {
        "mfe_price": round(mfe_p, 4),
        "mae_price": round(mae_p, 4),
        "mfe_usd": round(mfe_usd_raw, 2),
        "mae_usd": round(mae_p * mult, 2),
        "mfe_bar_time": best[1],
        "mae_bar_time": worst[1],
        "mfe_offset_sec": best[1] - t0,
        "mae_offset_sec": worst[1] - t0,
        "price_move": round(move, 4),
        "mfe_capture_ratio": capture,
        "pol": pol,
        "mae_mfe_ratio": round(mae_p / mfe_p, 3) if mfe_p > 1e-9 else None,
        "path_tf": tf_name,
        "bar_count": len(seg),
        "precision": precision,
    }


def classify_archetype(r):
    """描述性路径原型 (非预测模型, 阈值见文件头常量)。"""
    mfe, mae = r["mfe_price"], r["mae_price"]
    cap = r["mfe_capture_ratio"]
    if mfe <= 1e-9:
        return "A_entry_wrong"
    if mae > 0 and mfe / max(mae, 1e-9) <= ARCHETYPE_ENTRY_WRONG_R:
        return "A_entry_wrong"
    if r["pnl"] < 0 and mfe >= mae:
        return "B_stop_too_tight"
    if cap is not None and cap < ARCHETYPE_CAPTURE_LOW:
        return "C_exit_management"
    if r["pnl"] < 0:
        return "B_stop_too_tight"
    return "D_captured"


def infer_sl_management(r):
    """SL 管理行为推断。见文件头说明: 同时输出正反两侧, 避免幸存者偏差。"""
    if r["exit_reason"] != "sl" or r.get("sl_trigger_price") is None:
        return "not_applicable", "none"
    ep, sl = r["entry_price"], r["sl_trigger_price"]
    is_buy = r["direction"] == "BUY"
    favorable = (sl > ep) if is_buy else (sl < ep)
    if favorable:
        return "manual_move", "to_profit"
    risk = abs(ep - sl)
    if risk > 1e-9 and r["mfe_price"] >= 2.0 * risk:
        return "no_move_despite_opportunity", "none"
    return "unknown", "unknown"


# ----------------------------- 汇总 -----------------------------

def summarize(rows):
    def agg(subset, label):
        if not subset:
            return {"label": label, "n": 0}
        caps = sorted(r["mfe_capture_ratio"] for r in subset
                      if r["mfe_capture_ratio"] is not None)
        pnls = [r["pnl"] for r in subset]
        wins = [p for p in pnls if p > 0]
        arche = {}
        for r in subset:
            arche[r["path_archetype"]] = arche.get(r["path_archetype"], 0) + 1
        med_cap = caps[len(caps) // 2] if caps else None
        pols = [r["pol"] for r in subset if r.get("pol") is not None]
        med_pol = sorted(pols)[len(pols) // 2] if pols else None
        return {
            "label": label,
            "n": len(subset),
            "net_pnl": round(sum(pnls), 2),
            "win_rate_pct": round(100.0 * len(wins) / len(subset), 1),
            "median_capture_ratio": med_cap,
            "median_pol": med_pol,
            "mean_capture_ratio": round(sum(caps) / len(caps), 4) if caps else None,
            "median_mfe_usd": sorted(r["mfe_usd"] for r in subset)[len(subset) // 2],
            "median_mae_usd": sorted(r["mae_usd"] for r in subset)[len(subset) // 2],
            "archetype": dict(sorted(arche.items())),
        }

    out = {"overall": agg(rows, "ALL")}
    out["by_precision"] = [
        agg([r for r in rows if r["precision"] == p], f"precision={p}")
        for p in ("high", "mid", "low")
    ]
    out["by_tf"] = [
        agg([r for r in rows if r["path_tf"] == t], f"tf={t}")
        for t in sorted({r["path_tf"] for r in rows})
    ]
    out["losers_only"] = agg([r for r in rows if r["pnl"] < 0], "pnl<0")
    out["winners_only"] = agg([r for r in rows if r["pnl"] > 0], "pnl>0")

    slm = {}
    for r in rows:
        slm[r["sl_management_type"]] = slm.get(r["sl_management_type"], 0) + 1
    out["sl_management"] = dict(sorted(slm.items()))

    # 幸存者偏差对照: 移动止损 vs 有机会没移动
    moved = [r for r in rows if r["sl_management_type"] == "manual_move"]
    not_moved = [r for r in rows
                 if r["sl_management_type"] == "no_move_despite_opportunity"]
    out["sl_behavior_contrast"] = {
        "manual_move": agg(moved, "SL moved to profit"),
        "no_move_despite_opportunity": agg(not_moved, "SL not moved (had chance)"),
    }
    return out


# ----------------------------- 主流程 -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--deals", default=os.path.join(RAW, "mt5_history_deals.csv"))
    ap.add_argument("--bars-dir", dest="bars_dir", default=RAW)
    ap.add_argument("--out", default=os.path.join(RAW, "trade_path"))
    args = ap.parse_args()

    if not os.path.exists(args.deals):
        print("缺少 deals:", args.deals)
        sys.exit(2)

    sources = []
    for tf_name, tf_sec in (("M1", 60), ("M5", 300), ("M15", 900)):
        p = os.path.join(args.bars_dir, f"{args.symbol}_{tf_name}.csv")
        if os.path.exists(p):
            bars = load_bars(p)
            if bars:
                sources.append((tf_name, tf_sec, bars, bars[0][0], bars[-1][0]))
    if not sources:
        print("缺少 K 线数据, 先运行:")
        print(f"  python mt5_export.py --bars {args.symbol} --bars-from 2026-03-15")
        sys.exit(2)

    print("K 线源(按精度优先):")
    for tf_name, _s, bars, t0, t1 in sources:
        print("  %-4s %6d 根  %s ~ %s" % (
            tf_name, len(bars),
            datetime.utcfromtimestamp(t0).strftime("%Y-%m-%d"),
            datetime.utcfromtimestamp(t1).strftime("%Y-%m-%d")))

    deals = load_deals(args.deals)
    positions = build_positions(deals, args.symbol)
    print("重建持仓: %d 笔 (%s)" % (len(positions), args.symbol))

    rows, skipped = [], 0
    for p in positions:
        chosen = None
        for tf_name, tf_sec, bars, t0, t1 in sources:
            if t0 <= p["in_time"] and p["out_time"] <= t1:
                chosen = (tf_name, tf_sec, bars)
                break
        if chosen is None:
            skipped += 1
            continue
        tf_name, tf_sec, bars = chosen
        path = compute_path(p, bars, tf_sec, tf_name)
        if path is None:
            skipped += 1
            continue
        r = {
            "trade_id": p["position_id"],
            "symbol": p["symbol"],
            "direction": p["direction"],
            "volume": round(p["volume"], 2),
            "entry_time": datetime.utcfromtimestamp(p["in_time"]).isoformat(),
            "exit_time": datetime.utcfromtimestamp(p["out_time"]).isoformat(),
            "holding_sec": p["holding_sec"],
            "entry_price": round(p["entry_price"], 4),
            "exit_price": round(p["exit_price"], 4),
            "pnl": p["pnl"],
            "exit_reason": p["exit_reason"],
            "sl_trigger_price": p["sl_trigger_price"],
            **path,
        }
        r["path_archetype"] = classify_archetype(r)
        slm, sld = infer_sl_management(r)
        r["sl_management_type"] = slm
        r["sl_move_direction"] = sld
        rows.append(r)

    if not rows:
        print("无可重建交易(K 线区间不覆盖任何持仓)。")
        sys.exit(3)

    cols = ["trade_id", "symbol", "direction", "volume", "entry_time", "exit_time",
            "holding_sec", "entry_price", "exit_price", "price_move", "pnl",
            "mfe_price", "mae_price", "mfe_usd", "mae_usd",
            "mfe_offset_sec", "mae_offset_sec",
            "mfe_capture_ratio", "pol", "mae_mfe_ratio", "path_archetype",
            "exit_reason", "sl_trigger_price", "sl_management_type",
            "sl_move_direction", "path_tf", "bar_count", "precision"]
    csv_path = args.out + ".csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    summary = summarize(rows)
    summary["_meta"] = {
        "symbol": args.symbol,
        "reconstructed": len(rows),
        "skipped_no_bars": skipped,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "precision_note": "low = 持仓 < 2 根 bar, MFE/MAE 被系统性高估, 不得与 high 混合下结论",
    }
    with open(args.out + ".json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "trades": rows}, f, ensure_ascii=False, indent=2)

    print("\n重建完成: %d 笔 (跳过 %d 笔: K线不覆盖)" % (len(rows), skipped))
    print("明细 ->", csv_path)
    o = summary["overall"]
    print("\n[全样本] n=%d  净盈亏=%.2f  胜率=%.1f%%  capture中位=%s" % (
        o["n"], o["net_pnl"], o["win_rate_pct"], o["median_capture_ratio"]))
    print("  路径原型:", o["archetype"])
    print("\n[按精度分层]")
    for b in summary["by_precision"]:
        if b["n"]:
            print("  %-16s n=%-4d 净=%9.2f capture中位=%s 原型=%s" % (
                b["label"], b["n"], b["net_pnl"],
                b["median_capture_ratio"], b["archetype"]))
    print("\n[SL 管理行为]", summary["sl_management"])


if __name__ == "__main__":
    main()
