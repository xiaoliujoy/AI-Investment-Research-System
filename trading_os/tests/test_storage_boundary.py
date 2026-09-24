# -*- coding: utf-8 -*-
"""
test_storage_boundary.py
G01 —— 存储边界回归 + 对抗性验证（MOCK/TEST fail-closed）

【覆盖目标（对应 R8 最低验收条件）】
  A. 模式 / 目标裁决矩阵
  B. 文件目标一律拒绝（含父目录已存在 / 不存在 / 相对路径 / 大小写变体 / \\\\?\\ 前缀）
  C. 构造期零 I/O（0 connect / 0 DDL / 0 commit）
  D. DDL / 写入授权位运行时校验
  E. 连接来源校验（外部注入的裸连接必须被拒）
  F. 两个生产入口分别覆盖（g2_supervisor / submit_close --serve）
  G. 静态门禁（唯一 connect 点 / 零 assert / 无生产库默认常量）

【方法学】
  call recording（记录 sqlite3.connect 实参）+ fake + tmp path + exit code 断言。
  **不检查 canonical DB 前后状态**（该判据已从验收中移除）。
"""
from __future__ import annotations
import os
import sys
import sqlite3
import dataclasses

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
TRADING_OS = os.path.dirname(_HERE)
if TRADING_OS not in sys.path:
    sys.path.insert(0, TRADING_OS)

import storage_policy as SP
from storage_policy import Mode, DbTarget, StoragePolicyError, MEMORY_TARGET
from attribution_sink import AttributionSink
import g2_supervisor as G
import submit_close as SC


# ---------------------------------------------------------------------------
# 工具：connect 调用记录器（阻断式 guard，隔离由构造保证）
# ---------------------------------------------------------------------------
class ConnectRecorder:
    def __init__(self):
        self.calls: list = []
        self._real = sqlite3.connect

    def install(self, monkeypatch):
        def _fake(*args, **kwargs):
            self.calls.append({"args": args, "kwargs": kwargs})
            return self._real(*args, **kwargs)
        monkeypatch.setattr(sqlite3, "connect", _fake)
        return self

    @property
    def paths(self):
        return [c["args"][0] for c in self.calls if c["args"]]

    @property
    def n(self):
        return len(self.calls)


@pytest.fixture
def rec(monkeypatch):
    return ConnectRecorder().install(monkeypatch)


# ---------------------------------------------------------------------------
# 组 A —— 模式 / 目标裁决
# ---------------------------------------------------------------------------
def test_a1_mock_and_test_default_to_memory():
    for m in (Mode.MOCK, Mode.TEST):
        t = SP.resolve_db_target(m, None)
        assert t.path == MEMORY_TARGET
        assert t.allow_ddl is True and t.allow_write is True


def test_a2_explicit_memory_ok():
    assert SP.resolve_db_target(Mode.TEST, ":memory:").path == MEMORY_TARGET


def test_a3_resolve_mode_matrix():
    assert SP.resolve_mode(mock=True) == Mode.MOCK
    assert SP.resolve_mode(mock=False, mode_arg="test") == Mode.TEST
    assert SP.resolve_mode(mock=False, mode_arg="mock") == Mode.MOCK
    assert SP.resolve_mode(mock=False, mode_arg=None) == Mode.UNKNOWN
    assert SP.resolve_mode(mock=False, mode_arg="bogus") == Mode.UNKNOWN


def test_a4_unknown_paper_production_rejected():
    for m in (Mode.UNKNOWN, Mode.PAPER, Mode.PRODUCTION):
        with pytest.raises(StoragePolicyError):
            SP.resolve_db_target(m, None)
        with pytest.raises(StoragePolicyError):
            SP.resolve_db_target(m, ":memory:")


# ---------------------------------------------------------------------------
# 组 B —— 文件目标一律拒绝（不回退、不降级）
# ---------------------------------------------------------------------------
def test_b1_canonical_production_path_rejected():
    canon = os.path.join("backend", "database", "vibe_research.db")
    with pytest.raises(StoragePolicyError) as e:
        SP.resolve_db_target(Mode.MOCK, canon)
    assert "不回退" in str(e.value)


def test_b2_file_target_variants_rejected(tmp_path):
    variants = [
        str(tmp_path / "existing_parent.db"),                       # 父目录已存在
        str(tmp_path / "no_such_dir" / "child.db"),                 # 父目录不存在
        "relative_attrib.db",                                        # 相对路径
        str(tmp_path / "UPPER.DB"),                                  # 大小写变体
        "\\\\?\\" + str(tmp_path / "prefixed.db"),                   # \\?\ 前缀
        ":memory",                                                   # 近似但非 :memory:
        " :memory:",                                                 # 前后空白
    ]
    for v in variants:
        for m in (Mode.MOCK, Mode.TEST):
            with pytest.raises(StoragePolicyError):
                SP.resolve_db_target(m, v)


def test_b3_rejection_creates_nothing(tmp_path):
    target = str(tmp_path / "must_not_exist" / "x.db")
    with pytest.raises(StoragePolicyError):
        SP.resolve_db_target(Mode.MOCK, target)
    assert not os.path.exists(target)
    assert not os.path.exists(os.path.dirname(target))


# ---------------------------------------------------------------------------
# 组 C —— 构造期零副作用
# ---------------------------------------------------------------------------
def test_c1_sink_construction_zero_io(rec):
    AttributionSink(db_target=SP.test_target())
    assert rec.n == 0, f"构造期不得产生任何 connect，实际 {rec.calls}"


def test_c2_open_connects_memory_only(rec):
    s = AttributionSink(db_target=SP.test_target())
    s.open()
    assert rec.n == 1
    assert rec.paths == [MEMORY_TARGET]
    s.close()


def test_c3_legacy_db_path_signature_rejected():
    with pytest.raises(StoragePolicyError):
        AttributionSink(db_path=":memory:")   # 旧签名必须彻底失效
    with pytest.raises(StoragePolicyError):
        AttributionSink(":memory:")


# ---------------------------------------------------------------------------
# 组 D —— DDL / 写入授权位运行时校验
# ---------------------------------------------------------------------------
def _sink_with(attr, value):
    s = AttributionSink(db_target=SP.test_target())
    object.__setattr__(s.target, attr, value)   # 绕过 frozen 以测试运行时门禁
    return s


def test_d1_ddl_gate():
    s = _sink_with("allow_ddl", False)
    with pytest.raises(StoragePolicyError):
        s.ensure_schema()
    with pytest.raises(StoragePolicyError):
        s.open()


def test_d2_write_gate():
    s = AttributionSink(db_target=SP.test_target())
    s.open()
    object.__setattr__(s.target, "allow_write", False)   # 连接建立后才篡夺授权位
    s.open_position(
        order_id="T1", symbol="XAUUSD", direction="BUY", entry_price=2000.0,
        sl_price=1990.0, requested_lots=0.1, filled_lots=0.1, fill_price=2000.0,
        max_loss_usd=100.0, spread_points=3.0, slippage_points=0.0, open_ts="t",
    )
    with pytest.raises(StoragePolicyError):
        s.close_position("T1", 2010.0, "MANUAL", 100.0)
    s.close()


def test_d3_not_opened_refuses_write():
    s = AttributionSink(db_target=SP.test_target())
    with pytest.raises(StoragePolicyError):
        s.get_record("whatever")


# ---------------------------------------------------------------------------
# 组 E —— 连接来源校验（防外部注入）
# ---------------------------------------------------------------------------
def test_e1_raw_connection_rejected():
    raw = sqlite3.connect(":memory:")
    with pytest.raises(StoragePolicyError):
        SP.assert_policy_issued(raw)
    raw.close()


def test_e2_injected_connection_rejected_on_write():
    s = AttributionSink(db_target=SP.test_target())
    s.open()
    raw = sqlite3.connect(":memory:")
    s._conn = raw                      # 模拟调用方偷换连接
    s.open_position(
        order_id="T2", symbol="XAUUSD", direction="BUY", entry_price=2000.0,
        sl_price=1990.0, requested_lots=0.1, filled_lots=0.1, fill_price=2000.0,
        max_loss_usd=100.0, open_ts="t",
    )
    with pytest.raises(StoragePolicyError):
        s.close_position("T2", 2010.0, "MANUAL", 100.0)
    with pytest.raises(StoragePolicyError):
        s.get_record("T2")
    raw.close()


def test_e3_handmade_target_rejected():
    with pytest.raises(StoragePolicyError):
        DbTarget(mode=Mode.TEST, path=":memory:", allow_ddl=True, allow_write=True)


def test_e4_dataclasses_replace_rejected():
    t = SP.test_target()
    with pytest.raises(StoragePolicyError):
        dataclasses.replace(t, path="/tmp/evil.db")


# ---------------------------------------------------------------------------
# 组 F —— 两个生产入口分别覆盖
# ---------------------------------------------------------------------------
def _run(fn, argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", argv)
    return fn()


def test_f1_g2_supervisor_mock_memory_only(rec, monkeypatch):
    monkeypatch.setattr(G, "supervise", lambda *a, **k: None)
    _run(G.main, ["g2_supervisor.py", "--mock"], monkeypatch)
    assert rec.n >= 1
    assert set(rec.paths) == {MEMORY_TARGET}, f"出现非 :memory: 目标：{rec.paths}"


def test_f2_g2_supervisor_nonmock_rejected_zero_connect(rec, monkeypatch):
    monkeypatch.setattr(G, "supervise", lambda *a, **k: None)
    with pytest.raises(SystemExit) as e:
        _run(G.main, ["g2_supervisor.py"], monkeypatch)
    assert e.value.code == 2
    assert rec.n == 0, "非 mock 模式必须零 connect（fail-closed）"


def test_f3_g2_supervisor_mock_with_file_db_rejected(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(G, "supervise", lambda *a, **k: None)
    p = str(tmp_path / "evil.db")
    with pytest.raises(SystemExit) as e:
        _run(G.main, ["g2_supervisor.py", "--mock", "--db", p], monkeypatch)
    assert e.value.code == 2
    assert rec.n == 0
    assert not os.path.exists(p)


def test_f4_submit_close_serve_requires_mode(rec, monkeypatch):
    monkeypatch.setattr(SC, "close_loop", lambda *a, **k: None)
    with pytest.raises(SystemExit) as e:
        _run(SC.main, ["submit_close.py", "--serve"], monkeypatch)
    assert e.value.code == 2
    assert rec.n == 0


def test_f5_submit_close_serve_mock_memory_only(rec, monkeypatch):
    monkeypatch.setattr(SC, "close_loop", lambda *a, **k: None)
    _run(SC.main, ["submit_close.py", "--serve", "--mode", "mock"], monkeypatch)
    assert rec.n >= 1
    assert set(rec.paths) == {MEMORY_TARGET}, f"出现非 :memory: 目标：{rec.paths}"


def test_f6_submit_close_serve_file_db_rejected(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(SC, "close_loop", lambda *a, **k: None)
    p = str(tmp_path / "evil2.db")
    with pytest.raises(SystemExit) as e:
        _run(SC.main, ["submit_close.py", "--serve", "--mode", "mock", "--db", p], monkeypatch)
    assert e.value.code == 2
    assert rec.n == 0
    assert not os.path.exists(p)


# ---------------------------------------------------------------------------
# 组 G —— 静态门禁
# ---------------------------------------------------------------------------
def _src(name):
    with open(os.path.join(TRADING_OS, name), "r", encoding="utf-8") as f:
        return f.read()


def test_g1_single_connect_point():
    """trading_os/*.py 下 sqlite3.connect(...) 的真实调用点必须且只能是 storage_policy.py。"""
    import ast
    hits = []
    for fn in sorted(os.listdir(TRADING_OS)):
        if not fn.endswith(".py"):
            continue
        tree = ast.parse(_src(fn))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "connect":
                if isinstance(f.value, ast.Name) and f.value.id == "sqlite3":
                    hits.append(f"{fn}:{node.lineno}")
    assert len(hits) == 1, (
        f"trading_os/ 下 sqlite3.connect 调用必须且只能有 1 处（storage_policy.py），实际：{hits}"
    )
    assert hits[0].startswith("storage_policy.py")


def test_g2_no_assert_in_policy():
    import re
    for i, line in enumerate(_src("storage_policy.py").splitlines(), 1):
        assert not re.match(r"\s*assert\s", line), (
            f"storage_policy.py:{i} 出现 assert —— python -O 会跳过，违反 fail-closed"
        )


def test_g3_no_production_db_default_constant():
    for fn in ("g2_supervisor.py", "submit_close.py", "attribution_sink.py"):
        body = _src(fn)
        assert "vibe_research.db" not in body, (
            f"{fn} 仍出现 canonical 生产库路径字面量（G01 要求彻底移除默认生产目标）"
        )
