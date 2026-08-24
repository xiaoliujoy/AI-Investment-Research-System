"""
WeStock 口径映射修正 · 离线单测（不碰真实 DB）

验证 backend/ingest_sector_flow_westock.py 的口径修正：
  - 交叉验证主体从 concept.top 切换为 plate.top / plate.bottom（行业板块对齐行业板块）
  - concept 侧降级为噪音，不进入一致性判定分母
  - 对齐防护（align / mag_ratio / MISMATCH_RATIO_LIMIT）保留

用内存 SQLite + 构造数据，零外部依赖、零真实 DB 写入。
"""
import os
import sys
import sqlite3
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import ingest_sector_flow_westock as I  # noqa: E402


def _sample_data():
    """构造与真实 westock_fundflow JSON 同构的样例：plate 为行业板块、concept 为概念板块。"""
    return {
        "date": "2026-08-21",
        "plate": {
            "top": [
                {"code": "p1", "name": "通信设备", "zdf": 2.98, "zljlr": 889307.61, "zljlr_d5": -2036095.65, "zljlr_d20": -1090777.30},
                {"code": "p2", "name": "元件", "zdf": 2.80, "zljlr": 468428.18, "zljlr_d5": -2128220.82, "zljlr_d20": -515775.83},
            ],
            "bottom": [
                {"code": "p3", "name": "化学制药", "zdf": -4.33, "zljlr": -340516.95, "zljlr_d5": -486239.04, "zljlr_d20": -1116107.82},
            ],
        },
        "concept": {
            "top": [
                {"code": "c1", "name": "芯片概念", "zdf": 0.70, "zljlr": 1592216.19, "zljlr_d5": -10058964.63, "zljlr_d20": -7007973.98},
                {"code": "c2", "name": "TMT", "zdf": 0.44, "zljlr": 1641678.65, "zljlr_d5": -11709740.42, "zljlr_d20": -17101361.50},
            ],
            "bottom": [],
        },
    }


def _sector_daily_stub():
    """sector_daily 行业板块（与 plate 同口径，名字可直接对齐）。"""
    return {
        "通信设备": {"net": 85.0, "chg": 2.9, "amount": 1600.0, "leader": "星网锐捷"},
        "元件": {"net": 42.0, "chg": 2.7, "amount": 970.0, "leader": "江海股份"},
        "化学制药": {"net": -30.0, "chg": -4.2, "amount": 680.0, "leader": "北陆药业"},
        "半导体": {"net": 36.0, "chg": 1.5, "amount": 800.0, "leader": "中芯国际"},
    }


class TestWeStockCrossCheck(unittest.TestCase):

    def _build_conn_with_data(self):
        conn = sqlite3.connect(":memory:")
        I.ensure_table(conn)
        data = _sample_data()
        I.ingest(conn, data)  # 写 plate + concept 两源 top/bottom 到 sector_flow_westock
        return conn, data

    def test_plate_top_aligns_consistent(self):
        """plate.top 行业板块（通信设备/元件）应与 sector_daily 对齐，判定 consistent。"""
        conn, data = self._build_conn_with_data()
        sdict = _sector_daily_stub()
        cross = I.build_cross_check(conn, data, sdict)
        self.assertEqual(cross["consistency"], "consistent",
                         "plate 行业板块同向应判 consistent，不应恒 unaligned")
        # aligned 应包含通信设备、元件（plate.top 两条）
        aligned_names = {a["w_name"] for a in cross["aligned"]}
        self.assertIn("通信设备", aligned_names)
        self.assertIn("元件", aligned_names)
        # plate.bottom 化学制药 净流出对齐 sector_daily 化学制药 净流出 -> 同向
        self.assertIn("化学制药", aligned_names)

    def test_concept_not_in_denominator(self):
        """concept 侧（芯片概念/TMT）不进入 aligned / consistency 判定。"""
        conn, data = self._build_conn_with_data()
        sdict = _sector_daily_stub()
        cross = I.build_cross_check(conn, data, sdict)
        aligned_names = {a["w_name"] for a in cross["aligned"]}
        self.assertNotIn("芯片概念", aligned_names)
        self.assertNotIn("TMT", aligned_names)
        # concept 侧备注存在
        self.assertIn("concept_side_note", cross)
        self.assertIn("噪音", cross["concept_side_note"])

    def test_no_baseline_when_sdict_empty(self):
        """sector_daily 无数据 → no_baseline（不是 unaligned，更不是 divergent）。"""
        conn, data = self._build_conn_with_data()
        cross = I.build_cross_check(conn, data, {})
        self.assertEqual(cross["consistency"], "no_baseline")

    def test_unaligned_only_when_plate_truly_miss(self):
        """sector_daily 有数据但 plate 完全对不上 → unaligned（不是因为 concept 不可比）。"""
        conn, data = self._build_conn_with_data()
        sdict = {"新能源": {"net": 50.0, "chg": 1.0, "amount": 900.0, "leader": "X"},
                 "光伏": {"net": -20.0, "chg": -1.0, "amount": 500.0, "leader": "Y"}}
        cross = I.build_cross_check(conn, data, sdict)
        self.assertEqual(cross["consistency"], "unaligned")

    def test_compare_report_plate_is_main(self):
        """compare_report 主口径为 plate 侧，concept 折叠为噪音参考且不污染未对齐。"""
        conn, data = self._build_conn_with_data()
        sdict = _sector_daily_stub()
        report = I.compare_report(data, sdict)
        self.assertIn("plate 侧（行业板块，口径可比，主看这一栏）", report)
        self.assertIn("概念板块（噪音参考，不参与交叉验证）", report)
        self.assertIn("通信设备", report)
        # 概念板块（芯片概念/TMT）在噪音小节，不在"未对齐"小节
        self.assertIn("芯片概念", report)
        # 未对齐小节不应出现概念板块（概念不尝试对齐，不污染未对齐清单）
        unmatched_section = report.split("## 未对齐")[1] if "## 未对齐" in report else ""
        self.assertNotIn("芯片概念", unmatched_section)
        self.assertNotIn("TMT", unmatched_section)


if __name__ == "__main__":
    unittest.main(verbosity=2)
