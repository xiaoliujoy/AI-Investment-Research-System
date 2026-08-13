# -*- coding: utf-8 -*-
"""
approve_risk_guard_takeover.py —— v0.2 Phase 1E 人工 Release Gate 批准入口。

【重要】本脚本【绝不】自动翻转 RISK_GUARD_ENABLED。它只做三件事：
  1) 运行 shadow_evaluator，确认当前结论为 PASS（否则拒绝批准）；
  2) 要求人工以显式参数确认（--approver 署名 + --confirm）；
  3) 在 release_gate 表写入一条 APPROVED 记录（可审计证据）。

真正的生产接管仍需人工在 backend/risk_guard.py 把 RISK_GUARD_ENABLED 从 0 改为 1，
且 risk_guard.is_enabled() 会同时校验本 gate 是否已批准 —— 二者缺一不可，接管才生效。

这与系统核心原则一致：学习可以观察生产，不能未经批准改变生产。

用法（务必人工显式执行，禁止任何定时任务自动调用）：
  python backend/approve_risk_guard_takeover.py --approver "JOY" --confirm
"""
from __future__ import annotations

import os
import sys
import json
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import shadow_evaluator as ev  # noqa: E402
import release_gate  # noqa: E402


def attempt_approval(approver: str, confirm: bool, db_path: str = None) -> dict:
    """人工批准流程：评估须 PASS + 显式确认，才写 APPROVED gate。绝不改常量。"""
    result = ev.evaluate(db_path=db_path, run_golden_master=True)
    if result["verdict"] != "PASS":
        return {
            "ok": False,
            "reason": "eval_not_pass",
            "verdict": result["verdict"],
            "checks": result["checks"],
            "note": "评估未达 PASS，拒绝批准。继续观察累积 shadow_run。",
        }
    if not confirm or not approver:
        return {
            "ok": False,
            "reason": "not_confirmed",
            "note": "缺少 --approver 署名或 --confirm 显式确认，拒绝批准。",
        }
    gate_id = release_gate.record_approval(
        "risk_guard_takeover", approver, result["metrics"],
        notes="人工批准 Risk Guard 生产接管（Release Gate）。常量 RISK_GUARD_ENABLED 仍需人工置 1。",
    )
    return {
        "ok": True,
        "gate_id": gate_id,
        "note": (
            "Gate 已记录(APPROVED)。生产接管尚未生效：需人工将 "
            "backend/risk_guard.py 的 RISK_GUARD_ENABLED 从 0 改为 1；"
            "is_enabled() 将同时校验本 gate，二者缺一接管不生效。"
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Risk Guard 接管人工 Release Gate 批准（不自动翻 flag）")
    ap.add_argument("--approver", required=True, help="审批人（人工署名，留痕）")
    ap.add_argument("--confirm", action="store_true", help="显式确认本次批准（缺省拒绝）")
    ap.add_argument("--db", default=None, help="指定数据库路径（默认生产库）")
    args = ap.parse_args()

    out = attempt_approval(args.approver, args.confirm, db_path=args.db)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
