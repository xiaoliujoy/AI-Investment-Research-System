"""统一采集器。

采集所有全球市场数据并保存到数据库。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from global_market.data_adapter import (
    get_us_index_quotes,
    get_us_stock_quotes,
    get_asia_index_quotes,
    get_all_macro_quotes,
)

BEIJING = timezone(timedelta(hours=8))


def collect_all() -> dict:
    """采集所有全球市场数据。
    
    Returns:
        {
            "date": "2026-07-10",
            "us_indices": [...],
            "us_stocks": [...],
            "asia_indices": [...],
            "macro": [...],
            "total_count": 20
        }
    """
    now = datetime.now(BEIJING)
    date_str = now.strftime("%Y-%m-%d")
    
    print(f"Collecting global market data for {date_str}...")
    
    result = {
        "date": date_str,
        "us_indices": [],
        "us_stocks": [],
        "asia_indices": [],
        "macro": [],
        "total_count": 0,
    }
    
    # 1. US indices
    print("  US indices...")
    us_indices = get_us_index_quotes()
    result["us_indices"] = us_indices
    print(f"    Got {len(us_indices)} indices")
    
    # 2. US stocks
    print("  US tech stocks...")
    us_stocks = get_us_stock_quotes()
    result["us_stocks"] = us_stocks
    print(f"    Got {len(us_stocks)} stocks")
    
    # 3. Asia indices
    print("  Asia indices...")
    asia_indices = get_asia_index_quotes()
    result["asia_indices"] = asia_indices
    print(f"    Got {len(asia_indices)} indices")
    
    # 4. Macro
    print("  Macro data...")
    macro = get_all_macro_quotes()
    result["macro"] = macro
    print(f"    Got {len(macro)} macro indicators")
    
    result["total_count"] = len(us_indices) + len(us_stocks) + len(asia_indices) + len(macro)
    
    print(f"Total: {result['total_count']} data points collected")
    
    return result


def save_to_database(data: dict):
    """保存采集数据到数据库。"""
    from database import models
    
    date_str = data["date"]
    all_items = []
    
    # 合并所有数据
    for category in ["us_indices", "us_stocks", "asia_indices", "macro"]:
        items = data.get(category, [])
        for item in items:
            all_items.append({
                "date": date_str,
                "symbol": item.get("symbol", ""),
                "name": item.get("name", ""),
                "close": item.get("close"),
                "change_pct": item.get("change_pct"),
                "volume": item.get("volume", 0),
                "market_status": item.get("market_status", "closed"),
            })
    
    # 批量保存
    conn = models.get_db()
    now = time.time()
    
    for item in all_items:
        conn.execute("""
            INSERT OR REPLACE INTO global_market_daily 
            (date, symbol, name, close, change_pct, volume, market_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            item["date"],
            item["symbol"],
            item["name"],
            item["close"],
            item["change_pct"],
            item["volume"],
            item["market_status"],
        ))
    
    conn.commit()
    conn.close()
    
    print(f"Saved {len(all_items)} records to database")


def collect_and_save():
    """采集并保存。"""
    data = collect_all()
    save_to_database(data)
    return data


if __name__ == "__main__":
    collect_and_save()
