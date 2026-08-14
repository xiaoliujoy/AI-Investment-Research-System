"""OMI 存储层（只增表，不碰现有评分表）。

三张表：
- option_watchlist      观察标的配置（幂等 seed，来自 omi.watchlist）
- option_chain_raw      原始期权链（逐合约原始字段，含 iv_reported 参考列）
- option_omi_daily      每日计算后的 19 字段 + AI 摘要

设计要点（用户要求：原始与计算分离、可重算历史）：
- 原始链原样入库，指标层重算不依赖已存指标。
- option_omi_daily 主键 (omi_id, trade_date)；重跑同日期覆盖。
- 历史查询 get_omi_history 用于 iv_rank / iv_percentile / iv_change_pct。
"""

from __future__ import annotations

import json
import time
from typing import Optional

from database.models import get_db

from .chain_model import RawOptionChain
from .watchlist import OMI_WATCHLIST


def init_omi_db() -> None:
    """创建 OMI 表并 seed watchlist。幂等。"""
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS option_watchlist (
            omi_id          TEXT PRIMARY KEY,
            name            TEXT,
            asset_class     TEXT,
            region          TEXT,
            exchange        TEXT,
            adapter         TEXT,
            underlying_symbol TEXT,
            product_key     TEXT,
            contract_root   TEXT,
            enabled         INTEGER DEFAULT 1,
            notes           TEXT,
            created_at      REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS option_chain_raw (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            omi_id          TEXT,
            trade_date      TEXT,
            contract_code   TEXT,
            option_type     TEXT,
            strike          REAL,
            expiry          TEXT,
            last_price      REAL,
            volume          REAL,
            open_interest   REAL,
            iv_reported     REAL,
            delta           REAL,
            underlying_price REAL,
            source          TEXT,
            created_at      REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS option_omi_daily (
            omi_id          TEXT,
            trade_date      TEXT,
            underlying_price REAL,
            underlying_change_pct REAL,
            atm_iv          REAL,
            iv_rank         REAL,
            iv_percentile   REAL,
            front_month_iv  REAL,
            back_month_iv   REAL,
            iv_term_structure REAL,
            iv_change_pct   REAL,
            iv_skew         REAL,
            call_volume     REAL,
            put_volume      REAL,
            put_call_volume_ratio REAL,
            call_open_interest REAL,
            put_open_interest REAL,
            put_call_oi_ratio REAL,
            max_call_oi_strike REAL,
            max_put_oi_strike REAL,
            option_market_summary TEXT,
            raw_coverage    TEXT,
            created_at      REAL,
            PRIMARY KEY (omi_id, trade_date)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chain_raw ON option_chain_raw(omi_id, trade_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_omi_daily_date ON option_omi_daily(trade_date)")

    # seed watchlist（仅插入缺失项，不覆盖已有配置）
    now = time.time()
    for u in OMI_WATCHLIST:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_watchlist
                (omi_id, name, asset_class, region, exchange, adapter,
                 underlying_symbol, product_key, contract_root, enabled, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                u.omi_id, u.name, u.asset_class, u.region, u.exchange, u.adapter,
                u.underlying_symbol, u.product_key, u.contract_root, u.notes, now,
            ),
        )
    conn.commit()
    conn.close()


def get_enabled_watchlist() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM option_watchlist WHERE enabled = 1").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_chain_raw(chain: RawOptionChain) -> int:
    conn = get_db()
    now = time.time()
    # 同日期重跑：先清后写，避免原始链重复累积
    conn.execute(
        "DELETE FROM option_chain_raw WHERE omi_id = ? AND trade_date = ?",
        (chain.omi_id, chain.trade_date),
    )
    rows = [
        (
            c.omi_id, c.trade_date, c.contract_code, c.option_type, c.strike,
            c.expiry, c.last_price, c.volume, c.open_interest, c.iv_reported,
            c.delta, c.underlying_price, c.source, now,
        )
        for c in chain.contracts
    ]
    conn.executemany(
        """
        INSERT INTO option_chain_raw
            (omi_id, trade_date, contract_code, option_type, strike, expiry,
             last_price, volume, open_interest, iv_reported, delta,
             underlying_price, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    n = len(rows)
    conn.close()
    return n


def save_omi_daily(rec: dict) -> None:
    conn = get_db()
    now = time.time()
    conn.execute(
        """
        INSERT OR REPLACE INTO option_omi_daily
            (omi_id, trade_date, underlying_price, underlying_change_pct,
             atm_iv, iv_rank, iv_percentile, front_month_iv, back_month_iv,
             iv_term_structure, iv_change_pct, iv_skew,
             call_volume, put_volume, put_call_volume_ratio,
             call_open_interest, put_open_interest, put_call_oi_ratio,
             max_call_oi_strike, max_put_oi_strike, option_market_summary,
             raw_coverage, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rec["omi_id"], rec["trade_date"], rec.get("underlying_price"),
            rec.get("underlying_change_pct"), rec.get("atm_iv"), rec.get("iv_rank"),
            rec.get("iv_percentile"), rec.get("front_month_iv"), rec.get("back_month_iv"),
            rec.get("iv_term_structure"), rec.get("iv_change_pct"), rec.get("iv_skew"),
            rec.get("call_volume"), rec.get("put_volume"), rec.get("put_call_volume_ratio"),
            rec.get("call_open_interest"), rec.get("put_open_interest"), rec.get("put_call_oi_ratio"),
            rec.get("max_call_oi_strike"), rec.get("max_put_oi_strike"),
            rec.get("option_market_summary"), rec.get("raw_coverage"), now,
        ),
    )
    conn.commit()
    conn.close()


def get_omi_history(omi_id: str, trade_date: str, limit: int = 252) -> list[dict]:
    """取该标的在 trade_date 之前的历史日度记录（用于 rank/percentile/change）。"""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT trade_date, atm_iv FROM option_omi_daily
        WHERE omi_id = ? AND trade_date < ?
        ORDER BY trade_date ASC
        LIMIT ?
        """,
        (omi_id, trade_date, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_omi_daily(omi_id: str, trade_date: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM option_omi_daily WHERE omi_id = ? AND trade_date = ?",
        (omi_id, trade_date),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_omi_daily(trade_date: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM option_omi_daily WHERE trade_date = ? ORDER BY omi_id",
        (trade_date,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
