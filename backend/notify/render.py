# -*- coding: utf-8 -*-
"""从 decision_tree.json 抽取一个统一的「看板视图」，供企业微信/飞书/公众号三端共用。"""
import os


def _safe(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def build_view(tree):
    L = tree.get("layers", {})
    l4 = L.get("L4_consensus", {}) or {}
    l5 = L.get("L5_leader", {}) or {}
    l6 = L.get("L6_execution", {}) or {}
    l7 = L.get("L7_risk", {}) or {}

    mains = []
    for r in (l4.get("main_lines") or [])[:8]:
        mains.append({
            "sector": r.get("sector", ""),
            "stage": r.get("stage", ""),
            "net_now": _safe(r.get("net_now")),
            "net_5d": _safe(r.get("net_5d")),
            "chg_pct": _safe(r.get("chg_pct")),
            "reason": r.get("reason", ""),
        })
    early = []
    for r in (l4.get("early_watch") or [])[:6]:
        early.append({"sector": r.get("sector", ""),
                      "stage": r.get("stage", ""),
                      "net_now": _safe(r.get("net_now")),
                      "chg_pct": _safe(r.get("chg_pct"))})

    # L5 龙头：取前 3 个主线板块
    leaders = []
    for sec in [m["sector"] for m in mains[:3]]:
        v = (l5.get("leaders") or {}).get(sec)
        if not v or "error" in v:
            continue
        row = {"sector": sec}
        for role in ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"]:
            ld = (v.get(role) or {})
            if ld.get("name"):
                row[role] = ld["name"]
        leaders.append(row)

    # L6 突破候选：取前 8
    cands = []
    for r in (l6.get("candidates") or [])[:8]:
        rk = r.get("risk") or {}
        cands.append({
            "name": r.get("name", ""),
            "code": r.get("code", ""),
            "sector": r.get("sector") or "",
            "breakout": r.get("breakout", ""),
            "risk_score": _safe(rk.get("score")),
            "amount_yi": _safe(r.get("amount_yi")),
            "change_pct": _safe(r.get("change_pct")),
        })

    risk = {
        "composite": l7.get("composite"),
        "position": l7.get("position", ""),
        "risk_market": l7.get("risk_market"),
        "risk_industry": l7.get("risk_industry"),
        "risk_stock": l7.get("risk_stock"),
        "worst_stock": l7.get("worst_stock"),
        "up_ratio": l7.get("up_ratio"),
    }

    nar = {}
    for k in ["L1_global_macro", "L2_china_macro", "L3_industry", "L8_learning"]:
        ly = L.get(k) or {}
        nar[k] = {"status": ly.get("status", ""), "read": ly.get("read", "")}

    return {
        "trade_date": tree.get("trade_date", ""),
        "generated_at": tree.get("generated_at", ""),
        "mains": mains,
        "early": early,
        "leaders": leaders,
        "candidates": cands,
        "risk": risk,
        "narrative": nar,
        "stage_distribution": l4.get("stage_distribution", {}),
        "sector_count": l4.get("sector_count"),
    }


def fmt_money(x):
    try:
        return f"{x:+.1f}亿"
    except Exception:
        return "-"
