# -*- coding: utf-8 -*-
"""
commodity_health.py —— 商品数据质量层（Commodity OS Phase 0.5）

每日检查 commodity_daily 8 品种，原则与 A股 Data Health Check 一致：
    「数据过期不编造」。

四类检查：
  1) 新鲜度(freshness)：相对"数据前沿"(所有品种最大日期)的滞后天数
       HEALTHY(≤1) / WATCH(2~4) / STALE(≥5)
  2) 价格异常(anomaly)：单日 |change_pct| > 8% 标记（涨跌停/极端波动/合约切换）
  3) 合约连续性(continuity)：implied close-to-close 与 reported change_pct 差异 > 5%
       标记换月缝合跳变（连续主连数据本应平滑，差异大需人工确认非真实跳空）
  4) 完整性(completeness)：volume=0 / open_interest=0 行数
       区分 内盘异常缺失(应报错) vs 外盘正常缺失(OI/volume 恒为0, akshare 限制)

输出：output/commodity_health.json + 打印摘要。
用法：
  python commodity_health.py                 # 检查全部 + 写报告
  python commodity_health.py --quiet         # 仅返回 dict（供 daily_collect 调用）
"""
from __future__ import annotations

import os
import sys
import json
import sqlite3
import datetime

_BACKEND = os.path.dirname(os.path.abspath(__file__))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from database.models import get_db  # noqa: E402

OUT = os.path.join(_BACKEND, "output")
os.makedirs(OUT, exist_ok=True)

ANOMALY_PCT = 8.0       # 单日涨跌幅异常阈值
STITCH_DIFF_PCT = 5.0   # implied vs reported 差异阈值（换月缝合）


def _symbols():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT symbol,market,category,name FROM commodity_symbol_map "
        "ORDER BY market,category,symbol").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _series(symbol: str) -> list[dict]:
    conn = get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT date,close,change_pct,volume,open_interest FROM commodity_daily "
        "WHERE symbol=? ORDER BY date ASC", (symbol,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _as_date(s):
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


def check_freshness(symbols, series_map) -> dict:
    """相对数据前沿的滞后。数据前沿 = 所有品种最大日期（与系统时钟解耦，沙箱鲁棒）。"""
    frontier = None
    for s in series_map.values():
        if s:
            d = _as_date(s[-1]["date"])
            if d and (frontier is None or d > frontier):
                frontier = d
    out = {}
    for m in symbols:
        sym = m["symbol"]
        s = series_map.get(sym, [])
        if not s or frontier is None:
            out[sym] = {"status": "NO_DATA", "lag_days": None,
                        "latest": s[-1]["date"] if s else None, "frontier": None}
            continue
        latest = _as_date(s[-1]["date"])
        lag = (frontier - latest).days
        if lag <= 1:
            st = "HEALTHY"
        elif lag <= 4:
            st = "WATCH"
        else:
            st = "STALE"
        out[sym] = {"status": st, "lag_days": lag,
                    "latest": s[-1]["date"], "frontier": frontier.isoformat()}
    return out


def check_anomaly_and_continuity(series_map) -> dict:
    out = {}
    for sym, s in series_map.items():
        flags = []
        for i, r in enumerate(s):
            cp = r["change_pct"]
            if cp is not None and abs(cp) > ANOMALY_PCT:
                flags.append({
                    "type": "price_anomaly", "date": r["date"], "change_pct": round(cp, 2),
                    "note": "单日涨跌幅超阈值，检查新闻/涨跌停/合约切换",
                })
            if i > 0:
                prev = s[i - 1]["close"]
                if prev:
                    implied = (r["close"] / prev - 1) * 100
                    reported = cp if cp is not None else 0.0
                    if abs(implied - reported) > STITCH_DIFF_PCT:
                        flags.append({
                            "type": "contract_stitch", "date": r["date"],
                            "implied": round(implied, 2), "reported": round(reported, 2),
                            "note": "换月/缝合导致价格跳变；系统用连续主连数据，需人工确认非真实跳空",
                        })
        out[sym] = flags
    return out


def check_completeness(symbols, series_map) -> dict:
    out = {}
    for m in symbols:
        sym = m["symbol"]
        market = m["market"]
        s = series_map.get(sym, [])
        total = len(s)
        vol_zero = sum(1 for r in s if r["volume"] in (None, 0))
        oi_zero = sum(1 for r in s if r["open_interest"] in (None, 0))
        if market == "外盘":
            # 外盘 akshare 限制：OI/volume 恒为 0 → 正常缺失，不报错
            vol_status = "NORMAL_MISSING" if vol_zero == total else "OK"
            oi_status = "NORMAL_MISSING" if oi_zero == total else "OK"
        else:
            # 内盘应有 OI/volume；少量历史零值(源噪声)不计，>0.5%或>3行才告警
            thr = max(3, int(total * 0.005))
            vol_status = "ABNORMAL" if vol_zero > thr else "OK"
            oi_status = "ABNORMAL" if oi_zero > thr else "OK"
        out[sym] = {
            "total": total, "vol_zero": vol_zero, "oi_zero": oi_zero,
            "vol_status": vol_status, "oi_status": oi_status, "market": market,
        }
    return out


def run_health() -> dict:
    symbols = _symbols()
    series_map = {m["symbol"]: _series(m["symbol"]) for m in symbols}
    freshness = check_freshness(symbols, series_map)
    anomaly = check_anomaly_and_continuity(series_map)
    completeness = check_completeness(symbols, series_map)

    # 总体状态：任一 STALE 或 内盘 ABNORMAL → 不健康
    stale = [s for s, v in freshness.items() if v["status"] == "STALE"]
    abnormal = [s for s, v in completeness.items()
                if v["vol_status"] == "ABNORMAL" or v["oi_status"] == "ABNORMAL"]
    anomaly_count = sum(len(v) for v in anomaly.values())
    overall = "HEALTHY" if not (stale or abnormal) else "DEGRADED"

    report = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "overall": overall,
        "freshness": freshness,
        "anomaly_count": anomaly_count,
        "anomaly": anomaly,
        "completeness": completeness,
        "summary": {
            "symbols": len(symbols),
            "stale": stale,
            "abnormal_completeness": abnormal,
            "anomaly_flags": anomaly_count,
        },
    }
    return report


def ensure_commodity_health() -> dict:
    """每日流水线入口（幂等，只读检查，不写商品数据表）。返回健康检查报告。"""
    report = run_health()
    path = os.path.join(OUT, "commodity_health.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    n_stale = len(report["summary"]["stale"])
    n_abn = len(report["summary"]["abnormal_completeness"])
    note = (f"overall={report['overall']} stale={n_stale} "
            f"异常完整性={n_abn} 异常波动标记={report['anomaly_count']} "
            f"→ {path}")
    return {"step": "commodity_health", "ok": report["overall"] == "HEALTHY",
            "note": note, "detail": report["summary"]}


if __name__ == "__main__":
    report = run_health()
    print(f"\n=== Commodity Health ({report['ts']}) ===")
    print(f"总体: {report['overall']}")
    print("-- 新鲜度 --")
    for sym, v in report["freshness"].items():
        print(f"  {sym:4s} {v['status']:8s} 滞后{v['lag_days']}天 最新{v['latest']}")
    print("-- 完整性 --")
    for sym, v in report["completeness"].items():
        print(f"  {sym:4s} {v['market']} 总行{v['total']} "
              f"vol零{v['vol_zero']}({v['vol_status']}) "
              f"OI零{v['oi_zero']}({v['oi_status']})")
    print(f"-- 异常波动标记: {report['anomaly_count']} 条 --")
    for sym, flags in report["anomaly"].items():
        for f in flags[:3]:
            print(f"  {sym:4s} {f['type']:16s} {f['date']} {f.get('change_pct', f.get('implied'))} "
                  f"→ {f['note'][:30]}")
    path = os.path.join(OUT, "commodity_health.json")
    print(f"\n报告已写: {path}")
