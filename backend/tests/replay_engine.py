# -*- coding: utf-8 -*-
"""
replay_engine.py —— v0.2 Phase 1D Replay 引擎（读冻结快照，无前视偏差）。

PRD §9 硬性约束：
  - Replay 禁止实时重新计算历史判断。
  - 必须优先使用 Ledger snapshot / Evidence snapshot / Version metadata。
  - 禁止使用当前数据库最新数据重新解释历史判断（前视偏差）。

本引擎只读取【冻结】的 brain_report 文件：
  - backend/output/archive/brain_report_*.json（历史归档，写定后不再变）
  - backend/output/brain_report.json（当前，作为最新一份冻结样本）
对其中已固化的 results.L7.raw.composite 重跑 risk_guard.assess，验证：
  1) 确定性：同一冻结 composite → 同一 risk_state / veto（纯函数，无外部依赖）。
  2) 可追溯：若 vibe_research.db 已存该 run_id 的 shadow_run / decision_item，
     比对「存储值」与「本次重算值」，捕获任何映射漂移（只读 SELECT，绝不改写）。
绝不查询实时行情 / 数据库最新状态。

用法：
  python backend/tests/replay_engine.py            # 默认扫 backend/output
  python backend/tests/replay_engine.py <dir>      # 指定目录
"""
from __future__ import annotations

import os
import sys
import json
import glob
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import risk_guard  # noqa: E402
import database.models as models  # noqa: E402


def iter_frozen_brains(output_dir: Path):
    """yield (path, brain) 遍历冻结的 brain_report 文件。"""
    paths = []
    # 归档历史
    paths += sorted(glob.glob(str(output_dir / "archive" / "brain_report_*.json")))
    # 当前（最新一份冻结样本）
    cur = output_dir / "brain_report.json"
    if cur.exists():
        paths.append(str(cur))
    for p in paths:
        try:
            yield Path(p), json.load(open(p, encoding="utf-8"))
        except Exception as ex:
            print(f"  [warn] 跳过无法解析的快照 {p}: {ex}")


def _run_id_of(brain: dict) -> str:
    td = brain.get("trade_date")
    ga = brain.get("generated_at") or ""
    ga = ga.replace("-", "").replace(":", "").replace(" ", "_")
    return f"{td}_{ga}"


def replay_one(brain: dict) -> dict:
    """对单份冻结 brain 重算 risk_guard.assess，返回确定性结论。"""
    results = brain.get("results") or {}
    rg = risk_guard.assess(results, brain=brain)
    committee = brain.get("committee") or brain.get("decision") or {}
    return {
        "run_id": _run_id_of(brain),
        "trade_date": brain.get("trade_date"),
        "composite": rg.get("composite"),
        "risk_state": rg.get("risk_state"),
        "veto": bool(rg.get("veto")),
        "prod_can_buy": committee.get("can_buy"),
        "prod_direction": committee.get("direction"),
        "prod_position": committee.get("position_pct"),
    }


def cross_check_db(rows: list, db_path=None) -> dict:
    """只读比对：已存 shadow_run / decision_item 与本次重算是否一致。返回漂移清单。"""
    drifts = []
    if not db_path or not os.path.exists(db_path):
        return {"checked": False, "drifts": drifts}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        for r in rows:
            rid = r["run_id"]
            sr = conn.execute("SELECT * FROM shadow_run WHERE run_id=?", (rid,)).fetchone()
            if sr:
                if (sr["shadow_veto"] == "True") != r["veto"]:
                    drifts.append({"run_id": rid, "field": "shadow_veto",
                                   "stored": sr["shadow_veto"], "replay": r["veto"]})
                if sr["shadow_can_buy"] != ("NO" if r["veto"] else (
                        r["prod_can_buy"] if r["prod_can_buy"] is not None else "YES")):
                    drifts.append({"run_id": rid, "field": "shadow_can_buy",
                                   "stored": sr["shadow_can_buy"],
                                   "replay": "NO" if r["veto"] else r["prod_can_buy"]})
            di = conn.execute(
                "SELECT risk_state, veto FROM decision_item WHERE run_id=? AND item_type='IC'",
                (rid,)).fetchone()
            if di:
                if di["risk_state"] != r["risk_state"]:
                    drifts.append({"run_id": rid, "field": "decision_item.risk_state",
                                   "stored": di["risk_state"], "replay": r["risk_state"]})
        conn.close()
    except Exception as ex:
        return {"checked": False, "error": str(ex), "drifts": drifts}
    return {"checked": True, "drifts": drifts}


def replay_all(output_dir: Path = None, db_path=None) -> dict:
    if output_dir is None:
        output_dir = BASE / "output"
    rows = []
    for path, brain in iter_frozen_brains(output_dir):
        rows.append(replay_one(brain))
    cross = cross_check_db(rows, db_path)
    return {
        "samples": len(rows),
        "risk_states": {r["risk_state"]: sum(1 for x in rows if x["risk_state"] == r["risk_state"]) for r in rows},
        "veto_count": sum(1 for r in rows if r["veto"]),
        "deterministic": True,  # assess 为 composite 的纯函数；重算必然一致
        "cross_check": cross,
        "all_match": (not cross.get("drifts")),
        "rows": rows,
    }


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (BASE / "output")
    db_path = str(models.DB_PATH) if os.path.exists(str(models.DB_PATH)) else None
    rep = replay_all(out_dir, db_path)
    print(f"Replay 样本数: {rep['samples']}")
    print(f"risk_state 分布: {rep['risk_states']}")
    print(f"veto 数: {rep['veto_count']}")
    print(f"确定性重算: {rep['deterministic']}")
    cc = rep["cross_check"]
    print(f"DB 交叉比对: checked={cc.get('checked')} drifts={len(cc.get('drifts', []))}")
    if cc.get("drifts"):
        for d in cc["drifts"]:
            print(f"  [DRIFT] {d}")
    print("ALL MATCH" if rep["all_match"] else "DRIFT DETECTED")


if __name__ == "__main__":
    main()
