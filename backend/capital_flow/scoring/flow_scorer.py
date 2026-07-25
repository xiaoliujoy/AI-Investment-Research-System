# -*- coding: utf-8 -*-
"""Flow Score - 资金流评分系统.

5-layer capital flow scoring (M1-M5):
  M1 Global Liquidity: DXY + UST + VIX
  M2 Cross-Asset: commodity momentum
  M3 ETF: net purchase/redemption
  M4 Sector: from existing L4 (passed in)
  M5 Individual: from existing L5 (passed in)

Each layer scored 0-100, with star rating (1-5 stars).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class LayerScore:
    """Single layer flow score."""
    name: str = ""
    name_cn: str = ""
    score: float = 0.0
    stars: int = 0
    direction: str = ""   # inflow / outflow / neutral
    detail: str = ""


@dataclass
class FlowScore:
    """Complete flow score across 5 layers."""
    timestamp: str = ""
    m1_global: LayerScore = field(default_factory=LayerScore)
    m2_cross_asset: LayerScore = field(default_factory=LayerScore)
    m3_etf: LayerScore = field(default_factory=LayerScore)
    m4_sector: LayerScore = field(default_factory=LayerScore)
    m5_individual: LayerScore = field(default_factory=LayerScore)
    overall: float = 0.0
    overall_stars: int = 0
    one_liner: str = ""


def _stars(score: float) -> int:
    if score >= 85: return 5
    if score >= 70: return 4
    if score >= 55: return 3
    if score >= 40: return 2
    return 1


def _score_m1_global(commodity_snap, gold_data=None) -> LayerScore:
    """M1 Global Liquidity Score."""
    score = 50
    detail_parts = []

    # DXY from gold_engine or commodity
    if gold_data and gold_data.get("dxy"):
        dxy = gold_data["dxy"]
        if dxy <= 98:
            score += 20
            detail_parts.append("美元走弱(DXY=%.2f)" % dxy)
        elif dxy >= 105:
            score -= 20
            detail_parts.append("美元走强(DXY=%.2f)" % dxy)
        else:
            detail_parts.append("美元中性(DXY=%.2f)" % dxy)

    # US 10Y yield
    if gold_data and gold_data.get("us_10y_yield"):
        y10 = gold_data["us_10y_yield"]
        if y10 < 4.0:
            score += 15
            detail_parts.append("美债收益率偏低(%.2f%%)" % y10)
        elif y10 > 4.5:
            score -= 10
            detail_parts.append("美债收益率偏高(%.2f%%)" % y10)

    # Risk appetite from commodities
    if commodity_snap and commodity_snap.risk_appetite:
        ra = commodity_snap.risk_appetite
        if ra == "risk_on":
            score += 10
            detail_parts.append("商品风险偏好上升")
        elif ra == "risk_off":
            score -= 10
            detail_parts.append("商品风险偏好下降")

    score = max(10, min(100, score))
    direction = "inflow" if score >= 60 else ("outflow" if score < 40 else "neutral")
    return LayerScore(
        name="M1", name_cn="全球流动性",
        score=round(score), stars=_stars(score),
        direction=direction, detail=" | ".join(detail_parts) if detail_parts else "数据不足",
    )


def _score_m2_cross_asset(commodity_snap) -> LayerScore:
    """M2 Cross-Asset Score - commodity momentum."""
    if not commodity_snap or not commodity_snap.all_items:
        return LayerScore(name="M2", name_cn="跨资产", score=50, stars=3, direction="neutral", detail="数据不足")

    up_count = sum(1 for i in commodity_snap.all_items if i.change_pct > 0.5)
    down_count = sum(1 for i in commodity_snap.all_items if i.change_pct < -0.5)
    total = len(commodity_snap.all_items)

    if total == 0:
        return LayerScore(name="M2", name_cn="跨资产", score=50, stars=3, direction="neutral", detail="无数据")

    bull_ratio = up_count / total
    score = 50 + (bull_ratio - 0.3) * 80
    score = max(10, min(100, score))

    direction = "inflow" if score >= 60 else ("outflow" if score < 40 else "neutral")
    detail = "上涨%d/下跌%d/共%d" % (up_count, down_count, total)
    return LayerScore(
        name="M2", name_cn="跨资产",
        score=round(score), stars=_stars(score),
        direction=direction, detail=detail,
    )


def _score_m3_etf(etf_snap) -> LayerScore:
    """M3 ETF Fund Flow Score."""
    if not etf_snap:
        return LayerScore(name="M3", name_cn="ETF资金", score=50, stars=3, direction="neutral", detail="数据不足")

    # Count ETFs with significant share increase/decrease
    inflow_count = sum(1 for e in etf_snap.top_inflow if e.shares_change > 0)
    outflow_count = sum(1 for e in etf_snap.top_outflow if e.shares_change < 0)

    # Use main force inflow as secondary signal
    total_inflow = etf_snap.total_main_inflow

    score = 50
    if inflow_count > outflow_count + 2:
        score += 20
    elif outflow_count > inflow_count + 2:
        score -= 20

    if total_inflow > 1e9:
        score += 10
    elif total_inflow < -1e9:
        score -= 10

    if "no_prev_shares" in (etf_snap.gaps or []):
        score = 50  # reset if no previous data
        detail = "首日运行，无份额变化数据"
    else:
        detail = "净申购TOP: %s" % (etf_snap.top_inflow[0].name[:12] if etf_snap.top_inflow else "无")

    score = max(10, min(100, score))
    direction = "inflow" if score >= 60 else ("outflow" if score < 40 else "neutral")
    return LayerScore(
        name="M3", name_cn="ETF资金",
        score=round(score), stars=_stars(score),
        direction=direction, detail=detail,
    )


def calc_flow_score(commodity_snap=None, etf_snap=None, institution_flow=None,
                    gold_data=None, sector_score=None, individual_score=None) -> FlowScore:
    """Calculate complete 5-layer flow score."""
    fs = FlowScore(timestamp=datetime.now().isoformat())

    fs.m1_global = _score_m1_global(commodity_snap, gold_data)
    fs.m2_cross_asset = _score_m2_cross_asset(commodity_snap)
    fs.m3_etf = _score_m3_etf(etf_snap)

    # M4/M5 from existing system (passed in)
    if sector_score:
        fs.m4_sector = LayerScore(
            name="M4", name_cn="板块资金",
            score=sector_score, stars=_stars(sector_score),
            direction="inflow" if sector_score >= 60 else ("outflow" if sector_score < 40 else "neutral"),
            detail="来自L4资金共识",
        )
    else:
        fs.m4_sector = LayerScore(name="M4", name_cn="板块资金", score=50, stars=3, direction="neutral", detail="待接入")

    if individual_score:
        fs.m5_individual = LayerScore(
            name="M5", name_cn="个股资金",
            score=individual_score, stars=_stars(individual_score),
            direction="inflow" if individual_score >= 60 else ("outflow" if individual_score < 40 else "neutral"),
            detail="来自L5龙头体系",
        )
    else:
        fs.m5_individual = LayerScore(name="M5", name_cn="个股资金", score=50, stars=3, direction="neutral", detail="待接入")

    # Overall
    scores = [fs.m1_global.score, fs.m2_cross_asset.score, fs.m3_etf.score,
              fs.m4_sector.score, fs.m5_individual.score]
    fs.overall = round(sum(scores) / len(scores))
    fs.overall_stars = _stars(fs.overall)

    # One-liner
    parts = []
    for layer in [fs.m1_global, fs.m2_cross_asset, fs.m3_etf, fs.m4_sector, fs.m5_individual]:
        if layer.direction == "inflow":
            parts.append("%s流入" % layer.name_cn)
        elif layer.direction == "outflow":
            parts.append("%s流出" % layer.name_cn)
    fs.one_liner = "；".join(parts) if parts else "各层资金中性"

    return fs
