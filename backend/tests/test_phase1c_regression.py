# -*- coding: utf-8 -*-
"""
test_phase1c_regression.py —— Phase 1C Golden Master 回归（PRD §10 + 用户验收红线）。

直接吃 Golden Master fixture 的 results 跑既有 IC decide() 与 risk_guard.assess()，
不依赖任何叙事/排版引擎，纯逻辑比对。

验收矩阵（用户确认）：
  A. Decision Golden Master（HARD 红线，全部样本必须一致）：
       can_buy / direction / verdict / hard_no
  B. Risk Guard（HARD 红线）：
       composite < 70  -> veto=False
       composite >= 70 -> veto=True
  C. Position（Carve-out）：
       记录 old_position / old_pos_scale / new_position / new_pos_scale；
       pos_scale != 1.0 的样本标记 POSITION_SCALE_CARVE_OUT（不算违规）；
       pos_scale == 1.0 的样本要求 position_pct 完全一致。
  D. Ledger（幂等）：
       同 run_id 只产生 1 条 decision_run / 2 条 decision_item（CIO 钩子 + run_daily 步骤重复触发不重复写）。
  E. 生产安全：
       risk_guard.assess / write_ledger 不修改输入 brain（纯读取），绝不改写生产裁决（Shadow/disabled 默认）。

Golden Master fixture 保持不可变；本测试只读，不改写任何 fixture。
运行：python backend/tests/test_phase1c_regression.py
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
import risk_guard  # noqa: E402
import write_decision_ledger as wl  # noqa: E402
from committee import investment_committee as ic  # noqa: E402

FIX = BASE / "tests" / "fixtures" / "golden_master"


def _load(d):
    return json.load(open(FIX / f"brain_report_{d}.json", encoding="utf-8"))


def _assert(cond, msg, fails):
    if not cond:
        fails.append(msg)
        print("  FAIL:", msg)
    else:
        print("  PASS:", msg)


def main():
    fixtures = sorted(FIX.glob("brain_report_*.json"))
    # 去掉与归档同日的当前 brain_report.json 副本（避免重复），仅用归档样本
    seen, uniq = set(), []
    for p in fixtures:
        r = json.load(open(p, encoding="utf-8"))
        td = r.get("trade_date")
        if td in seen:
            continue
        seen.add(td)
        uniq.append(p)

    fails = []
    carve_outs = []  # POSITION_SCALE_CARVE_OUT 清单

    print(f"加载 {len(uniq)} 个独立交易日 fixture\n")

    for p in uniq:
        r = json.load(open(p, encoding="utf-8"))
        d = r.get("trade_date")
        # 兼容旧格式 fixture（顶层键为 decision）与新格式（committee），
        # 与 build_golden_master.py 的提取逻辑保持一致。
        c = r.get("committee") or r.get("decision") or {}
        results = r.get("results") or {}
        fb = r.get("learning_feedback") or {}
        comp = (results.get("L7") or {}).get("raw", {}).get("composite")

        print(f"=== {d} (composite={comp}, pos_scale={fb.get('pos_scale')}) ===")

        # A. Decision Golden Master（HARD）
        # 注意：最老的 3 个 fixture（07-13/14/15）是旧格式，decision dict 仅含 can_buy/hard_no，
        # 未记录 direction/verdict。对这类样本只断言已记录的字段，不伪造比对（不掩盖缺口）。
        new = ic.decide(results, r.get("conflicts"), r.get("confidence"), fb)
        _assert(new["can_buy"] == c.get("can_buy"),
                f"[{d}] can_buy 一致 ({new['can_buy']})", fails)
        if "hard_no" in c:
            _assert(new["hard_no"] == c.get("hard_no"),
                    f"[{d}] hard_no 一致 ({new['hard_no']})", fails)
        if "direction" in c:
            _assert(new["direction"] == c.get("direction"),
                    f"[{d}] direction 一致 ({new['direction']})", fails)
        else:
            print(f"  SKIP: [{d}] direction 未记录于旧格式 fixture（覆盖缺口，非回归）")
        if "verdict" in c:
            _assert(new["verdict"] == c.get("verdict"),
                    f"[{d}] verdict 一致", fails)
        else:
            print(f"  SKIP: [{d}] verdict 未记录于旧格式 fixture（覆盖缺口，非回归）")

        # B. Risk Guard（HARD）
        rg = risk_guard.assess(results, r)
        expect_veto = (comp is not None and float(comp) >= 70)
        _assert(rg["veto"] == expect_veto,
                f"[{d}] risk_guard veto==(comp>=70): {rg['veto']}=={expect_veto}", fails)
        expect_state = risk_guard.risk_state_from_composite(comp)
        _assert(rg["risk_state"] == expect_state,
                f"[{d}] risk_state 映射 {rg['risk_state']}=={expect_state}", fails)

        # C. Position（Carve-out）
        old_pos = c.get("position_pct")
        new_pos = new["position_pct"]
        if fb.get("pos_scale", 1.0) != 1.0:
            carve_outs.append({
                "trade_date": d, "composite": comp,
                "pos_scale": fb.get("pos_scale"),
                "old_position": old_pos, "new_position": new_pos,
            })
            print(f"  CARVE-OUT: pos_scale={fb.get('pos_scale')} 旧仓位={old_pos!r} → 新仓位={new_pos!r} （冻结历史自校准，不计违规）")
        else:
            _assert(new_pos == old_pos,
                    f"[{d}] position_pct 一致（pos_scale=1.0）: {new_pos!r}", fails)

        # E. 生产安全（纯读取，不修改输入）
        brain_copy = json.loads(json.dumps(r))
        _ = risk_guard.assess(results, r)
        _assert(r == brain_copy, f"[{d}] risk_guard 未修改输入 brain", fails)

    # D. Ledger 幂等（临时 DB）
    tmp = tempfile.mkdtemp(prefix="p1c_ledger_")
    saved = models.DB_PATH
    models.DB_PATH = Path(tmp) / "vibe_research.db"
    models.init_db()
    try:
        sample = _load(sorted(seen)[0] if seen else "2026-08-13")
        s1 = wl.write_ledger_from_brain(sample, triggered_by="test")
        s2 = wl.write_ledger_from_brain(sample, triggered_by="test")
        _assert(s2.get("already_exists") is True, "Ledger 二次写入幂等跳过", fails)
        import sqlite3
        conn = sqlite3.connect(str(models.DB_PATH))
        n_run = conn.execute("SELECT COUNT(*) FROM decision_run WHERE run_id=?",
                             (s1["run_id"],)).fetchone()[0]
        n_item = conn.execute("SELECT COUNT(*) FROM decision_item WHERE run_id=?",
                              (s1["run_id"],)).fetchone()[0]
        conn.close()
        _assert(n_run == 1, f"同 run_id 仅 1 条 decision_run（实际 {n_run}）", fails)
        _assert(n_item == 2, f"同 run_id 仅 2 条 decision_item（实际 {n_item}）", fails)
    finally:
        models.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)

    # 汇总
    print("\n" + "=" * 60)
    print(f"POSITION_SCALE_CARVE_OUT 样本数：{len(carve_outs)}")
    for co in carve_outs:
        print(f"  - {co['trade_date']}  comp={co['composite']}  pos_scale={co['pos_scale']}"
              f"  旧={co['old_position']!r} → 新={co['new_position']!r}")
    print("=" * 60)
    if fails:
        print(f"\nRESULT: FAILED —— {len(fails)} 项违规")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    else:
        print("\nRESULT: ALL PHASE 1C ASSERTIONS PASSED "
              f"（Decision 硬红线 + Risk Guard 硬红线 + Ledger 幂等；"
              f"{len(carve_outs)} 个 position carve-out 不计入违规）")


if __name__ == "__main__":
    main()
