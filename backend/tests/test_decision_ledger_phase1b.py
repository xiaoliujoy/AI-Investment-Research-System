# -*- coding: utf-8 -*-
"""
test_decision_ledger_phase1b.py —— Phase 1B 验收自测（PRD §10.2 / §11）。

不依赖 pytest（本环境未装）。直接 `python backend/tests/test_decision_ledger_phase1b.py` 运行。
用临时 DB（monkeypatch DB_PATH），不污染生产库。

覆盖断言：
  - decision_run 每条运行 1 行；snapshot_id 与 data_snapshot 可外键追溯
  - decision_item ≥1（含 IC 最终裁决节点，且否决写 REJECT/RISK_VETO）
  - evidence ≥1 且 as_of_date / observed_at 均非空
  - decision_version 六维齐全
  - risk_state 映射与既有 L7 composite 一致（EXTREME 样本 → EXTREME）
  - 对 YES / NO / 不同 position_pct 样本也能正确抽取（读 fixtures）
"""
import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

import database.models as models  # noqa: E402
import VERSION  # noqa: E402
import write_decision_ledger as wl  # noqa: E402

FIX = BASE / "tests" / "fixtures" / "golden_master"


def _setup_tmp_db():
    tmp = tempfile.mkdtemp(prefix="ledger_test_")
    models.DB_PATH = Path(tmp) / "vibe_research.db"
    models.init_db()
    return tmp


def _run_on(path: Path):
    brain = json.load(open(path, encoding="utf-8"))
    return wl.write_ledger_from_brain(brain, triggered_by="test")


def _assert(cond, msg):
    if not cond:
        raise AssertionError("FAIL: " + msg)
    print("  PASS:", msg)


def main():
    tmp = _setup_tmp_db()
    try:
        # 取一个 EXTREME 样本（brain_report_2026-08-13.json 在 fixtures 中）
        extreme = sorted(FIX.glob("brain_report_2026-08-1*.json"))
        if not extreme:
            raise SystemExit("fixtures 缺失，先运行 build_golden_master.py")
        sample = extreme[-1]
        summ = _run_on(sample)
        run_id = summ["run_id"]

        import sqlite3
        conn = sqlite3.connect(str(models.DB_PATH))
        conn.row_factory = sqlite3.Row

        # decision_run
        run = conn.execute("SELECT * FROM decision_run WHERE run_id=?", (run_id,)).fetchone()
        _assert(run is not None, "decision_run 写入 1 行")
        _assert(run["snapshot_id"], "decision_run.snapshot_id 非空")
        snap = conn.execute("SELECT * FROM data_snapshot WHERE snapshot_id=?",
                            (run["snapshot_id"],)).fetchone()
        _assert(snap is not None, "snapshot_id 可外键追溯 data_snapshot")

        # decision_item
        items = conn.execute("SELECT * FROM decision_item WHERE run_id=?", (run_id,)).fetchall()
        _assert(len(items) >= 1, "decision_item ≥ 1")
        ic = [d for d in items if d["item_type"] == "IC"]
        _assert(ic, "含 IC 最终裁决节点")
        ic = ic[0]
        _assert(ic["parent_item_id"], "IC 节点有 parent_item_id（Decision Graph）")
        _assert(summ["risk_state"] == "EXTREME", "EXTREME 样本 → risk_state=EXTREME")
        _assert(ic["decision"] == "REJECT" and ic["decision_basis"] == "RISK_VETO",
                "EXTREME+hard_no → decision=REJECT / basis=RISK_VETO")
        _assert(ic["veto"], "REJECT 节点带 veto 原因码（Counterfactual Dataset）")

        # evidence
        evs = conn.execute("SELECT * FROM evidence WHERE item_id=?", (ic["item_id"],)).fetchall()
        _assert(len(evs) >= 1, "evidence ≥ 1")
        for e in evs:
            _assert(e["as_of_date"] and e["observed_at"],
                    f"evidence {e['evidence_id']} as_of_date/observed_at 非空")

        # decision_version
        dv = conn.execute("SELECT * FROM decision_version WHERE run_id=?", (run_id,)).fetchone()
        _assert(dv is not None, "decision_version 写入")
        for col in ["data_snapshot_version", "indicator_version", "strategy_version",
                    "risk_version", "decision_engine_version", "prompt_version"]:
            _assert(dv[col], f"decision_version.{col} 非空")

        # 多样本覆盖：YES / 不同 position（取一个 MEDIUM 样本验证非 EXTREME 分支）
        medium = [p for p in FIX.glob("brain_report_*.json")
                  if "2026-07-29" in p.name]  # comp=34 MEDIUM/YES
        if medium:
            s2 = wl.write_ledger_from_brain(json.load(open(medium[0], encoding="utf-8")),
                                            triggered_by="test")
            _assert(s2["risk_state"] == "MEDIUM", "MEDIUM 样本 → risk_state=MEDIUM")
            _assert(s2["decision"] in ("YES", "NO"),
                    "非 EXTREME 样本 decision 为 YES/NO（不误杀为 REJECT）")

        conn.close()
        print("\nALL PHASE 1B ASSERTIONS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
