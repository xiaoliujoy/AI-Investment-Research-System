# -*- coding: utf-8 -*-
"""Phase 1.8-C 单元测试：统一资产宇宙快照（Asset Intelligence Universe Snapshot）。

DB-free：用固定 commodity / equity / cash 骨架构造混合 List[AssetIntelligence]，
验证 build_universe_snapshot 产出结构稳定、可序列化、作为 Phase 1.9 Dashboard 输入。

覆盖：
  - n_assets / asset_classes 正确
  - assets 按 score 降序
  - protocol_health 整体 PASS
  - 空输入降级不崩（n_assets=0，结构完整）
"""
import os
import sys
import unittest

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from asset_intelligence.protocol import AssetIntelligence
from asset_intelligence.universe import build_universe_snapshot


def _commodity(symbol, name, score, trend, state):
    return AssetIntelligence(
        asset_class="commodity", symbol=symbol, name=name,
        state=state, score=score, trend=trend,
        drivers=["宏观驱动"], risks=["技术回调"], confidence=0.8,
        detail={"category": "测试"},
    )


def _equity(can_buy, up_ratio, main_lines, sentiment_score):
    # 与 equity_engine.adapter.build_equity_signal 等价的最小构造（避开 brain/tree 依赖）
    from equity_engine.analysis import analyze_equity
    from equity_engine.adapter import _wrap  # 仅测试用
    return _wrap({
        "can_buy": can_buy, "direction": "", "up_ratio": up_ratio,
        "main_lines": main_lines, "sentiment_score": sentiment_score,
        "risk_state_label": "",
    })


class TestUniverseSnapshot(unittest.TestCase):
    def _build_mixed(self):
        comm = [
            _commodity("AU0", "沪金", 55.0, "down", "下行-避险"),
            _commodity("CU0", "沪铜", 63.0, "sideways", "震荡-周期"),
            _commodity("SC0", "原油", 54.0, "up", "上行-供给"),
        ]
        equity = _equity("YES", 0.62, [{"sector": "半导体", "stage": "主升"}], 68)
        cash = AssetIntelligence(
            asset_class="cash", symbol="CASH", name="现金", state="持有",
            score=50.0, trend="sideways",
            drivers=["环境变量决定，作为观望与流动性缓冲"],
            risks=["机会成本：踏空风险"], confidence=0.9,
            detail={"note": "现金为基准资产"},
        )
        return comm + [equity, cash]

    def test_structure_and_counts(self):
        assets = self._build_mixed()
        snap = build_universe_snapshot(assets)
        self.assertEqual(snap["n_assets"], 5)
        self.assertEqual(set(snap["asset_classes"]), {"commodity", "equity", "cash"})

    def test_sorted_descending_by_score(self):
        assets = self._build_mixed()
        snap = build_universe_snapshot(assets)
        scores = [a["score"] for a in snap["assets"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # 最高分应为 A股（IC=YES + 广度62% + 主线，约 73），最低为现金(50)
        self.assertEqual(snap["assets"][0]["symbol"], "CN_EQ_ALL")
        self.assertEqual(snap["assets"][-1]["symbol"], "CASH")

    def test_protocol_health_pass(self):
        assets = self._build_mixed()
        snap = build_universe_snapshot(assets)
        ph = snap["protocol_health"]
        self.assertEqual(ph["overall"], "PASS")
        self.assertEqual(ph["n_signals"], 5)
        for c in ph["checks"].values():
            self.assertTrue(c["ok"], f"协议检查未通过: {c}")

    def test_serializable_note_present(self):
        snap = build_universe_snapshot(self._build_mixed())
        self.assertIn("统一资产宇宙快照", snap["note"])
        self.assertIn("generated_at", snap)
        self.assertTrue(snap["assets"])
        # 每个资产都含 AIP 必备字段
        for a in snap["assets"]:
            for k in ("asset_class", "symbol", "name", "score", "trend", "state"):
                self.assertIn(k, a)

    def test_empty_input_safe(self):
        """空输入不崩，结构完整，n_assets=0。"""
        snap = build_universe_snapshot([])
        self.assertEqual(snap["n_assets"], 0)
        self.assertEqual(snap["assets"], [])
        self.assertEqual(snap["asset_classes"], [])
        self.assertIn("protocol_health", snap)
        self.assertIn("generated_at", snap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
