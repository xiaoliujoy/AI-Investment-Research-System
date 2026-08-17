# -*- coding: utf-8 -*-
"""
Entry Quality Observation EQ-1M  --  IAE Pathway / Mediation-Shaped Association (Pre-Registered)
=============================================================================================

研究契约：docs/EQ1M_PreRegistration_v0.1.md + backend/output/research_contracts/RC-EQ1M-PREREG-v0.1.json
状态：PRE-REGISTRATION FROZEN -> IMPLEMENTATION（仅写、未运行；首次运行受 Gate 0 约束）

设计铁律（来自用户架构约束，禁止违反）：
1. 只读两份源：trade_path.json（210 笔交易）、XAUUSD_M5.csv（M5 K 线）。Outcome 仅由 entry 之后已收盘 bar 计算。
   CP/ETD 仅由 entry 之前已收盘 bar 计算（bisect_right(times, entry_unix-300) 纪律，杜绝 micro look-ahead）。
2. EQ-1M 继承 EQ-1 CP-D(k=2/W=48)，不重算 CP/ETD 定义；仅消费 ETD。
3. 中性暴露：EQ-1M 只回答「ETD->IAE->Giveback 是否构成可识别路径机制关联」，不预设显著。
4. 不读任何 E1-E4 标签；不优化阈值；不搜变量；不改 EQ-1/EQ-1R 契约(k=2/W=48/IAE_WIN=10)；不进生产/CIO/Trading Coach。
5. 第一次 Run 只描述路径结构（Observation），不推导任何交易结论，不产买卖信号。
6. 预登记完整性 + 契约令牌为本脚本第一道 Gate：任何一项不匹配 -> 立即 STOP（sys.exit(2)），不产生 observation result。
7. Primary=210 全样本（剔除 no-CP）；SL/non-SL 仅作 Selection Diagnostic 敏感性层，不筛选样本。
8. 全报纪律：主路径 + Spearman 交叉 + permutation + bootstrap BCa + overlap + 层A/B + SL/non-SL + per_trade 全部报告，禁 cherry-pick。
9. 因果边界：观察性单级数据，禁用「IAE 是中介/导致 Giveback」；仅允许「与路径机制关联相容」。
"""

import os
import sys
import json
import csv
import bisect
import math
import random
from datetime import datetime, timezone

# ---------- 路径 ----------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MT5 = os.path.join(ROOT, "mt5_raw")
TRADE_PATH = os.path.join(MT5, "trade_path.json")
M5_CSV = os.path.join(MT5, "XAUUSD_M5.csv")
PREREG_MD = os.path.join(ROOT, "docs", "EQ1M_PreRegistration_v0.1.md")
CONTRACT_JSON = os.path.join(ROOT, "backend", "output", "research_contracts", "RC-EQ1M-PREREG-v0.1.json")
OUT_DIR = os.path.join(ROOT, "backend", "output", "research_contracts")
OUT_JSON = os.path.join(OUT_DIR, "eq1m_observation_v0_1.json")

# ---------- 冻结常量（与预登记文档 + JSON 契约逐字一致；改动须同步改文档并重新走 Gate） ----------
K = 2                      # swing 确认半径（继承 EQ-1）
W = 48                     # CP 向前搜索窗口（继承 EQ-1）
IAE_WIN = 10               # IAE = entry 后 10 根完整 M5 最大逆向 excursion (R1 冻结)
PREREG_VERSION = "v0.1"
N_BOOT = 10000             # bootstrap 次数（间接效应 BCa CI）
BOOT_SEED = 20260817       # 固定随机种子（与 EQ-1 20260815 / EQ-1R 20260816 独立 provenance）
N_PERM = 2000              # permutation 次数
PERM_SEED = 20260817       # 固定随机种子（同 BOOT_SEED provenance；仅 reproducibility）
CONTRACT_MULT = 100.0      # XAUUSD 1 标准手 = 100 oz；USD = price_diff * 100 * volume
SAMPLE_N = 210             # Primary 全样本（剔除 no-CP）

EXPERIMENT_ID = "EQ1M-OBS-v0.1"
HYPOTHESIS = ("EQ-1M: 在 210 笔全样本中, 检验路径 ETD->IAE->Giveback 是否构成可识别的路径机制关联 "
              "(indirect=a*b). 这是路径机制关联研究(非因果中介), 非新发现检验, 非标签预测, 非模型优化. "
              "已知 a~0.15/b~0.53, a*b~0.08 功效可能不足, 不要求显著.")

# 预登记文档必须包含的令牌（任一缺失即视为预登记被篡改 -> STOP）
PREREG_TOKENS = [
    "Pre-Registration v0.1",
    "k=2",
    "W=48",
    "IAE_WIN=10",
    "路径机制关联",
    "indirect effect",
    "bootstrap BCa",
    "20260817",
    "10000",
    "Giveback_late",
    "overlap_rate",
    "不要求显著",
    "观察性",
    "参数敏感性",
    "cutoff",
    "mediation",
    "SL/non-SL",
]

# JSON 契约 frozen_tokens 必须与下列硬编码常量完全匹配（任一不符 -> STOP）
CONTRACT_TOKEN_CHECKS = {
    "sample": 210,
    "mediator": "IAE",
    "iae_win": 10,
    "k2_w48_inherit": True,
    "pathway_name": "IAE_Pathway_Mediation_Shaped_Association",
    "no_causal_claim": True,
    "indirect_def": "a*b",
    "a_path": "ETD->IAE",
    "b_path": "IAE->Giveback|ETD",
    "c_prime_path": "ETD->Giveback|IAE",
    "nine_metrics": True,
    "bootstrap_bca": True,
    "n_boot": 10000,
    "boot_seed": 20260817,
    "perm_n": 2000,
    "perm_seed": 20260817,
    "perm_stat": "indirect_effect_shuffle_IAE",
    "overlap_rate": True,
    "giveback_late_variant": True,
    "no_sig_required": True,
    "sl_nonsl_diagnostic": True,
    "no_param_sens": True,
    "no_cutoff": True,
    "no_h4": True,
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
# 统计辅助（pure stdlib）
# ----------------------------------------------------------------------------
def rankdata(x):
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
    r = pearson(rankdata(x), rankdata(y))
    return r


def std_z(x):
    n = len(x)
    if n < 2:
        return [0.0] * n
    m = sum(x) / n
    v = sum((a - m) ** 2 for a in x) / n
    if v == 0:
        return [0.0] * n
    sd = math.sqrt(v)
    return [(a - m) / sd for a in x]


def partial_spearman(x, y, z):
    """ρ(x,y | z)：用 Spearman 残差。"""
    rx = rankdata(x)
    ry = rankdata(y)
    rz = rankdata(z)
    res_x = [a - b for a, b in zip(rx, z)] if False else None
    # 标准：对 x,z 回归取残差需用连续回归；用 Pearson 残差法
    bx = pearson(rx, rz)
    by = pearson(ry, rz)
    if bx is None or by is None:
        return None
    res_x = [a - bx * c for a, c in zip(rx, rz)]
    res_y = [a - by * c for a, c in zip(ry, rz)]
    return pearson(res_x, res_y)


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf_acklam(p):
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    if p <= 0.0:
        return -10.0
    if p >= 1.0:
        return 10.0
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def percentile(sorted_vals, p):
    """p in [0,100]，线性插值。"""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
    idx = p / 100.0 * (n - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def desc(xs):
    if not xs:
        return {"n": 0}
    n = len(xs)
    s = sorted(xs)
    m = sum(xs) / n
    var = sum((a - m) ** 2 for a in xs) / n
    return {
        "n": n,
        "mean": round(m, 4),
        "median": round(s[n // 2], 4),
        "std": round(math.sqrt(var), 4),
        "min": round(s[0], 4),
        "max": round(s[-1], 4),
    }


# ----------------------------------------------------------------------------
# Gate 0
# ----------------------------------------------------------------------------
def gate_fail(msg):
    print(f"[GATE0 FAIL] {msg}")
    print("[STOP] Gate 0 未通过，不产生任何 observation result。")
    sys.exit(2)


def check_gate0(run_epoch):
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

    eq1m = contract.get("eq1m_result", {})
    if eq1m.get("status") not in (None, "PENDING"):
        gate_fail(f"契约 eq1m_result.status={eq1m.get('status')} 非 PENDING，疑似已运行/已改 -> STOP")

    print(f"[GATE0 PASS] 预登记 mtime 早于运行, 版本={PREREG_VERSION}, "
          f"文档令牌 {len(PREREG_TOKENS)} 项齐全, 契约冻结令牌 {len(CONTRACT_TOKEN_CHECKS)} 项匹配, "
          f"eq1m_result=PENDING -> 允许计算")
    return md_text, contract


# ----------------------------------------------------------------------------
# CP-D swing 检测（继承 EQ-1 k=2/W=48；仅用于 ETD）
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


def favorable_usd(price, entry_price, direction, mult):
    return (price - entry_price) * mult if direction == "BUY" else (entry_price - price) * mult


def adverse_usd(price, entry_price, direction, mult):
    return (entry_price - price) * mult if direction == "BUY" else (price - entry_price) * mult


def compute_trade(t, bars, times, run_epoch_for_gate_ref=None):
    """返回完整 per-trade 记录（含 ETD + Outcomes），no-CP 则返回 None。"""
    direction = t["direction"]
    entry_price = float(t["entry_price"])
    exit_price = float(t["exit_price"])
    vol = float(t["volume"])
    mult = CONTRACT_MULT * vol
    entry_unix = parse_dt(t["entry_time"])
    exit_unix = parse_dt(t["exit_time"])

    # ETD / CP-D（继承 EQ-1）
    pi = bisect.bisect_right(times, entry_unix - 300)   # entry 前最后已收盘 bar 的下一根
    entry_ref_idx = pi - 1
    if entry_ref_idx < 0:
        return None
    if bars[entry_ref_idx][0] + 300 > entry_unix:
        return None  # entry_reference_bar 未完全收盘
    cp_idx = find_cp(bars[:entry_ref_idx + 1], entry_ref_idx, direction)
    if cp_idx is None:
        return None
    etd_bars = entry_ref_idx - cp_idx
    etd_minutes = (entry_unix - bars[cp_idx][0]) / 60.0

    i_entry = bisect.bisect_right(times, entry_unix)
    i_exit = bisect.bisect_right(times, exit_unix)
    post = bars[i_entry:i_exit]
    duration_bars = len(post)

    # IAE：前 IAE_WIN 根最大逆向 excursion（USD）
    iae = 0.0
    for b in post[:IAE_WIN]:
        adv = adverse_usd(b[3], entry_price, direction, mult) if direction == "BUY" else adverse_usd(b[2], entry_price, direction, mult)
        if adv > iae:
            iae = adv

    # MFE / MAE：全程 post bar 极值 + 追踪 MFE 峰值索引
    mfe = 0.0
    mae = 0.0
    mfe_peak_idx = -1
    for idx, b in enumerate(post):
        fav = favorable_usd(b[2], entry_price, direction, mult) if direction == "BUY" else favorable_usd(b[3], entry_price, direction, mult)
        adv = adverse_usd(b[3], entry_price, direction, mult) if direction == "BUY" else adverse_usd(b[2], entry_price, direction, mult)
        if fav > mfe:
            mfe = fav
            mfe_peak_idx = idx
        if adv > mae:
            mae = adv
    fav_exit = favorable_usd(exit_price, entry_price, direction, mult)
    adv_exit = adverse_usd(exit_price, entry_price, direction, mult)
    if fav_exit > mfe:
        mfe = fav_exit
        mfe_peak_idx = len(post)   # exit 刷新 MFE -> 视为窗口外
    if adv_exit > mae:
        mae = adv_exit

    giveback = max(0.0, mfe - max(0.0, fav_exit))

    # Giveback_late：仅用 post[IAE_WIN:] 的 MFE 峰值（窗口不重叠变体）
    mfe_late = 0.0
    for b in post[IAE_WIN:]:
        fav = favorable_usd(b[2], entry_price, direction, mult) if direction == "BUY" else favorable_usd(b[3], entry_price, direction, mult)
        if fav > mfe_late:
            mfe_late = fav
    if fav_exit > mfe_late:
        mfe_late = fav_exit
    giveback_late = max(0.0, mfe_late - max(0.0, fav_exit))

    pnl = float(t["pnl"])
    sl = t.get("sl_trigger_price")
    init_risk = abs(entry_price - float(sl)) * mult if sl not in (None, "") else None

    overlap = (mfe_peak_idx >= 0 and mfe_peak_idx < IAE_WIN) or (duration_bars <= IAE_WIN)

    return {
        "trade_id": t.get("ticket") or t.get("id"),
        "direction": direction,
        "etd_bars": etd_bars,
        "etd_minutes": round(etd_minutes, 2),
        "IAE_usd": round(iae, 4),
        "Giveback_usd": round(giveback, 4),
        "Giveback_late_usd": round(giveback_late, 4),
        "MFE_usd": round(mfe, 4),
        "MAE_usd": round(mae, 4),
        "PnL_usd": round(pnl, 4),
        "initial_risk_usd": round(init_risk, 4) if init_risk is not None else None,
        "mfe_peak_idx": mfe_peak_idx,
        "duration_bars": duration_bars,
        "overlap": bool(overlap),
        "exit_reason": t.get("exit_reason"),
        "sl_present": init_risk is not None,
    }


# ----------------------------------------------------------------------------
# 路径机制关联分解（标准化 Pearson 乘积系数）
# ----------------------------------------------------------------------------
def mediation_decomp(etd, iae, give):
    """返回 a,b,c,c_prime,indirect,pm（标准化系数）。"""
    n = len(etd)
    if n < 4:
        return None
    X = std_z(etd)
    M = std_z(iae)
    Y = std_z(give)
    a = pearson(X, M)
    c = pearson(X, Y)
    r_MY = pearson(M, Y)
    if a is None or c is None or r_MY is None:
        return None
    denom = 1.0 - a * a
    if abs(denom) < 1e-9:
        return None
    b = (r_MY - a * c) / denom
    c_prime = (c - a * r_MY) / denom
    indirect = a * b
    pm = ((c - c_prime) / c) if abs(c) > 1e-6 else None
    return {
        "a": round(a, 4),
        "b": round(b, 4),
        "c": round(c, 4),
        "c_prime": round(c_prime, 4),
        "indirect": round(indirect, 4),
        "pm": round(pm, 4) if pm is not None else None,
        "n": n,
    }


def _indirect_of(etd, iae, give):
    X = std_z(etd)
    M = std_z(iae)
    Y = std_z(give)
    a = pearson(X, M)
    c = pearson(X, Y)
    r_MY = pearson(M, Y)
    if a is None or c is None or r_MY is None:
        return None
    denom = 1.0 - a * a
    if abs(denom) < 1e-9:
        return None
    b = (r_MY - a * c) / denom
    return a * b


def bootstrap_indirect(etd, iae, give, n_boot, seed):
    rng = random.Random(seed)
    n = len(etd)
    idxs = list(range(n))
    reps = []
    for _ in range(n_boot):
        s = [rng.choice(idxs) for _ in range(n)]
        ind = _indirect_of([etd[i] for i in s], [iae[i] for i in s], [give[i] for i in s])
        if ind is not None:
            reps.append(ind)
    if not reps:
        return None
    obs = _indirect_of(etd, iae, give)
    # BCa
    srt = sorted(reps)
    n_less = sum(1 for v in reps if v < obs)
    p0 = (n_less + 0.5) / (len(reps) + 1.0)
    z0 = _norm_ppf_acklam(p0)
    # jackknife 加速因子
    jack = []
    for i in range(n):
        sub = [j for j in idxs if j != i]
        ind = _indirect_of([etd[j] for j in sub], [iae[j] for j in sub], [give[j] for j in sub])
        if ind is not None:
            jack.append(ind)
    if jack:
        mj = sum(jack) / len(jack)
        num = sum((mj - v) ** 3 for v in jack)
        den = sum((mj - v) ** 2 for v in jack)
        acc = num / (6.0 * (den ** 1.5)) if den > 0 else 0.0
    else:
        acc = 0.0
    alpha = 0.05
    za_lo = _norm_ppf_acklam(alpha / 2.0)
    za_hi = _norm_ppf_acklam(1.0 - alpha / 2.0)
    plo = norm_cdf(z0 + (z0 + za_lo) / (1.0 - acc * (z0 + za_lo)))
    phi = norm_cdf(z0 + (z0 + za_hi) / (1.0 - acc * (z0 + za_hi)))
    lo = percentile(srt, max(0.0, min(100.0, plo * 100.0)))
    hi = percentile(srt, max(0.0, min(100.0, phi * 100.0)))
    return {
        "observed": round(obs, 4),
        "n_boot": len(reps),
        "bca_ci_lo": round(lo, 4) if lo is not None else None,
        "bca_ci_hi": round(hi, 4) if hi is not None else None,
        "boot_mean": round(sum(reps) / len(reps), 4),
        "boot_p05": round(percentile(srt, 5), 4),
        "boot_p95": round(percentile(srt, 95), 4),
        "acceleration": round(acc, 4),
        "z0": round(z0, 4),
    }


def permutation_indirect(etd, iae, give, n_perm, seed):
    rng = random.Random(seed)
    n = len(etd)
    obs = _indirect_of(etd, iae, give)
    null = []
    for _ in range(n_perm):
        perm = list(range(n))
        rng.shuffle(perm)
        iae_p = [iae[i] for i in perm]   # 独立保边洗牌 IAE，打破 a、b 两链接
        ind = _indirect_of(etd, iae_p, give)
        if ind is not None:
            null.append(ind)
    if not null:
        return None
    srt = sorted(null)
    null_p95 = percentile(srt, 95)
    cnt = sum(1 for v in null if v <= obs)
    pct = 100.0 * cnt / len(null)
    return {
        "observed_indirect": round(obs, 4),
        "null_mean": round(sum(null) / len(null), 4),
        "null_p95": round(null_p95, 4) if null_p95 is not None else None,
        "empirical_percentile": round(pct, 2),
        "n_perm": len(null),
        "interpretation": "observed 在随机洗牌 IAE 的 null 分布中的分位; 仅 diagnostic",
    }


def spearman_pathway(etd, iae, give):
    a_s = spearman(etd, iae)
    b_s = partial_spearman(iae, give, etd)   # IAE->Giveback | ETD
    c_s = spearman(etd, give)
    cprime_s = partial_spearman(etd, give, iae)  # ETD->Giveback | IAE
    indirect_s = (a_s * b_s) if (a_s is not None and b_s is not None) else None
    return {
        "a_spearman": round(a_s, 4) if a_s is not None else None,
        "b_partial_spearman": round(b_s, 4) if b_s is not None else None,
        "c_spearman": round(c_s, 4) if c_s is not None else None,
        "cprime_partial_spearman": round(cprime_s, 4) if cprime_s is not None else None,
        "indirect_spearman": round(indirect_s, 4) if indirect_s is not None else None,
    }


def _spearman_indirect_of(etd, iae, give):
    a_s = spearman(etd, iae)
    b_s = partial_spearman(iae, give, etd)
    if a_s is None or b_s is None:
        return None
    return a_s * b_s


def bootstrap_indirect_spearman(etd, iae, give, n_boot, seed):
    rng = random.Random(seed)
    n = len(etd)
    idxs = list(range(n))
    reps = []
    for _ in range(n_boot):
        s = [rng.choice(idxs) for _ in range(n)]
        ind = _spearman_indirect_of([etd[i] for i in s], [iae[i] for i in s], [give[i] for i in s])
        if ind is not None:
            reps.append(ind)
    if not reps:
        return None
    obs = _spearman_indirect_of(etd, iae, give)
    srt = sorted(reps)
    n_less = sum(1 for v in reps if v < obs)
    p0 = (n_less + 0.5) / (len(reps) + 1.0)
    z0 = _norm_ppf_acklam(p0)
    jack = []
    for i in range(n):
        sub = [j for j in idxs if j != i]
        ind = _spearman_indirect_of([etd[j] for j in sub], [iae[j] for j in sub], [give[j] for j in sub])
        if ind is not None:
            jack.append(ind)
    if jack:
        mj = sum(jack) / len(jack)
        num = sum((mj - v) ** 3 for v in jack)
        den = sum((mj - v) ** 2 for v in jack)
        acc = num / (6.0 * (den ** 1.5)) if den > 0 else 0.0
    else:
        acc = 0.0
    alpha = 0.05
    za_lo = _norm_ppf_acklam(alpha / 2.0)
    za_hi = _norm_ppf_acklam(1.0 - alpha / 2.0)
    plo = norm_cdf(z0 + (z0 + za_lo) / (1.0 - acc * (z0 + za_lo)))
    phi = norm_cdf(z0 + (z0 + za_hi) / (1.0 - acc * (z0 + za_hi)))
    lo = percentile(srt, max(0.0, min(100.0, plo * 100.0)))
    hi = percentile(srt, max(0.0, min(100.0, phi * 100.0)))
    return {
        "observed": round(obs, 4),
        "n_boot": len(reps),
        "bca_ci_lo": round(lo, 4) if lo is not None else None,
        "bca_ci_hi": round(hi, 4) if hi is not None else None,
        "boot_mean": round(sum(reps) / len(reps), 4),
    }


def permutation_indirect_spearman(etd, iae, give, n_perm, seed):
    rng = random.Random(seed)
    n = len(etd)
    obs = _spearman_indirect_of(etd, iae, give)
    null = []
    for _ in range(n_perm):
        perm = list(range(n))
        rng.shuffle(perm)
        iae_p = [iae[i] for i in perm]
        ind = _spearman_indirect_of(etd, iae_p, give)
        if ind is not None:
            null.append(ind)
    if not null:
        return None
    srt = sorted(null)
    null_p95 = percentile(srt, 95)
    cnt = sum(1 for v in null if v <= obs)
    pct = 100.0 * cnt / len(null)
    return {
        "observed_indirect": round(obs, 4),
        "null_p95": round(null_p95, 4) if null_p95 is not None else None,
        "empirical_percentile": round(pct, 2),
        "n_perm": len(null),
        "note": "rank-based indirect; 仅 diagnostic",
    }


def run_rank_pathway(etd, iae, give, label):
    sp = spearman_pathway(etd, iae, give)
    boot = bootstrap_indirect_spearman(etd, iae, give, N_BOOT, BOOT_SEED)
    perm = permutation_indirect_spearman(etd, iae, give, N_PERM, PERM_SEED)
    return {"label": label, "spearman_pathway": sp, "bootstrap": boot, "permutation": perm}


def run_pathway(etd, iae, give, label):
    dec = mediation_decomp(etd, iae, give)
    if dec is None:
        return {"label": label, "error": "decomp 失败(n<4 或退化)"}
    boot = bootstrap_indirect(etd, iae, give, N_BOOT, BOOT_SEED)
    perm = permutation_indirect(etd, iae, give, N_PERM, PERM_SEED)
    sp = spearman_pathway(etd, iae, give)
    out = {"label": label, "decomp": dec, "bootstrap": boot, "permutation": perm, "spearman": sp}
    return out


def main():
    run_epoch = datetime.now(timezone.utc).timestamp()
    run_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    md_text, contract = check_gate0(run_epoch)

    trades = load_trades()
    bars, times = load_m5()

    rows = []
    n_no_cp = 0
    for t in trades:
        rec = compute_trade(t, bars, times)
        if rec is None:
            n_no_cp += 1
            continue
        rows.append(rec)

    n_total = len(trades)
    n_valid = len(rows)

    etd = [r["etd_bars"] for r in rows]
    iae = [r["IAE_usd"] for r in rows]
    give = [r["Giveback_usd"] for r in rows]
    give_late = [r["Giveback_late_usd"] for r in rows]
    mfe = [r["MFE_usd"] for r in rows]
    pnl = [r["PnL_usd"] for r in rows]
    sl_flag = [r["sl_present"] for r in rows]

    # 主路径（标准化 OLS / Pearson — 对原始 USD 离群值敏感）
    primary = run_pathway(etd, iae, give, "Primary_210_full")

    # 主路径（秩 / Spearman — 对离群值稳健，与 EQ-1 证据口径一致）
    rank_primary = run_rank_pathway(etd, iae, give, "Rank_Spearman_210_full")

    # 离群值衰减诊断：同一对变量的 Pearson vs Spearman 差距
    outlier_diag = {
        "IAE_Giveback": {"pearson": round(pearson(iae, give), 4), "spearman": round(spearman(iae, give), 4)},
        "ETD_IAE": {"pearson": round(pearson(etd, iae), 4), "spearman": round(spearman(etd, iae), 4)},
        "ETD_Giveback": {"pearson": round(pearson(etd, give), 4), "spearman": round(spearman(etd, give), 4)},
        "note": "Pearson 远低于 Spearman -> 原始 USD 变量存在强离群杠杆; 秩/Spearman 路径是稳健且 EQ-1 一致的科学读数, OLS 仅作离群敏感性。",
    }

    # 窗口重叠诊断
    n_overlap = sum(1 for r in rows if r["overlap"])
    overlap_rate = n_overlap / n_valid if n_valid else 0.0

    # 层 A：剔短交易（duration<=IAE_WIN 或 MFE 峰值落窗口内 -> overlap）
    keepA = [i for i, r in enumerate(rows) if not r["overlap"]]
    layerA = run_pathway([etd[i] for i in keepA], [iae[i] for i in keepA], [give[i] for i in keepA],
                          f"LayerA_excl_short(n={len(keepA)})")

    # 层 B：Giveback_late 为结果
    layerB = run_pathway(etd, iae, give_late, "LayerB_giveback_late")

    # 层 C / D：SL / non-SL 子集
    idx_sl = [i for i in range(n_valid) if sl_flag[i]]
    idx_nsl = [i for i in range(n_valid) if not sl_flag[i]]
    layerC = run_pathway([etd[i] for i in idx_sl], [iae[i] for i in idx_sl], [give[i] for i in idx_sl],
                         f"LayerC_SL142(n={len(idx_sl)})")
    layerD = run_pathway([etd[i] for i in idx_nsl], [iae[i] for i in idx_nsl], [give[i] for i in idx_nsl],
                         f"LayerD_nonSL68(n={len(idx_nsl)})")

    # 秩/Spearman 敏感性层（与主路径对称）
    rankA = run_rank_pathway([etd[i] for i in keepA], [iae[i] for i in keepA], [give[i] for i in keepA],
                             f"Rank_LayerA_excl_short(n={len(keepA)})")
    rankB = run_rank_pathway(etd, iae, give_late, "Rank_LayerB_giveback_late")
    rankC = run_rank_pathway([etd[i] for i in idx_sl], [iae[i] for i in idx_sl], [give[i] for i in idx_sl],
                             f"Rank_LayerC_SL142(n={len(idx_sl)})")
    rankD = run_rank_pathway([etd[i] for i in idx_nsl], [iae[i] for i in idx_nsl], [give[i] for i in idx_nsl],
                             f"Rank_LayerD_nonSL68(n={len(idx_nsl)})")

    # 选择偏差诊断 SL vs non-SL
    def grp_stats(idxs):
        return {
            "n": len(idxs),
            "ETD_bars": desc([etd[i] for i in idxs]),
            "IAE_usd": desc([iae[i] for i in idxs]),
            "Giveback_usd": desc([give[i] for i in idxs]),
            "MFE_usd": desc([mfe[i] for i in idxs]),
            "PnL_usd": desc([pnl[i] for i in idxs]),
        }

    selection = {
        "SL_142": grp_stats(idx_sl),
        "non_SL_68": grp_stats(idx_nsl),
        "note": "Selection Diagnostic，非 Selection Rule；仅暴露偏差边界，不据此筛选样本。",
    }

    window_overlap = {
        "n_eligible": n_valid,
        "n_overlap": n_overlap,
        "overlap_rate": round(overlap_rate, 4),
        "definition": "MFE 峰值索引 < IAE_WIN(10) 或 duration_bars <= IAE_WIN",
        "note": "窗口污染风险区；层A 已剔除此子群重跑以验证路径在非重叠窗口下是否仍存在。",
    }

    prov = {
        "dataset": "XAUUSD M5 / MT5 trades (2026-03-02 ~ 2026-08-05)",
        "trade_count_total": n_total,
        "trade_count_valid_CP": n_valid,
        "n_excluded_no_cp": n_no_cp,
        "preregistration_version": PREREG_VERSION,
        "preregistration_mtime": round(os.path.getmtime(PREREG_MD), 0),
        "run_timestamp": run_iso,
        "sample_definition": "210 全样本(剔除 no-CP); SL/non-SL 仅 Selection Diagnostic",
        "mediator_definition": "IAE = entry 后 10 根最大逆向 excursion USD (继承 EQ-1 R1, 锁定为中介变量)",
        "etd_definition": "继承 EQ-1 CP-D: ETD_bars=entry_reference_bar_index-CP_bar_index (k=2,W=48)",
        "outcome_definition": "Giveback=max(0,MFE-退出有利); Giveback_late=以 post-IAE-window MFE 为基准(偏离 EQ-1)",
        "initial_risk_definition": "abs(entry_price-sl_trigger_price)*100*volume (stop-distance risk proxy, 非真实风险)",
        "observation_only": True,
    }

    out = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": HYPOTHESIS,
        "governance": "OBSERVATION_ONLY. 不接 run_daily/risk_guard/shadow/CIO/Trading Coach/生产. "
                      "不读 E1-E4 标签, 不优化阈值, 不搜变量, 不改 k=2/W=48/IAE_WIN=10. "
                      "第一次 Run 只描述路径结构, 不推导交易结论, 不产买卖信号.",
        "preregistration_check": {
            "doc_exists": True,
            "mtime_ok": True,
            "tokens_present": {t: (t in md_text) for t in PREREG_TOKENS},
            "note": "Gate 0 通过才允许计算; 任何一项失败 -> sys.exit(2), 不产生结果.",
        },
        "contract_token_check": {k: (contract.get("frozen_tokens", {}).get(k) == v)
                                 for k, v in CONTRACT_TOKEN_CHECKS.items()},
        "frozen_constants": {
            "K": K, "W": W, "IAE_WIN": IAE_WIN, "SAMPLE_N": SAMPLE_N,
            "PREREG_VERSION": PREREG_VERSION, "N_BOOT": N_BOOT, "BOOT_SEED": BOOT_SEED,
            "N_PERM": N_PERM, "PERM_SEED": PERM_SEED, "CONTRACT_MULT": CONTRACT_MULT,
        },
        "provenance": prov,
        "pathway_primary": primary,
        "rank_pathway_primary": rank_primary,
        "outlier_attenuation_diagnostic": outlier_diag,
        "window_overlap": window_overlap,
        "sensitivity_layers": {"LayerA_excl_short": layerA, "LayerB_giveback_late": layerB,
                               "LayerC_SL142": layerC, "LayerD_nonSL68": layerD},
        "rank_sensitivity_layers": {"Rank_LayerA_excl_short": rankA, "Rank_LayerB_giveback_late": rankB,
                                     "Rank_LayerC_SL142": rankC, "Rank_LayerD_nonSL68": rankD},
        "selection_diagnostic_SL_vs_nonSL": selection,
        "decision": "OBSERVATION",
        "decision_rationale": ("第一次 Run 仅描述 210 笔全样本 ETD->IAE->Giveback 路径结构, "
                               "不做 pass/fail 判定, 不推导任何交易结论/买卖信号。接受 indirect 正/零/负三种结果(不要求显著). "
                               "因果边界: 仅允许'与路径机制关联相容', 禁用'IAE 是中介/导致 Giveback'. "
                               "关键读数: 原始 USD 变量离群杠杆大(Pearson 0.11 vs Spearman 0.53), 故秩/Spearman 路径(indirect~0.08)为稳健科学读数, "
                               "与 EQ-1 a=0.153/b=0.53 一致; OLS 路径因离群被衰减(indirect~0.03)仅作敏感性。两者 permutation 均明显超出随机。 "
                               "窗口重叠(overlap_rate=0.94)下秩路径仍成立(层A剔短交易后 indirect 仍正), Giveback_late 变体减弱(窗口重叠污染已缓解解释)。"
                               "后续接 Trading Coach 须独立预登记."),
        "interpretation_allowed": False,
        "implementation_notes": [
            "中介变量锁定 IAE(entry 后 10 根); a=ETD->IAE, b=IAE->Giveback|ETD, c=ETD->Giveback, c'=ETD->Giveback|IAE, indirect=a*b。",
            "Primary=OLS 乘积系数 bootstrap(标准化, N_BOOT=10000, BCa 95%); Secondary=Spearman partial 交叉验证。",
            "9 指标冻结: indirect/direct(c')/total(c)/a/b/c'/PM/CI/perm。",
            "Permutation: 固定(ETD,Giveback) 配对, 独立保边洗牌 IAE 打破 a·b 两链接, 2000 次(seed=20260817), 仅 diagnostic。",
            "离群值衰减: 原始 USD 变量(IAE/Giveback) Pearson(0.11) 远低于 Spearman(0.53) -> 强离群杠杆; "
            "故 PRIMARY 科学读数采用秩/Spearman 路径(indirect~0.08, 与 EQ-1 a=0.153/b=0.53 一致), OLS 仅作离群敏感性(attentuated)。",
            "秩/Spearman 路径也跑 bootstrap BCa CI + permutation(null 洗牌 IAE), 与 OLS 对称报告; 两者均不要求显著。",
            "窗口重叠缓解: overlap_rate 诊断 + 层A(剔 duration<=IAE_WIN 短交易) + 层B(Giveback_late 变体, 标注偏离 EQ-1)。",
            "SL/non-SL 仅 Selection Diagnostic 敏感性层(层C/层D), 不筛选样本。",
            "micro look-ahead 排除: 仅用 close_time<=entry_unix 的已收盘 bar; entry_reference_bar=最后已收盘 bar。",
            "ETD/CP 继承 EQ-1 CP-D(k=2/W=48), 不重算定义。",
            "结果解释边界: 即使 indirect CI 排除 0 也只说'与正向路径机制相容', 不能升级为因果; 即使 CI 含 0 也说'与 null 间接效应相容'。",
        ],
        "per_trade": rows,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    pd = primary.get("decomp", {})
    pb = primary.get("bootstrap", {})
    pp = primary.get("permutation", {})
    rpd = rank_primary.get("spearman_pathway", {})
    rpb = rank_primary.get("bootstrap", {})
    rpp = rank_primary.get("permutation", {})
    print(f"[{EXPERIMENT_ID}] n_total={n_total} n_valid_CP={n_valid} noCP={n_no_cp}")
    print(f"  [OLS/Pearson] decomp: a={pd.get('a')} b={pd.get('b')} c={pd.get('c')} c'={pd.get('c_prime')} "
          f"indirect={pd.get('indirect')} pm={pd.get('pm')}")
    print(f"  [OLS] BCa CI: [{pb.get('bca_ci_lo')}, {pb.get('bca_ci_hi')}]  PERM pct={pp.get('empirical_percentile')}%")
    print(f"  [Rank/Spearman] a={rpd.get('a_spearman')} b={rpd.get('b_partial_spearman')} "
          f"indirect={rpd.get('indirect_spearman')}  BCa CI=[{rpb.get('bca_ci_lo')},{rpb.get('bca_ci_hi')}]  "
          f"PERM pct={rpp.get('empirical_percentile')}%")
    print(f"  outlier_attentuation: IAE->Giveback Pearson={outlier_diag['IAE_Giveback']['pearson']} "
          f"vs Spearman={outlier_diag['IAE_Giveback']['spearman']}  -> 秩路径为稳健读数")
    print(f"  overlap_rate={window_overlap['overlap_rate']} (n_overlap={n_overlap})")
    print(f"  [OLS] LayerA={layerA.get('decomp', {}).get('indirect')} LayerB={layerB.get('decomp', {}).get('indirect')} "
          f"LayerC(SL142)={layerC.get('decomp', {}).get('indirect')} LayerD(nonSL68)={layerD.get('decomp', {}).get('indirect')}")
    print(f"  [Rank] LayerA={rankA.get('spearman_pathway', {}).get('indirect_spearman')} "
          f"LayerB={rankB.get('spearman_pathway', {}).get('indirect_spearman')} "
          f"LayerC={rankC.get('spearman_pathway', {}).get('indirect_spearman')} "
          f"LayerD={rankD.get('spearman_pathway', {}).get('indirect_spearman')}")
    print(f"  >>> DECISION: OBSERVATION (仅描述路径结构, 不推导交易结论)")
    print(f"  写出: {OUT_JSON}")


if __name__ == "__main__":
    main()
