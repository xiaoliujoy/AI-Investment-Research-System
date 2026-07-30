# -*- coding: utf-8 -*-
"""
asset_intelligence/validation/confidence_eval.py —— Confidence 校准验证（Phase 1.9-B1 · 问题③）

来源：asset_intelligence_history（enabled=1，排除 CASH / 空壳）。

回答：高 confidence 是否真的更可靠？（呼应 AIP §7.5 score≠confidence 铁律）
  - 若 High / Medium / Low 三档的 20 日正确率 无梯度（High≈Low）→
    confidence 只是标签，需要重新设计。
  - 正确率口径：该信号未来 20 日收益 > 0 的比例。

不预测：只统计「历史上不同 confidence 档位对应的已发生收益方向命中」。
"""
from __future__ import annotations

from typing import Optional

from db import get_conn

from .returns import load_price_series, fwd_metrics


_LABELS = ["High", "Medium", "Low"]


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


def _label(confidence: Optional[float]) -> Optional[str]:
    if confidence is None:
        return None
    if confidence >= 0.7:
        return "High"
    if confidence >= 0.4:
        return "Medium"
    return "Low"


def confidence_calibration() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    # 先确认是否有 A股信号（决定是否需要加载 A股序列）
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

    try:
        cur.execute(
            "SELECT symbol, date, confidence FROM asset_intelligence_history "
            "WHERE enabled=1 AND symbol<>'CASH'")
        rows = cur.fetchall()
    except Exception:
        rows = []
    recorded = len(rows)          # 已落库信号（含尚无未来收益者）
    conn.close()

    buckets = {l: {"n": 0, "r20": [], "win": 0} for l in _LABELS}
    for sym, d, cf in rows:
        m20 = fwd_metrics(series, sym, d, 20)
        if m20 is None:
            continue
        lab = _label(cf)
        if lab is None:
            continue
        b = buckets[lab]
        b["n"] += 1
        b["r20"].append(m20[0])
        if m20[0] > 0:
            b["win"] += 1

    out = []
    for l in _LABELS:
        b = buckets[l]
        n = b["n"]
        out.append({
            "confidence": l,
            "n": n,
            "avg_ret_20d": _mean(b["r20"]),
            "correct_rate_20d": round(b["win"] / n * 100.0, 1) if n else None,
            "reliability": _reliability(n),
        })

    # 校准诊断：High 与 Low 正确率是否有梯度
    by_lab = {x["confidence"]: x for x in out}
    diag = _calibration_diagnosis(by_lab)
    # total_signals = 可验证样本（已有未来收益）；recorded_signals = 已落库信号（含待验证）
    return {"levels": out, "total_signals": sum(b["n"] for b in buckets.values()),
            "recorded_signals": recorded, "diagnosis": diag}


def _calibration_diagnosis(by_lab: dict) -> dict:
    hi = by_lab.get("High", {}).get("correct_rate_20d")
    lo = by_lab.get("Low", {}).get("correct_rate_20d")
    if hi is None or lo is None:
        return {"status": "样本不足，无法诊断", "gradient_ok": None}
    gap = round(hi - lo, 1)
    # 梯度合理阈值：High 比 Low 高 ≥5 个百分点视为有区分度
    gradient_ok = gap >= 5.0
    status = ("confidence 具备区分度" if gradient_ok
              else "confidence 区分度不足（High≈Low，疑似标签化）")
    return {"status": status, "gap_high_minus_low": gap, "gradient_ok": gradient_ok}
