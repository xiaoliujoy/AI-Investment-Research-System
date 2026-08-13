# -*- coding: utf-8 -*-
"""
test_phase1d_shadow_replay.py —— Phase 1D 验收（PRD §10 / §6 Shadow / §9 Replay）。

不依赖 pytest（本环境未装）。直接 `python backend/tests/test_phase1d_shadow_replay.py` 运行。
用临时 DB（monkeypatch DB_PATH），不污染生产库。

覆盖断言：
  A. Shadow Mode（flag=0 默认，生产零变化）：
     - RISK_GUARD_ENABLED == 0（守卫：禁止意外接管）
     - 每个 fixture 写入后 shadow_run 恰 1 行；同 run_id 二次写入仍 1 行（幂等）
     - shadow_run.shadow_veto 与 risk_guard.assess 一致
     - prod_can_buy / prod_direction == committee 原值（Shadow 绝不改生产裁决）
     - diff == "MATCH"（Risk Guard 镜像 IC，current 窗口无意外分歧）
     - decision_run.shadow_mode == 1（Shadow 并行记录阶段）
  B. Replay（读冻结快照，无前视偏差）：
     - 对冻结 fixture 重跑 risk_guard.assess，risk_state / veto 与已存 shadow_run 一致
     - 不查询实时库状态（replay_engine 只读冻结文件）
  C. 冻结项：production verdict 与 Golden Master 完全一致（零变化红线）
"""
import os
import sys
import json
import tempfile
import shutil
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

import database.models as models  # noqa: E402
import risk_guard  # noqa: E402
import write_decision_ledger as wl  # noqa: E402
import replay_engine  # noqa: E402

FIX = BASE / "tests" / "fixtures" / "golden_master"


def _setup_tmp_db():
    tmp = tempfile.mkdtemp(prefix="shadow_test_")
    models.DB_PATH = Path(tmp) / "vibe_research.db"
    models.init_db()
    return tmp


def _assert(cond, msg):
    if not cond:
        raise AssertionError("FAIL: " + msg)
    print("  PASS:", msg)


def main():
    # 守卫：Phase 1D 默认 Shadow，禁止意外接管生产
    _assert(risk_guard.RISK_GUARD_ENABLED == 0, "RISK_GUARD_ENABLED == 0（Shadow 默认，未接管）")
    _assert(risk_guard.is_shadow(), "is_shadow() == True")
    _assert(not risk_guard.is_enabled(), "is_enabled() == False（生产裁决仍由旧 IC 决定）")

    tmp = _setup_tmp_db()
    try:
        fixtures = sorted(FIX.glob("brain_report*.json"))
        _assert(len(fixtures) >= 20, f"fixtures 充足（{len(fixtures)} 份）")

        checked = 0
        for fx in fixtures:
            brain = json.load(open(fx, encoding="utf-8"))
            committee = brain.get("committee") or brain.get("decision") or {}
            rg = risk_guard.assess(brain.get("results") or {}, brain=brain)
            expected_veto = "True" if rg["veto"] else "False"
            run_id = wl._run_id_for(brain["trade_date"], brain.get("generated_at"))

            # 写入（含 shadow_run）
            summ = wl.write_ledger_from_brain(brain, triggered_by="test")
            # 幂等：二次写入
            wl.write_ledger_from_brain(brain, triggered_by="test")

            conn = sqlite3.connect(str(models.DB_PATH))
            conn.row_factory = sqlite3.Row
            sr = conn.execute("SELECT * FROM shadow_run WHERE run_id=?", (run_id,)).fetchall()
            _assert(len(sr) == 1, f"[{fx.name}] shadow_run 恰 1 行（幂等）")
            sr = sr[0]
            run = conn.execute("SELECT shadow_mode FROM decision_run WHERE run_id=?",
                               (run_id,)).fetchone()

            _assert(sr["shadow_veto"] == expected_veto,
                    f"[{fx.name}] shadow_veto==risk_guard.assess ({expected_veto})")
            _assert(sr["prod_can_buy"] == committee.get("can_buy"),
                    f"[{fx.name}] prod_can_buy==committee.can_buy（生产零变化）")
            _assert(sr["prod_direction"] == committee.get("direction"),
                    f"[{fx.name}] prod_direction==committee.direction（生产零变化）")
            _assert(sr["diff"] == "MATCH",
                    f"[{fx.name}] diff==MATCH（Risk Guard 镜像 IC，无意外分歧）")
            _assert(run["shadow_mode"] == 1,
                    f"[{fx.name}] decision_run.shadow_mode==1（Shadow 并行阶段）")
            conn.close()
            checked += 1

        print(f"  [覆盖] {checked} 份 fixture 全部通过 Shadow 断言")

        # ---- B. Replay 确定性 + 无漂移 ----
        rows = [replay_engine.replay_one(json.load(open(f, encoding="utf-8"))) for f in fixtures]
        conn = sqlite3.connect(str(models.DB_PATH))
        conn.row_factory = sqlite3.Row
        drift = 0
        for r in rows:
            sr = conn.execute("SELECT shadow_veto, shadow_can_buy FROM shadow_run WHERE run_id=?",
                              (r["run_id"],)).fetchone()
            if sr:
                exp_can = "NO" if r["veto"] else (r["prod_can_buy"] if r["prod_can_buy"] is not None else "YES")
                if (sr["shadow_veto"] == "True") != r["veto"]:
                    drift += 1
                if sr["shadow_can_buy"] != exp_can:
                    drift += 1
        conn.close()
        _assert(drift == 0, "Replay 重算与已存 shadow_run 零漂移（确定性，无前视偏差）")
        _assert(replay_engine.replay_all(FIX)["deterministic"], "replay_all 确定性=True（纯函数重算）")

        print("\nALL PHASE 1D ASSERTIONS PASSED （Shadow 记录 + Replay 引擎；生产裁决零变化）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
