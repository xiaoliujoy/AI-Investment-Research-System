"""全球科技周期分析器。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

BEIJING = timezone(timedelta(hours=8))


def analyze_technology_cycle() -> dict:
    """分析科技周期。"""
    from database import models
    from global_market.config import load_theme_mapping
    
    now = datetime.now(BEIJING)
    date_str = now.strftime("%Y-%m-%d")
    
    config = load_theme_mapping()
    themes = config.get("themes", [])
    
    results = []
    
    for theme in themes:
        name = theme.get("name", "")
        description = theme.get("description", "")
        
        global_drivers = theme.get("global_drivers", [])
        driver_performance = []
        
        for driver in global_drivers:
            symbol = driver.get("symbol")
            driver_name = driver.get("name")
            
            conn = models.get_db()
            rows = conn.execute("""
                SELECT date, close, change_pct FROM global_market_daily 
                WHERE symbol = ? ORDER BY date DESC LIMIT 20
            """, (symbol,)).fetchall()
            conn.close()
            
            if rows:
                latest = rows[0]
                if len(rows) >= 20:
                    old_close = rows[19]["close"]
                    new_close = latest["close"]
                    if old_close and new_close and old_close > 0:
                        return_20d = round((new_close - old_close) / old_close * 100, 2)
                    else:
                        return_20d = None
                else:
                    return_20d = None
                
                driver_performance.append({
                    "symbol": symbol,
                    "name": driver_name,
                    "close": latest["close"],
                    "change_pct": latest["change_pct"],
                    "return_20d": return_20d,
                })
        
        valid_returns = [d["return_20d"] for d in driver_performance if d.get("return_20d") is not None]
        
        if valid_returns:
            avg_return = sum(valid_returns) / len(valid_returns)
            heat_score = min(100, max(0, 50 + avg_return * 2))
        else:
            heat_score = 50
        
        if heat_score >= 80:
            status = "accelerating"
        elif heat_score >= 60:
            status = "expanding"
        elif heat_score >= 40:
            status = "neutral"
        else:
            status = "cooling"
        
        results.append({
            "name": name,
            "description": description,
            "global_drivers": driver_performance,
            "china_mapping": theme.get("china_mapping", []),
            "heat_score": round(heat_score, 1),
            "status": status,
        })
    
    results.sort(key=lambda x: x["heat_score"], reverse=True)
    
    return {
        "date": date_str,
        "themes": results,
    }


def save_theme_mapping_json(data: dict, output_path: Path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    data = analyze_technology_cycle()
    output = Path(__file__).parent.parent / "output" / "theme_mapping.json"
    save_theme_mapping_json(data, output)
    
    for t in data["themes"]:
        print(f"{t['name']}: heat={t['heat_score']:.1f}, status={t['status']}")
