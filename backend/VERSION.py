# -*- coding: utf-8 -*-
"""
VERSION.py —— v0.2 六维版本常量（PRD §5）。

每次 run_daily.py 把当前常量 + 生成的 snapshot_id 写入 decision_version 与
decision_run（见 write_decision_ledger.py）。未来任一规则修改 → 升对应版本号 →
回放按版本分组。

注意：本文件是「版本号」的单一事实来源，不承载任何决策逻辑。
冻结期内（90 天）这些常量应保持不变；若确须修改某维度，仅升该维度版本号，
绝不允许为「顺手优化」改动后保持版本号不变（那会破坏回放的可溯源语义）。
"""

# 数据快照版本（data_snapshot.manifest 所引用的源 schema 版本）
DATA_SNAPSHOT_VERSION = "1.4"

# 指标定义版本（L1~L8 各指标口径；冻结项：指标定义不可改，故版本固定）
INDICATOR_VERSION = "1.2"

# 策略版本（decision_tree / 板块>龙头>资金>图形 排序逻辑）
STRATEGY_VERSION = "0.8"

# 风险约束版本（单独版本：风险约束是硬规则，必须可溯源）
# 任何 risk_guard / Risk Budget 参数变化必须升此版本。
RISK_VERSION = "0.3"

# 决策引擎版本（investment_committee 裁决逻辑）
DECISION_ENGINE_VERSION = "0.3"

# 提示词版本（CIO memo 模板 / prompt）
PROMPT_VERSION = "0.5"


def as_dict() -> dict:
    """返回六维版本字典，便于直接写入 decision_version。"""
    return {
        "data_snapshot_version": DATA_SNAPSHOT_VERSION,
        "indicator_version": INDICATOR_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "risk_version": RISK_VERSION,
        "decision_engine_version": DECISION_ENGINE_VERSION,
        "prompt_version": PROMPT_VERSION,
    }


def version_line() -> str:
    """单行版本串，用于日志与快照 manifest 快速比对。"""
    d = as_dict()
    return ".".join(f"{k[:3]}={v}" for k, v in d.items())
