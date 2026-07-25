# -*- coding: utf-8 -*-
"""
brain / 总指挥包
===========================================================
把八层从「平行模块」重构成「串行推理流水线」：

    L0 Market Narrative（今天市场在交易什么）
      ↓
    L1 全球宏观 → L2 中国宏观 → L3 产业趋势 → L4 共识
      ↓
    L5 龙头 → L6 执行（可以买吗）→ L7 风险 → L8 学习

由 orchestrator 按序调度：上一层结论 → 下一层输入。
全程维护共享 ReasoningContext，最后做冲突检测 + 置信度聚合，
输出唯一决策结论（can_buy / reason / position_pct / confidence）。

设计原则（守用户边界）：
- 系统只负责「定方向 + 验证 + 决策建议」，价格行为/图形/个股硬过滤归用户。
- 置信度是启发式（基于数据覆盖与层间一致性），非黑箱模型。
"""
from .context import ReasoningContext
from .orchestrator import run, build_report

__all__ = ["ReasoningContext", "run", "build_report"]
