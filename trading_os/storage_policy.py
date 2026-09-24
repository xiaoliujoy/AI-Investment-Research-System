# -*- coding: utf-8 -*-
"""
storage_policy.py —— G01 存储边界策略层（MOCK/TEST fail-closed）

【为什么存在】
  G01 实证缺陷：`AttributionSink.__init__` 默认指向 canonical 生产库
  `backend/database/vibe_research.db`，且**构造即 connect + DDL + commit**；
  而 `g2_supervisor.py` / `submit_close.py` 都在判定 mock 分支**之前**就构造了 sink。
  结果是：跑 `--mock` 也会连生产库、建表、提交。

【本层边界（G01-a scope）】
  - 只有 MOCK / TEST 两种模式可以产出存储目标，且目标**必须**是 `":memory:"`。
  - 任何文件形态目标（已存在 / 父目录不存在 / 相对路径 / 大小写变体 / `\\\\?\\` 前缀）
    一律 `raise StoragePolicyError`，**不回退、不降级、不静默改写成 :memory:**。
  - PAPER / PRODUCTION / UNKNOWN 一律拒绝（PRODUCTION 归 G01-b，不在本片）。

【唯一连接点】
  本模块是 `trading_os/` 下**唯一**允许调用 `sqlite3.connect` 的位置。
  静态门禁：`grep -rn "sqlite3.connect" trading_os/` 应只命中本文件 1 处。
  连接以 `PolicyConnection` 包装并携带来源标记，sink 在任何写操作前校验该标记，
  防止调用方先自行 `sqlite3.connect(<canonical>)` 再注入绕过。

【校验强度】
  全部用 `raise`，**零 `assert`**（`python -O` 不得削弱校验）。
  `DbTarget` 需携带策略层签发的令牌，手工构造 / `dataclasses.replace` / 反序列化一律拒绝。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

# 唯一合法的非生产目标形态
MEMORY_TARGET = ":memory:"


class StoragePolicyError(RuntimeError):
    """任何违反存储边界的行为均抛出本异常（fail-closed）。"""


class Mode:
    """运行模式。G01-a 仅 MOCK / TEST 可产出目标。"""

    MOCK = "MOCK"
    TEST = "TEST"
    PAPER = "PAPER"
    PRODUCTION = "PRODUCTION"
    UNKNOWN = "UNKNOWN"

    ALL = (MOCK, TEST, PAPER, PRODUCTION, UNKNOWN)
    ALLOWED_FOR_TARGET = (MOCK, TEST)


# ---------------------------------------------------------------------------
# 模式裁决
# ---------------------------------------------------------------------------
def resolve_mode(*, mock: bool = False, mode_arg: Optional[str] = None) -> str:
    """裁决运行模式。无 I/O。

    - `g2_supervisor --mock` → MOCK
    - `submit_close --mode {mock,test}` → MOCK / TEST
    - 缺失 / 无法识别 → UNKNOWN（后续必然被拒）
    """
    if mock:
        return Mode.MOCK
    if mode_arg is None:
        return Mode.UNKNOWN
    m = str(mode_arg).strip().upper()
    return m if m in Mode.ALL else Mode.UNKNOWN


# ---------------------------------------------------------------------------
# 目标对象（带签发令牌）
# ---------------------------------------------------------------------------
class _Token:
    """策略层内部签发令牌；外部无法构造同 identity 的对象。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return "<policy-token>"


_ISSUE_TOKEN = _Token()


@dataclass(frozen=True)
class DbTarget:
    mode: str
    path: str
    allow_ddl: bool = False
    allow_write: bool = False
    token: Any = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        # 校验 D：非策略层构造 → 拒绝
        if self.token is not _ISSUE_TOKEN:
            raise StoragePolicyError(
                "DbTarget 只能由 storage_policy.resolve_db_target() 创建；"
                "手工构造（含 dataclasses.replace / 反序列化 / 拷贝）一律拒绝。"
            )
        # 校验 A / B / C：目标形态 + 模式自洽 + 授权位自洽
        validate_target(self)


def validate_target(target: Any) -> None:
    """目标校验。可重复调用（resolve 时一次、连接前再一次）。零 I/O。"""
    if not isinstance(target, DbTarget):
        raise StoragePolicyError(f"期望 DbTarget，实际 {type(target).__name__}")

    # 校验 C：PAPER / PRODUCTION / UNKNOWN 不得产出目标
    if target.mode not in Mode.ALLOWED_FOR_TARGET:
        raise StoragePolicyError(
            f"mode={target.mode!r} 不得产出存储目标"
            "（G01-a 仅允许 MOCK/TEST；PRODUCTION 归 G01-b）"
        )

    # 校验 A：MOCK/TEST 必须 :memory:，任何文件形态一律拒绝，不回退
    if target.path != MEMORY_TARGET:
        raise StoragePolicyError(
            f"MOCK/TEST 模式存储目标必须是 '{MEMORY_TARGET}'，收到 {target.path!r}。"
            "任何文件目标（含父目录已存在/不存在、相对路径、大小写变体、"
            "'\\\\?\\' 前缀）一律拒绝，且不回退到 :memory:。"
        )

    # 校验 B：授权位与模式自洽
    if not (target.allow_ddl and target.allow_write):
        raise StoragePolicyError(
            "MOCK/TEST 目标必须同时具备 allow_ddl / allow_write，"
            f"实际 allow_ddl={target.allow_ddl} allow_write={target.allow_write}"
        )


def resolve_db_target(mode: str, db_arg: Optional[str]) -> DbTarget:
    """由模式 + 入参裁决存储目标。无 I/O；失败即 raise。"""
    if mode not in Mode.ALLOWED_FOR_TARGET:
        raise StoragePolicyError(
            f"mode={mode!r} 不得产出存储目标（G01-a 仅允许 MOCK/TEST）"
        )
    if db_arg is not None and db_arg != MEMORY_TARGET:
        raise StoragePolicyError(
            f"{mode} 模式收到显式文件目标 {db_arg!r} → 拒绝，"
            f"且不回退到 '{MEMORY_TARGET}'（fail-closed）"
        )
    return DbTarget(
        mode=mode,
        path=MEMORY_TARGET,
        allow_ddl=True,
        allow_write=True,
        token=_ISSUE_TOKEN,
    )


# ---------------------------------------------------------------------------
# 连接签发（全仓唯一 connect 点）
# ---------------------------------------------------------------------------
class PolicyConnection:
    """策略层签发的连接包装：携带来源标记，供 sink 在写操作前校验。

    只暴露 sink 实际用到的方法，避免把裸连接当成通用句柄外传。
    """

    __slots__ = ("_conn", "policy_issued", "target")

    def __init__(self, conn: sqlite3.Connection, target: DbTarget) -> None:
        self._conn = conn
        self.policy_issued = True
        self.target = target

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()


def open_connection(target: DbTarget) -> PolicyConnection:
    """创建连接。调用前**再次** validate_target（防 TOCTOU / 目标被篡改）。

    ⚠️ 这是 `trading_os/` 全仓唯一的 `sqlite3.connect` 调用点。
    """
    validate_target(target)  # 二次校验
    # check_same_thread=False：G2 守护后台线程消费平仓并落库，连接须跨线程
    conn = sqlite3.connect(target.path, check_same_thread=False)
    return PolicyConnection(conn, target)


def assert_policy_issued(conn: Any) -> None:
    """写操作前的连接来源校验：非策略层签发的连接一律拒绝。"""
    if not isinstance(conn, PolicyConnection) or getattr(conn, "policy_issued", False) is not True:
        raise StoragePolicyError(
            "连接非 storage_policy 签发（外部注入 / 伪造 / 未 open）→ 拒绝执行写操作"
        )


# ---------------------------------------------------------------------------
# 便捷入口（供单测显式声明 TEST 模式）
# ---------------------------------------------------------------------------
def test_target() -> DbTarget:
    return resolve_db_target(Mode.TEST, MEMORY_TARGET)
