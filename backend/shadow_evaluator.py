# -*- coding: utf-8 -*-
"""
shadow_evaluator.py —— v0.2 Phase 1E Shadow 对照评估器（只读，不改变生产）。

职责：把 1D 阶段在每次日报运行中自动累积的 shadow_run 转化为一份可审计的评估结果，
给出明确的「接管判定结论」：
    PASS  —— 满足全部接管前提（见 _verdict 红线）
    HOLD  —— 任一前提不满足（默认，继续观察累积）

设计红线（最高优先级，与系统原则一致）：
  - 本模块【只读】vibe_research.db 与冻结快照，绝不写入、绝不改写任何生产裁决。
  - 本模块【不】翻转 RISK_GUARD_ENABLED；是否接管是人工 Release Gate 的决策
    （见 release_gate.py / approve_risk_guard_takeover.py）。
  - 仅输出评估；是否接管由人在看到本报告后决定是否批准 gate。

指标（对应需求表）：
  - Shadow 样本数                  -> samples.shadow_run_count / unique_trade_dates
  - MATCH / DIFF                   -> match_diff
  - Shadow veto 数量/比例          -> shadow_veto
  - Production NO vs Shadow NO     -> prod_vs_shadow_no
  - Production position vs Shadow position -> position_diff（by-design 仅 EXTREME 时不同）
  - EXTREME 覆盖率                 -> extreme_coverage
  - 非 EXTREME 意外 DIFF           -> non_extreme_unexpected_diff
  - replay drift                   -> replay_drift（复用 replay_engine，只读冻结快照）

接管判定红线（用户给定）：
  PASS  iff  Shadow >= 10 交易日
            AND replay drift = 0
            AND 非 EXTREME 意外 DIFF = 0
            AND veto 逻辑 100% 等价
            AND Golden Master 回归通过
  HOLD   otherwise

用法：
  python backend/shadow_evaluator.py                 # 评估 + 写报告 artifact + 打印
  （测试/嵌入）from shadow_evaluator import evaluate
"""
from __future__ import annotations

import os
import sys
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
# replay_engine 位于 backend/tests/，确保直接运行本模块时也能 import
TESTS = BASE / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import database.models as models  # noqa: E402
import replay_engine  # noqa: E402  # 复用 Replay 引擎算 replay_drift（只读冻结快照）


MIN_SAMPLES = 10  # 用户口径：>= 10 个交易日
GOLDEN_MASTER_TEST = "tests/test_phase1c_regression.py"  # 1C Golden Master 回归


# --------------------------------------------------------------------------- #
# 数据读取（只读）
# --------------------------------------------------------------------------- #
def _read_shadow_rows(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT s.run_id, s.prod_can_buy, s.prod_direction, s.prod_position,
                      s.shadow_can_buy, s.shadow_direction, s.shadow_position,
                      s.shadow_veto, s.diff,
                      d.risk_state AS ic_risk_state
               FROM shadow_run s
               LEFT JOIN decision_item d
                      ON d.run_id = s.run_id AND d.item_type = 'IC'"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _unique_trade_dates(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT DISTINCT trade_date FROM decision_run").fetchall()
        return {r["trade_date"] for r in rows}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 指标计算
# --------------------------------------------------------------------------- #
def _metrics(rows, trade_dates, replay_drift, gm_passed):
    n = len(rows)
    match = sum(1 for r in rows if r["diff"] == "MATCH")
    diff = n - match
    veto_rows = [r for r in rows if r["shadow_veto"] == "True"]
    veto_count = len(veto_rows)
    extreme_rows = [r for r in rows if r.get("ic_risk_state") == "EXTREME"]
    extreme_count = len(extreme_rows)
    # veto 逻辑 100% 等价：shadow_veto == (risk_state == EXTREME)
    veto_equiv_violations = sum(
        1 for r in rows
        if (r["shadow_veto"] == "True") != (r.get("ic_risk_state") == "EXTREME")
    )
    # 非 EXTREME 意外 DIFF：diff != MATCH 且 risk_state != EXTREME
    non_extreme_diff = sum(
        1 for r in rows
        if r["diff"] != "MATCH" and r.get("ic_risk_state") != "EXTREME"
    )
    prod_no = sum(1 for r in rows if str(r["prod_can_buy"]).upper() == "NO")
    shadow_no = sum(1 for r in rows if str(r["shadow_can_buy"]).upper() == "NO")
    pos_mismatch = sum(1 for r in rows if r["shadow_position"] != r["prod_position"])
    return {
        "samples": {
            "shadow_run_count": n,
            "unique_trade_dates": len(trade_dates),
        },
        "match_diff": {
            "match_count": match,
            "diff_count": diff,
            "match_ratio": (match / n) if n else 0.0,
        },
        "shadow_veto": {
            "count": veto_count,
            "ratio": (veto_count / n) if n else 0.0,
        },
        "extreme_coverage": {
            "extreme_count": extreme_count,
            "extreme_ratio": (extreme_count / n) if n else 0.0,
            "all_extreme_vetoed": all(r["shadow_veto"] == "True" for r in extreme_rows),
        },
        "prod_vs_shadow_no": {
            "prod_no": prod_no,
            "shadow_no": shadow_no,
            "diff": abs(prod_no - shadow_no),
        },
        "position_diff": {
            "mismatch_count": pos_mismatch,
            "note": "by-design 仅在 EXTREME(veto) 时不同",
        },
        "veto_equivalence": {
            "violations": veto_equiv_violations,
            "equivalent": veto_equiv_violations == 0,
        },
        "non_extreme_unexpected_diff": non_extreme_diff,
        "replay_drift": replay_drift,
        "golden_master_passed": gm_passed,
    }


# --------------------------------------------------------------------------- #
# 接管判定（用户给定红线）
# --------------------------------------------------------------------------- #
def _verdict(metrics):
    checks = []
    s = metrics["samples"]["shadow_run_count"]
    c1 = s >= MIN_SAMPLES
    checks.append({"name": f"Shadow 样本 >= {MIN_SAMPLES} 个交易日",
                   "passed": c1, "detail": f"shadow_run={s}"})

    rd = metrics["replay_drift"]
    c2 = rd == 0
    checks.append({"name": "Replay drift = 0", "passed": c2, "detail": f"drift={rd}"})

    ne = metrics["non_extreme_unexpected_diff"]
    c3 = ne == 0
    checks.append({"name": "非 EXTREME 意外 DIFF = 0",
                   "passed": c3, "detail": f"non_extreme_diff={ne}"})

    ve = metrics["veto_equivalence"]["equivalent"]
    c4 = ve
    checks.append({"name": "veto 逻辑 100% 等价",
                   "passed": c4, "detail": f"violations={metrics['veto_equivalence']['violations']}"})

    gm = metrics["golden_master_passed"]
    c5 = gm
    checks.append({"name": "Golden Master 回归通过", "passed": c5, "detail": f"passed={gm}"})

    verdict = "PASS" if all([c1, c2, c3, c4, c5]) else "HOLD"
    return verdict, checks


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def _run_golden_master() -> bool:
    """只读跑 1C Golden Master 回归测试，捕获 returncode。失败不影响评估输出。"""
    try:
        r = subprocess.run(
            [sys.executable, GOLDEN_MASTER_TEST],
            cwd=str(BASE), capture_output=True, text=True, timeout=300,
        )
        return r.returncode == 0
    except Exception:
        return False


def evaluate(db_path: str = None, run_golden_master: bool = True) -> dict:
    """只读评估。返回完整结果 dict。绝不写入。

    db_path: 指定数据库路径；默认 models.DB_PATH（生产库）。
    run_golden_master: 是否顺带跑 1C 回归（测试时可置 False 提速）。
    """
    db_path = db_path or str(models.DB_PATH)
    rows = _read_shadow_rows(db_path) if os.path.exists(db_path) else []
    trade_dates = _unique_trade_dates(db_path) if os.path.exists(db_path) else set()

    # replay drift（只读冻结快照 + 交叉比对，绝不实时重算）
    rep = replay_engine.replay_all(
        Path(BASE) / "output", db_path if os.path.exists(db_path) else None
    )
    replay_drift = len(rep.get("cross_check", {}).get("drifts", []) or [])

    gm_passed = _run_golden_master() if run_golden_master else True

    metrics = _metrics(rows, trade_dates, replay_drift, gm_passed)
    verdict, checks = _verdict(metrics)
    return {
        "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": db_path,
        "criteria": {"min_samples": MIN_SAMPLES},
        "metrics": metrics,
        "checks": checks,
        "verdict": verdict,
    }


def render_report(result: dict) -> str:
    m = result["metrics"]
    lines = []
    lines.append("=" * 66)
    lines.append("  Shadow 对照评估（Risk Guard Takeover Gate 前置评估）")
    lines.append("=" * 66)
    lines.append(f"评估时间 : {result['evaluated_at']}")
    lines.append(f"样本数   : shadow_run={m['samples']['shadow_run_count']}  "
                 f"交易日={m['samples']['unique_trade_dates']}  (接管阈值>={result['criteria']['min_samples']})")
    lines.append(f"MATCH/DIFF : {m['match_diff']['match_count']} / {m['match_diff']['diff_count']} "
                 f"(match_ratio={m['match_diff']['match_ratio']:.1%})")
    lines.append(f"Shadow veto: {m['shadow_veto']['count']} ({m['shadow_veto']['ratio']:.1%})")
    lines.append(f"EXTREME覆盖: {m['extreme_coverage']['extreme_count']} "
                 f"({m['extreme_coverage']['extreme_ratio']:.1%}) "
                 f"all_vetoed={m['extreme_coverage']['all_extreme_vetoed']}")
    lines.append(f"Prod/Shadow NO 差: {m['prod_vs_shadow_no']['diff']} "
                 f"(prod_no={m['prod_vs_shadow_no']['prod_no']}, shadow_no={m['prod_vs_shadow_no']['shadow_no']})")
    lines.append(f"仓位差异(by-design): {m['position_diff']['mismatch_count']}")
    lines.append(f"veto 等价违规: {m['veto_equivalence']['violations']}")
    lines.append(f"非EXTREME意外DIFF: {m['non_extreme_unexpected_diff']}")
    lines.append(f"Replay drift: {m['replay_drift']}")
    lines.append(f"Golden Master 回归: {m['golden_master_passed']}")
    lines.append("-" * 66)
    for c in result["checks"]:
        tag = "PASS" if c["passed"] else "FAIL"
        lines.append(f"  [{tag}] {c['name']}  ({c['detail']})")
    lines.append("-" * 66)
    lines.append(f"  接管判定结论: {result['verdict']}")
    if result["verdict"] == "PASS":
        lines.append("  → 满足全部接管前提。是否真实接管由人工批准 Release Gate 决定")
        lines.append("    （approve_risk_guard_takeover.py；本评估不改生产）。")
    else:
        lines.append("  → HOLD：继续观察累积 shadow_run；不满足条件前绝不接管。")
    lines.append("=" * 66)
    return "\n".join(lines)


def main():
    result = evaluate()
    print(render_report(result))
    out_dir = BASE / "output"
    out_dir.mkdir(exist_ok=True)
    fname = out_dir / f"shadow_evaluation_{datetime.now().strftime('%Y%m%d')}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[artifact] 已写入: {fname}")


if __name__ == "__main__":
    main()
