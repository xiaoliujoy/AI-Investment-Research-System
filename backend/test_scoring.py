"""评分引擎单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scoring_engine import (
    calc_market_score,
    calc_sector_score,
    calc_leader_score,
    score_all,
    score_from_thresholds,
    score_from_range,
    weighted_score,
    load_config,
    OUTPUT_DIR,
)


class TestConfig(unittest.TestCase):
    """测试配置加载。"""
    
    def test_config_loaded(self):
        cfg = load_config()
        self.assertIn("market_score", cfg)
        self.assertIn("sector_score", cfg)
        self.assertIn("leader_score", cfg)
    
    def test_market_weights_sum(self):
        cfg = load_config()
        weights = cfg["market_score"]["weights"]
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=2)
    
    def test_sector_weights_sum(self):
        cfg = load_config()
        weights = cfg["sector_score"]["weights"]
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=2)
    
    def test_leader_weights_sum(self):
        cfg = load_config()
        weights = cfg["leader_score"]["weights"]
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=2)


class TestScoreFromThresholds(unittest.TestCase):
    """测试阈值评分函数。"""
    
    def test_basic(self):
        thresholds = [
            {"threshold": 90, "score": 100},
            {"threshold": 80, "score": 80},
            {"threshold": 70, "score": 60},
            {"threshold": 60, "score": 40},
            {"threshold": 0, "score": 20},
        ]
        self.assertEqual(score_from_thresholds(95, thresholds), 100)
        self.assertEqual(score_from_thresholds(85, thresholds), 80)
        self.assertEqual(score_from_thresholds(75, thresholds), 60)
        self.assertEqual(score_from_thresholds(65, thresholds), 40)
        self.assertEqual(score_from_thresholds(50, thresholds), 20)
    
    def test_none_value(self):
        thresholds = [{"threshold": 0, "score": 50}]
        self.assertEqual(score_from_thresholds(None, thresholds), 0)


class TestScoreFromRange(unittest.TestCase):
    """测试范围评分函数。"""
    
    def test_linear(self):
        self.assertAlmostEqual(score_from_range(50, 0, 100), 50)
        self.assertAlmostEqual(score_from_range(0, 0, 100), 0)
        self.assertAlmostEqual(score_from_range(100, 0, 100), 100)
    
    def test_clamp(self):
        self.assertAlmostEqual(score_from_range(-10, 0, 100), 0)
        self.assertAlmostEqual(score_from_range(110, 0, 100), 100)


class TestWeightedScore(unittest.TestCase):
    """测试加权求和。"""
    
    def test_basic(self):
        factors = {"a": 80, "b": 60}
        weights = {"a": 0.6, "b": 0.4}
        self.assertAlmostEqual(weighted_score(factors, weights), 72)


class TestMarketScore(unittest.TestCase):
    """测试市场评分。"""
    
    def test_high_score(self):
        data = {
            "total_amount": 35000, "amount_change_rate": 0.20,
            "up_count": 3500, "down_count": 1500,
            "zt_count": 100, "dt_count": 5,
            "seal_rate": 0.80, "break_rate": 0.20,
            "max_boards": 8, "lianban_count": 15,
            "promotion_rate": 0.60, "active_ratio": 0.60,
            "yesterday_zt_avg_pct": 4.0, "yesterday_zt_win_rate": 0.75,
            "concentration": 0.20,
        }
        result = calc_market_score(data)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertIn(result["stage"], ["启动期", "发酵期", "加速期", "高潮期", "分歧期", "修复期", "退潮期"])
    
    def test_low_score(self):
        data = {
            "total_amount": 8000, "amount_change_rate": -0.20,
            "up_count": 1000, "down_count": 4000,
            "zt_count": 10, "dt_count": 50,
            "seal_rate": 0.30, "break_rate": 0.70,
            "max_boards": 1, "lianban_count": 1,
            "promotion_rate": 0.10, "active_ratio": 0.15,
            "yesterday_zt_avg_pct": -3.0, "yesterday_zt_win_rate": 0.30,
            "concentration": 0.10,
        }
        result = calc_market_score(data)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertEqual(result["stage"], "退潮期")
    
    def test_factors_present(self):
        data = {"total_amount": 20000, "up_count": 2000, "down_count": 3000}
        result = calc_market_score(data)
        self.assertIn("factors", result)
        self.assertIn("amount_factor", result["factors"])
        self.assertIn("profit_factor", result["factors"])


class TestSectorScore(unittest.TestCase):
    """测试板块评分。"""
    
    def test_hot_sector(self):
        data = {
            "name": "半导体",
            "amount": 400, "amount_ratio": 0.08,
            "amount_change_rate": 0.30, "change_pct": 6.0,
            "up_count": 150, "down_count": 30,
            "zt_count": 15, "total_firms": 180,
            "leader_pct": 10.0, "leader_turnover": 300,
            "leader_board": 4, "leader_rps": 85,
            "days_in_top10": 5, "consecutive_days": 4,
        }
        result = calc_sector_score(data)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertIn(result["tier"], ["T0", "T1", "T2", "T3", "T4"])
    
    def test_cold_sector(self):
        data = {
            "name": "银行",
            "amount": 20, "amount_ratio": 0.003,
            "amount_change_rate": -0.10, "change_pct": -0.5,
            "up_count": 5, "down_count": 30,
            "zt_count": 0, "total_firms": 40,
            "leader_pct": -1.0, "leader_turnover": 5,
            "leader_board": 0, "leader_rps": 30,
            "days_in_top10": 0, "consecutive_days": 0,
        }
        result = calc_sector_score(data)
        self.assertLess(result["score"], 50)
        self.assertEqual(result["tier"], "T4")


class TestLeaderScore(unittest.TestCase):
    """测试龙头评分。"""
    
    def test_filter_reject(self):
        # 不通过过滤（成交额太小）
        data = {
            "code": "000001", "name": "平安银行",
            "sector": "银行",
            "amount": 5e8,  # 5亿，不够10亿
            "turnover_rate": 0.03,
        }
        result = calc_leader_score(data, 75)
        self.assertIsNone(result)
    
    def test_pass_filter(self):
        data = {
            "code": "603986", "name": "兆易创新",
            "sector": "半导体",
            "amount": 380e8,
            "turnover_rate": 0.088,
            "change_pct": 10.0,
            "board_height": 3,
            "mcap": 4656,
            "amount_rank": 2,
            "sector_rank": 1,
            "rps_20": 85,
            "rps_60": 80,
            "is_first_board": False,
            "is_open_height": False,
            "percentile": 0.95,
            "lhm_net_buy": 50000000,
            "follower_count": 5,
            "sector_amount": 397e8,
        }
        result = calc_leader_score(data, 75)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertIn(result["category"], ["绝对龙头", "核心龙头", "趋势龙头", "次龙", "跟风"])


class TestScoreAll(unittest.TestCase):
    """测试全量评分。"""
    
    def test_full_pipeline(self):
        market_data = {
            "total_amount": 29137, "amount_change_rate": 0.10,
            "up_count": 2500, "down_count": 2400,
            "zt_count": 75, "dt_count": 12,
            "seal_rate": 0.68, "break_rate": 0.32,
            "max_boards": 6, "lianban_count": 10,
            "promotion_rate": 0.50, "active_ratio": 0.40,
            "yesterday_zt_avg_pct": 3.0, "yesterday_zt_win_rate": 0.70,
            "concentration": 0.18,
        }
        sectors_data = [
            {"name": "半导体", "amount": 397, "amount_ratio": 0.06, "amount_change_rate": 0.25,
             "change_pct": 6.5, "up_count": 150, "down_count": 31, "zt_count": 12, "total_firms": 181,
             "leader_pct": 10.0, "leader_turnover": 380, "leader_board": 3, "leader_rps": 85,
             "days_in_top10": 5, "consecutive_days": 4},
        ]
        leaders_data = [
            {"code": "603986", "name": "兆易创新", "sector": "半导体",
             "amount": 380e8, "turnover_rate": 0.088, "change_pct": 10.0,
             "board_height": 3, "mcap": 4656, "amount_rank": 2, "sector_rank": 1,
             "rps_20": 85, "rps_60": 80, "is_first_board": False, "is_open_height": False,
             "percentile": 0.95, "lhm_net_buy": 50000000, "follower_count": 5,
             "sector_amount": 397e8},
        ]
        
        result = score_all(market_data, sectors_data, leaders_data)
        
        self.assertIn("market_score", result)
        self.assertIn("sector_scores", result)
        self.assertIn("leader_scores", result)
        self.assertIn("timestamp", result)
        
        self.assertEqual(len(result["sector_scores"]), 1)
        self.assertTrue(len(result["leader_scores"]) >= 0)


class TestSaveScores(unittest.TestCase):
    """测试评分保存。"""
    
    def test_save(self):
        import tempfile
        import shutil
        import json
        
        temp_dir = Path(tempfile.mkdtemp())
        
        output = {
            "market_score": {"score": 75, "stage": "加速期"},
            "sector_scores": [{"name": "半导体", "score": 85}],
            "leader_scores": [{"code": "603986", "score": 80}],
            "timestamp": "2026-07-09 12:00:00",
        }
        
        from scoring_engine import save_scores
        paths = save_scores(output, temp_dir)
        
        self.assertTrue(Path(paths["market_score"]).exists())
        self.assertTrue(Path(paths["sector_scores"]).exists())
        self.assertTrue(Path(paths["leader_scores"]).exists())
        
        with open(paths["market_score"], "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["score"], 75)
        
        shutil.rmtree(temp_dir)


def run_tests():
    """运行所有测试。"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestScoreFromThresholds))
    suite.addTests(loader.loadTestsFromTestCase(TestScoreFromRange))
    suite.addTests(loader.loadTestsFromTestCase(TestWeightedScore))
    suite.addTests(loader.loadTestsFromTestCase(TestMarketScore))
    suite.addTests(loader.loadTestsFromTestCase(TestSectorScore))
    suite.addTests(loader.loadTestsFromTestCase(TestLeaderScore))
    suite.addTests(loader.loadTestsFromTestCase(TestScoreAll))
    suite.addTests(loader.loadTestsFromTestCase(TestSaveScores))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
