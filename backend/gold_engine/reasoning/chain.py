#!/usr/bin/env python3
"""L4: Causal Reasoning Chain.

Builds a step-by-step causal chain from macro events → intermediate variables → gold price.
Each link in the chain has a confidence score based on data support.
Flags unsupported links as low-confidence.

Example chain:
  Middle East conflict → Oil price ↑ [conf: 85%]
  → Inflation expectation ↑ [conf: 70%]
  → US 10Y yield ↑ [conf: 80%]
  → Real rate ↑ [conf: 75%]
  → Gold ↓ [conf: 65%]
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional

from ..data_adapter.gold_data import GoldFactors
from ..scoring.drive_scorer import DriveScore
from ..narrative.detector import GoldNarrative


@dataclass
class ChainLink:
    """A single link in the causal chain."""
    from_event: str
    to_event: str
    confidence: float        # 0-100
    has_data: bool           # whether data supports this link
    note: str = ""


@dataclass
class ReasoningChain:
    """Complete causal reasoning chain."""
    timestamp: str
    chain: List[ChainLink] = field(default_factory=list)
    overall_confidence: float = 0.0
    summary: str = ""
    unsupported_links: list = field(default_factory=list)


def _build_inflation_chain(gf: GoldFactors) -> tuple[List[ChainLink], float]:
    """Build chain: Oil/Demand → Inflation → Rates → Real Rate → Gold."""
    links = []
    conf_penalty = 0
    
    # Link 1: Oil/commodity → Inflation expectation
    if gf.oil_price > 0 and gf.breakeven_inflation:
        if gf.oil_change_pct > 1:
            links.append(ChainLink(
                from_event=f"油价上涨{gf.oil_change_pct:+.1f}% (${gf.oil_price:.0f})",
                to_event=f"通胀预期上升至{gf.breakeven_inflation:.2f}%",
                confidence=80,
                has_data=True,
                note="油价是通胀的主要传导渠道"
            ))
        elif gf.oil_change_pct < -1:
            links.append(ChainLink(
                from_event=f"油价下跌{gf.oil_change_pct:+.1f}% (${gf.oil_price:.0f})",
                to_event=f"通胀预期降至{gf.breakeven_inflation:.2f}%",
                confidence=80,
                has_data=True,
            ))
        else:
            links.append(ChainLink(
                from_event=f"油价平稳 (${gf.oil_price:.0f})",
                to_event=f"通胀预期{gf.breakeven_inflation:.2f}%",
                confidence=60,
                has_data=True,
            ))
    
    # Link 2: Inflation → US bond yields
    if gf.breakeven_inflation and gf.us_10y_yield > 0:
        if gf.breakeven_inflation >= 2.5:
            links.append(ChainLink(
                from_event=f"通胀预期偏高({gf.breakeven_inflation:.2f}%)",
                to_event=f"美债10Y收益率{gf.us_10y_yield:.2f}%",
                confidence=75,
                has_data=True,
                note="通胀预期推升名义收益率"
            ))
    
    # Link 3: Nominal yields → Real rate
    if gf.us_10y_yield > 0 and gf.tips_10y_yield:
        links.append(ChainLink(
            from_event=f"美债10Y={gf.us_10y_yield:.2f}%",
            to_event=f"实际利率(TIPS)={gf.tips_10y_yield:.2f}%",
            confidence=85,
            has_data=True,
            note="实际利率 = 名义收益率 - 通胀预期"
        ))
    elif gf.us_10y_yield > 0:
        links.append(ChainLink(
            from_event=f"美债10Y={gf.us_10y_yield:.2f}%",
            to_event="实际利率=估算值",
            confidence=45,
            has_data=False,
            note="⚠️ 缺少TIPS实际数据，此环节为估算"
        ))
    
    # Link 4: Real rate → Gold price
    if gf.tips_10y_yield and gf.gold_price > 0:
        direction = "上涨" if gf.tips_10y_yield < 1.5 else "下跌" if gf.tips_10y_yield > 2.0 else "震荡"
        links.append(ChainLink(
            from_event=f"实际利率={gf.tips_10y_yield:.2f}%",
            to_event=f"黄金{direction} (${gf.gold_price:.0f}, {gf.gold_change_pct:+.1f}%)",
            confidence=70,
            has_data=True,
            note="实际利率是黄金最核心的驱动因子"
        ))
    
    confidence = max(30, 85 - len([l for l in links if not l.has_data]) * 20)
    return links, confidence


def _build_dollar_chain(gf: GoldFactors) -> tuple[List[ChainLink], float]:
    """Build chain: Fed/DXY → Dollar strength → Gold."""
    links = []
    
    if gf.dxy > 0:
        dxy_trend = "走弱" if gf.dxy < 100 else ("走强" if gf.dxy > 105 else "中性")
        links.append(ChainLink(
            from_event=f"美联储利率{gf.fed_rate:.1f}% ({gf.fed_direction})",
            to_event=f"美元指数{dxy_trend}({gf.dxy:.2f})",
            confidence=70,
            has_data=True,
        ))
        
        links.append(ChainLink(
            from_event=f"美元指数{gf.dxy:.2f} ({gf.dxy_change_pct:+.1f}%)",
            to_event=f"黄金${gf.gold_price:.0f} ({gf.gold_change_pct:+.1f}%)",
            confidence=75,
            has_data=True,
            note="美元走弱→黄金走强的反向关系成立"
        ))
    
    return links, 72


def _build_safehaven_chain(gf: GoldFactors) -> tuple[List[ChainLink], float]:
    """Build chain: Geopolitical → Risk sentiment → Safe haven → Gold."""
    links = []
    
    if gf.geopolitical_risk >= 5:
        links.append(ChainLink(
            from_event=f"地缘风险评分{gf.geopolitical_risk:.1f}/10",
            to_event="避险需求上升",
            confidence=65,
            has_data=True,
        ))
        links.append(ChainLink(
            from_event="避险需求上升",
            to_event=f"黄金${gf.gold_price:.0f} ({gf.gold_change_pct:+.1f}%)",
            confidence=60,
            has_data=True,
            note="避险逻辑在不同事件中传导权重不同"
        ))
    else:
        links.append(ChainLink(
            from_event=f"地缘风险{gf.geopolitical_risk:.1f}/10 (可控)",
            to_event="避险逻辑不主导今日行情",
            confidence=55,
            has_data=True,
        ))
    
    return links, 55


def _build_centralbank_chain(gf: GoldFactors) -> tuple[List[ChainLink], float]:
    """Build chain: Dollar credibility → Central bank buying → Structural demand."""
    links = []
    
    if gf.central_bank_buying and gf.central_bank_buying > 20:
        links.append(ChainLink(
            from_event=f"全球央行月度净购金{gf.central_bank_buying:.0f}吨",
            to_event="结构性需求支撑金价底部",
            confidence=80,
            has_data=True,
            note="央行购金是中长期结构性因素"
        ))
    
    return links, 80


def build_reasoning_chain(ds: DriveScore, gf: GoldFactors, narrative: GoldNarrative) -> ReasoningChain:
    """Build the causal reasoning chain based on detected narrative.
    
    Constructs 1-3 parallel causal chains depending on what themes are active.
    Each chain traces from a macro event to the gold price through intermediate steps.
    """
    all_links = []
    unsupported = []
    
    # Build chains based on active narrative
    primary = narrative.primary_theme
    
    # Always build the inflation/rates chain (core driver)
    if gf.us_10y_yield > 0 or gf.tips_10y_yield or gf.breakeven_inflation:
        links1, conf1 = _build_inflation_chain(gf)
        all_links.extend(links1)
    
    # Dollar chain
    if gf.dxy > 0 and ("美元" in primary or "降息" in primary):
        links2, conf2 = _build_dollar_chain(gf)
        all_links.extend(links2)
    
    # Safe haven chain
    if "地缘" in primary or "避险" in primary:
        links3, conf3 = _build_safehaven_chain(gf)
        all_links.extend(links3)
    
    # Central bank chain
    if "信用" in primary:
        links4, conf4 = _build_centralbank_chain(gf)
        all_links.extend(links4)
    
    # Fallback: always add dollar chain
    if not all_links and gf.dxy > 0:
        links2, conf2 = _build_dollar_chain(gf)
        all_links.extend(links2)
    
    if not all_links and gf.gold_price > 0:
        all_links.append(ChainLink(
            from_event="多因子综合驱动",
            to_event=f"黄金${gf.gold_price:.0f} ({gf.gold_change_pct:+.1f}%)",
            confidence=40,
            has_data=False,
            note="⚠️ 多个数据源缺失，推理链可信度较低"
        ))
    
    # Calculate overall confidence
    if all_links:
        avg_conf = sum(l.confidence for l in all_links) / len(all_links)
        # Penalty for unsupported links
        unsupported_count = sum(1 for l in all_links if not l.has_data)
        overall_conf = max(25, avg_conf - unsupported_count * 10)
    else:
        overall_conf = 30
    
    # Collect unsupported
    unsupported = [l for l in all_links if not l.has_data]
    
    # Build summary
    if unsupported:
        summary = f"推理链整体可信度{overall_conf:.0f}%，{len(unsupported)}个环节缺乏数据支撑"
    else:
        summary = f"推理链完整，整体可信度{overall_conf:.0f}%"
    
    return ReasoningChain(
        timestamp=ds.timestamp,
        chain=all_links,
        overall_confidence=round(overall_conf, 1),
        summary=summary,
        unsupported_links=[l.note for l in unsupported],
    )
