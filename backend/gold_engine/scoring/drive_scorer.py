#!/usr/bin/env python3
"""L1: Gold Drive Factor Scoring.

Maps 8 driving factors to individual Bullish/Bearish/Neutral signals,
then computes a weighted composite score (0-100).

Scoring logic is rule-based and transparent:
  - Each factor has explicit thresholds for bull/bear determination
  - Weights from the user's specification (★1-5)
  - Final score = weighted sum of individual scores
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from ..data_adapter.gold_data import GoldFactors, FactorResult


@dataclass
class DriveScore:
    """Complete drive factor scoring result."""
    timestamp: str
    composite_score: float      # 0-100 weighted composite
    direction: str              # "bullish" / "bearish" / "neutral"
    factors: list[FactorResult] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0     # based on data coverage


# ── Factor scoring functions ────────────────────────────────────

def _score_tips(tips_yield: Optional[float], us_10y: float) -> FactorResult:
    """Score US 10Y TIPS real yield.
    
    Low real yield = bullish for gold (lower opportunity cost).
    High real yield = bearish for gold.
    
    Historical context: TIPS has ranged roughly 0% to 2.5% in recent years.
    """
    weight = 5
    if tips_yield is None:
        return FactorResult(
            name="实际利率(TIPS)", weight=weight, direction="neutral",
            score=50, value="数据缺失", source="estimated",
            note="TIPS收益率不可用，使用估算值"
        )
    
    # Thresholds
    if tips_yield <= 0.5:
        direction, score = "bullish", 85
    elif tips_yield <= 1.0:
        direction, score = "bullish", 72
    elif tips_yield <= 1.5:
        direction, score = "neutral_bullish", 58
    elif tips_yield <= 2.0:
        direction, score = "neutral", 50
    elif tips_yield <= 2.5:
        direction, score = "neutral_bearish", 35
    else:
        direction, score = "bearish", 20
    
    value_str = f"{tips_yield:.2f}% (US 10Y: {us_10y:.2f}%)"
    
    return FactorResult(
        name="实际利率(TIPS)", weight=weight, direction=direction,
        score=score, value=value_str, source="estimated",
        note=f"实际利率={tips_yield:.2f}%，{'压制' if direction.startswith('bear') else '支撑'}黄金"
    )


def _score_dxy(dxy: float, dxy_change: float) -> FactorResult:
    """Score US Dollar Index.
    
    Weak dollar = bullish for gold (inverse relationship).
    Strong dollar = bearish for gold.
    
    Recent range: 95-110, 100 is neutral zone.
    """
    weight = 5
    if dxy == 0:
        return FactorResult(
            name="美元指数DXY", weight=weight, direction="neutral",
            score=50, value="数据缺失", source="missing"
        )
    
    change_label = f"{dxy_change:+.2f}%"
    if dxy <= 98:
        direction, score = "bullish", 82
    elif dxy <= 100:
        direction, score = "bullish", 68
    elif dxy <= 102:
        direction, score = "neutral_bullish", 55
    elif dxy <= 105:
        direction, score = "neutral", 45
    elif dxy <= 108:
        direction, score = "neutral_bearish", 32
    else:
        direction, score = "bearish", 18
    
    value_str = f"{dxy:.2f} ({change_label})"
    
    return FactorResult(
        name="美元指数DXY", weight=weight, direction=direction,
        score=score, value=value_str, source="thsdk",
        note=f"DXY={dxy:.2f}，{'走弱利好' if 'bull' in direction else '走强利空'}黄金"
    )


def _score_fed(fed_rate: float, fed_direction: str) -> FactorResult:
    """Score Fed rate expectations.
    
    Lower rates / cutting cycle = bullish for gold.
    Higher rates / hiking cycle = bearish for gold.
    """
    weight = 4
    if fed_rate == 0:
        return FactorResult(
            name="美联储利率", weight=weight, direction="neutral",
            score=50, value="数据缺失", source="missing"
        )
    
    # Determine from rate level + direction
    if fed_direction == "cut" or fed_rate <= 3.5:
        direction, score = "bullish", 78
    elif fed_direction == "pause_low" or fed_rate <= 4.0:
        direction, score = "neutral_bullish", 62
    elif fed_direction == "pause" or fed_rate <= 4.5:
        direction, score = "neutral", 50
    elif fed_rate <= 5.0:
        direction, score = "neutral_bearish", 38
    else:
        direction, score = "bearish", 22
    
    dir_label = {"cut": "降息", "hike": "加息", "pause": "暂停", "unknown": "未知"}.get(fed_direction, fed_direction)
    value_str = f"{fed_rate:.2f}% ({dir_label})"
    
    return FactorResult(
        name="美联储利率", weight=weight, direction=direction,
        score=score, value=value_str, source="akshare",
        note=f"联邦基金利率{fed_rate:.2f}%，政策方向：{dir_label}"
    )


def _score_gld_etf(gld_price: float, gld_volume: int, gld_change: float,
                   inv_change: float, flow_streak: int = 0) -> FactorResult:
    """Score gold ETF flow.

    ETF inflows = bullish (investors buying gold).
    ETF outflows = bearish (investors selling gold).

    Uses GLD volume + price change + consecutive flow streak (from DB history).
    flow_streak: positive = consecutive inflow days, negative = outflow days.
    """
    weight = 4
    if gld_price == 0:
        # Even if GLD real-time is missing, flow_streak from XAU/518880 history
        # can still provide signal
        if flow_streak != 0:
            streak_note = f"连续{'流入' if flow_streak > 0 else '流出'}{abs(flow_streak)}天"
            if flow_streak >= 5:
                return FactorResult(
                    name="黄金ETF(GLD)", weight=weight, direction="bullish",
                    score=70, value="GLD实时缺失", source="streak_only",
                    note=f"GLD实时数据缺失，但XAU/518880历史{streak_note}"
                )
            elif flow_streak >= 3:
                return FactorResult(
                    name="黄金ETF(GLD)", weight=weight, direction="neutral_bullish",
                    score=60, value="GLD实时缺失", source="streak_only",
                    note=f"GLD实时数据缺失，但XAU/518880历史{streak_note}"
                )
            elif flow_streak <= -5:
                return FactorResult(
                    name="黄金ETF(GLD)", weight=weight, direction="bearish",
                    score=30, value="GLD实时缺失", source="streak_only",
                    note=f"GLD实时数据缺失，但XAU/518880历史{streak_note}"
                )
            elif flow_streak <= -3:
                return FactorResult(
                    name="黄金ETF(GLD)", weight=weight, direction="neutral_bearish",
                    score=40, value="GLD实时缺失", source="streak_only",
                    note=f"GLD实时数据缺失，但XAU/518880历史{streak_note}"
                )
        return FactorResult(
            name="黄金ETF(GLD)", weight=weight, direction="neutral",
            score=50, value="数据缺失", source="missing"
        )

    # Volume signal
    vol_m = gld_volume / 1_000_000
    vol_signal = "high" if vol_m > 8 else ("moderate" if vol_m > 4 else "low")

    # Direction from price change + inventory
    if gld_change > 0.5 and (inv_change > 0 or vol_signal == "high"):
        direction, score = "bullish", 78
    elif gld_change > 0:
        direction, score = "neutral_bullish", 62
    elif gld_change > -0.5:
        direction, score = "neutral", 50
    elif gld_change > -1.5:
        direction, score = "neutral_bearish", 35
    else:
        direction, score = "bearish", 22

    # Flow streak adjustment (time-series dimension)
    streak_note = ""
    if flow_streak >= 5:
        score = min(score + 10, 95)
        streak_note = f"，连续流入{flow_streak}天↑"
    elif flow_streak >= 3:
        score = min(score + 5, 90)
        streak_note = f"，连续流入{flow_streak}天↑"
    elif flow_streak <= -5:
        score = max(score - 10, 5)
        streak_note = f"，连续流出{abs(flow_streak)}天↓"
    elif flow_streak <= -3:
        score = max(score - 5, 10)
        streak_note = f"，连续流出{abs(flow_streak)}天↓"

    value_str = f"${gld_price:.2f} ({gld_change:+.2f}%) 量{vol_m:.1f}M"

    return FactorResult(
        name="黄金ETF(GLD)", weight=weight, direction=direction,
        score=score, value=value_str, source="thsdk",
        note=f"GLD {gld_change:+.2f}%，成交量{vol_m:.1f}M，库存变动{inv_change:+.1f}t{streak_note}"
    )


def _score_central_bank(buying: Optional[float], trend: str) -> FactorResult:
    """Score central bank gold buying.
    
    Consistent buying = bullish (structural demand).
    Selling = bearish.
    """
    weight = 4
    if buying is None:
        return FactorResult(
            name="央行购金", weight=weight, direction="neutral",
            score=50, value="数据缺失", source="missing"
        )
    
    if buying > 30:
        direction, score = "bullish", 82
    elif buying > 10:
        direction, score = "bullish", 70
    elif buying > 0:
        direction, score = "neutral_bullish", 58
    elif buying == 0:
        direction, score = "neutral", 50
    elif buying > -20:
        direction, score = "neutral_bearish", 35
    else:
        direction, score = "bearish", 20
    
    value_str = f"净买入{buying:.0f}吨 ({trend})"
    
    return FactorResult(
        name="央行购金", weight=weight, direction=direction,
        score=score, value=value_str, source="WGC(新闻)",
        note=f"全球央行月度净购金{buying:.0f}吨，{trend}"
    )


def _score_oil(oil_price: float, oil_change: float) -> FactorResult:
    """Score crude oil price.
    
    Oil up = inflation pressure up = potentially bullish for gold (inflation hedge).
    Oil down = disinflation = potentially bearish for gold.
    But relationship is not always stable.
    """
    weight = 3
    if oil_price == 0:
        return FactorResult(
            name="原油WTI", weight=weight, direction="neutral",
            score=50, value="数据缺失", source="missing"
        )
    
    # Oil as inflation proxy
    if oil_change > 2:
        direction, score = "bullish", 65     # inflation fear
    elif oil_change > 0:
        direction, score = "neutral_bullish", 55
    elif oil_change > -2:
        direction, score = "neutral", 50
    else:
        direction, score = "neutral_bearish", 42
    
    value_str = f"${oil_price:.2f} ({oil_change:+.2f}%)"
    
    return FactorResult(
        name="原油WTI", weight=weight, direction=direction,
        score=score, value=value_str, source="akshare",
        note=f"WTI={oil_price:.2f}，{'通胀压力↑' if 'bull' in direction else '通胀压力→'} "
             f"但原油-黄金传导不稳定"
    )


def _score_geopolitical(risk_score: float) -> FactorResult:
    """Score geopolitical risk.
    
    Higher risk = bullish for gold (safe haven demand).
    Lower risk = neutral/bearish.
    """
    weight = 3
    if risk_score >= 7:
        direction, score = "bullish", 78
    elif risk_score >= 5:
        direction, score = "neutral_bullish", 62
    elif risk_score >= 3:
        direction, score = "neutral", 50
    else:
        direction, score = "neutral", 48
    
    value_str = f"{risk_score:.1f}/10"
    
    return FactorResult(
        name="地缘政治风险", weight=weight, direction=direction,
        score=score, value=value_str, source="proxy",
        note=f"地缘风险评分{risk_score:.1f}/10，{'避险需求↑' if 'bull' in direction else '风险可控'}"
    )


def _score_breakeven(breakeven: Optional[float]) -> FactorResult:
    """Score breakeven inflation expectations.
    
    Rising breakeven = inflation fears = bullish for gold.
    Falling breakeven = disinflation = bearish for gold.
    """
    weight = 4
    if breakeven is None:
        return FactorResult(
            name="通胀预期(BE)", weight=weight, direction="neutral",
            score=50, value="数据缺失", source="missing"
        )
    
    if breakeven >= 2.8:
        direction, score = "bullish", 75
    elif breakeven >= 2.4:
        direction, score = "neutral_bullish", 60
    elif breakeven >= 2.0:
        direction, score = "neutral", 50
    else:
        direction, score = "neutral_bearish", 38
    
    value_str = f"{breakeven:.2f}%"
    
    return FactorResult(
        name="通胀预期(BE)", weight=weight, direction=direction,
        score=score, value=value_str, source="calculated",
        note=f"10Y盈亏平衡通胀率{breakeven:.2f}%"
    )


# ── Composite scoring ─────────────────────────────────────────

def score_drive_factors(gf: GoldFactors) -> DriveScore:
    """Score all 8 driving factors and compute composite.
    
    Returns DriveScore with individual factor scores and weighted composite.
    """
    factors = []
    total_weight = 0
    weighted_sum = 0.0
    covered = 0
    
    # 1. TIPS real yield ★5
    f_tips = _score_tips(gf.tips_10y_yield, gf.us_10y_yield)
    factors.append(f_tips)
    if f_tips.score != 50 or f_tips.source != "missing":
        covered += 1
    weighted_sum += f_tips.score * f_tips.weight
    total_weight += f_tips.weight
    
    # 2. DXY ★5
    f_dxy = _score_dxy(gf.dxy, gf.dxy_change_pct)
    factors.append(f_dxy)
    if f_dxy.source != "missing":
        covered += 1
    weighted_sum += f_dxy.score * f_dxy.weight
    total_weight += f_dxy.weight
    
    # 3. Fed rate ★4
    f_fed = _score_fed(gf.fed_rate, gf.fed_direction)
    factors.append(f_fed)
    if f_fed.source != "missing":
        covered += 1
    weighted_sum += f_fed.score * f_fed.weight
    total_weight += f_fed.weight
    
    # 4. GLD ETF ★4
    inv_change = gf.factors.get("gold_inventory", {}).get("value", 0)
    f_gld = _score_gld_etf(gf.gld_price, gf.gld_volume, gf.gld_change_pct,
                           inv_change, gf.flow_streak_days)
    factors.append(f_gld)
    if f_gld.source != "missing":
        covered += 1
    weighted_sum += f_gld.score * f_gld.weight
    total_weight += f_gld.weight
    
    # 5. Central bank ★4
    f_cb = _score_central_bank(gf.central_bank_buying, gf.factors["central_bank"]["trend"])
    factors.append(f_cb)
    if f_cb.source != "missing":
        covered += 1
    weighted_sum += f_cb.score * f_cb.weight
    total_weight += f_cb.weight
    
    # 6. Oil ★3
    f_oil = _score_oil(gf.oil_price, gf.oil_change_pct)
    factors.append(f_oil)
    if f_oil.source != "missing":
        covered += 1
    weighted_sum += f_oil.score * f_oil.weight
    total_weight += f_oil.weight
    
    # 7. Geopolitical ★3
    f_geo = _score_geopolitical(gf.geopolitical_risk)
    factors.append(f_geo)
    covered += 1
    weighted_sum += f_geo.score * f_geo.weight
    total_weight += f_geo.weight
    
    # 8. Breakeven inflation ★4
    f_be = _score_breakeven(gf.breakeven_inflation)
    factors.append(f_be)
    if f_be.source != "missing":
        covered += 1
    weighted_sum += f_be.score * f_be.weight
    total_weight += f_be.weight
    
    # Composite
    composite = weighted_sum / total_weight if total_weight > 0 else 50
    confidence = (covered / len(factors)) * 100
    
    # Direction from composite
    if composite >= 65:
        direction = "bullish"
    elif composite >= 55:
        direction = "neutral_bullish"
    elif composite >= 45:
        direction = "neutral"
    elif composite >= 35:
        direction = "neutral_bearish"
    else:
        direction = "bearish"
    
    # Summary
    bulls = [f for f in factors if "bull" in f.direction]
    bears = [f for f in factors if "bear" in f.direction]
    bull_factors = ", ".join(f"{f.name}({f.score:.0f})" for f in bulls[:3])
    bear_factors = ", ".join(f"{f.name}({f.score:.0f})" for f in bears[:3])
    
    if bulls and not bears:
        summary = f"全面看涨：{bull_factors}"
    elif bears and not bulls:
        summary = f"全面看空：{bear_factors}"
    elif len(bulls) > len(bears):
        summary = f"偏多（{len(bulls)}/{len(factors)}利好）：{bull_factors}"
    elif len(bears) > len(bulls):
        summary = f"偏空（{len(bears)}/{len(factors)}利空）：{bear_factors}"
    else:
        summary = "多空力量均衡"
    
    return DriveScore(
        timestamp=gf.timestamp,
        composite_score=round(composite, 1),
        direction=direction,
        factors=factors,
        summary=summary,
        confidence=round(confidence, 1),
    )
