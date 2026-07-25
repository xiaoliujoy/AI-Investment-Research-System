# -*- coding: utf-8 -*-
"""L2 中国宏观 Agent —— PMI/M2/社融/LPR/CPI 货币信用格局"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from narrative_layers import layer2_china
    from brain.confidence import coverage_conf

    raw = layer2_china()
    data = raw.get("data", {})
    regime = data.get("regime", "数据待补")
    dmap = {"宽货币+宽信用": "bullish", "宽货币+紧信用": "neutral_bullish",
            "紧货币+宽信用": "neutral_bearish", "紧货币+紧信用": "bearish",
            "数据待补": "unknown"}
    stage = dmap.get(regime, "neutral")
    conf = coverage_conf(raw.get("gaps"), full=88)
    narrative = f"【货币信用：{regime}】{(raw.get('read', ''))[:120]}"
    risk = "衰退/防御格局，低估值+高股息防守，控制仓位等右侧。" if stage == "bearish" else ""
    res = make_result("L2", "中国宏观", stage, narrative, raw=raw,
                      signal={"direction": stage, "regime": regime},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"),
                      upstream="（源头：PMI/M2/社融/LPR/CPI）")
    ctx.put("L2", res.to_dict())
    return res
