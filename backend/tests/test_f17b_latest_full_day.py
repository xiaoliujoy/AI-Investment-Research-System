# -*- coding: utf-8 -*-
"""F17b —— `latest_full_day()` 日期语义回归测试。

【缺陷】
  旧实现 `ORDER BY COUNT(*) DESC LIMIT 1` 取的是「**行数最多的那天**」。
  2026-07-21 数据清洗后行数由 9,327 降至 5,553，行数排序于是恒定选中
  **2026-07-20**，主线报告默认读约 40 个交易日前的数据（P0）。

【正确语义】
  最新交易日 = **日期最大**，与当日行数多寡无关。

【测试策略】
  不连生产库、不联网、不写盘：在内存库里构造「旧日期行数多 / 新日期行数少」
  的极端反例，确保旧实现必然失败、新实现必然通过。
"""
import sqlite3

import pytest

import main_line_report as M


def _make_conn(rows_by_date):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE stock_daily (date TEXT, code TEXT, close REAL)")
    for d, n in rows_by_date.items():
        con.executemany(
            "INSERT INTO stock_daily (date, code, close) VALUES (?,?,?)",
            [(d, f"{i:06d}", 10.0 + i % 7) for i in range(n)],
        )
    con.commit()
    return con


def test_latest_full_day_returns_newest_not_most_rows():
    """核心反例：旧日期 9,327 行 vs 新日期 5,553 行 → 必须返回新日期。"""
    con = _make_conn({"2026-07-20": 9327, "2026-09-23": 5553})
    try:
        assert M.latest_full_day(con) == "2026-09-23"
    finally:
        con.close()


def test_latest_full_day_ignores_row_count_entirely():
    """极端反例：新日期只有 1 行，旧日期有 10,000 行。"""
    con = _make_conn({"2026-01-05": 10000, "2026-09-29": 1})
    try:
        assert M.latest_full_day(con) == "2026-09-29"
    finally:
        con.close()


def test_latest_full_day_equal_counts_still_newest():
    con = _make_conn({"2026-09-22": 100, "2026-09-23": 100, "2026-09-24": 100})
    try:
        assert M.latest_full_day(con) == "2026-09-24"
    finally:
        con.close()


def test_latest_full_day_sql_semantics_documented():
    """守住 SQL 本身：必须是 ORDER BY date DESC，不得回退成 COUNT(*)。"""
    src = open(M.__file__, "r", encoding="utf-8").read()
    start = src.index("SELECT date FROM stock_daily GROUP BY date")
    sql = src[start:start + 120]
    assert "ORDER BY date DESC" in sql, "必须用日期倒序，而非行数排序"
    assert "COUNT(*)" not in sql, "SQL 本身不得再用行数最多作为排序依据"
