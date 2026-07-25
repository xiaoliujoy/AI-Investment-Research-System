# -*- coding: utf-8 -*-
"""
brain.agents — 八层决策 Agent 子包。

每个 Agent 对应你架构蓝图里的一层，返回统一的 AgentResult（score/stage/narrative）。
Agent 之间通过 ReasoningContext 串行传递结论 —— 上一层输出是下一层输入。
"""
from .base_agent import AgentResult, make_result

from .global_agent import run as run_L1
from .gold_agent import run as run_gold
from .china_agent import run as run_L2
from .consensus_agent import run as run_L4
from .industry_agent import run as run_L3
from .industry_chain_agent import run as run_L3_5
from .leader_agent import run as run_L5
from .sentiment_agent import run as run_sentiment
from .fundamental_agent import run as run_fundamental
from .execution_agent import run as run_L6
from .risk_agent import run as run_L7
from .learning_agent import run as run_L8

# Capital Flow Engine — L0 Global Flow（消费 GOLD → 反哺 L1 全球宏观）
try:
    from capital_flow.agents.flow_agent import run as run_flow
except ImportError:
    run_flow = None

__all__ = [
    "AgentResult", "make_result",
    "run_L1", "run_L2", "run_L3", "run_L3_5", "run_L4", "run_L5",
    "run_L6", "run_L7", "run_L8",
    "run_sentiment", "run_fundamental",
    "run_gold", "run_flow",
]
