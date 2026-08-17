# -*- coding: utf-8 -*-
"""
Entry Quality Observation EQ-1R  --  Risk-Normalized Robustness Review (Pre-Registered)
======================================================================================

研究契约：docs/EQ1R_PreRegistration_v0.1.md + backend/output/research_contracts/RC-EQ1R-PREREG-v0.1.json
状态：PRE-REGISTRATION FROZEN -> IMPLEMENTATION（仅写、未运行；首次运行受 Gate 0 约束）

设计铁律（来自用户架构约束，禁止违反）：
1. 只读三份源：trade_path.json（210 笔交易）、XAUUSD_M5.csv（M5 K 线）。Outcome 仅由 entry 之后已收盘 bar 计算。
   CP/ETD 仅由 entry 之前已收盘 bar 计算（复用 H2-A / EQ-1 的 bisect_right(times, entry_unix-300) 纪律，杜绝 micro look-ahead）。
2. EQ-1R 不重算 CP/ETD 用于核心证据；ETD 仅用于 142/68 选择偏差诊断（继承 EQ-1 的 CP-D k=2/W=48）。
3. 中性暴露：EQ-1R 只回答「IAE->Giveback 在 stop-distance 风险标准化后是否仍存在」，不预设方向。
4. 不读任何 E1-E4 标签；不优化阈值；不搜变量；不改 EQ-1 v0.1 契约（k=2/W=48 继承不可改）；不进生产/CIO/Trading Coach。
5. **第一次 Run 只描述数据（Observation），不推导任何交易结论。** 输出注明 OBSERVATION_ONLY。
6. 预登记完整性 + 契约令牌为本脚本第一道 Gate：任何一项不匹配 -> 立即 STOP（sys.exit(2)），不产生 observation result。
7. 仅 142 笔 sl_trigger_price 非空进入核心证据；68 笔不补造 initial_risk，仅作 Selection Diagnostic。
8. 全报纪律：A/B/C 三组证据 + PnL 次级 + permutation + 142/68 诊断全部报告，禁 cherry-pick。
9. permutation seed 固定（20260816），保证可复现；仅 diagnostic，不新增 Hard Gate，不构成重新设计 A/B/C 的理由。
10. B（IAE_norm->Giveback_norm）不是标准化后的最终稳健性证明；A/B/C 联合解释，不单独以 B 下结论。
"""

import os
import sys
import json
import csv
import bisect
import math
import random
from datetime import datetime, timezone

# ---------- 路径（相对项目根；脚本置于 backend/os_layers/） ----------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MT5 = os.path.join(ROOT, "mt5_raw")
TRADE_PATH = os.path.join(MT5, "trade_path.json")
M5_CSV = os.path.join(MT5, "XAUUSD_M5.csv")
PREREG_MD = os.path.join(ROOT, "docs", "EQ1R_PreRegistration_v0.1.md")
CONTRACT_JSON = os.path.join(ROOT, "backend", "output", "research_contracts", "RC-EQ1R-PREREG-v0.1.json")
OUT_DIR = os.path.join(ROOT, "backend", "output", "research_contracts")
OUT_JSON = os.path.join(OUT_DIR, "eq1r_observation_v0_1.json")

# ---------- 冻结常量（与预登记文档 + JSON 契约逐字一致；改动须同步改文档并重新走 Gate） ----------
K = 2                      # swing 确认半径（继承 EQ-1，仅用于 ETD 诊断）
W = 48                     # CP 向前搜索窗口（继承 EQ-1，仅用于 ETD 诊断）
IAE_WIN = 10               # IAE = entry 后 10 根完整 M5 最大逆向 excursion (R1 冻结)
PREREG_VERSION = "v0.1"
N_PERM = 2000              # permutation 次数
PERM_SEED = 20260816       # 固定随机种子（与 EQ-1 的 20260815 区分，独立 provenance）
PERM_STAT = "max|assoc| over A/B/C"   # primary permutation statistic
CONTRACT_MULT = 100.0      # XAUUSD 1 标准手 = 100 oz；USD = price_diff * 100 * volume
SAMPLE_N = 142             # SL 子集（sl_trigger_price 非空）

EXPERIMENT_ID = "EQ1R-OBS-v0.1"
HYPOTHESIS = ("EQ-1R: 在 142 笔 SL 子样本中, EQ-1 观察到的 IAE->Giveback 强关系(rho=0.532), "
              "在 stop-distance 风险标准化(÷ initial_risk)后是否仍存在, 以及多少可能由共同尺度因素造成. "
              "这是稳健性检查, 非新发现检验, 非标签预测, 非模型优化.")

# 预登记文档必须包含的令牌（任一缺失即视为预登记被篡改 -> STOP）
PREREG_TOKENS = [
    "Pre-Registration v0.1",
    "k=2",
    "W=48",
    "142 笔",
    "stop-distance risk proxy",
    "Secondary economic diagnostic",
    "Spearman",
    "Fisher-z",
    "20260816",
    "2000",
    "max|assoc|",
    "A/B/C",
    "mediation",
    "参数敏感性",
    "cutoff",
]

# JSON 契约 frozen_tokens 必须与下列硬编码常量完全匹配（任一不符 -> STOP）
CONTRACT_TOKEN_CHECKS = {
    "sample": 142,
    "no_fabricate_68": True,
    "initial_risk_def": "|entry-sl|*100*volume",
    "initial_risk_semantics": "stop_distance_risk_proxy_not_true_risk",
    "raw_norm_dual": True,
    "a_primary": "IAE_USD->Giveback_USD",
    "b_primary": "IAE_norm->Giveback_norm",
    "b_not_proof": True,
    "c_denominator": "initial_risk->IAE_USD & initial_risk->Giveback_USD",
    "abc_joint": True,
    "pnl_secondary": True,
    "spearman": True,
    "fisher_z_approx": True,
    "perm_n": 2000,
    "perm_seed": 20260816,
    "perm_stat": "max_abs_assoc_over_A_B_C",
    "k2_w48_inherit": True,
    "no_mediation": True,
    "no_param_sens": True,
    "no_cutoff": True,
}


# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------
def parse_dt(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def load_trades():
    with open(TRADE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["trades"]


def load_m5():
    bars = []
    with open(M5_CSV, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            bars.append((int(row["time"]), float(row["open"]), float(row["high"]),
                         float(row["low"]), float(row["close"])))
    bars.sort(key=lambda b: b[0])
    times = [b[0] for b in bars]
    return bars, times


# ----------------------------------------------------------------------------
# 统计辅助（pure stdlib；不改变 Gate）
# ----------------------------------------------------------------------------
def rankdata(x):
    """平均秩法（处理并列）。"""
    order = sorted(range(len(x)), key=lambda i: x[i])
    ranks = [0.0] * len(x)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x, y):
    n = len(x)
    if n < 2:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def spearman(x, y):
    if len(x) < 2:
        return None
    return pearson(rankdata(x), rankdata(y))


def fisher_z_ci(rho, n):
    """Spearman 的 Fisher-z CI 仅作 descriptive approximation（非严格精确 CI）。"""
    if n < 4 or abs(rho) >= 1:
        return None
    z = math.atanh(rho)
    se = 1.0 / math.sqrt(n - 3)
    return [round(math.tanh(z - 1.96 * se), 4), round(math.tanh(z + 1.96 * se), 4)]


def corr_block(x, y):
    """返回 {rho, pearson, n, ci95, t} 或 None。"""
    if x is None or y is None or len(x) < 4:
        return None
    rho = spearman(x, y)
    if rho is None:
        return None
    n = len(x)
    pr = pearson(x, y)
    ci = fisher_z_ci(rho, n)
    t = rho * math.sqrt((n - 2) / (1 - rho ** 2)) if abs(rho) < 1 else None
    return {
        "rho": round(rho, 4),
        "pearson_r": round(pr, 4) if pr is not None else None,
        "n": n,
        "ci95_rho_fisher_z_approx": ci,
        "t_stat": round(t, 3) if t is not None else None,
    }


# ----------------------------------------------------------------------------
# Gate 0：预登记完整性 + 契约令牌（第一道 Gate，任何不匹配立即 STOP）
# ----------------------------------------------------------------------------
def gate_fail(msg):
    print(f"[GATE0 FAIL] {msg}")
    print("[STOP] Gate 0 未通过，不产生任何 observation result。")
    sys.exit(2)


def check_gate0(run_epoch):
    # 1. 预登记文档存在 + mtime < 运行时间
    if not os.path.exists(PREREG_MD):
        gate_fail(f"预登记文档不存在: {PREREG_MD}")
    mtime = os.path.getmtime(PREREG_MD)
    if mtime >= run_epoch:
        gate_fail(f"预登记 mtime({mtime:.0f}) 不早于运行时间({run_epoch:.0f})")
    with open(PREREG_MD, encoding="utf-8") as f:
        md_text = f.read()
    missing_doc = [t for t in PREREG_TOKENS if t not in md_text]
    if missing_doc:
        gate_fail(f"预登记文档缺失冻结令牌: {missing_doc}")
    if PREREG_VERSION not in md_text:
        gate_fail(f"版本标记 {PREREG_VERSION} 未找到")

    # 2. 契约 JSON 存在 + frozen_tokens 全部匹配
    if not os.path.exists(CONTRACT_JSON):
        gate_fail(f"契约 JSON 不存在: {CONTRACT_JSON}")
    with open(CONTRACT_JSON, encoding="utf-8") as f:
        contract = json.load(f)
    ft = contract.get("frozen_tokens", {})
    mism = []
    for key, expected in CONTRACT_TOKEN_CHECKS.items():
        if key not in ft:
            mism.append(f"缺失 {key}")
        elif ft[key] != expected:
            mism.append(f"{key}: 契约={ft[key]} 代码={expected}")
    if mism:
        gate_fail(f"契约冻结令牌不匹配: {mism}")

    # 3. eq1r_result 状态必须为 PENDING（防重复运行篡改结论）
    eq1r = contract.get("eq1r_result", {})
    if eq1r.get("status") not in (None, "PENDING"):
        gate_fail(f"契约 eq1r_result.status={eq1r.get('status')} 非 PENDING，疑似已运行/已改 -> STOP")

    print(f"[GATE0 PASS] 预登记 mtime 早于运行, 版本={PREREG_VERSION}, "
          f"文档令牌 {len(PREREG_TOKENS)} 项齐全, 契约冻结令牌 {len(CONTRACT_TOKEN_CHECKS)} 项匹配, "
          f"eq1r_result=PENDING -> 允许计算")
    return md_text, contract


# ----------------------------------------------------------------------------
# CP-D swing 检测（仅用于 ETD 诊断；继承 EQ-1 k=2/W=48）
# ----------------------------------------------------------------------------
def find_cp(prior_bars, entry_ref_idx, direction):
    lo = max(0, entry_ref_idx + 1 - W)
    candidates = []
    for i in range(lo, entry_ref_idx + 1):
        ok = True
        for j in range(1, K + 1):
            if i - j < 0 or i + j >= len(prior_bars):
                ok = False
                break
            if direction == "BUY":
                if not (prior_bars[i][2] > prior_bars[i - j][2] and prior_bars[i][2] > prior_bars[i + j][2]):
                    ok = False
                    break
            else:
                if not (prior_bars[i][3] < prior_bars[i - j][3] and prior_bars[i][3] < prior_bars[i + j][3]):
                    ok = False
                    break
        if ok:
            candidates.append(i)
    if not candidates:
        return None
    cp_idx = max(candidates)
    if cp_idx + K > entry_ref_idx:
        return None
    return cp_idx


# ----------------------------------------------------------------------------
# 逐笔 Outcome 计算（仅用 entry 之后已收盘 bar）
# ----------------------------------------------------------------------------
def favorable_usd(price, entry_price, direction, mult):
    if direction == "BUY":
        return (price - entry_price) * mult
    return (entry_price - price) * mult


def adverse_usd(price, entry_price, direction, mult):
    if direction == "BUY":
        return (entry_price - price) * mult
    return (price - entry_price) * mult


def compute_outcomes(t, bars, times, entry_unix, entry_ref_idx):
    direction = t["direction"]
    entry_price = float(t["entry_price"])
    exit_price = float(t["exit_price"])
    vol = float(t["volume"])
    mult = CONTRACT_MULT * vol
    exit_unix = parse_dt(t["exit_time"])

    i_entry = bisect.bisect_right(times, entry_unix)
    i_exit = bisect.bisect_right(times, exit_unix)
    post = bars[i_entry:i_exit]

    iae = 0.0
    for b in post[:IAE_WIN]:
        adv = adverse_usd(b[3], entry_price, direction, mult) if direction == "BUY" else adverse_usd(b[2], entry_price, direction, mult)
        if adv > iae:
            iae = adv

    mfe = 0.0
    mae = 0.0
    for b in post:
        fav = favorable_usd(b[2], entry_price, direction, mult) if direction == "BUY" else favorable_usd(b[3], entry_price, direction, mult)
        adv = adverse_usd(b[3], entry_price, direction, mult) if direction == "BUY" else adverse_usd(b[2], entry_price, direction, mult)
        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv
    fav_exit = favorable_usd(exit_price, entry_price, direction, mult)
    adv_exit = adverse_usd(exit_price, entry_price, direction, mult)
    if fav_exit > mfe:
        mfe = fav_exit
    if adv_exit > mae:
        mae = adv_exit

    giveback = max(0.0, mfe - max(0.0, fav_exit))
    pnl = float(t["pnl"])
    sl = t.get("sl_trigger_price")
    init_risk = abs(entry_price - float(sl)) * mult if sl not in (None, "") else None

    return {
        "IAE_usd": round(iae, 4),
        "MFE_usd": round(mfe, 4),
        "MAE_usd": round(mae, 4),
        "Giveback_usd": round(giveback, 4),
        "PnL_usd": round(pnl, 4),
        "initial_risk_usd": round(init_risk, 4) if init_risk is not None else None,
        "mfe_file_usd": round(float(t.get("mfe_usd", 0.0)), 4),
    }


# ----------------------------------------------------------------------------
# Permutation Null（仅 diagnostic，不新增 Hard Gate）
# 固定各变量的边际分布，仅保边洗牌交易配对（单一对齐索引），复刻 max|assoc| over A/B/C。
# ----------------------------------------------------------------------------
def run_permutation(iae_usd, give_usd, init_risk, rng_seed):
    n = len(iae_usd)
    rng = random.Random(rng_seed)

    def stat_of(iu, gu, ir):
        # iu/gu/ir 为（独立）洗牌后的向量；比率由 mismatched 对构成，正确打破联合关联
        pairs = [(iu[k], gu[k], ir[k]) for k in range(n) if ir[k] and ir[k] > 0]
        if len(pairs) < 4:
            return 0.0
        iu2 = [p[0] for p in pairs]
        gu2 = [p[1] for p in pairs]
        ir2 = [p[2] for p in pairs]
        inr2 = [iu2[k] / ir2[k] for k in range(len(pairs))]
        gnr2 = [gu2[k] / ir2[k] for k in range(len(pairs))]
        mx = 0.0
        for r in (spearman(iu2, gu2), spearman(inr2, gnr2),
                  spearman(ir2, iu2), spearman(ir2, gu2)):
            if r is not None:
                mx = max(mx, abs(r))
        return mx

    iu0 = list(iae_usd)
    gu0 = list(give_usd)
    ir0 = list(init_risk)
    observed = stat_of(iu0, gu0, ir0)
    null = []
    for _ in range(N_PERM):
        a = iu0[:]; rng.shuffle(a)
        b = gu0[:]; rng.shuffle(b)
        c = ir0[:]; rng.shuffle(c)
        null.append(stat_of(a, b, c))
    null.sort()
    mean = sum(null) / len(null)
    median = null[len(null) // 2]
    p95 = null[min(len(null) - 1, int(0.95 * (len(null) - 1)))]
    below = sum(1 for x in null if x < observed)
    pct = 100.0 * below / len(null)
    if pct >= 95:
        interp = "observed exceeds permutation null (明显超出随机配对)"
    elif pct >= 90:
        interp = "borderline (<95%)"
    else:
        interp = "lacks evidence beyond null (<90%)"
    return {
        "n_permutations": N_PERM,
        "seed": rng_seed,
        "statistic": PERM_STAT,
        "fixed": "各变量边际分布固定; 独立保边洗牌 IAE/Giveback/initial_risk 三向量(打破所有两两配对); 比率由 mismatched 对构成",
        "observed_max_abs_assoc": round(observed, 4),
        "null_mean": round(mean, 4),
        "null_median": round(median, 4),
        "null_p95": round(p95, 4),
        "empirical_percentile": round(pct, 2),
        "interpretation": interp,
        "note": "Permutation 仅 diagnostic，不新增 Hard Gate；percentile<95 仅标 caveat；不构成重新设计 A/B/C 的理由。",
    }


# ----------------------------------------------------------------------------
# 描述统计
# ----------------------------------------------------------------------------
def desc(v):
    if not v:
        return None
    sv = sorted(v)
    return {"n": len(v), "mean": round(sum(v) / len(v), 4),
            "median": round(sv[len(v) // 2], 4),
            "min": round(min(v), 4), "max": round(max(v), 4)}


def counts(items):
    d = {}
    for it in items:
        d[it] = d.get(it, 0) + 1
    return d


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    run_epoch = datetime.now(timezone.utc).timestamp()
    run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Gate 0（最早执行，失败即 STOP） ----
    md_text, contract = check_gate0(run_epoch)

    # ---- 载入 ----
    trades = load_trades()
    bars, times = load_m5()

    rows = []
    n_no_cp = 0
    for t in trades:
        tid = str(t["trade_id"])
        direction = t["direction"]
        entry_unix = parse_dt(t["entry_time"])
        pi = bisect.bisect_right(times, entry_unix - 300)
        if pi < 1:
            n_no_cp += 1
            continue
        entry_ref_idx = pi - 1
        if bars[entry_ref_idx][0] + 300 > entry_unix:
            gate_fail(f"trade {tid}: entry_reference_bar 未收盘 (micro look-ahead)")
        prior_bars = [bars[k] for k in range(pi)]
        cp_idx = find_cp(prior_bars, entry_ref_idx, direction)
        if cp_idx is None:
            n_no_cp += 1
            continue
        etd_bars = entry_ref_idx - cp_idx
        oc = compute_outcomes(t, bars, times, entry_unix, entry_ref_idx)
        rows.append({
            "trade_id": tid,
            "direction": direction,
            "entry_time": t["entry_time"],
            "exit_reason": t.get("exit_reason"),
            "cp_bar_index": cp_idx,
            "etd_bars": etd_bars,
            "has_initial_risk": oc["initial_risk_usd"] is not None,
            **oc,
        })

    n_total = len(trades)
    n_valid = len(rows)
    sl_rows = [r for r in rows if r["has_initial_risk"]]
    nonsl_rows = [r for r in rows if not r["has_initial_risk"]]
    n_sl = len(sl_rows)
    n_nonsl = len(nonsl_rows)

    # ---- 核心证据（仅 142 SL 子集） ----
    iae = [r["IAE_usd"] for r in sl_rows]
    give = [r["Giveback_usd"] for r in sl_rows]
    pnl = [r["PnL_usd"] for r in sl_rows]
    initr = [r["initial_risk_usd"] for r in sl_rows]
    iae_norm = [iae[i] / initr[i] for i in range(n_sl) if initr[i] and initr[i] > 0]
    give_norm = [give[i] / initr[i] for i in range(n_sl) if initr[i] and initr[i] > 0]
    pnl_norm = [pnl[i] / initr[i] for i in range(n_sl) if initr[i] and initr[i] > 0]
    # 口径对齐：normalized 子集可能因 initr<=0 缩容；记录实际 n
    n_norm = len(iae_norm)

    A = corr_block(iae, give)                       # Raw replication
    B = corr_block(iae_norm, give_norm)             # Risk-scale sensitivity (not proof)
    C1 = corr_block(initr, iae)                     # Denominator diagnostic
    C2 = corr_block(initr, give)                    # Denominator diagnostic
    # PnL Secondary economic diagnostic
    A_pnl = corr_block(iae, pnl)
    B_pnl = corr_block(iae_norm, pnl_norm)

    # ---- Permutation Null（max|assoc| over A/B/C） ----
    perm = run_permutation(iae, give, initr, PERM_SEED)

    # ---- MFE 交叉校验（仅 diagnostic） ----
    mfe_xcheck = [(r["MFE_usd"], r["mfe_file_usd"]) for r in rows]
    diffs = [abs(a - b) for a, b in mfe_xcheck]
    mfe_xcheck_summary = {
        "n": len(diffs),
        "mean_abs_diff": round(sum(diffs) / len(diffs), 4),
        "max_abs_diff": round(max(diffs), 4),
        "note": "自算 MFE (从 M5 棒) vs 文件 mfe_usd；差异来自手续费/取整或管线不同定义，仅 diagnostic。",
    }

    # ---- 142 vs 68 选择偏差诊断（Selection Diagnostic，非 Rule） ----
    def grp_stats(g):
        return {
            "n": len(g),
            "long_short": counts([r["direction"] for r in g]),
            "exit_reason": counts([r["exit_reason"] for r in g]),
            "ETD_bars": desc([r["etd_bars"] for r in g]),
            "PnL_usd": desc([r["PnL_usd"] for r in g]),
            "MFE_usd": desc([r["MFE_usd"] for r in g]),
            "IAE_usd": desc([r["IAE_usd"] for r in g]),
            "Giveback_usd": desc([r["Giveback_usd"] for r in g]),
        }

    selection_diagnostic = {
        "SL_142": grp_stats(sl_rows),
        "non_SL_68": grp_stats(nonsl_rows),
        "note": "Selection Diagnostic，非 Selection Rule；仅暴露偏差边界，不据此筛选样本；结论仅覆盖 SL 子群体，不可外推全部 210。",
    }

    # ---- 描述统计（仅 SL 子集核心变量） ----
    desc_stats = {
        "IAE_usd": desc(iae),
        "Giveback_usd": desc(give),
        "PnL_usd": desc(pnl),
        "initial_risk_usd": desc(initr),
        "IAE_norm": desc(iae_norm),
        "Giveback_norm": desc(give_norm),
        "PnL_norm": desc(pnl_norm),
    }

    # ---- provenance ----
    entry_times = [parse_dt(t["entry_time"]) for t in trades]
    prov = {
        "dataset": "XAUUSD M5 / MT5 210 trades (2026-03-02 ~ 2026-08-05)",
        "trade_count_total": n_total,
        "trade_count_valid_CP": n_valid,
        "n_excluded_no_cp": n_no_cp,
        "n_sl_subset": n_sl,
        "n_non_sl_subset": n_nonsl,
        "n_with_initial_risk": n_sl,
        "preregistration_version": PREREG_VERSION,
        "preregistration_mtime": round(os.path.getmtime(PREREG_MD), 0),
        "run_timestamp": run_iso,
        "sample_definition": "142 笔 sl_trigger_price 非空 (exit_reason=sl); 68 笔无 sl 仅作 Selection Diagnostic, 不补造 initial_risk",
        "initial_risk_definition": "abs(entry_price - sl_trigger_price) * 100 * volume (stop-distance risk proxy, 非真实风险)",
        "outcome_definition": "IAE=entry后10根最大逆向excursion; MFE=entry后最大有利excursion; Giveback=max(0,MFE-退出有利excursion); 均从M5棒自算, 合约mult=100*volume",
        "etd_definition": "继承 EQ-1 CP-D: ETD_bars=entry_reference_bar_index-CP_bar_index (k=2,W=48); 仅用于 142/68 诊断",
        "observation_only": True,
    }

    evidence = {
        "A_raw": {
            "pair": "IAE_usd -> Giveback_usd",
            "role": "Primary diagnostic (H3 replication)",
            "result": A,
        },
        "B_normalized": {
            "pair": "IAE_norm -> Giveback_norm",
            "role": "Primary diagnostic / risk-scale sensitivity check (NOT final robustness proof)",
            "result": B,
        },
        "C1_denominator_IAE": {
            "pair": "initial_risk -> IAE_usd",
            "role": "Denominator diagnostic",
            "result": C1,
        },
        "C2_denominator_Giveback": {
            "pair": "initial_risk -> Giveback_usd",
            "role": "Denominator diagnostic",
            "result": C2,
        },
        "PnL_secondary": {
            "note": "Secondary economic diagnostic, 非假设定义终点, 不派生新研究问题",
            "A_raw_IAE_PnL": A_pnl,
            "B_norm_IAE_PnL": B_pnl,
        },
        "joint_interpretation_rule": (
            "A/B/C 三者联合决定 H3 是否具有非纯尺度解释证据; 不单独以 B 显著/强下结论. "
            "若 B≈A 且 C1/C2 弱 -> 支持 IAE->Giveback 非 stop-distance 尺度混淆; "
            "若 B 弱于 A 或 C1/C2 强 -> 关系可能含 stop-distance 尺度成分, IAE 独立性待定."
        ),
    }

    out = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": HYPOTHESIS,
        "governance": "OBSERVATION_ONLY. 不接 run_daily/risk_guard/shadow/CIO/Trading Coach/生产. "
                      "不读 E1-E4 标签, 不优化阈值, 不搜变量, 不改 EQ-1 v0.1 契约(k=2/W=48). "
                      "第一次 Run 只描述数据, 不推导交易结论.",
        "preregistration_check": {
            "doc_exists": True,
            "mtime_ok": True,
            "run_approved": True,
            "tokens_present": {t: (t in md_text) for t in PREREG_TOKENS},
            "note": "Gate 0 通过才允许计算; 任何一项失败 -> sys.exit(2), 不产生结果.",
        },
        "contract_token_check": {k: (contract.get("frozen_tokens", {}).get(k) == v)
                                 for k, v in CONTRACT_TOKEN_CHECKS.items()},
        "frozen_constants": {
            "K": K, "W": W, "IAE_WIN": IAE_WIN, "SAMPLE_N": SAMPLE_N,
            "PREREG_VERSION": PREREG_VERSION, "N_PERM": N_PERM, "PERM_SEED": PERM_SEED,
            "PERM_STAT": PERM_STAT, "CONTRACT_MULT": CONTRACT_MULT,
        },
        "provenance": prov,
        "descriptive_stats_SL_subset": desc_stats,
        "evidence": evidence,
        "permutation_null": perm,
        "selection_diagnostic_142_vs_68": selection_diagnostic,
        "mfe_crosscheck": mfe_xcheck_summary,
        "decision": "OBSERVATION",
        "decision_rationale": ("第一次 Run 仅描述 142 笔 SL 子样本在 IAE/Giveback/initial_risk 的关系, "
                              "不做 pass/fail 判定, 不推导任何交易结论。A/B/C 联合解释, 不单独以 B 下结论. "
                              "后续解释与未来假设须独立进行."),
        "interpretation_allowed": False,
        "implementation_notes": [
            "仅 142 笔 sl_trigger_price 非空进入核心证据; 68 笔不补造 initial_risk, 仅作 Selection Diagnostic。",
            "A=raw(IAE_usd->Giveback_usd) 复刻 H3; B=normalized(IAE_norm->Giveback_norm) 风险尺度敏感性检查(非最终稳健性证明); C=分母诊断(initial_risk->IAE_usd & initial_risk->Giveback_usd)。",
            "A/B/C 联合解释, 不单独以 B 显著/强下结论 (用户修正 #3)。",
            "PnL_norm 仅 Secondary economic diagnostic, 不派生新研究问题 (用户修正 #2)。",
            "Fisher-z CI 标注为 Spearman 的 descriptive approximation, 非严格精确 CI; bootstrap 敏感性归 v0.2 (用户修正 #4)。",
            "Permutation: 固定各变量边际分布, 独立保边洗牌 IAE/Giveback/initial_risk 三向量(打破所有两两配对), 2000 次(seed=20260816)复刻 max|assoc| over A/B/C; 仅 diagnostic (用户批准)。",
            "ETD 继承 EQ-1 CP-D(k=2/W=48), 仅用于 142/68 诊断, 不进核心证据。",
            "micro look-ahead 排除: 仅用 close_time<=entry_unix 的已收盘 bar; entry_reference_bar=最后已收盘 bar。",
            "initial_risk = abs(entry-sl)*100*volume, 语义锁死为 stop-distance risk proxy, 非真实风险。",
            "MFE/IAE/Giveback 自 M5 棒计算(合约 mult=100*volume), 与文件 mfe_usd 仅交叉校验(diagnostic)。",
            "全报纪律: A/B/C + PnL 次级 + permutation + 142/68 诊断全部报告。",
            "结果解释边界: 即使 A强/B强/C弱, 也只说与'非纯尺度造成'相容, 不能直接升级为因果; 即使 B 消失, 也不说 IAE 无价值。",
        ],
        "per_trade": rows,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print(f"[{EXPERIMENT_ID}] n_total={n_total} n_valid_CP={n_valid} "
          f"SL={n_sl} nonSL={n_nonsl} noCP={n_no_cp}")
    print(f"  A  raw      IAE_usd->Giveback_usd : rho={A['rho'] if A else None} n={A['n'] if A else None}")
    print(f"  B  norm     IAE_norm->Giveback_norm: rho={B['rho'] if B else None} n={B['n'] if B else None}")
    print(f"  C1 denom    initial_risk->IAE_usd  : rho={C1['rho'] if C1 else None} n={C1['n'] if C1 else None}")
    print(f"  C2 denom    initial_risk->Giveback : rho={C2['rho'] if C2 else None} n={C2['n'] if C2 else None}")
    print(f"  PnL sec A   IAE_usd->PnL_usd       : rho={A_pnl['rho'] if A_pnl else None}")
    print(f"  PnL sec B   IAE_norm->PnL_norm      : rho={B_pnl['rho'] if B_pnl else None}")
    print(f"  PERM: observed_max|assoc|={perm['observed_max_abs_assoc']} "
          f"null_p95={perm['null_p95']} pct={perm['empirical_percentile']}% ({perm['interpretation']})")
    print(f"  MFE xcheck: mean|diff|={mfe_xcheck_summary['mean_abs_diff']} "
          f"max|diff|={mfe_xcheck_summary['max_abs_diff']}")
    print(f"  >>> DECISION: OBSERVATION (仅描述数据, 不推导交易结论)")
    print(f"  写出: {OUT_JSON}")


if __name__ == "__main__":
    main()
