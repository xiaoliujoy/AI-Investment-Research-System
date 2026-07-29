# -*- coding: utf-8 -*-
"""Commodity Engine — 商品研究中心（Commodity OS 数据层）。

Phase 0：商品期货日线数据链路（内盘为交易核心，外盘为宏观锚）。
- 内盘（新浪源，沙箱可达）：沪金 AU0 / 沪铜 CU0 / 原油 SC0 / 沪银 AG0 / 螺纹 RB0
- 外盘（akshare 源）：COMEX 黄金 GC / WTI 原油 CL / COMEX 铜 HG
落库：commodity_daily（交易层）+ commodity_symbol_map（元数据）
外盘额外回写 global_history 的 XAU/CL/HG（补全跨资产看板缺口）。
"""
