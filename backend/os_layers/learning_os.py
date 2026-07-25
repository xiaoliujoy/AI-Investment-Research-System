# -*- coding: utf-8 -*-
"""
Learning OS —— 学习操作系统（进化 / 反哺）。

职责：记录每一笔交易结果，按月统计胜率与可复用模式，并【反向回写】Decision OS——
      让历史胜率影响未来的置信度与仓位护栏。这是"系统自己修改自己"的闭环。

数据流方向（唯一一条反向箭头）：
    Learning OS ──(learning_feedback 板块胜率/模式信号)──▶ Decision OS(orchestrator)

统辖的物理模块：
    trade_log_cli       交易日志录入 CLI（add / stats / list）
    narrative_layers    L8 统计本体：add_journal / monthly_pattern / interactive_add
                        （原在 narrative_engine，2026-07-16 被「为什么引擎」覆盖后迁出重建）
    learning_feedback   ★反哺引擎：把月度胜率转成对 orchestrator 的调整信号

用法：
    from os_layers import learning_os
    learning_os.add(date, code, action, sector=..., result="胜", pnl=5.2)
    fb = learning_os.feedback()   # {sector_bias:{...}, notes:[...], applied:bool}
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
    for name in ("narrative_layers", "trade_log_cli", "learning_feedback"):
        try:
            globals()[name] = importlib.import_module(name)
        except Exception as e:
            _UNAVAILABLE[name] = repr(e)[:120]


_load()


def add(trade_date, code, action, **kw):
    """录入一笔交易日志。"""
    ne = globals().get("narrative_layers")
    return ne.add_journal(trade_date, code, action, **kw)


def stats():
    """月度模式统计。"""
    ne = globals().get("narrative_layers")
    return ne.monthly_pattern()


def feedback():
    """取学习反哺信号（供 orchestrator 调整置信度/仓位）。"""
    lf = globals().get("learning_feedback")
    if lf is None:
        raise RuntimeError("learning_feedback 不可用：" + _UNAVAILABLE.get("learning_feedback", "?"))
    return lf.learning_feedback()
