# -*- coding: utf-8 -*-
"""
write_decision_ledger.py —— v0.2 Phase 1B 流水线步骤。

职责：从一次系统运行产出的 brain_report（或已在内存中的 brain dict）抽取并写入
Decision Ledger / Evidence / Snapshot Manifest / Version 到 vibe_research.db。

设计红线（PRD §11）：
  - 只「读」既有决策结果并「记录」，绝不修改任何生产裁决逻辑或返回值。
  - 不 import 也不改动 _DEBATE_LAYERS / 评分公式 / 阈值 / L7 composite / pos_scale。
  - 失败一律向上抛，由调用方（cio_agent 钩子 / run_daily 步骤）try/except 吞掉，
    绝不因 Ledger 写入失败而中断主流程（memo 生产、日报 HTML 等）。

调用方式：
  - 作为钩子：write_ledger_from_brain(brain_dict)
  - 命令行自测：python write_decision_ledger.py [path/to/brain_report.json]
"""
from __future__ import annotations

import os
import sys
import json
import time
import random
import string
import datetime
import hashlib
import re
import sqlite3

# 路径：本文件位于 backend/，确保能 import database / VERSION
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from database.models import get_db  # noqa: E402
import VERSION  # noqa: E402
import risk_guard  # noqa: E402  # 风险映射唯一权威（PRD §6）


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _rand(n: int = 4) -> str:
    return "".join(random.choices(string.hexdigits[:16].lower(), k=n))


# 风险映射（risk_state_from_composite / parse_position_limit）已统一收口到
# risk_guard.py，本模块不再重复实现，避免映射漂移。直接委托：
#   risk_guard.risk_state_from_composite(...)
#   risk_guard.parse_position_limit(...)
#   risk_guard.assess(results, brain)  -> 一次性给出 risk_state/veto/position_limit


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 抽取
# --------------------------------------------------------------------------- #
def _extract(brain: dict) -> dict:
    """从 brain_report 抽取 Ledger / Evidence / Snapshot 所需字段。纯函数，无副作用。"""
    trade_date = brain.get("trade_date") or datetime.date.today().strftime("%Y-%m-%d")
    generated_at = brain.get("generated_at") or _now_iso()

    committee = brain.get("committee") or brain.get("decision") or {}
    results = brain.get("results") or {}

    l7 = results.get("L7") or {}
    l7_raw = l7.get("raw") if isinstance(l7.get("raw"), dict) else {}
    composite = l7_raw.get("composite")

    can_buy = committee.get("can_buy")
    direction = committee.get("direction")
    position_pct = committee.get("position_pct")
    verdict = committee.get("verdict")
    hard_no = committee.get("hard_no") or []
    overall_conf = committee.get("overall_confidence")

    risk_state = risk_guard.risk_state_from_composite(composite)  # 委托 risk_guard（唯一权威）
    has_hard_no = bool(hard_no)
    # veto 字段记录 IC 实际 hard_no 原因（完整透明）；risk_state 由 risk_guard 口径给出。
    veto = hard_no[0] if has_hard_no else None

    # 决策映射（PRD §4.3.1）：can_buy=YES -> YES/SCORE；NO 且有 hard_no -> REJECT/RISK_VETO
    if str(can_buy).upper() == "YES":
        decision = "YES"
        decision_basis = "SCORE"
    else:
        if has_hard_no:
            decision = "REJECT"
            decision_basis = "RISK_VETO"
        else:
            decision = "NO"
            decision_basis = "SCORE"

    pos_min, pos_max, pos_label = risk_guard.parse_position_limit(position_pct)

    return {
        "trade_date": trade_date,
        "generated_at": generated_at,
        "committee": committee,
        "composite": composite,
        "can_buy": can_buy,
        "direction": direction,
        "position_pct": position_pct,
        "verdict": verdict,
        "hard_no": hard_no,
        "has_hard_no": has_hard_no,
        "veto": veto,
        "overall_conf": overall_conf,
        "risk_state": risk_state,
        "decision": decision,
        "decision_basis": decision_basis,
        "pos_min": pos_min,
        "pos_max": pos_max,
        "pos_label": pos_label,
    }


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def _run_id_for(trade_date: str, generated_at: str) -> str:
    """确定性 run_id：同一 brain_report（同 trade_date + 同 generated_at）→ 同一 run_id。

    这是 Ledger 幂等的关键：cio_agent.produce() 钩子与 run_daily 独立步骤都会调用本函数，
    吃的是同一份 brain_report.json（trade_date + generated_at 一致），因此产生同一 run_id，
    第二次调用会因 decision_run 已存在而跳过，确保「同一个 run_id 只产生一份 Ledger」。
    """
    ga = (generated_at or "").replace("-", "").replace(":", "").replace(" ", "_")
    return f"{trade_date}_{ga}"


def write_ledger_from_brain(brain: dict, triggered_by: str = "scheduled") -> dict:
    """主入口：抽取并写入 Ledger 相关表。返回本次写入摘要。

    幂等性（PRD/用户确认）：run_id 由 trade_date + generated_at 确定性派生。
    若 decision_run 已存在（CIO 钩子与 run_daily 步骤重复触发），直接跳过写入并返回
    既有 run_id / snapshot_id，绝不对同一运行产生重复 decision_item / evidence。
    """
    if not isinstance(brain, dict):
        raise ValueError("brain 必须是 dict（brain_report.json 的反序列化结果）")

    e = _extract(brain)
    results = brain.get("results") or {}
    trade_date = e["trade_date"]
    generated_at = e["generated_at"]
    now = time.time()
    run_id = _run_id_for(trade_date, generated_at)
    snapshot_id = f"{trade_date}_{generated_at or ''}_snap".replace(" ", "_").replace("-", "")

    conn = get_db()
    try:
        # 幂等检查：同 run_id 已落库则跳过（避免 CIO 钩子 + run_daily 步骤重复写入）
        existing = conn.execute(
            "SELECT run_id, snapshot_id FROM decision_run WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing:
            conn.close()
            return {
                "run_id": existing["run_id"],
                "snapshot_id": existing["snapshot_id"],
                "trade_date": trade_date,
                "decision": e["decision"],
                "decision_basis": e["decision_basis"],
                "risk_state": e["risk_state"],
                "veto": e["veto"],
                "items": [],
                "evidence_count": 0,
                "versions": VERSION.as_dict(),
                "already_exists": True,
            }
    # ---- 4.1 data_snapshot（Snapshot Manifest）----
        manifest = {
            "sources": [
                {
                    "name": "brain_report.json",
                    "trade_date": trade_date,
                    "hash": _sha256_text(json.dumps(brain, ensure_ascii=False, sort_keys=True)),
                }
            ],
            "note": "P0 Snapshot Manifest only（记录来源+日期+哈希）；完整数据快照(immutable artifact) 属 v0.2.5，不在本 PRD 范围。",
        }
        conn.execute(
            """INSERT INTO data_snapshot (snapshot_id, captured_at, manifest, created_at)
               VALUES (?, ?, ?, ?)""",
            (snapshot_id, e["generated_at"], json.dumps(manifest, ensure_ascii=False), now),
        )

        # ---- 4.2 decision_run ----
        versions = VERSION.as_dict()
        market_snapshot = json.dumps({
            "trade_date": trade_date,
            "risk_state": e["risk_state"],
            "risk_composite": e["composite"],
            "can_buy": e["can_buy"],
            "direction": e["direction"],
        }, ensure_ascii=False)
        conn.execute(
            """INSERT INTO decision_run
               (run_id, trade_date, triggered_by, market_snapshot, versions_json, snapshot_id, shadow_mode, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, trade_date, triggered_by, market_snapshot,
             json.dumps(versions, ensure_ascii=False), snapshot_id,
             0 if risk_guard.is_enabled() else 1, now),
        )

        # ---- 4.5 decision_version ----
        conn.execute(
            """INSERT INTO decision_version
               (run_id, data_snapshot_version, indicator_version, strategy_version,
                risk_version, decision_engine_version, prompt_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, versions["data_snapshot_version"], versions["indicator_version"],
             versions["strategy_version"], versions["risk_version"],
             versions["decision_engine_version"], versions["prompt_version"]),
        )

        # ---- 4.3 decision_item（Market 级 + IC 最终裁决；构成最小 Decision Graph）----
        items = []

        # Market 级读（父节点，无 parent）
        market_item_id = f"{run_id}_MKT"
        market_decision = "BULLISH" if str(e["direction"]).lower().startswith("bull") else (
            "BEARISH" if str(e["direction"]).lower().startswith("bear") else "NEUTRAL")
        conn.execute(
            """INSERT INTO decision_item
               (item_id, run_id, parent_item_id, item_type, asset, layer, decision,
                decision_basis, direction, score, evidence_ref, risk_state, veto,
                confidence, position_limit_min, position_limit_max, position_limit_label,
                invalidation, human_decision, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (market_item_id, run_id, None, "MARKET", None, "IC", market_decision,
             "SCORE", e["direction"], e["composite"], None, e["risk_state"], None,
             json.dumps({"overall": e["overall_conf"]}, ensure_ascii=False) if e["overall_conf"] is not None else None,
             None, None, None, None, None, now),
        )
        items.append(market_item_id)

        # IC 最终裁决（父 = Market 节点）
        ic_item_id = f"{run_id}_IC"
        ic_evidence = json.dumps([], ensure_ascii=False)  # 下面写入 evidence 后回填
        conn.execute(
            """INSERT INTO decision_item
               (item_id, run_id, parent_item_id, item_type, asset, layer, decision,
                decision_basis, direction, score, evidence_ref, risk_state, veto,
                confidence, position_limit_min, position_limit_max, position_limit_label,
                invalidation, human_decision, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ic_item_id, run_id, market_item_id, "IC", None, "IC", e["decision"],
             e["decision_basis"], e["direction"], e["composite"], ic_evidence, e["risk_state"],
             e["veto"],
             json.dumps({"overall": e["overall_conf"]}, ensure_ascii=False) if e["overall_conf"] is not None else None,
             e["pos_min"], e["pos_max"], e["pos_label"], None, None, now),
        )
        items.append(ic_item_id)

        # ---- 4.4 evidence（每条带 as_of_date / observed_at，非空）----
        evidence_ids = []
        # (layer, metric, value, unit, source, raw_reference)
        ev_rows = []
        if e["composite"] is not None:
            ev_rows.append(("L7", "risk_composite", str(e["composite"]), "score",
                            "results.L7.raw", "results.L7.raw.composite"))
        for i, hn in enumerate(e["hard_no"]):
            ev_rows.append(("IC", "hard_no", str(hn), "flag",
                            "committee.hard_no", f"committee.hard_no[{i}]"))
        if e["overall_conf"] is not None:
            ev_rows.append(("IC", "overall_confidence", str(e["overall_conf"]), "score",
                            "committee.overall_confidence", "committee.overall_confidence"))
        if e["verdict"] is not None:
            ev_rows.append(("IC", "committee_verdict", str(e["verdict"]), "text",
                            "committee.verdict", "committee.verdict"))

        for idx, (layer, metric, value, unit, source, raw_ref) in enumerate(ev_rows):
            ev_id = f"{run_id}_E{idx:02d}"
            conn.execute(
                """INSERT INTO evidence
                   (evidence_id, item_id, layer, metric, value, unit, source,
                    observed_at, as_of_date, confidence, independence_flag, raw_reference, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ev_id, ic_item_id, layer, metric, value, unit, source,
                 e["generated_at"], trade_date, "High", 1, raw_ref, now),
            )
            evidence_ids.append(ev_id)

        # 回填 IC 项的 evidence_ref
        conn.execute(
            "UPDATE decision_item SET evidence_ref = ? WHERE item_id = ?",
            (json.dumps(evidence_ids, ensure_ascii=False), ic_item_id),
        )

        # ---- 4.7 shadow_run（Shadow Mode 对照记录，PRD §6/§7）----
        # risk_guard 只读适配器，与既有 IC comp>=70 逻辑完全等价：
        #   shadow 仅在 EXTREME（comp>=70）给出否决，其余镜像生产裁决。
        # 生产 verdict / position / memo 一律不被本写入改变（shadow_mode=1 时
        # Risk Guard 只记录 shadow_veto，绝不接管）。
        rg = risk_guard.assess(results, brain=brain)
        shadow_veto_bool = bool(rg.get("veto"))
        prod_can_buy = e["can_buy"]
        prod_direction = e["direction"]
        prod_position = e["position_pct"]
        # Risk Guard 不改方向；仅在否决时使用其仓位护栏口径，否则镜像生产仓位。
        shadow_can_buy = "NO" if shadow_veto_bool else (prod_can_buy if prod_can_buy is not None else "YES")
        shadow_direction = prod_direction
        shadow_position = rg.get("position_limit_label") if shadow_veto_bool else prod_position
        verdict_match = (str(prod_can_buy) == str(shadow_can_buy)) and (str(prod_direction) == str(shadow_direction))
        diff = "MATCH" if verdict_match else json.dumps(
            {"prod_can_buy": prod_can_buy, "shadow_can_buy": shadow_can_buy,
             "prod_direction": prod_direction, "shadow_direction": shadow_direction},
            ensure_ascii=False)
        conn.execute(
            """INSERT INTO shadow_run
               (run_id, prod_can_buy, prod_direction, prod_position,
                shadow_can_buy, shadow_direction, shadow_position, shadow_veto, diff, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, prod_can_buy, prod_direction, prod_position,
             shadow_can_buy, shadow_direction, shadow_position,
             "True" if shadow_veto_bool else "False", diff, now),
        )

        conn.commit()
    finally:
        conn.close()

    return {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "trade_date": trade_date,
        "decision": e["decision"],
        "decision_basis": e["decision_basis"],
        "risk_state": e["risk_state"],
        "veto": e["veto"],
        "items": items,
        "evidence_count": len(evidence_ids),
        "versions": VERSION.as_dict(),
    }


# --------------------------------------------------------------------------- #
# CLI 自测
# --------------------------------------------------------------------------- #
def _default_brain_path() -> str:
    return os.path.join(BASE, "output", "brain_report.json")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else _default_brain_path()
    if not os.path.exists(path):
        print(f"ERROR: 找不到 brain_report: {path}")
        sys.exit(2)
    brain = json.load(open(path, encoding="utf-8"))
    summary = write_ledger_from_brain(brain, triggered_by="manual_cli")
    print("Decision Ledger 写入完成：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
