# -*- coding: utf-8 -*-
"""
asset_intelligence/validation/signal_eval.py —— Asset Intelligence 信号验证（Phase 1.9-B1 · 问题②）

来源：asset_intelligence_history（enabled=1，排除 CASH / 空壳）。

回答：score 是否具备横截面排序能力？（不是预测）
  - 高分(≥70)资产，未来 5/20 日平均收益、胜率、最大回撤 是否系统性优于低分？
  - 若各档收益/胜率无梯度 → score 可能只是噪音。

不预测：只统计「历史上不同 score 档位对应的已发生收益」。
样本不足时该段返回 total_signals=0，由报告层标注「暂不可用」。
"""
from __future__ import annotations

from typing import Optional

from db import get_conn

from .returns import load_price_series, fwd_metrics


# score 分档（用户建议口径）
_TIERS = ["90-100", "70-90", "50-70", "<50"]


def _mean(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _reliability(n: int) -> str:
    if n == 0:
        return "无样本"
    if n < 30:
        return "低（样本不足）"
    if n < 100:
        return "中（样本有限）"
    return "较高"


def _tier(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score >= 90:
        return "90-100"
    if score >= 70:
        return "70-90"
    if score >= 50:
        return "50-70"
    return "<50"


def signal_ranking_ability() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    # 先确认有哪些真实信号符号 + A股信号日期区间（缺表时优雅降级）
    need_a_share = False
    dmin = dmax = None
    try:
        cur.execute(
            "SELECT DISTINCT symbol FROM asset_intelligence_history "
            "WHERE enabled=1 AND symbol<>'CASH'")
        syms = [r[0] for r in cur.fetchall()]
        need_a_share = "CN_EQ_ALL" in syms
        if need_a_share:
            cur.execute(
                "SELECT MIN(date), MAX(date) FROM asset_intelligence_history "
                "WHERE enabled=1 AND symbol='CN_EQ_ALL'")
            dmin, dmax = cur.fetchone()
    except Exception:
        syms = []
    series = load_price_series(need_a_share=need_a_share, date_min=dmin, date_max=dmax)

    # 只取真实评分资产（enabled=1）且排除现金基准
    try:
        cur.execute(
            "SELECT symbol, date, score FROM asset_intelligence_history "
            "WHERE enabled=1 AND symbol<>'CASH'")
        rows = cur.fetchall()
    except Exception:
        rows = []
    recorded = len(rows)          # 已落库信号（含尚无未来收益者）
    conn.close()

    buckets = {t: {"n": 0, "r5": [], "r20": [], "dd20": [], "win": 0}
               for t in _TIERS}
    for sym, d, sc in rows:
        m5 = fwd_metrics(series, sym, d, 5)
        m20 = fwd_metrics(series, sym, d, 20)
        if m5 is None and m20 is None:
            continue
        tier = _tier(sc)
        if tier is None:
            continue
        b = buckets[tier]
        b["n"] += 1
        if m5 is not None:
            b["r5"].append(m5[0])
        if m20 is not None:
            b["r20"].append(m20[0])
            b["dd20"].append(m20[1])
            if m20[0] > 0:
                b["win"] += 1

    out = []
    for t in _TIERS:
        b = buckets[t]
        n = b["n"]
        out.append({
            "tier": t,
            "n": n,
            "avg_ret_5d": _mean(b["r5"]),
            "avg_ret_20d": _mean(b["r20"]),
            "avg_max_dd_20d": _mean(b["dd20"]),
            "win_rate_20d": round(b["win"] / n * 100.0, 1) if n else None,
            "reliability": _reliability(n),
        })
    # total_signals = 可验证样本（已有未来收益）；recorded_signals = 已落库信号（含待验证）
    return {"tiers": out,
            "total_signals": sum(b["n"] for b in buckets.values()),
            "recorded_signals": recorded}
