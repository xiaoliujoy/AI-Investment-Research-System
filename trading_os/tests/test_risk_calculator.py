# -*- coding: utf-8 -*-
"""
test_risk_calculator.py
G1 离线单测矩阵（100% 覆盖率目标）

覆盖：
  UC1 标准 BUY/SELL 反算（封顶 0.01，理论亏损 ≤ $20）
  UC2 超窄止损拦截（< 100pt → InvalidStopDistanceError）
  UC3 超宽止损预算溢出（0.01 封顶仍超 $20 → RiskBudgetExceededError）
  UC4 连亏冷却触发（30min 内连续 2 亏 → COOLDOWN 120min，can_submit_order False + 解锁时间校验）
  UC5 日亏停机触发（累计 ≥ $60 → DAILY_HALTED 阻断）
  附加：点差拦截 / 方向校验 / 跨日重置 / 冷却精确时间戳 / 封顶不超预算
"""
from __future__ import annotations
import datetime
import pytest

from risk_calculator import (
    compute_risk_plan,
    RiskPlan,
    InvalidStopDistanceError,
    RiskBudgetExceededError,
    SpreadTooWideError,
    DEFAULT_MAX_LOT,
    DEFAULT_RISK_BUDGET,
)
from circuit_breaker import CircuitBreaker, CBState

# 离线规格（与 probe 降级常量一致，point=0.01 → per_lot_per_point = $1）
SPEC = {
    "symbol": "XAUUSD",
    "trade_contract_size": 100.0,
    "point": 0.01,
    "tick_size": 0.01,
    "tick_value": 1.0,
    "volume_min": 0.01,
    "volume_step": 0.01,
    "volume_max": 100.0,
    "spread_avg_points": 3.0,
    "source": "OFFLINE_KNOWN_CONSTANT",
}


# ============ UC1 标准 BUY/SELL 反算 ============
def test_uc1_buy_standard():
    # entry=2000, invalidation=1995 → 止损 $5.00 = 500 points
    # raw_lots = 20 / (500 * 1) = 0.04 → 封顶 0.01
    plan = compute_risk_plan(2000.0, 1995.0, "BUY", DEFAULT_RISK_BUDGET, SPEC)
    assert isinstance(plan, RiskPlan)
    assert plan.stop_distance_points == 500.0
    assert plan.calculated_lots == DEFAULT_MAX_LOT  # 封顶 0.01
    assert plan.max_loss_usd == pytest.approx(0.01 * 1.0 * 500, abs=1e-6)  # $5.00
    assert plan.within_budget is True


def test_uc1_sell_standard():
    # SELL: entry=2000, invalidation=2005 → 止损 $5.00 = 500 points，方向不影响距离
    plan = compute_risk_plan(2000.0, 2005.0, "SELL", DEFAULT_RISK_BUDGET, SPEC)
    assert plan.stop_distance_points == 500.0
    assert plan.calculated_lots == DEFAULT_MAX_LOT
    assert plan.max_loss_usd <= DEFAULT_RISK_BUDGET + 1e-9


def test_uc1_precise_lots_floor():
    # 选一个让 raw_lots 落在 step 之间的止损距离，验证向 lot_step 下取整
    # 想要 raw_lots ≈ 0.025（介于 0.02 和 0.03 之间）→ floor/step=0.02
    # raw = 20 / (dist * 1) = 0.025 → dist = 800 points = $8.00
    plan = compute_risk_plan(2000.0, 1992.0, "BUY", DEFAULT_RISK_BUDGET, SPEC)
    assert plan.stop_distance_points == 800.0
    # raw=0.025, floor(0.025/0.01)*0.01 = 0.02，但未超过 max_lot 0.01 → 仍封顶 0.01
    assert plan.calculated_lots == 0.01


# ============ UC2 超窄止损拦截 ============
def test_uc2_narrow_stop_rejected():
    # entry=2000, invalidation=1999.50 → $0.50 = 50 points < 100 下限
    with pytest.raises(InvalidStopDistanceError):
        compute_risk_plan(2000.0, 1999.50, "BUY", DEFAULT_RISK_BUDGET, SPEC)


def test_uc2_boundary_exact_100_allowed():
    # 正好 100 points = $1.00，应放行（下限是 < 不允许，= 允许）
    plan = compute_risk_plan(2000.0, 1999.0, "BUY", DEFAULT_RISK_BUDGET, SPEC)
    assert plan.stop_distance_points == 100.0
    assert plan.calculated_lots == DEFAULT_MAX_LOT


# ============ UC3 超宽止损预算溢出 ============
def test_uc3_wide_stop_budget_exceeded():
    # entry=2000, invalidation=1970 → $30.00 = 3000 points
    # 0.01 手理论亏损 = 0.01 * 1 * 3000 = $30 > $20 → 即使最小手也超预算
    with pytest.raises(RiskBudgetExceededError):
        compute_risk_plan(2000.0, 1970.0, "BUY", DEFAULT_RISK_BUDGET, SPEC)


# ============ 点差拦截 ============
def test_spread_too_wide_rejected():
    with pytest.raises(SpreadTooWideError):
        compute_risk_plan(2000.0, 1995.0, "BUY", DEFAULT_RISK_BUDGET, SPEC, spread_points=50.0)


def test_spread_boundary_45_allowed():
    # 正好 45 points 应放行（> 才拒绝）
    plan = compute_risk_plan(2000.0, 1995.0, "BUY", DEFAULT_RISK_BUDGET, SPEC, spread_points=45.0)
    assert plan.spread_points == 45.0


# ============ 方向校验 ============
def test_invalid_direction_rejected():
    with pytest.raises(ValueError):
        compute_risk_plan(2000.0, 1995.0, "HOLD", DEFAULT_RISK_BUDGET, SPEC)


# ============ UC4 连亏冷却 ============
def test_uc4_consecutive_loss_cooldown():
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    assert cb.can_submit_order(now=t0) == (True, "IDLE 允许开仓")

    # 第1笔亏损（10:01）
    cb.record_trade(-10.0, now=t0 + datetime.timedelta(minutes=1))
    ok, _ = cb.can_submit_order(now=t0 + datetime.timedelta(minutes=1))
    assert ok is True  # 连亏 1 笔未触发

    # 第2笔亏损（10:02，仍在 30min 窗口内）
    cb.record_trade(-15.0, now=t0 + datetime.timedelta(minutes=2))
    ok, msg = cb.can_submit_order(now=t0 + datetime.timedelta(minutes=2))
    assert ok is False
    assert cb.state == CBState.COOLDOWN
    # 解锁时间 = 10:02 + 120min = 12:02
    assert cb.cooldown_unlock_ts == (t0 + datetime.timedelta(minutes=2 + 120))


def test_uc4_cooldown_unlock_after_120min():
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    cb.record_trade(-10.0, now=t0 + datetime.timedelta(minutes=1))
    cb.record_trade(-15.0, now=t0 + datetime.timedelta(minutes=2))
    assert cb.state == CBState.COOLDOWN
    # 119min 后仍锁定
    ok, _ = cb.can_submit_order(now=t0 + datetime.timedelta(minutes=2 + 119))
    assert ok is False
    # 120min 整解锁
    ok, _ = cb.can_submit_order(now=t0 + datetime.timedelta(minutes=2 + 120))
    assert ok is True
    assert cb.state == CBState.IDLE


def test_uc4_loss_window_sliding_resets():
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    # 亏损1（10:00）
    cb.record_trade(-10.0, now=t0)
    # 盈利打断（10:05）
    cb.record_trade(+20.0, now=t0 + datetime.timedelta(minutes=5))
    # 再亏（10:10）——窗口内只有1连亏，不应触发
    cb.record_trade(-5.0, now=t0 + datetime.timedelta(minutes=10))
    ok, _ = cb.can_submit_order(now=t0 + datetime.timedelta(minutes=10))
    assert ok is True
    assert cb.state == CBState.IDLE


# ============ UC5 日亏停机 ============
def test_uc5_daily_halt():
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    cb.record_trade(-30.0, now=t0)
    cb.record_trade(-31.0, now=t0 + datetime.timedelta(minutes=5))  # 累计 61 ≥ 60
    ok, msg = cb.can_submit_order(now=t0 + datetime.timedelta(minutes=5))
    assert ok is False
    assert cb.state == CBState.DAILY_HALTED
    assert "DAILY_HALTED" in msg


def test_uc5_daily_reset_next_day():
    t0 = datetime.datetime(2026, 8, 22, 23, 0, 0)
    cb = CircuitBreaker(now=t0)
    cb.record_trade(-60.0, now=t0)  # 当日停机
    assert cb.state == CBState.DAILY_HALTED
    # 跨日到次日 01:00
    next_day = datetime.datetime(2026, 8, 23, 1, 0, 0)
    ok, _ = cb.can_submit_order(now=next_day)
    assert ok is True
    assert cb.state == CBState.IDLE
    assert cb.daily_loss_usd == 0.0


# ============ 组合：Risk Gate + Circuit Breaker 串联 ============
def test_combined_gate_passes_when_idle_and_valid():
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    can, _ = cb.can_submit_order(now=t0)
    assert can is True
    plan = compute_risk_plan(2000.0, 1995.0, "BUY", DEFAULT_RISK_BUDGET, SPEC)
    assert plan.within_budget is True


# ============ 覆盖率补齐：防御分支 ============
def test_risk_calculator_spec_none_rejected():
    # spec_dict 为 None 的防御（行 102）
    with pytest.raises(ValueError):
        compute_risk_plan(2000.0, 1995.0, "BUY", DEFAULT_RISK_BUDGET, None)


def test_risk_calculator_as_dict_serializes():
    # 漏行 66：RiskPlan.as_dict() 序列化
    plan = compute_risk_plan(2000.0, 1995.0, "BUY", DEFAULT_RISK_BUDGET, SPEC)
    d = plan.as_dict()
    assert d["direction"] == "BUY"
    assert d["calculated_lots"] == DEFAULT_MAX_LOT
    assert "max_loss_usd" in d


def test_risk_calculator_nonpositive_spec_rejected():
    # 漏行 108：spec point / lot_step 非正防御
    bad_spec = dict(SPEC)
    bad_spec["point"] = 0.0
    with pytest.raises(ValueError):
        compute_risk_plan(2000.0, 1995.0, "BUY", DEFAULT_RISK_BUDGET, bad_spec)


def test_cb_in_position_gate_blocks():
    # 漏行 102：IN_POSITION 状态下 can_submit_order 返回 False
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    cb.set_in_position(True, now=t0)
    assert cb.state == CBState.IN_POSITION
    ok, msg = cb.can_submit_order(now=t0)
    assert ok is False
    assert "IN_POSITION" in msg


def test_cb_set_in_position_toggle():
    # 漏行 141-146：set_in_position 两个分支
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    cb.set_in_position(True, now=t0)   # IDLE → IN_POSITION
    assert cb.state == CBState.IN_POSITION
    cb.set_in_position(False, now=t0)  # IN_POSITION → IDLE
    assert cb.state == CBState.IDLE


def test_cb_snapshot_serializes():
    # 漏行 149：snapshot() 返回 dict
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb = CircuitBreaker(now=t0)
    snap = cb.snapshot()
    assert snap["state"] == "IDLE"
    assert snap["daily_loss_usd"] == 0.0

