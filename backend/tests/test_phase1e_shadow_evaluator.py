# -*- coding: utf-8 -*-
"""
test_phase1e_shadow_evaluator.py —— Phase 1E 验收（PRD §7 Release Gate / Shadow 评估）。

不依赖 pytest。直接 `python backend/tests/test_phase1e_shadow_evaluator.py` 运行。
用临时 DB（monkeypatch DB_PATH），不污染生产库。

覆盖断言：
  A. Shadow 评估指标计算正确（样本/MATCH-DIFF/veto/EXTREME 覆盖/position diff/veto 等价/非EXTREME意外DIFF/replay drift）
  B. 接管判定红线：
     - PASS：样本>=10 且 replay drift=0 且 非EXTREME意外DIFF=0 且 veto 等价 且 GM 通过
     - HOLD：样本<10 / replay drift>0 / 非EXTREME意外DIFF>0 / veto 不等价 → 任一即 HOLD
  C. Release Gate（人工批准，非脚本自动翻 flag）：
     - 默认 is_approved=False；record_approval 后 True；revoke 后 False
     - is_enabled() 接 gate：常量=0 恒 False；常量=1 + gate 批准=True；=1 + 未批准=False
  D. approve_risk_guard_takeover：
     - evaluate 非 PASS → 拒绝批准
     - 未 --confirm → 拒绝批准
     - PASS + 确认 → 写 APPROVED gate（但绝不改 RISK_GUARD_ENABLED）
"""
import os
import sys
import json
import tempfile
import shutil
import sqlite3
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

import database.models as models  # noqa: E402
import risk_guard  # noqa: E402
import shadow_evaluator as ev  # noqa: E402
import release_gate  # noqa: E402
import approve_risk_guard_takeover as approver  # noqa: E402


_TMP = None


def _setup_tmp_db():
    global _TMP
    _TMP = tempfile.mkdtemp(prefix="eval_test_")
    models.DB_PATH = Path(_TMP) / "vibe_research.db"
    models.init_db()
    return _TMP


def _insert_run(rid, trade_date, prod_can_buy, prod_direction, prod_position,
                shadow_can_buy, shadow_direction, shadow_position, shadow_veto,
                diff, ic_risk_state):
    conn = sqlite3.connect(str(models.DB_PATH))
    conn.execute(
        "INSERT INTO decision_run (run_id, trade_date, triggered_by, market_snapshot, "
        "versions_json, snapshot_id, shadow_mode, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (rid, trade_date, "test", "{}", "{}", "snap", 1, 1.0))
    conn.execute(
        """INSERT INTO decision_item
           (item_id, run_id, parent_item_id, item_type, asset, layer, decision, decision_basis,
            direction, score, evidence_ref, risk_state, veto, confidence,
            position_limit_min, position_limit_max, position_limit_label,
            invalidation, human_decision, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid + "_IC", rid, None, "IC", None, "IC", "YES", "SCORE", prod_direction, 70.0,
         "[]", ic_risk_state, None, None, None, None, None, None, None, 1.0))
    conn.execute(
        """INSERT INTO shadow_run
           (run_id, prod_can_buy, prod_direction, prod_position, shadow_can_buy,
            shadow_direction, shadow_position, shadow_veto, diff, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (rid, prod_can_buy, prod_direction, prod_position, shadow_can_buy,
         shadow_direction, shadow_position, shadow_veto, diff, 1.0))
    conn.commit()
    conn.close()


def _extreme_run(rid, td):
    _insert_run(rid, td, "NO", "震荡", "<30%（或空仓）", "NO", "震荡", "<30%",
                "True", "MATCH", "EXTREME")


def _normal_run(rid, td):
    _insert_run(rid, td, "YES", "看多", "30-50%", "YES", "看多", "30-50%",
                "False", "MATCH", "HIGH")


def _assert(cond, msg):
    if not cond:
        raise AssertionError("FAIL: " + msg)
    print("  PASS:", msg)


def _fake_replay_clean(*a, **k):
    return {"samples": 0, "cross_check": {"drifts": []}, "all_match": True,
            "risk_states": {}, "veto_count": 0, "deterministic": True, "rows": []}


def main():
    # ---- 守卫：Phase 1E 默认仍 Shadow，绝不自动接管 ----
    _assert(risk_guard.RISK_GUARD_ENABLED == 0, "RISK_GUARD_ENABLED == 0（默认 Shadow）")
    _assert(risk_guard.is_shadow(), "is_shadow() == True")
    _assert(not risk_guard.is_enabled(), "is_enabled() == False（生产仍由旧 IC 决定）")

    # ===== A/B. 评估指标 + 判定红线（监控 replay 为干净、GM 关闭以隔离）=====
    tmp = _setup_tmp_db()
    try:
        # 12 个 clean 样本：8 EXTREME(veto) + 4 非 EXTREME，全部 MATCH
        for i in range(8):
            _extreme_run(f"2026-08-{10+i:02d}_r{i}", f"2026-08-{10+i:02d}")
        for i in range(4):
            _normal_run(f"2026-08-20_r{i}", f"2026-08-2{i%9 + 1:02d}")
        with mock.patch.object(ev.replay_engine, "replay_all", _fake_replay_clean):
            res = ev.evaluate(db_path=str(models.DB_PATH), run_golden_master=False)
        m = res["metrics"]
        _assert(m["samples"]["shadow_run_count"] == 12, "样本数=12（>=10）")
        _assert(m["match_diff"]["match_count"] == 12 and m["match_diff"]["diff_count"] == 0,
                "MATCH=12 / DIFF=0")
        _assert(m["shadow_veto"]["count"] == 8, "Shadow veto=8（EXTREME 全部否决）")
        _assert(m["extreme_coverage"]["extreme_count"] == 8 and m["extreme_coverage"]["all_extreme_vetoed"],
                "EXTREME 覆盖=8 且全部被 veto")
        _assert(m["position_diff"]["mismatch_count"] == 8, "仓位差异=8（by-design 仅 EXTREME 时不同）")
        _assert(m["veto_equivalence"]["equivalent"], "veto 逻辑 100% 等价（violations=0）")
        _assert(m["non_extreme_unexpected_diff"] == 0, "非 EXTREME 意外 DIFF=0")
        _assert(m["replay_drift"] == 0, "replay drift=0")
        _assert(m["golden_master_passed"] is True, "Golden Master 回归=True（run_golden_master=False 隔离）")
        _assert(all(c["passed"] for c in res["checks"]), "全部检查项 PASS")
        _assert(res["verdict"] == "PASS", "判定结论=PASS（满足全部接管前提）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ===== B. HOLD：样本不足 =====
    tmp = _setup_tmp_db()
    try:
        for i in range(5):
            _normal_run(f"2026-08-0{i+1}_r{i}", f"2026-08-0{i+1}")
        with mock.patch.object(ev.replay_engine, "replay_all", _fake_replay_clean):
            res = ev.evaluate(db_path=str(models.DB_PATH), run_golden_master=False)
        _assert(res["verdict"] == "HOLD", "HOLD：样本<10（仅 5）")
        _assert(not res["checks"][0]["passed"], "检查项[样本>=10] FAIL")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ===== B. HOLD：非 EXTREME 意外 DIFF =====
    tmp = _setup_tmp_db()
    try:
        for i in range(10):
            _normal_run(f"2026-08-0{i+1}_r{i}", f"2026-08-0{i+1}")
        # 注入 1 条 MEDIUM 但 diff != MATCH
        _insert_run("2026-08-99_rx", "2026-08-99", "YES", "看多", "30-50%", "NO", "看多",
                    "30-50%", "False", json.dumps({"prod_can_buy": "YES", "shadow_can_buy": "NO"}), "MEDIUM")
        with mock.patch.object(ev.replay_engine, "replay_all", _fake_replay_clean):
            res = ev.evaluate(db_path=str(models.DB_PATH), run_golden_master=False)
        _assert(res["metrics"]["non_extreme_unexpected_diff"] == 1, "非EXTREME意外DIFF=1")
        _assert(res["verdict"] == "HOLD", "HOLD：非 EXTREME 意外 DIFF>0")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ===== B. HOLD：veto 不等价 =====
    tmp = _setup_tmp_db()
    try:
        for i in range(10):
            _normal_run(f"2026-08-0{i+1}_r{i}", f"2026-08-0{i+1}")
        # 注入 1 条 shadow_veto=True 但 risk_state=MEDIUM（非 EXTREME）
        _insert_run("2026-08-99_rv", "2026-08-99", "YES", "看多", "30-50%", "NO", "看多",
                    "30-50%", "True", json.dumps({"prod_can_buy": "YES", "shadow_can_buy": "NO"}), "MEDIUM")
        with mock.patch.object(ev.replay_engine, "replay_all", _fake_replay_clean):
            res = ev.evaluate(db_path=str(models.DB_PATH), run_golden_master=False)
        _assert(res["metrics"]["veto_equivalence"]["violations"] == 1, "veto 等价违规=1")
        _assert(res["verdict"] == "HOLD", "HOLD：veto 逻辑不等价")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ===== B. HOLD：replay drift>0 =====
    tmp = _setup_tmp_db()
    try:
        for i in range(12):
            _normal_run(f"2026-08-0{i+1}_r{i}", f"2026-08-0{i+1}")
        with mock.patch.object(ev.replay_engine, "replay_all",
                              lambda *a, **k: {"cross_check": {"drifts": [{"run_id": "x"}]}}):
            res = ev.evaluate(db_path=str(models.DB_PATH), run_golden_master=False)
        _assert(res["metrics"]["replay_drift"] == 1, "replay drift=1")
        _assert(res["verdict"] == "HOLD", "HOLD：replay drift>0")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ===== C. Release Gate 往返 =====
    tmp = _setup_tmp_db()
    try:
        _assert(not release_gate.is_approved(), "默认 gate 未批准（LOCKED）")
        _assert(release_gate.current_status() == "LOCKED", "current_status=LOCKED")
        gid = release_gate.record_approval("risk_guard_takeover", "JOY", {"samples": 12})
        _assert(gid > 0, "record_approval 返回 gate_id>0")
        _assert(release_gate.is_approved(), "批准后 is_approved=True")
        _assert(release_gate.current_status() == "APPROVED", "current_status=APPROVED")
        release_gate.revoke("risk_guard_takeover", "JOY", "回归观察")
        _assert(not release_gate.is_approved(), "revoke 后 is_approved=False")
        _assert(release_gate.current_status() == "REVOKED", "current_status=REVOKED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ===== C. is_enabled 接 gate 校验 =====
    saved_flag = risk_guard.RISK_GUARD_ENABLED
    try:
        # 常量=0：恒 False（无论 gate）
        risk_guard.RISK_GUARD_ENABLED = 0
        with mock.patch.object(release_gate, "is_approved", lambda f="x": True):
            _assert(not risk_guard.is_enabled(), "常量=0 → is_enabled=False（即便 gate 批准）")
        # 常量=1 + gate 批准 → True
        risk_guard.RISK_GUARD_ENABLED = 1
        with mock.patch.object(release_gate, "is_approved", lambda f="x": True):
            _assert(risk_guard.is_enabled(), "常量=1 + gate 批准 → is_enabled=True")
        # 常量=1 + gate 未批准 → False（锁定，绝不默认接管）
        with mock.patch.object(release_gate, "is_approved", lambda f="x": False):
            _assert(not risk_guard.is_enabled(), "常量=1 + gate 未批准 → is_enabled=False（锁定）")
    finally:
        risk_guard.RISK_GUARD_ENABLED = saved_flag

    # ===== D. approve 脚本：非 PASS 拒绝 / 未确认拒绝 / PASS+确认写 gate（不改 flag）=====
    tmp = _setup_tmp_db()
    try:
        # 非 PASS
        hold_res = {"verdict": "HOLD", "checks": [], "metrics": {}}
        with mock.patch.object(approver.ev, "evaluate", lambda **k: hold_res):
            out = approver.attempt_approval("JOY", True, db_path=str(models.DB_PATH))
        _assert(not out["ok"] and out["reason"] == "eval_not_pass", "evaluate=HOLD → 拒绝批准")
        # 未确认
        pass_res = {"verdict": "PASS", "checks": [], "metrics": {"samples": {"shadow_run_count": 12}}}
        with mock.patch.object(approver.ev, "evaluate", lambda **k: pass_res):
            out = approver.attempt_approval("JOY", False, db_path=str(models.DB_PATH))
        _assert(not out["ok"] and out["reason"] == "not_confirmed", "未 --confirm → 拒绝批准")
        # PASS + 确认 → 写 gate，且 RISK_GUARD_ENABLED 仍=0（脚本不翻 flag）
        with mock.patch.object(approver.ev, "evaluate", lambda **k: pass_res):
            out = approver.attempt_approval("JOY", True, db_path=str(models.DB_PATH))
        _assert(out["ok"] and out.get("gate_id"), "PASS+确认 → 写 APPROVED gate")
        _assert(risk_guard.RISK_GUARD_ENABLED == 0, "approve 脚本绝不改 RISK_GUARD_ENABLED（仍为 0）")
        _assert(release_gate.is_approved(), "gate 已记录 APPROVED（留痕，供人工置常量 1）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL PHASE 1E ASSERTIONS PASSED （Shadow 评估器 + 人工 Release Gate；生产零变化）")


if __name__ == "__main__":
    main()
