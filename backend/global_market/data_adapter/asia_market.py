"""亚洲市场数据采集器。

采集韩国、台湾、日本、香港市场数据。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from global_market.config import load_symbols


def get_asia_index_quotes() -> list[dict]:
    """获取亚洲市场指数行情。"""
    symbols = load_symbols()
    asia_indices = symbols.get("asia_indices", [])
    
    results = []
    for idx in asia_indices:
        symbol = idx["symbol"]
        name = idx["name"]
        secid = idx.get("secid")
        
        if secid:
            # 有 secid 的通过东财获取
            quote = _get_eastmoney_quote(secid)
            if quote:
                results.append({
                    "symbol": symbol,
                    "name": name,
                    "close": quote.get("price"),
                    "change_pct": quote.get("change_pct"),
                    "volume": quote.get("volume", 0),
                    "market_status": "closed",
                })
        else:
            # 无 secid 的通过 akshare 获取
            quote = _get_akshare_quote(symbol, name)
            if quote:
                results.append(quote)
    
    return results


def _get_eastmoney_quote(secid: str) -> dict | None:
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
        
        if not d or d.get("f43") is None:
            return None
        
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
        return None


def _get_akshare_quote(symbol: str, name: str) -> dict | None:
    """通过 akshare 获取行情。"""
    import akshare as ak
    
    try:
        # 全球指数实时行情
        df = ak.index_global_hist_em(symbol=symbol)
        
        if df is None or df.empty:
            return None
        
        latest = df.iloc[-1]
        
        return {
            "symbol": symbol,
            "name": name,
            "close": round(float(latest.get("最新价", 0)), 4),
            "change_pct": round(float(latest.get("涨跌幅", 0)), 4),
            "volume": float(latest.get("成交量", 0)),
            "market_status": "closed",
        }
        
    except Exception:
        return None


if __name__ == "__main__":
    print("Testing Asia market data...")
    quotes = get_asia_index_quotes()
    for q in quotes:
        print(f"  {q['symbol']}: {q['close']} ({q['change_pct']}%)")

