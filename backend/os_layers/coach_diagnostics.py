# -*- coding: utf-8 -*-
"""
Trading Coach Diagnostic Engine v0.1
====================================

状态：OBSERVATION / DESIGN（测量态，非统计研究、非分类器、非规则）

定位
----
EQ 系列（EQ-1 / EQ-1R / EQ-1M）已收口为 OBSERVATION。本引擎是
**Research -> Diagnostic 单向翻译的最终落地代码**：只读 EQ-1M 既有运行结果，
把已验证的研究变量稳定地测量到每一笔交易上。

它**只测量，不分类、不解释、不决策**。

防火墙（铁律）
------------
- 仅消费 EQ 系列的"已验证观察（方向+量级）"；不重算任何 EQ 统计。
- 不回写任何研究冻结参数（k=2 / W=48 / IAE_WIN=10 / seed / N_BOOT / N_PERM / 路径定义）。
- 不接入生产（run_daily / risk_guard / shadow）。
- 严禁：分类 / cutoff / 新统计 / 规则 / 解释性结论 / 生产链。
- diagnostic_label 恒为 null；所有 percentile 仅为样本内描述性排名，无决策含义。

v0.1 只做 5 件事（见 Spec Review §4）：
  1. 读 eq1m_observation_v0_1.json 的 per_trade（不重算 EQ）
  2. 每笔生成四维原始诊断（etd_bars / iae_usd / mfe_usd / giveback_usd / capture_efficiency）
  3. 生成诊断事实（仅报告数值）
  4. 结构化 Diagnosis（事实型：符号检查布尔 + 事实比率 + 中性陈述）
  5. Trading DNA（仅分布 / 描述：median / P25 / P75 / exit_reason 分布）

D4 数学边界（必锁，见 Spec Review §5）：
  capture_efficiency = (MFE - Giveback) / MFE
  if MFE <= 0: capture_efficiency = None   # 避免 0/0 与极小 MFE 极端值
  保留三原始字段 MFE_usd / Giveback_usd / capture_efficiency，不折叠。
"""

import json
import math
import os
import statistics
import sys

ENGINE_VERSION = "v0.1"

# 默认路径（相对仓库根；脚本从任意 cwd 调用时自动解析）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_INPUT = os.path.join(
    _ROOT, "backend", "output", "research_contracts", "eq1m_observation_v0_1.json"
)
DEFAULT_OUTPUT = os.path.join(
    _ROOT, "backend", "output", "coach_diagnostics_v0_1.json"
)


# ---------------------------------------------------------------------------
# 纯描述性统计工具（无假设检验、无采样、无优化）
# ---------------------------------------------------------------------------
def _rank_pct(value, sample):
    """样本内描述性百分位：sample 中 <= value 的比例 * 100。仅描述分布位置。"""
    if value is None or not sample:
        return None
    le = sum(1 for x in sample if x <= value)
    return round(le / len(sample) * 100.0, 1)


def _interp_percentile(arr, p):
    """线性插值百分位（与 numpy 默认方法一致），用于 DNA 描述统计。"""
    if not arr:
        return None
    if len(arr) == 1:
        return arr[0]
    s = sorted(arr)
    k = (len(s) - 1) * (p / 100.0)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def _dist_stats(arr):
    """返回 median / p25 / p75；arr 为空返回 None。"""
    if not arr:
        return None
    return {
        "median": round(statistics.median(arr), 4),
        "p25": round(_interp_percentile(arr, 25), 4),
        "p75": round(_interp_percentile(arr, 75), 4),
        "n_valid": len(arr),
    }


# ---------------------------------------------------------------------------
# D4 数学边界（必锁）
# ---------------------------------------------------------------------------
def capture_efficiency(mfe_usd, giveback_usd):
    """Capture Efficiency = (MFE - Giveback) / MFE；MFE <= 0 时无定义 -> None。"""
    if mfe_usd is None or mfe_usd <= 0:
        return None
    return (mfe_usd - (giveback_usd or 0.0)) / mfe_usd


# ---------------------------------------------------------------------------
# 单笔诊断（测量态）
# ---------------------------------------------------------------------------
def diagnose_trade(t, idx, pools):
    etd = t.get("etd_bars")
    iae = t.get("IAE_usd")
    mfe = t.get("MFE_usd")
    give = t.get("Giveback_usd")
    cap = capture_efficiency(mfe, give)

    # 事实型布尔：仅符号检查（sign-check），不含任何 cutoff
    opportunity_available = (mfe is not None and mfe > 0)
    giveback_occurred = (give is not None and give > 0)
    ratio = None
    if cap is not None and mfe not in (None, 0):
        ratio = give / mfe if mfe != 0 else None

    # 中性陈述串（不出现"应该/太早/太晚"等解释）
    fact_strings = []
    if etd is not None:
        fact_strings.append("ETD = %s bars" % _fmt_num(etd))
    if iae is not None:
        fact_strings.append("IAE = $%s" % _fmt_money(iae))
    if mfe is not None:
        note = " (opportunity available)" if opportunity_available else " (no favorable excursion)"
        fact_strings.append("MFE = $%s%s" % (_fmt_money(mfe), note))
    if give is not None:
        fact_strings.append("Giveback = $%s" % _fmt_money(give))
    if cap is not None:
        fact_strings.append("Capture Efficiency = %.1f%%" % (cap * 100.0))
        if ratio is not None:
            fact_strings.append("Giveback/MFE = %.1f%%" % (ratio * 100.0))
    else:
        fact_strings.append("Capture Efficiency = null (MFE<=0)")

    return {
        "trade_index": idx,
        "source_trade_id": t.get("trade_id"),
        "direction": t.get("direction"),
        "timing": {
            "etd_bars": etd,
            "etd_percentile": _rank_pct(etd, pools["etd_bars"]),
        },
        "exposure": {
            "iae_usd": iae,
            "iae_percentile": _rank_pct(iae, pools["iae_usd"]),
        },
        "opportunity": {
            "mfe_usd": mfe,
            "mfe_percentile": _rank_pct(mfe, pools["mfe_usd"]),
        },
        "profit_capture": {
            "giveback_usd": give,
            "giveback_percentile": _rank_pct(give, pools["giveback_usd"]),
            "capture_efficiency": (round(cap, 4) if cap is not None else None),
            "capture_percentile": _rank_pct(cap, pools["capture_efficiency"]),
        },
        "diagnostic_label": None,  # v0.1 不分类
        "diagnostic_facts": {
            "opportunity_available": opportunity_available,
            "giveback_occurred": giveback_occurred,
            "giveback_to_mfe_ratio": (round(ratio, 4) if ratio is not None else None),
        },
        "diagnostic_fact_strings": fact_strings,
        "context": {
            "pnl_usd": t.get("PnL_usd"),
            "exit_reason": t.get("exit_reason"),
            "sl_present": t.get("sl_present"),
        },
    }


def _fmt_num(x):
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return ("%g" % x)


def _fmt_money(x):
    return ("%.2f" % x)


# ---------------------------------------------------------------------------
# Trading DNA（仅分布 / 描述）
# ---------------------------------------------------------------------------
def build_dna(per_trade):
    etd = [t.get("etd_bars") for t in per_trade if t.get("etd_bars") is not None]
    iae = [t.get("IAE_usd") for t in per_trade if t.get("IAE_usd") is not None]
    mfe = [t.get("MFE_usd") for t in per_trade if t.get("MFE_usd") is not None]
    give = [t.get("Giveback_usd") for t in per_trade if t.get("Giveback_usd") is not None]
    cap = [
        capture_efficiency(t.get("MFE_usd"), t.get("Giveback_usd"))
        for t in per_trade
        if capture_efficiency(t.get("MFE_usd"), t.get("Giveback_usd")) is not None
    ]

    exit_dist = {}
    for t in per_trade:
        r = t.get("exit_reason")
        if r is None:
            r = "unknown"
        exit_dist[r] = exit_dist.get(r, 0) + 1

    dir_dist = {}
    for t in per_trade:
        d = t.get("direction")
        if d is None:
            d = "unknown"
        dir_dist[d] = dir_dist.get(d, 0) + 1

    return {
        "n": len(per_trade),
        "distributions": {
            "etd_bars": _dist_stats(etd),
            "iae_usd": _dist_stats(iae),
            "mfe_usd": _dist_stats(mfe),
            "giveback_usd": _dist_stats(give),
            "capture_efficiency": _dist_stats(cap),
        },
        "exit_reason_distribution": exit_dist,
        "direction_distribution": dir_dist,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main(input_path=DEFAULT_INPUT, output_path=DEFAULT_OUTPUT):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    per_trade = data.get("per_trade") or data.get("per_trade_data") or []
    if not per_trade:
        print("[ERROR] per_trade 为空或缺失: %s" % input_path, file=sys.stderr)
        return 1

    # 构建百分位池（仅非 None 值）
    pools = {
        "etd_bars": [t.get("etd_bars") for t in per_trade if t.get("etd_bars") is not None],
        "iae_usd": [t.get("IAE_usd") for t in per_trade if t.get("IAE_usd") is not None],
        "mfe_usd": [t.get("MFE_usd") for t in per_trade if t.get("MFE_usd") is not None],
        "giveback_usd": [t.get("Giveback_usd") for t in per_trade if t.get("Giveback_usd") is not None],
        "capture_efficiency": [
            c for c in (
                capture_efficiency(t.get("MFE_usd"), t.get("Giveback_usd"))
                for t in per_trade
            ) if c is not None
        ],
    }

    diagnostics = [diagnose_trade(t, i + 1, pools) for i, t in enumerate(per_trade)]
    dna = build_dna(per_trade)

    # ---- D4 边界自检 ----
    n_mfe_le0 = sum(1 for t in per_trade if (t.get("MFE_usd") or 0) <= 0)
    n_cap_null = sum(1 for d in diagnostics if d["profit_capture"]["capture_efficiency"] is None)
    n_label_nonnull = sum(1 for d in diagnostics if d["diagnostic_label"] is not None)
    n_cutoff = 0  # v0.1 不存在任何 cutoff 逻辑

    result = {
        "engine": "Trading Coach Diagnostic Engine",
        "version": ENGINE_VERSION,
        "status": "OBSERVATION",
        "design": "measurement_only (no classification / no cutoff / no rule)",
        "source": os.path.relpath(input_path, _ROOT),
        "n_trades": len(diagnostics),
        "per_trade": diagnostics,
        "trading_dna": dna,
        "self_check": {
            "n_mfe_le0": n_mfe_le0,
            "n_capture_efficiency_null": n_cap_null,
            "n_diagnostic_label_nonnull": n_label_nonnull,
            "n_cutoff_rules": n_cutoff,
            "d4_boundary_ok": (n_mfe_le0 == n_cap_null),
            "no_classification": (n_label_nonnull == 0),
        },
    }

    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ---- 控制台 DNA 摘要（仅描述） ----
    print("=== Trading Coach Diagnostic Engine %s — DNA (descriptive only) ===" % ENGINE_VERSION)
    print("N trades               : %d" % dna["n"])
    for k, st in dna["distributions"].items():
        if st:
            print("  %-18s median=%s  P25=%s  P75=%s  (n=%d)"
                  % (k, st["median"], st["p25"], st["p75"], st["n_valid"]))
        else:
            print("  %-18s (no valid data)" % k)
    print("exit_reason_dist       : %s" % dna["exit_reason_distribution"])
    print("direction_dist         : %s" % dna["direction_distribution"])
    print("--- self-check ---")
    print("  MFE<=0 trades        : %d" % n_mfe_le0)
    print("  capture_eff null      : %d  (== MFE<=0: %s)" % (n_cap_null, n_mfe_le0 == n_cap_null))
    print("  diagnostic_label!=null: %d  (must be 0)" % n_label_nonnull)
    print("  cutoff rules          : %d  (must be 0)" % n_cutoff)
    print("  D4 boundary ok        : %s" % (n_mfe_le0 == n_cap_null))
    print("  no classification     : %s" % (n_label_nonnull == 0))
    print("OUTPUT -> %s" % output_path)
    return 0


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT
    sys.exit(main(inp, out))
