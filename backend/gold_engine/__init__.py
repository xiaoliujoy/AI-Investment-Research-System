#!/usr/bin/env python3
"""Gold Decision Engine — Cross Asset Engine Module 1.

Six-layer daily gold analysis:
  L1: Drive Factor Scoring (8 factors → composite 0-100)
  L2: Market Narrative Detection (what is gold trading on?)
  L3: Gold Cycle State Machine (6-phase lifecycle)
  L4: Causal Reasoning Chain (event → intermediate → price + confidence)
  L5: Conditional Trading Plan (if-then rules)
  L6: Risk Radar (weekly catalyst calendar)

Data sources: thsdk (GLD/DXY/XAUUSD), akshare (bonds/Fed/macro),
              neodata (WGC news/TIPS auctions/events)
"""

from .data_adapter.gold_data import get_all_gold_factors, GoldFactors
from .scoring.drive_scorer import score_drive_factors, DriveScore
from .narrative.detector import detect_narrative, GoldNarrative
from .cycle.state_machine import detect_cycle, GoldCycle
from .reasoning.chain import build_reasoning_chain, ReasoningChain
from .plan.trading_plan import generate_plan, TradingPlan
from .risk.radar import scan_risks, RiskRadar

__all__ = [
    "get_all_gold_factors", "GoldFactors",
    "score_drive_factors", "DriveScore",
    "detect_narrative", "GoldNarrative",
    "detect_cycle", "GoldCycle",
    "build_reasoning_chain", "ReasoningChain",
    "generate_plan", "TradingPlan",
    "scan_risks", "RiskRadar",
]
