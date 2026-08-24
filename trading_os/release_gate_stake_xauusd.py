# -*- coding: utf-8 -*-
"""
release_gate_stake_xauusd.py
XAUUSD Execution Engine v0.1 —— G0~G2 Release Gate 打桩脚本（控制平面准入）

【重要治理约束】
  - 本脚本不裸 INSERT release_gate 表。必须经由 backend/release_gate.record_approval()
    官方审计模块写入，保留 criteria_hash 锁定与人工署名。
  - 真实表字段：gate_id, feature, status, approved_by, approved_at,
    eval_snapshot(JSON), criteria_hash, notes, created_at
  - 资金权限 / 风险预算 / 停机线 全部锁进 eval_snapshot（JSON dict），不写死为列。
  - feature 独立命名 'xauusd_execution_g0_g2'，不与 risk_guard 混用。
  - 本脚本默认 DRY_RUN=True，打印将要写入的快照但不落库。须人工显式 --commit 才写入。

运行：
  python trading_os/release_gate_stake_xauusd.py            # 干跑预览
  python trading_os/release_gate_stake_xauusd.py --commit  # 真实打桩（需 --approver 署名）
"""
from __future__ import annotations
import sys
import os
import json
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

import release_gate  # backend/release_gate.py

FEATURE = "xauusd_execution_g0_g2"
PROVENANCE = "docs/XAUUSD_Execution_Engine_PreReg_v0.1.md"

# 从已冻结的 risk_limits.json 读取参数，保证单一事实源（不重复硬编码）
CONFIG_PATH = BASE / "config" / "risk_limits.json"


def load_snapshot_from_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    rb = cfg["risk_budget"]
    cb = cfg["circuit_breaker"]
    sc = cfg["scope"]
    g2 = cfg["g2_validation"]
    return {
        "scope_symbols": sc["symbols"],
        "account_id": sc["account_id"],
        "max_lot_per_order": sc["max_lot_per_order"],
        "fund_access_level": "execution",
        "execution_mode": sc["execution_mode"],
        "per_trade_risk_usd": rb["per_trade_usd"],
        "risk_basis": rb["basis"],
        "daily_loss_halt_usd": cb["daily_loss_halt_usd"],
        "daily_loss_halt_r": cb["daily_loss_halt_r"],
        "consecutive_loss_k": cb["consecutive_loss_cooldown"]["k_losses"],
        "cooldown_minutes": cb["consecutive_loss_cooldown"]["cooldown_minutes"],
        "max_total_open_risk_usd": cb["max_total_open_risk_usd"],
        "mt5_interface_mode": cfg["mt5_interface"]["mode"],
        "g2_environment": g2["environment"],
        "g2_min_trades_pass": g2["min_trades_for_gate_pass"],
        "approved_scope": "XAUUSD_ONLY_G0_G2_MAX_0_01_LOT",
        "provenance_doc": PROVENANCE,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="真实写入 release_gate（默认干跑）")
    ap.add_argument("--approver", default="", help="人工署名（--commit 时必填）")
    args = ap.parse_args()

    snap = load_snapshot_from_config()
    notes = (
        f"XAUUSD Execution Engine v0.1 G0~G2 机器执行权限解锁。"
        f"范围={snap['approved_scope']}。资金权限=execution（系统首个获得真实资金机器执行权限的组件）。"
        f"参数冻结自 {PROVENANCE} + trading_os/config/risk_limits.json。"
    )

    print("=" * 60)
    print("RELEASE GATE STAKE — xauusd_execution_g0_g2")
    print("=" * 60)
    print(f"feature       : {FEATURE}")
    print(f"status        : APPROVED (pending commit)")
    print(f"eval_snapshot :")
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    print(f"notes         : {notes}")
    print("=" * 60)

    if not args.commit:
        print("[DRY_RUN] 未写入。确认参数无误后加 --commit --approver <署名> 真实打桩。")
        return

    if not args.approver:
        print("[ERROR] --commit 必须配合 --approver <人工署名>，拒绝匿名打桩。")
        sys.exit(2)

    gate_id = release_gate.record_approval(
        feature=FEATURE,
        approved_by=args.approver,
        eval_snapshot=snap,
        notes=notes,
    )
    print(f"[COMMITTED] gate_id={gate_id} 已写入 release_gate（criteria_hash 锁定，事后改参须新记录）。")
    print(f"[NEXT] G0 无副作用探测可启动：trading_os/probe_xauusd_spec.py")


if __name__ == "__main__":
    main()
