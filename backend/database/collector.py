"""每日数据采集器。

收盘后自动采集当日数据，写入数据库。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import models


def collect_market_daily(date: str = None) -> dict:
    """采集市场日线数据。
    
    Args:
        date: 日期 YYYY-MM-DD，默认为今天
    
    Returns:
        采集到的数据
    """
    import astock
    
    if date is None:
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    
    # 获取市场情绪
    try:
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        d = {}
    
    def num(v):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0
    
    up = num(d.get("上涨", 0))
    down = num(d.get("下跌", 0))
    flat = num(d.get("平盘", 0))
    zt = num(d.get("涨停", 0))
    dt = num(d.get("跌停", 0))
    zt_real = num(d.get("真实涨停", 0))
    dt_real = num(d.get("真实跌停", 0))
    
    # 获取成交额
    try:
        from market_amount import get_market_amount
        amount_data = get_market_amount(store=False)
        total_amount = amount_data.get("total_amount", 0)
        sh_amount = amount_data.get("sh_amount", 0)
        sz_amount = amount_data.get("sz_amount", 0)
    except Exception:
        total_amount = 0
        sh_amount = 0
        sz_amount = 0
    
    # 获取连板数据
    try:
        from market import get_short_term_emotion
        emotion = get_short_term_emotion()
        max_boards = emotion.get("max_boards", 0)
        lianban_count = emotion.get("lianban_count", 0)
        seal_rate = emotion.get("seal_rate", 0)
        break_rate = emotion.get("break_rate", 0)
        promotion_rate = emotion.get("promotion_rate", 0)
    except Exception:
        max_boards = 0
        lianban_count = 0
        seal_rate = 0
        break_rate = 0
        promotion_rate = 0
    
    # 计算均值（从数据库获取历史）
    avg_5d = None
    avg_20d = None
    change_rate = None
    
    history = models.get_latest_market_daily(20)
    if history:
        amounts = [h["total_amount"] for h in history if h.get("total_amount")]
        if len(amounts) >= 1:
            prev = amounts[0]
            if prev > 0:
                change_rate = round((total_amount - prev) / prev, 4)
        if len(amounts) >= 5:
            avg_5d = round(sum(amounts[:5]) / 5, 2)
        if len(amounts) >= 20:
            avg_20d = round(sum(amounts[:20]) / 20, 2)
    
    data = {
        "date": date,
        "total_amount": total_amount,
        "sh_amount": sh_amount,
        "sz_amount": sz_amount,
        "amount_change_rate": change_rate,
        "avg_5d_amount": avg_5d,
        "avg_20d_amount": avg_20d,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "limit_up_count": zt,
        "limit_down_count": dt,
        "real_limit_up": zt_real,
        "real_limit_down": dt_real,
        "broken_limit_count": 0,  # 需要额外计算
        "highest_board": max_boards,
        "lianban_count": lianban_count,
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_avg_return": None,  # 需要历史数据
        "yzt_win_rate": None,
        "emotion_score": None,
        "stage": None,
    }
    
    models.save_market_daily(data)
    return data


def collect_sector_daily(date: str = None) -> list[dict]:
    """采集板块日线数据。
    
    Args:
        date: 日期 YYYY-MM-DD，默认为今天
    
    Returns:
        采集到的数据列表
    """
    import astock
    
    if date is None:
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    
    # 获取板块资金流向
    try:
        f = astock._akshare().stock_fund_flow_industry(symbol="即时")
        f = f.sort_values("净额", ascending=False)
    except Exception:
        return []
    
    # 获取全市场成交额（用于计算占比）
    total_amount = 1  # 避免除零
    try:
        from market_amount import get_market_amount
        amount_data = get_market_amount(store=False)
        total_amount = amount_data.get("total_amount", 1)
    except Exception:
        pass
    
    results = []
    for _, row in f.iterrows():
        name = str(row["行业"])
        amount = float(row.get("净额", 0)) / 1e8  # 亿元
        amount_ratio = round(amount / max(total_amount, 1), 4)
        change_pct = float(row.get("行业-涨跌幅", 0) or 0)
        
        # 获取板块历史数据（计算持续性）
        history = models.get_sector_daily(name, 20)
        days_in_top5 = sum(1 for h in history if (h.get("amount_ratio") or 0) > 0.03)
        consecutive = models.get_sector_consecutive_days(name)
        
        data = {
            "date": date,
            "sector_name": name,
            "change_pct": round(change_pct, 2),
            "amount": round(amount, 2),
            "amount_ratio": amount_ratio,
            "amount_change_rate": None,  # 需要历史数据
            "net_amount": round(amount, 2),
            "up_count": None,
            "down_count": None,
            "flat_count": None,
            "limit_up_count": None,
            "cm20_count": None,
            "leader_code": None,
            "leader_name": None,
            "leader_change_pct": None,
            "leader_amount": None,
            "days_in_top5": days_in_top5,
            "consecutive_days": consecutive,
            "sector_score": None,
            "tier": None,
        }
        
        models.save_sector_daily(data)
        results.append(data)
    
    return results


def _is_st(name: str) -> int:
    """名字含 ST / 星号风险警示 / 退（退市）→ 1，否则 0。排除 ST 连板对情绪高度的虚高。"""
    if not name:
        return 0
    n = name.strip()
    if "ST" in n.upper() or n.startswith("*") or "退" in n:
        return 1
    return 0


def collect_limit_up_daily(date: str = None) -> list[dict]:
    """采集涨停日线数据。
    
    Args:
        date: 日期 YYYY-MM-DD，默认为今天
    
    Returns:
        采集到的数据列表
    """
    import astock
    
    if date is None:
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    
    date_str = date.replace("-", "")
    
    try:
        zt_list = astock.em_zt_topic_pool("getTopicZTPool", date_str, "fbt:asc")
    except Exception:
        return []
    
    if not zt_list:
        return []
    
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
        
        # 封板质量（以首次封板时间 fbt 判断早/中/尾板）
        if fbt:
            try:
                from datetime import datetime as dt
                t1 = dt.strptime(str(fbt).zfill(6), "%H%M%S")
                if t1.hour == 9 and t1.minute <= 25:
                    seal_quality = "一字"
                elif t1.hour < 10:
                    seal_quality = "早板"
                elif t1.hour < 14:
                    seal_quality = "中板"
                else:
                    seal_quality = "尾板"
            except Exception:
                seal_quality = "其他"
        else:
            seal_quality = "一字"
        
        batch.append({
            "date": date,
            "code": code,
            "name": name,
            "sector": sector,
            "board_height": board_height,
            "is_first_board": 1 if board_height == 1 else 0,
            "is_st": _is_st(name),
            "first_limit_time": str(fbt) if fbt else None,
            "last_limit_time": str(lbt) if lbt else None,
            "seal_amount": round(seal_amount, 2),
            "broken_count": int(zt.get("zbc", 0)),
            "turnover_rate": round(turnover_rate, 4),
            "float_cap": round(float_cap, 2),
            "change_pct": round(change_pct, 2),
            "amount": round(amount_yi, 2),
            "seal_quality": seal_quality,
        })
    
    models.save_limit_up_daily_batch(batch)
    return batch


def collect_stock_daily(codes: list[str], date: str = None) -> int:
    """采集个股日线数据。
    
    Args:
        codes: 股票代码列表
        date: 日期 YYYY-MM-DD，默认为今天
    
    Returns:
        写入的记录数
    """
    import astock
    
    if date is None:
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    
    total = 0
    
    for code in codes:
        try:
            klines = astock.kline(code, category=4, offset=5)
            if not klines:
                continue
            
            # 获取最新一天的数据
            latest = klines[-1]
            dt = latest.get("datetime", "")
            if dt and dt[:10] != date:
                continue
            
            # 计算均线
            closes = [k["close"] for k in klines]
            ma5 = sum(closes[-5:]) / min(len(closes), 5) if len(closes) >= 5 else None
            ma10 = sum(closes[-10:]) / min(len(closes), 10) if len(closes) >= 10 else None
            ma20 = sum(closes[-20:]) / min(len(closes), 20) if len(closes) >= 20 else None
            ma60 = sum(closes[-60:]) / min(len(closes), 60) if len(closes) >= 60 else None
            
            models.save_stock_daily({
                "date": date,
                "code": code,
                "name": latest.get("name", ""),
                "sector": latest.get("sector", ""),
                "open": latest.get("open", 0),
                "high": latest.get("high", 0),
                "low": latest.get("low", 0),
                "close": latest.get("close", 0),
                "volume": latest.get("volume", 0),
                "amount": latest.get("amount", 0) / 1e8,
                "change_pct": latest.get("change_pct"),
                "turnover_rate": latest.get("volume", 0) * 100 / 1e9,
                "market_cap": latest.get("mcap"),
                "float_cap": latest.get("float_cap"),
                "ma5": round(ma5, 4) if ma5 else None,
                "ma10": round(ma10, 4) if ma10 else None,
                "ma20": round(ma20, 4) if ma20 else None,
                "ma60": round(ma60, 4) if ma60 else None,
                "high_20d": None,
                "low_20d": None,
                "is_new_high_20d": 0,
                "volume_ratio": latest.get("volume_ratio"),
                "main_net_buy": latest.get("main_net_buy"),
            })
            
            total += 1
            
        except Exception:
            pass
        
        time.sleep(0.3)
    
    return total


def collect_daily(date: str = None):
    """执行每日全量采集。
    
    Args:
        date: 日期 YYYY-MM-DD，默认为今天
    """
    if date is None:
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    
    print(f"开始采集 {date} 数据...")
    
    # 1. 市场日线
    print("  采集市场日线...")
    market_data = collect_market_daily(date)
    print(f"    成交额: {market_data.get('total_amount', 0):.0f}亿")
    
    # 2. 板块日线
    print("  采集板块日线...")
    sector_data = collect_sector_daily(date)
    print(f"    板块数: {len(sector_data)}")
    
    # 3. 涨停日线
    print("  采集涨停日线...")
    limit_up_data = collect_limit_up_daily(date)
    print(f"    涨停数: {len(limit_up_data)}")
    
    # 4. 个股日线（TOP 100）
    print("  采集个股日线 (TOP 100)...")
    try:
        import astock
        top_codes = [s["code"] for s in astock.market_turnover_rank(100)]
        stock_count = collect_stock_daily(top_codes, date)
        print(f"    个股数: {stock_count}")
    except Exception as e:
        print(f"    失败: {e}")
    
    print(f"采集完成！")


if __name__ == "__main__":
    collect_daily()
