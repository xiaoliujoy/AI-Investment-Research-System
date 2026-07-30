# -*- coding: utf-8 -*-
"""
asset_intelligence/protocol.py —— Asset Intelligence Protocol 核心契约（Phase 1.8）

═══════════════════════════════════════════════════════════════
AssetIntelligence 六元组（统一投资语言）——

  asset_class  str   资产类别（见 ASSET_CLASSES 白名单）
  symbol       str   标的代码（"AU0" | "CU0" | "SC0" | "A_SHARE" | "US10Y" | "DXY" ...）
  name         str   人类可读名（"沪铜" | "A股" | "美债10Y" | "美元指数"）
  state        str   资产自身状态（语义化，见 docs/asset-intelligence-protocol.md §3）
  score        float 0-100 强弱（越高 = 越 favorable / 越占优）
  trend        str   "up" | "down" | "sideways"（动量方向，由 20 日斜率阈值派生）
  drivers      list[str]  为什么（因果驱动，≥1 条，见 §5）
  risks        list[str]  什么会错（失效条件，≥1 条，见 §6）
  confidence   float 0-1  浮点可信度（见 §7）
  detail       dict  引擎特定扩展字段（可选，不进入跨资产比较）

设计原则（呼应 _DB_PATH 可靠性教训）：
  - 协议层零外部依赖（不 import 数据库 / 评分引擎），只做契约与工具函数。
  - 所有边界由 validator 把关（见 validator.py），adapter 只负责「填字段」。
  - 缺数据 / 缺链路 → 用 make_skeleton / make_cash_hold 注册空壳，绝不编造评分。
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────────────────────
# 白名单 / 枚举
# ─────────────────────────────────────────────────────────────
ASSET_CLASSES = {
    "equity",    # 股票（含 A股、个股、指数）
    "commodity", # 商品（黄金/铜/原油/白银/螺纹…）
    "bond",      # 债券（利率债/信用债，收益率曲线为核心）
    "etf",       # 交易所基金（底层资产评分聚合）
    "cash",      # 现金 / 货币基金（持有 / 观望）
    "crypto",    # 加密货币（BTC 等，风险偏好代理）
    "fx",        # 外汇（DXY / 汇率）
}

# trend 仅三个合法值（统一动量口径）
TRENDS = {"up", "down", "sideways"}

# stage（旧商品用语）→ trend（AIP 统一动量）映射
STAGE_TO_TREND = {
    "上涨趋势": "up",
    "下跌趋势": "down",
    "震荡整理": "sideways",
}


# ─────────────────────────────────────────────────────────────
# 核心对象
# ─────────────────────────────────────────────────────────────
@dataclass
class AssetIntelligence:
    asset_class: str
    symbol: str
    name: str
    state: str
    score: float
    trend: str
    drivers: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.0
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为纯 dict（供 CIO / 渲染层 / JSON 流动）。"""
        d = asdict(self)
        # 浮点保留可读性
        d["score"] = round(float(self.score), 2)
        d["confidence"] = round(float(self.confidence), 4)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AssetIntelligence":
        """从 dict 构造（缺失可选字段回退默认，不抛异常）。"""
        return cls(
            asset_class=str(d.get("asset_class", "")),
            symbol=str(d.get("symbol", "")),
            name=str(d.get("name", "")),
            state=str(d.get("state", "")),
            score=float(d.get("score", 0.0) or 0.0),
            trend=str(d.get("trend", "sideways")),
            drivers=list(d.get("drivers", []) or []),
            risks=list(d.get("risks", []) or []),
            confidence=float(d.get("confidence", 0.0) or 0.0),
            detail=dict(d.get("detail", {}) or {}),
        )


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────
def confidence_label(c: float) -> str:
    """0-1 可信度 → 中文标签（高 / 中 / 低）。"""
    c = clamp_confidence(c)
    if c >= 0.7:
        return "高"
    if c >= 0.4:
        return "中"
    return "低"


def clamp_confidence(c: float) -> float:
    """confidence 越界 clamp 到 [0, 1]（绝不抛异常）。"""
    try:
        v = float(c)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def clamp_score(s: float) -> float:
    """score 越界 clamp 到 [0, 100]。"""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return 50.0
    return max(0.0, min(100.0, v))


def derive_trend_from_stage(stage: str) -> str:
    """从旧商品 stage 文本派生统一 trend（兼容层；最终由 20 日斜率派生）。"""
    return STAGE_TO_TREND.get(stage, "sideways")


def derive_trend_from_slope(slope_20d_pct: float, threshold: float = 0.3) -> str:
    """由 20 日斜率（归一化日均变动 %）派生 trend（AIP §4 规范）。

    slope_20d_pct >  +T1 → up
    slope_20d_pct <  -T1 → down
    否则                → sideways
    """
    try:
        s = float(slope_20d_pct)
    except (TypeError, ValueError):
        return "sideways"
    if s > threshold:
        return "up"
    if s < -threshold:
        return "down"
    return "sideways"


# ─────────────────────────────────────────────────────────────
# 空壳资产注册（Phase 1.8 边界：只注册、不编造评分）
# ─────────────────────────────────────────────────────────────
_NO_LINK_DRIVER = "暂无可靠数据链路，未参与评分"
_NO_LINK_RISK = "数据链路未建立，信号不启用"


def make_cash_hold() -> AssetIntelligence:
    """现金：变量决定，几乎恒为「持有」（高置信，不参与强弱排序）。"""
    return AssetIntelligence(
        asset_class="cash",
        symbol="CASH",
        name="现金",
        state="持有",
        score=50.0,
        trend="sideways",
        drivers=["环境变量决定，作为观望与流动性缓冲"],
        risks=["机会成本：踏空风险"],
        confidence=0.9,
        detail={"note": "现金为基准资产，不代表看空；用于风险预算与等待机会。"},
    )


def make_skeleton(asset_class: str, symbol: str, name: str,
                  state: str = "待接入") -> AssetIntelligence:
    """债券 / ETF / Crypto / FX 的空壳注册：明确标注「未启用」，绝不编造评分。

    这些资产在 Phase 1.8 没有可靠数据链路，提前接入只会制造虚假的统一。
    空壳通过校验（字段完整、非空、范围合法），但不进入机会排序。
    """
    if asset_class not in ASSET_CLASSES:
        raise ValueError(f"非法 asset_class: {asset_class}")
    return AssetIntelligence(
        asset_class=asset_class,
        symbol=symbol,
        name=name,
        state=state,
        score=50.0,
        trend="sideways",
        drivers=[_NO_LINK_DRIVER],
        risks=[_NO_LINK_RISK],
        confidence=0.0,
        detail={"skeleton": True, "enabled": False},
    )
