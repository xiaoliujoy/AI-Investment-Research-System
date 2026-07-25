# -*- coding: utf-8 -*-
"""
Decision OS —— 决策操作系统（编排 / 决策 / 报告）。

职责：调度 Research OS 的 Agent，形成"一条推理链 + 唯一决策结论"，
      并渲染成人可一分钟读完的决策简报。这是"总指挥"所在层。

统辖的物理模块：
    brain.orchestrator  总指挥：按序调度 L0→L8、冲突检测、置信度、唯一决策
    brain.render        决策简报 HTML
    decision_tree       八层完整分析报告（下游细节）
    main_line_report    主线报告
    report_generator    报告生成
    daily_dashboard     每日看板
    run_daily           每日流水线串接
    run_brain_report    brain 决策简报薄包装（供 run_daily step2b）

守边界：只"定方向 + 验证 + 给决策建议"，买卖点/图形/个股硬过滤归用户人工。
"""
from __future__ import annotations
import os as _os
import sys as _sys

_BACK = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _BACK not in _sys.path:
    _sys.path.insert(0, _BACK)

_UNAVAILABLE = {}


def _load():
    import importlib
    for name in ("decision_tree", "main_line_report", "report_generator",
                 "daily_dashboard"):
        try:
            globals()[name] = importlib.import_module(name)
        except Exception as e:
            _UNAVAILABLE[name] = repr(e)[:120]
    try:
        globals()["brain"] = importlib.import_module("brain")
    except Exception as e:
        _UNAVAILABLE["brain"] = repr(e)[:120]


_load()


def run_brain(date=None, build_html=True):
    """入口：跑总指挥推理链，产出唯一决策结论（+ 可选 HTML 简报）。"""
    brain = globals().get("brain")
    if brain is None:
        raise RuntimeError("brain 不可用：" + _UNAVAILABLE.get("brain", "?"))
    report = brain.run(date)
    if build_html:
        brain.build_report(report)
    return report


def run_analysis(date=None):
    """入口：跑八层完整分析报告（decision_tree，下游细节）。"""
    dt = globals().get("decision_tree")
    if dt is None:
        raise RuntimeError("decision_tree 不可用")
    return dt.main() if hasattr(dt, "main") else None
