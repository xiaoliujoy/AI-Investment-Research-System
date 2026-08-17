# -*- coding: utf-8 -*-
"""
trade_measurement.py  --  B2.0 Manual Observation Pipeline 的测量核心（FROZEN）

状态：OBSERVATION（测量态，非统计研究、非分类器、非规则）

窄职责（铁律，来自用户 2026-08-16 架构锁定）
------------------------------------------
本模块**只能回答**：
    「这笔交易客观上发生了什么？」
本模块**不能回答**：
    「这笔交易做得好不好？」「哪里出了问题？」「以后应该怎么做？」
后三类属 Interpretation，归 Phase C / D，不在本模块权限内。

来源与不可变性
--------------
本文件是 `entry_quality_eq1m.py::compute_trade` 及其依赖（find_cp / favorable_usd /
adverse_usd / parse_dt）的**逐字提取**，冻结常量 K=2 / W=48 / IAE_WIN=10 与原文件
逐字一致。任何数学改动都须同步改 EQ-1M 预登记文档并重走 Gate 0——否则视为破坏冻结。

唯一外部化：CONTRACT_MULT（原硬编码 100）改为 `contract_mult` 参数（mult = contract_mult * volume）。
这是为了支持多品种（XAUUSD 标准手=100、A 股按股数、期货按合约乘数），不改变任何测量数学。

保真要求（关键）
--------------
compute_trade 仍读取 `t.get("ticket") or t.get("id")`（逐字复制 eq1m）。历史源
trade_path.json 的 key 为 `trade_id`，故测量输出 `trade_id` 恒为 null，与
eq1m_observation_v0_1.json 的冻结 observation 字节一致。**不得**为"修正"历史 id 丢失而改读
`trade_id` 键 —— 那会破坏 Round-trip Oracle 的字节一致。真实交易的去重键在摄入层
（coach_b2_ingest.py）从原始 blotter 单独提取，不依赖本模块输出的 trade_id。

本模块**不调用** EQ-1M 的 mediation_decomp / bootstrap / permutation（那是 Research 层统计）。
本模块**不写入**任何生产文件（run_daily / risk_guard / shadow / CIO）。
"""

import os
import bisect
from datetime import datetime, timezone

# ---------- 冻结常量（与 EQ-1M 逐字一致；改动须同步改预登记文档并重新走 Gate 0） ----------
K = 2                      # swing 确认半径（继承 EQ-1）
W = 48                     # CP 向前搜索窗口（继承 EQ-1）
IAE_WIN = 10               # IAE = entry 后 10 根完整 M5 最大逆向 excursion (R1 冻结)


# ----------------------------------------------------------------------------
# 基础工具（逐字复制自 eq1m；仅移除未使用的统计/路径函数）
# ----------------------------------------------------------------------------
def parse_dt(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


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


def compute_trade(t, bars, times, contract_mult=100.0):
    """返回完整 per-trade 记录（含 ETD + Outcomes），no-CP 则返回 None。

    逐字复制自 entry_quality_eq1m.compute_trade。唯一外部化：CONTRACT_MULT → contract_mult。
    trade_id 仍读 t.get("ticket") or t.get("id")（保真，历史源为 null）。
    """
    direction = t["direction"]
    entry_price = float(t["entry_price"])
    exit_price = float(t["exit_price"])
    vol = float(t["volume"])
    mult = contract_mult * vol
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
        "trade_id": t.get("ticket") or t.get("id"),   # 逐字复制 eq1m：历史源 key=trade_id → 此处恒 null
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
