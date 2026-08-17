# -*- coding: utf-8 -*-
"""
Exit Engine Observation H2-A  --  Entry Archetype Identifiability (Pre-Registered Test)
=======================================================================================

研究契约：docs/H2A_PreRegistration_v0.1.md + backend/output/research_contracts/RC-H2A-PREREG-v0.1.json
状态：PRE-REGISTRATION FROZEN -> IMPLEMENTATION（本脚本只写、未运行；首次运行受预登记完整性 Gate 约束）

设计铁律（来自用户架构约束，禁止违反）：
1. 只读三份源：trade_path.json（210 笔交易）、entry_timing_report.json（E2 post-trade 标签）、
   XAUUSD_M5.csv（M5 K 线）。Archetype 仅由 entry_time 之前已完整结束的信息生成。
2. **方向性镜像**：A/B/C 原定义偏向「向上突破」语义。XAUUSD 含多空，故先定 direction，
   对 Long/Short 使用镜像规则（突破=破前高/破前低；回踩=守住/压住；扩张=近当根高/近当根低）。
   不新增变量，不改变预登记规则，仅让原规则对双向交易具对称含义。
3. **entry bar micro look-ahead 排除**：所有 feature 只用 `time < entry_unix` 的已收盘 K 线，
   严格 `<`（非 `<=`）。正在形成的 entry bar 的 high/low/close 一律不参与 Archetype 生成。
4. 不做 trailing 重模拟；不读 MFE/MAE/capture 生成 Archetype；不优化任何阈值；不搜最佳变量；
   不改 H2-A Contract；不进 H2-B / OOS / 生产；不接 run_daily/risk_guard/shadow/CIO/Trading Coach。
5. 主指标 = Lift（唯一）；Fisher/Chi-square 仅辅助，不得改变 Gate。
6. 预登记完整性为本脚本第一道 Gate：首次运行须校验预登记文件存在、mtime < 运行时间、
   版本=v0.1、且全部冻结阈值令牌存在于文档。任何一项不匹配 -> 直接 STOP，不产生结果。
7. 多重比较纪律：必须完整报告 A/B/C/Other 四态，绝不只报告 PASS 的那个。
8. 实现层歧义一律采用最保守、最不易产生 look-ahead 的解释，记入 implementation_notes，
   不反向修改研究假设。

判定（机械）：
   对每个 Archetype in {A,B,C} 计算 5 个硬 Gate：
     A1 方向       Lift > 1
     A2 稳定       Lift_train > 1 AND Lift_validation > 1
     A3 经济       Lift_validation >= 1.25
     N>=20         样本量 >= 20
     非单笔驱动    剔除 E2 贡献最大的单笔后 Lift 不坍塌（subrate > baseline）
   + 负对照特异性：命中的 Archetype 不得在 Y_neg 上同样 Lift >= 1.25（否则仅降置信度，不硬阻塞）
   PASS    = 至少一个 A/B/C 全过 5 硬 Gate 且负对照特异
   PASS_WITH_CAVEAT = 至少过一个但负对照不特异（特异性警告，进 H2-B 前需谨慎）
   FAIL    = 无 Archetype 过 5 硬 Gate -> 终止 E2-conditioned Exit 路线
"""

import os
import sys
import json
import csv
import bisect
import math
import random
import statistics
from datetime import datetime, timezone

# ---------- 路径（相对项目根；脚本置于 backend/os_layers/） ----------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MT5 = os.path.join(ROOT, "mt5_raw")
TRADE_PATH = os.path.join(MT5, "trade_path.json")
ENTRY_TIMING = os.path.join(MT5, "entry_timing_report.json")
M5_CSV = os.path.join(MT5, "XAUUSD_M5.csv")
PREREG_MD = os.path.join(ROOT, "docs", "H2A_PreRegistration_v0.1.md")
OUT_DIR = os.path.join(ROOT, "backend", "output", "research_contracts")
OUT_JSON = os.path.join(OUT_DIR, "h2a_observation_v0_1.json")

# ---------- 冻结常量（与预登记文档逐字一致；改动须同步改文档并重新走 Gate） ----------
N_BREAK = 20            # breakout 前视窗口（根）
RETEST_TOL_FRAC = 0.1   # 回踩容差 = 0.1 × 窗口均值振幅
RETEST_WINDOW = 10      # 突破后回踩确认窗口（根）
EXPANSION_Q = 0.75      # entry_expansion 分位阈值
VOL_MULT_HI = 1.1       # ATR 扩张倍数
VOL_MULT_LO = 0.9       # ATR 收缩倍数
ATR_WIN = 50            # ATR 回望窗口（根）
SPLIT_FRAC = 0.70       # Discovery 前 70%
LIFT_THRESHOLD = 1.25   # Validation Lift 经济门槛
MIN_SAMPLE = 20         # 最小样本量
PREREG_VERSION = "v0.1"

# Permutation Null（§7.1，运行前冻结；仅 diagnostic，不新增 Hard Gate）
N_PERM = 2000            # permutation 次数
PERM_SEED = 20260815     # 固定随机种子，保证可复现
PERM_STAT = "max_lift"       # primary statistic: max(Lift_A, Lift_B, Lift_C) — 挑最强 E2 Archetype 的选择过程

EXPERIMENT_ID = "H2A-OBS-v0.1"
HYPOTHESIS = ("H2-A: 在完全冻结的 Pre-Trade Information Set 下, 预定义的机械 Archetype (A/B/C) "
              "能否在未使用结果信息的情况下, 对历史 E2 标签产生稳定区分能力 (Lift)? "
              "这是 identifiability test, 非模型优化.")

# 预登记文档必须包含的令牌（任一缺失即视为预登记被篡改 -> STOP）
PREREG_TOKENS = [
    "H2-A Pre-Registration v0.1",
    "N_break=20",
    "retest_tol=0.1",
    "lookback=10",
    "q=0.75",
    "mult=1.1/0.9",
    "70% / 30%",
    "1.25",
    "N ≥ 20",
    "n_permutations=2000",
    "seed=20260815",
    "max_lift",
    "保留 97/113 边际",
    "仅 diagnostic, 不新增 Hard Gate",
]


# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------
def parse_dt(s):
    # 沿用既有管线约定：trade 时间按 UTC 解析（与 M5 csv 的 Unix time 一致）
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def load_trades():
    with open(TRADE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["trades"]


def load_e2_labels():
    """从 entry_timing_report.json 取 trade_id -> 是否为 E2（仅用标签，绝不读 MFE/MAE/capture）。"""
    with open(ENTRY_TIMING, encoding="utf-8") as f:
        data = json.load(f)
    id2e2 = {}
    for v in data.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and "trade_id" in item and "entry_type" in item:
                    id2e2[str(item["trade_id"])] = (item["entry_type"] == "E2_anticipatory_suffered")
    return id2e2


def load_m5():
    bars = []
    with open(M5_CSV, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            bars.append((int(row["time"]), float(row["high"]), float(row["low"]),
                         float(row["open"]), float(row["close"])))
    bars.sort(key=lambda b: b[0])
    times = [b[0] for b in bars]
    return bars, times


# ----------------------------------------------------------------------------
# Gate 0：预登记完整性（第一道 Gate，任何不匹配直接 STOP）
# ----------------------------------------------------------------------------
def check_preregistration(run_epoch):
    res = {"file": PREREG_MD, "exists": False, "mtime_ok": False,
           "tokens_present": {}, "version": PREREG_VERSION, "run_approved": False}
    if not os.path.exists(PREREG_MD):
        print(f"[PRE-REG GATE] FAIL: 预登记文档不存在: {PREREG_MD}")
        return res
    res["exists"] = True
    mtime = os.path.getmtime(PREREG_MD)
    # 严格：预登记文件修改时间必须早于本次运行时间
    if mtime >= run_epoch:
        print(f"[PRE-REG GATE] FAIL: 预登记 mtime({mtime:.0f}) 不早于运行时间({run_epoch:.0f})")
        return res
    res["mtime_ok"] = True
    with open(PREREG_MD, encoding="utf-8") as f:
        text = f.read()
    missing = [t for t in PREREG_TOKENS if t not in text]
    for t in PREREG_TOKENS:
        res["tokens_present"][t] = (t in text)
    if missing:
        print(f"[PRE-REG GATE] FAIL: 预登记文档缺失冻结令牌: {missing}")
        return res
    if PREREG_VERSION not in text:
        print(f"[PRE-REG GATE] FAIL: 版本标记 {PREREG_VERSION} 未找到")
        return res
    res["run_approved"] = True
    print(f"[PRE-REG GATE] PASS: 文件存在, mtime 早于运行, 版本={PREREG_VERSION}, "
          f"全部冻结令牌齐全 -> 允许计算")
    return res


# ----------------------------------------------------------------------------
# Pre-Trade 特征（仅用 time < entry_unix 的已收盘 K 线）
# ----------------------------------------------------------------------------
def atr_state(prior_bars):
    """vol_state：用 prior_bars 最后 ATR_WIN+1 根计算滚动 ATR(50)，比较当前 TR 与均值。
    窗口不足 -> 'insufficient'（保守：落入 Other）。"""
    if len(prior_bars) < ATR_WIN + 1:
        return "insufficient"
    wb = prior_bars[-(ATR_WIN + 1):]
    trs = []
    for k in range(1, len(wb)):
        h, l, _o, c = wb[k][1], wb[k][2], wb[k][3], wb[k][4]
        cp = wb[k - 1][4]
        trs.append(max(h - l, abs(h - cp), abs(l - cp)))
    atr_avg = sum(trs) / len(trs)
    atr_now = trs[-1]
    if atr_now > VOL_MULT_HI * atr_avg:
        return "expansion"
    if atr_now < VOL_MULT_LO * atr_avg:
        return "contraction"
    return "neutral"


def breakout_pullback(prior_bars, entry_price, direction):
    """返回 (breakout: bool, pullback_confirm: bool)。窗口不足 -> (False, False)。
    Long：突破=entry>前20根最高；回踩=突破后10根内价格回到突破位±0.1*均值振幅并收在突破位之上。
    Short：镜像。"""
    if len(prior_bars) < N_BREAK:
        return False, False
    win = prior_bars[-N_BREAK:]
    range_mean = statistics.mean(max(b[1] - b[2], 1e-9) for b in win)
    tol = RETEST_TOL_FRAC * range_mean
    if direction == "BUY":
        break_level = max(b[1] for b in win)
        if entry_price <= break_level:
            return False, False
        bidx = next(k for k in range(len(win)) if win[k][1] >= break_level)
        # win 是 prior_bars 末尾 N_BREAK 根；bidx 必须换算回 prior_bars 真实索引，
        # 回踩搜索须在「突破 bar 之后」进行，否则会错误地在突破之前找回踩（旧代码 bug）。
        bo_pos = len(prior_bars) - N_BREAK + bidx
        for k in range(bo_pos + 1, min(bo_pos + 1 + RETEST_WINDOW, len(prior_bars))):
            bh, bl, _o, bc = prior_bars[k][1], prior_bars[k][2], prior_bars[k][3], prior_bars[k][4]
            if abs(bl - break_level) <= tol and bc >= break_level:
                return True, True
        return True, False
    else:  # SELL
        break_level = min(b[2] for b in win)
        if entry_price >= break_level:
            return False, False
        bidx = next(k for k in range(len(win)) if win[k][2] <= break_level)
        bo_pos = len(prior_bars) - N_BREAK + bidx
        for k in range(bo_pos + 1, min(bo_pos + 1 + RETEST_WINDOW, len(prior_bars))):
            bh, bl, _o, bc = prior_bars[k][1], prior_bars[k][2], prior_bars[k][3], prior_bars[k][4]
            if abs(bh - break_level) <= tol and bc <= break_level:
                return True, True
        return True, False


def entry_expansion(prior_bars, entry_price, direction):
    """entry 位于上一根已收盘 K 线的激进端（分位 > q）。
    Long：近高位 -> (entry-low)/(high-low) > q；Short：近低位 -> (high-entry)/(high-low) > q。"""
    if not prior_bars:
        return False
    h, l = prior_bars[-1][1], prior_bars[-1][2]
    denom = (h - l) if (h - l) > 1e-9 else 1e-9
    if direction == "BUY":
        pos = (entry_price - l) / denom
    else:
        pos = (h - entry_price) / denom
    return pos > EXPANSION_Q


def assign_archetype(prior_bars, entry_price, direction):
    """按冻结规则分配 A/B/C/Other；窗口不足时保守落入 Other/A。"""
    if len(prior_bars) < N_BREAK:
        # 无法确认突破 -> 视同为「无突破」-> A 候选（保守）
        return "A"
    if len(prior_bars) < 1:
        return "Other"
    breakout, pullback = breakout_pullback(prior_bars, entry_price, direction)
    vol = atr_state(prior_bars)
    expansion = entry_expansion(prior_bars, entry_price, direction)
    if not breakout:
        return "A"
    if pullback:
        return "B"
    if expansion and vol == "expansion":
        return "C"
    return "Other"


# ----------------------------------------------------------------------------
# 统计辅助（辅助证据，pure stdlib；不改变 Gate）
# ----------------------------------------------------------------------------
def fisher_exact_two_sided(a, b, c, d):
    """2x2 表 [[a,b],[c,d]] 双尾 Fisher 精确检验（超几何分布手算，无 scipy 依赖）。"""
    n = a + b + c + d
    if n == 0:
        return None
    row1, col1 = a + b, a + c
    row2 = c + d
    lo = max(0, col1 - row2)
    hi = min(row1, col1)

    def p_of(k):
        if k < lo or k > hi:
            return 0.0
        return math.comb(row1, k) * math.comb(row2, col1 - k) / math.comb(n, col1)

    p_obs = p_of(a)
    if p_obs <= 0:
        return 1.0
    p_val = 0.0
    for k in range(lo, hi + 1):
        pk = p_of(k)
        if pk <= p_obs + 1e-12:
            p_val += pk
    return min(1.0, p_val)


def chi_square_2x2(a, b, c, d):
    """Yates 校正 Pearson 卡方（仅作辅助；有零格则返 None）。"""
    n = a + b + c + d
    if n == 0:
        return None
    if a == 0 or b == 0 or c == 0 or d == 0:
        return None
    row1, row2 = a + b, c + d
    col1, col2 = a + c, b + d
    expected_a = row1 * col1 / n
    expected_b = row1 * col2 / n
    expected_c = row2 * col1 / n
    expected_d = row2 * col2 / n
    num = (abs(a - expected_a) - 0.5) ** 2
    chi = num / expected_a
    chi += (abs(b - expected_b) - 0.5) ** 2 / expected_b
    chi += (abs(c - expected_c) - 0.5) ** 2 / expected_c
    chi += (abs(d - expected_d) - 0.5) ** 2 / expected_d
    return round(chi, 4)


def lift_ci(p1, n1, p0, n0):
    """Lift = p1/p0 的近似 95% CI（Wald on log scale）。p1 在边界或 n1=0 返 None。"""
    if n1 == 0 or p1 <= 0 or p1 >= 1:
        return None
    if n0 == 0 or p0 <= 0 or p0 >= 1:
        return None
    se = math.sqrt((1 - p1) / (n1 * p1) + (1 - p0) / (n0 * p0))
    loglift = math.log(p1 / p0)
    return [round(math.exp(loglift - 1.96 * se), 4), round(math.exp(loglift + 1.96 * se), 4)]


# ----------------------------------------------------------------------------
# Permutation Null（§7.1）：全流程选择偏差诊断（仅 diagnostic，不新增 Hard Gate）
# ----------------------------------------------------------------------------
def compute_archetype_lifts(e2_flags, rows, baseline_rate):
    """给定一套 is_e2 标签，按冻结 Archetype 分配计算 A/B/C 全样本 Lift。
    Archetype 分配（X）固定，仅 e2_flags（Y）变化 -> 与真实分析同口径。"""
    lifts = {}
    for arch in ["A", "B", "C"]:
        sub = [i for i, r in enumerate(rows) if r["archetype"] == arch]
        n = len(sub)
        e2 = sum(1 for i in sub if e2_flags[i])
        rate = e2 / n if n else 0.0
        lifts[arch] = rate / baseline_rate if baseline_rate > 0 else 0.0
    return lifts


def run_permutation_null(rows, real_e2_flags, baseline_rate, rng_seed):
    """固定 Archetype（rows 已生成），仅保边洗牌 E2 标签，复刻 A/B/C 的 max Lift。
    返回 observed / null distribution summary / empirical_percentile。"""
    rng = random.Random(rng_seed)
    observed = compute_archetype_lifts(real_e2_flags, rows, baseline_rate)
    observed_max = max(observed[a] for a in ["A", "B", "C"])

    null_max = []
    base = list(real_e2_flags)
    for _ in range(N_PERM):
        perm = base[:]
        rng.shuffle(perm)  # 保边洗牌：只重排标签，True 个数恒 = 97
        lf = compute_archetype_lifts(perm, rows, baseline_rate)
        null_max.append(max(lf[a] for a in ["A", "B", "C"]))
    null_max.sort()
    mean = sum(null_max) / len(null_max)
    median = null_max[len(null_max) // 2]
    p95 = null_max[min(len(null_max) - 1, int(0.95 * (len(null_max) - 1)))]
    below = sum(1 for x in null_max if x < observed_max)
    pct = 100.0 * below / len(null_max)

    if pct >= 95:
        interp = "observed exceeds permutation null (明显超出随机标签)"
    elif pct >= 90:
        interp = "borderline signal (90%~95%)"
    else:
        interp = "lacks evidence beyond null (<90%)"

    return {
        "n_permutations": N_PERM,
        "seed": rng_seed,
        "statistic": PERM_STAT,
        "fixed": "Archetype assignment fixed; only E2 labels permuted (preserve 97/113 margin)",
        "observed_max_lift": round(observed_max, 4),
        "null_mean": round(mean, 4),
        "null_median": round(median, 4),
        "null_p95": round(p95, 4),
        "empirical_percentile": round(pct, 2),
        "interpretation": interp,
        "note": ("Permutation 仅 diagnostic，不新增 Hard Gate；"
                 "percentile<95 时把 PASS 降级为 PASS_WITH_CAVEAT，绝不复活 FAIL。"),
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    run_epoch = datetime.now(timezone.utc).timestamp()
    run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Gate 0：预登记完整性（最早执行，失败即 STOP） ----
    prereg = check_preregistration(run_epoch)
    if not prereg["run_approved"]:
        print("[STOP] 预登记 Gate 未通过，不产生任何实验结果。")
        sys.exit(2)

    # ---- 载入 ----
    trades = load_trades()
    id2e2 = load_e2_labels()
    bars, times = load_m5()

    # 时间切分（机械：按 entry_time 升序的前 70%）
    idx_sorted = sorted(range(len(trades)),
                        key=lambda i: parse_dt(trades[i]["entry_time"]))
    cut = int(SPLIT_FRAC * len(trades))
    discover_idx = set(idx_sorted[:cut])
    validate_idx = set(idx_sorted[cut:])

    # ---- 逐笔生成 Archetype + 标签 + Y_neg ----
    rows = []
    for i, t in enumerate(trades):
        tid = str(t["trade_id"])
        direction = t["direction"]
        entry_price = float(t["entry_price"])
        entry_unix = parse_dt(t["entry_time"])
        is_e2 = id2e2.get(tid, False)

        # 仅取「已完整收盘」的 K 线：M5 的 time 是 bar 开盘时间，bar 在 time+300s 才收盘；
        # entry 落在某根 bar 区间内时该 bar 仍在形成，其 high/low/close 不可用。
        # 故严格用 close_time = time+300 <= entry_unix，即 bisect_right(times, entry_unix-300)。
        # （实测：210 笔 entry 几乎都落在一根正在形成的 bar 内，旧代码 bisect_left 会把它当已收盘读入 -> micro look-ahead）
        pi = bisect.bisect_right(times, entry_unix - 300)
        prior_bars = [bars[k] for k in range(pi)]

        arch = assign_archetype(prior_bars, entry_price, direction)

        # 负对照 Y_neg：入场后固定 10 根窗口收益率方向（原始涨跌，与方向无关，不涉及 MFE/MAE）
        i_entry = bisect.bisect_right(times, entry_unix)  # 第一根严格晚于 entry 的 bar
        entry_bar_idx = i_entry - 1
        j = entry_bar_idx + 1 + 10
        y_neg_up = None
        if 0 <= entry_bar_idx < len(bars) and j < len(bars):
            ret10 = bars[j][4] - bars[entry_bar_idx][4]
            y_neg_up = (ret10 > 0)

        rows.append({
            "trade_id": tid,
            "direction": direction,
            "entry_time": t["entry_time"],
            "archetype": arch,
            "is_e2": is_e2,
            "split": "discover" if i in discover_idx else "validate",
            "y_neg_up": y_neg_up,
        })

    # ---- baseline ----
    n_total = len(rows)
    e2_total = sum(1 for r in rows if r["is_e2"])
    baseline_rate = e2_total / n_total if n_total else 0.0

    # ---- 每 Archetype 指标 ----
    arches = ["A", "B", "C", "Other"]
    table = {}
    for arch in arches:
        sub = [r for r in rows if r["archetype"] == arch]
        n = len(sub)
        e2 = sum(1 for r in sub if r["is_e2"])
        rate = e2 / n if n else 0.0
        lift = rate / baseline_rate if baseline_rate > 0 else None

        dsub = [r for r in sub if r["split"] == "discover"]
        nd = len(dsub)
        e2d = sum(1 for r in dsub if r["is_e2"])
        rd = e2d / nd if nd else 0.0
        lift_d = rd / baseline_rate if baseline_rate > 0 else None

        vsub = [r for r in sub if r["split"] == "validate"]
        nv = len(vsub)
        e2v = sum(1 for r in vsub if r["is_e2"])
        rv = e2v / nv if nv else 0.0
        lift_v = rv / baseline_rate if baseline_rate > 0 else None

        ci = lift_ci(rate, n, baseline_rate, n_total) if lift is not None else None
        table[arch] = {
            "N": n,
            "E2_count": e2,
            "E2_rate": round(rate, 4),
            "baseline_rate": round(baseline_rate, 4),
            "lift": round(lift, 4) if lift is not None else None,
            "train_N": nd,
            "train_E2_rate": round(rd, 4),
            "train_lift": round(lift_d, 4) if lift_d is not None else None,
            "validation_N": nv,
            "validation_E2_rate": round(rv, 4),
            "validation_lift": round(lift_v, 4) if lift_v is not None else None,
            "lift_ci_95": ci,
        }

    # ---- 统计证据（辅助） ----
    stats_ev = {}
    overall_e2 = e2_total
    overall_none2 = n_total - e2_total
    for arch in arches:
        sub = [r for r in rows if r["archetype"] == arch]
        n = len(sub)
        e2 = sum(1 for r in sub if r["is_e2"])
        a, b = e2, n - e2
        c, d = overall_e2 - e2, overall_none2 - (n - e2)
        fisher_p = fisher_exact_two_sided(a, b, c, d)
        chi2 = chi_square_2x2(a, b, c, d)
        effect = "positive" if (table[arch]["lift"] or 0) > 1 else "negative_or_null"
        stats_ev[arch] = {
            "fisher_p_two_sided": round(fisher_p, 4) if fisher_p is not None else None,
            "chi_square_yates": chi2,
            "effect_direction": effect,
            "ci_95": table[arch]["lift_ci_95"],
        }

    # ---- 负对照 ----
    yneg_up_total = sum(1 for r in rows if r["y_neg_up"] is True)
    yneg_known = sum(1 for r in rows if r["y_neg_up"] is not None)
    yneg_base = yneg_up_total / yneg_known if yneg_known else 0.0
    neg_ctrl = {"y_neg_definition": "入场后固定10根 M5 窗口原始收益率方向(涨=True)，与交易方向无关，不涉及MFE/MAE/capture",
                "baseline_y_neg_up_rate": round(yneg_base, 4)}
    for arch in arches:
        sub = [r for r in rows if r["archetype"] == arch and r["y_neg_up"] is not None]
        n = len(sub)
        up = sum(1 for r in sub if r["y_neg_up"])
        rate = up / n if n else 0.0
        lift = rate / yneg_base if yneg_base > 0 else None
        neg_ctrl[arch] = {
            "y_neg_N": n,
            "y_neg_up_rate": round(rate, 4),
            "y_neg_lift": round(lift, 4) if lift is not None else None,
        }

    # ---- Gate 矩阵 ----
    def robust_single(e2, n):
        if n < 2 or e2 == 0:
            return False
        after = (e2 - 1) / (n - 1)
        return after > baseline_rate

    def neg_specific(arch):
        yl = neg_ctrl[arch]["y_neg_lift"]
        if yl is None:
            return True  # 数据不足，不能证伪特异性
        return yl < LIFT_THRESHOLD

    gate = {}
    for arch in ["A", "B", "C"]:
        t = table[arch]
        a1 = (t["lift"] is not None) and (t["lift"] > 1)
        a2 = (t["train_lift"] is not None and t["train_lift"] > 1 and
              t["validation_lift"] is not None and t["validation_lift"] > 1)
        a3 = (t["validation_lift"] is not None) and (t["validation_lift"] >= LIFT_THRESHOLD)
        nok = t["N"] >= MIN_SAMPLE
        single_ok = robust_single(t["E2_count"], t["N"])
        spec = neg_specific(arch)
        gate[arch] = {
            "A1_direction": a1,
            "A2_stability": a2,
            "A3_economic": a3,
            "N>=20": nok,
            "non_single_trade": single_ok,
            "neg_control_specific": spec,
            "pass_hard_gates": (a1 and a2 and a3 and nok and single_ok),
        }

    # ---- Permutation Null（§7.1，仅 diagnostic） ----
    real_e2_flags = [r["is_e2"] for r in rows]
    perm = run_permutation_null(rows, real_e2_flags, baseline_rate, PERM_SEED)
    perm_weak = perm["empirical_percentile"] < 95

    # ---- 决策（机械） ----
    clean_hits = [a for a in ["A", "B", "C"] if gate[a]["pass_hard_gates"] and gate[a]["neg_control_specific"]]
    caveat_hits = [a for a in ["A", "B", "C"] if gate[a]["pass_hard_gates"] and not gate[a]["neg_control_specific"]]
    if clean_hits:
        decision = "PASS"
        rationale = f"Archetype(s) {clean_hits} 通过全部 5 硬 Gate 且负对照特异 -> 进 H2-B。"
        if perm_weak:
            decision = "PASS_WITH_CAVEAT"
            rationale += (f" 但 Permutation null 显示最大 Lift 未明显超出随机标签"
                          f"（empirical_percentile={perm['empirical_percentile']}%<95%）"
                          f"-> 选择偏差警告，进 H2-B 前需谨慎。")
    elif caveat_hits:
        decision = "PASS_WITH_CAVEAT"
        rationale = (f"Archetype(s) {caveat_hits} 通过 5 硬 Gate，但负对照不特异"
                     f"（同样强预测无关标签 Y_neg）-> 进 H2-B 前需谨慎，特异性待释。"
                     f" Permutation: empirical_percentile={perm['empirical_percentile']}%.")
    else:
        decision = "FAIL"
        rationale = "无 Archetype 通过 5 硬 Gate -> 终止 E2-conditioned Exit 路线；E2 记为纯 post-trade artifact。"

    # ---- provenance ----
    entry_times = [parse_dt(t["entry_time"]) for t in trades]
    prov = {
        "dataset": "XAUUSD M5 / MT5 210 trades (2026-03-02 ~ 2026-08-05)",
        "trade_count": n_total,
        "entry_time_range": {
            "start": datetime.fromtimestamp(min(entry_times), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": datetime.fromtimestamp(max(entry_times), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "preregistration_version": PREREG_VERSION,
        "preregistration_mtime": round(os.path.getmtime(PREREG_MD), 0),
        "run_timestamp": run_iso,
        "feature_timestamp_policy": "feature_timestamp < entry_timestamp (strict; 正形成的 entry bar 不参与 Archetype)",
    }

    out = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": HYPOTHESIS,
        "governance": "Observation-only. 不接 run_daily/risk_guard/shadow/CIO/Trading Coach/生产. "
                      "不重模拟 trailing, 不读 MFE/MAE/capture, 不优化阈值, 不搜变量, 不改 Contract, 不进 H2-B/OOS.",
        "preregistration_check": {
            "exists": prereg["exists"],
            "mtime_ok": prereg["mtime_ok"],
            "run_approved": prereg["run_approved"],
            "tokens_present": prereg["tokens_present"],
            "note": "Gate 0 通过才允许计算; 任何一项失败 -> sys.exit(2), 不产生结果.",
        },
        "frozen_constants": {
            "N_break": N_BREAK, "RETEST_TOL_FRAC": RETEST_TOL_FRAC, "RETEST_WINDOW": RETEST_WINDOW,
            "EXPANSION_Q": EXPANSION_Q, "VOL_MULT_HI": VOL_MULT_HI, "VOL_MULT_LO": VOL_MULT_LO,
            "ATR_WIN": ATR_WIN, "SPLIT_FRAC": SPLIT_FRAC, "LIFT_THRESHOLD": LIFT_THRESHOLD,
            "MIN_SAMPLE": MIN_SAMPLE, "PREREG_VERSION": PREREG_VERSION,
            "N_PERM": N_PERM, "PERM_SEED": PERM_SEED, "PERM_STAT": PERM_STAT,
        },
        "provenance": prov,
        "baseline_e2_rate": round(baseline_rate, 4),
        "baseline_e2_count": e2_total,
        "archetype_table": table,
        "statistical_evidence": stats_ev,
        "negative_control": neg_ctrl,
        "permutation_null": perm,
        "gate_matrix": gate,
        "decision": decision,
        "decision_rationale": rationale,
        "decision_note": "PASS != 进入生产, 仅意味可进 H2-B(条件化 Exit 增量检验). "
                         "FAIL -> 终止 E2 路线. p-value 仅辅助, 不改变 Gate.",
        "implementation_notes": [
            "方向性镜像：Long/Short 使用镜像的突破/回踩/扩张判据，使原规则对双向交易对称。",
            "micro look-ahead 排除：M5 的 time 为 bar 开盘时间，bar 在 time+300s 才收盘；"
            "只用 close_time=time+300 <= entry_unix 的已完全收盘 K 线，正在形成的 entry bar 一律排除（修复初版的 window 内已收盘误判）。",
            "breakout 窗口 = entry 之前紧邻的 20 根已收盘 K 线；窗口不足 20 根 -> 视为无突破 -> 保守归入 A。",
            "vol_state 需至少 51 根历史 K 线（ATR_WIN+1）；不足 -> 'insufficient' -> 落入 Other。",
            "retest_tol 基值 = 20 根窗口的均值振幅（与 ATR 窗口解耦，避免互相依赖）。",
            "Y_neg 使用 entry bar 之后第 10 根收盘相对 entry bar 收盘的原始涨跌，与交易方向无关。",
            "Lift 分母统一为全局基线 E2 率；train/validation Lift 为各时间子集 E2 率 / 全局基线。",
            "多重比较：A/B/C/Other 四态完整报告，绝不只展示 PASS 的那个。",
            "Permutation Null (§7.1)：固定 Archetype 分配，仅保边洗牌 E2 标签(97/113 边际)，"
            f"2000 次(种子 {PERM_SEED})复刻 A/B/C 全样本 Lift；primary statistic = max_lift = "
            "max over A/B/C of full-sample Lift（把多重比较选择过程包进 null）；仅 diagnostic，"
            "percentile<95 时把 PASS 降级 PASS_WITH_CAVEAT，绝不复活 FAIL。",
        ],
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print(f"[{EXPERIMENT_ID}] baseline E2 = {e2_total}/{n_total} = {baseline_rate:.4f}")
    for arch in arches:
        t = table[arch]
        print(f"  {arch}: N={t['N']:>3} E2={t['E2_count']:>3} rate={t['E2_rate']:.3f} "
              f"Lift={t['lift']} trainL={t['train_lift']} valL={t['validation_lift']} "
              f"ynegL={neg_ctrl[arch]['y_neg_lift']}")
    print(f"  GATE: " + " | ".join(f"{a}:{'Y' if gate[a]['pass_hard_gates'] else 'N'}"
                                   f"(spec={'Y' if gate[a]['neg_control_specific'] else 'N'})"
                                   for a in ['A', 'B', 'C']))
    print(f"  PERM: observed_max_lift={perm['observed_max_lift']} null_p95={perm['null_p95']} "
          f"pct={perm['empirical_percentile']}% ({perm['interpretation']})")
    print(f"  >>> DECISION: {decision} -- {rationale}")
    print(f"  写出: {OUT_JSON}")


if __name__ == "__main__":
    main()
