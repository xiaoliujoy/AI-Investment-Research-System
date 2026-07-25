"""异常强度检测器。

检测A股是否出现全球超额表现。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from global_market.config import load_scoring_config, load_symbols

BEIJING = timezone(timedelta(hours=8))


def detect_divergence() -> dict:
    """检测异常强度。
    
    Returns:
        {
            "date": "2026-07-10",
            "divergences": [
                {
                    "china_index": "STAR50",
                    "global_index": "NDX",
                    "china_return_5d": 8.4,
                    "global_return_5d": 1.2,
                    "excess_return": 7.2,
                    "level": "warning",
                    "duration_days": 3
                },
                ...
            ]
        }
    """
    from database import models
    
    now = datetime.now(BEIJING)
    date_str = now.strftime("%Y-%m-%d")
    
    config = load_scoring_config()
    threshold_warning = config.get("divergence", {}).get("thresholds", {}).get("warning", 10)
    threshold_extreme = config.get("divergence", {}).get("thresholds", {}).get("extreme", 20)
    
    # A股 vs 海外 对标
    pairs = [
        {"china": "STAR50", "china_name": "科创50", "global": "NDX", "global_name": "纳斯达克"},
        {"china": "CSI1000", "china_name": "中证1000", "global": "SPX", "global_name": "标普500"},
        {"china": "ChiNext", "china_name": "创业板指", "global": "SOX", "global_name": "费城半导体"},
    ]
    
    divergences = []
    
    for pair in pairs:
        china_sym = pair["china"]
        global_sym = pair["global"]
        
        # 获取A股数据（从 stock_daily 或市场数据）
        china_return = _get_index_return(china_sym, 5)
        global_return = _get_index_return(global_sym, 5)
        
        if china_return is not None and global_return is not None:
            excess = china_return - global_return
            
            if excess >= threshold_extreme:
                level = "extreme"
            elif excess >= threshold_warning:
                level = "warning"
            else:
                level = "normal"
            
            if level != "normal":
                # 计算持续时间
                duration = _calc_excess_duration(china_sym, global_sym, threshold_warning)
                
                divergences.append({
                    "china_index": china_sym,
                    "china_name": pair["china_name"],
                    "global_index": global_sym,
                    "global_name": pair["global_name"],
                    "china_return_5d": china_return,
                    "global_return_5d": global_return,
                    "excess_return": round(excess, 2),
                    "level": level,
                    "duration_days": duration,
                })
    
    # 按超额收益排序
    divergences.sort(key=lambda x: x["excess_return"], reverse=True)
    
    return {
        "date": date_str,
        "divergences": divergences,
    }


def _get_index_return(symbol: str, days: int) -> float | None:
    """获取指数最近N日收益率。"""
    from database import models
    
    conn = models.get_db()
    rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = ? ORDER BY date DESC LIMIT ?
    """, (symbol, days + 2)).fetchall()
    conn.close()
    
    if len(rows) < 2:
        return None
    
    latest = rows[0]["close"]
    
    # 找到N天前的数据
    if len(rows) > days:
        old = rows[days]["close"]
    else:
        old = rows[-1]["close"]
    
    if latest is None or old is None or old == 0:
        return None
    
    return round((latest - old) / old * 100, 2)


def _calc_excess_duration(china_sym: str, global_sym: str, threshold: float) -> int:
    """计算超额收益持续时间。"""
    from database import models
    
    conn = models.get_db()
    
    # 获取两组数据
    china_rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = ? ORDER BY date DESC LIMIT 30
    """, (china_sym,)).fetchall()
    
    global_rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = ? ORDER BY date DESC LIMIT 30
    """, (global_sym,)).fetchall()
    
    conn.close()
    
    if len(china_rows) < 2 or len(global_rows) < 2:
        return 0
    
    # 计算每日超额收益
    duration = 0
    for i in range(min(len(china_rows), len(global_rows))):
        if i + 1 < len(china_rows) and i + 1 < len(global_rows):
            china_today = china_rows[i]["close"]
            china_yesterday = china_rows[i + 1]["close"]
            global_today = global_rows[i]["close"]
            global_yesterday = global_rows[i + 1]["close"]
            
            if all([china_today, china_yesterday, global_today, global_yesterday]):
                china_ret = (china_today - china_yesterday) / china_yesterday * 100
                global_ret = (global_today - global_yesterday) / global_yesterday * 100
                excess = china_ret - global_ret
                
                if excess > threshold / 5:  # 日均超额
                    duration += 1
                else:
                    break
    
    return duration


def save_divergence_json(data: dict, output_path: Path):
    """保存异常检测JSON。"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    data = detect_divergence()
    
    output = Path(__file__).parent.parent / "output" / "divergence.json"
    save_divergence_json(data, output)
    
    print("Divergence Detection:")
    if data["divergences"]:
        for d in data["divergences"]:
            print(f"  {d['china_name']} vs {d['global_name']}: excess={d['excess_return']}% ({d['level']})")
    else:
        print("  No significant divergence detected")
