"""Phase A-1: 从 TDX 量价(OHLCV)反算技术字段并回填 stock_daily。

只处理最近 ~120 个交易日的窗口（含 ~180 日缓冲用于 MA60），
避免对 1400 万行全量 UPDATE 造成 WAL 膨胀。

计算字段：
  ma5 / ma10 / ma20 / ma60  (收盘均价)
  high_20d / low_20d        (近 20 日高低，用于"密集成交区/突破")
  is_new_high_20d           (当日收盘创 20 日新高 -> 突破信号)
  volume_ratio             (量比 = 当日成交量 / 前 5 日日均成交量)
  change_pct               (当日涨跌幅)
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB = Path(__file__).parent / "database" / "vibe_research.db"
WINDOW = 120          # 实际回填的交易日窗口
LOOKBACK = 60         # 额外缓冲（保证 MA60 有足够前序数据）


def get_recent_cutoffs(c: sqlite3.Connection):
    dates = [r[0] for r in c.execute(
        "SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT ?",
        (WINDOW + LOOKBACK,),
    )]
    dates_sorted = sorted(dates)  # 升序
    lookback_cut = dates_sorted[0]                 # 最早需要的数据日（含缓冲）
    fill_cut = dates_sorted[LOOKBACK]              # 实际回填起点
    return lookback_cut, fill_cut


def compute_for_stock(rows):
    """rows: list of (date, open, high, low, close, volume, amount) 按日期升序。
    返回 dict: date -> (ma5,ma10,ma20,ma60,high20,low20,is_new_high,vol_ratio,chg)
    对数据中可能出现的 None（停牌/缺字段）做全面防御，避免崩溃。"""
    n = len(rows)
    closes = [r[4] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    vols = [r[5] for r in rows]
    out = {}
    for i in range(n):
        def avg(seq, period):
            if i + 1 < period:
                return None
            valid = [v for v in seq[i + 1 - period:i + 1] if v is not None]
            if not valid:
                return None
            return sum(valid) / len(valid)
        ma5 = avg(closes, 5)
        ma10 = avg(closes, 10)
        ma20 = avg(closes, 20)
        ma60 = avg(closes, 60)
        # 20 日高低（跳过 None）
        if i + 1 >= 20:
            hv = [h for h in highs[i - 19:i + 1] if h is not None]
            lv = [l for l in lows[i - 19:i + 1] if l is not None]
        else:
            hv = [h for h in highs[:i + 1] if h is not None]
            lv = [l for l in lows[:i + 1] if l is not None]
        h20 = max(hv) if hv else None
        l20 = min(lv) if lv else None
        close = closes[i]
        is_new_high = 1 if (h20 is not None and close is not None and close >= h20) else 0
        # 量比：当日量 / 前 5 日日均量（防 None）
        if i >= 5:
            prev5 = [v for v in vols[i - 5:i] if v is not None]
            vavg = sum(prev5) / len(prev5) if prev5 else 0
            vol_ratio = (vols[i] / vavg) if (vols[i] is not None and vavg > 0) else None
        else:
            vol_ratio = None
        # 涨跌幅（防 None）
        if i >= 1 and closes[i - 1] is not None and closes[i - 1] > 0 and close is not None:
            chg = (close / closes[i - 1] - 1) * 100
        else:
            chg = None
        out[rows[i][0]] = (ma5, ma10, ma20, ma60, h20, l20, is_new_high, vol_ratio, chg)
    return out


def main():
    t0 = time.time()
    c = sqlite3.connect(str(DB), timeout=30)
    lookback_cut, fill_cut = get_recent_cutoffs(c)
    print(f"缓冲起点(含) = {lookback_cut}  回填起点(含) = {fill_cut}")

    codes = [r[0] for r in c.execute(
        "SELECT DISTINCT code FROM stock_daily WHERE date >= ?", (lookback_cut,)
    )]
    print(f"涉及个股数: {len(codes)}")

    batch = []
    batch_size = 4000
    updated = 0
    for idx, code in enumerate(codes):
        rows = c.execute(
            "SELECT date, open, high, low, close, volume, amount "
            "FROM stock_daily WHERE code=? AND date>=? ORDER BY date ASC",
            (code, lookback_cut),
        ).fetchall()
        if not rows:
            continue
        tech = compute_for_stock(rows)
        for d, vals in tech.items():
            if d < fill_cut:
                continue
            ma5, ma10, ma20, ma60, h20, l20, ish, vr, chg = vals
            batch.append((ma5, ma10, ma20, ma60, h20, l20, ish, vr, chg, code, d))
        if len(batch) >= batch_size:
            c.executemany(
                "UPDATE stock_daily SET ma5=?,ma10=?,ma20=?,ma60=?,high_20d=?,"
                "low_20d=?,is_new_high_20d=?,volume_ratio=?,change_pct=? "
                "WHERE code=? AND date=?",
                batch,
            )
            c.commit()
            updated += len(batch)
            batch = []
        if (idx + 1) % 500 == 0:
            print(f"  {idx+1}/{len(codes)} 已更新 {updated} 行  ({time.time()-t0:.0f}s)")
    if batch:
        c.executemany(
            "UPDATE stock_daily SET ma5=?,ma10=?,ma20=?,ma60=?,high_20d=?,"
            "low_20d=?,is_new_high_20d=?,volume_ratio=?,change_pct=? "
            "WHERE code=? AND date=?",
            batch,
        )
        c.commit()
        updated += len(batch)
    print(f"完成: 更新 {updated} 行, 耗时 {time.time()-t0:.0f}s")
    c.close()


if __name__ == "__main__":
    main()
