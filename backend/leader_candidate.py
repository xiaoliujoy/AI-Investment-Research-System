"""龙头候选数据层 — 龙头候选股票列表。"""

from __future__ import annotations

import time
import urllib.request
import json
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


def get_leader_candidates(limit: int = 30) -> list[dict]:
    """获取龙头候选股票列表。"""
    return _cached("leader_candidates", 
                   lambda: _build_candidates(limit), 
                   valid=bool)


def _build_candidates(limit: int) -> list[dict]:
    """构建候选列表。"""
    # 1. 获取成交额 TOP N
    turnover_data = _get_turnover_data(limit * 2)
    
    # 2. 获取连板数据
    lianban_map = _get_lianban_map()
    
    # 3. 获取个股行情（换手率、市值等）
    codes = [s["code"] for s in turnover_data]
    quotes = _get_quotes(codes)
    
    # 4. 获取历史新高信息
    new_high_map = _get_new_high(codes)
    
    # 5. 组装数据
    candidates = []
    for rank, stock in enumerate(turnover_data, 1):
        code = stock["code"]
        quote = quotes.get(code, {})
        
        candidates.append({
            "code": code,
            "name": stock.get("name", ""),
            "sector": stock.get("industry", ""),
            "amount": round(stock.get("amount", 0) / 1e8, 2),
            "turnover_rate": quote.get("turnover_pct"),
            "change_pct": stock.get("pct"),
            "board_height": lianban_map.get(code, 0),
            "mcap": quote.get("mcap_yi"),
            "float_cap": quote.get("float_mcap_yi"),
            "is_new_high": new_high_map.get(code, False),
            "amount_rank": rank,
        })
    
    return candidates[:limit]


def _get_turnover_data(limit: int) -> list[dict]:
    """获取成交额排名数据。"""
    try:
        return astock.market_turnover_rank(limit)
    except Exception:
        return []


def _get_lianban_map() -> dict[str, int]:
    """获取连板高度映射。"""
    try:
        from market import get_short_term_emotion
        emotion = get_short_term_emotion()
        lianban_stocks = emotion.get("lianban_stocks", [])
        return {s["code"]: s.get("boards", 0) for s in lianban_stocks}
    except Exception:
        return {}


def _get_quotes(codes: list[str]) -> dict[str, dict]:
    """获取个股行情。"""
    if not codes:
        return {}
    try:
        return astock.tencent_quote(codes[:50])
    except Exception:
        return {}


def _get_new_high(codes: list[str]) -> dict[str, bool]:
    """检测是否创新高（收盘价 >= 前20日最高价）。"""
    result = {}
    for code in codes:
        result[code] = _is_new_high_20d(code)
    return result


def _is_new_high_20d(code: str) -> bool:
    """检查个股是否创20日新高。"""
    try:
        prefix = astock.get_prefix(code)
        symbol = f"{prefix}{code}"
        
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,22,qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        stock_data = data.get("data", {}).get(symbol, {})
        klines = stock_data.get("qfqday", [])
        
        if len(klines) < 2:
            return False
        
        # 当前收盘价
        current_close = float(klines[-1][2])
        
        # 前20日最高价
        prev_klines = klines[:-1]
        max_high = max(float(d[3]) for d in prev_klines)
        
        return current_close >= max_high
    except Exception:
        return False
