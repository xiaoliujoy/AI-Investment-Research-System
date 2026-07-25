"""全球相对强度(RPS)计算器。

计算不同资产在5日/20日/60日的相对表现。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from global_market.config import load_scoring_config

BEIJING = timezone(timedelta(hours=8))


def calc_rps(symbols: list[dict], lookback_days: int = 60) -> list[dict]:
    """计算相对强度。
    
    Args:
        symbols: 标的列表 [{symbol, name, ...}]
        lookback_days: 回看天数
    
    Returns:
        [
            {
                "symbol": "NDX",
                "name": "纳斯达克",
                "return_5d": 2.5,
                "return_20d": 8.2,
                "return_60d": 15.3,
                "global_rank": 1,
                "relative_score": 95
            },
            ...
        ]
    """
    from database import models
    
    now = datetime.now(BEIJING)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=lookback_days + 10)).strftime("%Y-%m-%d")
    
    results = []
    
    for sym in symbols:
        symbol = sym["symbol"]
        name = sym["name"]
        
        # 获取历史数据
        conn = models.get_db()
        rows = conn.execute("""
            SELECT date, close FROM global_market_daily 
            WHERE symbol = ? AND date <= ?
            ORDER BY date DESC LIMIT ?
        """, (symbol, end_date, lookback_days + 10)).fetchall()
        conn.close()
        
        if len(rows) < 2:
            continue
        
        # 反转顺序（从早到晚）
        rows = list(reversed(rows))
        
        # 计算收益率
        latest_close = rows[-1]["close"]
        if latest_close is None:
            continue
        
        returns = {}
        for period_name, period_days in [("return_5d", 5), ("return_20d", 20), ("return_60d", 60)]:
            if len(rows) > period_days:
                past_close = rows[-period_days - 1]["close"]
                if past_close and past_close > 0:
                    returns[period_name] = round((latest_close - past_close) / past_close * 100, 2)
                else:
                    returns[period_name] = None
            else:
                returns[period_name] = None
        
        results.append({
            "symbol": symbol,
            "name": name,
            "close": latest_close,
            **returns,
        })
    
    # 排名（基于20日收益率）
    results_with_return = [r for r in results if r.get("return_20d") is not None]
    results_with_return.sort(key=lambda x: x["return_20d"], reverse=True)
    
    for i, r in enumerate(results_with_return, 1):
        r["global_rank"] = i
        # 相对分数 (0-100)
        r["relative_score"] = max(0, 100 - (i - 1) * 10)
    
    # 没有收益率的放在最后
    results_without_return = [r for r in results if r.get("return_20d") is None]
    for r in results_without_return:
        r["global_rank"] = 999
        r["relative_score"] = 0
    
    return results_with_return + results_without_return


def calc_all_rps() -> list[dict]:
    """计算所有标的的RPS。"""
    from global_market.config import load_symbols
    
    symbols = load_symbols()
    
    all_symbols = []
    for category in ["us_indices", "us_tech", "asia_indices"]:
        items = symbols.get(category, [])
        for item in items:
            all_symbols.append({
                "symbol": item["symbol"],
                "name": item["name"],
            })
    
    return calc_rps(all_symbols)


def save_rps_to_json(rps: list[dict], output_path: Path):
    """保存RPS到JSON文件。"""
    now = datetime.now(BEIJING)
    
    data = {
        "date": now.strftime("%Y-%m-%d"),
        "rps": rps,
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    rps = calc_all_rps()
    
    output = Path(__file__).parent.parent / "output" / "global_rps.json"
    save_rps_to_json(rps, output)
    
    print("RPS Results:")
    for r in rps[:10]:
        print(f"  {r['symbol']}: 20d={r.get('return_20d', 'N/A')}%, rank={r.get('global_rank', 'N/A')}")
