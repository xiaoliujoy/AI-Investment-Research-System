# -*- coding: utf-8 -*-
"""
Research OS —— 研究操作系统（分析 / 推理）。

职责：把 Data OS 的结构化数据加工成"结论"。这里是八层决策树的算法本体，
      以及把它们串成推理链的 brain Agent 层。

统辖的物理模块：
    narrative_layers    L1/L2/L3 叙事宏观 + L8 学习进化统计（2026-07-16 从 narrative_engine 迁出重建）
    narrative_engine    「为什么」板块因果链引擎（run() + INDUSTRY_CHAIN）
    consensus_engine    L4 资金共识（生命周期）
    leader_engine       L5 四龙头体系
    leader_candidate    龙头候选
    sentiment           情绪验证（宽度/涨跌家数/连板高度）
    fundamental_engine  基本面验证（板块级业绩 vs 估值）
    risk_stock          L7 个股风险三维
    scoring_engine      打分引擎
    sector_pipeline     板块流水线
    sector_stat         板块统计
    tech_fill           技术字段回填
    playbook_engine     候选圈选（只圈不筛，守边界）
    market              市场层
    brain.*             推理链 Agent 层（context/agents/confidence/
                        conflict/narrative_l0）—— 归 Research，但产出的
                        orchestrator/render 归 Decision OS

本文件仅做 re-export。
"""
from __future__ import annotations
import os as _os
import sys as _sys

_BACK = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _BACK not in _sys.path:
    _sys.path.insert(0, _BACK)

MODULES = [
    "narrative_layers", "narrative_engine",
    "consensus_engine", "leader_engine", "leader_candidate",
    "sentiment", "fundamental_engine", "risk_stock", "scoring_engine",
    "sector_pipeline", "sector_stat", "tech_fill", "playbook_engine", "market",
]

_UNAVAILABLE = {}


def _load():
    import importlib
    for name in MODULES:
        try:
            globals()[name] = importlib.import_module(name)
        except Exception as e:
            _UNAVAILABLE[name] = repr(e)[:120]
    # brain Agent 层（属 Research）
    for sub in ("context", "agents", "confidence", "conflict", "narrative_l0"):
        try:
            globals()["brain_" + sub] = importlib.import_module("brain." + sub)
        except Exception as e:
            _UNAVAILABLE["brain." + sub] = repr(e)[:120]


_load()
