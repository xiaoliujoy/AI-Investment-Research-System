# -*- coding: utf-8 -*-
"""
os_layers —— 四操作系统门面层（Four-OS Facade）。

用户架构评审的终极形态：系统不是"八个平行模块"，而是四个操作系统：

    Data OS  →  Research OS  →  Decision OS  →  Learning OS
    (采集)       (分析/推理)      (决策/编排)       (进化/反哺)
                                                      │
                                                      └── 反向回写 Decision OS

为什么是"门面层"而非物理搬移目录？
  backend 内 40+ 模块全部使用扁平 import（import astock / import narrative_engine …），
  依赖 backend 根目录在 sys.path 上。物理搬移会导致所有 import 断裂、run_daily 流水线全崩。
  因此这里用【逻辑归类 + 统一入口】的门面模式：物理文件不动，通过四个子包 re-export
  各模块，既确立四 OS 的清晰边界与命名空间，又零破坏风险。

用法：
    from os_layers import data_os, research_os, decision_os, learning_os
    report = decision_os.run_brain()          # 跑总指挥决策链
    fb     = learning_os.learning_feedback()  # 取学习反哺信号

每个子包的 __init__ 顶部列出它统辖的物理模块清单（single source of truth）。
"""
from __future__ import annotations

import os
import sys

# 确保 backend 根在 sys.path（门面子包 re-export 扁平模块的前提）
# 本文件位于 backend/os_layers/__init__.py，backend 根 = 上一级目录
_BACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACK not in sys.path:
    sys.path.insert(0, _BACK)

from . import data_os      # noqa: E402,F401
from . import research_os  # noqa: E402,F401
from . import decision_os  # noqa: E402,F401
from . import learning_os  # noqa: E402,F401

__all__ = ["data_os", "research_os", "decision_os", "learning_os"]
