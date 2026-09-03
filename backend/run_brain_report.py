# -*- coding: utf-8 -*-
"""
每日决策简报（brain 总指挥）：基于已有 output/sector_mainline.json，
跑「推理链 + 唯一决策结论」，写 output/brain_report.json + brain_report.html。

不直接抓取数据（数据由 step1 负责），只做"定方向 + 验证 + 决策建议"。
单步失败不阻断其他步（run_daily 已隔离）。
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import brain  # noqa


# ── 失败可见（P0-A1, 2026-09-03）────────────────────────────────────────
# 核心层降级即视为不可信：这些层直接决定 can_buy / position_pct / 主线判断。
# 单层（如 GOLD、L8）降级只是信息变少；核心层降级意味着「决策是在关键输入缺失
# 的情况下做出的」。按「宁可失败，也绝不悄悄产出错误结果」原则 → 阻断。
CORE_LAYERS = {"L4", "L5", "L6", "L7", "sentiment"}


def _degraded_layers(report):
    """返回被降级（signal.direction == unknown）的层名列表。"""
    out = []
    for k, v in (report.get("results") or {}).items():
        sig = (v or {}).get("signal") or {}
        if sig.get("direction") == "unknown":
            out.append(k)
    return out


if __name__ == "__main__":
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description="每日决策简报（brain 总指挥）")
    ap.add_argument("--date", help="指定交易日 YYYY-MM-DD（默认自动取最新）")
    ap.add_argument("--allow-degraded", action="store_true",
                    help="人工豁免：核心层降级时仍产出简报（报告内写入 degraded_override "
                         "审计标记）。仅限明确知情的人工干预；默认关闭 = 失败必阻断。")
    args = ap.parse_args()

    try:
        r = brain.run(date=args.date)
        p = brain.build_report(r)
    except Exception as e:
        print("=" * 68, file=sys.stderr)
        print("run_brain_report FAIL —— 简报生成异常，阻断下游（不产出/不推送）",
              file=sys.stderr)
        print(f"  {type(e).__name__}: {e}", file=sys.stderr)
        print("=" * 68, file=sys.stderr)
        sys.exit(1)

    d = r["decision"]
    degraded = _degraded_layers(r)
    core_degraded = [x for x in degraded if x in CORE_LAYERS]

    # 1) trade_date 必须存在（没有时点的数据没有资格叫「今天的简报」）
    if not r.get("trade_date"):
        print("run_brain_report FAIL —— trade_date 缺失，无法证明数据时点",
              file=sys.stderr)
        sys.exit(1)

    # 2) 核心推理层不得降级
    if core_degraded:
        print("=" * 68, file=sys.stderr)
        print("run_brain_report FAIL —— 核心推理层降级，简报不可信", file=sys.stderr)
        print(f"  trade_date : {r['trade_date']}", file=sys.stderr)
        print(f"  降级核心层 : {', '.join(core_degraded)}", file=sys.stderr)
        for k in core_degraded:
            out = (r.get("results") or {}).get(k) or {}
            print(f"    - {k}: {str(out.get('output', ''))[:120]}", file=sys.stderr)
        if not args.allow_degraded:
            print("  处置：阻断下游。确需人工出简报时，显式加 --allow-degraded。",
                  file=sys.stderr)
            print("=" * 68, file=sys.stderr)
            sys.exit(1)
        # 人工豁免：写可审计标记 + 回写 JSON，保证事后可追溯是谁、在哪天放行的
        r["degraded_override"] = {
            "allowed_by": "manual --allow-degraded",
            "degraded_core_layers": core_degraded,
            "trade_date": r["trade_date"],
        }
        jp = os.path.join(BASE, "output", "brain_report.json")
        with open(jp, "w", encoding="utf-8") as _f:
            _json.dump(r, _f, ensure_ascii=False, indent=2, default=str)
        print("  ⚠ 人工豁免生效（--allow-degraded），报告已标记 degraded_override",
              file=sys.stderr)
        print("=" * 68, file=sys.stderr)

    print(f"brain_report: {p}")
    print(f"  trade_date={r['trade_date']} can_buy={d['can_buy']} "
          f"position={d['position_pct']} confidence={r['confidence']['overall']} "
          f"conflicts={len(r['conflicts'])}")
    print(f"  L0: {r['L0']['headline']}")
    if degraded:
        print(f"  ⚠ 非核心层降级（不阻断）: {', '.join(degraded)}")
