"""数据库模型定义。"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BEIJING = timezone(timedelta(hours=8))

# 数据库路径
DB_PATH = Path(__file__).parent.parent / "database" / "vibe_research.db"


def get_db() -> sqlite3.Connection:
    """获取数据库连接。"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 提升并发性能
    return conn


def init_db():
    """初始化数据库表。"""
    conn = get_db()
    
    # 市场日线
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_daily (
            date                TEXT PRIMARY KEY,
            total_amount        REAL,
            sh_amount           REAL,
            sz_amount           REAL,
            amount_change_rate  REAL,
            avg_5d_amount       REAL,
            avg_20d_amount      REAL,
            up_count            INTEGER,
            down_count          INTEGER,
            flat_count          INTEGER,
            limit_up_count      INTEGER,
            limit_down_count    INTEGER,
            real_limit_up       INTEGER,
            real_limit_down     INTEGER,
            broken_limit_count  INTEGER,
            highest_board       INTEGER,
            lianban_count       INTEGER,
            seal_rate           REAL,
            break_rate          REAL,
            promotion_rate      REAL,
            yzt_avg_return      REAL,
            yzt_win_rate        REAL,
            emotion_score       REAL,
            stage               TEXT,
            created_at          REAL,
            updated_at          REAL
        )
    """)
    
    # 板块日线
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sector_daily (
            date                TEXT,
            sector_name         TEXT,
            change_pct          REAL,
            amount              REAL,
            amount_ratio        REAL,
            amount_change_rate  REAL,
            net_amount          REAL,
            up_count            INTEGER,
            down_count          INTEGER,
            flat_count          INTEGER,
            limit_up_count      INTEGER,
            cm20_count          INTEGER,
            leader_code         TEXT,
            leader_name         TEXT,
            leader_change_pct   REAL,
            leader_amount       REAL,
            days_in_top5        INTEGER,
            consecutive_days    INTEGER,
            sector_score        REAL,
            tier                TEXT,
            PRIMARY KEY (date, sector_name)
        )
    """)
    
    # 个股日线
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            date                TEXT,
            code                TEXT,
            name                TEXT,
            sector              TEXT,
            open                REAL,
            high                REAL,
            low                 REAL,
            close               REAL,
            volume              REAL,
            amount              REAL,
            change_pct          REAL,
            turnover_rate       REAL,
            market_cap          REAL,
            float_cap           REAL,
            ma5                 REAL,
            ma10                REAL,
            ma20                REAL,
            ma60                REAL,
            high_20d            REAL,
            low_20d             REAL,
            is_new_high_20d     INTEGER,
            volume_ratio        REAL,
            main_net_buy        REAL,
            created_at          REAL,
            PRIMARY KEY (date, code)
        )
    """)
    
    # 涨停日线
    conn.execute("""
        CREATE TABLE IF NOT EXISTS limit_up_daily (
            date                TEXT,
            code                TEXT,
            name                TEXT,
            sector              TEXT,
            board_height        INTEGER,
            is_first_board      INTEGER,
            is_st               INTEGER DEFAULT 0,
            first_limit_time    TEXT,
            last_limit_time     TEXT,
            seal_amount         REAL,
            broken_count        INTEGER,
            turnover_rate       REAL,
            float_cap           REAL,
            change_pct          REAL,
            amount              REAL,
            seal_quality        TEXT,
            next_day_open       REAL,
            next_day_close      REAL,
            next_day_high       REAL,
            next_day_return     REAL,
            PRIMARY KEY (date, code)
        )
    """)

    # 迁移：存量库补 is_st 列（ST 连板过滤用），幂等
    try:
        conn.execute("ALTER TABLE limit_up_daily ADD COLUMN is_st INTEGER DEFAULT 0")
    except Exception:
        pass

    # 个股资金流（独立表，不混入 stock_daily）
    # 设计：价格数据（低频）与资金流（另一套数据体系）分离，避免混淆与幻觉。
    #   数据源：东财 push2 个股资金流排名（urllib 直连，绕开 akshare 死代理）。
    #   单位：元 → 亿元（与 amount / market_cap 同单位），f62=主力 f66=超大单
    #   f72=大单 f78=中单 f84=小单（净额）。
    #   source/confidence 标明来源与可信度，便于 Data Health 校验。
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_flow_daily (
            date                TEXT,
            code                TEXT,
            name                TEXT,
            main_net_buy        REAL,    -- 主力净流入（亿元，f62）
            super_large_net_buy REAL,    -- 超大单净流入（亿元，f66）
            large_net_buy       REAL,    -- 大单净流入（亿元，f72）
            medium_net_buy      REAL,    -- 中单净流入（亿元，f78）
            small_net_buy       REAL,    -- 小单净流入（亿元，f84）
            source              TEXT,
            confidence          REAL DEFAULT 1.0,
            PRIMARY KEY (date, code)
        )
    """)

    # 资金强度评分（Stock Capital Score，100 分模型）
    # 设计：基于真实 stock_flow_daily 个股资金流，按板块聚合 + 跨截面百分位。
    #   因子：个股主力净流入30 + 3/5日持续性20 + 板块资金排名20 + 龙头位置15
    #        + 成交活跃度10 - 异常风险15。下游：L5 龙头体系 / 日报龙头资金层。
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_capital_score (
            date            TEXT,
            code            TEXT,
            name            TEXT,
            score           REAL,    -- 综合 Capital Score（0~100）
            f_fund          REAL,    -- 个股主力净流入（0~30）
            f_persist       REAL,    -- 3/5日持续性（0~20）
            f_sector        REAL,    -- 板块资金排名（0~20）
            f_leader        REAL,    -- 龙头位置（0~15）
            f_active        REAL,    -- 成交活跃度（0~10）
            f_risk          REAL,    -- 异常风险扣分（0 或 15）
            sector_name     TEXT,    -- 贡献最高的板块（em 名）
            sector_rank_pct REAL,    -- 该板块资金排名百分位（0~1）
            intra_rank      INTEGER, -- 该板块内主力净流入排名（1=龙头）
            is_st           INTEGER DEFAULT 0,
            PRIMARY KEY (date, code)
        )
    """)

    # 观察清单
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            code                TEXT,
            name                TEXT,
            sector              TEXT,
            added_date          TEXT,
            watch_reason        TEXT,
            trigger_condition   TEXT,
            invalidation_condition TEXT,
            target_price        REAL,
            stop_loss           REAL,
            status              TEXT DEFAULT "watching",
            notes               TEXT,
            created_at          REAL,
            updated_at          REAL
        )
    """)
    
    # 交易信号
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_signals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT,
            code                TEXT,
            name                TEXT,
            signal_type         TEXT,
            direction           TEXT,
            trigger_price       REAL,
            target_price        REAL,
            stop_loss           REAL,
            confidence          REAL,
            reasons             TEXT,
            status              TEXT DEFAULT "active",
            created_at          REAL
        )
    """)
    

    # 全球市场日线
    conn.execute("""
        CREATE TABLE IF NOT EXISTS global_market_daily (
            date                TEXT,
            symbol              TEXT,
            name                TEXT,
            region              TEXT,
            category            TEXT,
            close               REAL,
            change_pct          REAL,
            volume              REAL,
            market_status       TEXT,
            created_at          REAL,
            PRIMARY KEY (date, symbol)
        )
    """)
    
    # 全球RPS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS global_rps (
            date                TEXT,
            symbol              TEXT,
            name                TEXT,
            return_5d           REAL,
            return_20d          REAL,
            return_60d          REAL,
            global_rank         INTEGER,
            relative_score      REAL,
            PRIMARY KEY (date, symbol)
        )
    """)
    
    # 全球评分
    conn.execute("""
        CREATE TABLE IF NOT EXISTS global_score (
            date                TEXT PRIMARY KEY,
            risk_appetite       REAL,
            tech_cycle          REAL,
            liquidity           REAL,
            china_relative      REAL,
            total_score         REAL,
            stage               TEXT,
            analysis            TEXT
        )
    """)

    # 创建索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sector_daily_name ON sector_daily(sector_name, date)")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_global_market_symbol ON global_market_daily(symbol, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_global_rps_date ON global_rps(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_global_score_date ON global_score(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_daily_sector ON stock_daily(sector, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_limit_up_sector ON limit_up_daily(sector, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_limit_up_height ON limit_up_daily(date, board_height)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_date ON trade_signals(date)")
    
    conn.commit()
    conn.close()


# =============================================================================
# Market Daily CRUD
# =============================================================================

def save_market_daily(data: dict):
    """保存市场日线数据。"""
    conn = get_db()
    now = time.time()
    
    conn.execute("""
        INSERT OR REPLACE INTO market_daily (
            date, total_amount, sh_amount, sz_amount, amount_change_rate,
            avg_5d_amount, avg_20d_amount, up_count, down_count, flat_count,
            limit_up_count, limit_down_count, real_limit_up, real_limit_down,
            broken_limit_count, highest_board, lianban_count,
            seal_rate, break_rate, promotion_rate,
            yzt_avg_return, yzt_win_rate, emotion_score, stage,
            created_at, updated_at
        ) VALUES (
            :date, :total_amount, :sh_amount, :sz_amount, :amount_change_rate,
            :avg_5d_amount, :avg_20d_amount, :up_count, :down_count, :flat_count,
            :limit_up_count, :limit_down_count, :real_limit_up, :real_limit_down,
            :broken_limit_count, :highest_board, :lianban_count,
            :seal_rate, :break_rate, :promotion_rate,
            :yzt_avg_return, :yzt_win_rate, :emotion_score, :stage,
            :created_at, :updated_at
        )
    """, {**data, "created_at": now, "updated_at": now})
    
    conn.commit()
    conn.close()


def get_market_daily(date: str) -> Optional[dict]:
    """获取指定日期的市场数据。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM market_daily WHERE date = ?", (date,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_market_daily_range(start_date: str, end_date: str) -> list[dict]:
    """获取日期范围的市场数据。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM market_daily WHERE date >= ? AND date <= ? ORDER BY date",
        (start_date, end_date)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_market_daily(days: int = 1) -> list[dict]:
    """获取最近N天的市场数据。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM market_daily ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =============================================================================
# Sector Daily CRUD
# =============================================================================

def save_sector_daily(data: dict):
    """保存板块日线数据。"""
    conn = get_db()
    
    conn.execute("""
        INSERT OR REPLACE INTO sector_daily (
            date, sector_name, change_pct, amount, amount_ratio,
            amount_change_rate, net_amount, up_count, down_count, flat_count,
            limit_up_count, cm20_count, leader_code, leader_name,
            leader_change_pct, leader_amount, days_in_top5, consecutive_days,
            sector_score, tier
        ) VALUES (
            :date, :sector_name, :change_pct, :amount, :amount_ratio,
            :amount_change_rate, :net_amount, :up_count, :down_count, :flat_count,
            :limit_up_count, :cm20_count, :leader_code, :leader_name,
            :leader_change_pct, :leader_amount, :days_in_top5, :consecutive_days,
            :sector_score, :tier
        )
    """, data)
    
    conn.commit()
    conn.close()


def get_sector_daily(sector_name: str, days: int = 20) -> list[dict]:
    """获取板块最近N天数据。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sector_daily WHERE sector_name = ? ORDER BY date DESC LIMIT ?",
        (sector_name, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sector_daily_by_date(date: str) -> list[dict]:
    """获取指定日期的所有板块数据。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sector_daily WHERE date = ? ORDER BY amount DESC",
        (date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_sectors(date: str, top_n: int = 10) -> list[dict]:
    """获取指定日期的TOP N板块。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sector_daily WHERE date = ? ORDER BY sector_score DESC LIMIT ?",
        (date, top_n)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sector_consecutive_days(sector_name: str) -> int:
    """获取板块连续上榜天数。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT date, sector_score FROM sector_daily WHERE sector_name = ? AND sector_score >= 60 ORDER BY date DESC",
        (sector_name,)
    ).fetchall()
    
    if not rows:
        conn.close()
        return 0
    
    consecutive = 0
    prev_date = None
    
    for row in rows:
        current_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        if prev_date is None or (prev_date - current_date).days == 1:
            consecutive += 1
            prev_date = current_date
        else:
            break
    
    conn.close()
    return consecutive


# =============================================================================
# Stock Daily CRUD
# =============================================================================

def save_stock_daily(data: dict):
    """保存个股日线数据。"""
    conn = get_db()
    
    conn.execute("""
        INSERT OR REPLACE INTO stock_daily (
            date, code, name, sector, open, high, low, close,
            volume, amount, change_pct, turnover_rate, market_cap, float_cap,
            ma5, ma10, ma20, ma60, high_20d, low_20d, is_new_high_20d,
            volume_ratio, main_net_buy, created_at
        ) VALUES (
            :date, :code, :name, :sector, :open, :high, :low, :close,
            :volume, :amount, :change_pct, :turnover_rate, :market_cap, :float_cap,
            :ma5, :ma10, :ma20, :ma60, :high_20d, :low_20d, :is_new_high_20d,
            :volume_ratio, :main_net_buy, :created_at
        )
    """, {**data, "created_at": time.time()})
    
    conn.commit()
    conn.close()


def save_stock_daily_batch(data_list: list[dict]):
    """批量保存个股日线数据。"""
    conn = get_db()
    now = time.time()
    
    conn.executemany("""
        INSERT OR REPLACE INTO stock_daily (
            date, code, name, sector, open, high, low, close,
            volume, amount, change_pct, turnover_rate, market_cap, float_cap,
            ma5, ma10, ma20, ma60, high_20d, low_20d, is_new_high_20d,
            volume_ratio, main_net_buy, created_at
        ) VALUES (
            :date, :code, :name, :sector, :open, :high, :low, :close,
            :volume, :amount, :change_pct, :turnover_rate, :market_cap, :float_cap,
            :ma5, :ma10, :ma20, :ma60, :high_20d, :low_20d, :is_new_high_20d,
            :volume_ratio, :main_net_buy, :created_at
        )
    """, [{**d, "created_at": now} for d in data_list])
    
    conn.commit()
    conn.close()


def get_stock_daily(code: str, days: int = 30) -> list[dict]:
    """获取个股最近N天数据。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM stock_daily WHERE code = ? ORDER BY date DESC LIMIT ?",
        (code, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stock_daily_by_date(date: str) -> list[dict]:
    """获取指定日期的所有个股数据。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM stock_daily WHERE date = ? ORDER BY amount DESC",
        (date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stock_by_code_and_date(code: str, date: str) -> Optional[dict]:
    """获取指定股票指定日期的数据。"""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM stock_daily WHERE code = ? AND date = ?",
        (code, date)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# Limit Up Daily CRUD
# =============================================================================

def save_limit_up_daily(data: dict):
    """保存涨停日线数据。"""
    conn = get_db()
    
    conn.execute("""
        INSERT OR REPLACE INTO limit_up_daily (
            date, code, name, sector, board_height, is_first_board, is_st,
            first_limit_time, last_limit_time, seal_amount, broken_count,
            turnover_rate, float_cap, change_pct, amount, seal_quality
        ) VALUES (
            :date, :code, :name, :sector, :board_height, :is_first_board, :is_st,
            :first_limit_time, :last_limit_time, :seal_amount, :broken_count,
            :turnover_rate, :float_cap, :change_pct, :amount, :seal_quality
        )
    """, data)
    
    conn.commit()
    conn.close()


def save_limit_up_daily_batch(data_list: list[dict]):
    """批量保存涨停日线数据。"""
    conn = get_db()
    
    conn.executemany("""
        INSERT OR REPLACE INTO limit_up_daily (
            date, code, name, sector, board_height, is_first_board, is_st,
            first_limit_time, last_limit_time, seal_amount, broken_count,
            turnover_rate, float_cap, change_pct, amount, seal_quality
        ) VALUES (
            :date, :code, :name, :sector, :board_height, :is_first_board, :is_st,
            :first_limit_time, :last_limit_time, :seal_amount, :broken_count,
            :turnover_rate, :float_cap, :change_pct, :amount, :seal_quality
        )
    """, data_list)
    
    conn.commit()
    conn.close()


def get_limit_up_daily(date: str) -> list[dict]:
    """获取指定日期的涨停股。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM limit_up_daily WHERE date = ? ORDER BY board_height DESC",
        (date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_limit_up_sector_distribution(date: str) -> list[dict]:
    """获取指定日期涨停股的板块分布。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT sector, COUNT(*) as count, 
               SUM(board_height) as total_height,
               AVG(board_height) as avg_height
        FROM limit_up_daily 
        WHERE date = ? 
        GROUP BY sector 
        ORDER BY count DESC
    """, (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_limit_up_history(code: str, days: int = 30) -> list[dict]:
    """获取指定股票的涨停历史。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM limit_up_daily WHERE code = ? ORDER BY date DESC LIMIT ?",
        (code, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =============================================================================
# 统计与元数据
# =============================================================================

def get_data_summary() -> dict:
    """获取数据库数据摘要。"""
    conn = get_db()
    
    summary = {}
    
    for table in ["market_daily", "sector_daily", "stock_daily", "limit_up_daily"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        summary[table] = count
    
    # 最新日期
    row = conn.execute("SELECT MAX(date) FROM market_daily").fetchone()
    summary["latest_market_date"] = row[0] if row else None
    
    row = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    summary["latest_stock_date"] = row[0] if row else None
    
    row = conn.execute("SELECT MAX(date) FROM limit_up_daily").fetchone()
    summary["latest_limit_up_date"] = row[0] if row else None
    
    conn.close()
    return summary


def get_missing_dates(table: str, start_date: str, end_date: str) -> list[str]:
    """获取指定表中缺失的日期。"""
    conn = get_db()
    
    rows = conn.execute(
        f"SELECT DISTINCT date FROM {table} WHERE date >= ? AND date <= ?",
        (start_date, end_date)
    ).fetchall()
    
    existing_dates = set(r["date"] for r in rows)
    
    # 生成所有日期
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    
    all_dates = set()
    current = start
    while current <= end:
        # 只检查交易日（周一至周五）
        if current.weekday() < 5:
            all_dates.add(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    
    missing = sorted(all_dates - existing_dates)
    conn.close()
    return missing

