# -*- coding: utf-8 -*-
"""L6 交易执行 Agent —— 边界声明：买卖/图形 100% 归用户人工，系统不越界"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from decision_tree import layer6_execution, latest_date

    date = ctx.trade_date or latest_date()
    l4 = (ctx.get("L4") or {}).get("raw") or {}
    main_sectors = [str(m.get("sector")) for m in (l4.get("main_lines") or [])]
    leader_codes = set()
    l5raw = (ctx.get("L5") or {}).get("raw") or {}
    for sec, v in (l5raw.get("leaders") or {}).items():
        if isinstance(v, dict):
            for role in ("产业龙头", "资金龙头", "技术龙头", "情绪龙头"):
                ld = v.get(role) or {}
                if ld.get("code"):
                    leader_codes.add(ld["code"])
    raw = layer6_execution(date, main_sectors, leader_codes=leader_codes)
    narrative = "价格行为（买点/卖点/图形）100% 由你人工看图表定；系统不输出突破候选、不替你定买卖。" \
                "候选范围见上方板块成分股圈定。"
    up = f"接 L4 主线（{len(main_sectors)}个）+ L5 龙头代码（{len(leader_codes)}只）"
    res = make_result("L6", "交易执行", "human", narrative, raw=raw,
                      signal={"direction": "human", "note": "边界声明"},
                      confidence=70, risk_note="系统不越界：买点/卖点/图形归用户人工。",
                      gaps=raw.get("gaps"), upstream=up)
    ctx.put("L6", res.to_dict())
    return res
