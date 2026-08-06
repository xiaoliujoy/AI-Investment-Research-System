#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B0.5 数据审计层 —— Trader OS / Outcome Analysis 分支
冻结文档 docs/trader_os_v0.1_architecture_freeze.md §12.4

职责：在进入 B2 行为分析之前，先回答「这批数据到底是什么」。
本层只输出事实，不做行为解读，不出建议。

用法:
    python mt5_audit.py [--file ../mt5_raw/mt5_history_trades.csv]

关键口径（必须显式声明，否则统计不可复现）：
  1. 剔除 position_id == 0 的行（MT5 的 balance/入金记录，非交易）
  2. 真实净利 = net_profit + commission + swap（导出文件三者分列）
  3. WIN/LOSS 按「真实净利 > 0 / < 0」判定，== 0 单列为 FLAT
  4. 时间戳为 MT5 服务器时间（FTMO 通常 GMT+2/+3），时段统计口径为服务器时间
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(HERE, "..", "mt5_raw", "mt5_history_trades.csv")


def load_trades(path):
    rows = []
    excluded = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            pid = (r.get("position_id") or "").strip()
            if pid in ("", "0"):
                excluded.append(r)
                continue
            try:
                net = float(r.get("net_profit") or 0)
                com = float(r.get("commission") or 0)
                swp = float(r.get("swap") or 0)
                ein = int(float(r.get("entry_time") or 0))
                eout = int(float(r.get("exit_time") or 0))
            except ValueError:
                excluded.append(r)
                continue
            pnl = round(net + com + swp, 2)
            rows.append({
                "position_id": pid,
                "symbol": (r.get("symbol") or "UNKNOWN").strip() or "UNKNOWN",
                "direction": (r.get("direction") or "").strip(),
                "volume": float(r.get("volume") or 0),
                "gross": net,
                "cost": round(com + swp, 2),
                "pnl": pnl,
                "entry_time": ein,
                "exit_time": eout,
                "hold_sec": max(0, eout - ein),
                "result": "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT"),
            })
    rows.sort(key=lambda x: x["entry_time"])
    return rows, excluded


def fmt_ts(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def fmt_dur(sec):
    if sec < 60:
        return f"{sec}秒"
    if sec < 3600:
        return f"{sec/60:.1f}分钟"
    if sec < 86400:
        return f"{sec/3600:.1f}小时"
    return f"{sec/86400:.1f}天"


def max_streak(rows, kind):
    best = cur = 0
    for r in rows:
        if r["result"] == kind:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def audit(rows, excluded):
    out = {}
    n = len(rows)
    if n == 0:
        return {"error": "no valid trades"}

    wins = [r for r in rows if r["result"] == "WIN"]
    losses = [r for r in rows if r["result"] == "LOSS"]
    flats = [r for r in rows if r["result"] == "FLAT"]

    t0, t1 = rows[0]["entry_time"], rows[-1]["entry_time"]
    span_days = max(1, (t1 - t0) / 86400)

    # 1 数量与跨度
    out["1_scale"] = {
        "trade_count": n,
        "excluded_rows": len(excluded),
        "first_trade": fmt_ts(t0),
        "last_trade": fmt_ts(t1),
        "span_days": round(span_days, 1),
        "trades_per_month": round(n / (span_days / 30.44), 1),
        "active_days": len({fmt_ts(r["entry_time"])[:10] for r in rows}),
    }

    # 2 品种分布
    by_sym = defaultdict(lambda: {"n": 0, "pnl": 0.0, "win": 0, "vol": 0.0})
    for r in rows:
        s = by_sym[r["symbol"]]
        s["n"] += 1
        s["pnl"] = round(s["pnl"] + r["pnl"], 2)
        s["vol"] = round(s["vol"] + r["volume"], 2)
        if r["result"] == "WIN":
            s["win"] += 1
    out["2_symbols"] = sorted(
        [{"symbol": k, "n": v["n"], "share_pct": round(100 * v["n"] / n, 1),
          "net_pnl": v["pnl"], "win_rate_pct": round(100 * v["win"] / v["n"], 1),
          "total_lots": v["vol"]}
         for k, v in by_sym.items()],
        key=lambda x: -x["n"])

    # 3 时间分布（服务器时间）
    by_hour = defaultdict(lambda: {"n": 0, "pnl": 0.0, "win": 0})
    by_dow = defaultdict(lambda: {"n": 0, "pnl": 0.0, "win": 0})
    by_month = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for r in rows:
        dt = datetime.fromtimestamp(r["entry_time"], tz=timezone.utc)
        for bucket, key in ((by_hour, dt.hour), (by_dow, dt.weekday())):
            b = bucket[key]
            b["n"] += 1
            b["pnl"] = round(b["pnl"] + r["pnl"], 2)
            if r["result"] == "WIN":
                b["win"] += 1
        m = by_month[dt.strftime("%Y-%m")]
        m["n"] += 1
        m["pnl"] = round(m["pnl"] + r["pnl"], 2)
    dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out["3_time"] = {
        "by_hour": [{"hour": h, "n": v["n"], "net_pnl": v["pnl"],
                     "win_rate_pct": round(100 * v["win"] / v["n"], 1)}
                    for h, v in sorted(by_hour.items())],
        "by_weekday": [{"dow": dows[d], "n": v["n"], "net_pnl": v["pnl"],
                        "win_rate_pct": round(100 * v["win"] / v["n"], 1)}
                       for d, v in sorted(by_dow.items())],
        "by_month": [{"month": k, "n": v["n"], "net_pnl": v["pnl"]}
                     for k, v in sorted(by_month.items())],
    }

    # 4 盈亏结构
    gross_win = round(sum(r["pnl"] for r in wins), 2)
    gross_loss = round(sum(r["pnl"] for r in losses), 2)
    total_cost = round(sum(r["cost"] for r in rows), 2)
    avg_win = round(gross_win / len(wins), 2) if wins else 0.0
    avg_loss = round(gross_loss / len(losses), 2) if losses else 0.0
    out["4_pnl"] = {
        "net_profit": round(gross_win + gross_loss, 2),
        "gross_profit": gross_win,
        "gross_loss": gross_loss,
        "total_cost_commission_swap": total_cost,
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": len(flats),
        "win_rate_pct": round(100 * len(wins) / n, 1),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": round(abs(avg_win / avg_loss), 2) if avg_loss else None,
        "profit_factor": round(abs(gross_win / gross_loss), 2) if gross_loss else None,
        "expectancy_per_trade": round((gross_win + gross_loss) / n, 2),
        "max_single_win": round(max((r["pnl"] for r in rows), default=0), 2),
        "max_single_loss": round(min((r["pnl"] for r in rows), default=0), 2),
        "max_consecutive_wins": max_streak(rows, "WIN"),
        "max_consecutive_losses": max_streak(rows, "LOSS"),
    }

    # 5 持仓时长（事实层，不解读）
    def dur_stats(sample):
        if not sample:
            return None
        secs = sorted(r["hold_sec"] for r in sample)
        return {
            "n": len(secs),
            "mean": fmt_dur(int(sum(secs) / len(secs))),
            "median": fmt_dur(int(median(secs))),
            "p10": fmt_dur(secs[int(0.1 * (len(secs) - 1))]),
            "p90": fmt_dur(secs[int(0.9 * (len(secs) - 1))]),
            "mean_sec": int(sum(secs) / len(secs)),
            "median_sec": int(median(secs)),
        }
    out["5_holding"] = {
        "all": dur_stats(rows),
        "wins": dur_stats(wins),
        "losses": dur_stats(losses),
        "under_5min_pct": round(100 * sum(1 for r in rows if r["hold_sec"] < 300) / n, 1),
        "over_4h_pct": round(100 * sum(1 for r in rows if r["hold_sec"] > 14400) / n, 1),
    }

    # 6 方向分布
    by_dir = defaultdict(lambda: {"n": 0, "pnl": 0.0, "win": 0})
    for r in rows:
        d = by_dir[r["direction"] or "UNKNOWN"]
        d["n"] += 1
        d["pnl"] = round(d["pnl"] + r["pnl"], 2)
        if r["result"] == "WIN":
            d["win"] += 1
    out["6_direction"] = [{"direction": k, "n": v["n"], "net_pnl": v["pnl"],
                           "win_rate_pct": round(100 * v["win"] / v["n"], 1)}
                          for k, v in sorted(by_dir.items())]

    # 7 数据质量警告
    warn = []
    if len(excluded):
        warn.append(f"剔除 {len(excluded)} 行非交易记录（balance/入金，position_id=0）")
    if flats:
        warn.append(f"{len(flats)} 笔净利恰为 0，已单列为 FLAT，未计入胜率分子")
    if out["1_scale"]["span_days"] < 180:
        warn.append(f"样本跨度仅 {out['1_scale']['span_days']} 天，不足半年，"
                    f"未覆盖完整市场环境，DNA 门槛（趋势+震荡）不满足")
    top = out["2_symbols"][0]
    if top["share_pct"] >= 50:
        warn.append(f"{top['symbol']} 占 {top['share_pct']}%，样本高度集中，"
                    f"任何结论实为「{top['symbol']} 交易特征」而非通用交易 DNA")
    if n < 100:
        warn.append(f"仅 {n} 笔，低于 DNA 门槛 100 笔，禁止生成 Trading DNA")
    out["7_warnings"] = warn
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    a = ap.parse_args()
    path = os.path.abspath(a.file)
    if not os.path.exists(path):
        raise SystemExit(f"找不到文件: {path}")
    rows, excluded = load_trades(path)
    res = audit(rows, excluded)
    txt = json.dumps(res, ensure_ascii=False, indent=2)
    print(txt)
    if not a.json:
        outp = os.path.join(os.path.dirname(path), "b05_audit.json")
        with open(outp, "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"\n已写入 {outp}")


if __name__ == "__main__":
    main()
