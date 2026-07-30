# -*- coding: utf-8 -*-
"""Phase 1.8-B 单元测试：A股 Adapter（analysis + adapter + 协议健康检查）。

DB-free：不触碰 commodity_factor_daily / 任何数据库，只验证：
  - analyze_equity 纯判断逻辑（状态/评分/趋势/驱动/风险/置信）
  - build_equity_signal 输出符合 AIP 六元组契约
  - 无交易建议泄漏（不产 position_pct / 买卖指令）
  - 与商品信号组合后的协议健康检查 PASS
"""
import os
import sys
import unittest

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from equity_engine.analysis import analyze_equity
from equity_engine.adapter import build_equity_signal
from asset_intelligence.protocol import AssetIntelligence
from asset_intelligence.validator import validate_and_clean, run_protocol_health

# AIP 标准字段（契约，见 docs/asset-intelligence-protocol.md）
_AIP_KEYS = {
    "asset_class", "symbol", "name", "state", "score", "trend",
    "drivers", "risks", "confidence", "detail", "confidence_label",
}

_BULLISH = {
    "can_buy": "YES", "direction": "多", "up_ratio": 0.62,
    "main_lines": [{"sector": "半导体", "stage": "主升"}],
    "sentiment_score": 68, "risk_state_label": "Risk On",
}
_BEARISH = {
    "can_buy": "NO", "direction": "", "up_ratio": 0.38,
    "main_lines": [], "sentiment_score": 42, "risk_state_label": "Risk Off",
}
_NEUTRAL = {
    "can_buy": "CAUTION", "direction": "", "up_ratio": 0.5,
    "main_lines": [], "sentiment_score": 50, "risk_state_label": "",
}


class TestAnalyzeEquity(unittest.TestCase):
    def test_bullish_recovery(self):
        r = analyze_equity(_BULLISH)
        self.assertEqual(r["state"], "趋势修复")
        self.assertGreater(r["score"], 0)
        self.assertLessEqual(r["score"], 100)
        self.assertEqual(r["trend"], "up")
        self.assertTrue(r["drivers"])
        self.assertTrue(r["risks"])
        self.assertGreater(r["confidence"], 0)
        self.assertLessEqual(r["confidence"], 1)

    def test_bearish_defense(self):
        r = analyze_equity(_BEARISH)
        self.assertEqual(r["trend"], "down")
        self.assertIn("偏弱", r["state"])
        self.assertTrue(r["drivers"])
        self.assertTrue(r["risks"])

    def test_unknown_fallback(self):
        r = analyze_equity({"can_buy": "UNKNOWN", "up_ratio": 0.5,
                            "main_lines": [], "sentiment_score": 50})
        self.assertEqual(r["state"], "信号待确认")
        self.assertAlmostEqual(r["confidence"], 0.30, places=4)
        # 没有主线时不应编造
        self.assertIn("缺乏清晰主线", r["risks"])

    def test_score_components_sane(self):
        # YES + 广度 62% + 主线 → 评分应高于纯中性
        bull = analyze_equity(_BULLISH)["score"]
        neut = analyze_equity(_NEUTRAL)["score"]
        self.assertGreater(bull, neut)


def _fake_brain_tree(params):
    brain = {"committee": {"can_buy": params["can_buy"], "direction": params.get("direction", "")},
             "results": {"sentiment": {"score": params.get("sentiment_score", 50)}}}
    tree = {"layers": {
        "sentiment": {"up_ratio": params["up_ratio"]},
        "L4_consensus": {"main_lines": params.get("main_lines", [])},
    }}
    return brain, tree


class TestBuildEquitySignal(unittest.TestCase):
    def test_schema_matches_aip(self):
        brain, tree = _fake_brain_tree(_BULLISH)
        sig = build_equity_signal(brain, tree)
        self.assertEqual(sig["asset_class"], "equity")
        self.assertEqual(sig["symbol"], "CN_A_SHARE")
        self.assertEqual(sig["name"], "A股")
        self.assertEqual(set(sig.keys()), _AIP_KEYS)

    def test_score_confidence_ranges(self):
        brain, tree = _fake_brain_tree(_BULLISH)
        sig = build_equity_signal(brain, tree)
        self.assertGreaterEqual(sig["score"], 0)
        self.assertLessEqual(sig["score"], 100)
        self.assertGreaterEqual(sig["confidence"], 0)
        self.assertLessEqual(sig["confidence"], 1)
        self.assertIn(sig["trend"], ("up", "down", "sideways"))

    def test_drivers_risks_nonempty(self):
        brain, tree = _fake_brain_tree(_NEUTRAL)
        sig = build_equity_signal(brain, tree)
        self.assertTrue(sig["drivers"], "drivers 不得为空")
        self.assertTrue(sig["risks"], "risks 不得为空")

    def test_no_trade_advice(self):
        """A股 adapter 绝不产出买卖指令 / 仓位建议（那是 IC/CIO 权责）。"""
        brain, tree = _fake_brain_tree(_BULLISH)
        sig = build_equity_signal(brain, tree)
        # 1) 不可含 position_pct 字段
        self.assertNotIn("position_pct", sig)
        self.assertNotIn("position_pct", sig.get("detail", {}))
        # 2) 驱动/风险/备注中不得出现买卖动作指令
        blob = " ".join(sig["drivers"] + sig["risks"] + [str(sig["detail"])])
        self.assertNotIn("买入", blob)
        self.assertNotIn("卖出", blob)
        self.assertNotIn("建仓", blob)
        # 3) 过校验应无致命 issue（drivers/risks 非空、范围合法）
        cleaned, issues = validate_and_clean(AssetIntelligence.from_dict(sig))
        self.assertTrue(cleaned["drivers"])
        self.assertTrue(cleaned["risks"])


class TestCombinedProtocolHealth(unittest.TestCase):
    def _fake_commodity(self, symbol, name, score, trend, state):
        return AssetIntelligence(
            asset_class="commodity", symbol=symbol, name=name,
            state=state, score=score, trend=trend,
            drivers=["宏观驱动"], risks=["技术回调"], confidence=0.8,
            detail={"category": "测试"},
        ).to_dict()

    def test_health_pass_with_equity(self):
        comm = [
            self._fake_commodity("AU0", "沪金", 55.0, "down", "下行-避险"),
            self._fake_commodity("CU0", "沪铜", 63.0, "sideways", "震荡-周期"),
        ]
        brain, tree = _fake_brain_tree(_BULLISH)
        equity = build_equity_signal(brain, tree)
        assets = comm + [equity]
        ph = run_protocol_health(assets)
        self.assertEqual(ph["overall"], "PASS")
        self.assertEqual(ph["n_signals"], 3)
        for c in ph["checks"].values():
            self.assertTrue(c["ok"], f"检查 {c} 未通过")


if __name__ == "__main__":
    unittest.main(verbosity=2)
