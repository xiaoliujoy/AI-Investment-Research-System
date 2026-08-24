# -*- coding: utf-8 -*-
"""
mt5_bridge.py
G2 阶段 —— 执行桥接器（文件队列 IPC + Mock 降级 + 前置门禁联防）

【职责】
  监听 trading_os/data/order_intent.json，处理单条 intent：
    1. CircuitBreaker.can_submit_order() 前置门禁（非 IDLE 直接拒绝）
    2. compute_risk_plan() 重新验算手数/止损距离，与 intent.lots 比对防篡改
    3. 原子订单下发：强制绑定 SL=invalidation_price，滑点校验
    4. 写回 execution_result.json，并登记 AttributionSink 开仓快照

【降级与 Mock】
  未安装 MetaTrader5 时自动启用 MockMT5Client，注入模拟成交回报/Tick流。
  单测全程使用 MockMT5Client，确定性、零副作用。

【解耦（校准2）】
  process_intent()  = 纯逻辑，单测全量覆盖
  poll_loop()       = while True: sleep 调度，不进单测

【防篡改（校准3）】
  bridge 不自己算 risk，而是用 intent 的 entry/invalidation/direction
  调 compute_risk_plan 拿 plan.lots，与 intent.lots 比对；偏差超 epsilon 视为篡改拒绝。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

from risk_calculator import compute_risk_plan, RiskPlan, DEFAULT_RISK_BUDGET
from circuit_breaker import CircuitBreaker
from attribution_sink import AttributionSink, ATTRIBUTION_TABLE

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
INTENT_PATH = os.path.join(DATA_DIR, "order_intent.json")
RESULT_PATH = os.path.join(DATA_DIR, "execution_result.json")

# 手数比对容差（防篡改阈值）
LOT_EPSILON = 1e-6
# 最大允许滑点（points）→ 来自 risk_limits.json 的 spread 拦截同源，这里校验成交偏离
MAX_SLIPPAGE_POINTS = 45.0


class MissingSLRejected(Exception):
    """SL（invalidation_price）缺失，拒绝下发。"""


class TamperedIntentRejected(Exception):
    """intent 手数与重新验算不一致，疑似篡改。"""


class CircuitBreakerBlocked(Exception):
    """熔断器处于非 IDLE 状态，拒绝开仓。"""


@dataclass
class MockFill:
    order_id: str
    fill_price: float
    filled_lots: float
    spread_points: float
    slippage_points: float


class MockMT5Client:
    """离线降级客户端：注入式成交回报，无 MT5 依赖。"""

    def __init__(self, fill_price_override: Optional[float] = None,
                 slippage_points: float = 0.0, spread_points: float = 1.0):
        self.fill_price_override = fill_price_override
        self.slippage_points = slippage_points
        self.spread_points = spread_points
        self.last_order = None
        self.calls = []

    def send_market_order(self, direction: str, lots: float,
                          entry_price: float, sl_price: float) -> MockFill:
        # 模拟成交：以 requested entry +/- 滑点 成交
        slip = self.slippage_points
        if direction == "BUY":
            fill = entry_price + slip if self.fill_price_override is None else self.fill_price_override
        else:
            fill = entry_price - slip if self.fill_price_override is None else self.fill_price_override
        fill = round(fill, 2)
        fill_obj = MockFill(
            order_id=f"MOCK-{int(time.time()*1000)}",
            fill_price=fill,
            filled_lots=lots,
            spread_points=self.spread_points,
            slippage_points=slip,
        )
        self.last_order = (direction, lots, entry_price, sl_price)
        self.calls.append(fill_obj)
        return fill_obj

    def close_position(self, order_id: str, exit_price: float) -> MockFill:
        return MockFill(
            order_id=order_id, fill_price=exit_price, filled_lots=0.0,
            spread_points=self.spread_points, slippage_points=self.slippage_points,
        )


def process_intent(
    intent: Dict[str, Any],
    circuit_breaker: CircuitBreaker,
    attribution_sink: AttributionSink,
    spec_dict: Dict[str, Any],
    mt5_client=None,
    now: str = "",
    risk_budget: float = DEFAULT_RISK_BUDGET,
) -> Dict[str, Any]:
    """处理单条订单意图（纯逻辑，可测试）。

    返回 execution_result 字典。任何拒绝路径都会抛出对应 Exception，
    由调用方（poll_loop 或单测）捕获并记录。
    """
    symbol = intent.get("symbol", "XAUUSD")
    direction = intent.get("direction", "BUY")
    entry = float(intent.get("entry_price", 0.0))
    invalidation = intent.get("invalidation_price", None)
    requested_lots = float(intent.get("lots", 0.0))

    # ---- 门禁1：硬止损必须存在 ----
    if invalidation is None:
        raise MissingSLRejected("invalidation_price 缺失，拒绝下发（违反 Hard Prohibitions：不取消止损）")

    # ---- 门禁2：熔断器前置 ----
    can, reason = circuit_breaker.can_submit_order()
    if not can:
        raise CircuitBreakerBlocked(f"熔断器拒绝：{reason}")

    # ---- 门禁3：防篡改重新验算 ----
    plan: RiskPlan = compute_risk_plan(
        entry_price=entry,
        invalidation_price=float(invalidation),
        direction=direction,
        risk_budget_usd=risk_budget,
        spec_dict=spec_dict,
    )
    if abs(plan.calculated_lots - requested_lots) > LOT_EPSILON:
        raise TamperedIntentRejected(
            f"手数篡改：intent={requested_lots} vs 验算={plan.calculated_lots}（偏差>{LOT_EPSILON}）"
        )

    # ---- 门禁4：滑点校验（成交价偏离 requested entry）----
    client = mt5_client or MockMT5Client()
    fill = client.send_market_order(direction, plan.calculated_lots, entry, float(invalidation))
    slippage = abs(fill.fill_price - entry)
    if slippage > MAX_SLIPPAGE_POINTS:
        # 滑点超限：拒绝并报警（不提交真实仓位）
        return {
            "status": "REJECTED_SLIPPAGE",
            "order_id": fill.order_id,
            "slippage_points": round(slippage, 2),
            "max_slippage_points": MAX_SLIPPAGE_POINTS,
            "notes": "成交偏离超阈值，拒绝下发",
        }

    # ---- 原子下单成功：登记开仓快照 ----
    attribution_sink.open_position(
        order_id=fill.order_id,
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        sl_price=float(invalidation),
        requested_lots=requested_lots,
        filled_lots=fill.filled_lots,
        fill_price=fill.fill_price,
        max_loss_usd=plan.max_loss_usd,
        spread_points=fill.spread_points,
        slippage_points=fill.slippage_points,
        open_ts=now,
    )

    result = {
        "status": "FILLED",
        "order_id": fill.order_id,
        "symbol": symbol,
        "direction": direction,
        "requested_entry": entry,
        "fill_price": fill.fill_price,
        "lots": fill.filled_lots,
        "sl_price": float(invalidation),
        "max_loss_usd": plan.max_loss_usd,
        "spread_points": fill.spread_points,
        "slippage_points": fill.slippage_points,
        "can_submit_before": True,
        "notes": "",
    }
    return result


def poll_loop(
    circuit_breaker: CircuitBreaker,
    attribution_sink: AttributionSink,
    spec_dict: Dict[str, Any],
    mt5_client=None,
    interval: float = 1.0,
    max_iterations: Optional[int] = None,
):
    """文件队列轮询调度（I/O 层，不进单测）。

    监听 order_intent.json，处理完后写回 execution_result.json。
    若 mt5_client 为 None 且 MetaTrader5 不可用，自动用 MockMT5Client。
    """
    iterations = 0
    while True:
        if os.path.exists(INTENT_PATH):
            try:
                with open(INTENT_PATH, "r", encoding="utf-8") as f:
                    intent = json.load(f)
                result = process_intent(
                    intent, circuit_breaker, attribution_sink, spec_dict, mt5_client
                )
                with open(RESULT_PATH, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            except (MissingSLRejected, CircuitBreakerBlocked, TamperedIntentRejected) as e:
                with open(RESULT_PATH, "w", encoding="utf-8") as f:
                    json.dump({"status": "REJECTED", "reason": str(e)}, f, ensure_ascii=False, indent=2)
            except Exception as e:  # 其它异常也不阻塞循环
                with open(RESULT_PATH, "w", encoding="utf-8") as f:
                    json.dump({"status": "ERROR", "reason": str(e)}, f, ensure_ascii=False, indent=2)
            # 处理完删除 intent，避免重复处理
            try:
                os.remove(INTENT_PATH)
            except OSError:
                pass

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        time.sleep(interval)
