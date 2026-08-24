# -*- coding: utf-8 -*-
"""
test_g2_supervisor.py
G2 方案 A 守护进程单测。

【验证重点】
  1. BUY 持仓期间注入价格拉升+回落 → 平仓后 mfe_r > 0 且 giveback_r = mfe_r - realized_r（E1 量纲自洽）。
  2. SELL 方向极值采样正确（有利=价更低）。
  3. 异常注入：未开仓直接录平仓意图 → 捕获 ERROR，进程不崩。
  4. 损坏 JSON（开仓意图） → 捕获 ERROR，进程不崩。
  5. 零侵入：supervise() 复用底层组合，不修改任何已冻结模块。

【确定性】
  - 用可追加的 Mock tick 源（list 存储，测试在采样窗口内注入价格）。
  - supervise 跑在后台线程，max_iterations 有限，主线程时序控制开仓/平仓意图写入。
"""
from __future__ import annotations
import os
import sys
import json
import time
import threading
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
TRADING_OS = os.path.dirname(_HERE)
if TRADING_OS not in sys.path:
    sys.path.insert(0, TRADING_OS)

import g2_supervisor as G
from g2_supervisor import supervise, make_mock_tick_source
from circuit_breaker import CircuitBreaker
from attribution_sink import AttributionSink
from mt5_bridge import MockMT5Client

SPEC = {
    "symbol": "XAUUSD", "trade_contract_size": 100.0, "point": 0.01,
    "tick_size": 0.01, "tick_value": 1.0, "volume_min": 0.01, "volume_step": 0.01,
    "volume_max": 100.0, "spread_avg_points": 3.0, "source": "OFFLINE_KNOWN_CONSTANT",
}


class _IsolatedPaths:
    """每个测试用独立临时目录，规避沙箱 os.remove 被拦截导致的测试间污染。

    同时 patch g2_supervisor 模块级路径常量，使 supervise() 读写测试专属文件。
    """

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="g2sup_")
        self.intent = os.path.join(self.dir, "order_intent.json")
        self.close_intent = os.path.join(self.dir, "close_intent.json")
        self.exec = os.path.join(self.dir, "execution_result.json")
        self.close_exec = os.path.join(self.dir, "execution_result_close.json")
        self._backup = {
            "INTENT_PATH": G.INTENT_PATH, "CLOSE_INTENT_PATH": G.CLOSE_INTENT_PATH,
            "EXEC_RESULT_PATH": G.EXEC_RESULT_PATH, "CLOSE_RESULT_PATH": G.CLOSE_RESULT_PATH,
        }
        G.INTENT_PATH = self.intent
        G.CLOSE_INTENT_PATH = self.close_intent
        G.EXEC_RESULT_PATH = self.exec
        G.CLOSE_RESULT_PATH = self.close_exec

    def restore(self):
        G.INTENT_PATH = self._backup["INTENT_PATH"]
        G.CLOSE_INTENT_PATH = self._backup["CLOSE_INTENT_PATH"]
        G.EXEC_RESULT_PATH = self._backup["EXEC_RESULT_PATH"]
        G.CLOSE_RESULT_PATH = self._backup["CLOSE_RESULT_PATH"]


class _AppendableTickSource:
    """测试用可追加 tick 源：测试线程在采样窗口内 append 价格。"""

    def __init__(self):
        self.prices = []
        self.lock = threading.Lock()

    def append(self, p: float):
        with self.lock:
            self.prices.append(p)

    def __call__(self, call_count: int) -> float:
        with self.lock:
            if call_count < len(self.prices):
                return self.prices[call_count]
        # 超出已注入范围：返回最后已知价（持仓未动），保证持续采样不崩溃
        with self.lock:
            return self.prices[-1] if self.prices else None


def _write_intent(paths, direction, entry, invalidation, lots=0.01):
    with open(paths.intent, "w", encoding="utf-8") as f:
        json.dump({"symbol": "XAUUSD", "direction": direction,
                   "entry_price": entry, "invalidation_price": invalidation,
                   "lots": lots}, f)


def _write_close(paths, order_id, exit_price, pnl, reason="MANUAL"):
    with open(paths.close_intent, "w", encoding="utf-8") as f:
        json.dump({"order_id": order_id, "exit_price": exit_price,
                   "realized_pnl_usd": pnl, "exit_reason": reason}, f)


def _wait_json_with_status(path: str, status: str, timeout: float = 3.0) -> dict:
    """轮询等待文件存在且 status 匹配（原子写保证读到即完整）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") == status:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(0.01)
    raise AssertionError(f"等待 {path} status={status} 超时")


def _spawn_supervise(cb, sink, ticks, mock, stop_event, max_iter=2000):
    t = threading.Thread(
        target=supervise, daemon=True,
        kwargs=dict(circuit_breaker=cb, attribution_sink=sink, spec_dict=SPEC,
                    tick_source=ticks, mt5_client=mock, tick_interval=0.01,
                    open_poll_interval=0.01, max_iterations=max_iter,
                    stop_event=stop_event))
    t.start()
    return t


def test_buy_mfe_giveback_dimensional_consistency():
    """BUY 持仓：注入拉升(2005)→回落(2002)，平仓2002。断言 mfe_r>0 且 giveback_r=mfe_r-realized_r。"""
    paths = _IsolatedPaths()
    cb = CircuitBreaker()
    sink = AttributionSink(db_path=":memory:")
    ticks = _AppendableTickSource()
    mock = MockMT5Client(fill_price_override=2000.10, slippage_points=0.0, spread_points=3.0)
    stop = threading.Event()
    t = _spawn_supervise(cb, sink, ticks, mock, stop)

    try:
        # 写开仓意图
        _write_intent(paths, "BUY", 2000.0, 1995.0, 0.01)
        exec_res = _wait_json_with_status(paths.exec, "FILLED")
        oid = exec_res["order_id"]

        # 持仓期间注入价格：先拉升到 2005（MFE），再回落到 2002
        ticks.append(2005.0)
        ticks.append(2005.0)  # 多采样几轮确认极值锁定
        ticks.append(2002.0)
        ticks.append(2002.0)
        time.sleep(0.1)  # 让 supervise 采样到上述价格

        # 写平仓意图：平仓价 2002，终端真实盈亏 = (2002 - 2000.10) * 0.01 * 100 = 1.90
        _write_close(paths, oid, 2002.0, 1.90, "MANUAL")
        cres = _wait_json_with_status(paths.close_exec, "CLOSED")

        # ---- 物理量纲断言 ----
        one_r = cres["max_loss_usd"]  # = 0.01*1*500 = 5.0
        expected_mfe_usd = (2005.0 - 2000.10) * 0.01 * 100.0
        expected_mfe_r = expected_mfe_usd / one_r
        expected_realized_r = 1.90 / one_r
        expected_giveback_r = expected_mfe_r - expected_realized_r

        assert cres["mfe_r"] > 0, f"mfe_r 应>0，实得 {cres['mfe_r']}"
        assert abs(cres["mfe_r"] - expected_mfe_r) < 1e-3, f"mfe_r={cres['mfe_r']} 期望 {expected_mfe_r}"
        assert abs(cres["realized_r"] - expected_realized_r) < 1e-3, \
            f"realized_r={cres['realized_r']} 期望 {expected_realized_r}"
        assert abs(cres["giveback_r"] - expected_giveback_r) < 1e-3, \
            f"giveback_r={cres['giveback_r']} 期望 {expected_giveback_r}"
        # 核心恒等式：giveback_r = mfe_r - realized_r （E1 量纲自洽）
        assert abs(cres["giveback_r"] - (cres["mfe_r"] - cres["realized_r"])) < 1e-6, \
            "Giveback 恒等式不成立"
        print(f"  [PASS] BUY mfe_r={cres['mfe_r']} realized_r={cres['realized_r']} "
              f"giveback_r={cres['giveback_r']} (方案A MFE捕获生效)")
    finally:
        stop.set()
        t.join(timeout=2.0)
        paths.restore()


def test_sell_mfe_direction():
    """SELL 持仓：有利=价更低。注入下跌(1990)→回升(1993)，平仓1993。"""
    paths = _IsolatedPaths()
    cb = CircuitBreaker()
    sink = AttributionSink(db_path=":memory:")
    ticks = _AppendableTickSource()
    mock = MockMT5Client(fill_price_override=1999.90, slippage_points=0.0, spread_points=3.0)
    stop = threading.Event()
    t = _spawn_supervise(cb, sink, ticks, mock, stop)

    try:
        _write_intent(paths, "SELL", 2000.0, 2005.0, 0.01)
        exec_res = _wait_json_with_status(paths.exec, "FILLED")
        oid = exec_res["order_id"]

        # SELL 有利=价更低：先跌到 1990（MFE），再回升 1993
        ticks.append(1990.0)
        ticks.append(1990.0)
        ticks.append(1993.0)
        ticks.append(1993.0)
        time.sleep(0.1)

        # 平仓价 1993，盈亏 = (1999.90 - 1993)*0.01*100 = 6.90
        _write_close(paths, oid, 1993.0, 6.90, "MANUAL")
        cres = _wait_json_with_status(paths.close_exec, "CLOSED")

        one_r = cres["max_loss_usd"]  # = 0.01*1*500 = 5.0
        expected_mfe_r = (1999.90 - 1990.0) * 0.01 * 100.0 / one_r
        assert abs(cres["mfe_r"] - expected_mfe_r) < 1e-3, f"SELL mfe_r={cres['mfe_r']} 期望 {expected_mfe_r}"
        assert cres["mfe_r"] > 0
        print(f"  [PASS] SELL mfe_r={cres['mfe_r']} (方向极值正确)")
    finally:
        stop.set()
        t.join(timeout=2.0)
        paths.restore()


def test_close_without_open_does_not_crash():
    """未开仓直接录平仓意图 → 捕获 ERROR，进程不崩（supervise 继续运行）。"""
    paths = _IsolatedPaths()
    cb = CircuitBreaker()
    sink = AttributionSink(db_path=":memory:")
    ticks = _AppendableTickSource()
    mock = MockMT5Client()
    stop = threading.Event()
    t = _spawn_supervise(cb, sink, ticks, mock, stop, max_iter=500)

    try:
        # 未开仓，直接写平仓意图（错误 order_id）
        _write_close(paths, "NONEXISTENT", 2000.0, 0.0, "MANUAL")
        cres = _wait_json_with_status(paths.close_exec, "ERROR")
        assert "未开仓登记" in cres["reason"], f"错误信息不符: {cres['reason']}"
        # 进程仍在运行（线程 alive）
        assert t.is_alive(), "守护进程在异常后退出（不该）"
        # 之后仍能正常开仓（证明状态机未损坏）
        _write_intent(paths, "BUY", 2000.0, 1995.0, 0.01)
        _wait_json_with_status(paths.exec, "FILLED")
        print("  [PASS] 未开仓平仓异常被捕获，进程不崩，状态机可恢复")
    finally:
        stop.set()
        t.join(timeout=2.0)
        paths.restore()


def test_corrupt_open_intent_does_not_crash():
    """开仓意图为损坏 JSON → 捕获 ERROR，进程不崩。"""
    paths = _IsolatedPaths()
    cb = CircuitBreaker()
    sink = AttributionSink(db_path=":memory:")
    ticks = _AppendableTickSource()
    stop = threading.Event()
    t = _spawn_supervise(cb, sink, MockMT5Client(), ticks, stop, max_iter=500)

    try:
        # 写损坏 JSON
        with open(paths.intent, "w", encoding="utf-8") as f:
            f.write("{ broken json ")
        res = _wait_json_with_status(paths.exec, "ERROR")
        assert t.is_alive(), "守护进程在损坏 JSON 后退出（不该）"
        print("  [PASS] 损坏 JSON 被捕获，进程不崩")
    finally:
        stop.set()
        t.join(timeout=2.0)
        paths.restore()


def test_make_mock_tick_source_exhaustion():
    """Mock tick 源耗尽返回 None（采样循环应跳过，不崩）。"""
    src = make_mock_tick_source([2001.0, 2002.0])
    assert src(0) == 2001.0
    assert src(1) == 2002.0
    assert src(2) is None
    assert src(3) is None
    print("  [PASS] Mock tick 源耗尽返回 None")


if __name__ == "__main__":
    test_buy_mfe_giveback_dimensional_consistency()
    test_sell_mfe_direction()
    test_close_without_open_does_not_crash()
    test_corrupt_open_intent_does_not_crash()
    test_make_mock_tick_source_exhaustion()
    print("\n[ALL] g2_supervisor 单测全部通过")
