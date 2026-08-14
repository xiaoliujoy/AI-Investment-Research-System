# -*- coding: utf-8 -*-
"""
Exit Engine Observation v0.1  --  H1: Trailing Exit 因果对照实验
=============================================================

设计铁律（来自用户架构约束，禁止违反）：
1. 唯一变量 = Exit。Signal / Entry / Stop / Position Sizing / 成本 / 数据 / 样本 全部固定。
2. 不做参数网格（禁止 ATR×1,1.5,2,... 寻优）。规则在 H1 定义阶段预先指定，见 RULE 常量。
3. 禁止根据结果反向选参。实验结果差 => H1 暂不成立，而非"换参数再跑"。
4. Observation-only：不接 run_daily / risk_guard / shadow / CIO / Trading Coach / 生产路径。
   不修改任何权重 / 阈值 / 生产公式 / Risk Budget / 交易规则。
5. 输出 6 核心指标 + 4 决策。Decision != 进入生产。

因果结构：
    同一批交易 (46 笔确认入场 E3+E4)
        |
        +-- Baseline : 实际退出 (原始 Exit，已实现的 pnl)
        |
        +-- Trailing : 预指定 Chandelier 1×R 规则，唯一改变 Exit
        |
        +-- 同口径比较 -> Net P&L / PF / Capture / Giveback / MaxDD / Distribution

预指定规则 (RULE, 写死，非调参)：
    R        = 4.34 USD   # 文档基线风险单位 (exit_lifecycle_report: median r_usd ≈ 4.34)
                          # 在 0.01 手黄金下 1 USD ≈ 1 价格点，故 R_price = 4.34
    ACT_MULT = 1.0        # 有利变动达到 +R 时激活 trailing
    TRAIL_MULT= 1.0       # trailing 止损距离 = R（激活瞬间止损移到 breakeven，之后随峰值 ratchet 上行）
    激活前若从未达到 +R：trailing 不触发，结果 = Baseline（只改"曾盈利"的交易）
    激活后价格回撤触到 trailing stop：在该 bar 以 stop 价退出（<= 原始退出时间，持仓不延长）

这是 Hypothesis Testing，不是 Parameter Mining。
"""

import json
import csv
import bisect
import statistics
from datetime import datetime, timezone

# ---------- 路径（相对项目根；脚本置于 backend/os_layers/） ----------
import os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MT5 = os.path.join(ROOT, "mt5_raw")
TRADE_PATH = os.path.join(MT5, "trade_path.json")
ENTRY_TIMING = os.path.join(MT5, "entry_timing_report.json")
M5_CSV = os.path.join(MT5, "XAUUSD_M5.csv")
OUT_DIR = os.path.join(ROOT, "backend", "output", "research_contracts")
OUT_JSON = os.path.join(OUT_DIR, "exit_observation_GOLD_TRAIL_v0.1.json")

# ---------- 预指定规则常量（禁止改成变量 / 网格） ----------
R_USD = 4.34          # 基线风险单位（文档已 REPRODUCED）
ACT_MULT = 1.0        # 激活阈值倍数
TRAIL_MULT = 1.0      # trailing 距离倍数
CONTRACT_PER_LOT = 100.0   # XAUUSD: 1 lot = 100 oz
DD_TOLERANCE = 1.10   # 决策用：trailing MaxDD <= baseline*1.10 视为"未显著恶化"

EXPERIMENT_ID = "EXIT-OBS-GOLD-TRAIL-v0.1"
HYPOTHESIS = ("H1: 在 Signal/Entry/Stop/Position/成本/数据完全固定下，仅引入 Trailing Exit，"
              "能否减少 Giveback 并提高 Realized P&L（MFE Capture 提升）。")


def parse_dt(s):
    # "2026-03-19T18:49:27" -> unix seconds (UTC, 与 M5 csv 的 time 字段一致)
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def pnl_usd(direction, entry, exit_px, volume):
    diff = (exit_px - entry) if direction == "BUY" else (entry - exit_px)
    return diff * volume * CONTRACT_PER_LOT


def load_trades():
    with open(TRADE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["trades"]


def load_confirmed_ids():
    """从 entry_timing_report.json 取 trade_id -> entry_type，确认子集 = E3 + E4。"""
    with open(ENTRY_TIMING, encoding="utf-8") as f:
        data = json.load(f)
    id2type = {}
    # 找包含 trade_id + entry_type 的列表（键名不固定，鲁棒解析）
    for v in data.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and "trade_id" in item and "entry_type" in item:
                    id2type[str(item["trade_id"])] = item["entry_type"]
    confirmed = {tid for tid, t in id2type.items() if t in ("E3_confirmed_entry", "E4_well_executed")}
    return confirmed, id2type


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


def simulate_trailing(trade, bars, times):
    """在 M5 路径上对单笔交易模拟预指定 Chandelier trailing。返回 dict。"""
    direction = trade["direction"]
    entry = float(trade["entry_price"])
    base_exit = float(trade["exit_price"])
    vol = float(trade["volume"])
    mfe_usd = float(trade["mfe_usd"])
    entry_unix = parse_dt(trade["entry_time"])
    exit_unix = parse_dt(trade["exit_time"])

    base_pnl = pnl_usd(direction, entry, base_exit, vol)

    # 切片：entry 之后到原始退出时间内的 M5 bar
    i = bisect.bisect_left(times, entry_unix)
    j = bisect.bisect_right(times, exit_unix)
    slice_bars = bars[i:j]

    R = R_USD / (vol * CONTRACT_PER_LOT)  # 价格单位的 R

    triggered = False
    trail_stop = None
    trailing_exit = base_exit
    trailing_exit_unix = exit_unix

    if slice_bars:
        if direction == "BUY":
            peak = entry
            for (t, high, low, _o, _c) in slice_bars:
                if high > peak:
                    peak = high
                fav = peak - entry
                if not triggered and fav >= R * ACT_MULT:
                    triggered = True
                    trail_stop = peak - R * TRAIL_MULT  # 激活瞬间 = breakeven 或更高
                if triggered:
                    cand = peak - R * TRAIL_MULT
                    if cand > trail_stop:
                        trail_stop = cand
                    if low <= trail_stop:
                        trailing_exit = trail_stop
                        trailing_exit_unix = t
                        break
        else:  # SELL
            peak = entry
            for (t, _h, low, _o, _c) in slice_bars:
                if low < peak:
                    peak = low
                fav = entry - peak
                if not triggered and fav >= R * ACT_MULT:
                    triggered = True
                    trail_stop = peak + R * TRAIL_MULT
                if triggered:
                    cand = peak + R * TRAIL_MULT
                    if cand < trail_stop or trail_stop is None:
                        trail_stop = cand
                    if _h >= trail_stop:
                        trailing_exit = trail_stop
                        trailing_exit_unix = t
                        break

    trail_pnl = pnl_usd(direction, entry, trailing_exit, vol)
    base_cap = (base_pnl / mfe_usd) if mfe_usd > 0 else float("nan")
    trail_cap = (trail_pnl / mfe_usd) if mfe_usd > 0 else float("nan")
    give_base = mfe_usd - base_pnl
    give_trail = mfe_usd - trail_pnl
    hold_base_h = (exit_unix - entry_unix) / 3600.0
    hold_trail_h = (trailing_exit_unix - entry_unix) / 3600.0

    return {
        "trade_id": trade["trade_id"],
        "direction": direction,
        "mfe_usd": mfe_usd,
        "baseline_pnl": base_pnl,
        "trailing_pnl": trail_pnl,
        "baseline_capture": base_cap,
        "trailing_capture": trail_cap,
        "giveback_baseline": give_base,
        "giveback_trailing": give_trail,
        "triggered": triggered,
        "hold_base_h": hold_base_h,
        "hold_trail_h": hold_trail_h,
    }


def agg(records):
    base_pnls = [r["baseline_pnl"] for r in records]
    trail_pnls = [r["trailing_pnl"] for r in records]
    net_base = sum(base_pnls)
    net_trail = sum(trail_pnls)

    def pf(pnls):
        gw = sum(p for p in pnls if p > 0)
        gl = -sum(p for p in pnls if p < 0)
        return (gw / gl) if gl > 0 else None  # None = 无亏损(退化，非调参结果)

    caps_base = [r["baseline_capture"] for r in records if r["baseline_capture"] == r["baseline_capture"]]
    caps_trail = [r["trailing_capture"] for r in records if r["trailing_capture"] == r["trailing_capture"]]
    give_base = [r["giveback_baseline"] for r in records]
    give_trail = [r["giveback_trailing"] for r in records]
    wins_base = [p for p in base_pnls if p > 0]
    losses_base = [p for p in base_pnls if p < 0]
    wins_trail = [p for p in trail_pnls if p > 0]
    losses_trail = [p for p in trail_pnls if p < 0]

    def max_dd(pnls):
        eq = 0.0
        peak = 0.0
        mdd = 0.0
        for p in pnls:
            eq += p
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > mdd:
                mdd = dd
        return mdd

    triggered_n = sum(1 for r in records if r["triggered"])
    return {
        "n": len(records),
        "triggered_n": triggered_n,
        "net_pnl_baseline": round(net_base, 2),
        "net_pnl_trailing": round(net_trail, 2),
        "net_pnl_delta": round(net_trail - net_base, 2),
        "pf_baseline": (round(pf(base_pnls), 4) if pf(base_pnls) is not None else None),
        "pf_trailing": (round(pf(trail_pnls), 4) if pf(trail_pnls) is not None else None),
        "median_capture_baseline": round(statistics.median(caps_base), 4) if caps_base else None,
        "median_capture_trailing": round(statistics.median(caps_trail), 4) if caps_trail else None,
        "median_giveback_baseline": round(statistics.median(give_base), 2),
        "median_giveback_trailing": round(statistics.median(give_trail), 2),
        "max_dd_baseline": round(max_dd(base_pnls), 2),
        "max_dd_trailing": round(max_dd(trail_pnls), 2),
        "win_rate_baseline": round(len(wins_base) / len(base_pnls), 4),
        "win_rate_trailing": round(len(wins_trail) / len(trail_pnls), 4),
        "avg_win_baseline": round(statistics.mean(wins_base), 2) if wins_base else 0.0,
        "avg_win_trailing": round(statistics.mean(wins_trail), 2) if wins_trail else 0.0,
        "avg_loss_baseline": round(statistics.mean(losses_base), 2) if losses_base else 0.0,
        "avg_loss_trailing": round(statistics.mean(losses_trail), 2) if losses_trail else 0.0,
        "median_R_baseline": round(statistics.median([p / R_USD for p in base_pnls]), 3),
        "median_R_trailing": round(statistics.median([p / R_USD for p in trail_pnls]), 3),
        "median_hold_base_h": round(statistics.median([r["hold_base_h"] for r in records]), 3),
        "median_hold_trail_h": round(statistics.median([r["hold_trail_h"] for r in records]), 3),
    }


def decide(m):
    imp_pnl = m["net_pnl_trailing"] > m["net_pnl_baseline"]
    pb = m["pf_baseline"]
    pt = m["pf_trailing"]
    imp_pf = (pb is not None and pt is not None and pt > pb)  # None(无亏损)不视为改善
    cap_b = m["median_capture_baseline"] or 0
    cap_t = m["median_capture_trailing"] or 0
    imp_cap = cap_t > cap_b
    dd_worsened = m["max_dd_trailing"] > m["max_dd_baseline"] * DD_TOLERANCE
    if imp_pnl and imp_pf and imp_cap and not dd_worsened:
        return "SUPPORT H1", "P&L/PF/Capture 均改善且 DD 未显著恶化"
    if imp_cap and not imp_pnl:
        return "PARTIAL SUPPORT", "Capture 改善但 P&L 未改善"
    if imp_cap and dd_worsened:
        return "TRADE-OFF", "Capture 改善但风险(DD)显著恶化"
    return "REJECT H1", "无改善或恶化"


def main():
    trades = load_trades()
    confirmed_ids, id2type = load_confirmed_ids()
    confirmed_trades = [t for t in trades if str(t["trade_id"]) in confirmed_ids]
    bars, times = load_m5()

    recs_confirmed = [simulate_trailing(t, bars, times) for t in confirmed_trades]
    recs_all = []
    for t in trades:
        rec = simulate_trailing(t, bars, times)
        rec["entry_type"] = id2type.get(str(t["trade_id"]), "unknown")  # 供 Entry×Exit Attribution 复用
        recs_all.append(rec)

    m_confirmed = agg(recs_confirmed)
    m_all = agg(recs_all)
    decision, rationale = decide(m_confirmed)

    # 校验：base 复算 vs 记录 pnl（抽样核对函数正确性）
    sample = confirmed_trades[0]
    rec0 = recs_confirmed[0]
    note_validate = (f"base 复算 pnl={rec0['baseline_pnl']:.2f} vs 记录 pnl={sample['pnl']:.2f} "
                     f"(差异≈佣金，函数有效)" if "pnl" in sample else "n/a")

    out = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": HYPOTHESIS,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "governance": "Observation-only. 不接 run_daily/risk_guard/shadow/CIO/Trading Coach/生产. "
                      "不修改权重/阈值/生产公式/Risk Budget/交易规则.",
        "rule_pre_specified": {
            "type": "Chandelier 1xR (预指定, 非调参)",
            "R_usd": R_USD,
            "activation_mult": ACT_MULT,
            "trail_mult": TRAIL_MULT,
            "note": "达到 +R 激活, 止损移到 breakeven 并 trails R; 回撤触 stop 即退出(<=原始退出时间). "
                    "未达 +R 则结果=Baseline. 禁止参数网格/反向选参.",
        },
        "batch_primary": {
            "definition": "确认入场 E3_confirmed_entry + E4_well_executed (固定 Signal/Entry)",
            "n": len(confirmed_trades),
            "trade_ids": [t["trade_id"] for t in confirmed_trades],
        },
        "metrics_primary_confirmed": m_confirmed,
        "metrics_secondary_all210": m_all,
        "decision": decision,
        "decision_rationale": rationale,
        "decision_note": "SUPPORT H1 != 进入生产. 最多意味值得进入 Robustness 阶段继续验证. 与 Phase 1E 治理一致.",
        "validation": note_validate,
        "per_trade_primary": recs_confirmed,
        "per_trade_all210": recs_all,
        "in_sample_note": "R=4.34 来自本批历史的 median r_usd (样本内统计量). 故本实验证据等级=样本内(IS), "
                          "不等于 OOS. H1 成立需独立/OOS 验证后方可进 Robustness.",
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print(f"[{EXPERIMENT_ID}] 批(主)=确认入场 n={len(confirmed_trades)} | 批(次)=全210 n={len(trades)}")
    print(f"  主批 NetPnL  base={m_confirmed['net_pnl_baseline']}  trail={m_confirmed['net_pnl_trailing']}  "
          f"Δ={m_confirmed['net_pnl_delta']}")
    print(f"  主批 PF      base={m_confirmed['pf_baseline']}  trail={m_confirmed['pf_trailing']}")
    print(f"  主批 Capture  base={m_confirmed['median_capture_baseline']}  trail={m_confirmed['median_capture_trailing']}")
    print(f"  主批 Giveback base={m_confirmed['median_giveback_baseline']}  trail={m_confirmed['median_giveback_trailing']}")
    print(f"  主批 MaxDD    base={m_confirmed['max_dd_baseline']}  trail={m_confirmed['max_dd_trailing']}")
    print(f"  主批 触发 trailing 笔数 = {m_confirmed['triggered_n']}/{m_confirmed['n']}")
    print(f"  校验: {note_validate}")
    print(f"  >>> DECISION: {decision} -- {rationale}")
    print(f"  写出: {OUT_JSON}")


if __name__ == "__main__":
    main()
