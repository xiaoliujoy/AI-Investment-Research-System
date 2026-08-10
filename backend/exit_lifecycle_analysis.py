#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""盈利交易生命周期分析 (Exit Lifecycle Analysis)

对 210 笔 MT5 XAUUSD 交易做离场策略回测，验证：
1. 盈利交易的最大浮盈 vs 实际收益（giveback 分析）
2. 四种离场策略模拟对比
3. 最优策略识别

离场策略：
  Baseline: 实际交易结果
  A: 固定止盈 (3R) + 初始止损 (1R)
  B: 盈利2R后保本 + 趋势跟踪退出
  C: ATR(14)×2 跟踪止损
  D: Donchian(10) 结构跟踪止损
"""

import json, csv, bisect, statistics, math
from datetime import datetime, timezone
from collections import defaultdict

BASE = "mt5_raw"
MAX_HOLD_BARS = 576  # 48h of M5 (576 * 5min = 2880min)
ATR_PERIOD = 14
ATR_MULT = 2.0
DONCHIAN_N = 10

# ============================================================
# Data Loading
# ============================================================

def load_trades():
    with open(f"{BASE}/trade_path.json", encoding="utf-8") as f:
        return json.load(f)

def load_entry_types():
    with open(f"{BASE}/entry_timing_report.json", encoding="utf-8") as f:
        return json.load(f)

def load_m5_bars():
    """Load M5 bars, filter to 2026 trade period."""
    bars = []
    with open(f"{BASE}/XAUUSD_M5.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ts = int(row["time"])
            # 2026-03-01 to 2026-08-31 (Unix timestamps)
            if ts < 1772500000 or ts > 1788100000:
                continue
            bars.append({
                "ts": ts,
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": int(row.get("tick_volume", 0) or 0),
            })
    bars.sort(key=lambda b: b["ts"])
    return bars

def iso_to_ts(iso_str):
    """Convert ISO datetime string to Unix timestamp (UTC)."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())

# ============================================================
# Part 1: Lifecycle Analysis (using trade data fields directly)
# ============================================================

def lifecycle_analysis(trades_data, entry_report):
    """Analyze profitable trade lifecycle: MFE vs actual P&L vs giveback."""
    trades = trades_data["trades"]
    type_map = {t["trade_id"]: t["entry_type"] for t in entry_report["trades"]}

    # Calculate R from trades with sl_trigger_price
    stop_distances = []
    for t in trades:
        if t.get("sl_trigger_price") and t["direction"] == "BUY":
            d = t["entry_price"] - t["sl_trigger_price"]
            if d > 0:
                stop_distances.append(d)
        elif t.get("sl_trigger_price") and t["direction"] == "SELL":
            d = t["sl_trigger_price"] - t["entry_price"]
            if d > 0:
                stop_distances.append(d)

    median_r = statistics.median(stop_distances) if stop_distances else 15.0
    mean_r = statistics.mean(stop_distances) if stop_distances else 15.0

    results = {
        "r_estimation": {
            "n_trades_with_sl": len(stop_distances),
            "median_r_usd": round(median_r, 2),
            "mean_r_usd": round(mean_r, 2),
            "min_r": round(min(stop_distances), 2) if stop_distances else 0,
            "max_r": round(max(stop_distances), 2) if stop_distances else 0,
        },
        "overall": {},
        "by_outcome": {},
        "by_entry_type": {},
        "by_archetype": {},
        "timing": {},
    }

    # Overall stats
    all_mfe = [t["mfe_usd"] for t in trades]
    all_pnl = [t["pnl"] for t in trades]
    all_mae = [t["mae_usd"] for t in trades]
    total_mfe = sum(all_mfe)
    total_pnl = sum(all_pnl)
    total_mae = sum(all_mae)

    # Giveback analysis
    winners = [t for t in trades if t["pnl"] > 0]
    losers_with_mfe = [t for t in trades if t["pnl"] <= 0 and t["mfe_usd"] > 5]
    pure_losers = [t for t in trades if t["pnl"] <= 0 and t["mfe_usd"] <= 5]

    def group_stats(group, label):
        if not group:
            return {"label": label, "n": 0}
        mfes = [t["mfe_usd"] for t in group]
        pnls = [t["pnl"] for t in group]
        maes = [t["mae_usd"] for t in group]
        givebacks = [t["mfe_usd"] - t["pnl"] for t in group if t["mfe_usd"] > 0]
        capture_ratios = [t["pnl"] / t["mfe_usd"] for t in group if t["mfe_usd"] > 0]
        return {
            "label": label,
            "n": len(group),
            "total_mfe": round(sum(mfes), 2),
            "total_pnl": round(sum(pnls), 2),
            "total_mae": round(sum(maes), 2),
            "avg_mfe": round(statistics.mean(mfes), 2),
            "median_mfe": round(statistics.median(mfes), 2),
            "avg_pnl": round(statistics.mean(pnls), 2),
            "median_pnl": round(statistics.median(pnls), 2),
            "avg_mae": round(statistics.mean(maes), 2),
            "total_giveback": round(sum(givebacks), 2) if givebacks else 0,
            "avg_giveback": round(statistics.mean(givebacks), 2) if givebacks else 0,
            "median_capture_ratio": round(statistics.median(capture_ratios), 4) if capture_ratios else 0,
            "mean_capture_ratio": round(statistics.mean(capture_ratios), 4) if capture_ratios else 0,
        }

    results["overall"] = group_stats(trades, "ALL")
    results["by_outcome"]["winners"] = group_stats(winners, "P&L > 0")
    results["by_outcome"]["losers_with_mfe"] = group_stats(losers_with_mfe, "P&L <= 0 but MFE > $5 (profit turned to loss)")
    results["by_outcome"]["pure_losers"] = group_stats(pure_losers, "P&L <= 0 and MFE <= $5 (never had chance)")

    # By entry type
    for et in ["E1_anticipatory_fail", "E2_anticipatory_suffered", "E3_confirmed_entry", "E4_well_executed"]:
        group = [t for t in trades if type_map.get(t["trade_id"]) == et]
        results["by_entry_type"][et] = group_stats(group, et)

    # By archetype
    for arch in ["A_entry_wrong", "B_stop_too_tight", "C_exit_management", "D_captured"]:
        group = [t for t in trades if t.get("path_archetype") == arch]
        results["by_archetype"][arch] = group_stats(group, arch)

    # Timing analysis
    mfe_before_mae = 0
    mae_before_mfe = 0
    concurrent = 0
    mfe_times = []
    mae_times = []
    mfe_to_exit_times = []

    for t in trades:
        mfe_off = t.get("mfe_offset_sec", 0)
        mae_off = t.get("mae_offset_sec", 0)

        # Normalize negative offsets to 0
        mfe_off_norm = max(mfe_off, 0)
        mae_off_norm = max(mae_off, 0)

        if mfe_off_norm < mae_off_norm:
            mfe_before_mae += 1
        elif mae_off_norm < mfe_off_norm:
            mae_before_mfe += 1
        else:
            concurrent += 1

        mfe_times.append(mfe_off_norm)
        mae_times.append(mae_off_norm)
        mfe_to_exit = t.get("holding_sec", 0) - mfe_off_norm
        mfe_to_exit_times.append(max(mfe_to_exit, 0))

    results["timing"] = {
        "mfe_before_mae": mfe_before_mae,
        "mae_before_mfe": mae_before_mfe,
        "concurrent": concurrent,
        "avg_time_to_mfe_min": round(statistics.mean(mfe_times) / 60, 1) if mfe_times else 0,
        "median_time_to_mfe_min": round(statistics.median(mfe_times) / 60, 1) if mfe_times else 0,
        "avg_time_to_mae_min": round(statistics.mean(mae_times) / 60, 1) if mae_times else 0,
        "median_time_to_mae_min": round(statistics.median(mae_times) / 60, 1) if mae_times else 0,
        "avg_mfe_to_exit_min": round(statistics.mean(mfe_to_exit_times) / 60, 1) if mfe_to_exit_times else 0,
        "median_mfe_to_exit_min": round(statistics.median(mfe_to_exit_times) / 60, 1) if mfe_to_exit_times else 0,
    }

    return results, median_r

# ============================================================
# Part 2: Exit Strategy Backtest (bar-by-bar simulation)
# ============================================================

def find_bar_index(bar_ts_list, target_ts):
    """Find the index of the first bar at or after target_ts."""
    idx = bisect.bisect_left(bar_ts_list, target_ts)
    return idx

def calc_atr(bars, idx, period=ATR_PERIOD):
    """Calculate ATR at bar idx using previous `period` bars."""
    if idx < period:
        return 5.0  # default
    trs = []
    for i in range(idx - period, idx):
        h, l = bars[i]["h"], bars[i]["l"]
        prev_c = bars[i - 1]["c"] if i > 0 else bars[i]["o"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 5.0

def simulate_strategy_a(bars, bar_ts_list, trade, entry_ts, r_usd):
    """Strategy A: Fixed TP at 3R, stop at 1R."""
    direction = trade["direction"]
    entry = trade["entry_price"]
    tp = 3 * r_usd
    sl = r_usd
    start_idx = find_bar_index(bar_ts_list, entry_ts)
    if start_idx >= len(bars):
        return None

    for i in range(start_idx, min(start_idx + MAX_HOLD_BARS, len(bars))):
        bar = bars[i]
        if direction == "BUY":
            # Check stop first (conservative)
            if entry - bar["l"] >= sl:
                return {"pnl": -sl, "exit_bar": i, "reason": "stop", "bars_held": i - start_idx + 1}
            if bar["h"] - entry >= tp:
                return {"pnl": tp, "exit_bar": i, "reason": "tp", "bars_held": i - start_idx + 1}
        else:
            if bar["h"] - entry >= sl:
                return {"pnl": -sl, "exit_bar": i, "reason": "stop", "bars_held": i - start_idx + 1}
            if entry - bar["l"] >= tp:
                return {"pnl": tp, "exit_bar": i, "reason": "tp", "bars_held": i - start_idx + 1}

    # Neither hit, use last available price
    last_idx = min(start_idx + MAX_HOLD_BARS - 1, len(bars) - 1)
    last = bars[last_idx]
    pnl = (last["c"] - entry) if direction == "BUY" else (entry - last["c"])
    return {"pnl": round(pnl, 2), "exit_bar": last_idx, "reason": "timeout", "bars_held": last_idx - start_idx + 1}

def simulate_strategy_b(bars, bar_ts_list, trade, entry_ts, r_usd):
    """Strategy B: BE protect after 2R + swing trail."""
    direction = trade["direction"]
    entry = trade["entry_price"]
    be_trigger = 2 * r_usd
    initial_sl = r_usd
    start_idx = find_bar_index(bar_ts_list, entry_ts)
    if start_idx >= len(bars):
        return None

    stop = initial_sl  # distance from entry
    be_activated = False
    trail_start_idx = None
    max_favorable = 0

    for i in range(start_idx, min(start_idx + MAX_HOLD_BARS, len(bars))):
        bar = bars[i]
        if direction == "BUY":
            fav = bar["h"] - entry
            adv = entry - bar["l"]
            if fav > max_favorable:
                max_favorable = fav
            # Check stop
            if adv >= stop:
                pnl = -stop if not be_activated else max(-stop, 0)
                # If BE activated, stop is at entry (stop=0)
                pnl = -stop if not be_activated else 0
                return {"pnl": round(pnl, 2), "exit_bar": i, "reason": "stop", "bars_held": i - start_idx + 1,
                        "be_activated": be_activated}
            # Check BE trigger
            if not be_activated and fav >= be_trigger:
                be_activated = True
                stop = 0  # move to breakeven
                trail_start_idx = i
            # After BE: trail using Donchian
            if be_activated and i - trail_start_idx >= DONCHIAN_N:
                lookback = bars[i - DONCHIAN_N:i]
                lowest = min(b["l"] for b in lookback)
                new_stop = entry - lowest  # distance from entry (negative = above entry = profit locked)
                if new_stop < stop:
                    stop = new_stop
        else:
            fav = entry - bar["l"]
            adv = bar["h"] - entry
            if fav > max_favorable:
                max_favorable = fav
            if adv >= stop:
                pnl = -stop if not be_activated else 0
                return {"pnl": round(pnl, 2), "exit_bar": i, "reason": "stop", "bars_held": i - start_idx + 1,
                        "be_activated": be_activated}
            if not be_activated and fav >= be_trigger:
                be_activated = True
                stop = 0
                trail_start_idx = i
            if be_activated and i - trail_start_idx >= DONCHIAN_N:
                lookback = bars[i - DONCHIAN_N:i]
                highest = max(b["h"] for b in lookback)
                new_stop = highest - entry
                if new_stop < stop:
                    stop = new_stop

    last_idx = min(start_idx + MAX_HOLD_BARS - 1, len(bars) - 1)
    last = bars[last_idx]
    pnl = (last["c"] - entry) if direction == "BUY" else (entry - last["c"])
    return {"pnl": round(pnl, 2), "exit_bar": last_idx, "reason": "timeout", "bars_held": last_idx - start_idx + 1,
            "be_activated": be_activated}

def simulate_strategy_c(bars, bar_ts_list, trade, entry_ts):
    """Strategy C: ATR(14)×2 trailing stop."""
    direction = trade["direction"]
    entry = trade["entry_price"]
    start_idx = find_bar_index(bar_ts_list, entry_ts)
    if start_idx >= len(bars):
        return None

    atr = calc_atr(bars, start_idx)
    stop_dist = atr * ATR_MULT
    if stop_dist < 1:
        stop_dist = 5.0

    if direction == "BUY":
        stop = entry - stop_dist
        max_price = entry
    else:
        stop = entry + stop_dist
        min_price = entry

    for i in range(start_idx, min(start_idx + MAX_HOLD_BARS, len(bars))):
        bar = bars[i]
        if direction == "BUY":
            if bar["l"] <= stop:
                return {"pnl": round(stop - entry, 2), "exit_bar": i, "reason": "trail_stop",
                        "bars_held": i - start_idx + 1, "atr": round(atr, 2)}
            if bar["h"] > max_price:
                max_price = bar["h"]
                new_stop = max_price - stop_dist
                if new_stop > stop:
                    stop = new_stop
        else:
            if bar["h"] >= stop:
                return {"pnl": round(entry - stop, 2), "exit_bar": i, "reason": "trail_stop",
                        "bars_held": i - start_idx + 1, "atr": round(atr, 2)}
            if bar["l"] < min_price:
                min_price = bar["l"]
                new_stop = min_price + stop_dist
                if new_stop < stop:
                    stop = new_stop

    last_idx = min(start_idx + MAX_HOLD_BARS - 1, len(bars) - 1)
    last = bars[last_idx]
    pnl = (last["c"] - entry) if direction == "BUY" else (entry - last["c"])
    return {"pnl": round(pnl, 2), "exit_bar": last_idx, "reason": "timeout", "bars_held": last_idx - start_idx + 1,
            "atr": round(atr, 2)}

def simulate_strategy_d(bars, bar_ts_list, trade, entry_ts):
    """Strategy D: Donchian(N) trailing stop from entry."""
    direction = trade["direction"]
    entry = trade["entry_price"]
    start_idx = find_bar_index(bar_ts_list, entry_ts)
    if start_idx >= len(bars):
        return None

    # Initial stop: use first N bars to establish
    initial_stop_dist = 20.0  # $20 default for first N bars

    if direction == "BUY":
        stop = entry - initial_stop_dist
    else:
        stop = entry + initial_stop_dist

    for i in range(start_idx, min(start_idx + MAX_HOLD_BARS, len(bars))):
        bar = bars[i]
        # After N bars, switch to Donchian trailing
        bars_since_entry = i - start_idx
        if bars_since_entry >= DONCHIAN_N:
            lookback_start = max(start_idx, i - DONCHIAN_N)
            lookback = bars[lookback_start:i]
            if direction == "BUY":
                lowest = min(b["l"] for b in lookback)
                new_stop = lowest
                if new_stop > stop:
                    stop = new_stop
            else:
                highest = max(b["h"] for b in lookback)
                new_stop = highest
                if new_stop < stop:
                    stop = new_stop

        if direction == "BUY":
            if bar["l"] <= stop:
                return {"pnl": round(stop - entry, 2), "exit_bar": i, "reason": "donchian_stop",
                        "bars_held": i - start_idx + 1}
        else:
            if bar["h"] >= stop:
                return {"pnl": round(entry - stop, 2), "exit_bar": i, "reason": "donchian_stop",
                        "bars_held": i - start_idx + 1}

    last_idx = min(start_idx + MAX_HOLD_BARS - 1, len(bars) - 1)
    last = bars[last_idx]
    pnl = (last["c"] - entry) if direction == "BUY" else (entry - last["c"])
    return {"pnl": round(pnl, 2), "exit_bar": last_idx, "reason": "timeout", "bars_held": last_idx - start_idx + 1}

def calc_metrics(results_list, label, mfe_list=None):
    """Calculate summary metrics for a strategy."""
    pnls = [r["pnl"] for r in results_list if r is not None]
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    net = sum(pnls)
    cumulative = []
    running = 0
    for p in pnls:
        running += p
        cumulative.append(running)
    max_dd = 0
    peak = float("-inf")
    for v in cumulative:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd

    # Sharpe (per-trade, annualized assuming ~200 trades/year)
    if len(pnls) > 1 and statistics.pstdev(pnls) > 0:
        sharpe = (statistics.mean(pnls) / statistics.pstdev(pnls)) * math.sqrt(200)
    else:
        sharpe = 0

    # MFE capture (for trades where we have MFE)
    capture_ratios = []
    if mfe_list:
        for r, mfe in zip(results_list, mfe_list):
            if r and mfe > 5:
                capture_ratios.append(r["pnl"] / mfe)

    return {
        "label": label,
        "n": n,
        "net_pnl": round(net, 2),
        "win_rate_pct": round(len(wins) / n * 100, 1),
        "pf": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_pnl": round(statistics.mean(pnls), 2),
        "median_pnl": round(statistics.median(pnls), 2),
        "max_dd": round(max_dd, 2),
        "sharpe_annualized": round(sharpe, 2),
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "avg_mfe_capture": round(statistics.mean(capture_ratios), 4) if capture_ratios else None,
        "median_mfe_capture": round(statistics.median(capture_ratios), 4) if capture_ratios else None,
    }

# ============================================================
# Simplified exit comparison (when M5 data unavailable)
# ============================================================

def simplified_exit_comparison(trades, r_usd):
    """Simplified exit strategy comparison using MFE/MAE/timing."""
    tp = 3 * r_usd
    sl = r_usd
    be_trigger = 2 * r_usd

    results = {"A_fixed_3r": [], "B_be_protect": [], "baseline": []}

    for t in trades:
        mfe = t["mfe_usd"]
        mae = t["mae_usd"]
        pnl = t["pnl"]
        mfe_off = max(t.get("mfe_offset_sec", 0), 0)
        mae_off = max(t.get("mae_offset_sec", 0), 0)
        mfe_first = mfe_off <= mae_off

        # Baseline
        results["baseline"].append(pnl)

        # Strategy A: Fixed 3R TP, 1R stop
        if mae >= sl and not mfe_first:
            # Stop hit before TP
            results["A_fixed_3r"].append(-sl)
        elif mae >= sl and mfe_first and mfe >= tp:
            # MFE reached TP before MAE hit stop
            results["A_fixed_3r"].append(tp)
        elif mae >= sl and mfe_first and mfe < tp:
            # MFE first but didn't reach TP, then stop hit
            results["A_fixed_3r"].append(-sl)
        elif mfe >= tp:
            # TP hit, stop never hit
            results["A_fixed_3r"].append(tp)
        else:
            # Neither hit
            results["A_fixed_3r"].append(pnl)

        # Strategy B: BE protect after 2R
        if mfe >= be_trigger:
            # BE activated. Worst case: exit at 0 (breakeven)
            if pnl < 0:
                results["B_be_protect"].append(0)  # saved by BE
            else:
                results["B_be_protect"].append(pnl)  # already profitable
        else:
            # No BE protection
            results["B_be_protect"].append(pnl)

    summary = {}
    for name, pnls in results.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        net = sum(pnls)
        summary[name] = {
            "n": len(pnls),
            "net_pnl": round(net, 2),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "pf": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
            "avg_pnl": round(statistics.mean(pnls), 2) if pnls else 0,
        }

    return summary

# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("  盈利交易生命周期分析 (Exit Lifecycle Analysis)")
    print("=" * 70)

    # Load data
    trades_data = load_trades()
    entry_report = load_entry_types()
    trades = trades_data["trades"]

    print(f"\n加载 {len(trades)} 笔交易")

    # Part 1: Lifecycle Analysis
    print("\n" + "=" * 70)
    print("  Part 1: 盈利交易生命周期")
    print("=" * 70)

    lifecycle, r_usd = lifecycle_analysis(trades_data, entry_report)

    print(f"\nR 估算 (来自 {lifecycle['r_estimation']['n_trades_with_sl']} 笔有止损单的交易):")
    print(f"  中位 R = ${lifecycle['r_estimation']['median_r_usd']}")
    print(f"  均值 R = ${lifecycle['r_estimation']['mean_r_usd']}")
    print(f"  范围: ${lifecycle['r_estimation']['min_r']} ~ ${lifecycle['r_estimation']['max_r']}")

    # Use median R for strategies
    r = lifecycle["r_estimation"]["median_r_usd"]
    print(f"\n  → 采用 R = ${r} 进行策略模拟")

    print(f"\n--- 总体 ---")
    o = lifecycle["overall"]
    print(f"  总 MFE (曾给的有利波动): ${o['total_mfe']}")
    print(f"  总 P&L (实际实现): ${o['total_pnl']}")
    print(f"  总 MAE (不利波动): ${o['total_mae']}")
    print(f"  MFE 捕获率(中位): {o['median_capture_ratio']}")
    print(f"  MFE 捕获率(均值): {o['mean_capture_ratio']}")

    print(f"\n--- 按交易结果分类 ---")
    for key, label in [("winners", "盈利交易"), ("losers_with_mfe", "盈利变亏损"), ("pure_losers", "纯亏损(从未盈利)")]:
        g = lifecycle["by_outcome"][key]
        if g["n"] == 0:
            continue
        print(f"\n  [{label}] N={g['n']}")
        print(f"    总MFE=${g['total_mfe']}, 总P&L=${g['total_pnl']}")
        print(f"    均MFE=${g['avg_mfe']}, 均P&L=${g['avg_pnl']}")
        print(f"    总giveback=${g['total_giveback']}, 均giveback=${g['avg_giveback']}")
        print(f"    MFE捕获率(中位)={g['median_capture_ratio']}")

    print(f"\n--- 按入场类型 ---")
    for et, g in lifecycle["by_entry_type"].items():
        if g["n"] == 0:
            continue
        print(f"  {et}: N={g['n']}, MFE=${g['total_mfe']}, P&L=${g['total_pnl']}, 捕获率={g['median_capture_ratio']}")

    print(f"\n--- 按路径原型 ---")
    for arch, g in lifecycle["by_archetype"].items():
        if g["n"] == 0:
            continue
        print(f"  {arch}: N={g['n']}, MFE=${g['total_mfe']}, P&L=${g['total_pnl']}, 捕获率={g['median_capture_ratio']}")

    print(f"\n--- 时序分析 ---")
    t = lifecycle["timing"]
    print(f"  MFE先于MAE: {t['mfe_before_mae']}笔 ({t['mfe_before_mae']/len(trades)*100:.1f}%)")
    print(f"  MAE先于MFE: {t['mae_before_mfe']}笔 ({t['mae_before_mfe']/len(trades)*100:.1f}%)")
    print(f"  同时: {t['concurrent']}笔")
    print(f"  MFE到达时间(中位): {t['median_time_to_mfe_min']}分钟")
    print(f"  MAE到达时间(中位): {t['median_time_to_mae_min']}分钟")
    print(f"  MFE到退出时间(中位): {t['median_mfe_to_exit_min']}分钟")

    # Part 2: Try M5 bar-by-bar backtest
    print("\n" + "=" * 70)
    print("  Part 2: 离场策略回测")
    print("=" * 70)

    bars = load_m5_bars()
    bar_ts_list = [b["ts"] for b in bars]
    print(f"\nM5数据: {len(bars)} 根bars")
    if bars:
        print(f"  时间范围: {datetime.fromtimestamp(bars[0]['ts'], tz=timezone.utc).isoformat()}")
        print(f"           ~ {datetime.fromtimestamp(bars[-1]['ts'], tz=timezone.utc).isoformat()}")
        print(f"  价格范围: ${min(b['l'] for b in bars):.2f} ~ ${max(b['h'] for b in bars):.2f}")

    # Check if M5 data matches trades
    matched = 0
    sample_prices = []
    for t in trades[:5]:
        entry_ts = iso_to_ts(t["entry_time"])
        idx = find_bar_index(bar_ts_list, entry_ts)
        if idx < len(bars):
            bar = bars[idx]
            price_diff = abs(bar["o"] - t["entry_price"])
            matched += 1 if price_diff < 50 else 0
            sample_prices.append({
                "trade": t["trade_id"],
                "entry_time": t["entry_time"],
                "entry_price": t["entry_price"],
                "bar_ts": bar["ts"],
                "bar_open": bar["o"],
                "diff": round(price_diff, 2),
            })

    m5_matches = all(s["diff"] < 50 for s in sample_prices) if sample_prices else False
    print(f"\n  样本匹配: {json.dumps(sample_prices[:3], indent=2)}")
    print(f"  M5数据匹配: {'YES' if m5_matches else 'NO'}")

    if m5_matches:
        # Full bar-by-bar backtest
        print("\n  → 使用 M5 bar-by-bar 回测")

        baseline_results = []
        strat_a_results = []
        strat_b_results = []
        strat_c_results = []
        strat_d_results = []
        mfe_list = []

        for t in trades:
            entry_ts = iso_to_ts(t["entry_time"])
            mfe_list.append(t["mfe_usd"])

            # Baseline
            baseline_results.append({"pnl": t["pnl"], "exit_bar": 0, "reason": "actual", "bars_held": 0})

            # Strategy A
            ra = simulate_strategy_a(bars, bar_ts_list, t, entry_ts, r)
            strat_a_results.append(ra)

            # Strategy B
            rb = simulate_strategy_b(bars, bar_ts_list, t, entry_ts, r)
            strat_b_results.append(rb)

            # Strategy C
            rc = simulate_strategy_c(bars, bar_ts_list, t, entry_ts)
            strat_c_results.append(rc)

            # Strategy D
            rd = simulate_strategy_d(bars, bar_ts_list, t, entry_ts)
            strat_d_results.append(rd)

        # Calculate metrics
        metrics = {
            "baseline": calc_metrics(baseline_results, "Baseline (实际)", mfe_list),
            "A_fixed_3r": calc_metrics(strat_a_results, f"A: 固定3R止盈 (TP=${3*r:.0f}, SL=${r:.0f})", mfe_list),
            "B_be_protect": calc_metrics(strat_b_results, f"B: 2R保本+趋势跟踪", mfe_list),
            "C_atr_trail": calc_metrics(strat_c_results, f"C: ATR(14)×{ATR_MULT}跟踪", mfe_list),
            "D_donchian": calc_metrics(strat_d_results, f"D: Donchian({DONCHIAN_N})跟踪", mfe_list),
        }

        # Also test multiple TP levels for Strategy A
        tp_metrics = {}
        for tp_r in [1, 2, 3, 5]:
            tp_usd = tp_r * r
            tp_results = []
            for t in trades:
                entry_ts = iso_to_ts(t["entry_time"])
                res = simulate_strategy_a(bars, bar_ts_list, t, entry_ts, r)
                # Override: use different TP
                # Actually re-simulate with custom TP
                direction = t["direction"]
                entry = t["entry_price"]
                sl = r
                tp = tp_usd
                start_idx = find_bar_index(bar_ts_list, entry_ts)
                if start_idx >= len(bars):
                    tp_results.append({"pnl": t["pnl"], "reason": "no_data"})
                    continue
                exited = False
                for i in range(start_idx, min(start_idx + MAX_HOLD_BARS, len(bars))):
                    bar = bars[i]
                    if direction == "BUY":
                        if entry - bar["l"] >= sl:
                            tp_results.append({"pnl": -sl, "reason": "stop"})
                            exited = True
                            break
                        if bar["h"] - entry >= tp:
                            tp_results.append({"pnl": tp, "reason": "tp"})
                            exited = True
                            break
                    else:
                        if bar["h"] - entry >= sl:
                            tp_results.append({"pnl": -sl, "reason": "stop"})
                            exited = True
                            break
                        if entry - bar["l"] >= tp:
                            tp_results.append({"pnl": tp, "reason": "tp"})
                            exited = True
                            break
                if not exited:
                    last_idx = min(start_idx + MAX_HOLD_BARS - 1, len(bars) - 1)
                    last = bars[last_idx]
                    pnl = (last["c"] - entry) if direction == "BUY" else (entry - last["c"])
                    tp_results.append({"pnl": round(pnl, 2), "reason": "timeout"})
            tp_metrics[f"{tp_r}R"] = calc_metrics(tp_results, f"TP={tp_r}R (${tp_usd:.0f})", mfe_list)

        # Also test multiple ATR multipliers for Strategy C
        atr_metrics = {}
        for mult in [1.0, 1.5, 2.0, 3.0]:
            atr_res = []
            for t in trades:
                entry_ts = iso_to_ts(t["entry_time"])
                start_idx = find_bar_index(bar_ts_list, entry_ts)
                if start_idx >= len(bars):
                    atr_res.append({"pnl": t["pnl"], "reason": "no_data"})
                    continue
                direction = t["direction"]
                entry = t["entry_price"]
                atr = calc_atr(bars, start_idx)
                stop_dist = atr * mult
                if stop_dist < 1:
                    stop_dist = 5.0
                if direction == "BUY":
                    stop = entry - stop_dist
                    max_price = entry
                else:
                    stop = entry + stop_dist
                    min_price = entry
                exited = False
                for i in range(start_idx, min(start_idx + MAX_HOLD_BARS, len(bars))):
                    bar = bars[i]
                    if direction == "BUY":
                        if bar["l"] <= stop:
                            atr_res.append({"pnl": round(stop - entry, 2), "reason": "trail"})
                            exited = True
                            break
                        if bar["h"] > max_price:
                            max_price = bar["h"]
                            new_stop = max_price - stop_dist
                            if new_stop > stop:
                                stop = new_stop
                    else:
                        if bar["h"] >= stop:
                            atr_res.append({"pnl": round(entry - stop, 2), "reason": "trail"})
                            exited = True
                            break
                        if bar["l"] < min_price:
                            min_price = bar["l"]
                            new_stop = min_price + stop_dist
                            if new_stop < stop:
                                stop = new_stop
                if not exited:
                    last_idx = min(start_idx + MAX_HOLD_BARS - 1, len(bars) - 1)
                    last = bars[last_idx]
                    pnl = (last["c"] - entry) if direction == "BUY" else (entry - last["c"])
                    atr_res.append({"pnl": round(pnl, 2), "reason": "timeout"})
            atr_metrics[f"ATR×{mult}"] = calc_metrics(atr_res, f"ATR×{mult}", mfe_list)

        backtest_type = "full_m5"

    else:
        # Fallback: simplified comparison
        print("\n  → M5数据不匹配，使用简化回测 (MFE/MAE 时序)")
        simplified = simplified_exit_comparison(trades, r)
        metrics = {}
        for name, m in simplified.items():
            metrics[name] = {
                "label": name,
                "n": m["n"],
                "net_pnl": m["net_pnl"],
                "win_rate_pct": m["win_rate_pct"],
                "pf": m["pf"],
                "avg_pnl": m["avg_pnl"],
                "median_pnl": 0,
                "max_dd": 0,
                "sharpe_annualized": 0,
                "gross_win": 0,
                "gross_loss": 0,
                "avg_mfe_capture": None,
                "median_mfe_capture": None,
            }
        tp_metrics = {}
        atr_metrics = {}
        backtest_type = "simplified"

    # Print comparison table
    print(f"\n--- 策略对比 ({'完整M5回测' if backtest_type == 'full_m5' else '简化回测'}) ---")
    print(f"{'策略':<30} {'N':>4} {'净P&L':>10} {'胜率%':>7} {'PF':>6} {'均P&L':>8} {'最大回撤':>10} {'Sharpe':>7}")
    print("-" * 90)
    for key, m in metrics.items():
        print(f"{m['label']:<30} {m['n']:>4} ${m['net_pnl']:>8.2f} {m['win_rate_pct']:>6.1f}% {m['pf']:>6} ${m['avg_pnl']:>7.2f} ${m['max_dd']:>8.2f} {m['sharpe_annualized']:>7.2f}")

    if tp_metrics:
        print(f"\n--- 策略A 敏感性 (不同止盈倍数) ---")
        print(f"{'止盈':<15} {'净P&L':>10} {'胜率%':>7} {'PF':>6} {'均P&L':>8} {'MFE捕获率':>10}")
        print("-" * 65)
        for key, m in tp_metrics.items():
            cap = f"{m['avg_mfe_capture']:.4f}" if m.get("avg_mfe_capture") is not None else "N/A"
            print(f"{m['label']:<15} ${m['net_pnl']:>8.2f} {m['win_rate_pct']:>6.1f}% {m['pf']:>6} ${m['avg_pnl']:>7.2f} {cap:>10}")

    if atr_metrics:
        print(f"\n--- 策略C 敏感性 (不同ATR倍数) ---")
        print(f"{'ATR倍数':<15} {'净P&L':>10} {'胜率%':>7} {'PF':>6} {'均P&L':>8} {'最大回撤':>10} {'MFE捕获率':>10}")
        print("-" * 80)
        for key, m in atr_metrics.items():
            cap = f"{m['avg_mfe_capture']:.4f}" if m.get("avg_mfe_capture") is not None else "N/A"
            print(f"{m['label']:<15} ${m['net_pnl']:>8.2f} {m['win_rate_pct']:>6.1f}% {m['pf']:>6} ${m['avg_pnl']:>7.2f} ${m['max_dd']:>8.2f} {cap:>10}")

    # By entry type breakdown for best strategy
    if backtest_type == "full_m5":
        print(f"\n--- 按入场类型 × 策略对比 ---")
        type_map = {t["trade_id"]: t["entry_type"] for t in entry_report["trades"]}
        for et in ["E1_anticipatory_fail", "E2_anticipatory_suffered", "E3_confirmed_entry", "E4_well_executed"]:
            indices = [i for i, t in enumerate(trades) if type_map.get(t["trade_id"]) == et]
            if not indices:
                continue
            print(f"\n  [{et}] N={len(indices)}")
            for name, results_list in [("Baseline", baseline_results), ("A_3R", strat_a_results),
                                        ("B_BE", strat_b_results), ("C_ATR", strat_c_results),
                                        ("D_Donch", strat_d_results)]:
                subset = [results_list[i] for i in indices if results_list[i] is not None]
                sub_mfe = [mfe_list[i] for i in indices]
                m = calc_metrics(subset, name, sub_mfe)
                print(f"    {name:<12} 净${m['net_pnl']:>8.2f} 胜率{m['win_rate_pct']:>5.1f}% PF{m['pf']:>5} 捕获{m['avg_mfe_capture'] or 'N/A'}")

    # Save report
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_trades": len(trades),
        "r_usd": r,
        "backtest_type": backtest_type,
        "lifecycle": lifecycle,
        "strategy_comparison": metrics,
        "tp_sensitivity": tp_metrics if tp_metrics else None,
        "atr_sensitivity": atr_metrics if atr_metrics else None,
    }

    if backtest_type == "full_m5":
        report["m5_data"] = {
            "n_bars": len(bars),
            "first_bar": datetime.fromtimestamp(bars[0]["ts"], tz=timezone.utc).isoformat() if bars else None,
            "last_bar": datetime.fromtimestamp(bars[-1]["ts"], tz=timezone.utc).isoformat() if bars else None,
        }

    with open(f"{BASE}/exit_lifecycle_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n报告已保存: {BASE}/exit_lifecycle_report.json")

    # Key findings
    print("\n" + "=" * 70)
    print("  关键发现")
    print("=" * 70)

    o = lifecycle["overall"]
    w = lifecycle["by_outcome"]["winners"]
    lwm = lifecycle["by_outcome"]["losers_with_mfe"]
    leaked = o['total_mfe'] - o['total_pnl']
    print(f"\n1. MFE捕获: 总MFE=${o['total_mfe']}, 实际P&L=${o['total_pnl']}, 漏掉${leaked:.2f}")
    print(f"2. 盈利交易: N={w['n']}, 均MFE=${w['avg_mfe']}, 均P&L=${w['avg_pnl']}, giveback=${w['avg_giveback']}/笔")
    print(f"3. 盈利变亏损: N={lwm['n']}, 均MFE=${lwm['avg_mfe']}, 最终P&L=${lwm['avg_pnl']}")
    tm = lifecycle["timing"]
    print(f"4. 时序: {tm['mfe_before_mae']}笔MFE先到({tm['mfe_before_mae']/len(trades)*100:.0f}%), MFE中位到达{tm['median_time_to_mfe_min']}分钟")

    if backtest_type == "full_m5":
        base = metrics["baseline"]
        best = max(metrics.values(), key=lambda m: m["net_pnl"])
        print(f"\n5. 策略对比: Baseline ${base['net_pnl']} → 最佳策略 {best['label']} ${best['net_pnl']}")

if __name__ == "__main__":
    main()
