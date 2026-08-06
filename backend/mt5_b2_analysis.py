#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B2 行为统计分析层 (Trader OS / 冻结文档 §12.5)

口径声明(必读):
  - 数据源: mt5_raw/mt5_history_trades.csv (聚合后逐笔交易, 已剔除 position_id=0 的入金)
  - pnl = net_profit + commission + swap (含成本口径, 唯一使用的盈亏字段)
  - result: WIN(pnl>0) / LOSS(pnl<0) / FLAT(pnl==0)
  - 胜率分母 = WIN + LOSS + FLAT (FLAT 计入分母, 不计入分子)
  - 持仓时长 = exit_time - entry_time (秒), 服务器时间
  - 所有时段/星期均为 MT5 服务器时间, 未转换为本地时区

本层只输出统计事实与显著性检验, 不生成交易建议。
"""
from __future__ import annotations
import csv, json, math, random, statistics as st
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "mt5_raw" / "mt5_history_trades.csv"
OUT = ROOT / "mt5_raw" / "b2_analysis.json"

random.seed(42)


def load():
    rows = []
    with open(SRC, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                pnl = float(r["pnl"])
                et, xt = int(r["entry_time"]), int(r["exit_time"])
            except (ValueError, KeyError):
                continue
            rows.append({
                "pid": r["position_id"],
                "symbol": r["symbol"],
                "pnl": pnl,
                "vol": float(r["volume"] or 0),
                "dir": r["direction"],
                "entry": et,
                "exit": xt,
                "hold_s": max(0, xt - et),
                "result": r["result"],
            })
    rows.sort(key=lambda x: x["entry"])
    return rows


def bucket_hold(s: int) -> str:
    if s < 300:
        return "1_lt5min"
    if s < 1800:
        return "2_5to30min"
    if s < 14400:
        return "3_30minTo4h"
    return "4_gt4h"


def agg(trs):
    """一组交易的核心指标"""
    n = len(trs)
    if n == 0:
        return {"n": 0}
    pnls = [t["pnl"] for t in trs]
    w = [p for p in pnls if p > 0]
    l = [p for p in pnls if p < 0]
    gw, gl = sum(w), sum(l)
    return {
        "n": n,
        "total_pnl": round(sum(pnls), 2),
        "win_rate_pct": round(len(w) / n * 100, 1),
        "avg_win": round(gw / len(w), 2) if w else 0.0,
        "avg_loss": round(gl / len(l), 2) if l else 0.0,
        "payoff": round((gw / len(w)) / abs(gl / len(l)), 2) if w and l else None,
        "profit_factor": round(gw / abs(gl), 2) if gl else None,
        "expectancy": round(sum(pnls) / n, 3),
        "median_hold_min": round(st.median([t["hold_s"] for t in trs]) / 60, 1),
        "median_vol": round(st.median([t["vol"] for t in trs]), 2),
    }


# ---------- 检验 1: 期望值是否显著非零 (bootstrap) ----------
def bootstrap_expectancy(pnls, iters=20000):
    n = len(pnls)
    means = []
    for _ in range(iters):
        s = 0.0
        for _ in range(n):
            s += pnls[random.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * iters)]
    hi = means[int(0.975 * iters)]
    p_neg = sum(1 for m in means if m <= 0) / iters
    return {
        "observed_expectancy": round(sum(pnls) / n, 3),
        "ci95_low": round(lo, 3),
        "ci95_high": round(hi, 3),
        "prob_true_expectancy_le_0": round(p_neg, 3),
        "significant_positive": bool(lo > 0),
    }


# ---------- 检验 2: 最大连亏是否异常 (蒙特卡洛) ----------
def max_streak(seq, target):
    best = cur = 0
    for x in seq:
        if x == target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def streak_significance(results, iters=20000):
    n = len(results)
    p_win = sum(1 for r in results if r == "W") / n
    obs_l = max_streak(results, "L")
    obs_w = max_streak(results, "W")
    ml, mw = [], []
    for _ in range(iters):
        sim = ["W" if random.random() < p_win else "L" for _ in range(n)]
        ml.append(max_streak(sim, "L"))
        mw.append(max_streak(sim, "W"))
    return {
        "n": n,
        "p_win_used": round(p_win, 4),
        "observed_max_loss_streak": obs_l,
        "random_expected_max_loss_streak": round(sum(ml) / iters, 1),
        "prob_random_ge_observed_loss": round(sum(1 for x in ml if x >= obs_l) / iters, 4),
        "observed_max_win_streak": obs_w,
        "random_expected_max_win_streak": round(sum(mw) / iters, 1),
        "prob_random_ge_observed_win": round(sum(1 for x in mw if x >= obs_w) / iters, 4),
    }


# ---------- 表 1: Holding Profile ----------
def holding_profile(trs):
    win = [t for t in trs if t["pnl"] > 0]
    los = [t for t in trs if t["pnl"] < 0]

    def dist(g):
        if not g:
            return {}
        h = sorted(t["hold_s"] for t in g)
        return {
            "n": len(h),
            "p25_min": round(h[len(h) // 4] / 60, 1),
            "median_min": round(st.median(h) / 60, 1),
            "p75_min": round(h[len(h) * 3 // 4] / 60, 1),
            "p95_min": round(h[min(len(h) - 1, int(len(h) * 0.95))] / 60, 1),
            "max_min": round(h[-1] / 60, 1),
        }

    by_bucket = defaultdict(list)
    for t in trs:
        by_bucket[bucket_hold(t["hold_s"])].append(t)
    return {
        "win_hold_dist": dist(win),
        "loss_hold_dist": dist(los),
        "pnl_by_hold_bucket": {k: agg(v) for k, v in sorted(by_bucket.items())},
    }


# ---------- 表 2: Frequency Impact ----------
def frequency_impact(trs):
    by_day = defaultdict(list)
    for t in trs:
        d = datetime.fromtimestamp(t["entry"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[d].append(t)
    tiers = {"1_le2": [], "2_3to5": [], "3_6to10": [], "4_gt10": []}
    day_rows = []
    for d, g in sorted(by_day.items()):
        c = len(g)
        p = sum(x["pnl"] for x in g)
        day_rows.append({"date": d, "trades": c, "pnl": round(p, 2)})
        k = "1_le2" if c <= 2 else "2_3to5" if c <= 5 else "3_6to10" if c <= 10 else "4_gt10"
        tiers[k].append((c, p, g))
    out = {}
    for k, v in tiers.items():
        if not v:
            out[k] = {"days": 0}
            continue
        alltr = [t for _, _, g in v for t in g]
        out[k] = {
            "days": len(v),
            "total_trades": sum(c for c, _, _ in v),
            "total_pnl": round(sum(p for _, p, _ in v), 2),
            "avg_pnl_per_day": round(sum(p for _, p, _ in v) / len(v), 2),
            "avg_pnl_per_trade": round(sum(p for _, p, _ in v) / sum(c for c, _, _ in v), 3),
            "win_rate_pct": agg(alltr)["win_rate_pct"],
            "median_hold_min": agg(alltr)["median_hold_min"],
        }
    # 相关性: 当日笔数 vs 当日盈亏
    xs = [r["trades"] for r in day_rows]
    ys = [r["pnl"] for r in day_rows]
    n = len(xs)
    if n > 2:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        vx = math.sqrt(sum((a - mx) ** 2 for a in xs))
        vy = math.sqrt(sum((b - my) ** 2 for b in ys))
        pear = cov / (vx * vy) if vx and vy else None
    else:
        pear = None
    return {
        "active_days": n,
        "by_daily_frequency_tier": out,
        "pearson_dailytrades_vs_dailypnl": round(pear, 3) if pear is not None else None,
        "day_rows": day_rows,
    }


# ---------- 表 3: Streak Analysis ----------
def streak_analysis(trs):
    seq = ["W" if t["pnl"] > 0 else "L" for t in trs]
    sig = streak_significance(seq)

    # 连亏第 N 笔之后的下一笔特征
    after = defaultdict(list)
    run = 0
    for i, t in enumerate(trs):
        if run >= 1:
            key = f"after_{min(run, 5)}_consec_loss" if run < 5 else "after_5plus_consec_loss"
            after[key].append(t)
        run = run + 1 if t["pnl"] <= 0 else 0

    base = agg(trs)
    # 连亏期内 vs 非连亏期 行为对比 (连亏期定义: 前一笔为亏且当前处于 >=3 连亏序列中)
    inloss, normal = [], []
    run = 0
    for t in trs:
        (inloss if run >= 3 else normal).append(t)
        run = run + 1 if t["pnl"] <= 0 else 0

    def gap_stats(g):
        if len(g) < 2:
            return None
        gaps = [g[i]["entry"] - g[i - 1]["exit"] for i in range(1, len(g))]
        gaps = [x for x in gaps if x >= 0]
        return round(st.median(gaps) / 60, 1) if gaps else None

    return {
        "significance_test": sig,
        "baseline_all": base,
        "next_trade_after_n_losses": {k: agg(v) for k, v in sorted(after.items())},
        "in_loss_streak_ge3": {**agg(inloss), "median_gap_to_prev_exit_min": gap_stats(inloss)},
        "outside_loss_streak": {**agg(normal), "median_gap_to_prev_exit_min": gap_stats(normal)},
        "direction_mix_in_streak": {
            d: sum(1 for t in inloss if t["dir"] == d) for d in ("BUY", "SELL")
        },
        "direction_mix_outside": {
            d: sum(1 for t in normal if t["dir"] == d) for d in ("BUY", "SELL")
        },
    }


# ---------- 表 4: Entry Quality (持仓分桶质量) ----------
def entry_quality(trs):
    by_bucket = defaultdict(list)
    for t in trs:
        by_bucket[bucket_hold(t["hold_s"])].append(t)
    res = {}
    for k, v in sorted(by_bucket.items()):
        a = agg(v)
        a["boot"] = bootstrap_expectancy([t["pnl"] for t in v], iters=5000)
        a["pnl_share_pct"] = round(sum(t["pnl"] for t in v), 2)
        res[k] = a
    return res


# ---------- 尾部依赖 ----------
def tail_dependency(trs):
    pnls = sorted((t["pnl"] for t in trs), reverse=True)
    total = sum(pnls)
    gw = sum(p for p in pnls if p > 0)
    out = {"total_pnl": round(total, 2), "gross_profit": round(gw, 2)}
    for k in (1, 3, 5, 10):
        top = sum(pnls[:k])
        out[f"top{k}_pnl"] = round(top, 2)
        out[f"top{k}_share_of_gross_profit_pct"] = round(top / gw * 100, 1) if gw else None
        out[f"pnl_excluding_top{k}"] = round(total - top, 2)
    return out


def main():
    trs = load()
    xau = [t for t in trs if t["symbol"].upper().startswith("XAU")]
    out = {
        "_meta": {
            "source": str(SRC),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "basis": "pnl = net_profit + commission + swap; FLAT counted in denominator",
            "total_trades": len(trs),
            "xauusd_trades": len(xau),
            "scope_note": "主分析限定 XAUUSD(占比最高), 全样本另列",
        },
        "A_expectancy_test_all": bootstrap_expectancy([t["pnl"] for t in trs]),
        "A_expectancy_test_xau": bootstrap_expectancy([t["pnl"] for t in xau]),
        "B_tail_dependency_all": tail_dependency(trs),
        "B_tail_dependency_xau": tail_dependency(xau),
        "T1_holding_profile_xau": holding_profile(xau),
        "T2_frequency_impact_xau": frequency_impact(xau),
        "T3_streak_analysis_xau": streak_analysis(xau),
        "T4_entry_quality_xau": entry_quality(xau),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台摘要
    print("=" * 62)
    print("B2 行为统计分析 | XAUUSD %d 笔 / 全样本 %d 笔" % (len(xau), len(trs)))
    print("=" * 62)
    a = out["A_expectancy_test_xau"]
    print("\n[A] 期望值显著性 (XAUUSD, bootstrap 20000)")
    print("  观测期望 %.3f USD/笔 | 95%%CI [%.3f, %.3f]" % (a["observed_expectancy"], a["ci95_low"], a["ci95_high"]))
    print("  真实期望<=0 的概率: %.1f%%  | 显著为正: %s" % (a["prob_true_expectancy_le_0"] * 100, a["significant_positive"]))
    s = out["T3_streak_analysis_xau"]["significance_test"]
    print("\n[B] 连亏显著性检验 (蒙特卡洛 20000)")
    print("  实测最大连亏 %d 笔 | 同胜率随机序列期望 %.1f 笔" % (s["observed_max_loss_streak"], s["random_expected_max_loss_streak"]))
    print("  随机产生 >=%d 连亏的概率: %.1f%%" % (s["observed_max_loss_streak"], s["prob_random_ge_observed_loss"] * 100))
    print("  实测最大连盈 %d 笔 | 随机期望 %.1f 笔 | P=%.1f%%" % (s["observed_max_win_streak"], s["random_expected_max_win_streak"], s["prob_random_ge_observed_win"] * 100))
    print("\n[T4] 持仓分桶质量 (XAUUSD)")
    print("  %-14s %5s %8s %8s %8s %8s" % ("bucket", "n", "win%", "payoff", "exp", "totPnL"))
    for k, v in out["T4_entry_quality_xau"].items():
        print("  %-14s %5d %8.1f %8s %8.3f %8.2f" % (k, v["n"], v["win_rate_pct"], v["payoff"], v["expectancy"], v["total_pnl"]))
    print("\n[T2] 日频率影响 (XAUUSD)")
    print("  %-10s %5s %7s %10s %12s %7s" % ("tier", "days", "trades", "totPnL", "pnl/trade", "win%"))
    for k, v in out["T2_frequency_impact_xau"]["by_daily_frequency_tier"].items():
        if v.get("days"):
            print("  %-10s %5d %7d %10.2f %12.3f %7.1f" % (k, v["days"], v["total_trades"], v["total_pnl"], v["avg_pnl_per_trade"], v["win_rate_pct"]))
    print("  当日笔数 vs 当日盈亏 Pearson: %s" % out["T2_frequency_impact_xau"]["pearson_dailytrades_vs_dailypnl"])
    print("\n[T3] 连亏期 vs 常态 行为对比")
    for lbl, key in (("连亏>=3期内", "in_loss_streak_ge3"), ("常态", "outside_loss_streak")):
        v = out["T3_streak_analysis_xau"][key]
        print("  %-10s n=%3d 中位持仓 %5.1f 分 中位手数 %.2f 距上笔平仓 %s 分 期望 %.3f"
              % (lbl, v["n"], v["median_hold_min"], v["median_vol"], v["median_gap_to_prev_exit_min"], v["expectancy"]))
    print("\n  方向占比: 连亏期内 %s | 常态 %s" % (out["T3_streak_analysis_xau"]["direction_mix_in_streak"], out["T3_streak_analysis_xau"]["direction_mix_outside"]))
    print("\n[B] 尾部依赖 (XAUUSD)")
    t = out["B_tail_dependency_xau"]
    print("  总盈亏 %.2f | 剔除最大1笔 %.2f | 剔除最大3笔 %.2f | 剔除最大5笔 %.2f"
          % (t["total_pnl"], t["pnl_excluding_top1"], t["pnl_excluding_top3"], t["pnl_excluding_top5"]))
    print("\n输出: %s" % OUT)


if __name__ == "__main__":
    main()
