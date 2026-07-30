# -*- coding: utf-8 -*-
"""
equity_engine/analysis.py —— A股环境判断逻辑（Phase 1.8-B）

═══════════════════════════════════════════════════════════════
设计铁律（呼应 Phase 1.8-B 用户警示：不要直接搬运 _derive_a_share_env）：

  本文件 = 纯判断逻辑（judgment），零 I/O、零 DB、零渲染。
  只接收「已经抽取好的扁平参数」→ 输出「结构化的 A股环境判断」。

  数据读取（brain/tree → 扁平参数）放在 adapter.py。
  文案生成（判断 → 人类可读句子）放在 os2_report 渲染层。
  三者分离，避免 commodity adapter 早期「数据+判断+文案」全挤在一个函数」的老问题。

输入 params（由 adapter 抽取后传入）：
  {
    "can_buy":          "YES" | "CAUTION" | "NO" | "UNKNOWN",  # IC 裁决
    "direction":        str,                                     # IC 方向
    "up_ratio":         float,                                   # 上涨家数占比 0-1 或 0-100
    "main_lines":       [{"sector": str, "stage": str}, ...],     # L4 主线
    "sentiment_score":  float,                                   # results.sentiment.score 0-100
    "risk_state_label": str,                                     # "Risk On"|"Neutral"|"Risk Off"
  }

输出 dict（AIP 六元组 + legacy 上下文）：
  {
    "state": str, "score": float, "trend": str,
    "drivers": [str], "risks": [str], "confidence": float,
    # legacy 上下文（供 snapshot / report 兼容，不进入跨资产比较）
    "can_buy", "direction", "breadth_pct", "breadth_label",
    "top_sector", "main_lines_names",
  }

边界（严守用户方法论红线）：
  - 不产出任何买卖指令 / 仓位建议（position_pct）；那是 IC/CIO 的权责。
  - score 是「环境强弱合成」，不是预测，命名透明、可解释。
  - 缺数据时降级到中性，绝不编造。
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import math


# ── 配置（透明、可解释，非黑盒）────────────────────────────────
# IC 裁决 → 环境评分权重（满分 35）
_IC_WEIGHT = {"YES": 35.0, "CAUTION": 18.0, "NO": 0.0}
_IC_DEFAULT = 5.0
# 市场广度 → 环境评分权重（满分 35，线性 0-100% → 0-35）
_BREADTH_MAX = 35.0
# 主线清晰度 → 环境评分权重（满分 15）
_SECTOR_BONUS = 15.0
# 情绪层 → 环境评分微调（±5，从 50 居中偏移）
_SENTIMENT_GAIN = 0.10

# 语义化状态映射（AIP §3：state 必须语义化，不复用「上涨趋势」等旧商品词）
_STATE_MAP = {
    ("YES", "up"):       "趋势修复",
    ("YES", "sideways"): "偏多震荡",
    ("YES", "down"):     "偏多承压",
    ("CAUTION", "up"):   "中性偏强",
    ("CAUTION", "sideways"): "中性整理",
    ("CAUTION", "down"): "中性偏弱",
    ("NO", "up"):        "防御中反弹",
    ("NO", "sideways"):  "偏弱整理",
    ("NO", "down"):      "偏弱防御",
    ("UNKNOWN", "up"):   "信号待确认",
    ("UNKNOWN", "sideways"): "信号待确认",
    ("UNKNOWN", "down"): "信号待确认",
}


def _breadth_pct(up_ratio) -> int:
    """上涨家数占比 → 整数百分比（兼容 0-1 与 0-100 两种口径）。"""
    try:
        v = float(up_ratio)
    except (TypeError, ValueError):
        return 50
    if v <= 1:
        return round(v * 100)
    return round(v)


def analyze_equity(params: dict) -> dict:
    """纯函数：把扁平参数映射为 A股环境判断（AIP 六元组 + legacy 上下文）。

    不抛异常；任何字段缺失都降级到中性，保证下游 CIO 永不吃到 None。
    """
    params = params or {}
    can_buy = str(params.get("can_buy", "UNKNOWN")).upper()
    if can_buy not in ("YES", "CAUTION", "NO"):
        can_buy = "UNKNOWN"
    direction = str(params.get("direction", "") or "")
    up_pct = _breadth_pct(params.get("up_ratio", 0.5))
    main_lines = [m for m in (params.get("main_lines", []) or []) if isinstance(m, dict) and m.get("sector")]
    sentiment_score = params.get("sentiment_score", 50)
    risk_label = str(params.get("risk_state_label", "") or "")

    has_main = bool(main_lines)
    top_sector = main_lines[0].get("sector", "") if main_lines else ""
    main_names = [m.get("sector", "") for m in main_lines]

    # ── 1. score（环境强弱合成，透明加权）──
    ic_comp = _IC_WEIGHT.get(can_buy, _IC_DEFAULT)
    breadth_comp = max(0.0, min(_BREADTH_MAX, up_pct * (_BREADTH_MAX / 100.0)))
    sector_comp = _SECTOR_BONUS if has_main else 0.0
    try:
        sent_off = max(-5.0, min(5.0, (float(sentiment_score) - 50.0) * _SENTIMENT_GAIN))
    except (TypeError, ValueError):
        sent_off = 0.0
    score = max(0.0, min(100.0, ic_comp + breadth_comp + sector_comp + sent_off))

    # ── 2. trend（动量方向：IC 裁决 + 广度联合判断）──
    if can_buy == "YES" and up_pct >= 55:
        trend = "up"
    elif can_buy == "NO" or up_pct <= 45:
        trend = "down"
    else:
        trend = "sideways"

    # ── 3. state（语义化）──
    state = _STATE_MAP.get((can_buy, trend), "信号待确认")

    # ── 4. drivers（为什么）──
    drivers = []
    if can_buy == "YES":
        drivers.append("IC 裁决偏多（可买）")
    elif can_buy == "NO":
        drivers.append("IC 裁决偏空（禁止交易）")
    elif can_buy == "CAUTION":
        drivers.append("IC 裁决中性（谨慎）")
    else:
        drivers.append("IC 裁决信号缺失")
    if up_pct >= 55:
        drivers.append(f"市场广度改善（上涨家数占比 {up_pct}%）")
    elif up_pct <= 45:
        drivers.append(f"市场广度偏弱（上涨家数占比 {up_pct}%）")
    else:
        drivers.append(f"市场广度中性（上涨家数占比 {up_pct}%）")
    if has_main and top_sector:
        drivers.append(f"主线清晰：{top_sector}")
    if risk_label == "Risk On":
        drivers.append("全球风险偏好回升（Risk On）")
    if not drivers:
        drivers = ["市场信号中性，等待确认"]

    # ── 5. risks（什么会错）──
    risks = []
    if can_buy != "YES":
        risks.append("IC 未给买入确认")
    if up_pct < 50:
        risks.append(f"上涨扩散不足（广度 {up_pct}%）")
    if not has_main:
        risks.append("缺乏清晰主线")
    if risk_label == "Risk Off":
        risks.append("全球避险情绪升温（Risk Off）")
    risks.append("成交与资金确认待盘中观察（图形买点人工定）")
    if not risks:
        risks = ["数据不足，信号待验证"]

    # ── 6. confidence（信号质量：IC 与广度是否共振）──
    if can_buy == "UNKNOWN":
        conf = 0.30
    elif can_buy in ("YES", "NO") and has_main and abs(up_pct - 50) >= 5:
        conf = 0.75
    elif can_buy in ("YES", "NO"):
        conf = 0.60
    else:  # CAUTION
        conf = 0.55
    conf = max(0.10, min(0.95, conf))

    breadth_label = "普涨" if up_pct >= 60 else ("普跌" if up_pct <= 40 else "分化")

    return {
        "state": state,
        "score": round(score, 2),
        "trend": trend,
        "drivers": drivers,
        "risks": risks,
        "confidence": round(conf, 4),
        # ── legacy 上下文（供 snapshot / report 兼容）──
        "can_buy": can_buy,
        "direction": direction,
        "breadth_pct": up_pct,
        "breadth_label": breadth_label,
        "top_sector": top_sector or "—",
        "main_lines_names": main_names,
    }
