# -*- coding: utf-8 -*-
"""L3 产业趋势 Agent —— AI 主导产业评分，6个月投资视角（产业≠板块）"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from narrative_layers import layer3_industry

    l4raw = (ctx.get("L4") or {}).get("raw")
    raw = layer3_industry(l4raw)
    top = raw.get("top_industries") or []
    confirmed = [t for t in top if t.get("confirmed")]
    phases = [t.get("phase") for t in top]
    if confirmed:
        stage = "bullish" if any(p == "加速" for p in phases) else "neutral"
    else:
        stage = "neutral"
    conf = 85 if confirmed else 60
    names = "、".join(t["name"] for t in top[:3])
    narrative = f"未来6月最值得研究产业 Top3：{names}。" + \
                ("（均已被资金验证）" if confirmed else "（均未被资金验证，潜伏）")
    risk = "主导产业处兑现/高潮区时防退潮。" if phases.count("兑现") >= 2 else ""
    l4 = ctx.get("L4") or {}
    up = f"接 L4：识别 {l4.get('signal', {}).get('main_count', 0)} 条主线，阶段分布 {l4.get('signal', {}).get('dist', {})}"
    res = make_result("L3", "产业趋势", stage, narrative, raw=raw,
                      signal={"direction": stage, "confirmed": bool(confirmed),
                              "top": [t["name"] for t in top], "phases": phases},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"), upstream=up)
    ctx.put("L3", res.to_dict())
    return res
