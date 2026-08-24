"""
H1 数据采集增强 · 离线单测（不触网）

验证 quant-lab/h1_universe_structure.py 中 fetch_daily 的增强逻辑：
  - 主源（东财）失败 → 指数级退避重试
  - 主源全失败 → 新浪备用源降级（标记 suspect）
  - 除权因子错位 → anomaly 标记（不绕过 Gate 1）
  - 正常数据 → 无误伤

通过 mock sys.modules['akshare'] 注入，不发起任何真实网络请求。
"""
import os
import sys
import types
import unittest
from unittest import mock

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
QLAB = os.path.dirname(HERE)
if QLAB not in sys.path:
    sys.path.insert(0, QLAB)

import h1_universe_structure as H  # noqa: E402


def _make_df(n: int = 100, start: str = "2015-01-01",
             noise: float = 0.01, div_jump: bool = False,
             sina: bool = False) -> pd.DataFrame:
    """构造近似正常的日线 DF。sina=True 用新浪列名。"""
    idx = pd.bdate_range(start, periods=n)
    closes = [10.0]
    for i in range(1, n):
        closes.append(round(closes[-1] * (1 + noise), 2))
    if div_jump:
        closes[50] = round(closes[49] * 0.6, 2)  # >30% 向下跳变
    dates = [d.strftime("%Y-%m-%d") for d in idx]
    vol = [1_000_000] * n
    if div_jump:
        vol[50] = 5_000_000
    if sina:
        return pd.DataFrame({
            "date": dates, "open": closes, "close": closes,
            "high": closes, "low": closes, "volume": vol, "pct_chg": [0.0] * n,
        })
    return pd.DataFrame({
        "日期": dates, "开盘": closes, "收盘": closes, "最高": closes,
        "最低": closes, "成交量": vol,
        "涨跌幅": [0.0] + [round((closes[i] / closes[i - 1] - 1) * 100, 2) for i in range(1, n)],
    })


class FakeAk:
    def __init__(self, em_se=None, em_ret=None, sina_ret=None, sina_se=None):
        self._em_se = em_se
        self._em_ret = em_ret
        self._sina_ret = sina_ret
        self._sina_se = sina_se
        self.em_calls = 0
        self.sina_calls = 0

    def stock_zh_a_hist(self, **kwargs):
        self.em_calls += 1
        if self._em_se is not None:
            # em_se(calls) 返回异常实例则 raise；返回 None 表示本次不抛（正常返回 em_ret）
            r = self._em_se(self.em_calls) if callable(self._em_se) else self._em_se
            if r is not None:
                raise r
        return self._em_ret

    def stock_zh_a_daily(self, **kwargs):
        self.sina_calls += 1
        if self._sina_se is not None:
            r = self._sina_se(self.sina_calls) if callable(self._sina_se) else self._sina_se
            if r is not None:
                raise r
        return self._sina_ret


class TestFetchResilience(unittest.TestCase):

    def _run(self, fake: FakeAk, code: str = "600000", tencent_fail: bool = False):
        # 同时 mock 腾讯主源，避免沙箱真实网络干扰
        if tencent_fail:
            class FailResp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"code": 0, "msg": "param error", "data": []}

            tencent_patch = mock.patch("requests.get", return_value=FailResp())
        else:
            tencent_rows = [
                ["2026-08-19", "10.00", "10.20", "10.30", "9.90", "1000000.0"],
                ["2026-08-20", "10.20", "10.10", "10.25", "10.05", "900000.0"],
                ["2026-08-21", "10.10", "10.50", "10.60", "10.08", "1100000.0"],
            ]
            prefix = H._tencent_market_prefix(code)
            tencent_json = {"code": 0, "msg": "", "data": {prefix: {"qfqday": tencent_rows}}}

            class OkResp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return tencent_json

            tencent_patch = mock.patch("requests.get", return_value=OkResp())
        with tencent_patch:
            with mock.patch.dict(sys.modules, {"akshare": fake}):
                return H.fetch_daily(code)

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return tencent_json

        with mock.patch.dict(sys.modules, {"akshare": fake}):
            with mock.patch("requests.get", return_value=FakeResp()):
                return H.fetch_daily(code)

    def test_primary_tencent_success(self):
        """腾讯主源 mock 成功 → 返回 DF，无 anomaly，不降级（东财不被调用，新浪做交叉校验）。"""
        fake = FakeAk(em_ret=_make_df(), sina_ret=_make_df())
        res = self._run(fake)
        self.assertIsNotNone(res)
        self.assertEqual(fake.em_calls, 0)  # 主源成功不触东财降级
        self.assertGreater(fake.sina_calls, 0)  # 主源成功仍拉新浪做交叉校验
        self.assertFalse(res["anomaly"].any())

    def test_primary_fail_fallback_sina(self):
        """腾讯主源失败 → 东财也失败 → 新浪降级，anomaly 全 True（suspect）。"""
        fake = FakeAk(em_se=RuntimeError("dead"),
                      sina_ret=_make_df(sina=True))
        res = self._run(fake, tencent_fail=True)
        self.assertIsNotNone(res)
        self.assertGreater(fake.sina_calls, 0)
        self.assertTrue(res["anomaly"].any())

    def test_divjump_marks_anomaly(self):
        """除权因子错位（>30% 跳变+放量）→ 第 50 日 anomaly 标记（腾讯失败、东财降级返回含跳变数据）。"""
        fake = FakeAk(em_ret=_make_df(div_jump=True), sina_ret=None)
        res = self._run(fake, tencent_fail=True)
        self.assertIsNotNone(res)
        self.assertTrue(bool(res["anomaly"].iloc[50]))
        self.assertGreater(int(res["anomaly"].sum()), 0)

    def test_normal_no_anomaly(self):
        """完全正常数据 → 无 anomaly，关键列齐全。"""
        fake = FakeAk(em_ret=_make_df(), sina_ret=_make_df())
        res = self._run(fake)
        self.assertIsNotNone(res)
        self.assertFalse(res["anomaly"].any())
        for col in ("suspend", "limit_up", "limit_down"):
            self.assertIn(col, res.columns)


class TestTencentPrimarySource(unittest.TestCase):
    """腾讯原生接口作为主源的解析与降级逻辑（不触网，mock requests.get）。"""

    def _tencent_json(self, rows, code="000001"):
        prefix = H._tencent_market_prefix(code)
        return {"code": 0, "msg": "", "data": {prefix: {"qfqday": rows}}}

    def _run_with_tencent(self, fake_json, code="000001"):
        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return fake_json

        with mock.patch("requests.get", return_value=FakeResp()):
            return H._tencent_fetch(None, code)

    def test_tencent_parse_reorder(self):
        """腾讯 [open,close,high,low,volume] → 重排为 [open,high,low,close,volume]。"""
        rows = [
            ["2026-08-19", "10.00", "10.20", "10.30", "9.90", "1000000.0"],
            ["2026-08-20", "10.20", "10.10", "10.25", "10.05", "900000.0"],
            ["2026-08-21", "10.10", "10.50", "10.60", "10.08", "1100000.0"],
        ]
        df = self._run_with_tencent(self._tencent_json(rows))
        self.assertIsNotNone(df)
        self.assertEqual(list(df.columns),
                         ["date", "open", "high", "low", "close", "volume", "pct_chg"])
        self.assertAlmostEqual(df["high"].iloc[0], 10.30, places=4)
        self.assertAlmostEqual(df["low"].iloc[0], 9.90, places=4)
        self.assertAlmostEqual(df["close"].iloc[0], 10.20, places=4)
        self.assertAlmostEqual(df["pct_chg"].iloc[-1], 3.96, places=2)

    def test_tencent_segmented_concat(self):
        """分段请求：每段返回部分数据，拼接后去重排序完整。"""
        rows_a = [["2024-01-02", "10.0", "10.2", "10.3", "9.9", "1000.0"],
                  ["2024-01-03", "10.2", "10.1", "10.25", "10.05", "900.0"]]
        rows_b = [["2026-08-20", "10.1", "10.5", "10.6", "10.08", "1100.0"],
                  ["2026-08-21", "10.5", "10.8", "10.9", "10.4", "1200.0"]]
        # 模拟两次请求：第一次返回 rows_a，第二次返回 rows_b
        calls = {"n": 0}
        prefix = H._tencent_market_prefix("000001")

        class SegResp:
            def raise_for_status(self):
                pass

            def json(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    return {"code": 0, "msg": "", "data": {prefix: {"qfqday": rows_a}}}
                return {"code": 0, "msg": "", "data": {prefix: {"qfqday": rows_b}}}

        with mock.patch("requests.get", return_value=SegResp()):
            df = H._tencent_fetch(None, "000001")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 4)
        self.assertEqual(str(df["date"].iloc[0]), "2024-01-02")
        self.assertEqual(str(df["date"].iloc[-1]), "2026-08-21")

    def test_tencent_prefix_sh(self):
        """6 开头代码 → sh 前缀；返回 sh600000 节点需匹配。"""
        rows = [["2026-08-21", "5.00", "5.10", "5.20", "4.90", "500000.0"]]
        fake = self._tencent_json(rows, code="600000")
        df = self._run_with_tencent(fake, code="600000")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)

    def test_tencent_empty_returns_none(self):
        """腾讯所有段均 param error（空 data）→ None，触发降级。"""
        fake = {"code": 0, "msg": "param error", "data": []}
        df = self._run_with_tencent(fake)
        self.assertIsNone(df)


if __name__ == "__main__":
    unittest.main(verbosity=2)
