# -*- coding: utf-8 -*-
"""conftest：把 trading_os 包目录加入 sys.path，统一测试 import 根。"""
import os
import sys

_TRADING_OS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TRADING_OS not in sys.path:
    sys.path.insert(0, _TRADING_OS)
