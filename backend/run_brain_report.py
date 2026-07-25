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


if __name__ == "__main__":
    r = brain.run()
    p = brain.build_report(r)
    d = r["decision"]
    print(f"brain_report: {p}")
    print(f"  trade_date={r['trade_date']} can_buy={d['can_buy']} "
          f"position={d['position_pct']} confidence={r['confidence']['overall']} "
          f"conflicts={len(r['conflicts'])}")
    print(f"  L0: {r['L0']['headline']}")
