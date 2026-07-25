# -*- coding: utf-8 -*-
"""
Data OS —— 数据操作系统（采集 / 清洗 / 入库）。

职责：把外部世界（TDX 本地行情、东财/新浪/同花顺/腾讯接口、宏观数据）
      转成本系统可用的结构化数据，落 SQLite。是整条链的地基。

统辖的物理模块（single source of truth）：
    import_tdx            通达信本地 vipdoc → stock_daily 导入
    tdx_refresh           TDX 增量刷新
    build_sector_daily    板块日线聚合回填（sector_daily）
    build_sector_mainline step1：板块资金流+成交额 → sector_mainline.json
    build_industry_mapping 东财板块成分 → industry_map
    build_crosswalk       同花顺行业 ↔ 东财板块 crosswalk
    fetch_industry_map    行业成分抓取
    market_amount         两市成交额
    fill_market_cap       gtimg 总市值/流通市值回填（市值数据源）
    fill_stock_flow       东财 push2 个股资金流（主力/超大单/大单/中单/小单）→ 独立表 stock_flow_daily
    tushare_provider      第三数据源（待激活）
    astock / gstock       行情底层工具
    macro                 全球宏观原始数据（DXY/商品/美股）
    newsradar             新闻雷达

本文件仅做 re-export；缺依赖的模块静默跳过（记入 _UNAVAILABLE）。
"""
from __future__ import annotations
import os as _os
import sys as _sys

_BACK = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _BACK not in _sys.path:
    _sys.path.insert(0, _BACK)

MODULES = [
    "import_tdx", "tdx_refresh", "build_sector_daily", "build_sector_mainline",
    "build_industry_mapping", "build_crosswalk", "fetch_industry_map",
    "market_amount", "fill_market_cap", "fill_stock_flow", "tushare_provider",
    "astock", "gstock", "macro", "newsradar",
    "daily_collect",
]

_UNAVAILABLE = {}


def _load():
    import importlib
    for name in MODULES:
        try:
            mod = importlib.import_module(name)
            globals()[name] = mod
        except Exception as e:  # 缺依赖/沙箱不可达不阻断门面
            _UNAVAILABLE[name] = repr(e)[:120]


_load()


def refresh_market_cap(date=None):
    """入口：回填最新交易日总市值/流通市值（gtimg）。"""
    m = globals().get("fill_market_cap")
    if m is None:
        raise RuntimeError("fill_market_cap 不可用：" + _UNAVAILABLE.get("fill_market_cap", "?"))
    return m.fill(date)


def refresh_stock_flow(date=None):
    """入口：回填最新交易日个股资金流（独立表 stock_flow_daily，东财 push2，urllib 绕过死代理）。"""
    m = globals().get("fill_stock_flow")
    if m is None:
        raise RuntimeError("fill_stock_flow 不可用：" + _UNAVAILABLE.get("fill_stock_flow", "?"))
    return m.fill(date)


def build_mainline():
    """入口：跑 step1 板块主线数据底座。"""
    m = globals().get("build_sector_mainline")
    if m is None:
        raise RuntimeError("build_sector_mainline 不可用")
    return m.main() if hasattr(m, "main") else None
