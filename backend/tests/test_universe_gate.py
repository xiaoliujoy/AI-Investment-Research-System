"""P0-C Step 3 —— Canonical Universe 门禁（U1/U2/U3）契约测试。

锁定目标（防止回归与防止被"为了方便"改坏）：

  * U1 使用**相对变动率**，不得引入任何绝对成员数常量
    （硬编码 5,557 会在历史回放中必然误报）
  * U2 在 BSE 缺失时**记录而不阻断**（OBSERVE 模式硬要求）
  * U3 必须能捕获 2026-07-21 那种断崖（removed = 4,072）
  * 当前模式强制锁定 OBSERVE，任何情况下 blocking 必须为 False
  * 不修改 `universe.py`（交易所映射复用 `market_of`）

设计原则：全部使用纯函数 `reconcile_codes()`，**不连 DB、不联网、不写库**，
因此不受 conftest 沙箱重定向影响。
"""
import os
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import universe_gate as ug


# ── 交易所映射（复用 C10 契约，不重写前缀规则）──────────────────────────
def test_exchange_of_maps_to_canonical_exchanges():
    assert ug.exchange_of("600000") == "SSE"     # 沪市主板
    assert ug.exchange_of("000001") == "SZSE"    # 深市主板
    assert ug.exchange_of("300750") == "SZSE"    # 创业板
    assert ug.exchange_of("688981") == "SSE"     # 科创板
    assert ug.exchange_of("920001") == "BSE"     # 北交所（治理裁定 INCLUDE）


def test_exchange_of_returns_none_for_non_stock():
    # 新三板 / ETF / 指数等不属于 Canonical Universe 交易所
    assert ug.exchange_of("430001") is None      # 新三板
    assert ug.exchange_of("159919") is None      # ETF
    assert ug.exchange_of("880001") is None      # 通达信板块指数伪代码（88x→「其他」）
    assert ug.exchange_of("") is None


# ── U1：相对变动率，禁止绝对常数 ────────────────────────────────────────
def test_u1_triggers_on_relative_drop_beyond_threshold():
    prev = {f"{600000 + i}" for i in range(1000)}
    today = set(list(prev)[:900])                # -10%
    r = ug.reconcile_codes(today, prev)
    assert r["u1_triggered"] is True
    assert r["delta_pct"] == pytest.approx(-10.0, abs=0.01)


def test_u1_no_trigger_within_threshold():
    prev = {f"{600000 + i}" for i in range(1000)}
    today = set(list(prev)[:996])                # -0.4%（阈值 ±0.5% 内）
    r = ug.reconcile_codes(today, prev)
    assert r["u1_triggered"] is False
    assert abs(r["delta_pct"]) <= ug.U1_MAX_ABS_DELTA_PCT


def test_u1_no_trigger_on_stable_universe():
    codes = {f"{600000 + i:06d}" for i in range(1000)} | {f"{1 + i:06d}" for i in range(1000)}
    r = ug.reconcile_codes(codes, codes)         # 零变动
    assert r["u1_triggered"] is False
    assert r["delta_pct"] == 0.0


def test_u1_is_relative_not_absolute_constant():
    """核心纠偏：同一绝对变动量，在大小不同的基准下判定必须不同。

    若实现误用绝对常数（如 expected=5,557），本测试会失败。
    """
    # 小基准：去掉 100 只 = -10% → 应触发
    small_prev = {f"{600000 + i}" for i in range(1000)}
    small_today = set(list(small_prev)[:900])
    assert ug.reconcile_codes(small_today, small_prev)["u1_triggered"] is True

    # 大基准：同样去掉 100 只 = -1% → 超过 0.5% 仍触发，但变动率必须不同
    big_prev = {f"{600000 + i}" for i in range(10000)}
    big_today = set(list(big_prev)[:9900])
    r_big = ug.reconcile_codes(big_today, big_prev)
    assert r_big["delta_pct"] == pytest.approx(-1.0, abs=0.01)
    assert r_big["delta_pct"] != ug.reconcile_codes(small_today, small_prev)["delta_pct"]


# ── U2：交易所覆盖，OBSERVE 下记录不阻断 ────────────────────────────────
def test_u2_records_missing_bse_without_blocking():
    """BSE=0（当前真实状态）→ 必须被记录，但 OBSERVE 下不得阻断。"""
    today = {f"{600000 + i}" for i in range(500)} | {f"{1 + i:06d}" for i in range(500)}
    r = ug.reconcile_codes(today, today)
    assert "BSE" in r["missing_exchanges"]
    assert r["u2_triggered"] is True
    assert r["blocking"] is False, "OBSERVE 模式下 BSE 缺失绝不可阻断主流水线"


def test_u2_all_exchanges_present_no_trigger():
    today = (
        {f"{600000 + i}" for i in range(300)}     # SSE
        | {f"{1 + i:06d}" for i in range(300)}    # SZSE (00xxxx)
        | {f"{920000 + i}" for i in range(50)}    # BSE
    )
    r = ug.reconcile_codes(today, today)
    assert r["missing_exchanges"] == []
    assert r["u2_triggered"] is False


# ── U3：断崖剔除捕获（回放 2026-07-21 的核心能力）──────────────────────
def test_u3_captures_cliff_removal_4072():
    """回放 2026-07-21：9,327 → 5,260，removed = 4,072。必须被 U3 捕获。"""
    prev = {f"{600000 + i}" for i in range(5000)}
    today = set(list(prev)[:928])                # removed = 5000 - 928 = 4072
    r = ug.reconcile_codes(today, prev)
    assert r["n_removed"] == 4072
    assert r["u3_triggered"] is True
    assert r["u1_triggered"] is True             # -81.4% 同时触发 U1
    assert r["blocking"] is False                # OBSERVE 仍不阻断


def test_u3_no_trigger_on_normal_churn():
    prev = {f"{600000 + i}" for i in range(5000)}
    today = set(list(prev)[:4980]) | {f"{900000 + i}" for i in range(10)}
    r = ug.reconcile_codes(today, prev)
    assert r["n_removed"] <= ug.U3_MAX_REMOVED
    assert r["u3_triggered"] is False


# ── 模式与阻断语义 ─────────────────────────────────────────────────────
def test_mode_is_locked_to_observe():
    """Step 3 硬要求：初始模式必须是 OBSERVE（BSE 未补采，ENFORCE 会上线即红）。"""
    assert ug.UNIVERSE_GATE_MODE == "OBSERVE"


def test_observe_never_blocks_even_on_cliff():
    prev = {f"{600000 + i}" for i in range(5000)}
    today = set(list(prev)[:100])
    r = ug.reconcile_codes(today, prev)
    assert r["triggered"] is True
    assert r["blocking"] is False
    # enforce() 在 OBSERVE 下必须原样返回，不得抛异常
    assert ug.enforce(r) is r


def test_enforce_raises_only_when_mode_is_enforce(monkeypatch):
    prev = {f"{600000 + i}" for i in range(5000)}
    today = set(list(prev)[:100])
    monkeypatch.setattr(ug, "UNIVERSE_GATE_MODE", "ENFORCE")
    r = ug.reconcile_codes(today, prev)
    assert r["blocking"] is True
    with pytest.raises(RuntimeError, match="FAIL_LOUD"):
        ug.enforce(r)


def test_enforce_passes_through_when_clean(monkeypatch):
    # 真正「干净」的 Universe：SSE + SZSE + BSE 三者齐全且零变动，
    # 否则 U2 会因缺失交易所触发 → blocking=True，并非「clean」。
    codes = (
        {f"{600000 + i}" for i in range(900)}      # SSE
        | {f"{1 + i:06d}" for i in range(900)}     # SZSE (00xxxx)
        | {f"{920000 + i}" for i in range(100)}    # BSE
    )
    monkeypatch.setattr(ug, "UNIVERSE_GATE_MODE", "ENFORCE")
    r = ug.reconcile_codes(codes, codes)
    assert r["u1_triggered"] is False
    assert r["u2_triggered"] is False
    assert r["u3_triggered"] is False
    assert r["blocking"] is False
    assert ug.enforce(r) is r


# ── 对账输出结构 ───────────────────────────────────────────────────────
def test_reconcile_reports_added_and_removed():
    prev = {"600001", "600002", "600003"}
    today = {"600001", "600004"}
    r = ug.reconcile_codes(today, prev)
    assert r["added"] == ["600004"]
    assert sorted(r["removed"]) == ["600002", "600003"]
    assert r["n_added"] == 1 and r["n_removed"] == 2


def test_reconcile_handles_empty_prev():
    """首个交易日无基准时不得除零、不得误报。"""
    r = ug.reconcile_codes({"600001"}, [])
    assert r["n_prev"] == 0
    assert r["delta_pct"] == 0.0
    assert r["u1_triggered"] is False


def test_format_report_contains_key_fields():
    prev = {f"{600000 + i}" for i in range(5000)}
    today = set(list(prev)[:928])
    r = ug.reconcile_codes(today, prev)
    txt = ug.format_report(r)
    assert "universe_gate" in txt
    assert "U3(removed=4072)" in txt
