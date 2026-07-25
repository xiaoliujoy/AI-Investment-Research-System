#!/usr/bin/env python3
"""L5: Conditional Trading Plan.

Generates conditional "if-then" trading rules, not simple buy/sell.
Based on cycle phase + factor scores + narrative.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List

from ..scoring.drive_scorer import DriveScore
from ..narrative.detector import GoldNarrative
from ..cycle.state_machine import GoldCycle


@dataclass
class ConditionRule:
    """A single condition-action rule."""
    condition: str
    action: str
    priority: str  # "A" / "B" / "C"


@dataclass
class TradingPlan:
    """Conditional trading plan for gold."""
    timestamp: str
    signal_level: str          # "A级机会" / "B级机会" / "C级机会" / "等待" / "回避"
    summary: str
    conditions: List[ConditionRule] = field(default_factory=list)
    position_guidance: str = ""


def generate_plan(ds: DriveScore, narrative: GoldNarrative, cycle: GoldCycle) -> TradingPlan:
    """Generate conditional trading plan based on all upper layers.
    
    Rules are conditional: "If X happens, then do Y" format.
    Not "buy" or "sell" — the user makes the final decision.
    """
    composite = ds.composite_score
    phase = cycle.current_phase
    conditions = []
    
    # Build conditions based on phase
    if phase in ("accumulation", "fermentation"):
        signal = "B级机会" if composite >= 65 else "C级机会"
        
        conditions.append(ConditionRule(
            condition="DXY跌破100 + GLD ETF连续3日流入",
            action="黄金A级做多机会，可考虑增加配置",
            priority="A",
        ))
        
        conditions.append(ConditionRule(
            condition="实际利率(TIPS)跌破1.5% + 央行购金>30t/月",
            action="基本面支撑强劲，维持当前持仓",
            priority="B",
        ))
        
        conditions.append(ConditionRule(
            condition="DXY反弹至103以上 或 GLD ETF连续流出",
            action="短期调整风险上升，减仓至观察仓位",
            priority="C",
        ))
    
    elif phase == "main_rise":
        signal = "A级机会"
        
        conditions.append(ConditionRule(
            condition="GLD ETF持续放量 + DXY弱势",
            action="趋势延续，继续持有，可适度加仓",
            priority="A",
        ))
        
        conditions.append(ConditionRule(
            condition="黄金单日跌幅>2% + ETF大幅流出",
            action="可能是正常回调而非趋势反转，观察2-3日",
            priority="B",
        ))
    
    elif phase == "euphoria":
        signal = "C级机会"
        
        conditions.append(ConditionRule(
            condition="RSI>80 或 价格加速上涨",
            action="狂热期建议分批减仓，落袋为安",
            priority="A",
        ))
    
    elif phase in ("correction", ""):
        signal = "等待"
        
        conditions.append(ConditionRule(
            condition="实际利率确认回落 + ETF重新流入",
            action="调整可能结束，开始逐步建仓",
            priority="A",
        ))
        
        conditions.append(ConditionRule(
            condition="价格继续下跌 + ETF持续流出",
            action="调整加深，继续等待，不抄底",
            priority="B",
        ))
    
    elif phase == "bear":
        signal = "回避"
        
        conditions.append(ConditionRule(
            condition="美联储转向鸽派 + 实际利率明显下降",
            action="熊市可能见底，开始小仓位试探",
            priority="B",
        ))
        
        conditions.append(ConditionRule(
            condition="DXY>105 + 实际利率>2.5%",
            action="熊市确认，继续回避",
            priority="A",
        ))
    
    # Summary
    summary_parts = [
        f"黄金当前周期：{cycle.phase_name_cn}",
        f"建议操作：{cycle.suggested_action}",
        f"信号等级：{signal}",
        f"驱动评分：{composite:.0f}/100",
    ]
    
    # Position guidance based on cycle
    position_map = {
        "accumulation": "20-30%",
        "fermentation": "30-50%",
        "main_rise": "50-70%",
        "euphoria": "30-40%",
        "correction": "10-20%",
        "bear": "0-10%",
    }
    position = position_map.get(phase, "观察仓位")
    
    return TradingPlan(
        timestamp=ds.timestamp,
        signal_level=signal,
        summary="\n".join(summary_parts),
        conditions=conditions,
        position_guidance=f"建议仓位区间：{position}",
    )
