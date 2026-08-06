"""
Regime History Validation Layer — Phase 1.7
记录每日 Regime 状态 + 资产状态，并回溯未来收益，验证系统「判环境」能力是否长期有效。

这是 Phase 2 Asset Regime Engine（六状态模型）的训练基础。
当前样本约 250 交易日（commodity_factor_daily 窗口），远未达 5 年，
但足以建立「状态 → 未来收益分布」的闭环，随数据积累自动增厚。

表 regime_history：
    date              PK
    risk_state        粗判 Risk On / Neutral / Risk Off
    risk_score        0~100
    risk_drivers      JSON [DXY=.., US10Y=.., BTC=..]
    a_share_emotion   market_daily.emotion_score
    a_share_stage     market_daily.stage
    a_share_ret       全市场均值涨跌%（A股收益代理）
    commodity_states  JSON {AU0:stage, CU0:stage, SC0:stage}
    gold_ret          AU0 当日涨跌%
    fwd_1d_a_share / fwd_5d_a_share / fwd_20d_a_share
    fwd_1d_gold / fwd_5d_gold / fwd_20d_gold
    fwd_20d_max_dd_gold
    generated_at

边界：只记录与回溯，不预测、不给配置比例。Risk State 是温度计不是信号。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

from db import get_conn

# 复用 snapshot 的阈值与粗判逻辑（单一事实源）
from commodity_engine.snapshot import _REGIME_THRESHOLDS, _score_macro_item


# ── 数据加载 ──────────────────────────────────────────────────
def _date_clause(date_from: str = None, date_to: str = None):
    """返回 (where_clause, and_clause, params)。
    where_clause 用于无前置 WHERE 的表；and_clause 用于已有 WHERE 的表。"""
    if date_from and date_to:
        return ("WHERE date >= ? AND date <= ?", "AND date >= ? AND date <= ?", (date_from, date_to))
    if date_from:
        return ("WHERE date >= ?", "AND date >= ?", (date_from,))
    if date_to:
        return ("WHERE date <= ?", "AND date <= ?", (date_to,))
    return ("", "", ())


def _shift(d: str, days: int) -> str:
    """YYYY-MM-DD ± N 天。"""
    return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _load_series(date_from: str = None, date_to: str = None) -> dict:
    """加载回溯所需序列（按日期窗口，增量/单日模式下只加载目标日附近，避免全表扫描）。"""
    conn = get_conn()
    cur = conn.cursor()
    data: dict[str, Any] = {}
    w, a, dp = _date_clause(date_from, date_to)

    # 1) 宏观：global_history 的 DXY / US10Y / BTC（date -> close）
    macro = {"DXY": {}, "US10Y": {}, "BTC": {}}
    for sym in macro:
        cur.execute(
            f"SELECT date, close FROM global_history WHERE symbol=? {a} ORDER BY date", (sym,) + dp)
        for d, v in cur.fetchall():
            macro[sym][d] = v
    data["macro"] = macro

    # 2) 黄金：commodity_daily AU0（date -> (close, change_pct)）
    gold = {}
    cur.execute(
        f"SELECT date, close, change_pct FROM commodity_daily WHERE symbol='AU0' {a} ORDER BY date", dp)
    for d, c, cp in cur.fetchall():
        gold[d] = (c, cp)
    data["gold"] = gold

    # 3) A股代理：stock_daily 每日全市场均值涨跌%（date -> mean change_pct）
    ashare = {}
    cur.execute(
        f"SELECT date, AVG(change_pct) FROM stock_daily {w} GROUP BY date ORDER BY date", dp)
    for d, m in cur.fetchall():
        if m is not None:
            ashare[d] = m
    data["ashare"] = ashare

    # 3b) A股交易日集合（去重 date，含 change_pct 为空的交易日；用于决定 regime 覆盖，
    #     不依赖 commodity_factor_daily，也不因 change_pct 为空而漏日）
    astock = set()
    cur.execute(f"SELECT DISTINCT date FROM stock_daily {w} ORDER BY date", dp)
    for (d,) in cur.fetchall():
        astock.add(d)
    data["astock"] = astock

    # 4) A股状态：market_daily（date -> (emotion_score, stage)）
    astate = {}
    try:
        cur.execute(
            f"SELECT date, emotion_score, stage FROM market_daily WHERE emotion_score IS NOT NULL {a} ORDER BY date", dp)
        for d, e, s in cur.fetchall():
            astate[d] = (e, s)
    except Exception:
        pass
    data["astate"] = astate

    # 5) 商品因子：commodity_factor_daily（date -> {symbol: (score, stage)}）
    cfac = {}
    cur.execute(
        f"SELECT date, symbol, total_score, stage FROM commodity_factor_daily {w} ORDER BY date", dp)
    for d, sym, sc, st in cur.fetchall():
        cfac.setdefault(d, {})[sym] = (sc, st)
    data["cfac"] = cfac

    conn.close()
    return data


def _nearest(d: str, series: dict) -> Optional[float]:
    """取 series 中 <= d 的最近值（宏观数据可能跳日）。"""
    if d in series:
        return series[d]
    # 线性扫描（已排序）
    best = None
    for k in series:
        if k <= d:
            best = series[k]
        else:
            break
    return best


# ── 单日 Regime 计算 ───────────────────────────────────────────
def _risk_state_at(date: str, macro: dict) -> dict:
    """基于某日宏观值粗判 risk_state（复用 snapshot 的阈值逻辑）。"""
    dxy = _nearest(date, macro["DXY"])
    us10y = _nearest(date, macro["US10Y"])
    btc = _nearest(date, macro["BTC"])

    items = []
    drivers = []
    for key, val in [("DXY", dxy), ("US10Y", us10y), ("BTC", btc)]:
        if val is None:
            continue
        items.append(_score_macro_item(key, val))
        drivers.append(f"{key}={val:.2f}" if key != "BTC" else f"{key}={val:.0f}")

    avg = sum(items) / len(items) if items else 50.0
    if avg >= _REGIME_THRESHOLDS["Risk On"]:
        label = "Risk On"
    elif avg >= _REGIME_THRESHOLDS["Neutral"]:
        label = "Neutral"
    else:
        label = "Risk Off"
    return {"label": label, "score": round(avg, 1), "drivers": drivers}


# ── 建表 ──────────────────────────────────────────────────────
def ensure_schema() -> None:
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regime_history (
            date              TEXT PRIMARY KEY,
            risk_state        TEXT,
            risk_score        REAL,
            risk_drivers      TEXT,
            a_share_emotion   REAL,
            a_share_stage     TEXT,
            a_share_ret       REAL,
            commodity_states  TEXT,
            gold_ret          REAL,
            fwd_1d_a_share    REAL,
            fwd_5d_a_share    REAL,
            fwd_20d_a_share   REAL,
            fwd_1d_gold       REAL,
            fwd_5d_gold       REAL,
            fwd_20d_gold      REAL,
            fwd_20d_max_dd_gold REAL,
            generated_at      TEXT
        )
    """)
    conn.commit()
    conn.close()


# ── 回溯构建 ──────────────────────────────────────────────────
def build_regime_history(full: bool = False, target_date: str = None,
                         incremental: bool = True) -> dict:
    """逐日回溯 regime_history（含远期收益）。幂等 upsert。

    覆盖范围已**解耦 commodity_factor_daily**：
    - 以「A股交易日(stock_daily) ∩ 有 DXY 宏观值的日期」为准，向下延伸到最新交易日。
    - commodity_factor_daily 仅贡献 commodity_states(AU0/CU0/SC0 stage)，缺则留空 dict，
      不再因商品因子采集滞后而漏掉整日 regime（这是原全量脚本的坑）。

    运行模式（向后兼容，无参=增量补缺失）：
    - 增量（默认）：仅加载最新日附近窗口 + 补 regime_history 缺失的交易日 → 秒级。
    - full=True：从 commodity_factor_daily 起点到最新+21天全量重算（数据大补后刷新旧行用）。
    - target_date='YYYY-MM-DD'：只算单日。
    """
    ensure_schema()
    conn = get_conn()
    cur = conn.cursor()

    # 最新 A股交易日（单次聚合，快）
    latest = cur.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    if not latest:
        conn.close()
        return {"built": 0, "samples": 0}

    # 加载窗口：避免全表扫描（原全量慢的根因）
    if target_date:
        lo, hi = _shift(target_date, -60), _shift(target_date, 21)
    elif full:
        # 全量：commodity_factor_daily 起点 → 最新+21（窗口本身已限定范围，不爆炸到全历史）
        row = cur.execute("SELECT MIN(date) FROM commodity_factor_daily").fetchone()[0]
        lo = row if row else _shift(latest, -400)
        hi = _shift(latest, 21)
    else:
        # 增量：只加载最近 ~90 天窗口（每日只补最新缺失日，秒级）
        lo, hi = _shift(latest, -70), _shift(latest, 21)

    data = _load_series(lo, hi)
    gold = data["gold"]
    ashare = data["ashare"]
    astock = data["astock"]
    cfac = data["cfac"]
    macro = data["macro"]

    # 目标日期集合（窗口内）：A股交易日（stock_daily 去重）∩ 有 DXY 宏观值
    # 用 astock 而非 ashare：change_pct 为空的交易日仍计入（a_ret 允许 NULL，与原逻辑一致）
    base = sorted(astock & set(macro["DXY"].keys()))
    if not base:
        conn.close()
        return {"built": 0, "samples": 0}

    if target_date:
        target_dates = [d for d in base if d == target_date]
    elif not full:
        # 增量：排除窗口内已存在日期
        cur.execute("SELECT date FROM regime_history WHERE date >= ? AND date <= ?", (lo, hi))
        existing = set(r[0] for r in cur.fetchall())
        target_dates = [d for d in base if d not in existing]
    else:
        target_dates = base  # 全量：窗口内全部重算

    if not target_dates:
        conn.close()
        return {"built": 0, "samples": 0}

    # 预建索引字典，远期收益定位 O(1)（替代原 .index() 的 O(n) 扫描）
    gold_dates = sorted(gold.keys())
    ashare_dates = sorted(ashare.keys())
    gold_idx = {d: i for i, d in enumerate(gold_dates)}
    ashare_idx = {d: i for i, d in enumerate(ashare_dates)}

    built = 0
    for d in target_dates:
        rs = _risk_state_at(d, macro)
        # commodity_states 仅作可选增强：缺 commodity_factor_daily 当日则留空（解耦核心）
        cf = cfac.get(d, {})
        comm_states = {s: cf[s][1] for s in ("AU0", "CU0", "SC0") if s in cf}

        # A股状态 + 当日收益代理
        a_state = data["astate"].get(d)
        a_emotion = a_state[0] if a_state else None
        a_stage = a_state[1] if a_state else None
        a_ret = ashare.get(d)

        # 黄金当日收益
        gold_pt = gold.get(d)
        gold_ret = gold_pt[1] if gold_pt else None

        # ── 远期收益 ──
        fwd = {k: None for k in (
            "fwd_1d_a_share", "fwd_5d_a_share", "fwd_20d_a_share",
            "fwd_1d_gold", "fwd_5d_gold", "fwd_20d_gold", "fwd_20d_max_dd_gold")}
        gi = gold_idx.get(d)
        if gi is not None:
            c0 = gold[d][0]
            if gi + 1 < len(gold_dates):
                c1 = gold[gold_dates[gi + 1]][0]
                fwd["fwd_1d_gold"] = round((c1 / c0 - 1) * 100, 2)
            if gi + 5 < len(gold_dates):
                c5 = gold[gold_dates[gi + 5]][0]
                fwd["fwd_5d_gold"] = round((c5 / c0 - 1) * 100, 2)
            if gi + 20 < len(gold_dates):
                c20 = gold[gold_dates[gi + 20]][0]
                fwd["fwd_20d_gold"] = round((c20 / c0 - 1) * 100, 2)
                # 20日最大回撤（黄金）
                closes = [gold[gold_dates[j]][0] for j in range(gi, min(gi + 21, len(gold_dates)))]
                peak = max(closes)
                dd = min((c / peak - 1) for c in closes)
                fwd["fwd_20d_max_dd_gold"] = round(dd * 100, 2)

        # A股（收益序列）：累计 N 日乘积
        ai = ashare_idx.get(d)
        if ai is not None:
            for n, key in [(1, "fwd_1d_a_share"), (5, "fwd_5d_a_share"), (20, "fwd_20d_a_share")]:
                if ai + n < len(ashare_dates):
                    prod = 1.0
                    for j in range(ai + 1, ai + n + 1):
                        r = ashare[ashare_dates[j]]
                        if r is not None:
                            prod *= (1 + r / 100.0)
                    fwd[key] = round((prod - 1) * 100, 2)

        cur.execute("""
            INSERT OR REPLACE INTO regime_history
            (date, risk_state, risk_score, risk_drivers, a_share_emotion, a_share_stage,
             a_share_ret, commodity_states, gold_ret,
             fwd_1d_a_share, fwd_5d_a_share, fwd_20d_a_share,
             fwd_1d_gold, fwd_5d_gold, fwd_20d_gold, fwd_20d_max_dd_gold, generated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            d, rs["label"], rs["score"], json.dumps(rs["drivers"], ensure_ascii=False),
            a_emotion, a_stage, a_ret,
            json.dumps(comm_states, ensure_ascii=False), gold_ret,
            fwd["fwd_1d_a_share"], fwd["fwd_5d_a_share"], fwd["fwd_20d_a_share"],
            fwd["fwd_1d_gold"], fwd["fwd_5d_gold"], fwd["fwd_20d_gold"],
            fwd["fwd_20d_max_dd_gold"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        built += 1

    conn.commit()
    conn.close()
    return {"built": built, "samples": len(target_dates)}


# ── 验证查询 ──────────────────────────────────────────────────
def validate_regime(state: Optional[str] = None) -> list[dict]:
    """按 risk_state 分组，返回远期收益统计。state=None 返回全部状态。"""
    conn = get_conn()
    cur = conn.cursor()
    where = "WHERE risk_state=?" if state else ""
    params = (state,) if state else ()
    cur.execute(
        f"SELECT risk_state, COUNT(*), "
        f"AVG(fwd_1d_a_share), AVG(fwd_5d_a_share), AVG(fwd_20d_a_share), "
        f"AVG(fwd_1d_gold), AVG(fwd_5d_gold), AVG(fwd_20d_gold) "
        f"FROM regime_history {where} GROUP BY risk_state ORDER BY risk_state",
        params)
    rows = []
    for r in cur.fetchall():
        rows.append({
            "risk_state": r[0], "n": r[1],
            "a_share_1d": round(r[2], 2) if r[2] is not None else None,
            "a_share_5d": round(r[3], 2) if r[3] is not None else None,
            "a_share_20d": round(r[4], 2) if r[4] is not None else None,
            "gold_1d": round(r[5], 2) if r[5] is not None else None,
            "gold_5d": round(r[6], 2) if r[6] is not None else None,
            "gold_20d": round(r[7], 2) if r[7] is not None else None,
        })
    conn.close()
    return rows


def format_regime_report(state: Optional[str] = None) -> str:
    """人类可读的 Regime 验证报告。"""
    rows = validate_regime(state)
    if not rows:
        return "regime_history 为空，请先运行 build_regime_history()"
    lines = ["Regime 历史验证报告", "=" * 40]
    for r in rows:
        lines.append(f"\n[{r['risk_state']}]  样本 n={r['n']}")
        lines.append(f"  A股   1D:{r['a_share_1d']}  5D:{r['a_share_5d']}  20D:{r['a_share_20d']}")
        lines.append(f"  黄金  1D:{r['gold_1d']}  5D:{r['gold_5d']}  20D:{r['gold_20d']}")
    lines.append("")
    lines.append("说明：以上为「该环境下未来 N 日平均收益%」，仅供验证系统判环境能力，")
    lines.append("不构成买卖建议。样本随数据积累增厚；当前约 250 交易日，未达 5 年回测要求。")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="回溯构建 regime_history（增量/全量/单日）")
    ap.add_argument("--full", action="store_true", help="全量重算（默认增量补缺失）")
    ap.add_argument("--date", type=str, default=None, help="只算单日 YYYY-MM-DD")
    ap.add_argument("--incremental", action="store_true",
                    help="显式指定增量（默认即增量，无参等价）")
    args = ap.parse_args()
    res = build_regime_history(full=args.full, target_date=args.date)
    print(f"regime_history built: {res}")
    print()
    print(format_regime_report())
