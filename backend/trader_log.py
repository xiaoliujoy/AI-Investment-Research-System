#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trader OS v0.1 —— A0 最小记录闭环（≤60 秒/笔）

原则（见 docs/trader_os_v0.1_architecture_freeze.md §11 Capture > Analysis）：
  先拥有数据，再分析。任何让单次记录 >60 秒的设计视为违反原则。

用法：
  python trader_log.py            # 交互式录入一笔（默认 A股/已执行/买入/计划内）
  python trader_log.py list       # 查看最近 10 笔
  python trader_log.py schema     # 初始化/迁移两张表
  python trader_log.py quick "BUY XAUUSD 4086.45 SL 4082.89 why=跌破前M5阳线低点"   # 一行极简录入（仅助手用）
  python trader_log.py exit <id> <price> [a-f原因] [a-e认知]                         # 平仓回填（仅助手用）

录入字段：
  [事后/执行层 — 旧]
  market_type   a=ASHARE / m=MT5       默认 a
  exec_status   e=executed / s=skipped 默认 e
  direction     b=BUY / s=SELL         默认 b
  planned       y/n                     默认 y   ← 驱动 Execution Fidelity
  symbol        代码或 MT5 symbol       可选，回车跳过
  decision_state n/h/u/r/f              可选，回车跳过（§4 最低优先级）
  reason        一句理由                 可选，回车跳过

  [事前意图层 — E3，Behavior Engine v0.1]
  signal_grade       a/b/c              可选，回车跳过（信心水平）
  expected_scenario  a/b/c/d            可选，回车跳过（交易假设）
  invalid_condition  一句失效条件         可选，回车跳过（文本）
  willing_hold_4h    y/n                可选，回车跳过（时间预期）
  planned_exit       一句退出计划         可选，回车跳过（文本）

  [平仓层 — 事后回填，实验性，可空]
  exit_trigger       a/b/c/d/e/f        可选，回车跳过（实际平仓原因；与 planned_exit 配对测计划偏离）
  exit_decision_state a/b/c/d/e          可选，回车跳过（平仓时刻主导认知；自我报告，非诊断，待 Q2 验证）

  [过程/结果层 — 后期回填，非手录]
  mfe_usd / mae_usd                      由 backend/mt5_mfe_mae.py 从 K 线重建

升级序列（不可合并）：
  executed + planned=1  → Execution Fidelity 分子
  skipped  + planned=1  → Execution Fidelity 分母（计划但未执行）
  E3 五字段             → Behavior Engine 事前变量（信号等级/假设/失效/时间预期/退出）
  exit_trigger          → 平仓层观测（planned_exit 的「实际」配对，测计划偏离；实验性）
  exit_decision_state   → 平仓时刻主导认知（自我报告，非诊断；待 Q2 验证）
  mfe/mae               → Phase 2 MFE/MAE 轨迹重建（止损问题 vs 入场问题）
"""
import os
import re
import sqlite3
import sys
from datetime import date

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "vibe_research.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_execution (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_datetime  TEXT DEFAULT (datetime('now')),
    trade_date      TEXT,
    market_type     TEXT NOT NULL,
    symbol          TEXT,
    direction       TEXT NOT NULL,
    exec_status     TEXT NOT NULL,
    planned         INTEGER NOT NULL,
    exit_planned    INTEGER,
    decision_state  TEXT,
    reason          TEXT,
    signal_grade        TEXT,
    expected_scenario   TEXT,
    invalid_condition   TEXT,
    willing_hold_4h     INTEGER,
    planned_exit        TEXT,
    exit_trigger        TEXT,
    exit_decision_state TEXT,
    mfe_usd             REAL,
    mae_usd             REAL,
    source          TEXT DEFAULT 'manual',
    content_hash    TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
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

# 已有旧表需要补齐的列（ALTER 不支持 IF NOT EXISTS，故用 PRAGMA 探测）
_COLUMNS_TO_ADD = {
    "signal_grade": "TEXT",
    "expected_scenario": "TEXT",
    "invalid_condition": "TEXT",
    "willing_hold_4h": "INTEGER",
    "planned_exit": "TEXT",
    "exit_trigger": "TEXT",
    "exit_decision_state": "TEXT",
    "exit_price": "REAL",
    "mfe_usd": "REAL",
    "mae_usd": "REAL",
}

DS_MAP = {"n": "normal", "h": "hesitant", "u": "urgent", "r": "revenge", "f": "fomo"}
SG_MAP = {"a": "A", "b": "B", "c": "C"}
SC_MAP = {"a": "A", "b": "B", "c": "C", "d": "D"}  # A趋势延续/B反转捕捉/C区间震荡/D新闻事件
# 平仓层（事后回填，实验性）—— exit_trigger 是「实际」平仓原因，与 planned_exit（计划）配对测计划偏离
ET_MAP = {"a": "target", "b": "structure_break", "c": "time_exit",
          "d": "emotion_exit", "e": "protect_profit", "f": "other"}
# exit_decision_state 是平仓时刻主导认知（自我报告，非诊断，待 Q2 验证）
EDS_MAP = {"a": "wrong_exit", "b": "pain_threshold", "c": "weak_exit",
           "d": "disoriented", "e": "other"}


def init():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    # 迁移：补齐 E3 / MFE-MAE 列（兼容 A0 早期已建表）
    cols = {r[1] for r in con.execute("PRAGMA table_info(trade_execution)").fetchall()}
    for name, typ in _COLUMNS_TO_ADD.items():
        if name not in cols:
            con.execute(f"ALTER TABLE trade_execution ADD COLUMN {name} {typ}")
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

    # ---- E3 事前意图层（单键为主，可空以保 ≤60s）----
    sg = ask("信心 signal_grade [a/b/c] (可选, 回车跳过): ", "")
    signal_grade = SG_MAP.get(sg, None)
    sc = ask("假设 expected_scenario [a趋势/b反转/c震荡/d新闻] (可选, 回车跳过): ", "")
    expected_scenario = SC_MAP.get(sc, None)
    invalid_condition = ask("失效条件 (可选, 回车跳过): ", "")
    wh = ask("愿持4h? [y/n] (可选, 回车跳过): ", "")
    willing_hold_4h = 1 if wh == "y" else (0 if wh == "n" else None)
    planned_exit = ask("退出计划 (可选, 回车跳过): ", "")

    # ---- 平仓层（事后回填，可空以保 ≤60s）----
    et = ask("平仓原因 exit_trigger [a目标/b结构破坏/c时间/d情绪/e保护盈利/f其他] (可选, 回车跳过): ", "")
    exit_trigger = ET_MAP.get(et, None)
    eds = ask("平仓时主导想法 exit_decision_state [a怕错/b怕亏/c偏弱/d茫然/e其他] (可选, 回车跳过): ", "")
    exit_decision_state = EDS_MAP.get(eds, None)

    con = sqlite3.connect(DB)
    con.execute(
        """INSERT INTO trade_execution
           (trade_date, market_type, symbol, direction, exec_status, planned,
            decision_state, reason,
            signal_grade, expected_scenario, invalid_condition,
            willing_hold_4h, planned_exit,
            exit_trigger, exit_decision_state)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (date.today().isoformat(), market_type, symbol or None,
         direction, exec_status, planned, decision_state, reason or None,
         signal_grade, expected_scenario, invalid_condition or None,
         willing_hold_4h, planned_exit or None,
         exit_trigger, exit_decision_state),
    )
    con.commit()
    con.close()
    print("✅ 已记录:", market_type, direction, exec_status,
          "planned=%d" % planned, ("state=%s" % decision_state) if decision_state else "")
    if signal_grade or expected_scenario or willing_hold_4h is not None:
        print("   E3:", ("sg=%s" % signal_grade) if signal_grade else "sg=-",
              ("sc=%s" % expected_scenario) if expected_scenario else "sc=-",
              ("hold4h=%s" % ("Y" if willing_hold_4h else "N")) if willing_hold_4h is not None else "hold4h=-")


def show_recent(n=10):
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT id, trade_date, market_type, symbol, direction,
                  exec_status, planned, decision_state,
                  signal_grade, expected_scenario, willing_hold_4h, exit_trigger
           FROM trade_execution ORDER BY id DESC LIMIT ?""", (n,)
    ).fetchall()
    con.close()
    if not rows:
        print("（暂无记录）")
        return
    print("\n最近 %d 笔:" % len(rows))
    for r in rows:
        sg = ("sg=%s" % r[8]) if r[8] else ""
        sc = ("sc=%s" % r[9]) if r[9] else ""
        wh = ("h4=%s" % ("Y" if r[10] else "N")) if r[10] is not None else ""
        et = ("exit=%s" % r[11]) if r[11] else ""
        extra = " ".join(x for x in (sg, sc, wh, et) if x)
        print("  #%d %s %-7s %-8s %-5s %-8s plan=%d %s %s" %
              (r[0], r[1], r[2], r[3] or "-", r[4], r[5], r[6],
               ("state=%s" % r[7]) if r[7] else "", extra))


def parse_quick(spec):
    """极简一行录入解析：BUY XAUUSD 4086.45 SL 4082.89 why=跌破前M5阳线低点
    方向/品种/入场 必填，止损与 why 选填。逐段剥离已识别 token 再取下一个，避免互相误吞。
    返回 dict 或 (None, err)。"""
    spec = spec.strip()
    rest = spec
    m = re.search(r"(BUY|SELL|做多|做空|多|空)", rest, re.IGNORECASE)
    if not m:
        return None, "缺少方向(BUY/SELL/多/空)"
    raw = m.group(1).upper()
    direction = "SELL" if raw in ("SELL", "做空", "空") else "BUY"
    rest = rest[:m.start()] + rest[m.end():]

    m = re.search(r"([A-Z]{3,6}\d?|\d{6}(?:\.[A-Z]{2})?)", rest)
    symbol = m.group(1) if m else None
    if symbol:
        rest = rest[:m.start()] + rest[m.end():]
    market_type = "ASHARE" if (symbol and re.match(r"^\d", symbol)) else "MT5"

    sl = None
    m = re.search(r"(?:SL|止损)\s*[:=]?\s*(\d+\.?\d*)", rest, re.IGNORECASE)
    if m:
        sl = float(m.group(1))
        rest = rest[:m.start()] + rest[m.end():]

    m = re.search(r"(\d+\.?\d*)", rest)
    if not m:
        return None, "缺少入场价"
    entry = float(m.group(1))

    why = None
    m = re.search(r"(?:why|因为)\s*[=：:]?\s*(.+)", spec, re.IGNORECASE)
    if m:
        why = m.group(1).strip()

    return {"direction": direction, "symbol": symbol, "market_type": market_type,
            "entry": entry, "sl": sl, "why": why}, None


def cmd_quick(spec):
    data, err = parse_quick(spec)
    if err:
        print("解析失败:", err)
        return
    reason = ("entry=%.2f" % data["entry"]) + ((" sl=%.2f" % data["sl"]) if data["sl"] else "")
    con = sqlite3.connect(DB)
    cur = con.execute(
        """INSERT INTO trade_execution
           (trade_date, market_type, symbol, direction, exec_status, planned,
            invalid_condition, reason, source)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (date.today().isoformat(), data["market_type"], data["symbol"],
         data["direction"], "executed", 1, data["why"], reason, "quick"),
    )
    tid = cur.lastrowid
    con.commit()
    con.close()
    print("✅ 已记录 #%d  %s %s @%.2f  SL=%s" %
          (tid, data["market_type"], data["direction"], data["entry"], data["sl"]))
    if data["why"]:
        print("   失效条件:", data["why"])
    else:
        print("   ⚠️ 未给 why（止损依据）—— 下一笔尽量补一句『因为…』")
    show_recent(3)


def cmd_exit(tid, price, trigger="", eds=""):
    con = sqlite3.connect(DB)
    exit_trigger = ET_MAP.get((trigger or "").lower(), None)
    exit_decision_state = EDS_MAP.get((eds or "").lower(), None)
    con.execute(
        "UPDATE trade_execution SET exit_price=?, exit_trigger=?, exit_decision_state=? WHERE id=?",
        (float(price), exit_trigger, exit_decision_state, int(tid)),
    )
    con.commit()
    con.close()
    print("✅ #%d 平仓 @%s  原因=%s 认知=%s" %
          (int(tid), price, exit_trigger or "未填", exit_decision_state or "未填"))


def main():
    if not os.path.exists(DB):
        print("DB 不存在:", DB)
        return
    init()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "schema":
        print("表已就绪（含 E3 / MFE-MAE 列）:", DB)
    elif cmd == "list":
        show_recent()
    elif cmd == "quick":
        spec = " ".join(sys.argv[2:])
        if not spec:
            print('用法: python trader_log.py quick "BUY XAUUSD 4086.45 SL 4082.89 why=跌破前M5阳线低点"')
        else:
            cmd_quick(spec)
    elif cmd == "exit":
        if len(sys.argv) < 4:
            print("用法: python trader_log.py exit <id> <price> [a-f原因] [a-e认知]")
        else:
            cmd_exit(sys.argv[2], sys.argv[3],
                     sys.argv[4] if len(sys.argv) > 4 else "",
                     sys.argv[5] if len(sys.argv) > 5 else "")
    else:
        log_one()
        show_recent(5)


if __name__ == "__main__":
    main()
