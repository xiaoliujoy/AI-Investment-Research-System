# -*- coding: utf-8 -*-
"""Commodity Engine — 品种元数据与 symbol 映射。

设计（v2 用户确认版 2026-07-29）：
- 内盘为交易核心：AU0 沪金 / CU0 沪铜 / SC0 原油 / AG0 沪银 / RB0 螺纹钢
- 外盘为宏观锚：GC COMEX黄金 / CL WTI原油 / HG COMEX铜
- 外盘 akshare 代码 → global_history 代码映射（GC→XAU, CL→CL, HG→HG）

em_link = 对应 A股板块关键词（供 Phase 3 Cross Asset Engine 使用）。
"""
from __future__ import annotations

# 内盘品种（新浪主力连续，含 OI/结算）
INNER = {
    "AU0": {"name": "沪金", "category": "贵金属", "em_link": "黄金"},
    "CU0": {"name": "沪铜", "category": "有色", "em_link": "铜"},
    "SC0": {"name": "原油", "category": "能源", "em_link": "原油"},
    "AG0": {"name": "沪银", "category": "贵金属", "em_link": "白银"},
    "RB0": {"name": "螺纹钢", "category": "黑色", "em_link": "螺纹钢"},
}

# 外盘品种（akshare futures_foreign_hist）
# global_symbol = 写入 global_history 时使用的代码（与 cio_agent 看板一致）
FOREIGN = {
    "GC": {"name": "COMEX黄金", "category": "贵金属", "global_symbol": "XAU", "em_link": "黄金"},
    "CL": {"name": "WTI原油", "category": "能源", "global_symbol": "CL", "em_link": "原油"},
    "HG": {"name": "COMEX铜", "category": "有色", "global_symbol": "HG", "em_link": "铜"},
}

# 外盘 akshare 代码 → global_history 代码（用于回写 global_history）
FOREIGN_TO_GLOBAL = {
    "GC": "XAU",
    "CL": "CL",
    "HG": "HG",
}

# global_history 友好名（与 global_history_backfill.YF_SYMBOLS 对齐）
GLOBAL_NAME = {
    "XAU": "黄金",
    "CL": "WTI原油",
    "HG": "COMEX铜",
}


def all_symbols() -> list[dict]:
    """返回所有品种的统一描述列表，每项含 symbol/market/category/name/em_link。"""
    out = []
    for sym, m in INNER.items():
        out.append({
            "symbol": sym, "market": "内盘", "category": m["category"],
            "name": m["name"], "em_link": m["em_link"],
            "inner_symbol": sym, "foreign_symbol": None,
            "global_symbol": None,
        })
    for sym, m in FOREIGN.items():
        out.append({
            "symbol": sym, "market": "外盘", "category": m["category"],
            "name": m["name"], "em_link": m["em_link"],
            "inner_symbol": None, "foreign_symbol": sym,
            "global_symbol": m["global_symbol"],
        })
    return out
