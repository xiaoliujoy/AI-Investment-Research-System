#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trader OS v0.1 —— A0 最小记录闭环（≤60 秒/笔）

原则（见 docs/trader_os_v0.1_architecture_freeze.md §11 Capture > Analysis）：
  先拥有数据，再分析。任何让单次记录 >60 秒的设计视为违反原则。

用法：
  python trader_log.py            # 交互式录入一笔（默认 A股/已执行/买入/计划内）
  python trader_log.py list       # 查看最近 10 笔
  python trader_log.py schema     # 仅初始化两张表

录入字段（交易结束后）：
  market_type   a=ASHARE / m=MT5       默认 a
  exec_status   e=executed / s=skipped 默认 e
  direction     b=BUY / s=SELL         默认 b
  planned       y/n                     默认 y   ← 驱动 Execution Fidelity
  symbol        代码或 MT5 symbol       可选，回车跳过
  decision_state n/h/u/r/f              可选，回车跳过（§4 最低优先级）
  reason        一句理由                 可选，回车跳过

升级序列（不可合并）：
  executed + planned=1  → Execution Fidelity 分子
  skipped  + planned=1  → Execution Fidelity 分母（计划但未执行）
  exit_planned          → Holding Discipline（v0.1 留空，稍后补）
"""
import os
import sqlite3
import sys
from datetime import date

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "vibe_research.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_execution (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_datetime TEXT DEFAULT (datetime('now')),
    trade_date    TEXT,
    market_type   TEXT NOT NULL,
    symbol        TEXT,
    direction     TEXT NOT NULL,
    exec_status   TEXT NOT NULL,
    planned       INTEGER NOT NULL,
    exit_planned  INTEGER,
    decision_state TEXT,
    reason        TEXT,
    source        TEXT DEFAULT 'manual',
    content_hash  TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_snapshot (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     TEXT,
    as_of_datetime  TEXT DEFAULT (datetime('now')),
    market_type     TEXT,
    regime_state    TEXT,
    regime_score    REAL,
    risk_budget_equity REAL,
    sector_context  TEXT,
    asset_context   TEXT,
    reasoning_text  TEXT,
    confidence      INTEGER,
    content_hash    TEXT
);
"""

DS_MAP = {"n": "normal", "h": "hesitant", "u": "urgent", "r": "revenge", "f": "fomo"}


def init():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def ask(prompt, default=""):
    """单行输入，默认回车即 default。"""
    try:
        val = input(prompt).strip().lower()
    except EOFError:
        val = ""
    return val or default


def log_one():
    print("\n--- Trader OS 记录（≤60s）---")
    market = ask("市场 [a]share/[m]t5 (默认 a): ", "a")
    market_type = "MT5" if market == "m" else "ASHARE"

    status = ask("执行状态 [e]xecuted/[s]kipped (默认 e): ", "e")
    exec_status = "skipped" if status == "s" else "executed"

    direction = ask("方向 [b]uy/[s]ell (默认 b): ", "b")
    direction = "SELL" if direction == "s" else "BUY"

    planned = ask("计划内? [y/n] (默认 y): ", "y")
    planned = 1 if planned == "y" else 0

    symbol = ask("代码/symbol (可选, 回车跳过): ", "")
    ds = ask("状态 [n/h/u/r/f] (可选, 回车跳过): ", "")
    decision_state = DS_MAP.get(ds, None)
    reason = ask("一句理由 (可选, 回车跳过): ", "")

    con = sqlite3.connect(DB)
    con.execute(
        """INSERT INTO trade_execution
           (trade_date, market_type, symbol, direction, exec_status, planned,
            decision_state, reason)
           VALUES (?,?,?,?,?,?,?,?)""",
        (date.today().isoformat(), market_type, symbol or None,
         direction, exec_status, planned, decision_state, reason or None),
    )
    con.commit()
    con.close()
    print("✅ 已记录:", market_type, direction, exec_status,
          "planned=%d" % planned, ("state=%s" % decision_state) if decision_state else "")


def show_recent(n=10):
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT id, trade_date, market_type, symbol, direction,
                  exec_status, planned, decision_state
           FROM trade_execution ORDER BY id DESC LIMIT ?""", (n,)
    ).fetchall()
    con.close()
    if not rows:
        print("（暂无记录）")
        return
    print("\n最近 %d 笔:" % len(rows))
    for r in rows:
        print("  #%d %s %-7s %-8s %-5s %-8s plan=%d %s" %
              (r[0], r[1], r[2], r[3] or "-", r[4], r[5], r[6],
               ("state=%s" % r[7]) if r[7] else ""))


def main():
    if not os.path.exists(DB):
        print("DB 不存在:", DB)
        return
    init()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "schema":
        print("表已就绪:", DB)
    elif cmd == "list":
        show_recent()
    else:
        log_one()
        show_recent(5)


if __name__ == "__main__":
    main()
