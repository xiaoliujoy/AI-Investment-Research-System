# -*- coding: utf-8 -*-
"""Phase 1.9-A 单元测试：统一资产认知历史层（asset_intelligence.history）。

DB-backed：用临时 SQLite 文件（patch db._DB_PATH）验证落库 / 幂等 / 过滤 /
score=None→NULL / 空壳 enabled 标志 / 面板聚合，不污染生产库。

覆盖：
  - ensure_schema 建表
  - save_and_load 保存+读取+score 降序
  - idempotent_upsert 同 (date,symbol) 覆盖不增行
  - score_none_stored_as_null（回应审计问题 #2：缺失不伪造 0）
  - skeleton_disabled_flag（空壳 enabled=0，Dashboard 可过滤）
  - panel_aggregation 时间序列面板
  - empty_snapshot_skipped 空输入安全跳过
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from asset_intelligence.history import (
    ensure_schema,
    save_universe_snapshot,
    load_universe_history,
    load_universe_panel,
)


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _snap(assets):
    return {
        "generated_at": "2026-07-29T23:00:00",
        "n_assets": len(assets),
        "asset_classes": [],
        "assets": assets,
        "protocol_health": {},
        "note": "t",
    }


def _asset(**kw):
    base = {
        "asset_class": "commodity", "symbol": "AU0", "name": "沪金",
        "state": "上行", "score": 70.0, "trend": "up",
        "drivers": ["宏观驱动"], "risks": ["技术回调"], "confidence": 0.8,
        "detail": {},
    }
    base.update(kw)
    return base


class TestUniverseHistory(unittest.TestCase):

    def test_ensure_schema_creates_table(self):
        path = _tmp_db()
        with patch("db._DB_PATH", path):
            ensure_schema()
            conn = sqlite3.connect(path)
            tbl = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='asset_intelligence_history'"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(tbl)
        os.remove(path)

    def test_save_and_load(self):
        path = _tmp_db()
        with patch("db._DB_PATH", path):
            snap = _snap([
                _asset(symbol="AU0", score=70.0),
                _asset(symbol="CU0", score=63.0),
            ])
            res = save_universe_snapshot(snap, date="2026-07-29")
            self.assertEqual(res["saved"], 2)
            rows = load_universe_history(date="2026-07-29")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["symbol"], "AU0")  # score 降序
            self.assertTrue(rows[0]["enabled"])
        os.remove(path)

    def test_idempotent_upsert(self):
        path = _tmp_db()
        with patch("db._DB_PATH", path):
            save_universe_snapshot(_snap([_asset(symbol="AU0", score=70.0)]),
                                   date="2026-07-29")
            save_universe_snapshot(_snap([_asset(symbol="AU0", score=80.0)]),
                                   date="2026-07-29")  # 同 (date,symbol) 覆盖
            rows = load_universe_history(date="2026-07-29")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["score"], 80.0)
        os.remove(path)

    def test_score_none_stored_as_null(self):
        path = _tmp_db()
        with patch("db._DB_PATH", path):
            save_universe_snapshot(_snap([_asset(symbol="AU0", score=None)]),
                                   date="2026-07-29")
            conn = sqlite3.connect(path)
            val = conn.execute(
                "SELECT score FROM asset_intelligence_history WHERE symbol='AU0'"
            ).fetchone()[0]
            conn.close()
            self.assertIsNone(val)  # 缺失→NULL，不伪造 0
        os.remove(path)

    def test_skeleton_disabled_flag(self):
        path = _tmp_db()
        with patch("db._DB_PATH", path):
            snap = _snap([
                _asset(symbol="US10Y", asset_class="bond", score=50.0,
                       detail={"skeleton": True, "enabled": False}),
                _asset(symbol="AU0", score=70.0),
            ])
            save_universe_snapshot(snap, date="2026-07-29")
            all_rows = load_universe_history(date="2026-07-29")
            self.assertEqual(len(all_rows), 2)
            enabled_rows = load_universe_history(date="2026-07-29", only_enabled=True)
            self.assertEqual(len(enabled_rows), 1)
            self.assertEqual(enabled_rows[0]["symbol"], "AU0")
        os.remove(path)

    def test_panel_aggregation(self):
        path = _tmp_db()
        with patch("db._DB_PATH", path):
            save_universe_snapshot(_snap([_asset(symbol="AU0", score=70.0)]),
                                   date="2026-07-29")
            save_universe_snapshot(_snap([_asset(symbol="AU0", score=75.0)]),
                                   date="2026-07-30")
            panel = load_universe_panel(symbols=["AU0"])
            self.assertIn("AU0", panel)
            self.assertEqual(len(panel["AU0"]), 2)
            self.assertEqual(panel["AU0"][0]["date"], "2026-07-29")
            self.assertEqual(panel["AU0"][1]["score"], 75.0)
        os.remove(path)

    def test_empty_snapshot_skipped(self):
        path = _tmp_db()
        with patch("db._DB_PATH", path):
            res = save_universe_snapshot({"assets": []}, date="2026-07-29")
            self.assertEqual(res["saved"], 0)
            self.assertEqual(res["skipped"], 1)
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
