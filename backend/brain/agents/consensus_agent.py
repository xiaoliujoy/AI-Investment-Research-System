# -*- coding: utf-8 -*-
"""L4 资金共识 Agent —— 板块资金净流入 + 成交额，量化+规则树识别主线与共识阶段"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from decision_tree import layer4_consensus

    raw = layer4_consensus()
    mains = raw.get("main_lines") or []
    dist = raw.get("stage_distribution") or {}
    tot = sum(dist.values()) or 1
    late = dist.get("高潮", 0) + dist.get("退潮", 0)
    if len(mains) >= 3 and (tot == 0 or late / tot < 0.5):
        stage = "bullish"
    elif mains:
        stage = "neutral"
    else:
        stage = "bearish_weak"
    conf = 90 if mains else 40
    narrative = f"识别 {len(mains)} 条主线，阶段分布：{dist}。"
    risk = "主线处高潮/退潮占比高→拥挤，宜去弱留强。" if (tot and late / tot > 0.5) else ""
    res = make_result("L4", "资金共识", stage, narrative, raw=raw,
                      signal={"direction": stage, "main_count": len(mains),
                              "late_ratio": round(late / tot, 2) if tot else 0, "dist": dist},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"),
                      upstream="（源头：板块资金净流入 + 成交额，量化+规则树）")
    ctx.put("L4", res.to_dict())
    return res
