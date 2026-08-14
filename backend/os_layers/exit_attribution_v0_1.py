# -*- coding: utf-8 -*-
"""
Exit Engine Attribution v0.1  --  Entry x Exit 交叉归因（纯聚合，不重模拟）
============================================================================

定位：实验口径审计。复用 exit_observation_GOLD_TRAIL_v0.1.json 里已保存的
      210 笔逐笔结果（同规则、同数据），只按 entry_type 重新聚合。
      这不是新实验，H1 规则未变、未引入新参数。

回答的核心问题：
  1. Trailing 的 Alpha 到底来自哪个 entry batch？（E1/E2 vs E3/E4 直接拆分）
  2. H1 是「Entry-conditioned Exit Edge」还是「universal Exit Edge」？
     -> 看 Entry x Exit 交叉：各 entry_type 的 baseline_capture vs trailing_capture。

治理：Observation-only。不改生产、不改 Contract spec（v0.1 冻结）。
"""

import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from exit_observation_v0_1 import agg  # 复用同一套指标聚合（规则/数据不变）

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OBS_JSON = os.path.join(ROOT, "backend", "output", "research_contracts",
                        "exit_observation_GOLD_TRAIL_v0.1.json")
OUT_JSON = os.path.join(ROOT, "backend", "output", "research_contracts",
                        "exit_attribution_GOLD_TRAIL_v0.1.json")

ENTRY_ORDER = ["E1_anticipatory_fail", "E2_anticipatory_suffered",
               "E3_confirmed_entry", "E4_well_executed"]
SHORT = {"E1_anticipatory_fail": "E1", "E2_anticipatory_suffered": "E2",
         "E3_confirmed_entry": "E3", "E4_well_executed": "E4"}


def median_mfe(recs):
    vals = [r["mfe_usd"] for r in recs if r["mfe_usd"] > 0]
    return round(statistics.median(vals), 2) if vals else None


def main():
    with open(OBS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    recs = data.get("per_trade_all210")
    if not recs:
        raise SystemExit("observation JSON 缺少 per_trade_all210；请先重跑 exit_observation_v0_1.py 持久化")

    groups = defaultdict(list)
    for r in recs:
        groups[r.get("entry_type", "unknown")].append(r)

    quad = {}
    for et in ENTRY_ORDER:
        g = groups.get(et, [])
        if not g:
            continue
        m = agg(g)
        quad[et] = {
            "short": SHORT[et],
            "n": m["n"],
            "triggered_n": m["triggered_n"],
            "net_baseline": m["net_pnl_baseline"],
            "net_trailing": m["net_pnl_trailing"],
            "net_delta": m["net_pnl_delta"],
            "pf_baseline": m["pf_baseline"],
            "pf_trailing": m["pf_trailing"],
            "median_mfe": median_mfe(g),
            "capture_baseline": m["median_capture_baseline"],
            "capture_trailing": m["median_capture_trailing"],
            "capture_delta": (round(m["median_capture_trailing"] - m["median_capture_baseline"], 4)
                              if m["median_capture_baseline"] is not None and m["median_capture_trailing"] is not None
                              else None),
            "giveback_baseline": m["median_giveback_baseline"],
            "giveback_trailing": m["median_giveback_trailing"],
            "maxdd_baseline": m["max_dd_baseline"],
            "maxdd_trailing": m["max_dd_trailing"],
            "avg_win_baseline": m["avg_win_baseline"],
            "avg_win_trailing": m["avg_win_trailing"],
            "avg_loss_baseline": m["avg_loss_baseline"],
            "avg_loss_trailing": m["avg_loss_trailing"],
            "median_R_baseline": m["median_R_baseline"],
            "median_R_trailing": m["median_R_trailing"],
            "median_hold_base_h": m["median_hold_base_h"],
            "median_hold_trail_h": m["median_hold_trail_h"],
        }

    # 数学一致性校验：E1/E2 Δ = Total Δ - E3/E4 Δ
    total = data["metrics_secondary_all210"]
    e34 = quad.get("E3_confirmed_entry", {})
    e34_n = e34.get("n", 0) + quad.get("E4_well_executed", {}).get("n", 0)
    e34_delta = (quad.get("E3_confirmed_entry", {}).get("net_delta", 0)
                 + quad.get("E4_well_executed", {}).get("net_delta", 0))
    e12_delta = total["net_pnl_delta"] - e34_delta
    check = {
        "total_delta": total["net_pnl_delta"],
        "e34_delta_sum": round(e34_delta, 2),
        "e12_delta_inferred": round(e12_delta, 2),
        "e12_delta_direct": round(quad["E1_anticipatory_fail"]["net_delta"]
                                  + quad["E2_anticipatory_suffered"]["net_delta"], 2),
        "consistent": abs(round(e12_delta, 2)
                          - (quad["E1_anticipatory_fail"]["net_delta"]
                             + quad["E2_anticipatory_suffered"]["net_delta"])) < 0.01,
    }

    # Entry x Exit 交叉（核心归因）：capture 视角
    cross = {et: {
        "short": SHORT[et],
        "capture_baseline": quad[et]["capture_baseline"],
        "capture_trailing": quad[et]["capture_trailing"],
        "capture_delta": quad[et]["capture_delta"],
        "net_delta": quad[et]["net_delta"],
    } for et in quad}

    # 判定：H1 是 Entry-conditioned 还是 universal
    cap_deltas = {et: quad[et]["capture_delta"] for et in quad}
    signs = set(d > 0 for d in cap_deltas.values() if d is not None)
    if len(signs) > 1:
        verdict = "ENTRY-CONDITIONED：Trailing 对不同 Entry 状态作用方向相反 -> 应按 Entry Archetype 选择 Exit"
    else:
        verdict = "UNIVERSAL：Trailing 对各 Entry 状态同向 -> 可考虑统一 Exit"

    out = {
        "attribution_id": "EXIT-ATTR-GOLD-TRAIL-v0.1",
        "source_experiment": data["experiment_id"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "governance": "Observation-only. 纯聚合（复用 observation JSON），非新实验.",
        "note": "E1/E2 是预期入场(净亏批)，E3/E4 是确认入场(净盈批)。Trailing 在其上作用相反 => Entry-conditioned Edge 强烈信号.",
        "quadrant_by_entry_type": quad,
        "entry_x_exit_capture_cross": cross,
        "math_consistency_check": check,
        "verdict": verdict,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台
    print("=== Quadrant (按 entry_type 直接拆分) ===")
    print(f"{'batch':<6}{'n':>4}{'base_net':>12}{'trail_net':>12}{'Δ':>10}{'cap_b':>9}{'cap_t':>9}{'capΔ':>9}")
    for et in quad:
        q = quad[et]
        print(f"{q['short']:<6}{q['n']:>4}{q['net_baseline']:>12.1f}{q['net_trailing']:>12.1f}"
              f"{q['net_delta']:>10.1f}{str(q['capture_baseline']):>9}{str(q['capture_trailing']):>9}"
              f"{str(q['capture_delta']):>9}")
    print("\n=== Entry x Exit Capture 交叉 ===")
    for et in cross:
        c = cross[et]
        print(f"{c['short']:<4} cap_b={c['capture_baseline']}  cap_t={c['capture_trailing']}  Δ={c['capture_delta']}  netΔ={c['net_delta']}")
    print(f"\n数学校验: TotalΔ={check['total_delta']}  E1/E2Δ(inferred)={check['e12_delta_inferred']}  "
          f"E1/E2Δ(direct)={check['e12_delta_direct']}  consistent={check['consistent']}")
    print(f"\n>>> VERDICT: {verdict}")
    print(f"写出: {OUT_JSON}")


if __name__ == "__main__":
    main()
