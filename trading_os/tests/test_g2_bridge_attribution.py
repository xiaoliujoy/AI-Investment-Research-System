# -*- coding: utf-8 -*-
"""G2 离线单测：mt5_bridge + attribution_sink 闭环验证。

覆盖：
  UC1 标准下单与成交链路（intent → FILLED → IN_POSITION 快照）
  UC2 硬止损缺失拒绝（零外部调用）
  UC3 熔断器拦截（COOLDOWN / DAILY_HALTED 状态注入拒绝）
  UC4 平仓归因与量纲自洽（MFE_R / Realized_R / Giveback_R）
  UC5 止损触发与状态机回写（HIT_SL + 连亏计数驱动CircuitBreaker）
  + 滑点超限拒绝
  + 手数篡改拒绝
  + attribution_sink 建表/落库/查询
"""
from __future__ import annotations

import datetime
import sqlite3

import pytest

from risk_calculator import DEFAULT_RISK_BUDGET
from circuit_breaker import CircuitBreaker
from attribution_sink import AttributionSink, ATTRIBUTION_TABLE
from mt5_bridge import (
    process_intent,
    MissingSLRejected,
    CircuitBreakerBlocked,
    TamperedIntentRejected,
    MockMT5Client,
)

# XAUUSD 离线规格（键名对齐 risk_calculator.py 真实读取：trade_contract_size / volume_step）
SPEC = {
    "trade_contract_size": 100.0,
    "tick_size": 0.01,
    "tick_value": 1.0,
    "point": 0.01,
    "volume_step": 0.01,
    "volume_min": 0.01,
    "max_lot_per_order": 0.01,
}

NOW = "2026-08-22T10:00:00"


@pytest.fixture
def sink():
    # 内存库，纯离线
    s = AttributionSink(db_path=":memory:", table=ATTRIBUTION_TABLE)
    yield s
    s.close()


@pytest.fixture
def cb():
    return CircuitBreaker(now=datetime.datetime(2026, 8, 22, 10, 0, 0))


def _intent(entry, inv, lots, direction="BUY"):
    return {
        "symbol": "XAUUSD",
        "direction": direction,
        "entry_price": entry,
        "invalidation_price": inv,
        "lots": lots,
    }


# ============ UC1：标准下单与成交链路 ============
def test_uc1_standard_fill_chain(sink, cb):
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")  # $5 风险，封顶 0.01
    client = MockMT5Client(fill_price_override=2000.05)
    res = process_intent(intent, cb, sink, SPEC, mt5_client=client, now=NOW)
    assert res["status"] == "FILLED"
    assert res["direction"] == "BUY"
    assert res["lots"] == 0.01
    assert res["sl_price"] == 1995.0
    # attribution_sink 已登记开仓内存快照（落库在平仓时，见 UC4/UC5）
    assert res["order_id"] in sink._positions
    ps = sink._positions[res["order_id"]]
    assert ps.entry_price == 2000.0
    assert ps.sl_price == 1995.0
    assert ps.max_loss_usd == 5.0  # 1R = $5


# ============ UC2：硬止损缺失拒绝（零外部调用） ============
def test_uc2_missing_sl_rejected_zero_external_call(sink, cb):
    intent = {
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_price": 2000.0,
        "invalidation_price": None,  # 缺失
        "lots": 0.01,
    }
    client = MockMT5Client()
    with pytest.raises(MissingSLRejected):
        process_intent(intent, cb, sink, SPEC, mt5_client=client, now=NOW)
    # 零外部下单调用
    assert len(client.calls) == 0
    # 无开仓快照落库
    assert sink._positions == {}


# ============ UC3：熔断器拦截 ============
def test_uc3_circuit_breaker_cooldown_blocks(sink, cb):
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb.record_trade(-5.0, now=t0)  # 连亏1
    cb.record_trade(-5.0, now=t0 + datetime.timedelta(minutes=1))  # 连亏2 → COOLDOWN
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")
    client = MockMT5Client()
    with pytest.raises(CircuitBreakerBlocked):
        process_intent(intent, cb, sink, SPEC, mt5_client=client, now=t0 + datetime.timedelta(minutes=2))
    assert len(client.calls) == 0


def test_uc3_circuit_breaker_daily_halt_blocks(sink, cb):
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb.record_trade(-20.0, now=t0)
    cb.record_trade(-20.0, now=t0)
    cb.record_trade(-20.0, now=t0)  # 累计 -60 → DAILY_HALTED
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")
    client = MockMT5Client()
    with pytest.raises(CircuitBreakerBlocked):
        process_intent(intent, cb, sink, SPEC, mt5_client=client, now=t0)
    assert len(client.calls) == 0


# ============ UC4：平仓归因与量纲自洽 ============
def test_uc4_attribution_dimension_self_consistent(sink, cb):
    # Entry 2000, SL 1995 → 1R = $5
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")
    client = MockMT5Client(fill_price_override=2000.0)
    res = process_intent(intent, cb, sink, SPEC, mt5_client=client, now=NOW)
    oid = res["order_id"]

    # 持仓期 Tick 采样：最高触及 2010（MFE (2010-2000)*0.01*100=$10 → +2.0R）
    sink.sample_tick(oid, 2005.0)
    sink.sample_tick(oid, 2010.0)
    sink.sample_tick(oid, 2003.0)

    # 最终 2002 平仓，Realized PnL 显式传入 $7.00 → +1.4R（1R=$5）
    row = sink.close_position(
        oid, exit_price=2002.0, exit_reason="MANUAL",
        realized_pnl_usd=7.0, circuit_breaker=cb, close_ts=NOW,
    )
    # 量纲核对（E1：1R=5 → MFE +$10=+2.0R, Realized +$7=+1.4R, Giveback=2.0-1.4=0.6R）
    assert abs(row["mfe_r"] - 2.0) < 1e-6
    assert abs(row["realized_r"] - 1.4) < 1e-6
    assert abs(row["giveback_r"] - 0.6) < 1e-6
    assert row["exit_reason"] == "MANUAL"
    # DB 落库核对
    rec = sink.get_record(oid)
    assert abs(rec["mfe_r"] - 2.0) < 1e-6
    assert abs(rec["realized_r"] - 1.4) < 1e-6
    assert abs(rec["giveback_r"] - 0.6) < 1e-6


# ============ UC5：止损触发与状态机回写 ============
def test_uc5_hit_sl_drives_circuit_breaker(sink, cb):
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")
    client = MockMT5Client(fill_price_override=2000.0)
    res = process_intent(intent, cb, sink, SPEC, mt5_client=client, now=NOW)
    oid = res["order_id"]

    # 价格触及 SL 1995 → 强平
    sink.sample_tick(oid, 1996.0)
    sink.sample_tick(oid, 1995.0)
    row = sink.close_position(
        oid, exit_price=1995.0, exit_reason="HIT_SL",
        realized_pnl_usd=-5.0, circuit_breaker=cb, close_ts=NOW,
    )
    assert row["exit_reason"] == "HIT_SL"
    # 驱动 CircuitBreaker 连亏计数 +1
    assert cb.consecutive_losses == 1


# ============ 滑点超限拒绝 ============
def test_slippage_exceed_rejected(sink, cb):
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")
    # 模拟滑点 100 points（远超 45 阈值）
    client = MockMT5Client(fill_price_override=2100.0, slippage_points=100.0)
    res = process_intent(intent, cb, sink, SPEC, mt5_client=client, now=NOW)
    assert res["status"] == "REJECTED_SLIPPAGE"
    # 未登记开仓（拒绝下单）
    assert sink._positions == {}


# ============ 手数篡改拒绝 ============
def test_tampered_lots_rejected(sink, cb):
    # 真实验算 lots=0.01，但 intent 写 0.02（篡改）
    intent = _intent(2000.0, 1995.0, 0.02, "BUY")
    client = MockMT5Client(fill_price_override=2000.0)
    with pytest.raises(TamperedIntentRejected):
        process_intent(intent, cb, sink, SPEC, mt5_client=client, now=NOW)
    assert len(client.calls) == 0
    assert sink._positions == {}


# ============ SELL 方向量纲自洽 ============
def test_sell_direction_attribution(sink, cb):
    # SELL @ 2000, SL 2005 → 1R = $5，价格跌到 1990 平仓（有利 $10 = +2.0R）
    intent = _intent(2000.0, 2005.0, 0.01, "SELL")
    client = MockMT5Client(fill_price_override=2000.0)
    res = process_intent(intent, cb, sink, SPEC, mt5_client=client, now=NOW)
    oid = res["order_id"]
    sink.sample_tick(oid, 1995.0)  # 有利极值
    sink.sample_tick(oid, 2002.0)  # 不利极值
    row = sink.close_position(
        oid, exit_price=1990.0, exit_reason="MANUAL",
        realized_pnl_usd=10.0, circuit_breaker=cb, close_ts=NOW,
    )
    # SELL：价更低=有利，mfe_price 应=1995 → MFE (2000-1995)*0.01*100=$5 → +1.0R
    assert abs(row["mfe_r"] - 1.0) < 1e-6
    assert row["direction"] == "SELL"


# ============ 建表防御：独立表 xau_execution_attribution 不碰 outcome_attribution ============
def test_attribution_table_isolated(sink):
    # 确认表存在且字段包含交易级字段
    cur = sink._conn.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name='{ATTRIBUTION_TABLE}'"
    )
    assert cur.fetchone() is not None
    # outcome_attribution 不应被本模块创建/修改
    cur2 = sink._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='outcome_attribution'"
    )
    assert cur2.fetchone() is None


# ============ attribution_sink 防御分支（漏行 134 / 154） ============
def test_sample_tick_unknown_order_id_noop(sink):
    # 漏行 134：sample_tick 对未知 order_id 早期 return，不应抛错
    sink.sample_tick("NON_EXISTENT", 2000.0)  # 静默 no-op
    assert "NON_EXISTENT" not in sink._positions


def test_close_position_unknown_order_id_raises(sink):
    # 漏行 154：close_position 对未开仓 order_id 抛 KeyError
    with pytest.raises(KeyError):
        sink.close_position("NON_EXISTENT", 2000.0, "MANUAL", 0.0)


# ============ MockMT5Client.close_position 降级完整性 ============
def test_mock_client_close_position():
    client = MockMT5Client()
    fill = client.close_position("ORDER_X", 1990.0)
    assert fill.order_id == "ORDER_X"
    assert fill.fill_price == 1990.0


# ============ process_intent 不传 mt5_client 自动降级 MockMT5Client ============
def test_process_intent_auto_mock_fallback(sink, cb):
    # 校准：bridge 未收到 mt5_client 时应自动用 MockMT5Client 降级，不依赖 MT5 环境
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")
    res = process_intent(intent, cb, sink, SPEC, mt5_client=None, now=NOW)
    assert res["status"] == "FILLED"
    assert res["order_id"] in sink._positions


# ============ poll_loop 文件队列调度（max_iterations 受限，确定性） ============
def test_poll_loop_processes_intent_file(tmp_path, sink, cb):
    import json
    import os
    import importlib
    import mt5_bridge as bridge_mod

    # 把 intent 写到临时目录，覆盖模块级路径常量
    intent_path = tmp_path / "order_intent.json"
    result_path = tmp_path / "execution_result.json"
    intent = _intent(2000.0, 1995.0, 0.01, "BUY")
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    bridge_mod.INTENT_PATH = str(intent_path)
    bridge_mod.RESULT_PATH = str(result_path)

    bridge_mod.poll_loop(cb, sink, SPEC, mt5_client=None, interval=0.0, max_iterations=1)

    # result 写出且 intent 被消费删除
    assert result_path.exists()
    assert not intent_path.exists()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "FILLED"


# ============ poll_loop 处理损坏 intent（通用 Exception 分支） ============
def test_poll_loop_corrupted_intent_writes_error(tmp_path, sink, cb):
    import json
    import mt5_bridge as bridge_mod

    intent_path = tmp_path / "order_intent.json"
    result_path = tmp_path / "execution_result.json"
    intent_path.write_text("{ this is not valid json", encoding="utf-8")

    bridge_mod.INTENT_PATH = str(intent_path)
    bridge_mod.RESULT_PATH = str(result_path)

    bridge_mod.poll_loop(cb, sink, SPEC, mt5_client=None, interval=0.0, max_iterations=1)

    # 损坏 intent 触发通用 Exception 分支 → 写 ERROR result，且 intent 被清理
    assert result_path.exists()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ERROR"
    assert not intent_path.exists()


# ============ poll_loop 捕获 CircuitBreakerBlocked → 写 REJECTED ============
def test_poll_loop_circuit_breaker_blocked_writes_rejected(tmp_path, sink, cb):
    import json
    import datetime
    import mt5_bridge as bridge_mod

    # 先把 cb 推入 COOLDOWN
    t0 = datetime.datetime(2026, 8, 22, 10, 0, 0)
    cb.record_trade(-5.0, now=t0)
    cb.record_trade(-5.0, now=t0 + datetime.timedelta(minutes=1))

    intent_path = tmp_path / "order_intent.json"
    result_path = tmp_path / "execution_result.json"
    intent_path.write_text(json.dumps(_intent(2000.0, 1995.0, 0.01, "BUY")), encoding="utf-8")

    bridge_mod.INTENT_PATH = str(intent_path)
    bridge_mod.RESULT_PATH = str(result_path)

    bridge_mod.poll_loop(cb, sink, SPEC, mt5_client=None, interval=0.0, max_iterations=1)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "REJECTED"
    assert not intent_path.exists()


# ============ poll_loop 捕获 MissingSLRejected → 写 REJECTED ============
def test_poll_loop_missing_sl_writes_rejected(tmp_path, sink, cb):
    import json
    import mt5_bridge as bridge_mod

    intent_path = tmp_path / "order_intent.json"
    result_path = tmp_path / "execution_result.json"
    bad_intent = {
        "symbol": "XAUUSD", "direction": "BUY",
        "entry_price": 2000.0, "invalidation_price": None, "lots": 0.01,
    }
    intent_path.write_text(json.dumps(bad_intent), encoding="utf-8")

    bridge_mod.INTENT_PATH = str(intent_path)
    bridge_mod.RESULT_PATH = str(result_path)

    bridge_mod.poll_loop(cb, sink, SPEC, mt5_client=None, interval=0.0, max_iterations=1)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "REJECTED"
    assert not intent_path.exists()


# ============ poll_loop：os.remove 抛 OSError 时被静默忽略（229-230） ============
def test_poll_loop_remove_oserror_ignored(tmp_path, sink, cb, monkeypatch):
    import json
    import os
    import mt5_bridge as bridge_mod

    intent_path = tmp_path / "order_intent.json"
    result_path = tmp_path / "execution_result.json"
    intent_path.write_text(json.dumps(_intent(2000.0, 1995.0, 0.01, "BUY")), encoding="utf-8")

    bridge_mod.INTENT_PATH = str(intent_path)
    bridge_mod.RESULT_PATH = str(result_path)

    def fake_remove(p):
        raise OSError("simulated lock")

    monkeypatch.setattr(os, "remove", fake_remove)

    bridge_mod.poll_loop(cb, sink, SPEC, mt5_client=None, interval=0.0, max_iterations=1)

    # FILLED 仍写出（删除失败被忽略，不阻塞）
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "FILLED"


# ============ poll_loop：多轮迭代触发 time.sleep（235） ============
def test_poll_loop_multi_iteration_sleeps(tmp_path, sink, cb, monkeypatch):
    import json
    import time
    import mt5_bridge as bridge_mod

    intent_path = tmp_path / "order_intent.json"
    result_path = tmp_path / "execution_result.json"
    intent_path.write_text(json.dumps(_intent(2000.0, 1995.0, 0.01, "BUY")), encoding="utf-8")

    bridge_mod.INTENT_PATH = str(intent_path)
    bridge_mod.RESULT_PATH = str(result_path)

    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    bridge_mod.poll_loop(cb, sink, SPEC, mt5_client=None, interval=0.0, max_iterations=2)

    # 第1轮处理完 intent 后被删，第2轮无 intent 直接 sleep → sleep 被调用
    assert len(slept) >= 1

