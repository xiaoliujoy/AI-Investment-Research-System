# -*- coding: utf-8 -*-
"""
asset_intelligence —— Phase 1.8 统一投资语言契约（Asset Intelligence Protocol, AIP）

让股票 / 商品 / 债券 / ETF / 现金 / 加密 / 外汇 进入同一套投资语言：
每个资产引擎都回答同一组问题（state / score / trend / drivers / risks / confidence），
使 IC / CIO / Regime Engine 能用同一语义消费。

本包只定义「协议 + 校验 + 空壳资产注册」，不依赖任何数据库或评分逻辑。
"""
from asset_intelligence.protocol import (
    ASSET_CLASSES,
    TRENDS,
    AssetIntelligence,
    confidence_label,
    clamp_confidence,
    clamp_score,
    derive_trend_from_stage,
    make_cash_hold,
    make_skeleton,
)
from asset_intelligence.validator import (
    validate,
    validate_and_clean,
    run_protocol_health,
)

__all__ = [
    "ASSET_CLASSES",
    "TRENDS",
    "AssetIntelligence",
    "confidence_label",
    "clamp_confidence",
    "clamp_score",
    "derive_trend_from_stage",
    "make_cash_hold",
    "make_skeleton",
    "validate",
    "validate_and_clean",
    "run_protocol_health",
]
