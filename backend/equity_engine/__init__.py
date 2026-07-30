# -*- coding: utf-8 -*-
"""equity_engine —— A股 Adapter（Phase 1.8-B，AIP 统一投资语言）。

职责拆分：
  - analysis.py : 纯判断逻辑（无 I/O）
  - adapter.py  : 数据读取 + 协议封装（I/O 边界）
"""
from equity_engine.adapter import build_equity_signal

__all__ = ["build_equity_signal"]
