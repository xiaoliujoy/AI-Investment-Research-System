# -*- coding: utf-8 -*-
"""L8 学习进化 Agent —— 交易日志统计，月度胜率与盈利模式，反哺决策系统"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from narrative_layers import layer8_learning

    raw = layer8_learning()
    n_trade = raw.get("count") or 0          # 执行录入（验证过的交易）
    n_signal = raw.get("n_signal", 0) or 0   # 系统判断信号（自动通电）
    judgment = raw.get("judgment") or {}
    execution = raw.get("execution") or {}

    # 置信度以「执行录入」为准：信号只是判断侧，未验证不升置信（避免虚高）
    conf = 70 if n_trade > 0 else (45 if n_signal > 0 else 35)
    narrative = raw.get("read", "")

    # 补充判断/执行指标
    extra = []
    if judgment.get("rate") is not None:
        extra.append(f"判断命中率 {judgment['rate']}%")
    if execution.get("capture_rate") is not None:
        extra.append(f"执行跟单率 {execution['capture_rate']}%")
    if extra:
        narrative = narrative.rstrip("。") + " [" + "；".join(extra) + "]"

    risk_parts = []
    if n_trade == 0:
        risk_parts.append("执行样本为空，迭代建议暂不可靠；录入实际交易后启动执行纪律统计。")
    if execution.get("discipline_error"):
        risk_parts.append(
            f"执行纪律误差 {execution['discipline_error']} 次"
            f"（判断对没跟 {execution.get('missed_profit',0)} / 判断错还跟 {execution.get('acted_on_wrong',0)}）"
            f"→ 重点复盘交易纪律。")
    risk = " ".join(risk_parts)

    res = make_result("L8", "学习进化", "neutral", narrative, raw=raw,
                      signal={"direction": "neutral",
                              "judgment_rate": judgment.get("rate"),
                              "capture_rate": execution.get("capture_rate"),
                              "n_signal": n_signal, "n_trade": n_trade},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"),
                      upstream="（源头：trade_journal 交易日志，判断/执行分离）")
    ctx.put("L8", res.to_dict())
    return res
