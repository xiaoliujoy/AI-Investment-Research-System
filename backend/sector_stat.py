"""板块统计数据层 — 板块成交额、涨停数、涨跌数等。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import astock

BEIJING = timezone(timedelta(hours=8))
_CACHE: dict = {}
_CACHE_TTL = 300  # 5分钟


def _cached(key: str, fn, valid=None):
    """TTL 缓存。"""
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    val = fn()
    if valid is None or valid(val):
        _CACHE[key] = (now, val)
    return val


def get_sector_stats() -> list[dict]:
    """获取板块统计数据。"""
    return _cached("sector_stats", _build_sector_stats, valid=bool)


def _build_sector_stats() -> list[dict]:
    """构建板块统计数据。"""
    sectors = _get_sectors_from_overview()
    
    if not sectors:
        return []
    
    # 计算全市场成交额（用于占比）
    total_amount = _get_total_amount(sectors)
    
    # 获取全市场涨跌数据（用于估算板块数据）
    market_activity = _get_market_activity()
    
    result = []
    for sector in sectors:
        name = sector.get("name", "")
        amount = sector.get("net", 0)
        amount_ratio = round(amount / max(total_amount, 1), 4) if total_amount > 0 else None
        
        # 估算板块涨跌数量（基于板块内公司数占全市场比例）
        firms = sector.get("firms", 0)
        total_firms = market_activity.get("total_firms", 1)
        ratio = firms / max(total_firms, 1)
        
        up_count = round(market_activity.get("up", 0) * ratio) if market_activity else None
        down_count = round(market_activity.get("down", 0) * ratio) if market_activity else None
        zt_count = round(market_activity.get("zt_real", 0) * ratio) if market_activity else None
        
        result.append({
            "name": name,
            "amount": round(amount, 2),
            "amount_ratio": amount_ratio,
            "amount_change_rate": None,
            "change_pct": sector.get("pct"),
            "up_count": up_count,
            "down_count": down_count,
            "zt_count": zt_count,
            "total_firms": firms,
        })
    
    return result


def _get_sectors_from_overview() -> list[dict]:
    """从已有接口获取板块数据。"""
    try:
        from market import get_overview
        overview = get_overview()
        return overview.get("sectors", [])
    except Exception:
        return []


def _get_total_amount(sectors: list[dict]) -> float:
    """计算全市场成交额（亿元）。"""
    total_net = sum(abs(s.get("net", 0)) for s in sectors)
    estimated_total = total_net / 0.18
    return round(estimated_total, 2)


def _get_market_activity() -> dict:
    """获取全市场涨跌数据。"""
    try:
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
        
        def num(v):
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return 0
        
        up = num(d.get("上涨", 0))
        down = num(d.get("下跌", 0))
        zt_real = num(d.get("真实涨停", 0))
        
        return {
            "up": up,
            "down": down,
            "zt_real": zt_real,
            "total_firms": up + down + num(d.get("平盘", 0)),
        }
    except Exception:
        return {}
