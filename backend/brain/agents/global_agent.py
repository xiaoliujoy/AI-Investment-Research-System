# -*- coding: utf-8 -*-
"""L1 全球宏观 Agent —— 美股/VIX/美元/商品/BTC/美债/人民币/沪深港通"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from narrative_layers import layer1_global
    from brain.confidence import coverage_conf

    raw = layer1_global()
    data = raw.get("data", {})
    regime = data.get("regime", "中性震荡")
    dmap = {"风险偏好回升": "bullish", "中性震荡": "neutral",
            "避险偏强": "bearish_weak", "避险主导": "bearish"}
    stage = dmap.get(regime, "neutral")
    conf = coverage_conf(raw.get("gaps"), full=88)
    narrative = f"【外围：{regime}】{data.get('regime_note', '')}"
    risk = ("外围避险信号（VIX/人民币/北向）偏强时注意外资流出与高位回撤。"
            if stage in ("bearish", "bearish_weak") else "")
    res = make_result("L1", "全球宏观", stage, narrative, raw=raw,
                      signal={"direction": stage, "regime": regime, "key": regime},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"),
                      upstream="（源头：美股/VIX/美元/商品/BTC/美债/人民币/沪深港通）")
    ctx.put("L1", res.to_dict())
    return res
