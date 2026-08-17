# -*- coding: utf-8 -*-
"""
Entry Quality Observation EQ-1  --  Entry Timing Distance (ETD) vs Risk/Opportunity/Exit (Pre-Registered)
=========================================================================================================

研究契约：docs/EQ1_PreRegistration_v0.1.md + backend/output/research_contracts/RC-EQ1-PREREG-v0.1.json
状态：PRE-REGISTRATION FROZEN -> IMPLEMENTATION（仅写、未运行；首次运行受 Gate 0 约束）

设计铁律（来自用户架构约束，禁止违反）：
1. 只读三份源：trade_path.json（210 笔交易）、XAUUSD_M5.csv（M5 K 线）。Outcome 仅由 entry 之后已收盘 bar 计算。
   CP/ETD 仅由 entry 之前已收盘 bar 计算（复用 H2-A 的 bisect_right(times, entry_unix-300) 纪律，杜绝 micro look-ahead）。
2. 中性暴露：ETD 只度量 entry 在客观市场结构中的时间位置，不预设「提前=差」方向。
3. 不读任何 E1-E4 标签、不读 MFE/MAE/capture 生成 CP/ETD；Outcome（IAE/MFE/Giveback/P&L）由 M5 棒自算，
   与 trade_path.json 的 mfe_usd/mae_usd 仅做交叉校验（diagnostic，不改任何定义）。
4. 不做 trailing 重模拟；不优化任何阈值；不搜最佳变量；不改 Contract；不进生产/CIO/Trading Coach。
5. **第一次 Run 只描述数据（Observation），不推导任何交易结论。** 输出注明 OBSERVATION_ONLY。
6. 预登记完整性 + 契约令牌为本脚本第一道 Gate：任何一项不匹配 -> 立即 STOP（sys.exit(2)），不产生 observation result。
7. CP 确认边界（用户审计修正 #1）：CP 候选须满足 CP_bar_index + k <= entry_reference_bar_index，
   否则未确认局部极值可能误作 CP -> STOP。
8. 全报纪律：H1-H4 无论方向/显著与否全报告，禁 cherry-pick。
9. no-CP = 排除该笔并报 exclusion_rate，不设 fallback。
10. permutation seed 固定（20260815），保证可复现；仅 diagnostic，不新增 Hard Gate。
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
PREREG_MD = os.path.join(ROOT, "docs", "EQ1_PreRegistration_v0.1.md")
CONTRACT_JSON = os.path.join(ROOT, "backend", "output", "research_contracts", "RC-EQ1-PREREG-v0.1.json")
OUT_DIR = os.path.join(ROOT, "backend", "output", "research_contracts")
OUT_JSON = os.path.join(OUT_DIR, "eq1_observation_v0_1.json")

# ---------- 冻结常量（与预登记文档 + JSON 契约逐字一致；改动须同步改文档并重新走 Gate） ----------
K = 2                      # swing 确认半径（左右各 k 根）
W = 48                     # CP 向前搜索窗口（M5 根）
IAE_WIN = 10               # IAE = entry 后 10 根完整 M5 最大逆向 excursion (R1 冻结)
PREREG_VERSION = "v0.1"
N_PERM = 2000              # permutation 次数
PERM_SEED = 20260815       # 固定随机种子
PERM_STAT = "max|assoc| over H1-H4"   # primary permutation statistic
CONTRACT_MULT = 100.0      # XAUUSD 1 标准手 = 100 oz；USD = price_diff * 100 * volume

EXPERIMENT_ID = "EQ1-OBS-v0.1"
HYPOTHESIS = ("EQ-1: 在完全冻结的 Pre-Trade 信息集下, entry 相对最近方向性结构摆点(CP)的时间距离 ETD, "
              "是否与 IAE / MFE / Giveback / P&L 存在可识别的连续关系? 这是中性 Entry Quality 研究, "
              "非标签预测, 非模型优化.")

# 预登记文档必须包含的令牌（任一缺失即视为预登记被篡改 -> STOP）
PREREG_TOKENS = [
    "EQ-1 Pre-Registration v0.1",
    "k = 2",
    "W = 48",
    "IAE = entry 后 10 根",
    "CP_bar_index + k <= entry_reference_bar_index",
    "Spearman",
    "ETD_bars",
    "seed = 20260815",
    "2000",
    "max |assoc|",
    "aggregate diagnostics",
    "Observation-only",
    "no-CP",
    "H4",
]

# JSON 契约 frozen_tokens 必须与下列硬编码常量完全匹配（任一不符 -> STOP）
CONTRACT_TOKEN_CHECKS = {
    "k": 2,
    "W": 48,
    "iae_win": 10,
    "perm_n": 2000,
    "perm_seed": 20260815,
    "price_field": "High/Low",
    "no_cp": "exclude_report_rate",
    "etd_primary": "bars",
    "etd_secondary": "minutes",
    "entry_ref": "last_closed_bar_before_entry",
    "cp_confirm_rule": "CP_bar_index + k <= entry_reference_bar_index",
    "h3_mode": "precondition_association_not_mediation",
    "h4_mode": "exploratory_no_realization_primary",
    "pf_location": "aggregate_diagnostics_not_per_trade",
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
        "ci95_rho": ci,
        "t_stat": round(t, 3) if t is not None else None,
    }


def solve_linear(A, b):
    """高斯消元解小线性系统（部分主元）。A: n×n, b: n。返回解或 None（奇异）。"""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        M[col] = [v / pv for v in M[col]]
        for r in range(n):
            if r != col:
                f = M[r][col]
                if f != 0:
                    M[r] = [M[r][k] - f * M[col][k] for k in range(n + 1)]
    return [M[i][n] for i in range(n)]


def ols_1(x, y):
    """y ~ x（单预测子），返回 {slope, intercept, r2} 或 None。"""
    n = len(x)
    if n < 3 or len(set(x)) < 2:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    if sxx == 0:
        return None
    slope = sxy / sxx
    intercept = my - slope * mx
    yhat = [intercept + slope * a for a in x]
    sst = sum((b - my) ** 2 for b in y)
    ssr = sum((b - h) ** 2 for b, h in zip(y, yhat))
    r2 = 1 - ssr / sst if sst > 0 else None
    return {"slope": round(slope, 4), "intercept": round(intercept, 4),
            "r2": round(r2, 4) if r2 is not None else None}


def ols_2(x1, x2, y):
    """y ~ x1 + x2（双预测子 + 截距），返回 {b0,b1,b2,r2} 或 None。"""
    n = len(y)
    if n < 4:
        return None
    sx1 = sum(x1); sx2 = sum(x2); sy = sum(y)
    sx11 = sum(a * a for a in x1); sx22 = sum(a * a for a in x2)
    sx12 = sum(a * b for a, b in zip(x1, x2))
    sx1y = sum(a * b for a, b in zip(x1, y))
    sx2y = sum(a * b for a, b in zip(x2, y))
    A = [[n, sx1, sx2], [sx1, sx11, sx12], [sx2, sx12, sx22]]
    b = [sy, sx1y, sx2y]
    sol = solve_linear(A, b)
    if sol is None:
        return None
    b0, b1, b2 = sol
    yhat = [b0 + b1 * a + b2 * c for a, c in zip(x1, x2)]
    my = sy / n
    sst = sum((v - my) ** 2 for v in y)
    ssr = sum((v - h) ** 2 for v, h in zip(y, yhat))
    r2 = 1 - ssr / sst if sst > 0 else None
    return {"intercept": round(b0, 4), "slope_ETD": round(b1, 4), "slope_risk": round(b2, 4),
            "r2": round(r2, 4) if r2 is not None else None}


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

    # 3. eq1_result 状态必须为 PENDING（防重复运行篡改结论）
    eq1r = contract.get("eq1_result", {})
    if eq1r.get("status") not in (None, "PENDING"):
        gate_fail(f"契约 eq1_result.status={eq1r.get('status')} 非 PENDING，疑似已运行/已改 -> STOP")

    print(f"[GATE0 PASS] 预登记 mtime 早于运行, 版本={PREREG_VERSION}, "
          f"文档令牌 {len(PREREG_TOKENS)} 项齐全, 契约冻结令牌 {len(CONTRACT_TOKEN_CHECKS)} 项匹配, "
          f"eq1_result=PENDING -> 允许计算")
    return md_text, contract


# ----------------------------------------------------------------------------
# CP-D swing 检测（仅用 entry 之前已收盘 bar）
# ----------------------------------------------------------------------------
def find_cp(prior_bars, entry_ref_idx, direction):
    """在 prior_bars 的最后 W 根中找最近的方向性严格 (2k+1) 局部极值。
    返回 CP_bar_index 或 None（no-CP）。
    BUY -> swing high（High 严格大于左右各 k 根）；SELL -> swing low。
    取最近者（最大 index）；等价时取更晚（严格不等号下近乎不可能）。
    须满足 CP_bar_index + k <= entry_ref_idx（确认状态在 entry 前完成）。"""
    lo = max(0, entry_ref_idx + 1 - W)   # 窗口起点（entry_ref_idx 即 pi-1）
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
            else:  # SELL
                if not (prior_bars[i][3] < prior_bars[i - j][3] and prior_bars[i][3] < prior_bars[i + j][3]):
                    ok = False
                    break
        if ok:
            candidates.append(i)
    if not candidates:
        return None
    cp_idx = max(candidates)              # 最近者胜
    # CP 确认边界（用户审计修正 #1）
    if cp_idx + K > entry_ref_idx:
        return None                       # 未确认摆点 -> 视为 no-CP（保守）
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

    i_entry = bisect.bisect_right(times, entry_unix)   # 第一根严格晚于 entry
    i_exit = bisect.bisect_right(times, exit_unix)     # 第一根严格晚于 exit
    post = bars[i_entry:i_exit]                          # entry 后、exit 前的已收盘 bar

    # IAE：前 IAE_WIN 根最大逆向 excursion（USD）
    # 逆向 = BUY 时价格低于 entry（用 low=b[3]）；SELL 时价格高于 entry（用 high=b[2]）
    iae = 0.0
    for b in post[:IAE_WIN]:
        adv = adverse_usd(b[3], entry_price, direction, mult) if direction == "BUY" else adverse_usd(b[2], entry_price, direction, mult)
        if adv > iae:
            iae = adv

    # MFE / MAE：全程 post bar 的极值
    mfe = 0.0
    mae = 0.0
    for b in post:
        fav = favorable_usd(b[2], entry_price, direction, mult) if direction == "BUY" else favorable_usd(b[3], entry_price, direction, mult)
        adv = adverse_usd(b[3], entry_price, direction, mult) if direction == "BUY" else adverse_usd(b[2], entry_price, direction, mult)
        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv
    # 用 exit_price 作为最终点纳入 MFE/MAE
    fav_exit = favorable_usd(exit_price, entry_price, direction, mult)
    adv_exit = adverse_usd(exit_price, entry_price, direction, mult)
    if fav_exit > mfe:
        mfe = fav_exit
    if adv_exit > mae:
        mae = adv_exit

    giveback = max(0.0, mfe - max(0.0, fav_exit))   # 从 MFE 回吐到 exit 的幅度
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
        "mfe_file_usd": round(float(t.get("mfe_usd", 0.0)), 4),  # 仅交叉校验
    }


# ----------------------------------------------------------------------------
# Permutation Null（仅 diagnostic，不新增 Hard Gate）
# ----------------------------------------------------------------------------
def run_permutation(etd_list, outcomes_dict, rng_seed):
    """固定 ETD 边际分布，仅保边洗牌 ETD 跨交易配对；复刻 max|assoc|。
    outcomes_dict: {name: [per-trade value]}（与 etd_list 同序）。"""
    rng = random.Random(rng_seed)
    keys = list(outcomes_dict.keys())

    def stat_of(etd_perm):
        mx = 0.0
        for name in keys:
            y = outcomes_dict[name]
            if len(etd_perm) < 4:
                continue
            r = spearman(etd_perm, y)
            if r is not None:
                mx = max(mx, abs(r))
        return mx

    observed = stat_of(etd_list)
    null = []
    base = list(etd_list)
    for _ in range(N_PERM):
        perm = base[:]
        rng.shuffle(perm)
        null.append(stat_of(perm))
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
        "fixed": "ETD 边际分布固定; 仅保边洗牌 ETD 跨交易配对 (outcome 固定)",
        "observed_max_abs_assoc": round(observed, 4),
        "null_mean": round(mean, 4),
        "null_median": round(median, 4),
        "null_p95": round(p95, 4),
        "empirical_percentile": round(pct, 2),
        "interpretation": interp,
        "note": "Permutation 仅 diagnostic，不新增 Hard Gate；percentile<95 仅标 caveat。",
    }


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
    n_excluded_no_cp = 0
    mfe_xcheck = []
    for t in trades:
        tid = str(t["trade_id"])
        direction = t["direction"]
        entry_unix = parse_dt(t["entry_time"])
        # entry_reference_bar = 最后一根已收盘 M5 bar（bisect_right(time, entry_unix-300)）
        pi = bisect.bisect_right(times, entry_unix - 300)
        if pi < 1:
            n_excluded_no_cp += 1
            continue
        entry_ref_idx = pi - 1
        # Gate 0 #4：确认 entry_reference_bar 已收盘（close_time <= entry_unix）
        if bars[entry_ref_idx][0] + 300 > entry_unix:
            gate_fail(f"trade {tid}: entry_reference_bar 未收盘 (micro look-ahead)")
        prior_bars = [bars[k] for k in range(pi)]

        cp_idx = find_cp(prior_bars, entry_ref_idx, direction)
        if cp_idx is None:
            n_excluded_no_cp += 1
            continue
        # Gate 0 #3：CP 确认边界
        if cp_idx + K > entry_ref_idx:
            gate_fail(f"trade {tid}: CP 确认边界违例 (CP+k={cp_idx+K} > entry_ref={entry_ref_idx})")

        etd_bars = entry_ref_idx - cp_idx
        etd_minutes = (entry_unix - bars[cp_idx][0]) / 60.0

        oc = compute_outcomes(t, bars, times, entry_unix, entry_ref_idx)
        rec = {
            "trade_id": tid,
            "direction": direction,
            "entry_time": t["entry_time"],
            "cp_bar_index": cp_idx,
            "entry_reference_bar_index": entry_ref_idx,
            "etd_bars": etd_bars,
            "etd_minutes": round(etd_minutes, 2),
            **oc,
        }
        # 交叉校验：自算 MFE vs 文件 mfe_usd（仅 diagnostic）
        mfe_xcheck.append((oc["MFE_usd"], oc["mfe_file_usd"]))
        rows.append(rec)

    n_total = len(trades)
    n_valid = len(rows)
    exclusion_rate = n_excluded_no_cp / n_total if n_total else 0.0

    # 向量抽取
    def col(name):
        return [r[name] for r in rows]

    etd_b = col("etd_bars")
    iae = col("IAE_usd")
    mfe = col("MFE_usd")
    give = col("Giveback_usd")
    pnl = col("PnL_usd")
    initr = [r["initial_risk_usd"] for r in rows]

    # ---- 假设关联（Primary = Spearman） ----
    h1 = corr_block(etd_b, iae)       # ETD -> IAE
    h2 = corr_block(etd_b, mfe)       # ETD -> MFE
    h3 = corr_block(iae, give)        # IAE -> Giveback (Exit Quality)

    # ---- H4 exploratory：每个原始连续 Outcome 对 ETD（Primary 不用 MFE Realization） ----
    h4 = {}
    for name, vec in [("Giveback_usd", give), ("MFE_usd", mfe), ("PnL_usd", pnl)]:
        blk = corr_block(etd_b, vec) or {}
        ols_e = ols_1(etd_b, vec)
        blk["ols_slope_vs_ETD"] = ols_e
        h4[name] = blk

    # H4 双预测子（SL 子集，initial_risk 可用）
    sl_idx = [i for i in range(n_valid) if initr[i] is not None]
    h4_risk = {}
    if len(sl_idx) >= 10:
        etd_sl = [etd_b[i] for i in sl_idx]
        risk_sl = [initr[i] for i in sl_idx]
        for name, vec_full in [("Giveback_usd", give), ("MFE_usd", mfe), ("PnL_usd", pnl)]:
            y_sl = [vec_full[i] for i in sl_idx]
            ols2 = ols_2(etd_sl, risk_sl, y_sl)
            sp_risk = spearman(risk_sl, y_sl)
            h4_risk[name] = {
                "n_sl_subset": len(sl_idx),
                "spearman_ETD": spearman(etd_sl, y_sl),
                "spearman_initial_risk": round(sp_risk, 4) if sp_risk is not None else None,
                "ols_ETD_plus_risk": ols2,
            }

    # ---- R 标准化（Secondary，仅 SL 子集） ----
    r_norm = {}
    if len(sl_idx) >= 10:
        for name, vec_full in [("IAE_usd", iae), ("MFE_usd", mfe), ("Giveback_usd", give), ("PnL_usd", pnl)]:
            rn = [vec_full[i] / initr[i] for i in sl_idx if initr[i] and initr[i] > 0]
            if rn:
                r_norm[name] = {
                    "n": len(rn),
                    "mean_R": round(sum(rn) / len(rn), 4),
                    "median_R": round(sorted(rn)[len(rn) // 2], 4),
                }

    # ---- Permutation Null（max|assoc| over H1/H2/H3 + H4 outcomes） ----
    perm_outcomes = {
        "H1_ETD_IAE": iae,
        "H2_ETD_MFE": mfe,
        "H3_IAE_Giveback": give,
        "H4_ETD_Giveback": give,
        "H4_ETD_MFE": mfe,
        "H4_ETD_PnL": pnl,
    }
    perm = run_permutation(etd_b, perm_outcomes, PERM_SEED)

    # ---- 描述统计 ----
    def desc(v):
        if not v:
            return None
        sv = sorted(v)
        return {"n": len(v), "mean": round(sum(v) / len(v), 4),
                "median": round(sv[len(v) // 2], 4),
                "min": round(min(v), 4), "max": round(max(v), 4)}

    desc_stats = {
        "ETD_bars": desc(etd_b),
        "IAE_usd": desc(iae),
        "MFE_usd": desc(mfe),
        "Giveback_usd": desc(give),
        "PnL_usd": desc(pnl),
    }

    # MFE 交叉校验
    if mfe_xcheck:
        diffs = [abs(a - b) for a, b in mfe_xcheck]
        mfe_xcheck_summary = {
            "n": len(diffs),
            "mean_abs_diff": round(sum(diffs) / len(diffs), 4),
            "max_abs_diff": round(max(diffs), 4),
            "note": "自算 MFE (从 M5 棒) vs 文件 mfe_usd；差异来自手续费/取整或管线不同定义，仅 diagnostic。",
        }
    else:
        mfe_xcheck_summary = None

    # ---- provenance ----
    entry_times = [parse_dt(t["entry_time"]) for t in trades]
    prov = {
        "dataset": "XAUUSD M5 / MT5 210 trades (2026-03-02 ~ 2026-08-05)",
        "trade_count_total": n_total,
        "trade_count_valid_CP": n_valid,
        "n_excluded_no_cp": n_excluded_no_cp,
        "exclusion_rate": round(exclusion_rate, 4),
        "n_with_initial_risk": sum(1 for r in rows if r["initial_risk_usd"] is not None),
        "entry_time_range": {
            "start": datetime.fromtimestamp(min(entry_times), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": datetime.fromtimestamp(max(entry_times), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "preregistration_version": PREREG_VERSION,
        "preregistration_mtime": round(os.path.getmtime(PREREG_MD), 0),
        "run_timestamp": run_iso,
        "cp_definition": "严格(2k+1)局部极值; k=2; W=48; Long->swing high, Short->swing low; "
                         "最近者胜; CP_bar_index+k<=entry_reference_bar_index",
        "etd_definition": "ETD_bars = entry_reference_bar_index - CP_bar_index (Primary); "
                          "ETD_minutes = (entry_unix - CP_time)/60 (Secondary)",
        "outcome_definition": "IAE=entry后10根最大逆向excursion; MFE=entry后最大有利excursion; "
                              "Giveback=max(0,MFE-退出有利excursion); 均从M5棒自算, 合约mult=100*volume",
        "observation_only": True,
    }

    out = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": HYPOTHESIS,
        "governance": "OBSERVATION_ONLY. 不接 run_daily/risk_guard/shadow/CIO/Trading Coach/生产. "
                      "不读 E1-E4 标签, 不读 MFE/MAE/capture 生成 CP/ETD, 不优化阈值, 不搜变量, 不改 Contract. "
                      "第一次 Run 只描述数据, 不推导交易结论.",
        "preregistration_check": {
            "doc_exists": True,
            "mtime_ok": True,
            "run_approved": True,
            "tokens_present": {t: (t in md_text) for t in PREREG_TOKENS},
            "note": "Gate 0 通过才允许计算; 任何一项失败 -> sys.exit(2), 不产生结果.",
        },
        "contract_token_check": {k: (ft_ok := (contract.get("frozen_tokens", {}).get(k) == v))
                                 for k, v in CONTRACT_TOKEN_CHECKS.items()},
        "frozen_constants": {
            "K": K, "W": W, "IAE_WIN": IAE_WIN, "PREREG_VERSION": PREREG_VERSION,
            "N_PERM": N_PERM, "PERM_SEED": PERM_SEED, "PERM_STAT": PERM_STAT,
            "CONTRACT_MULT": CONTRACT_MULT,
        },
        "provenance": prov,
        "descriptive_stats": desc_stats,
        "hypotheses": {
            "H1_ETD_to_IAE": h1,
            "H2_ETD_to_MFE": h2,
            "H3_IAE_to_ExitQuality_Giveback": h3,
            "H4_exploratory_ETD_to_ExecutionOutcome": h4,
            "H4_with_initial_risk_SL_subset": h4_risk,
        },
        "R_normalized_secondary_SL_subset": r_norm,
        "permutation_null": perm,
        "mfe_crosscheck": mfe_xcheck_summary,
        "decision": "OBSERVATION",
        "decision_rationale": ("第一次 Run 仅描述 210 笔交易在 ETD/IAE/MFE/Giveback/P&L 的连续关系, "
                              "不做 pass/fail 判定, 不推导任何交易结论。后续解释与未来假设须独立进行。"),
        "interpretation_allowed": False,
        "implementation_notes": [
            "CP-D：严格 (2k+1) 局部极值; k=2, W=48; Long->swing high, Short->swing low; 最近者胜; 等价取更晚。",
            "micro look-ahead 排除：M5 的 time 为 bar 开盘时间, bar 在 time+300s 收盘; 仅用 close_time=time+300<=entry_unix 的已收盘 bar; entry_reference_bar=最后已收盘 bar。",
            "CP 确认边界（审计修正#1）：CP_bar_index + k <= entry_reference_bar_index，未确认摆点一律排除（no-CP）。",
            "ETD 完全中性：报告 ETD->IAE / ETD->MFE / IAE->Giveback 三种可能方向均接受，无「提前=差」先验。",
            "H3 降级为中介前置关联检验（审计修正#2）：v0.1 不执行正式 mediation；仅 Spearman(IAE,Giveback)。",
            "H4 降级 exploratory（审计修正#3）：Primary 不用未处理 MFE Realization；报告 Giveback/MFE/P&L 原始连续量对 ETD 的关联 + SL 子集 ETD+initial_risk 双预测子。",
            "PF 移 aggregate diagnostics（审计修正#4）：PF/Sharpe/MaxDD/win_rate 为样本级聚合，不进单笔 ETD->outcome；本报告未计算 PF（属独立聚合诊断）。",
            "initial_risk 仅 142/210 笔有 sl_trigger_price（exit_reason=sl），其余 68 笔无预设计止损 -> R 标准化与 H4 risk 协变量仅在 SL 子集；此为数据缺口，非参数修改。",
            "MFE/IAE/Giveback 自 M5 棒计算（合约 mult=100*volume），与文件 mfe_usd 仅交叉校验（diagnostic）。",
            "Permutation Null：固定 ETD 边际分布，仅保边洗牌 ETD 跨交易配对，2000 次(seed=20260815)复刻 max|assoc|；仅 diagnostic。",
            "全报纪律：H1-H4 无论方向/显著与否全报告。",
        ],
        "per_trade": rows,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print(f"[{EXPERIMENT_ID}] n_total={n_total} n_valid={n_valid} "
          f"excluded_noCP={n_excluded_no_cp} exclusion_rate={exclusion_rate:.3f}")
    print(f"  H1 ETD->IAE : {h1}")
    print(f"  H2 ETD->MFE : {h2}")
    print(f"  H3 IAE->Give: {h3}")
    for name, blk in h4.items():
        print(f"  H4 {name} vs ETD: rho={blk.get('rho')} n={blk.get('n')} "
              f"ols_slope={blk.get('ols_slope_vs_ETD')}")
    print(f"  PERM: observed_max|assoc|={perm['observed_max_abs_assoc']} "
          f"null_p95={perm['null_p95']} pct={perm['empirical_percentile']}% ({perm['interpretation']})")
    if mfe_xcheck_summary:
        print(f"  MFE xcheck: mean|diff|={mfe_xcheck_summary['mean_abs_diff']} "
              f"max|diff|={mfe_xcheck_summary['max_abs_diff']}")
    print(f"  >>> DECISION: OBSERVATION (仅描述数据, 不推导交易结论)")
    print(f"  写出: {OUT_JSON}")


if __name__ == "__main__":
    main()
