# -*- coding: utf-8 -*-
"""
equity_engine/adapter.py —— A股 → Asset Intelligence Protocol 适配器（Phase 1.8-B）

═══════════════════════════════════════════════════════════════
职责拆分（关键，避免重蹈 commodity adapter 早期覆辙）：
  - 数据读取（brain/tree → 扁平参数）：本文件 _extract_params()
  - 判断逻辑（参数 → AIP 六元组）：equity_engine/analysis.analyze_equity
  - 协议封装（判断 → AssetIntelligence + 校验）：_wrap()
  - 文案生成（AIP → 人类可读句子）：os2_report 渲染层

本文件只做「抽取 + 封装」，不含任何判断分支、不含任何句子拼接。

输出 build_equity_signal(brain, tree) -> dict（AssetIntelligence，AIP 标准字段）：
  {
    "asset_class": "equity", "symbol": "CN_EQ_ALL", "name": "A股",
    "state": "...", "score": 0-100, "trend": up/down/sideways,
    "drivers": [...], "risks": [...], "confidence": 0-1, "confidence_label": "...",
    "detail": { "market_context": { breadth_pct, breadth_label,
                top_sector, main_lines_names }, "note": "..." }
                # market_context = 纯市场事实；IC 裁决(can_buy/direction) 不在此，
                # 属 IC Decision Layer，由 CIO 从 brain.committee 读取（详见 Phase 1.8-C）
  }

边界（与商品 adapter 一致）：
  - 不产出买卖指令 / 仓位建议（那是 IC/CIO 的权责）。
  - 失败降级：返回中性占位（can_buy=UNKNOWN），绝不抛异常、绝不崩日报；
    降级路径带 logger.warning(exc_info) 便于研发侧追踪根因。
═══════════════════════════════════════════════════════════════

用法：
  python equity_engine/adapter.py        # 打印 A股 AIP 信号（需传入 brain/tree 较繁，
                                          # 故 CLI 仅演示 fallback 与直接 analyze 路径）
"""
from __future__ import annotations

import os
import sys
import datetime
import logging

logger = logging.getLogger(__name__)

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from asset_intelligence.protocol import (
    AssetIntelligence,
    confidence_label,
)
from asset_intelligence.validator import validate_and_clean
from equity_engine.analysis import analyze_equity

# A股统一符号：A股是「资产集合」而非单一品种，故用 CN_EQ_ALL
# （区别于单只 ETF 如 CN_EQ_TECH，避免未来符号冲突）。
EQUITY_SYMBOL = "CN_EQ_ALL"
EQUITY_NAME = "A股"


# =============================================================================
# 1) 数据读取：brain/tree → 扁平参数（唯一会碰外部结构的地方）
# =============================================================================
def _extract_params(brain: dict, tree: dict) -> dict:
    """从 CIO 的 brain/tree 抽取 A股环境所需的扁平参数（不判断、不拼句子）。"""
    brain = brain or {}
    tree = tree or {}
    committee = brain.get("committee") or brain.get("decision") or {}
    can_buy = committee.get("can_buy", "UNKNOWN")
    direction = committee.get("direction", "")

    layers = (tree or {}).get("layers", {}) or {}
    sentiment = layers.get("sentiment", {}) or {}
    up_ratio = sentiment.get("up_ratio", 0.5)

    l4 = layers.get("L4_consensus", {}) or {}
    mains = (l4.get("main_lines", []) or [])[:3]
    main_lines = [
        {"sector": m.get("sector", ""), "stage": m.get("stage", "")}
        for m in mains if m.get("sector")
    ]

    results = brain.get("results", {}) or {}
    sentiment_score = (results.get("sentiment", {}) or {}).get("score", 50)

    return {
        "can_buy": can_buy,
        "direction": direction,
        "up_ratio": up_ratio,
        "main_lines": main_lines,
        "sentiment_score": sentiment_score,
        "risk_state_label": "",   # 由 CIO 外层在 snapshot 之后注入，避免 adapter 内重算宏观
    }


# =============================================================================
# 2) 协议封装：判断 → AssetIntelligence + 校验
# =============================================================================
def _wrap(params: dict) -> dict:
    """把分析结论包装成 AIP 标准 dict，过校验 + 自动清洗。"""
    r = analyze_equity(params)
    ai = AssetIntelligence(
        asset_class="equity",
        symbol=EQUITY_SYMBOL,
        name=EQUITY_NAME,
        state=r["state"],
        score=r["score"],
        trend=r["trend"],
        drivers=r["drivers"],
        risks=r["risks"],
        confidence=r["confidence"],
        # detail 只承载「市场事实」(market_context)，不承载 IC 裁决(can_buy/direction)。
        # can_buy/direction 属 IC Decision Layer，由 CIO 从 brain.committee 读取，
        # 不污染 AIP 的 detail（详见 Phase 1.8-C 用户架构审计 #4）。
        detail={
            "market_context": {
                "breadth_pct": r["breadth_pct"],
                "breadth_label": r["breadth_label"],
                "top_sector": r["top_sector"],
                "main_lines_names": r["main_lines_names"],
            },
            "note": "A股环境判断（IC裁决+广度+主线），不构成交易指令",
        },
    )
    cleaned, _ = validate_and_clean(ai)
    cleaned["confidence_label"] = confidence_label(cleaned["confidence"])
    return cleaned


def _neutral_fallback() -> dict:
    """中性占位：数据缺失时返回（can_buy=UNKNOWN），保证下游不崩。"""
    return _wrap({
        "can_buy": "UNKNOWN",
        "direction": "",
        "up_ratio": 0.5,
        "main_lines": [],
        "sentiment_score": 50,
        "risk_state_label": "",
    })


# =============================================================================
# 对外入口
# =============================================================================
def build_equity_signal(brain: dict, tree: dict) -> dict:
    """构建标准化 A股 AIP 信号（供 CIO 统一消费）。

    失败降级：返回中性占位 dict，绝不让上游崩溃。
    """
    try:
        params = _extract_params(brain, tree)
        return _wrap(params)
    except Exception as e:
        # 降级路径可追踪：研发侧能从日志定位根因，生产侧不崩日报（中性占位）。
        logger.warning(
            "equity_engine.adapter.build_equity_signal 降级为中性占位: %s", e, exc_info=e
        )
        return _neutral_fallback()


if __name__ == "__main__":
    # 演示：直接喂一组参数，看 AIP 输出（不依赖完整 brain/tree）
    demo = _wrap({
        "can_buy": "YES",
        "direction": "多",
        "up_ratio": 0.62,
        "main_lines": [{"sector": "半导体", "stage": "主升"}],
        "sentiment_score": 68,
        "risk_state_label": "Risk On",
    })
    print(f"\n=== A股 AIP 信号（{datetime.datetime.now().isoformat(timespec='seconds')}）===")
    print(f"  {demo['name']}（{demo['symbol']}）  评分{demo['score']}  "
          f"状态{demo['state']} 趋势{demo['trend']}  "
          f"置信{demo['confidence_label']}({demo['confidence']})")
    print(f"  驱动: {'；'.join(demo['drivers'])}")
    print(f"  风险: {'；'.join(demo['risks'])}")
    print(f"  detail: {demo['detail']}")
