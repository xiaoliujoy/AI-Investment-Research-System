# -*- coding: utf-8 -*-
"""Phase 1.9-B1 单元测试：Investment Intelligence Validation Engine。

DB-backed：临时 SQLite（patch db._DB_PATH）播种 regime_history /
asset_intelligence_history / commodity_daily，验证三评估模块的结构、计数与
基础统计；并验证空样本（无资产认知历史）时优雅降级。

覆盖：
  - regime_effectiveness：分组统计 + 胜率 + 样本量 + 可信度
  - signal_ranking_ability：score 分档计数 + 平均收益 + 胜率
  - confidence_calibration：confidence 分档 + 正确率 + 校准诊断
  - build_report：三段齐全 + overall_caveat 非空
  - write_report：写出 validation_report.json 且可解析
  - 空样本降级：signal/confidence total_signals=0，caveat 提示暂无样本
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import regime_history as RH
from asset_intelligence.history import ensure_schema as ai_ensure_schema
from asset_intelligence.validation.report import build_report, write_report


def _seed(db_path: str):
    """播种测试数据到临时库。"""
    RH.ensure_schema()
    ai_ensure_schema()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # commodity_daily 在测试中按需建表（仅测试列，不影响生产库）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS commodity_daily (
            date TEXT, symbol TEXT, name TEXT, market TEXT, category TEXT,
            close REAL, change_pct REAL, volume REAL, open_interest REAL,
            settlement REAL, main_contract TEXT, source TEXT
        )
    """)

    # 1) regime_history：Risk On/Neutral/Risk Off 各若干，含远期收益
    regimes = [
        ("2026-01-01", "Risk On", 5.0, 6.0, 3.0, 4.0),
        ("2026-01-02", "Risk On", 4.0, 5.0, 2.0, 3.0),
        ("2026-01-03", "Risk On", 3.0, 4.0, 1.0, 2.0),
        ("2026-01-04", "Neutral", 1.0, 2.0, 0.5, 1.0),
        ("2026-01-05", "Neutral", -1.0, -2.0, -0.5, -1.0),
        ("2026-01-06", "Neutral", 2.0, 3.0, 1.0, 1.5),
        ("2026-01-07", "Neutral", 0.5, 1.0, 0.2, 0.5),
        ("2026-01-08", "Risk Off", -3.0, -4.0, -2.0, -3.0),
        ("2026-01-09", "Risk Off", -2.0, -3.0, -1.0, -2.0),
    ]
    for d, st, a5, a20, g5, g20 in regimes:
        cur.execute(
            "INSERT INTO regime_history "
            "(date, risk_state, fwd_5d_a_share, fwd_20d_a_share, "
            "fwd_5d_gold, fwd_20d_gold) VALUES (?,?,?,?,?,?)",
            (d, st, a5, a20, g5, g20))

    # 2) commodity_daily：AU0 价格序列（单调上行，保证可算远期收益）
    for i in range(1, 31):
        cur.execute(
            "INSERT INTO commodity_daily (symbol, date, close) VALUES (?,?,?)",
            ("AU0", f"2026-01-{i:02d}", 100.0 + i * 0.5))

    # 3) asset_intelligence_history：AU0 跨 score 档 + 跨 confidence 档
    #    score: 95,88,60,40,92,75,55,45,70,30
    #    conf : .9,.5,.2,.1,.8,.6,.3,.2,.75,.05
    scores = [95, 88, 60, 40, 92, 75, 55, 45, 70, 30]
    confs = [0.9, 0.5, 0.2, 0.1, 0.8, 0.6, 0.3, 0.2, 0.75, 0.05]
    for i, (sc, cf) in enumerate(zip(scores, confs)):
        cur.execute(
            "INSERT INTO asset_intelligence_history "
            "(date, asset_class, symbol, name, score, state, trend, confidence, enabled) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (f"2026-01-{i+1:02d}", "commodity", "AU0", "沪金", sc,
             "上行", "up", cf, 1))
    conn.commit()
    conn.close()


class TestValidationEngine(unittest.TestCase):

    def _tmp(self):
        fd, p = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        return p

    def test_regime_effectiveness(self):
        p = self._tmp()
        with patch("db._DB_PATH", p):
            _seed(p)
            from asset_intelligence.validation.regime_eval import regime_effectiveness
            rg = regime_effectiveness()
            self.assertEqual(rg["total_samples"], 9)
            by = {r["risk_state"]: r for r in rg["rows"]}
            self.assertEqual(set(by), {"Risk On", "Neutral", "Risk Off"})
            self.assertEqual(by["Risk On"]["n"], 3)
            self.assertEqual(by["Risk On"]["a_share_20d_win_rate"], 100.0)
            self.assertEqual(by["Risk Off"]["a_share_20d_win_rate"], 0.0)
            self.assertEqual(by["Neutral"]["a_share_20d_win_rate"], 75.0)
        os.remove(p)

    def test_signal_ranking_ability(self):
        p = self._tmp()
        with patch("db._DB_PATH", p):
            _seed(p)
            from asset_intelligence.validation.signal_eval import signal_ranking_ability
            sg = signal_ranking_ability()
            self.assertEqual(sg["total_signals"], 10)
            by = {t["tier"]: t for t in sg["tiers"]}
            self.assertEqual(by["90-100"]["n"], 2)
            self.assertEqual(by["70-90"]["n"], 3)
            self.assertEqual(by["50-70"]["n"], 2)
            self.assertEqual(by["<50"]["n"], 3)
            # 单调上行价格 → 所有档位 20 日收益为正、胜率 100
            for t in sg["tiers"]:
                self.assertIsNotNone(t["avg_ret_20d"])
                self.assertGreater(t["avg_ret_20d"], 0)
                self.assertEqual(t["win_rate_20d"], 100.0)
        os.remove(p)

    def test_confidence_calibration(self):
        p = self._tmp()
        with patch("db._DB_PATH", p):
            _seed(p)
            from asset_intelligence.validation.confidence_eval import confidence_calibration
            cf = confidence_calibration()
            self.assertEqual(cf["total_signals"], 10)
            by = {l["confidence"]: l for l in cf["levels"]}
            self.assertEqual(by["High"]["n"], 3)
            self.assertEqual(by["Medium"]["n"], 2)
            self.assertEqual(by["Low"]["n"], 5)
            for l in cf["levels"]:
                self.assertEqual(l["correct_rate_20d"], 100.0)
            diag = cf["diagnosis"]
            self.assertIn("status", diag)
            self.assertIsInstance(diag["gradient_ok"], bool)
        os.remove(p)

    def test_build_report_structure(self):
        p = self._tmp()
        with patch("db._DB_PATH", p):
            _seed(p)
            rep = build_report()
            for k in ("report", "version", "phase", "generated_at",
                      "regime_effectiveness", "signal_ranking_ability",
                      "confidence_calibration", "overall_caveat"):
                self.assertIn(k, rep)
            self.assertEqual(rep["version"], "v0.1")
            self.assertTrue(rep["overall_caveat"])
        os.remove(p)

    def test_write_report_json(self):
        p = self._tmp()
        with patch("db._DB_PATH", p):
            _seed(p)
            out = os.path.join(tempfile.gettempdir(), "validation_report_test.json")
            path = write_report(out)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["version"], "v0.1")
            self.assertIn("regime_effectiveness", data)
            os.remove(path)
        os.remove(p)

    def test_empty_asset_history_degrades(self):
        p = self._tmp()
        with patch("db._DB_PATH", p):
            RH.ensure_schema()      # 仅建 regime 表，无 asset 历史
            ai_ensure_schema()
            rep = build_report()
            self.assertEqual(rep["signal_ranking_ability"]["total_signals"], 0)
            self.assertEqual(rep["confidence_calibration"]["total_signals"], 0)
            # caveat 应提示暂无样本
            self.assertIn("暂无样本", rep["overall_caveat"])
        os.remove(p)

    def test_recorded_vs_validatable(self):
        """已落库但尚无未来收益的信号：recorded>0 但可验证=0。
        对应 Phase 1.9-C：最新交易日信号尚无未来数据，验证段应为 0 而非『暂无样本』。
        模拟：清空 seeded 行，只插一个落在价格序列范围之外的最新日信号。"""
        p = self._tmp()
        with patch("db._DB_PATH", p):
            _seed(p)
            # 清空 seeded 的 10 行，仅保留一个『未来日』信号（无未来收益可验证）
            conn = sqlite3.connect(p)
            conn.execute("DELETE FROM asset_intelligence_history")
            conn.execute(
                "INSERT INTO asset_intelligence_history "
                "(date, asset_class, symbol, name, score, state, trend, confidence, enabled) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                ("2026-02-15", "commodity", "AU0", "沪金", 80.0,
                 "上行", "up", 0.9, 1))
            conn.commit()
            conn.close()
            from asset_intelligence.validation.signal_eval import signal_ranking_ability
            from asset_intelligence.validation.confidence_eval import confidence_calibration
            sg = signal_ranking_ability()
            cf = confidence_calibration()
            # 仅 1 个未来日信号：已记录=1，因无未来收益 → 可验证=0
            self.assertEqual(sg["recorded_signals"], 1)
            self.assertEqual(sg["total_signals"], 0)
            self.assertEqual(cf["recorded_signals"], 1)
            self.assertEqual(cf["total_signals"], 0)
            # 报告累积段应反映已落库天数与最新日信号
            rep = build_report()
            h = rep["history_accumulation"]
            self.assertEqual(h["n_days"], 1)
            self.assertEqual(h["total_rows"], 1)
            # caveat 不应再写『暂无样本』（已落库），而应说明可验证=0 待解锁
            self.assertNotIn("暂无样本", rep["overall_caveat"])
            self.assertIn("可验证样本=0", rep["overall_caveat"])
        os.remove(p)


if __name__ == "__main__":
    unittest.main()
