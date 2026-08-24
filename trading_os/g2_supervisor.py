# -*- coding: utf-8 -*-
"""
g2_supervisor.py
G2 阶段 —— 单进程执行守护（方案 A：统管开仓监听 + Tick 采样 + 平仓结算）

【定位】
  纯上层编排器。零侵入复用已冻结且 100% 覆盖的：
    - risk_calculator.compute_risk_plan   (G1 反推手数 + 硬门禁)
    - circuit_breaker.CircuitBreaker      (G1 状态机 + 前置门禁)
    - attribution_sink.AttributionSink    (G2 开仓登记 + sample_tick + close_position 落库)
    - mt5_bridge.process_intent / MockMT5Client (G2 原子下单桥)
  本文件不修改任何底层逻辑，只负责把它们串成单进程常驻守护。

【状态机】
  IDLE ──(order_intent.json)──► process_intent() ──► AttributionSink.open_position()
        ──► IN_POSITION：每 tick_interval 读价 ──► sample_tick(order_id, price)
        ──(close_intent.json)──► close_position() 落库 + 回调熔断 ──► IDLE / COOLDOWN

【Tick 采样抽象（关键）】
  tick_source(call_count) -> float | None
    - 实盘模式：封装 MetaTrader5.symbol_info_tick("XAUUSD").bid/ask
    - Mock 模式：返回注入价格序列的下一元素（耗尽返回 None，停止采样）
  supervisor 不依赖具体客户端对象取 Tick，避免在 mt5_bridge 里加接口（零侵入）。

【异常不崩溃】
  - 未开仓直接录平仓意图 → close_position 抛 KeyError → 捕获写 ERROR 结果，进程继续
  - 损坏 JSON / 缺字段 → 捕获写 ERROR，进程继续
  - Tick 读取异常 → 跳过本轮采样，进程继续

运行：
  实盘：python trading_os/g2_supervisor.py
  Mock：python trading_os/g2_supervisor.py --mock   （供本地无 MT5 时验证链路）
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from typing import Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from circuit_breaker import CircuitBreaker
from attribution_sink import AttributionSink
from mt5_bridge import process_intent, MockMT5Client

DATA_DIR = os.path.join(_HERE, "data")
INTENT_PATH = os.path.join(DATA_DIR, "order_intent.json")
CLOSE_INTENT_PATH = os.path.join(DATA_DIR, "close_intent.json")
EXEC_RESULT_PATH = os.path.join(DATA_DIR, "execution_result.json")
CLOSE_RESULT_PATH = os.path.join(DATA_DIR, "execution_result_close.json")
SPEC_PATH = os.path.join(DATA_DIR, "xauusd_spec.json")
DEFAULT_DB = os.path.join(os.path.dirname(_HERE), "backend", "database", "vibe_research.db")


# ---------------------------------------------------------------------------
# Tick 源工厂
# ---------------------------------------------------------------------------
def make_live_tick_source(symbol: str = "XAUUSD"):
    """实盘 Tick 源：封装 MetaTrader5.symbol_info_tick。惰性 import，无 MT5 不崩。"""
    def _src(call_count: int) -> Optional[float]:
        try:
            import MetaTrader5 as mt5
        except Exception:
            return None
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        # 买价/卖价取中值作为持仓标记价（BUY 看 bid，SELL 看 ask；中值足够极值采样）
        return float((tick.bid + tick.ask) / 2.0)
    return _src


def make_mock_tick_source(price_sequence: list[float]):
    """Mock Tick 源：依次吐出注入价格序列，耗尽返回 None。"""
    it = iter(price_sequence)
    def _src(call_count: int) -> Optional[float]:
        try:
            return next(it)
        except StopIteration:
            return None
    return _src


# ---------------------------------------------------------------------------
# 守护主循环
# ---------------------------------------------------------------------------
def _atomic_write_json(path: str, obj: dict) -> None:
    """原子写 JSON：写临时文件再 os.replace，避免消费方读到半截文件（竞态）。

    Windows 沙箱下 os.replace 对已存在目标偶发 PermissionError（WinError 5），
    捕获后先删旧文件再 replace，并做有限重试。
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
            time.sleep(0.01)
    # 兜底：直接覆盖写
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def supervise(
    circuit_breaker: CircuitBreaker,
    attribution_sink: AttributionSink,
    spec_dict: dict,
    tick_source: Callable[[int], Optional[float]],
    mt5_client=None,
    tick_interval: float = 0.5,
    open_poll_interval: float = 0.5,
    max_iterations: Optional[int] = None,
    stop_event=None,
) -> None:
    """单进程守护：开仓监听 + 持仓 Tick 采样 + 平仓监听。

    tick_source(call_count) 在 IN_POSITION 状态下每个 tick_interval 调用一次。
    返回 None 表示该轮无价（跳过采样）。
    """
    iterations = 0
    current_order_id: Optional[str] = None
    tick_count = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            break

        # ---- 1. 开仓意图监听（仅 IDLE 时处理新开仓）----
        if current_order_id is None and os.path.exists(INTENT_PATH):
            try:
                with open(INTENT_PATH, "r", encoding="utf-8") as f:
                    intent = json.load(f)
                result = process_intent(
                    intent, circuit_breaker, attribution_sink, spec_dict, mt5_client
                )
                _atomic_write_json(EXEC_RESULT_PATH, result)
                if result.get("status") == "FILLED":
                    current_order_id = result["order_id"]
                    tick_count = 0
                    print(f"[SUP] 开仓成功 order_id={current_order_id}，进入 IN_POSITION 采样")
                else:
                    print(f"[SUP] 开仓被拒：{result}")
            except Exception as e:
                _atomic_write_json(EXEC_RESULT_PATH, {"status": "ERROR", "reason": str(e)})
                print(f"[SUP-ERROR] 开仓处理异常：{e}")
            try:
                os.remove(INTENT_PATH)
            except OSError:
                pass

        # ---- 2. 持仓 Tick 采样（仅 IN_POSITION 时）----
        if current_order_id is not None:
            price = tick_source(tick_count)
            if price is not None:
                try:
                    attribution_sink.sample_tick(current_order_id, price)
                except Exception as e:
                    # 采样异常不致命，跳过本轮
                    print(f"[SUP-WARN] sample_tick 异常（跳过）：{e}")
            tick_count += 1

        # ---- 3. 平仓意图监听（始终检查，无论 IDLE/IN_POSITION）----
        if os.path.exists(CLOSE_INTENT_PATH):
            try:
                with open(CLOSE_INTENT_PATH, "r", encoding="utf-8") as f:
                    cintent = json.load(f)
                row = attribution_sink.close_position(
                    order_id=cintent["order_id"],
                    exit_price=float(cintent["exit_price"]),
                    exit_reason=cintent.get("exit_reason", "MANUAL"),
                    realized_pnl_usd=float(cintent["realized_pnl_usd"]),
                    circuit_breaker=circuit_breaker,
                )
                _atomic_write_json(CLOSE_RESULT_PATH, {"status": "CLOSED", **row})
                print(f"[SUP] 平仓落库 order_id={row['order_id']} "
                      f"mfe_r={row['mfe_r']} realized_r={row['realized_r']} "
                      f"giveback_r={row['giveback_r']}")
                current_order_id = None  # 重置为 IDLE（熔断态由 cb 自身管理）
            except Exception as e:
                _atomic_write_json(CLOSE_RESULT_PATH, {"status": "ERROR", "reason": str(e)})
                print(f"[SUP-ERROR] 平仓处理异常（进程继续）：{e}")
            try:
                os.remove(CLOSE_INTENT_PATH)
            except OSError:
                pass

        # ---- 节拍 ----
        if current_order_id is not None:
            time.sleep(tick_interval)
        else:
            time.sleep(open_poll_interval)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="Mock 模式（无 MT5 时验证链路，不真连）")
    ap.add_argument("--db", default=DEFAULT_DB, help="归因 SQLite 路径")
    ap.add_argument("--tick-interval", type=float, default=0.5)
    ap.add_argument("--symbol", default="XAUUSD")
    args = ap.parse_args()

    if not os.path.exists(SPEC_PATH):
        print(f"[FAIL] 找不到规格文件 {SPEC_PATH}，请先跑 probe_xauusd_spec.py")
        sys.exit(2)
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    cb = CircuitBreaker()
    sink = AttributionSink(db_path=args.db)

    if args.mock:
        tick_source = make_mock_tick_source([])  # 空序列：Mock 模式下不采样（由单测注入）
        client = MockMT5Client()
        print(f"[SUP] Mock 模式启动（不真连 MT5），监听 {INTENT_PATH} ...")
    else:
        tick_source = make_live_tick_source(args.symbol)
        client = None  # process_intent 内部自动降级 Mock 或需真实 mt5（见 mt5_bridge）
        print(f"[SUP] 实盘模式启动，Tick 源=MetaTrader5({args.symbol})，监听 {INTENT_PATH} ...")

    try:
        supervise(cb, sink, spec, tick_source, mt5_client=client,
                  tick_interval=args.tick_interval)
    except KeyboardInterrupt:
        print("\n[SUP] 守护已停止")
        sink.close()


if __name__ == "__main__":
    main()
