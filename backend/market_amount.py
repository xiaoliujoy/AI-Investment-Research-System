"""市场成交额数据层 — 两市成交额、变化率、均值。

数据来源：
  实时：腾讯行情 API（qt.gtimg.cn）
  历史：腾讯历史K线 + 比值估算法
  存储：本地 SQLite 数据库
"""

from __future__ import annotations

import sqlite3
import time
import urllib.request
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8))

_DB_PATH = Path(__file__).parent / "data" / "strategy.db"


def _get_db() -> sqlite3.Connection:
    """获取数据库连接。"""
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_amount (
            date TEXT PRIMARY KEY,
            sh_amount REAL,
            sz_amount REAL,
            total_amount REAL,
            created_at REAL
        )
    """)
    conn.commit()
    return conn


def _fetch_turnover_tencent() -> dict:
    """从腾讯实时 API 获取成交额。"""
    url = "https://qt.gtimg.cn/q=sh000001,sz399001"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("gbk")
    
    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "~" not in line:
            continue
        parts = line.split("~")
        if len(parts) < 36:
            continue
        
        name = parts[1]
        combined = parts[35]
        
        if "/" in combined:
            _, _, amt_str = combined.split("/")
            amount_yi = float(amt_str) / 100000000
        else:
            amount_yi = float(parts[37]) / 10000
        
        if "上证" in name:
            result["sh"] = round(amount_yi, 2)
        elif "深证" in name:
            result["sz"] = round(amount_yi, 2)
    
    return result


def _fetch_hist_kline(symbol: str, days: int = 25) -> list[list]:
    """获取历史K线数据。"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{days},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    
    key = symbol  # e.g. "sh000001"
    if key in data.get("data", {}):
        return data["data"][key].get("day", [])
    return []


def backfill_historical_turnover() -> int:
    """回填历史成交额数据。
    
    方法：用当日实际成交额 / 当日成交量 = 比值
    然后用比值 * 历史成交量 = 估算历史成交额
    
    Returns:
        回填的天数
    """
    # 获取当日实时数据
    realtime = _fetch_turnover_tencent()
    sh_today = realtime.get("sh", 0)
    sz_today = realtime.get("sz", 0)
    
    if sh_today <= 0 and sz_today <= 0:
        return 0
    
    # 获取今日Volume（用于计算比值）
    # 从历史K线的最后一条获取今日volume
    sh_kline = _fetch_hist_kline("sh000001", 25)
    sz_kline = _fetch_hist_kline("sz399001", 25)
    
    if not sh_kline or not sz_kline:
        return 0
    
    # 计算比值
    sh_vol_today = float(sh_kline[-1][5])
    sz_vol_today = float(sz_kline[-1][5])
    
    sh_ratio = sh_today / sh_vol_today if sh_vol_today > 0 else 0
    sz_ratio = sz_today / sz_vol_today if sz_vol_today > 0 else 0
    
    # 回填历史数据
    conn = _get_db()
    now = datetime.now(BEIJING)
    today = now.strftime("%Y-%m-%d")
    inserted = 0
    
    # 创建日期到volume的映射
    sh_vol_map = {d[0]: float(d[5]) for d in sh_kline}
    sz_vol_map = {d[0]: float(d[5]) for d in sz_kline}
    
    # 获取所有日期
    all_dates = sorted(set(list(sh_vol_map.keys()) + list(sz_vol_map.keys())))
    
    for date_str in all_dates:
        if date_str == today:
            # 今日数据使用实时值
            sh_amount = sh_today
            sz_amount = sz_today
        else:
            # 历史数据使用比值估算
            sh_amount = sh_vol_map.get(date_str, 0) * sh_ratio
            sz_amount = sz_vol_map.get(date_str, 0) * sz_ratio
        
        total = sh_amount + sz_amount
        
        if total <= 0:
            continue
        
        # 检查是否已存在
        existing = conn.execute(
            "SELECT date FROM market_amount WHERE date = ?", (date_str,)
        ).fetchone()
        
        if not existing:
            conn.execute("""
                INSERT INTO market_amount (date, sh_amount, sz_amount, total_amount, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (date_str, round(sh_amount, 2), round(sz_amount, 2), round(total, 2), time.time()))
            inserted += 1
    
    conn.commit()
    conn.close()
    
    return inserted


def get_market_amount(store: bool = True) -> dict:
    """获取市场成交额数据。"""
    now = datetime.now(BEIJING)
    today = now.strftime("%Y-%m-%d")
    
    # 获取实时数据
    realtime = _fetch_turnover_tencent()
    sh_amount = realtime.get("sh", 0)
    sz_amount = realtime.get("sz", 0)
    total = sh_amount + sz_amount
    
    result = {
        "date": today,
        "sh_amount": sh_amount,
        "sz_amount": sz_amount,
        "total_amount": total,
        "change_rate": None,
        "avg_5d": None,
        "avg_20d": None,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # 存入数据库
    if store and total > 0:
        conn = _get_db()
        conn.execute("""
            INSERT OR REPLACE INTO market_amount 
            (date, sh_amount, sz_amount, total_amount, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (today, sh_amount, sz_amount, total, time.time()))
        conn.commit()
        conn.close()
    
    # 回填历史数据（如果数据库中历史数据不足）
    conn = _get_db()
    count = conn.execute("SELECT COUNT(*) FROM market_amount").fetchone()[0]
    
    if count < 20:
        backfill_historical_turnover()
    
    # 计算变化率
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT total_amount FROM market_amount WHERE date = ?", (yesterday,)
    ).fetchone()
    
    if row and row["total_amount"] > 0:
        result["change_rate"] = round(
            (total - row["total_amount"]) / row["total_amount"], 4
        )
    
    # 计算5日均值
    rows_5d = conn.execute(
        "SELECT total_amount FROM market_amount WHERE date >= ? ORDER BY date DESC LIMIT 5",
        ((now - timedelta(days=7)).strftime("%Y-%m-%d"),)
    ).fetchall()
    
    if rows_5d:
        result["avg_5d"] = round(sum(r["total_amount"] for r in rows_5d) / len(rows_5d), 2)
    
    # 计算20日均值
    rows_20d = conn.execute(
        "SELECT total_amount FROM market_amount WHERE date >= ? ORDER BY date DESC LIMIT 20",
        ((now - timedelta(days=30)).strftime("%Y-%m-%d"),)
    ).fetchall()
    
    if rows_20d:
        result["avg_20d"] = round(sum(r["total_amount"] for r in rows_20d) / len(rows_20d), 2)
    
    conn.close()
    return result
