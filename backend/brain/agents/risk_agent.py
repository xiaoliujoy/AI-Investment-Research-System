# -*- coding: utf-8 -*-
"""L7 风险控制 Agent —— 市场+行业+个股三维风险，仓位护栏"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from decision_tree import layer7_risk, latest_date

    date = ctx.trade_date or latest_date()
    l4raw = (ctx.get("L4") or {}).get("raw")
    l6res = ctx.get("L6")
    l6raw = (l6res or {}).get("raw") if l6res else None
    raw = layer7_risk(date, l4raw, l6raw)
    comp = raw.get("composite")
    if comp is None:
        stage = "neutral"
    elif comp < 50:
        stage = "bullish"
    elif comp >= 70:
        stage = "bearish"
    else:
        stage = "neutral"
    risk_level = "低" if (comp or 100) < 30 else ("中" if (comp or 100) < 70 else "高")
    full3d = raw.get("status", "").startswith("已接入(市场+行业+个股")
    conf = 88 if full3d else 60
    narrative = (f"三维风险综合 {comp}（市场{raw.get('risk_market')}/行业{raw.get('risk_industry')}"
                 f"/个股{raw.get('risk_stock')}），仓位护栏 {raw.get('position')}。")
    risk = f"综合风险{risk_level}，最险个股 {(raw.get('worst_stock') or {}).get('code', '-')}。"
    up = "接 L4 主线（行业风险维度）+ L6 边界声明"
    res = make_result("L7", "风险控制", stage, narrative, raw=raw,
                      signal={"direction": stage, "composite": comp,
                              "position": raw.get("position"), "risk_level": risk_level},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"), upstream=up)
    ctx.put("L7", res.to_dict())
    return res
