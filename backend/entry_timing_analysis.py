#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入场时机分类回验 —— 把 ChatGPT 对话中"预期突破 vs 确认突破"假设落地成数据。

假设：赚钱来自趋势判断（方向对），亏钱来自入场提前（在压力位预判突破）。

分类逻辑（基于 MT5 210笔 XAUUSD 交易的 MFE/MAE 价格路径）：

  E1 预期突破失败  —— MFE 极低（趋势没验证），MAE 高（立即反向），净亏
                     → 典型"压力位买入，突破没发生，被扫止损"
  E2 先苦后甜      —— MFE 尚可但 MAE 先到且大（入场后先大幅浮亏再反转）
                     → 典型"方向对但入场太早，扛了一段痛苦"
  E3 确认入场      —— MAE 低、MFE 先到（入场后快速有利波动）
                     → 典型"突破后回踩确认买入，止损小、盈亏比好"
  E4 完美执行      —— D_captured 原型（系统已标记的成功样本）

输出：mt5_raw/entry_timing_report.json + stdout 摘要
"""
import json, os, sys
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TP_PATH = os.path.join(ROOT, "mt5_raw", "trade_path.json")
OUT_PATH = os.path.join(ROOT, "mt5_raw", "entry_timing_report.json")


def load_trades():
    with open(TP_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["trades"], data.get("summary", {})


def classify_entry(t):
    """返回入场类型 E1/E2/E3/E4 + 分类依据"""
    arch = t.get("path_archetype", "?")
    mfe = t.get("mfe_usd", 0) or 0
    mae = t.get("mae_usd", 0) or 0
    pnl = t.get("pnl", 0) or 0
    mfe_off = t.get("mfe_offset_sec", 0) or 0
    mae_off = t.get("mae_offset_sec", 0) or 0

    # E4 优先：D_captured 是系统已验证的成功样本
    if arch == "D_captured":
        return "E4_well_executed", "D_captured原型"

    # E1：MFE 极低（趋势从未验证）+ 净亏
    #    A_entry_wrong 原型 MFE avg=2.08，设阈值 5 USD
    if mfe < 5.0 and pnl < 0:
        return "E1_anticipatory_fail", "MFE<5且亏损，趋势未验证"

    # 计算疼痛指标
    total = mae + mfe
    pain_ratio = (mae / total) if total > 0 else 1.0
    pain_before_profit = mae_off <= mfe_off  # MAE 先于或同时于 MFE

    # E2：先苦后甜 —— 疼痛比 >0.5（亏大于赚的峰值）或疼痛先到且 MFE 尚可
    if pain_ratio > 0.5 or (pain_before_profit and mae > mfe * 0.5 and mfe >= 5):
        return "E2_anticipatory_suffered", "MAE>MFE*0.5或疼痛先到，入场偏早"

    # E3：确认入场 —— 疼痛比低（有利波动远大于不利）
    if pain_ratio < 0.25:
        return "E3_confirmed_entry", "MAE<MFE*0.25，入场时机良好"

    # 剩余归为 E2（中间地带，偏早）
    return "E2_anticipatory_suffered", "疼痛比0.25-0.5，入场偏中性偏早"


def calc_stats(trades):
    """计算一组交易的统计指标"""
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = [t for t in trades if (t.get("pnl", 0) or 0) > 0]
    losses = [t for t in trades if (t.get("pnl", 0) or 0) < 0]
    pnls = [t.get("pnl", 0) or 0 for t in trades]
    mfes = [t.get("mfe_usd", 0) or 0 for t in trades]
    maes = [t.get("mae_usd", 0) or 0 for t in trades]
    caps = [t.get("mfe_capture_ratio", 0) or 0 for t in trades]
    holds = [(t.get("holding_sec", 0) or 0) / 3600.0 for t in trades]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = sum(-p for p in pnls if p < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0)

    # 疼痛比
    pain_ratios = []
    for t in trades:
        mfe = t.get("mfe_usd", 0) or 0
        mae = t.get("mae_usd", 0) or 0
        total = mae + mfe
        if total > 0:
            pain_ratios.append(mae / total)

    return {
        "n": n,
        "win_rate": len(wins) / n,
        "net_pnl": sum(pnls),
        "avg_pnl": sum(pnls) / n,
        "avg_mfe": sum(mfes) / n,
        "avg_mae": sum(maes) / n,
        "avg_capture": sum(caps) / n,
        "avg_hold_h": sum(holds) / n,
        "pf": pf,
        "avg_pain_ratio": sum(pain_ratios) / len(pain_ratios) if pain_ratios else None,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
    }


def fmt_money(x):
    return f"{x:,.2f}"


def fmt_pct(x):
    return f"{x*100:.1f}%"


def main():
    trades, summary = load_trades()
    print("=" * 72)
    print("  入场时机分类回验 —— MT5 XAUUSD %d 笔" % len(trades))
    print("  假设：赚钱来自趋势判断，亏钱来自入场提前")
    print("=" * 72)

    # 分类
    classified = []
    for t in trades:
        etype, reason = classify_entry(t)
        t2 = dict(t)
        t2["entry_type"] = etype
        t2["entry_reason"] = reason
        classified.append(t2)

    # 按入场类型统计
    groups = defaultdict(list)
    for t in classified:
        groups[t["entry_type"]].append(t)

    order = ["E1_anticipatory_fail", "E2_anticipatory_suffered",
             "E3_confirmed_entry", "E4_well_executed"]
    labels = {
        "E1_anticipatory_fail": "E1 预期突破失败",
        "E2_anticipatory_suffered": "E2 先苦后甜(入场早)",
        "E3_confirmed_entry": "E3 确认入场",
        "E4_well_executed": "E4 完美执行",
    }

    print("\n%-24s %5s %6s %10s %10s %10s %8s %8s %7s" % (
        "入场类型", "N", "胜率", "净盈亏", "均MFE", "均MAE", "捕获率", "均持仓h", "PF"))
    print("-" * 100)

    all_stats = {}
    for key in order:
        if key not in groups:
            continue
        stats = calc_stats(groups[key])
        all_stats[key] = stats
        print("%-24s %5d %6s %10s %10s %10s %8s %8.2f %7s" % (
            labels[key], stats["n"], fmt_pct(stats["win_rate"]),
            fmt_money(stats["net_pnl"]), fmt_money(stats["avg_mfe"]),
            fmt_money(stats["avg_mae"]), f"{stats['avg_capture']:.2f}",
            stats["avg_hold_h"],
            f"{stats['pf']:.2f}" if stats["pf"] != float("inf") else "inf"))

    # 总计
    total_stats = calc_stats(classified)
    print("-" * 100)
    print("%-24s %5d %6s %10s %10s %10s %8s %8.2f %7s" % (
        "总计", total_stats["n"], fmt_pct(total_stats["win_rate"]),
        fmt_money(total_stats["net_pnl"]), fmt_money(total_stats["avg_mfe"]),
        fmt_money(total_stats["avg_mae"]), f"{total_stats['avg_capture']:.2f}",
        total_stats["avg_hold_h"],
        f"{total_stats['pf']:.2f}" if total_stats["pf"] != float("inf") else "inf"))

    # ---- 精度分层 ----
    print("\n" + "=" * 72)
    print("  按数据精度分层（low = 持仓<2根bar，MFE/MAE系统性高估）")
    print("=" * 72)
    for prec in ["high", "mid", "low"]:
        prec_trades = [t for t in classified if t.get("precision") == prec]
        if not prec_trades:
            continue
        prec_groups = defaultdict(list)
        for t in prec_trades:
            prec_groups[t["entry_type"]].append(t)
        print("\n  [precision=%s] N=%d" % (prec, len(prec_trades)))
        for key in order:
            if key not in prec_groups:
                continue
            s = calc_stats(prec_groups[key])
            print("    %-24s N=%-3d 胜率=%-5s 净=%-10s 均MFE=%-8s 均MAE=%-8s" % (
                labels[key], s["n"], fmt_pct(s["win_rate"]),
                fmt_money(s["net_pnl"]), fmt_money(s["avg_mfe"]),
                fmt_money(s["avg_mae"])))

    # ---- 交叉表：入场类型 × 路径原型 ----
    print("\n" + "=" * 72)
    print("  交叉表：入场类型 × 路径原型(A/B/C/D)")
    print("=" * 72)
    archetypes = ["A_entry_wrong", "B_stop_too_tight", "C_exit_management", "D_captured"]
    print("%-24s %5s %5s %5s %5s %5s" % ("入场类型\\原型", "A", "B", "C", "D", "合计"))
    print("-" * 52)
    crosstab = {}
    for key in order:
        if key not in groups:
            continue
        row = {}
        for arch in archetypes:
            row[arch] = sum(1 for t in groups[key] if t.get("path_archetype") == arch)
        row["total"] = len(groups[key])
        crosstab[key] = row
        print("%-24s %5d %5d %5d %5d %5d" % (
            labels[key], row["A_entry_wrong"], row["B_stop_too_tight"],
            row["C_exit_management"], row["D_captured"], row["total"]))

    # ---- 核心假设验证 ----
    print("\n" + "=" * 72)
    print("  核心假设验证")
    print("=" * 72)
    e1 = all_stats.get("E1_anticipatory_fail", {})
    e3 = all_stats.get("E3_confirmed_entry", {})
    e4 = all_stats.get("E4_well_executed", {})

    print("\n  假设1：预期突破失败(E1)是主要出血点")
    if e1:
        print("    E1 N=%d, 净=%s, 占总亏损比=%s" % (
            e1["n"], fmt_money(e1["net_pnl"]),
            fmt_pct(e1["net_pnl"] / total_stats["net_pnl"]) if total_stats["net_pnl"] != 0 else "N/A"))

    print("\n  假设2：确认入场(E3)的盈亏比远优于预期入场(E1+E2)")
    e12_net = sum(all_stats.get(k, {}).get("net_pnl", 0) for k in ["E1_anticipatory_fail", "E2_anticipatory_suffered"])
    e34_net = sum(all_stats.get(k, {}).get("net_pnl", 0) for k in ["E3_confirmed_entry", "E4_well_executed"])
    e12_n = sum(all_stats.get(k, {}).get("n", 0) for k in ["E1_anticipatory_fail", "E2_anticipatory_suffered"])
    e34_n = sum(all_stats.get(k, {}).get("n", 0) for k in ["E3_confirmed_entry", "E4_well_executed"])
    print("    预期入场(E1+E2): N=%d, 净=%s" % (e12_n, fmt_money(e12_net)))
    print("    确认入场(E3+E4): N=%d, 净=%s" % (e34_n, fmt_money(e34_net)))
    if e12_n > 0 and e34_n > 0:
        print("    人均盈亏: 预期=%.2f vs 确认=%.2f (差 %.2f)" % (
            e12_net / e12_n, e34_net / e34_n, e34_net / e34_n - e12_net / e12_n))

    print("\n  假设3：如果只做确认入场(E3+E4)，理论改善")
    if e34_n > 0:
        print("    仅E3+E4: N=%d, 净=%s, 胜率=%s, PF=%.2f" % (
            e34_n, fmt_money(e34_net),
            fmt_pct(sum(1 for t in classified
                        if t["entry_type"] in ("E3_confirmed_entry", "E4_well_executed")
                        and (t.get("pnl", 0) or 0) > 0) / e34_n),
            e34_net / abs(e12_net) if e12_net < 0 else 0))

    # ---- MFE 捕获率对比 ----
    print("\n  假设4：确认入场的 MFE 捕获率高于预期入场")
    for key in order:
        s = all_stats.get(key)
        if s and s.get("avg_capture") is not None:
            print("    %-24s 捕获率=%.4f" % (labels[key], s["avg_capture"]))

    # ---- 输出 JSON ----
    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_trades": len(trades),
        "classification_method": {
            "E1_anticipatory_fail": "MFE<5 USD且净亏，趋势未验证",
            "E2_anticipatory_suffered": "疼痛比>0.5或MAE先到且>MFE*0.5",
            "E3_confirmed_entry": "疼痛比<0.25，入场时机良好",
            "E4_well_executed": "D_captured原型",
        },
        "stats_by_entry_type": {k: all_stats[k] for k in order if k in all_stats},
        "crosstab_entry_vs_archetype": crosstab,
        "hypothesis_test": {
            "anticipatory_net": e12_net,
            "confirmed_net": e34_net,
            "anticipatory_n": e12_n,
            "confirmed_n": e34_n,
        },
        "trades": [{"trade_id": t["trade_id"], "entry_type": t["entry_type"],
                     "entry_reason": t["entry_reason"], "pnl": t.get("pnl", 0),
                     "mfe_usd": t.get("mfe_usd", 0), "mae_usd": t.get("mae_usd", 0),
                     "path_archetype": t.get("path_archetype", "?"),
                     "precision": t.get("precision", "?"),
                     "holding_sec": t.get("holding_sec", 0),
                     "mfe_capture_ratio": t.get("mfe_capture_ratio", 0)}
                    for t in classified],
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n" + "=" * 72)
    print("  [OK] -> %s" % OUT_PATH)
    print("=" * 72)


if __name__ == "__main__":
    main()
