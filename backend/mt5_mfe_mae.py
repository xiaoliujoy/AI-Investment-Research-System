#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trader OS · Phase 2 —— MFE / MAE 轨迹重建（Behavior Engine v0.1）

目的（见 docs/trader_os_behavior_engine_v0.1.md §7）：
  判断单笔交易是「止损问题」还是「入场问题」，而非仅看存活时间。

    MFE (Max Favorable Excursion) = 持仓期间价格朝有利方向的最大移动
    MAE (Max Adverse Excursion)   = 持仓期间价格朝不利方向的最大移动

    BUY:  MFE = max(high) - entry,  MAE = entry - min(low)
    SELL: MFE = entry - min(low),  MAE = max(high) - entry

    direction_correct = MFE > 0（方向至少对过）

数据依赖（当前阻塞）：
  mt5_raw/ 目前只有 deals / orders / trades，**没有价格轨迹**。
  必须先导出 XAUUSD 的 K 线（推荐 M15，含 epoch 秒 time 列）到：
      mt5_raw/XAUUSD_M15.csv  (time,open,high,low,close)
  可用 backend/mt5_export.py 扩展 bar 导出（需本机 MT5 运行）。

用法：
  python mt5_mfe_mae.py            # 读 mt5_raw/XAUUSD_M15.csv + trades，写报告
  python mt5_mfe_mae.py --bars X.csv --trades T.csv --out report.json

输出：
  mt5_raw/mfe_mae_report.json / .csv
    position_id, symbol, direction, entry_time, exit_time,
    mfe_usd, mae_usd, mfe_price, mae_price, direction_correct
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "mt5_raw")

DEFAULT_BARS = os.path.join(RAW, "XAUUSD_M15.csv")
DEFAULT_TRADES = os.path.join(RAW, "mt5_history_trades.csv")
DEFAULT_OUT = os.path.join(RAW, "mfe_mae_report")

CONTRACT_SIZE = 100.0  # XAUUSD: 1 lot = 100 oz


def load_bars(path):
    """返回 [(epoch, open, high, low, close), ...]，按时间升序。"""
    bars = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            t = int(float(row.get("time") or row.get("Time") or 0))
            o = float(row["open"] if "open" in row else row["Open"])
            h = float(row["high"] if "high" in row else row["High"])
            lo = float(row["low"] if "low" in row else row["Low"])
            c = float(row["close"] if "close" in row else row["Close"])
            bars.append((t, o, h, lo, c))
    bars.sort(key=lambda x: x[0])
    return bars


def load_trades(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def entry_price_for(row, bars, entry_t):
    """优先用 bar 在 entry_time 的开盘价近似；后续可接 deals 精确价。"""
    for b in bars:
        if b[0] >= entry_t:
            return b[1]
    return None


def compute(bars, entry_t, exit_t, direction, volume, entry_price):
    seg = [b for b in bars if entry_t <= b[0] <= exit_t]
    if not seg or entry_price is None:
        return None
    highs = [b[2] for b in seg]
    lows = [b[3] for b in seg]
    if direction.upper() == "BUY":
        mfe_p = max(highs) - entry_price
        mae_p = entry_price - min(lows)
    else:
        mfe_p = entry_price - min(lows)
        mae_p = max(highs) - entry_price
    vol = float(volume)
    mfe_usd = mfe_p * vol * CONTRACT_SIZE
    mae_usd = mae_p * vol * CONTRACT_SIZE
    return {
        "mfe_usd": round(mfe_usd, 2),
        "mae_usd": round(mae_usd, 2),
        "mfe_price": round(mfe_p, 4),
        "mae_price": round(mae_p, 4),
        "direction_correct": mfe_usd > 0,
    }


def reconstruct(bars, trades):
    out = []
    for tr in trades:
        sym = tr.get("symbol", "")
        if "XAUUSD" not in sym:
            continue
        try:
            entry_t = int(float(tr["entry_time"]))
            exit_t = int(float(tr["exit_time"]))
            direction = tr["direction"]
            volume = float(tr.get("volume", 1))
        except (KeyError, ValueError):
            continue
        ep = entry_price_for(tr, bars, entry_t)
        res = compute(bars, entry_t, exit_t, direction, volume, ep)
        if res is None:
            continue
        out.append({
            "position_id": tr.get("position_id"),
            "symbol": sym,
            "direction": direction,
            "entry_time": entry_t,
            "exit_time": exit_t,
            **res,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", default=DEFAULT_BARS)
    ap.add_argument("--trades", default=DEFAULT_TRADES)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    if not os.path.exists(args.bars):
        print("❌ 缺少 K 线数据：", args.bars)
        print("   需先从 MT5 导出 XAUUSD M15 OHLC（time 列为 epoch 秒）到此路径。")
        print("   导出后可扩展 backend/mt5_export.py 的 bar 导出，或手动 Copy As CSV。")
        sys.exit(2)
    if not os.path.exists(args.trades):
        print("❌ 缺少 trades：", args.trades)
        sys.exit(2)

    bars = load_bars(args.bars)
    trades = load_trades(args.trades)
    results = reconstruct(bars, trades)

    json_path = args.out + ".json"
    csv_path = args.out + ".csv"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "position_id", "symbol", "direction", "entry_time", "exit_time",
            "mfe_usd", "mae_usd", "mfe_price", "mae_price", "direction_correct"])
        w.writeheader()
        w.writerows(results)

    n_dir_ok = sum(1 for r in results if r["direction_correct"])
    print("✅ MFE/MAE 重建完成：%d 笔（方向曾正确 %d 笔，%.1f%%）" %
          (len(results), n_dir_ok, 100.0 * n_dir_ok / max(len(results), 1)))
    print("   报告：", json_path)
    # 提示性统计：方向对但亏 / 方向错（典型入场问题）
    wrong = [r for r in results if not r["direction_correct"]]
    print("   方向从未正确（疑似入场问题）: %d 笔" % len(wrong))


if __name__ == "__main__":
    main()
