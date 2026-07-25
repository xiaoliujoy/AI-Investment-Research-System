"""全球宏观数据采集器。

采集商品、外汇、利率数据。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from global_market.config import load_symbols


def get_commodity_quotes() -> list[dict]:
    """获取商品期货行情。"""
    import akshare as ak
    
    symbols = load_symbols()
    commodities = symbols.get("commodities", [])
    
    results = []
    for comm in commodities:
        symbol = comm["symbol"]
        name = comm["name"]
        futures_code = comm.get("futures_code")
        
        if not futures_code:
            continue
        
        try:
            df = ak.futures_foreign_commodity_realtime(futures_code)
            
            if df is None or df.empty:
                continue
            
            row = df.iloc[0]
            price = row.get("最新价")
            chg = row.get("涨跌幅")
            
            results.append({
                "symbol": symbol,
                "name": name,
                "close": round(float(price), 4) if price is not None else None,
                "change_pct": round(float(chg), 4) if chg is not None else None,
                "volume": 0,
                "market_status": "closed",
            })
            
        except Exception as e:
            print(f"  Failed to get {symbol}: {e}")
    
    return results


def get_forex_quotes() -> list[dict]:
    """获取外汇行情。"""
    import akshare as ak
    
    symbols = load_symbols()
    forex_list = symbols.get("forex", [])
    
    results = []
    
    try:
        df = ak.currency_boc_safe()
        
        if df is not None and not df.empty:
            for fx in forex_list:
                symbol = fx["symbol"]
                name = fx["name"]
                
                rate = None
                for _, row in df.iterrows():
                    if symbol in str(row.get("币种", "")):
                        rate = row.get("中行汇买价")
                        break
                
                if rate:
                    results.append({
                        "symbol": symbol,
                        "name": name,
                        "close": round(float(rate) / 100, 4),
                        "change_pct": None,
                        "volume": 0,
                        "market_status": "closed",
                    })
                    
    except Exception as e:
        print(f"  Failed to get forex: {e}")
    
    # DXY - 通过 BOC 汇率计算
    try:
        dxy = _calc_dxy()
        if dxy and dxy.get("price"):
            results.append({
                "symbol": "DXY",
                "name": "美元指数",
                "close": dxy["price"],
                "change_pct": dxy.get("change_pct"),
                "volume": 0,
                "market_status": "closed",
            })
    except Exception as e:
        print(f"  Failed to get DXY: {e}")
    
    return results


def _calc_dxy() -> dict | None:
    """计算美元指数（基于 BOC 汇率）。"""
    import akshare as ak
    
    try:
        df = ak.currency_boc_safe()
        if df is None or df.empty:
            return None
        
        row = df.iloc[-1]
        
        # 获取主要货币汇率
        cny_per_unit = {}
        for col, iso in {
            "美元": "USD", "欧元": "EUR", "英镑": "GBP", "日元": "JPY",
            "加元": "CAD", "瑞士法郎": "CHF", "瑞典克朗": "SEK",
        }.items():
            v = row.get(col)
            if v and float(v) > 0:
                cny_per_unit[iso] = float(v) / 100.0
        
        needed = {"USD", "EUR", "JPY", "GBP", "CAD", "SEK", "CHF"}
        if not needed.issubset(cny_per_unit):
            return None
        
        # 计算交叉汇率
        eur_usd = cny_per_unit["EUR"] / cny_per_unit["USD"]
        usd_jpy = cny_per_unit["USD"] / cny_per_unit["JPY"]
        gbp_usd = cny_per_unit["GBP"] / cny_per_unit["USD"]
        usd_cad = cny_per_unit["USD"] / cny_per_unit["CAD"]
        usd_sek = cny_per_unit["USD"] / cny_per_unit["SEK"]
        usd_chf = cny_per_unit["USD"] / cny_per_unit["CHF"]
        
        # DXY 公式
        dxy = 50.14348112
        dxy *= eur_usd ** -0.576
        dxy *= usd_jpy ** 0.136
        dxy *= gbp_usd ** -0.119
        dxy *= usd_cad ** 0.091
        dxy *= usd_sek ** 0.042
        dxy *= usd_chf ** 0.036
        
        return {"price": round(dxy, 4), "change_pct": None, "time": str(row.get("日期", ""))}
        
    except Exception:
        return None


def get_bond_quotes() -> list[dict]:
    """获取债券收益率。"""
    import akshare as ak
    
    symbols = load_symbols()
    bonds = symbols.get("bonds", [])
    
    results = []
    
    for bond in symbols.get("bonds", []):
        symbol = bond["symbol"]
        name = bond["name"]
        
        try:
            # 尝试获取美国国债收益率
            df = ak.bond_zh_us_rate(start_date="20260101")
            
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                # 10年期
                cols = [c for c in latest.index if "10" in str(c) and "年" in str(c)]
                if cols:
                    rate = latest[cols[0]]
                    results.append({
                        "symbol": symbol,
                        "name": name,
                        "close": round(float(rate), 4),
                        "change_pct": None,
                        "volume": 0,
                        "market_status": "closed",
                    })
                    
        except Exception as e:
            print(f"  Failed to get {symbol}: {e}")
    
    return results


def get_all_macro_quotes() -> list[dict]:
    """获取所有宏观数据。"""
    results = []
    results.extend(get_commodity_quotes())
    results.extend(get_forex_quotes())
    results.extend(get_bond_quotes())
    return results
