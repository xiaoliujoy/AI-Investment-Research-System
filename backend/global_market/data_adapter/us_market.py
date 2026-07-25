"""美股数据采集器。

采集美国市场指数和个股数据。
复用 gstock.py 的东财 push2 接口。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from global_market.config import load_symbols


def get_us_index_quotes() -> list[dict]:
    """获取美股指数行情。
    
    Returns:
        [
            {
                "symbol": "NDX",
                "name": "纳斯达克",
                "close": 18500.0,
                "change_pct": 1.2,
                "volume": 0,
                "market_status": "closed"
            },
            ...
        ]
    """
    symbols = load_symbols()
    us_indices = symbols.get("us_indices", [])
    
    results = []
    for idx in us_indices:
        symbol = idx["symbol"]
        name = idx["name"]
        secid = idx.get("secid")
        
        if not secid:
            continue
        
        try:
            quote = _get_eastmoney_quote(secid)
            if quote:
                results.append({
                    "symbol": symbol,
                    "name": name,
                    "close": quote.get("price"),
                    "change_pct": quote.get("change_pct"),
                    "volume": quote.get("volume", 0),
                    "market_status": "closed",  # 东财实时接口
                })
        except Exception as e:
            print(f"  Failed to get {symbol}: {e}")
    
    return results


def get_us_stock_quotes() -> list[dict]:
    """获取美股个股行情。
    
    Returns:
        [
            {
                "symbol": "NVDA",
                "name": "NVIDIA",
                "close": 125.0,
                "change_pct": 2.5,
                "volume": 200000000,
                "market_status": "closed"
            },
            ...
        ]
    """
    symbols = load_symbols()
    us_stocks = symbols.get("us_tech", [])
    
    results = []
    for stock in us_stocks:
        symbol = stock["symbol"]
        name = stock["name"]
        
        try:
            # 美股代码格式: 105.NVDA (NASDAQ)
            quote = _get_us_stock_quote(symbol)
            if quote:
                results.append({
                    "symbol": symbol,
                    "name": name,
                    "close": quote.get("price"),
                    "change_pct": quote.get("change_pct"),
                    "volume": quote.get("volume", 0),
                    "market_status": "closed",
                })
        except Exception as e:
            print(f"  Failed to get {symbol}: {e}")
    
    return results


def _get_eastmoney_quote(secid: str) -> Optional[dict]:
    """通过东财 push2 获取行情。"""
    import astock
    
    try:
        r = astock.em_get(
            f"https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": secid, "fields": "f43,f44,f45,f46,f48,f170"},
            headers={"User-Agent": astock.UA},
            timeout=10
        )
        d = r.json().get("data")
        
        if not d:
            return None
        
        # 价格需要还原小数位
        price_raw = d.get("f43")
        dec = d.get("f59", 2)
        
        if price_raw is None:
            return None
        
        price = price_raw / (10 ** dec)
        change_pct = d.get("f170")
        
        if change_pct is not None:
            change_pct = change_pct / 100
        
        return {
            "price": round(price, 4),
            "change_pct": round(change_pct, 4) if change_pct else None,
            "volume": d.get("f48", 0),
        }
        
    except Exception:
        return None


def _get_us_stock_quote(symbol: str) -> Optional[dict]:
    """获取美股个股行情。
    
    美股代码格式:
    - NASDAQ: 105.{symbol}
    - NYSE: 106.{symbol}
    """
    import astock
    
    # 尝试 NASDAQ
    for prefix in ["105", "106"]:
        try:
            secid = f"{prefix}.{symbol}"
            r = astock.em_get(
                f"https://push2.eastmoney.com/api/qt/stock/get",
                params={"secid": secid, "fields": "f43,f44,f45,f46,f48,f170"},
                headers={"User-Agent": astock.UA},
                timeout=10
            )
            d = r.json().get("data")
            
            if d and d.get("f43") is not None:
                price_raw = d.get("f43")
                dec = d.get("f59", 2)
                price = price_raw / (10 ** dec)
                change_pct = d.get("f170")
                
                if change_pct is not None:
                    change_pct = change_pct / 100
                
                return {
                    "price": round(price, 4),
                    "change_pct": round(change_pct, 4) if change_pct else None,
                    "volume": d.get("f48", 0),
                }
        except Exception:
            continue
    
    return None


if __name__ == "__main__":
    print("Testing US market data...")
    quotes = get_us_index_quotes()
    for q in quotes:
        print(f"  {q['symbol']}: {q['close']} ({q['change_pct']}%)")

