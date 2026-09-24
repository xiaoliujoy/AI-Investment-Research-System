# -*- coding: utf-8 -*-
"""F17 —— 单位 lineage 回归测试（资金维度在主线评分中不得被压成 ~0）。

【缺陷根因（2026-09-24 两方独立确认）】
    `stock_flow_daily.main_net_buy` = **亿元**（models.py:170，东财 f62）
      → `sector_daily.net_amount` = SUM(main_net_buy) = **亿元**
        → `ranking_main_line()` 里 `cum_net` 已是亿元
          → 原代码 `score = cum_net / 1e8 + amt_growth*50 + profit` **再除一次 1e8**
            ⇒ 资金项落到 ~1e-6 量级，相对 profit(~200) 贡献约 **0.0019 ppm**，
               「资金+成交额并重」的方法论在评分里形同虚设。

【修复】
    去掉错误的 `/1e8`（**不改权重**：amt_growth 系数 50、profit 原样保留）。
    同源的显示缺陷：`fmt(net,'yi')` 会把已是亿元的值二次 /1e8 → 恒定 0.00亿，
    改用不入参缩放的 `fmt_yi()`。

【测试策略】
    内存库构造反例，不连生产库 / 不联网 / 不写盘。
    关键断言：资金项贡献 == cum_net 本身（量级 ≥ 1），而非 1e-6。
"""
import sqlite3

import pytest

import main_line_report as M

_DDL = """
CREATE TABLE sector_daily (
    date TEXT, sector_name TEXT, net_amount REAL, amount REAL,
    change_pct REAL, up_count INT, down_count INT
)
"""


def _conn(rows):
    con = sqlite3.connect(":memory:")
    con.execute(_DDL)
    con.executemany(
        "INSERT INTO sector_daily (date, sector_name, net_amount, amount, "
        "change_pct, up_count, down_count) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    return con


# date, sector, net(亿元), amount(元), chg, up, down
_ROWS = [
    ("2026-09-24", "资金强", 100.0, 1e10, 2.1, 300, 100),
    ("2026-09-23", "资金强", 50.0, 5e9, 1.0, 250, 150),
    ("2026-09-24", "资金弱", -20.0, 1e10, 2.1, 300, 100),
    ("2026-09-23", "资金弱", 0.0, 5e9, 1.0, 250, 150),
]


def test_f17_capital_term_not_annihilated():
    """核心断言：资金项贡献 == cum_net 本身（150），不是 150/1e8。"""
    con = _conn(_ROWS)
    try:
        ranked = M.ranking_main_line(con, ["2026-09-24", "2026-09-23"])
        top = {r[0]: r for r in ranked}["资金强"]
        _sec, _net, _amt, _chg, _up, _dwn, cum_net, amt_growth, profit, score = top

        assert cum_net == 150.0
        assert amt_growth == 1.0          # 1e10 / 5e9 - 1
        assert profit == 200.0            # 300 - 100

        capital_contribution = score - (amt_growth * 50 + profit)
        assert capital_contribution == pytest.approx(150.0, abs=1e-6), (
            f"资金项贡献应为 150（亿元原值），实际 {capital_contribution}"
        )
        # 旧缺陷的量化留证：若仍 /1e8，该贡献会是 1.5e-6
        assert capital_contribution > 1.0, "资金项仍被缩放，F17 未修"
    finally:
        con.close()


def test_f17_score_formula_and_ordering():
    con = _conn(_ROWS)
    try:
        ranked = M.ranking_main_line(con, ["2026-09-24", "2026-09-23"])
        assert ranked[0][0] == "资金强", "资金更强的板块必须排前面（旧 bug 下排序由 profit 主导）"
        assert ranked[0][-1] == pytest.approx(150 + 50 + 200, abs=1e-6)
        assert ranked[1][-1] == pytest.approx(-20 + 50 + 200, abs=1e-6)
    finally:
        con.close()


def test_f17_bug_magnitude_documented():
    """留证：旧公式下 150 亿的资金项对 score 的贡献量级。"""
    assert 150.0 / 1e8 < 1e-5, "缺陷量级假设不成立，测试前提需复核"


def test_fmt_yi_is_not_rescaled():
    assert M.fmt_yi(150.0) == "150.00亿"
    assert M.fmt_yi(0.0) == "0.00亿"
    assert M.fmt_yi(None) == "-"


def test_fmt_yi_still_converts_yuan():
    """成交额单位是元，仍必须走 /1e8 的 fmt(v,'yi')。"""
    assert M.fmt(1e10, "yi") == "100.00亿"
    assert M.fmt(5e9, "yi") == "50.00亿"


def test_no_double_scaling_left_in_source():
    src = open(M.__file__, "r", encoding="utf-8").read()
    # 去注释后扫描：避免修复说明性注释（如「原为 cum_net / 1e8」）误命中 lint。
    # 真正的回归防护由 test_f17_capital_term_not_annihilated（断言资金项贡献==150）承担。
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "cum_net / 1e8" not in code, "score 中不得再出现双重 /1e8"
    # 净流入类字段（net / cum / s）不得再用 fmt(...,'yi')
    for bad in ("fmt(net,'yi')", 'fmt(net,"yi")', "fmt(cum,'yi')", "fmt(s,'yi')"):
        assert bad not in code, f"净流入字段仍被二次缩放：{bad}"
