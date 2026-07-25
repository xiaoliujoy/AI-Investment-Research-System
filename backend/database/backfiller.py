"""历史数据回补器 - 完整版。

基于现有 API 能力，回补尽可能多的历史数据。

API 限制：
- limit_up: 仅当前月份
- stock_kline: 最多 800 个交易日（约3年）
- market/sector: 无法回补，需每日快照
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import models

BEIJING = timezone(timedelta(hours=8))


def backfill_limit_up_all() -> int:
    """回补涨停池数据（当前月份）。
    
    由于 API 限制，只能获取当前月份数据。
    """
    import astock
    
    now = datetime.now(BEIJING)
    # 获取当月第一天
    first_day = now.replace(day=1)
    
    total = 0
    current = first_day
    
    print(f"回补涨停池: {first_day.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}")
    
    while current <= now:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        
        date_str = current.strftime("%Y%m%d")
        date_iso = current.strftime("%Y-%m-%d")
        
        try:
            zt_list = astock.em_zt_topic_pool("getTopicZTPool", date_str, "fbt:asc")
            
            if zt_list:
                batch = []
                for zt in zt_list:
                    code = zt.get("c", "")
                    name = zt.get("n", "")
                    sector = zt.get("hybk", "")
                    board_height = int(zt.get("lbc", 1))
                    
                    fbt = zt.get("fbt", "")
                    lbt = zt.get("lbt", "")
                    
                    fund = zt.get("fund", 0)
                    seal_amount = float(fund) / 1e8 if fund else 0
                    
                    hs = zt.get("hs", 0)
                    turnover_rate = float(hs) / 100 if hs else 0
                    
                    ltsz = zt.get("ltsz", 0)
                    float_cap = float(ltsz) / 1e8 if ltsz else 0
                    
                    zdp = zt.get("zdp", 0)
                    change_pct = float(zdp)
                    
                    amount = zt.get("amount", 0)
                    amount_yi = float(amount) / 1e8 if amount else 0
                    
                    if lbt and fbt:
                        try:
                            from datetime import datetime as dt
                            t1 = dt.strptime(str(lbt), "%H%M%S")
                            if t1.hour < 10:
                                seal_quality = "早板"
                            elif t1.hour < 14:
                                seal_quality = "中板"
                            else:
                                seal_quality = "尾板"
                        except:
                            seal_quality = "其他"
                    else:
                        seal_quality = "一字"
                    
                    batch.append({
                        "date": date_iso,
                        "code": code,
                        "name": name,
                        "sector": sector,
                        "board_height": board_height,
                        "is_first_board": 1 if board_height == 1 else 0,
                        "first_limit_time": str(lbt) if lbt else None,
                        "last_limit_time": str(fbt) if fbt else None,
                        "seal_amount": round(seal_amount, 2),
                        "broken_count": int(zt.get("zbc", 0)),
                        "turnover_rate": round(turnover_rate, 4),
                        "float_cap": round(float_cap, 2),
                        "change_pct": round(change_pct, 2),
                        "amount": round(amount_yi, 2),
                        "seal_quality": seal_quality,
                    })
                
                models.save_limit_up_daily_batch(batch)
                total += len(batch)
                print(f"  {date_iso}: {len(batch)} records")
            
        except Exception as e:
            print(f"  {date_iso}: FAILED - {e}")
        
        current += timedelta(days=1)
        time.sleep(0.3)
    
    return total


def backfill_stock_daily_all(top_n: int = 500, days: int = 800) -> int:
    """回补个股日线数据。
    
    由于 mootdx API 限制，最多获取 800 个交易日（约3年）。
    
    Args:
        top_n: 回补前 N 只股票
        days: 回补天数（最大 800）
    """
    import astock
    
    # 获取股票列表
    print(f"获取成交额 TOP {top_n} 股票...")
    try:
        top_list = astock.market_turnover_rank(top_n)
        codes = [s["code"] for s in top_list]
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        return 0
    
    print(f"获取到 {len(codes)} 只股票")
    print(f"开始回补 {days} 个交易日数据...")
    
    total = 0
    errors = 0
    
    for i, code in enumerate(codes):
        try:
            # mootdx 最多返回 800 条
            klines = astock.kline(code, category=4, offset=days)
            
            if not klines:
                continue
            
            # 计算均线
            closes = [k["close"] for k in klines]
            ma5 = _calc_ma(closes, 5)
            ma10 = _calc_ma(closes, 10)
            ma20 = _calc_ma(closes, 20)
            ma60 = _calc_ma(closes, 60)
            
            for idx, kline in enumerate(klines):
                dt = kline.get("datetime", "")
                date_str = dt[:10] if dt else None
                
                if not date_str:
                    continue
                
                # 20日高低
                high_20d = None
                low_20d = None
                is_new_high = 0
                
                if idx >= 20:
                    past_20 = klines[idx-20:idx]
                    high_20d = max(k["high"] for k in past_20)
                    low_20d = min(k["low"] for k in past_20)
                    is_new_high = 1 if kline["close"] >= high_20d else 0
                
                turnover_rate = kline.get("volume", 0) * 100 / 1e9
                
                models.save_stock_daily({
                    "date": date_str,
                    "code": code,
                    "name": kline.get("name", ""),
                    "sector": kline.get("sector", ""),
                    "open": kline.get("open", 0),
                    "high": kline.get("high", 0),
                    "low": kline.get("low", 0),
                    "close": kline.get("close", 0),
                    "volume": kline.get("volume", 0),
                    "amount": kline.get("amount", 0) / 1e8,
                    "change_pct": kline.get("change_pct"),
                    "turnover_rate": turnover_rate,
                    "market_cap": kline.get("mcap"),
                    "float_cap": kline.get("float_cap"),
                    "ma5": ma5[idx] if idx < len(ma5) else None,
                    "ma10": ma10[idx] if idx < len(ma10) else None,
                    "ma20": ma20[idx] if idx < len(ma20) else None,
                    "ma60": ma60[idx] if idx < len(ma60) else None,
                    "high_20d": high_20d,
                    "low_20d": low_20d,
                    "is_new_high_20d": is_new_high,
                    "volume_ratio": kline.get("volume_ratio"),
                    "main_net_buy": kline.get("main_net_buy"),
                })
                
                total += 1
            
            if (i + 1) % 50 == 0:
                print(f"  进度: {i+1}/{len(codes)}, 累计 {total} 条")
            
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  {code}: {e}")
        
        time.sleep(0.3)
    
    print(f"完成! 总计 {total} 条, 错误 {errors} 条")
    return total


def _calc_ma(data: list[float], period: int) -> list[float | None]:
    """计算移动平均线。"""
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            ma = sum(data[i-period+1:i+1]) / period
            result.append(round(ma, 4))
    return result


def run_full_backfill(top_n: int = 500):
    """运行完整回补。"""
    print("=" * 60)
    print("历史数据回补")
    print("=" * 60)
    
    # 1. 涨停池（当前月份）
    print("\n[1/2] 涨停池数据")
    count = backfill_limit_up_all()
    print(f"  写入 {count} 条涨停记录")
    
    # 2. 个股日线（最多 800 天）
    print(f"\n[2/2] 个股日线 (TOP {top_n})")
    count = backfill_stock_daily_all(top_n=top_n, days=800)
    print(f"  写入 {count} 条个股记录")
    
    # 数据摘要
    print(f"\n{'=' * 60}")
    print("数据回补完成！")
    summary = models.get_data_summary()
    for table, count in summary.items():
        print(f"  {table}: {count} 条")
    
    # 数据范围
    conn = models.get_db()
    
    row = conn.execute("SELECT MIN(date), MAX(date) FROM stock_daily").fetchone()
    if row and row[0]:
        print(f"\n个股数据范围: {row[0]} ~ {row[1]}")
    
    row = conn.execute("SELECT MIN(date), MAX(date) FROM limit_up_daily").fetchone()
    if row and row[0]:
        print(f"涨停数据范围: {row[0]} ~ {row[1]}")
    
    conn.close()


if __name__ == "__main__":
    run_full_backfill(top_n=500)
