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
from datetime import datetime
from typing import Any, Optional

from db import get_conn

# 复用 snapshot 的阈值与粗判逻辑（单一事实源）
from commodity_engine.snapshot import _REGIME_THRESHOLDS, _score_macro_item


# ── 数据加载 ──────────────────────────────────────────────────
def _load_series() -> dict:
    """一次性加载回溯所需的全部序列，返回字典供快速查询。"""
    conn = get_conn()
    cur = conn.cursor()
    data: dict[str, Any] = {}

    # 1) 宏观：global_history 的 DXY / US10Y / BTC（date -> close）
    macro = {"DXY": {}, "US10Y": {}, "BTC": {}}
    for sym in macro:
        cur.execute(
            "SELECT date, close FROM global_history WHERE symbol=? ORDER BY date", (sym,))
        for d, v in cur.fetchall():
            macro[sym][d] = v
    data["macro"] = macro

    # 2) 黄金：commodity_daily AU0（date -> (close, change_pct)）
    gold = {}
    cur.execute(
        "SELECT date, close, change_pct FROM commodity_daily WHERE symbol='AU0' ORDER BY date")
    for d, c, cp in cur.fetchall():
        gold[d] = (c, cp)
    data["gold"] = gold

    # 3) A股代理：stock_daily 每日全市场均值涨跌%（date -> mean change_pct）
    ashare = {}
    cur.execute("SELECT date, AVG(change_pct) FROM stock_daily GROUP BY date ORDER BY date")
    for d, m in cur.fetchall():
        if m is not None:
            ashare[d] = m
    data["ashare"] = ashare

    # 4) A股状态：market_daily（date -> (emotion_score, stage)）
    astate = {}
    try:
        cur.execute(
            "SELECT date, emotion_score, stage FROM market_daily WHERE emotion_score IS NOT NULL ORDER BY date")
        for d, e, s in cur.fetchall():
            astate[d] = (e, s)
    except Exception:
        pass
    data["astate"] = astate

    # 5) 商品因子：commodity_factor_daily（date -> {symbol: (score, stage)}）
    cfac = {}
    cur.execute(
        "SELECT date, symbol, total_score, stage FROM commodity_factor_daily ORDER BY date")
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
def build_regime_history() -> dict:
    """逐日回溯 regime_history（含远期收益）。幂等 upsert。"""
    ensure_schema()
    data = _load_series()
    gold = data["gold"]
    ashare = data["ashare"]

    # 观测窗口：有商品因子 + 有宏观的交易日
    obs_dates = sorted(set(data["cfac"].keys()) & set(data["macro"]["DXY"].keys()))
    if not obs_dates:
        return {"built": 0, "samples": 0}

    # 黄金有序日期表（用于远期收益定位）
    gold_dates = sorted(gold.keys())
    ashare_dates = sorted(ashare.keys())

    conn = get_conn()
    cur = conn.cursor()
    built = 0

    for i, d in enumerate(obs_dates):
        rs = _risk_state_at(d, data["macro"])
        cf = data["cfac"].get(d, {})
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
        # 黄金（价格序列）：定位 d 在 gold_dates 的索引
        fwd = {k: None for k in (
            "fwd_1d_a_share", "fwd_5d_a_share", "fwd_20d_a_share",
            "fwd_1d_gold", "fwd_5d_gold", "fwd_20d_gold", "fwd_20d_max_dd_gold")}
        try:
            gi = gold_dates.index(d)
            if gi + 1 < len(gold_dates):
                c0 = gold[d][0]
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
        except (ValueError, KeyError, ZeroDivisionError):
            pass

        # A股（收益序列）：累计 N 日乘积
        try:
            ai = ashare_dates.index(d)
            for n, key in [(1, "fwd_1d_a_share"), (5, "fwd_5d_a_share"), (20, "fwd_20d_a_share")]:
                if ai + n < len(ashare_dates):
                    prod = 1.0
                    for j in range(ai + 1, ai + n + 1):
                        r = ashare[ashare_dates[j]]
                        if r is not None:
                            prod *= (1 + r / 100.0)
                    fwd[key] = round((prod - 1) * 100, 2)
        except ValueError:
            pass

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
    return {"built": built, "samples": len(obs_dates)}


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
    res = build_regime_history()
    print(f"regime_history built: {res}")
    print()
    print(format_regime_report())
