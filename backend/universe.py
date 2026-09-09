# -*- coding: utf-8 -*-
"""
universe.py —— Canonical Universe（A 股成员资格 / 交易所分类单一事实源）

P1-C · C10 引入。此前 `_is_stock` 在 data_health / capital_score / fill_market_cap
各有一份等价副本，另有 astock / fundamental_engine / tushare_provider 各有一套
交易所前缀分类（且语义偏宽：整段 `8` 当北交所，含新三板）。本模块把它们收敛为单点。

设计约束（用户授权范围）：
  - 仅定义规则，零 DB 依赖、零网络依赖。
  - 业务语义与历史 `_is_stock` 完全一致（行为等价，见 test_universe_contract.py）：
      沪(6) / 深(0) / 创业(3) / 北交(83/87/920) = 真个股；
      先排除 转债(11/12/13) / ETF·基金(15/16/18) / 板块指数伪代码(88/5) / 新三板(4)。
  - 北交所 327→0 是「采集层缺口」（fill_stock_flow.py 故意不覆盖），**不是**成员资格排除；
    本模块保证 920 经 is_stock()=True 进入 Canonical Universe，与采集覆盖率治理解耦。
  - 不引入 stock_info.board/exchange 物化（用户明确剥离出本轮）。
"""

from __future__ import annotations

# 北交所 proper 前缀
BJ_PREFIXES = ("83", "87", "920")

# 主板 / 创业板 / 深市
MAIN_PREFIXES = ("6", "0", "3")

# 明确非个股的前缀（顺序无关，startswith 任一即排除）
NON_STOCK_PREFIXES = (
    "11", "12", "13",   # 可转债
    "15", "16", "18",   # ETF / 基金 / 其他场内基金
    "88",               # 通达信板块指数伪代码（88x）
    "5",                # ETF / 基金（5x）
    "4",                # 新三板（43/44/45/48/83/87 中 83/87 已归北交所，其余归新三板）
)

# 意图显式化：Universe 是否包含北交所。历史 `_is_stock` 实际包含，仅文档写反。
# 设为 True 即把「含北交所」从隐含行为变成单一可审计常量，消除 doc/intent 漂移。
UNIVERSE_INCLUDES_BJ = True


def is_stock(code: str) -> bool:
    """真个股判定（与全系统历史 `_is_stock` 行为等价，单一事实源）。

    沪(6)/深(0)/创业(3)/北交(83/87/920) = True；
    转债/ETF/基金/板块指数伪代码/新三板 = False。
    """
    if not code:
        return False
    if code.startswith(NON_STOCK_PREFIXES):
        return False
    return code[0] in MAIN_PREFIXES or code.startswith(BJ_PREFIXES)


def market_of(code: str) -> str:
    """交易所归属（人类可读，Canonical Universe 语义）。

    返回：沪市 / 深市 / 北交所 / 其他。
    北交所 = 83/87/920（proper）；新三板(4x) 与板块指数伪代码(88x) 归「其他」，
    不被误纳入北交所，也不被误判为个股。

    沪市含 6(主板) 与 9(900xxx 沪市B股)：920xxx 已在 BJ_PREFIXES 先行判定为北交所，
    因此不会与本条冲突——这正是历史「整段 9 当沪市」误伤 920 的修正点。
    """
    if not code:
        return "其他"
    if code.startswith(BJ_PREFIXES):
        return "北交所"
    if code[0] == "6":
        return "沪市"
    if code[0] == "9":
        return "沪市"   # 900xxx 沪市B股（920xxx 已由 BJ_PREFIXES 判定为北交所）
    if code[0] in ("0", "3"):
        return "深市"
    return "其他"
