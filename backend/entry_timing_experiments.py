"""Entry Timing Experiments — 三组验证实验

实验1: E3/E4 成功因子拆解（什么让确认入场赚钱？）
实验2: 确认入场是否遗漏机会（E1/E2 后来有没有发展成大趋势？）
实验3: 模拟 E3/E4-only 资金曲线（只做确认入场会怎样？）

数据源:
  - mt5_raw/trade_path.json        210笔交易完整路径
  - mt5_raw/entry_timing_report.json  E1-E4分类
  - mt5_raw/XAUUSD_M5.csv          M5 K线 (2026-03-02 ~ 2026-08-05)

输出:
  - mt5_raw/entry_experiments_report.json
  - 控制台摘要打印
"""

import json, csv, math, statistics
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW  = ROOT / "mt5_raw"

# ───────────────────────── 数据加载 ─────────────────────────

def load_trades():
    """加载交易路径 + 入场分类，合并成完整记录"""
    with open(RAW / "trade_path.json", encoding="utf-8") as f:
        tp = json.load(f)
    with open(RAW / "entry_timing_report.json", encoding="utf-8") as f:
        et = json.load(f)

    # 建立 trade_id -> entry_type 映射
    type_map = {}
    for t in et["trades"]:
        type_map[str(t["trade_id"])] = t["entry_type"]

    trades = []
    for t in tp["trades"]:
        tid = str(t["trade_id"])
        t["entry_type"] = type_map.get(tid, "unknown")
        trades.append(t)
    return trades

def load_m5_bars():
    """加载M5 K线，返回 (timestamp, o, h, l, c, vol) 列表"""
    bars = []
    with open(RAW / "XAUUSD_M5.csv", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                "ts": int(row["time"]),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": int(row["tick_volume"]),
            })
    bars.sort(key=lambda x: x["ts"])
    return bars

def ts_from_iso(iso_str):
    """ISO字符串 -> unix timestamp"""
    dt = datetime.fromisoformat(iso_str)
    return int(dt.replace(tzinfo=timezone.utc).timestamp())

# ───────────────────────── 实验1: E3/E4 成功因子 ─────────────────────────

def experiment1(trades):
    """拆解46笔确认入场交易的成功因子"""
    confirmed = [t for t in trades if t["entry_type"] in ("E3_confirmed_entry", "E4_well_executed")]

    # 按子类型分析
    results = {"e3": {}, "e4": {}, "combined": {}, "subtypes": {}}

    def stats_group(group, label):
        if not group:
            return {"n": 0}
        pnls = [t["pnl"] for t in group]
        mfes = [t["mfe_usd"] for t in group]
        maes = [t["mae_usd"] for t in group]
        holds = [t["holding_sec"] / 3600 for t in group]
        captures = [t["mfe_capture_ratio"] for t in group if t["mfe_capture_ratio"] is not None]
        mfe_offsets = [t.get("mfe_offset_sec", 0) for t in group]
        mae_offsets = [t.get("mae_offset_sec", 0) for t in group]
        buys = sum(1 for t in group if t["direction"] == "BUY")
        sells = len(group) - buys

        # 时段分析
        hours = []
        for t in group:
            et_ts = ts_from_iso(t["entry_time"])
            h = datetime.fromtimestamp(et_ts, tz=timezone.utc).hour
            hours.append(h)

        return {
            "n": len(group),
            "net_pnl": round(sum(pnls), 2),
            "win_rate": round(len([p for p in pnls if p > 0]) / len(pnls), 4),
            "avg_pnl": round(statistics.mean(pnls), 2),
            "avg_mfe": round(statistics.mean(mfes), 2),
            "avg_mae": round(statistics.mean(maes), 2),
            "median_mfe": round(statistics.median(mfes), 2),
            "median_mae": round(statistics.median(maes), 2),
            "avg_hold_h": round(statistics.mean(holds), 2),
            "median_hold_h": round(statistics.median(holds), 2),
            "avg_capture": round(statistics.mean(captures), 4) if captures else None,
            "median_capture": round(statistics.median(captures), 4) if captures else None,
            "avg_mfe_offset_sec": round(statistics.mean(mfe_offsets), 0) if mfe_offsets else None,
            "avg_mae_offset_sec": round(statistics.mean(mae_offsets), 0) if mae_offsets else None,
            "buy_count": buys,
            "sell_count": sells,
            "entry_hours": dict(sorted(defaultdict(int, {h: hours.count(h) for h in hours}).items())) if hours else {},
        }

    results["e3"] = stats_group([t for t in confirmed if t["entry_type"] == "E3_confirmed_entry"], "E3")
    results["e4"] = stats_group([t for t in confirmed if t["entry_type"] == "E4_well_executed"], "E4")
    results["combined"] = stats_group(confirmed, "E3+E4")

    # ── 确认方式代理分类 ──
    # A_immediate: MFE offset < 300s (5min内就朝有利方向走), MAE < 5
    # B_small_pullback: MAE offset < MFE offset (先苦后甜但MAE小), MAE < 10
    # C_pullback_entry: MAE极小(<3), MFE moderate, holding > 1h
    # D_trend_rider: MFE > 30, MAE < MFE*0.3, holding > 1h
    subtypes = defaultdict(list)
    for t in confirmed:
        mfe = t["mfe_usd"]
        mae = t["mae_usd"]
        mfe_off = t.get("mfe_offset_sec", 0) or 0
        mae_off = t.get("mae_offset_sec", 0) or 0
        hold_h = t["holding_sec"] / 3600

        if mae < 3 and hold_h > 1 and mfe > 10:
            st = "C_pullback_entry"
        elif mfe > 30 and mae < mfe * 0.3 and hold_h > 1:
            st = "D_trend_rider"
        elif mfe_off < 300 and mae < 5:
            st = "A_immediate_continuation"
        elif mae_off < mfe_off and mae < 10:
            st = "B_small_pullback_then continuation"
        else:
            st = "E_other"

        subtypes[st].append(t)

    results["subtypes"] = {k: stats_group(v, k) for k, v in subtypes.items()}

    # ── E3 vs E4 关键差异 ──
    results["key_differences"] = {
        "E3_avg_mae": results["e3"].get("avg_mae"),
        "E4_avg_mae": results["e4"].get("avg_mae"),
        "E3_avg_mfe": results["e3"].get("avg_mfe"),
        "E4_avg_mfe": results["e4"].get("avg_mfe"),
        "E3_avg_hold_h": results["e3"].get("avg_hold_h"),
        "E4_avg_hold_h": results["e4"].get("avg_hold_h"),
        "E3_avg_capture": results["e3"].get("avg_capture"),
        "E4_avg_capture": results["e4"].get("avg_capture"),
        "insight": "E3=入场时机好但退出仍差(capture低); E4=入场好+退出好(D_captured). 核心差异在退出层.",
    }

    return results, confirmed

# ───────────────────────── 实验2: 机会遗漏分析 ─────────────────────────

def experiment2(trades, bars):
    """对E1/E2交易，追踪平仓后价格是否朝预期方向发展"""

    # 构建 M5 时间索引
    bar_ts = [b["ts"] for b in bars]
    import bisect

    anticipatory = [t for t in trades if t["entry_type"] in ("E1_anticipatory_fail", "E2_anticipatory_suffered")]

    # 对每笔交易，追踪平仓后 4h / 8h / 24h 的最大有利运动
    windows = [4, 8, 24]  # hours
    results = {"by_window": {}, "summary": {}}

    for win_h in windows:
        win_s = win_h * 3600
        tracked = []

        for t in anticipatory:
            exit_ts = ts_from_iso(t["exit_time"])
            entry_price = t["entry_price"]
            direction = t["direction"]

            # 找平仓后的M5 bar
            idx = bisect.bisect_left(bar_ts, exit_ts)
            end_idx = bisect.bisect_left(bar_ts, exit_ts + win_s)

            if idx >= len(bars) or end_idx <= idx:
                continue

            future_bars = bars[idx:end_idx]

            if direction == "BUY":
                # 期望价格涨
                max_high = max(b["h"] for b in future_bars)
                min_low = min(b["l"] for b in future_bars)
                favorable = max_high - entry_price  # 朝有利方向的最大运动
                adverse = entry_price - min_low
            else:
                # SELL: 期望价格跌
                max_high = max(b["h"] for b in future_bars)
                min_low = min(b["l"] for b in future_bars)
                favorable = entry_price - min_low
                adverse = max_high - entry_price

            # 记录有利运动达到的时间
            fav_time = None
            for b in future_bars:
                if direction == "BUY" and b["h"] >= entry_price + 10:
                    fav_time = b["ts"] - exit_ts
                    break
                elif direction == "SELL" and b["l"] <= entry_price - 10:
                    fav_time = b["ts"] - exit_ts
                    break

            tracked.append({
                "trade_id": t["trade_id"],
                "entry_type": t["entry_type"],
                "direction": direction,
                "entry_price": entry_price,
                "original_pnl": t["pnl"],
                "original_mfe": t["mfe_usd"],
                "post_exit_favorable": round(favorable, 2),
                "post_exit_adverse": round(adverse, 2),
                "time_to_10usd_move_sec": fav_time,
                "developed_big_trend": favorable > 30,
                "developed_moderate": 10 <= favorable <= 30,
                "never_moved": favorable < 10,
            })

        # 统计
        big_trend = [x for x in tracked if x["developed_big_trend"]]
        moderate = [x for x in tracked if x["developed_moderate"]]
        never = [x for x in tracked if x["never_moved"]]

        # 对 big_trend 的交易，计算确认入场能捕获多少
        # 确认入场 = 等价格先朝有利方向运动10 USD以上再入场
        # 如果后来确实发展成大趋势(>30)，确认入场者会捕获大部分
        captured_by_confirmation = 0
        total_big_trend_potential = 0
        for x in big_trend:
            # 确认入场者在大趋势确认后入场，保守估计捕获 50% 的剩余运动
            if x["time_to_10usd_move_sec"] is not None:
                # 价格在平仓后 eventually 朝有利方向走了 10+
                # 假设确认入场者在 +10 处入场，捕获后续运动
                remaining = x["post_exit_favorable"] - 10  # 减去确认前已走的10
                captured_by_confirmation += remaining * 0.5  # 保守50%捕获
                total_big_trend_potential += x["post_exit_favorable"]

        results["by_window"][f"{win_h}h"] = {
            "n_tracked": len(tracked),
            "n_big_trend": len(big_trend),
            "pct_big_trend": round(len(big_trend) / len(tracked), 4) if tracked else 0,
            "n_moderate": len(moderate),
            "pct_moderate": round(len(moderate) / len(tracked), 4) if tracked else 0,
            "n_never_moved": len(never),
            "pct_never_moved": round(len(never) / len(tracked), 4) if tracked else 0,
            "avg_favorable": round(statistics.mean([x["post_exit_favorable"] for x in tracked]), 2) if tracked else 0,
            "median_favorable": round(statistics.median([x["post_exit_favorable"] for x in tracked]), 2) if tracked else 0,
            "big_trend_avg_favorable": round(statistics.mean([x["post_exit_favorable"] for x in big_trend]), 2) if big_trend else 0,
            "confirmation_capture_estimate_usd": round(captured_by_confirmation, 2),
            "actual_anticipatory_loss": round(sum(x["original_pnl"] for x in tracked), 2),
        }

    # 汇总（用24h窗口）
    w24 = results["by_window"]["24h"]
    results["summary"] = {
        "question": "E1/E2预期入场亏的钱，如果等确认后入场，能捕获多少？",
        "anticipatory_n": w24["n_tracked"],
        "anticipatory_actual_pnl": w24["actual_anticipatory_loss"],
        "big_trend_count": w24["n_big_trend"],
        "big_trend_pct": w24["pct_big_trend"],
        "big_trend_avg_move": w24["big_trend_avg_favorable"],
        "confirmation_estimate": w24["confirmation_capture_estimate_usd"],
        "verdict": "",
    }

    # 判断
    if w24["pct_big_trend"] < 0.15:
        results["summary"]["verdict"] = "绝大多数预期突破从未发展成趋势，确认入场没有遗漏显著机会"
    elif w24["pct_big_trend"] < 0.30:
        results["summary"]["verdict"] = "少数预期突破后来成趋势，但确认入场大概率能捕获其中大部分"
    else:
        results["summary"]["verdict"] = "相当多预期突破后来成趋势，需进一步评估确认入场的覆盖率"

    # E1 vs E2 分别统计
    e1_tracked = [x for x in tracked if x["entry_type"] == "E1_anticipatory_fail"]
    e2_tracked = [x for x in tracked if x["entry_type"] == "E2_anticipatory_suffered"]
    results["by_entry_type"] = {
        "E1": {
            "n": len(e1_tracked),
            "big_trend": sum(1 for x in e1_tracked if x["developed_big_trend"]),
            "never_moved": sum(1 for x in e1_tracked if x["never_moved"]),
            "avg_favorable_24h": round(statistics.mean([x["post_exit_favorable"] for x in e1_tracked]), 2) if e1_tracked else 0,
        },
        "E2": {
            "n": len(e2_tracked),
            "big_trend": sum(1 for x in e2_tracked if x["developed_big_trend"]),
            "never_moved": sum(1 for x in e2_tracked if x["never_moved"]),
            "avg_favorable_24h": round(statistics.mean([x["post_exit_favorable"] for x in e2_tracked]), 2) if e2_tracked else 0,
        },
    }

    return results

# ───────────────────────── 实验3: 资金曲线模拟 ─────────────────────────

def experiment3(trades):
    """模拟只做E3/E4的资金曲线 vs 全量"""

    # 按时间排序
    all_sorted = sorted(trades, key=lambda t: ts_from_iso(t["exit_time"]))
    confirmed_sorted = [t for t in all_sorted if t["entry_type"] in ("E3_confirmed_entry", "E4_well_executed")]

    def equity_curve(trade_list):
        cum = 0
        curve = []
        pnls = []
        for t in trade_list:
            cum += t["pnl"]
            curve.append({
                "trade_id": t["trade_id"],
                "exit_time": t["exit_time"],
                "pnl": t["pnl"],
                "cum_pnl": round(cum, 2),
                "entry_type": t["entry_type"],
            })
            pnls.append(t["pnl"])

        if not pnls:
            return {}

        # 最大回撤
        peak = -float("inf")
        max_dd = 0
        for p in curve:
            if p["cum_pnl"] > peak:
                peak = p["cum_pnl"]
            dd = peak - p["cum_pnl"]
            if dd > max_dd:
                max_dd = dd

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))

        # Sharpe (per-trade, annualized assuming ~250 trades/year)
        if len(pnls) > 1 and statistics.stdev(pnls) > 0:
            sharpe_per_trade = statistics.mean(pnls) / statistics.stdev(pnls)
            # Annualize: sqrt(250) for daily, but trades aren't daily
            # Use sqrt(n_trades) as rough annualization
            sharpe_annual = sharpe_per_trade * math.sqrt(len(pnls))
        else:
            sharpe_per_trade = 0
            sharpe_annual = 0

        # 连续亏损
        max_consec_loss = 0
        cur_consec = 0
        for p in pnls:
            if p < 0:
                cur_consec += 1
                max_consec_loss = max(max_consec_loss, cur_consec)
            else:
                cur_consec = 0

        # 连续盈利
        max_consec_win = 0
        cur_consec = 0
        for p in pnls:
            if p > 0:
                cur_consec += 1
                max_consec_win = max(max_consec_win, cur_consec)
            else:
                cur_consec = 0

        # 盈亏比
        avg_win = statistics.mean(wins) if wins else 0
        avg_loss = statistics.mean(losses) if losses else 0
        payoff_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else float("inf")

        return {
            "n": len(pnls),
            "net_pnl": round(sum(pnls), 2),
            "win_rate": round(len(wins) / len(pnls), 4),
            "max_drawdown": round(max_dd, 2),
            "sharpe_per_trade": round(sharpe_per_trade, 4),
            "sharpe_annualized": round(sharpe_annual, 2),
            "pf": round(gross_win / gross_loss, 4) if gross_loss > 0 else float("inf"),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "payoff_ratio": round(payoff_ratio, 2),
            "max_consec_wins": max_consec_win,
            "max_consec_losses": max_consec_loss,
            "final_equity": round(cum, 2),
            "curve": curve,
        }

    all_stats = equity_curve(all_sorted)
    confirmed_stats = equity_curve(confirmed_sorted)

    # 对比表
    comparison = {}
    for key in ["n", "net_pnl", "win_rate", "max_drawdown", "sharpe_per_trade",
                "sharpe_annualized", "pf", "avg_win", "avg_loss", "payoff_ratio",
                "max_consec_wins", "max_consec_losses"]:
        comparison[key] = {
            "all_210": all_stats.get(key),
            "confirmed_46": confirmed_stats.get(key),
            "delta": None,
        }
        if isinstance(all_stats.get(key), (int, float)) and isinstance(confirmed_stats.get(key), (int, float)):
            comparison[key]["delta"] = round(confirmed_stats.get(key) - all_stats.get(key), 2)

    # 月度分解
    monthly = defaultdict(lambda: {"all": [], "confirmed": []})
    for t in all_sorted:
        exit_dt = datetime.fromisoformat(t["exit_time"])
        month_key = f"{exit_dt.year}-{exit_dt.month:02d}"
        monthly[month_key]["all"].append(t["pnl"])
        if t["entry_type"] in ("E3_confirmed_entry", "E4_well_executed"):
            monthly[month_key]["confirmed"].append(t["pnl"])

    monthly_summary = {}
    for month, pnls in sorted(monthly.items()):
        monthly_summary[month] = {
            "all_n": len(pnls["all"]),
            "all_pnl": round(sum(pnls["all"]), 2),
            "confirmed_n": len(pnls["confirmed"]),
            "confirmed_pnl": round(sum(pnls["confirmed"]), 2),
        }

    return {
        "all_trades": {k: v for k, v in all_stats.items() if k != "curve"},
        "confirmed_only": {k: v for k, v in confirmed_stats.items() if k != "curve"},
        "comparison": comparison,
        "monthly": monthly_summary,
        "all_curve": all_stats.get("curve", []),
        "confirmed_curve": confirmed_stats.get("curve", []),
    }

# ───────────────────────── 主流程 ─────────────────────────

def main():
    print("=" * 70)
    print("  入场时机三组验证实验")
    print("=" * 70)

    trades = load_trades()
    bars = load_m5_bars()
    print(f"\n加载: {len(trades)} 笔交易, {len(bars)} 根 M5 K线")
    print(f"价格数据范围: {datetime.fromtimestamp(bars[0]['ts'], tz=timezone.utc)} ~ {datetime.fromtimestamp(bars[-1]['ts'], tz=timezone.utc)}")

    # ── 实验1 ──
    print("\n" + "=" * 70)
    print("  实验1: E3/E4 成功因子拆解")
    print("=" * 70)

    exp1, confirmed = experiment1(trades)
    c = exp1["combined"]
    print(f"\n确认入场(E3+E4) {c['n']}笔:")
    print(f"  净盈亏: ${c['net_pnl']} | 胜率: {c['win_rate']*100:.1f}% | 均MFE: ${c['avg_mfe']} | 均MAE: ${c['avg_mae']}")
    print(f"  均持仓: {c['avg_hold_h']}h | 均MFE捕获率: {c['avg_capture']}")
    print(f"  方向: BUY {c['buy_count']} / SELL {c['sell_count']}")
    print(f"  MFE平均到达时间: {c['avg_mfe_offset_sec']}s | MAE平均到达时间: {c['avg_mae_offset_sec']}s")

    print(f"\n  E3 vs E4 关键差异:")
    print(f"    E3: MAE=${exp1['e3'].get('avg_mae')} MFE=${exp1['e3'].get('avg_mfe')} 持仓={exp1['e3'].get('avg_hold_h')}h 捕获={exp1['e3'].get('avg_capture')}")
    print(f"    E4: MAE=${exp1['e4'].get('avg_mae')} MFE=${exp1['e4'].get('avg_mfe')} 持仓={exp1['e4'].get('avg_hold_h')}h 捕获={exp1['e4'].get('avg_capture')}")
    print(f"    → {exp1['key_differences']['insight']}")

    print(f"\n  确认方式代理分类:")
    for st, s in sorted(exp1["subtypes"].items(), key=lambda x: -x[1].get("net_pnl", 0)):
        if s["n"] > 0:
            print(f"    {st}: {s['n']}笔 净${s['net_pnl']} 胜率{s['win_rate']*100:.0f}% MFE=${s['avg_mfe']} MAE=${s['avg_mae']}")

    # ── 实验2 ──
    print("\n" + "=" * 70)
    print("  实验2: 确认入场是否遗漏机会")
    print("=" * 70)

    exp2 = experiment2(trades, bars)

    for win in ["4h", "8h", "24h"]:
        w = exp2["by_window"][win]
        print(f"\n  平仓后 {win} 窗口:")
        print(f"    追踪: {w['n_tracked']}笔 (E1+E2)")
        print(f"    大趋势(>30USD): {w['n_big_trend']}笔 ({w['pct_big_trend']*100:.1f}%)")
        print(f"    中等(10-30USD): {w['n_moderate']}笔 ({w['pct_moderate']*100:.1f}%)")
        print(f"    未动(<10USD): {w['n_never_moved']}笔 ({w['pct_never_moved']*100:.1f}%)")
        print(f"    平均有利运动: ${w['avg_favorable']} | 中位: ${w['median_favorable']}")

    s = exp2["summary"]
    print(f"\n  结论: {s['verdict']}")
    print(f"  E1/E2实际亏损: ${s['anticipatory_actual_pnl']}")
    print(f"  大趋势笔数: {s['big_trend_count']}/{s['anticipatory_n']} ({s['big_trend_pct']*100:.1f}%)")
    print(f"  大趋势平均运动: ${s['big_trend_avg_move']}")
    print(f"  确认入场保守估计捕获: ${s['confirmation_estimate']}")

    print(f"\n  E1 vs E2 分解 (24h):")
    for et, d in exp2["by_entry_type"].items():
        print(f"    {et}: {d['n']}笔, 大趋势{d['big_trend']}笔, 未动{d['never_moved']}笔, 均有利${d['avg_favorable_24h']}")

    # ── 实验3 ──
    print("\n" + "=" * 70)
    print("  实验3: 模拟 E3/E4-only 资金曲线")
    print("=" * 70)

    exp3 = experiment3(trades)

    comp = exp3["comparison"]
    print(f"\n  {'指标':<22} {'全量210笔':<18} {'确认46笔':<18} {'差值':<12}")
    print(f"  {'-'*70}")
    for key in ["n", "net_pnl", "win_rate", "pf", "max_drawdown", "sharpe_annualized",
                "avg_win", "avg_loss", "payoff_ratio", "max_consec_losses"]:
        a = comp[key]["all_210"]
        c_val = comp[key]["confirmed_46"]
        d = comp[key]["delta"]
        if isinstance(a, float):
            print(f"  {key:<22} {a:<18.2f} {c_val:<18.2f} {d:+.2f}" if d is not None else f"  {key:<22} {a:<18.2f} {c_val:<18.2f}")
        else:
            print(f"  {key:<22} {a:<18} {c_val:<18} {d}" if d is not None else f"  {key:<22} {a:<18} {c_val:<18}")

    print(f"\n  月度分解:")
    print(f"  {'月份':<10} {'全量笔数':<8} {'全量P&L':<12} {'确认笔数':<8} {'确认P&L':<12}")
    for month, m in exp3["monthly"].items():
        print(f"  {month:<10} {m['all_n']:<8} ${m['all_pnl']:<10.2f} {m['confirmed_n']:<8} ${m['confirmed_pnl']:<10.2f}")

    # ── 保存报告 ──
    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_source": "mt5_raw/trade_path.json + entry_timing_report.json + XAUUSD_M5.csv",
        "experiment1": exp1,
        "experiment2": exp2,
        "experiment3": {k: v for k, v in exp3.items() if k not in ("all_curve", "confirmed_curve")},
    }

    with open(RAW / "entry_experiments_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: mt5_raw/entry_experiments_report.json")

if __name__ == "__main__":
    main()
