# -*- coding: utf-8 -*-
"""Commodity data adapter - 商品期货数据采集.

Covers 5 categories:
  1. Energy: WTI, NatGas (futures_foreign_hist)
  2. Precious Metals: Gold, Silver (futures_foreign_hist)
  3. Industrial Metals: Copper (futures_foreign_hist)
  4. China Commodities: Cu, Al, Ni, Sn, etc. (futures_zh_realtime)
  5. Agriculture: Corn, Soybean (futures_zh_realtime if available)

Data source: akshare futures_foreign_hist + futures_zh_realtime
Cache: 5-minute TTL (same as gold_engine)
"""
from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---- proxy cleanup (must run before akshare import) ----
for _k in list(os.environ.keys()):
    if "proxy" in _k.lower():
        del os.environ[_k]
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

_CACHE = {"data": None, "ts": 0}
_CACHE_TTL = 300  # 5 minutes

# Foreign futures symbols -> akshare symbols
FOREIGN_SYMBOLS = {
    "wti":       {"ak_sym": "CL",  "name_cn": "WTI原油",   "category": "energy"},
    "natgas":    {"ak_sym": "NG",  "name_cn": "天然气",     "category": "energy"},
    "gold":      {"ak_sym": "GC",  "name_cn": "COMEX黄金",  "category": "precious"},
    "silver":    {"ak_sym": "SI",  "name_cn": "COMEX白银",  "category": "precious"},
    "copper":    {"ak_sym": "HG",  "name_cn": "COMEX铜",    "category": "industrial"},
}

# China futures symbols for futures_zh_realtime
# These are the main continuous contracts
CHINA_SYMBOLS = {
    "cu":   {"name_cn": "沪铜",   "category": "industrial", "a_share": "有色"},
    "al":   {"name_cn": "沪铝",   "category": "industrial", "a_share": "有色"},
    "ni":   {"name_cn": "沪镍",   "category": "industrial", "a_share": "电池/新能源"},
    "sn":   {"name_cn": "沪锡",   "category": "industrial", "a_share": "半导体"},
    "rb":   {"name_cn": "螺纹钢", "category": "industrial", "a_share": "钢铁/基建"},
    "i":    {"name_cn": "铁矿石", "category": "industrial", "a_share": "钢铁"},
    "au":   {"name_cn": "沪金",   "category": "precious",   "a_share": "黄金"},
    "ag":   {"name_cn": "沪银",   "category": "precious",   "a_share": "白银"},
    "sc":   {"name_cn": "原油",   "category": "energy",     "a_share": "石化"},
    "fu":   {"name_cn": "燃油",   "category": "energy",     "a_share": "航运"},
    "m":    {"name_cn": "豆粕",   "category": "agriculture","a_share": "农业/养殖"},
    "y":    {"name_cn": "豆油",   "category": "agriculture","a_share": "农业"},
    "c":    {"name_cn": "玉米",   "category": "agriculture","a_share": "农业"},
    "sr":   {"name_cn": "白糖",   "category": "agriculture","a_share": "食品"},
}


@dataclass
class CommodityItem:
    """Single commodity data point."""
    name: str = ""
    name_cn: str = ""
    category: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    a_share_link: str = ""  # corresponding A-share sector
    source: str = ""  # akshare_foreign / akshare_china


@dataclass
class CommoditySnapshot:
    """Complete commodity market snapshot."""
    timestamp: str = ""
    # By category
    energy: List[CommodityItem] = field(default_factory=list)
    precious: List[CommodityItem] = field(default_factory=list)
    industrial: List[CommodityItem] = field(default_factory=list)
    agriculture: List[CommodityItem] = field(default_factory=list)
    # Summary
    all_items: List[CommodityItem] = field(default_factory=list)
    risk_appetite: str = ""  # risk_on / risk_off / neutral
    gaps: list = field(default_factory=list)


def _fetch_foreign(sym: str, name_cn: str, category: str, a_share: str = "") -> Optional[CommodityItem]:
    """Fetch foreign commodity futures from akshare."""
    try:
        import akshare as ak
        df = ak.futures_foreign_hist(symbol=sym)
        if df is None or len(df) < 2:
            return None
        latest = df.tail(1).iloc[0]
        prev = df.tail(2).iloc[0]
        price = float(latest["close"])
        prev_close = float(prev["close"])
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
        return CommodityItem(
            name=sym,
            name_cn=name_cn,
            category=category,
            price=price,
            change_pct=round(change_pct, 2),
            a_share_link=a_share,
            source="akshare_foreign",
        )
    except Exception as e:
        logger.warning("futures_foreign_hist(%s) failed: %s", sym, e)
        return None


def _fetch_china_realtime() -> List[CommodityItem]:
    """Fetch China commodity futures real-time data."""
    items = []
    try:
        import akshare as ak
        df = ak.futures_zh_realtime()
        if df is None or len(df) == 0:
            return items
        # Build symbol lookup (uppercase continuous contract codes)
        # futures_zh_realtime returns symbol like 'CU0', 'AL0', etc.
        sym_map = {k.upper() + "0": v for k, v in CHINA_SYMBOLS.items()}
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).upper()
            if sym in sym_map:
                info = sym_map[sym]
                price = float(row.get("close", 0) or row.get("trade", 0) or 0)
                pre_close = float(row.get("preclose", 0) or 0)
                change_pct = float(row.get("changepercent", 0) or 0)
                if not change_pct and pre_close:
                    change_pct = ((price - pre_close) / pre_close * 100)
                items.append(CommodityItem(
                    name=sym,
                    name_cn=info["name_cn"],
                    category=info["category"],
                    price=price,
                    change_pct=round(change_pct, 2),
                    a_share_link=info.get("a_share", ""),
                    source="akshare_china",
                ))
    except Exception as e:
        logger.warning("futures_zh_realtime failed: %s", e)
    return items


def _calc_risk_appetite(items: List[CommodityItem]) -> str:
    """Determine risk appetite from commodity movements."""
    if not items:
        return "unknown"
    # Energy up + industrial metals up = risk_on
    # Energy down + gold up = risk_off
    energy_up = sum(1 for i in items if i.category == "energy" and i.change_pct > 0.5)
    energy_down = sum(1 for i in items if i.category == "energy" and i.change_pct < -0.5)
    industrial_up = sum(1 for i in items if i.category == "industrial" and i.change_pct > 0.5)
    gold_up = sum(1 for i in items if "金" in i.name_cn and i.change_pct > 0.5)

    if energy_up >= 1 and industrial_up >= 1:
        return "risk_on"
    if energy_down >= 1 and gold_up >= 1:
        return "risk_off"
    return "neutral"


def get_commodity_snapshot() -> CommoditySnapshot:
    """Collect all commodity data with caching."""
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["data"]

    snap = CommoditySnapshot(timestamp=datetime.now().isoformat())
    gaps = []
    all_items = []

    # 1. Foreign commodity futures
    foreign_a_share = {
        "wti": "石化/航空",
        "natgas": "天然气",
        "gold": "黄金",
        "silver": "白银/光伏",
        "copper": "有色/电网/工程机械",
    }
    for key, info in FOREIGN_SYMBOLS.items():
        item = _fetch_foreign(info["ak_sym"], info["name_cn"], info["category"],
                              foreign_a_share.get(key, ""))
        if item:
            all_items.append(item)
            if item.category == "energy":
                snap.energy.append(item)
            elif item.category == "precious":
                snap.precious.append(item)
            elif item.category == "industrial":
                snap.industrial.append(item)
        else:
            gaps.append(f"foreign_{key}")

    # 2. China commodity futures (real-time, may be empty outside market hours)
    china_items = _fetch_china_realtime()
    for item in china_items:
        all_items.append(item)
        if item.category == "energy" and not any(i.name == item.name for i in snap.energy):
            snap.energy.append(item)
        elif item.category == "precious" and not any(i.name == item.name for i in snap.precious):
            snap.precious.append(item)
        elif item.category == "industrial" and not any(i.name == item.name for i in snap.industrial):
            snap.industrial.append(item)
        elif item.category == "agriculture":
            snap.agriculture.append(item)

    if not china_items:
        gaps.append("china_futures_closed")

    # 3. Risk appetite
    snap.risk_appetite = _calc_risk_appetite(all_items)
    snap.all_items = all_items
    snap.gaps = gaps

    _CACHE["data"] = snap
    _CACHE["ts"] = now
    return snap


# Convenience function with cache
def get_commodity_cached() -> CommoditySnapshot:
    return get_commodity_snapshot()
