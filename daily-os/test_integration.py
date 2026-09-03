# -*- coding: utf-8 -*-
"""P1-A.1b：daily-os 交易 OS 集成测试（pytest 原生）。

验证 daily-os 与「交易 OS 主库」的边界链路：
  1) GET /api/import_trades 从交易 OS 只读拉取 trade_journal
  2) POST /api/link + /api/evening 写本地 daily_records
  3) POST /api/sync_review 把复盘定性部分回写 trader_review
核心不变量：回写只落在「临时交易 OS 库」，绝不触碰真实主库 vibe_research.db。
依赖 daily-os/conftest.py 的 `app_server` fixture 提供隔离服务与临时 daily_os.db；
本测试再自行把 A.TRADING_DB 重定向到自建临时交易库（fixture teardown 会还原全局）。
"""
import json
import os
import sqlite3
import urllib.request
import pytest
import app as A

DATE = "2026-08-13"


def _post(base, path, body):
    req = urllib.request.Request(base + path,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read())


def _build_fake_trading_db(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE trade_journal(
        id INTEGER PRIMARY KEY, trade_date TEXT, code TEXT, name TEXT, action TEXT,
        plan_stop TEXT, result TEXT, pnl REAL, judge_result TEXT, exec_result TEXT, note TEXT)""")
    cur.execute("""CREATE TABLE trader_review(
        id INTEGER PRIMARY KEY, trade_id INTEGER, rdate TEXT, decision_quality REAL,
        execution_quality REAL, emotion_management TEXT, judgment_correct TEXT,
        execution_correct TEXT, fear_trigger TEXT, improvement TEXT,
        deviation_reason TEXT, close_reason TEXT, created_at TEXT)""")
    cur.execute("INSERT INTO trade_journal(trade_date,code,name,action,plan_stop,result,pnl,"
                "judge_result,exec_result,note) "
                "VALUES('2026-08-13','300005','探路者','买','10.2','',NULL,'right','missed','测试')")
    conn.commit()
    conn.close()


def test_integration(app_server, tmp_path):
    base = app_server["base"]

    # 重定向 TRADING_DB 到临时库（不动真实主库）。fixture teardown 会还原全局。
    fake_os = str(tmp_path / "fake_trading.db")
    _build_fake_trading_db(fake_os)
    saved_trading_db = A.TRADING_DB
    A.TRADING_DB = fake_os
    try:
        # 1) 导入今日交易（只读拉取）
        imp = _get(base, "/api/import_trades?date=" + DATE)
        assert len(imp) == 1 and imp[0]["journal_id"] == 1, imp
        assert imp[0]["name"] == "探路者", imp[0]

        # 2) 本地记录 trade_link + 晚间复盘
        link = _post(base, "/api/link", {"date": DATE, "trade_link": "1"})
        assert link == {"ok": True}, link
        evening = _post(base, "/api/evening", {"date": DATE,
            "evening_data": {"closest": "x", "taken": "恐惧", "error": "无",
                              "review": {}, "growth": {"learn": "a", "good": "b", "next": "c"}},
            "score_inner": 4, "score_abundance": 5, "score_discipline": 4,
            "score_awareness": 4, "score_joy": 5, "belief_fulfillment": 4})
        assert evening == {"ok": True}, evening

        today = _get(base, "/api/today?date=" + DATE)
        assert today.get("trade_link") == "1", today.get("trade_link")
        assert today.get("daily_state_score") == 4.4, today.get("daily_state_score")

        # 3) 复盘回写 trader_review
        syn = _post(base, "/api/sync_review", {"date": DATE, "reviews": [{
            "trade_id": 1, "belief": 4, "emotion": "恐惧", "improvement": "先写计划",
            "deviation_reason": "无", "judgment_correct": "right",
            "execution_correct": "missed", "fear_trigger": "恐惧", "close_reason": "D"}]})
        assert syn.get("ok") is True and syn.get("inserted") == 1, syn

        # 4) 核对 trader_review 真实写入（写入的是临时库，不是真实主库）
        oc = sqlite3.connect(fake_os)
        oc.row_factory = sqlite3.Row
        row = oc.execute("SELECT * FROM trader_review").fetchone()
        oc.close()
        assert row is not None, "trader_review 未写入"
        assert row["close_reason"] == "D" and row["trade_id"] == 1, dict(row)
    finally:
        A.TRADING_DB = saved_trading_db
