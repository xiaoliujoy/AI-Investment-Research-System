# -*- coding: utf-8 -*-
"""情绪验证 Agent —— 市场宽度/涨跌家数/涨停跌停/连板高度/量能比，验证方向"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from sentiment import market_sentiment
    from decision_tree import latest_date

    date = ctx.trade_date or latest_date()
    raw = market_sentiment(date)
    state = raw.get("state")
    smap = {"高潮": "bullish", "活跃": "bullish", "回暖": "neutral_bullish",
            "低迷": "neutral_bearish", "冰点": "bearish", "退潮": "bearish"}
    stage = smap.get(state, "neutral")
    conf = 85 if state else 40
    narrative = f"【情绪：{state}】{raw.get('verdict', '')}"
    risk = "情绪退潮/冰点→亏钱效应扩散，回避追高。" if state in ("退潮", "冰点") else ""
    res = make_result("sentiment", "情绪验证", stage, narrative, raw=raw,
                      signal={"direction": stage, "state": state, "score": raw.get("score")},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"),
                      upstream=f"（源头：{date} 市场宽度/涨跌家数/涨停跌停/连板高度/量能比）")
    ctx.put("sentiment", res.to_dict())
    return res
