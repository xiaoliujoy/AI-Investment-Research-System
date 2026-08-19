# -*- coding: utf-8 -*-
"""
ust_yield_observer.py — 美债收益率观察模块（外围黑天鹅 · 纯观察层）

事件背景（2026-08-19 加入）：
  30 年期美债收益率突破 5.3%（8/17 官方收盘 5.31%），创 2007 年 6 月以来新高。
  逻辑链：30Y 是"无风险利率"锚 → 抬升全球贴现率 → 压制长久期/高估值成长股；
          同时抬高居民房贷（~6.7%）、巨头企业贷（~6.5%）、中小企业融资（~12%）成本，
          等效于一次加息。详见 docs/ust_yield_blackswan_202608.md（若生成）。

定位（铁律，与 Phase 1E FROZEN 一致）：
  - 只读 / 观测层。零生产决策改动（不碰 run_daily / risk_guard / shadow / CIO /
    os2_report / flow_report.json / 任何生产表）。
  - 数据源 = 美国财政部官网 daily_treasury_yield_curve（一手来源，国内可达），
    每日官方收盘收益率曲线，非实时盘中。
  - 只落盘到 output/archive/ust_yield_snapshots/，供决策 Provenance 与后续
    m1_global（全球流动性）证据链参考。

输出：
  output/archive/ust_yield_snapshots/ust_yield_snapshot_YYYY-MM-DD.json  每日快照
  output/archive/ust_yield_snapshots/ust_yield_manifest.jsonl           每次运行追加一行

用法：
  python ust_yield_observer.py                      # 自动拉取财政部数据（今日快照）
  python ust_yield_observer.py --date 2026-08-18    # 指定计算日期
  python ust_yield_observer.py --manual 5.28 --manual-10y 4.71   # 离线兜底：手动录入当日 30Y/10Y

状态标记（研究阈值，非交易信号）：
  BLACK_SWAN  30Y > 5.30   创 2007-06 以来新高区（本次事件区）
  ALERT       5.00 < 30Y ≤ 5.30   历史高位区（2023-10 曾触 5.0+）
  ELEVATED    4.50 < 30Y ≤ 5.00   偏高区
  NORMAL      30Y ≤ 4.50
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.request
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent           # backend/os_layers
BACKEND = HERE.parent
OUTPUT = BACKEND / "output"
ARCHIVE_DIR = OUTPUT / "archive" / "ust_yield_snapshots"
MANIFEST = ARCHIVE_DIR / "ust_yield_manifest.jsonl"

SCHEMA_VERSION = "1.0"
SNAPSHOT_TYPE = "ust_yield_observer"

# ── 美国财政部官方每日收益率曲线（一手来源）──────────────────────────────
# 按年一个 XML（OData ATOM），跨年时自动补拉上一年
TREASURY_URL_TMPL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
}

# ── 研究阈值（非信号）：30Y 状态带 ──────────────────────────────────────
BLACK_SWAN = 5.30   # 创 2007-06 以来新高区
ALERT = 5.00        # 历史高位区
ELEVATED = 4.50     # 偏高区

# 观察的核心期限
KEY_TENORS = ["BC_1MONTH", "BC_3MONTH", "BC_6MONTH", "BC_1YEAR", "BC_2YEAR",
              "BC_3YEAR", "BC_5YEAR", "BC_7YEAR", "BC_10YEAR", "BC_20YEAR", "BC_30YEAR"]
TENOR_LABEL = {
    "BC_1MONTH": "1M", "BC_3MONTH": "3M", "BC_6MONTH": "6M", "BC_1YEAR": "1Y",
    "BC_2YEAR": "2Y", "BC_3YEAR": "3Y", "BC_5YEAR": "5Y", "BC_7YEAR": "7Y",
    "BC_10YEAR": "10Y", "BC_20YEAR": "20Y", "BC_30YEAR": "30Y",
}


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def fetch_treasury_curves(years: list[int]) -> list[dict]:
    """拉取若干年的收益率曲线，返回 [{date, tenors:{...}}]，按日期升序。"""
    rows: dict[str, dict] = {}
    for year in years:
        url = TREASURY_URL_TMPL.format(year=year)
        with urllib.request.urlopen(url, timeout=25) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        for entry in root.findall("a:entry", NS):
            props = entry.find("a:content/m:properties", NS)
            if props is None:
                continue
            d = {}
            for c in props:
                tag = c.tag.split("}")[1]
                d[tag] = (c.text or "").strip()
            date_s = d.get("NEW_DATE", "")
            if not date_s:
                continue
            rows[date_s[:10]] = {
                "date": date_s[:10],
                "tenors": {t: (float(d[t]) if d.get(t) not in (None, "") else None)
                           for t in KEY_TENORS},
            }
    return [rows[k] for k in sorted(rows)]


def derive_30y_state(y30: float) -> str:
    """30Y 状态带（研究阈值，非信号）。"""
    if y30 > BLACK_SWAN:
        return "BLACK_SWAN"
    if y30 > ALERT:
        return "ALERT"
    if y30 > ELEVATED:
        return "ELEVATED"
    return "NORMAL"


def build_snapshot(today: str, curves: list[dict], manual: dict | None,
                   prev_path: pathlib.Path | None) -> dict:
    """构建快照。异常向上抛，由 main 捕获写 FAILED 留证。"""
    if manual:
        y30 = float(manual.get("y30") or 0)
        y10 = float(manual.get("y10") or 0)
        latest = {
            "date": today, "tenors": {"BC_30YEAR": y30, "BC_10YEAR": y10},
            "manual": True,
        }
    else:
        latest = curves[-1]
        latest["manual"] = False

    tenors = latest["tenors"]
    y30 = tenors.get("BC_30YEAR")
    y10 = tenors.get("BC_10YEAR")
    y20 = tenors.get("BC_20YEAR")
    y2 = tenors.get("BC_2YEAR")

    # 上一快照（趋势对比）
    prev = None
    if prev_path and prev_path.exists():
        try:
            prev = json.load(open(prev_path, encoding="utf-8"))
        except Exception:
            prev = None
    prev_y30 = None
    if prev and prev.get("status") == "OK":
        prev_y30 = prev.get("curve", {}).get("y30")

    # 年内 30Y 序列（官方数据年内全部交易日）用于分位
    y30_series = [r["tenors"].get("BC_30YEAR") for r in curves if r["tenors"].get("BC_30YEAR") is not None]
    y30_high = max(y30_series) if y30_series else None
    y30_low = min(y30_series) if y30_series else None
    y30_pct = None
    if y30 is not None and y30_series:
        y30_pct = round(sum(1 for v in y30_series if v <= y30) / len(y30_series) * 100, 1)

    curve = {
        "date": latest["date"],
        "manual": latest["manual"],
        "source": "US Treasury Daily Yield Curve (official)" if not latest["manual"] else "manual entry",
        "y30": y30,
        "y20": y20,
        "y10": y10,
        "y2": y2,
        "spread_30y_10y": round(y30 - y10, 3) if (y30 is not None and y10 is not None) else None,
        "full_curve": {TENOR_LABEL[k]: v for k, v in tenors.items() if v is not None},
    }

    change_bp = None
    if y30 is not None and prev_y30 is not None:
        change_bp = round((y30 - prev_y30) * 100, 1)

    state = derive_30y_state(y30) if y30 is not None else "NO_DATA"

    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_type": SNAPSHOT_TYPE,
        "status": "OK",
        "computation_date": today,
        "generated_at": _now_iso(),
        "curve": curve,
        "change_from_prev_snapshot_bp": change_bp,
        "state": state,
        "state_note": (
            "30Y 突破 5.30%（2007-06 以来新高区），无风险利率锚抬高 → 等效加息，"
            "压制长久期/高估值资产，抬高全球融资成本。研究阈值非交易信号。"
            if state == "BLACK_SWAN" else
            "30Y 处于历史高位警戒区（5.00~5.30）。研究阈值非交易信号。"
            if state == "ALERT" else
            "30Y 处于偏高区（4.50~5.00）。研究阈值非交易信号。"
            if state == "ELEVATED" else
            "30Y 处于常态区（≤4.50）。研究阈值非交易信号。"
        ),
        "y30_year_band": {"high": y30_high, "low": y30_low, "pct_in_year": y30_pct},
        "thresholds": {"BLACK_SWAN_GT": BLACK_SWAN, "ALERT_GT": ALERT, "ELEVATED_GT": ELEVATED},
        "provenance": {
            "source": "US Department of the Treasury - Daily Treasury Yield Curve (XML)",
            "url": TREASURY_URL_TMPL.format(year=dt.date.today().year),
            "is_official_close": not latest["manual"],
            "note": "官方每日收盘收益率，非实时盘中；8/17=5.31%（2007-06 以来新高），8/18 收 5.28%，盘中最高 5.335%。",
        },
        "audit_notes": (
            "纯观察层快照：记录 30Y 美债收益率锚的状态，供 m1_global（全球流动性）证据链参考；"
            "不进入任何生产评分/决策。pre-2026-08-19 无逐日序列，无法考古重建，本文件为序列起点。"
        ),
    }


def write_failed_snapshot(today: str, stage: str, error: Exception) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_type": SNAPSHOT_TYPE,
        "status": "FAILED",
        "computation_date": today,
        "generated_at": _now_iso(),
        "failure_stage": stage,
        "error": str(error)[:500],
        "note": "失败也必须留下证据：缺失证据本身也是证据。",
    }
    out_path = ARCHIVE_DIR / f"ust_yield_snapshot_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    _append_manifest(today, "FAILED", str(out_path))
    print(f"[UST Yield Observer] FAILED 已写入(留证): {out_path}")
    print(f"  failure_stage = {stage}")
    print(f"  error         = {snap['error']}")


def _append_manifest(today: str, status: str, path: str) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(MANIFEST, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "date": today, "status": status, "path": path, "ts": _now_iso(),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="美债收益率观察（纯观察层，零生产改动）")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="计算日期（默认今日）")
    ap.add_argument("--manual", type=float, default=None, metavar="Y30", help="离线兜底：手动录入 30Y 收益率（%）")
    ap.add_argument("--manual-10y", type=float, default=None, metavar="Y10", help="离线兜底：手动录入 10Y 收益率（%）")
    args = ap.parse_args()

    today = args.date
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    manual = None
    if args.manual is not None:
        manual = {"y30": args.manual, "y10": args.manual_10y}

    try:
        if manual:
            curves: list[dict] = []
        else:
            this_year = dt.date.today().year
            curves = fetch_treasury_curves([this_year, this_year - 1])
            if not curves:
                raise RuntimeError("财政部数据为空（网络失败或 XML 结构变化）")
        prev_path = ARCHIVE_DIR / f"ust_yield_snapshot_{today}.json"
        snapshot = build_snapshot(today, curves, manual, prev_path)
    except Exception as e:
        write_failed_snapshot(today, "build_snapshot", e)
        return 1

    out_path = ARCHIVE_DIR / f"ust_yield_snapshot_{today}.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        write_failed_snapshot(today, "write", e)
        return 1

    c = snapshot["curve"]
    print(f"[UST Yield Observer] 已写入: {out_path}")
    print(f"  计算日期      : {today}")
    print(f"  数据日期      : {c['date']}  来源: {c['source']}")
    print(f"  30Y           : {c['y30']}%  (20Y={c['y20']}%  10Y={c['y10']}%  2Y={c['y2']}%)")
    print(f"  30Y-10Y 期限溢价: {c['spread_30y_10y']}")
    print(f"  较上一快照    : {snapshot['change_from_prev_snapshot_bp']} bp")
    print(f"  状态          : {snapshot['state']}")
    print(f"  年内 30Y 区间 : 高 {snapshot['y30_year_band']['high']} / 低 {snapshot['y30_year_band']['low']} / 年内分位 {snapshot['y30_year_band']['pct_in_year']}%")
    _append_manifest(today, "OK", str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
