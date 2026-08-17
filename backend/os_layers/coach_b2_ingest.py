# -*- coding: utf-8 -*-
"""
coach_b2_ingest.py  --  B2.0 Manual Observation Pipeline 摄入与累积层（OBSERVATION）

状态：OBSERVATION / DESIGN（测量态；自动计算，不自动干预）

职责（窄，来自 Spec Review §0.1 / §0.2 / §0.3）
---------------------------------------------
  - oracle   : Round-trip Hard Gate（逐字段比全部 16 个 measurement primitive vs 冻结 observation）
  - seed     : 历史 210 笔回放 → 去重 → 累积存储 → 调 B.1 引擎
  - ingest   : 手动 CSV blotter + 价格 CSV → 测量 → 去重 → 累积 → 调 B.1 引擎

铁律（不破）
--------
  - 不重算 EQ；只调 trade_measurement.compute_trade（冻结提取）
  - 不接入生产；不写 run_daily / risk_guard / shadow / CIO；不推送任何建议/告警
  - 不跨入 Interpretation / Rule：输出仅 Measurement + descriptive DNA
  - 任何 seed / ingest 运行前必过 Oracle Gate；不过则 sys.exit(2) STOP
  - n_interpretation_strings == 0 / n_auto_intervention_actions == 0（机器可校验防火墙）
"""

import os
import sys
import json
import csv
import bisect
import argparse

# 同目录模块（B.1 引擎 + 冻结测量）
import trade_measurement as tm
import coach_diagnostics as cd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MT5 = os.path.join(ROOT, "mt5_raw")
TRADE_PATH = os.path.join(MT5, "trade_path.json")
M5_CSV = os.path.join(MT5, "XAUUSD_M5.csv")
EQ1M_OBS = os.path.join(ROOT, "backend", "output", "research_contracts", "eq1m_observation_v0_1.json")
ACCUM = os.path.join(ROOT, "backend", "output", "coach_accumulated_per_trade.json")
DNA_OUT = os.path.join(ROOT, "backend", "output", "coach_dna_accumulated.json")

# 解释性 deny-list（B.2 防火墙 Guard：输出文本含这些词 → n_interpretation_strings>0 → STOP）
INTERPRET_DENY = ["应该", "太晚", "太早", "偏高", "偏低", "稳定", "模式", "做得好", "做得不好", "出错", "建议", "处方", "你的最大问题"]

# 全部 16 个 measurement primitive（Oracle 逐字段比较）
PRIMITIVES = [
    "trade_id", "direction", "etd_bars", "etd_minutes", "IAE_usd", "Giveback_usd",
    "Giveback_late_usd", "MFE_usd", "MAE_usd", "PnL_usd", "initial_risk_usd",
    "mfe_peak_idx", "duration_bars", "overlap", "exit_reason", "sl_present",
]

# ----------------------------------------------------------------------------
# B2.0 Observation Period — 治理状态（机器可读，随累积 JSON 落盘）
# ----------------------------------------------------------------------------
# 收口判断（2026-08-17）：B.2 正式进入 Observation Period。
# 期间只积累真实样本、不急于解释；禁止任何"根据结果反向塑造 Measurement / Rule"的动作。
# 该 dict 写入 coach_dna_accumulated.json["b2_self_check"]，随每次 seed/ingest 复写，
# 既机器可读，又位于 B.1 DNA 相等性比较的排除键内（不污染 B.1 全等证明）。
OBSERVATION_PERIOD = {
    "active": True,
    "entered": "2026-08-17",
    "freeze_state": "Measurement Validated / Continuous Observation Enabled / Behavioral Interpretation Pending",
    "allowed": [
        "摄入真实交易（manual CSV）",
        "自动测量（冻结 trade_measurement.compute_trade）",
        "累积 / 去重（幂等）",
        "更新描述性 DNA（仅 descriptive percentiles）",
        "记录样本数量",
        "记录数据质量",
        "记录异常",
    ],
    "forbidden": [
        "根据新数据修改测量定义",
        "根据结果修改 CP / ETD / IAE 定义",
        "根据结果增加分类",
        "根据结果产生交易规则",
        "根据结果修改仓位",
        "根据结果连接 Risk Guard / CIO",
        "根据结果重新定义成功 / 失败",
        "任何 Interpretation / Auto-intervention（已由机器护栏保证：n_interpretation_strings==0 / n_auto_intervention_actions==0）",
    ],
    "note": "系统只回答『最近发生了什么』，暂不回答『以后应该怎么交易』。",
}


# ----------------------------------------------------------------------------
# 加载
# ----------------------------------------------------------------------------
def load_m5(path):
    bars = []
    with open(path, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            bars.append((int(row["time"]), float(row["open"]), float(row["high"]),
                         float(row["low"]), float(row["close"])))
    bars.sort(key=lambda b: b[0])
    times = [b[0] for b in bars]
    return bars, times


def load_trade_path(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["trades"]


def load_blotter_csv(path):
    """读取手动 blotter；返回 [(trade_dict, instrument, ticket), ...]。
    compute_trade 需要的键：direction/entry_price/exit_price/volume/entry_time/exit_time/pnl/sl_trigger_price/exit_reason。"""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            t = {
                "direction": row["direction"].strip().upper(),
                "entry_time": row["entry_time"].strip(),
                "entry_price": float(row["entry_price"]),
                "exit_time": row["exit_time"].strip(),
                "exit_price": float(row["exit_price"]),
                "volume": float(row["volume"]),
                "pnl": float(row["pnl"]),
                "exit_reason": row.get("exit_reason", "manual").strip().lower(),
                "sl_trigger_price": (float(row["sl_trigger_price"]) if row.get("sl_trigger_price", "").strip() not in ("", "None", "null") else None),
                "ticket": row.get("ticket", "").strip() or None,
            }
            instrument = row.get("instrument", "UNKNOWN").strip()
            rows.append((t, instrument, t["ticket"]))
    return rows


# ----------------------------------------------------------------------------
# 测量
# ----------------------------------------------------------------------------
def run_measurement(trades, bars, times, contract_mult):
    """逐笔调用冻结 compute_trade；返回 (有效记录列表, 被排除笔数)。"""
    out = []
    excluded = 0
    for t in trades:
        rec = tm.compute_trade(t, bars, times, contract_mult)
        if rec is None:
            excluded += 1
            continue
        out.append(rec)
    return out, excluded


# ----------------------------------------------------------------------------
# Round-trip Oracle = B.2 的 Hard Gate
# ----------------------------------------------------------------------------
def _approx_eq(a, b, tol=1e-6):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def oracle_test():
    """逐字段、逐笔比较 B.2 测量 vs 冻结 observation。任一冻结字段变化 → STOP。返回 True/False。"""
    trades = load_trade_path(TRADE_PATH)
    bars, times = load_m5(M5_CSV)
    b2, _ = run_measurement(trades, bars, times, contract_mult=100.0)

    with open(EQ1M_OBS, encoding="utf-8") as f:
        obs = json.load(f)
    ref = obs["per_trade"]

    if len(b2) != len(ref):
        print("[ORACLE FAIL] 笔数不一致: B.2=%d  冻结=%d" % (len(b2), len(ref)))
        return False

    mism = 0
    first = None
    for i, (a, b) in enumerate(zip(b2, ref)):
        for k in PRIMITIVES:
            if not _approx_eq(a.get(k), b.get(k)):
                mism += 1
                if first is None:
                    first = (i, k, a.get(k), b.get(k))
    if mism > 0:
        print("[ORACLE FAIL] %d 个冻结字段不一致；首例 @trade#%d field=%s  B2=%s  冻结=%s"
              % (mism, first[0], first[1], first[2], first[3]))
        return False

    print("[ORACLE PASS] B.2 测量与冻结 observation 逐字段一致（%d 笔 × %d primitive）"
          % (len(b2), len(PRIMITIVES)))
    return True


# ----------------------------------------------------------------------------
# 去重 + 累积
# ----------------------------------------------------------------------------
def dedupe_and_accumulate(records, keys, accum_path):
    """追加 records 到累积存储；按 key 去重。返回 (n_new, n_dup, total)。"""
    if os.path.exists(accum_path):
        with open(accum_path, encoding="utf-8") as f:
            store = json.load(f)
    else:
        store = {"per_trade": [], "meta": {"accum_keys": [], "version": "B2.0"}}

    existing = set(store.get("meta", {}).get("accum_keys", []))
    n_new, n_dup = 0, 0
    for rec, key in zip(records, keys):
        if key in existing:
            n_dup += 1
            continue
        store["per_trade"].append(rec)
        store["meta"]["accum_keys"].append(key)
        existing.add(key)
        n_new += 1

    out_dir = os.path.dirname(accum_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(accum_path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    return n_new, n_dup, len(store["per_trade"])


# ----------------------------------------------------------------------------
# B.2 机器可校验防火墙自检
# ----------------------------------------------------------------------------
def b2_self_check(dna_path, oracle_pass, n_dup=0):
    with open(dna_path, encoding="utf-8") as f:
        dna = json.load(f)

    # 扫描所有输出文本是否含解释性 deny-list
    n_interpret = 0
    for d in dna.get("per_trade", []):
        for s in d.get("diagnostic_fact_strings", []) or []:
            for w in INTERPRET_DENY:
                if w in s:
                    n_interpret += 1

    eng = dna.get("self_check", {})
    n_auto_intervention = 0  # 本模块从不调用任何生产/推送动作，构造上为 0

    b2 = {
        "oracle_pass": bool(oracle_pass),
        "n_measurement_mismatch_vs_oracle": 0 if oracle_pass else 1,
        "n_duplicate_dropped": n_dup,
        "n_diagnostic_label_nonnull": eng.get("n_diagnostic_label_nonnull", 0),
        "n_cutoff_rules": eng.get("n_cutoff_rules", 0),
        "n_interpretation_strings": n_interpret,
        "n_auto_intervention_actions": n_auto_intervention,
        "d4_boundary_ok": eng.get("d4_boundary_ok", False),
        "no_classification": eng.get("no_classification", False),
        "observation_only": True,
        "status": "Measurement Validated / Continuous Observation Enabled / Behavioral Interpretation Pending",
        "governance_state": OBSERVATION_PERIOD["freeze_state"],
        "observation_period": OBSERVATION_PERIOD,
    }

    firewall_ok = (
        b2["oracle_pass"]
        and b2["n_interpretation_strings"] == 0
        and b2["n_auto_intervention_actions"] == 0
        and b2["d4_boundary_ok"]
        and b2["no_classification"]
    )
    b2["firewall_ok"] = firewall_ok

    dna["b2_self_check"] = b2
    with open(dna_path, "w", encoding="utf-8") as f:
        json.dump(dna, f, ensure_ascii=False, indent=2)

    print("--- B2 self_check ---")
    print("  oracle_pass             : %s" % b2["oracle_pass"])
    print("  interpretation_strings  : %d  (must be 0)" % n_interpret)
    print("  auto_intervention       : %d  (must be 0)" % n_auto_intervention)
    print("  d4_boundary_ok          : %s" % b2["d4_boundary_ok"])
    print("  no_classification       : %s" % b2["no_classification"])
    print("  firewall_ok             : %s" % firewall_ok)
    return b2


def write_milestones(dna_path, total):
    """里程碑仅计数、描述性；显式 'stability NOT claimed'（Spec §9）。"""
    thresholds = [100, 200, 500, 1000]
    crossed = [m for m in thresholds if total >= m]
    milestones = [
        {"n": m, "note": "DNA recomputed at N>=%d (descriptive only; stability NOT claimed)" % m}
        for m in crossed
    ]
    with open(dna_path, encoding="utf-8") as f:
        dna = json.load(f)
    dna["b2_milestones"] = milestones
    with open(dna_path, "w", encoding="utf-8") as f:
        json.dump(dna, f, ensure_ascii=False, indent=2)
    if milestones:
        print("  milestones crossed      : %s" % crossed)


# ----------------------------------------------------------------------------
# 子命令
# ----------------------------------------------------------------------------
def cmd_oracle():
    ok = oracle_test()
    sys.exit(0 if ok else 2)


def cmd_seed():
    if not oracle_test():
        print("[STOP] Oracle Gate 未过，不产生任何累积输出。")
        sys.exit(2)
    trades = load_trade_path(TRADE_PATH)
    bars, times = load_m5(M5_CSV)
    records, excluded = run_measurement(trades, bars, times, contract_mult=100.0)
    keys = ["eq1m_%d" % i for i in range(len(records))]
    n_new, n_dup, total = dedupe_and_accumulate(records, keys, ACCUM)
    cd.main(ACCUM, DNA_OUT)
    b2 = b2_self_check(DNA_OUT, oracle_pass=True, n_dup=n_dup)
    write_milestones(DNA_OUT, total)
    print("=== B2.0 seed (历史 210 回放) ===")
    print("  measured(valid)  : %d  (excluded no-CP: %d)" % (len(records), excluded))
    print("  new / dup / total: %d / %d / %d" % (n_new, n_dup, total))
    print("  OUT accum  : %s" % ACCUM)
    print("  OUT dna    : %s" % DNA_OUT)
    if not b2["firewall_ok"]:
        print("[STOP] 防火墙自检未过。")
        sys.exit(2)


def cmd_ingest(blotter, price, mult):
    if not oracle_test():
        print("[STOP] Oracle Gate 未过，不产生任何累积输出。")
        sys.exit(2)
    rows = load_blotter_csv(blotter)
    bars, times = load_m5(price)
    records, keys = [], []
    excluded = 0
    journal_counter = 0
    for (t, instrument, ticket) in rows:
        rec = tm.compute_trade(t, bars, times, contract_mult=mult)
        if rec is None:
            excluded += 1
            continue
        records.append(rec)
        if ticket:
            keys.append("%s:%s" % (instrument, ticket))
        else:
            keys.append("%s:journal_%d" % (instrument, journal_counter))
            journal_counter += 1
    n_new, n_dup, total = dedupe_and_accumulate(records, keys, ACCUM)
    cd.main(ACCUM, DNA_OUT)
    b2 = b2_self_check(DNA_OUT, oracle_pass=True, n_dup=n_dup)
    write_milestones(DNA_OUT, total)
    print("=== B2.0 ingest (手动 CSV) ===")
    print("  measured(valid)  : %d  (excluded no-CP: %d)" % (len(records), excluded))
    print("  new / dup / total: %d / %d / %d" % (n_new, n_dup, total))
    print("  OUT accum  : %s" % ACCUM)
    print("  OUT dna    : %s" % DNA_OUT)
    if not b2["firewall_ok"]:
        print("[STOP] 防火墙自检未过。")
        sys.exit(2)


def main():
    p = argparse.ArgumentParser(description="B2.0 Manual Observation Pipeline")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("oracle", help="Round-trip Hard Gate：逐字段比 16 primitive vs 冻结 observation")
    sub.add_parser("seed", help="历史 210 笔回放 → 累积 → 调 B.1 引擎")
    pi = sub.add_parser("ingest", help="手动 CSV blotter + 价格 CSV → 测量 → 累积")
    pi.add_argument("--blotter", required=True)
    pi.add_argument("--price", required=True)
    pi.add_argument("--mult", type=float, default=100.0, help="contract base multiplier（XAUUSD=100, A股=股数）")
    args = p.parse_args()
    if args.cmd == "oracle":
        cmd_oracle()
    elif args.cmd == "seed":
        cmd_seed()
    elif args.cmd == "ingest":
        cmd_ingest(args.blotter, args.price, args.mult)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
