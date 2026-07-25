# -*- coding: utf-8 -*-
"""Capital Flow Engine - 资金决策系统.

5-layer capital flow monitoring:
  M1 Global Liquidity (DXY, UST, VIX)
  M2 Cross-Asset (commodity futures)
  M3 ETF Fund Flow (shares change tracking)
  M4 A-share Sector (existing L4)
  M5 Individual Stock (existing L5)

Core output: Flow Intelligence - 5 daily questions.

Data sources: akshare (commodity/ETF/HSGT) + thsdk (GLD/DXY) + gold_engine
"""

from .data_adapter.commodity_data import get_commodity_snapshot, CommoditySnapshot
from .data_adapter.etf_data import get_etf_flow, ETFFlowSnapshot, ETFItem
from .data_adapter.institution_data import get_institution_flow, InstitutionFlow
from .scoring.flow_scorer import calc_flow_score, FlowScore
from .intelligence.five_questions import answer_five_questions, FlowIntelligence

__all__ = [
    "get_commodity_snapshot", "CommoditySnapshot",
    "get_etf_flow", "ETFFlowSnapshot", "ETFItem",
    "get_institution_flow", "InstitutionFlow",
    "calc_flow_score", "FlowScore",
    "answer_five_questions", "FlowIntelligence",
]
