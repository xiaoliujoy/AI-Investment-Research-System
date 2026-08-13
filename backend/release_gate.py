# -*- coding: utf-8 -*-
"""
release_gate.py —— v0.2 Phase 1E 人工批准的 Release Gate（PRD §7「最后才允许接管」）。

核心原则（与系统一致）：
  - 学习可以观察生产，不能未经批准改变生产。
  - Risk Guard 接管生产裁决（RISK_GUARD_ENABLED=1 真正生效）必须经由人工 Release Gate 批准。
  - 本模块【只记录】批准/撤销动作，绝不自动翻转 RISK_GUARD_ENABLED
    （那是人工刻意在 backend/risk_guard.py 改常量的动作，须配合本 gate 批准才生效）。

表：release_gate(gate_id, feature, status, approved_by, approved_at,
            eval_snapshot, criteria_hash, notes, created_at)

status ∈ {APPROVED, REVOKED}。is_approved 取该 feature 最新一条记录判断。
"""
from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import database.models as models  # noqa: E402


FEATURE = "risk_guard_takeover"


def _now_iso() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conn(conn=None):
    if conn is not None:
        return conn, False
    return models.get_db(), True


def is_approved(feature: str = FEATURE, conn=None) -> bool:
    """该 feature 最新一条 gate 是否为 APPROVED。无记录/已撤销 → False。"""
    c, own = _conn(conn)
    try:
        row = c.execute(
            "SELECT status FROM release_gate WHERE feature=? "
            "ORDER BY created_at DESC, gate_id DESC LIMIT 1",
            (feature,),
        ).fetchone()
        return bool(row and row["status"] == "APPROVED")
    finally:
        if own:
            c.close()


def current_status(feature: str = FEATURE, conn=None) -> str:
    """该 feature 当前 gate 状态：APPROVED / REVOKED / LOCKED（默认）。"""
    c, own = _conn(conn)
    try:
        row = c.execute(
            "SELECT status FROM release_gate WHERE feature=? "
            "ORDER BY created_at DESC, gate_id DESC LIMIT 1",
            (feature,),
        ).fetchone()
        return row["status"] if row else "LOCKED"
    finally:
        if own:
            c.close()


def record_approval(
    feature: str, approved_by: str, eval_snapshot: dict, notes: str = "", conn=None
) -> int:
    """写入一条 APPROVED gate 记录。仅在人工显式调用（approve_risk_guard_takeover.py）时触发。

    返回 gate_id。绝不在此翻转 RISK_GUARD_ENABLED。
    """
    if not approved_by:
        raise ValueError("approved_by 不能为空（须人工署名）")
    snap = json.dumps(eval_snapshot, ensure_ascii=False, sort_keys=True)
    chash = hashlib.sha256(snap.encode("utf-8")).hexdigest()[:16]
    c, own = _conn(conn)
    try:
        cur = c.execute(
            """INSERT INTO release_gate
               (feature, status, approved_by, approved_at, eval_snapshot, criteria_hash, notes, created_at)
               VALUES (?, 'APPROVED', ?, ?, ?, ?, ?, ?)""",
            (feature, approved_by, _now_iso(), snap, chash, notes, time.time()),
        )
        c.commit()
        return cur.lastrowid
    finally:
        if own:
            c.close()


def revoke(feature: str, by: str, notes: str = "", conn=None) -> int:
    """写入一条 REVOKED gate 记录（人工撤销接管授权）。返回 gate_id。"""
    if not by:
        raise ValueError("revoke by 不能为空（须人工署名）")
    c, own = _conn(conn)
    try:
        cur = c.execute(
            """INSERT INTO release_gate
               (feature, status, approved_by, approved_at, eval_snapshot, criteria_hash, notes, created_at)
               VALUES (?, 'REVOKED', ?, ?, ?, ?, ?, ?)""",
            (feature, by, _now_iso(), "{}", "", notes, time.time()),
        )
        c.commit()
        return cur.lastrowid
    finally:
        if own:
            c.close()
