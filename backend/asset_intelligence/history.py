# -*- coding: utf-8 -*-
"""
asset_intelligence/history.py —— 统一资产认知历史层（Phase 1.9-A）

每日把 build_universe_snapshot() 产出的跨资产宇宙快照落到 SQLite，
形成「资产认知时间序列」，供 Phase 1.9-B Regime Backtest Dashboard 使用。

设计原则（对齐 regime_history.py）：
  - 单一事实源：只 import db.get_conn()，不自行构造 sqlite3 连接
    （呼应 Phase 1.6 的 _DB_PATH 教训）。
  - 幂等 upsert：PK(date, symbol) → INSERT OR REPLACE。
  - 不污染 universe.py：universe.py 保持零外部依赖，本模块只做持久化。
  - score 缺失 → 存 NULL（不伪造 0）。
  - enabled 标志：承接 adapter 在 detail 中写入的 enabled（空壳 skeleton =
    False，详见 protocol.make_skeleton），让 Dashboard 能区分
    「真实评分资产」与「空壳占位（score=50 系占位、不参与真实排序）」——
    直接回应审计问题 #2（score:null 隐藏「无评分」）。
  - 与 regime_history 对齐：同用 trade_date 作为 canonical date；
    generated_at 用本地时间（与 regime_history 一致；UTC 问题已记入 AIP 文档 Backlog）。

表 asset_intelligence_history：
    date          PK 交易日（与 regime_history.date 同口径）
    asset_class   TEXT
    symbol        PK 标的
    name          TEXT
    score         REAL（NULL 允许）
    state         TEXT
    trend         TEXT
    confidence    REAL
    enabled       INTEGER 1=真实评分参与排序 / 0=空壳未启用（详见 detail.enabled）
    drivers_json  TEXT
    risks_json    TEXT
    generated_at  TEXT

边界：只记录、不预测、不给配置比例。本层是 Dashboard 的训练基础，不是信号。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from db import get_conn


# ── 建表 ──────────────────────────────────────────────────────
def ensure_schema() -> None:
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS asset_intelligence_history (
            date          TEXT NOT NULL,
            asset_class   TEXT,
            symbol        TEXT NOT NULL,
            name          TEXT,
            score         REAL,
            state         TEXT,
            trend         TEXT,
            confidence    REAL,
            enabled       INTEGER DEFAULT 1,
            drivers_json  TEXT,
            risks_json    TEXT,
            generated_at  TEXT,
            PRIMARY KEY (date, symbol)
        )
    """)
    conn.commit()
    conn.close()


def _asset_enabled(a: dict) -> int:
    """从 detail 读 enabled 标志（缺省视为真实资产=1）。

    skeleton 资产（protocol.make_skeleton）固定写 detail.enabled=False，
    其 score=50 系占位值，Dashboard 应据 enabled=0 过滤、不参与真实强弱排序。
    """
    detail = a.get("detail") or {}
    return 1 if bool(detail.get("enabled", True)) else 0


# ── 落库 ──────────────────────────────────────────────────────
def save_universe_snapshot(snapshot: dict, date: Optional[str] = None) -> dict:
    """把 universe_snapshot 落库。幂等 upsert。

    Args:
        snapshot: build_universe_snapshot() 的返回值（含 assets 列表）。
        date: 交易日（canonical）。None → 用 snapshot['generated_at'] 日期部分兜底；
              调用方（os2_report.write）应显式传 memo.trade_date。

    Returns:
        {"saved": int, "date": str, "assets": int, "skipped": int}
        saved = 实际写入行数；skipped = 空输入或快照无 assets 的跳过计数。
    """
    ensure_schema()
    assets = (snapshot or {}).get("assets") or []
    if not assets:
        return {"saved": 0, "date": date, "assets": 0, "skipped": 1}

    # canonical date：优先显式传入；否则从 generated_at 取日期
    if not date:
        g = (snapshot or {}).get("generated_at") or ""
        date = g[:10] if g else datetime.now().strftime("%Y-%m-%d")

    conn = get_conn()
    cur = conn.cursor()
    saved = 0
    for a in assets:
        score = a.get("score", None)
        cur.execute("""
            INSERT OR REPLACE INTO asset_intelligence_history
            (date, asset_class, symbol, name, score, state, trend, confidence,
             enabled, drivers_json, risks_json, generated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            date,
            a.get("asset_class"),
            a.get("symbol"),
            a.get("name"),
            score,  # None → NULL，不伪造
            a.get("state"),
            a.get("trend"),
            a.get("confidence"),
            _asset_enabled(a),
            json.dumps(a.get("drivers") or [], ensure_ascii=False),
            json.dumps(a.get("risks") or [], ensure_ascii=False),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        saved += 1
    conn.commit()
    conn.close()
    return {"saved": saved, "date": date, "assets": len(assets), "skipped": 0}


# ── 读取（供 Phase 1.9-B） ────────────────────────────────────
def load_universe_history(date: Optional[str] = None,
                          asset_class: Optional[str] = None,
                          only_enabled: bool = False) -> list[dict]:
    """读取历史。可按 date / asset_class 过滤；only_enabled 过滤空壳。

    Returns: list of {date, asset_class, symbol, name, score, state,
                      trend, confidence, enabled, drivers, risks}
    """
    conn = get_conn()
    cur = conn.cursor()
    sql = ("SELECT date, asset_class, symbol, name, score, state, trend, "
           "confidence, enabled, drivers_json, risks_json "
           "FROM asset_intelligence_history")
    where, params = [], []
    if date:
        where.append("date=?")
        params.append(date)
    if asset_class:
        where.append("asset_class=?")
        params.append(asset_class)
    if only_enabled:
        where.append("enabled=1")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date DESC, score DESC"
    cur.execute(sql, params)
    rows = []
    for r in cur.fetchall():
        rows.append({
            "date": r[0], "asset_class": r[1], "symbol": r[2], "name": r[3],
            "score": r[4], "state": r[5], "trend": r[6], "confidence": r[7],
            "enabled": bool(r[8]),
            "drivers": json.loads(r[9]) if r[9] else [],
            "risks": json.loads(r[10]) if r[10] else [],
        })
    conn.close()
    return rows


def load_universe_panel(symbols: Optional[list[str]] = None,
                        limit: int = 250,
                        only_enabled: bool = False) -> dict[str, list[dict]]:
    """按 symbol 聚合成时间序列面板，供 Dashboard 画折线。

    Args:
        symbols: 限定标的；None = 全部。
        limit:   每个 symbol 最多保留最近 N 条。
        only_enabled: True 时仅取真实评分资产（过滤空壳）。

    Returns: {symbol: [{date, score, state, trend, confidence, enabled}, ...]}
    """
    conn = get_conn()
    cur = conn.cursor()
    sql = ("SELECT symbol, date, score, state, trend, confidence, enabled "
           "FROM asset_intelligence_history")
    params: list[Any] = []
    where = []
    if symbols:
        ph = ",".join("?" for _ in symbols)
        where.append(f"symbol IN ({ph})")
        params.extend(symbols)
    if only_enabled:
        where.append("enabled=1")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date ASC"
    cur.execute(sql, params)
    panel: dict[str, list[dict]] = {}
    for sym, d, sc, st, tr, cf, en in cur.fetchall():
        panel.setdefault(sym, []).append({
            "date": d, "score": sc, "state": st,
            "trend": tr, "confidence": cf, "enabled": bool(en),
        })
    conn.close()
    for sym in panel:
        panel[sym] = panel[sym][-limit:]
    return panel


def history_summary() -> dict:
    """累积概览（Phase 1.9-C 观察历史是否在稳定落库）。

    不依赖未来收益，只统计已落库事实：总行数、覆盖交易日数、最新日。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        total = cur.execute(
            "SELECT COUNT(*) FROM asset_intelligence_history").fetchone()[0]
        dates = [r[0] for r in cur.execute(
            "SELECT DISTINCT date FROM asset_intelligence_history "
            "ORDER BY date").fetchall()]
        # 当日（最新日）已落库的真实资产数
        today = dates[-1] if dates else None
        if today:
            n_today = cur.execute(
                "SELECT COUNT(*) FROM asset_intelligence_history "
                "WHERE date=? AND enabled=1 AND symbol<>'CASH'",
                (today,)).fetchone()[0]
        else:
            n_today = 0
    except Exception:
        total, dates, today, n_today = 0, [], None, 0
    conn.close()
    return {"total_rows": total,
            "distinct_dates": dates,
            "n_days": len(dates),
            "latest_date": today,
            "latest_day_enabled_signals": n_today}


if __name__ == "__main__":
    ensure_schema()
    print("asset_intelligence/history.py 模块加载 OK；asset_intelligence_history 表已确保存在")
