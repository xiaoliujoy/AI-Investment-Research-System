"""
Global Asset Snapshot — Phase 1.6
每天生成全球资产快照：风险状态 + 各资产环境判读。
不预测，只观察。回答「今天全球资金在哪里，风险偏好如何」。

输出结构：
{
    date, generated_at,
    risk_state: { label, score, drivers },
    assets: {
        equity:   { a_share: {...}, global: {...} },
        commodity: { AU0: {...}, CU0: {...}, SC0: {...} },
        macro:    { dxy: {...}, us10y: {...}, tips: {...}, btc: {...} }
    },
    narrative: str,          # 一句话环境总结
    has_data: bool
}

接入点：可独立调用，也可被 CIO _build_global_asset_obs 复用。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional

_DB_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "vibe_research.db"))

# ── 风险状态阈值 ──────────────────────────────────────────────
# 基于 DXY + US10Y + BTC + 商品均值 的综合得分粗判
_REGIME_THRESHOLDS = {
    "Risk On":      65,    # 弱美元 + 利率稳定/下行 + BTC强 + 商品强
    "Neutral":      40,    # 中间地带
    "Risk Off":     0,     # 强美元 + 利率上行 + BTC弱 + 商品弱
}

_REGIME_LABELS = ["Risk Off", "Neutral", "Risk On"]


def _db_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _latest_value(symbol: str) -> Optional[dict]:
    """取 global_history 某符号最新一行。"""
    try:
        cur = _db_conn().cursor()
        cur.execute(
            "SELECT date, close FROM global_history WHERE symbol=? ORDER BY date DESC LIMIT 1",
            (symbol,),
        )
        r = cur.fetchone()
        if r:
            return {"date": r[0], "value": round(r[1], 2) if r[1] else None}
    except Exception:
        pass
    return None


def _latest_commodity_factor() -> list[dict]:
    """取 commodity_factor_daily 每品种最新行。"""
    rows = []
    try:
        cur = _db_conn().cursor()
        cur.execute("""
            SELECT symbol, name, category, total_score, stage,
                   macro_score, fund_score, technical_score, risk_score,
                   analysis, date
            FROM commodity_factor_daily
            WHERE (symbol, date) IN (
                SELECT symbol, MAX(date) FROM commodity_factor_daily GROUP BY symbol
            )
            ORDER BY total_score DESC
        """)
        for r in cur.fetchall():
            analysis = {}
            if r[9]:
                try:
                    analysis = json.loads(r[9])
                except (json.JSONDecodeError, TypeError):
                    pass
            rows.append({
                "symbol": r[0], "name": r[1], "category": r[2],
                "total_score": round(r[3], 1) if r[3] else None,
                "stage": r[4],
                "macro": round(r[5], 1) if r[5] else None,
                "fund": round(r[6], 1) if r[6] else None,
                "technical": round(r[7], 1) if r[7] else None,
                "risk": round(r[8], 1) if r[8] else None,
                "analysis": analysis,
                "date": r[10],
            })
    except Exception:
        pass
    return rows


def _score_macro_item(d: Optional[dict]) -> float:
    """给单个宏观数据打分(0~100)，用于 regime 粗估。"""
    if not d or d.get("value") is None:
        return 50.0  # 无数据给中性分

    v = d["value"]
    # DXY: <98 强 Risk On / ~100 Neutral / >103 Risk Off
    if "dxy" in str(d).lower():
        if v < 97:
            return 75
        elif v < 100:
            return 60
        elif v < 102:
            return 45
        else:
            return 25

    # US10Y: <4.0 Risk On / ~4.5 Neutral / >5.0 Risk Off
    if v < 3.8:
        return 72
    elif v < 4.5:
        return 55
    elif v < 5.0:
        return 38
    else:
        return 22

    # BTC: >70k Risk On / ~60k Neutral / <45k Risk Off
    if v > 70000:
        return 75
    elif v > 55000:
        return 52
    else:
        return 28


def _derive_risk_state(macro_items: dict) -> dict:
    """
    基于宏观数据粗判风险偏好状态。
    注意：这是 Phase 1.6 的简化版，Phase 2 Asset Regime Engine 会用更精细的状态机替代。
    """
    scores = []
    drivers = []

    dxy = macro_items.get("dxy")
    us10y = macro_items.get("us10y")
    btc = macro_items.get("btc")

    for key, item in [("DXY", dxy), ("US10Y", us10y), ("BTC", btc)]:
        s = _score_macro_item(item)
        scores.append(s)
        if item and item.get("value") is not None:
            drivers.append(f"{key}={item['value']}")

    avg = sum(scores) / len(scores) if scores else 50.0

    if avg >= _REGIME_THRESHOLDS["Risk On"]:
        label = "Risk On"
    elif avg >= _REGIME_THRESHOLDS["Neutral"]:
        label = "Neutral"
    else:
        label = "Risk Off"

    return {
        "label": label,
        "score": round(avg, 1),
        "drivers": drivers,
        "note": "Phase 1.6 粗估（基于 DXY/US10Y/BTC 三因子），Phase 2 Asset Regime Engine 将用多因子状态机替代",
    }


def _summarize_commodity(signal: dict) -> str:
    """一句话概括单个商品状态。"""
    name = signal.get("name", "")
    stage = signal.get("stage", "未知")
    score = signal.get("total_score")
    analysis = signal.get("analysis", {})
    drivers = analysis.get("主要驱动", [])
    driver_str = ", ".join(drivers[:2]) if drivers else ""

    parts = [f"{name}: {stage}"]
    if score is not None:
        parts.insert(1, f"评分{score:.0f}")
    if driver_str:
        parts.append(f"({driver_str})")
    return " ".join(parts)


def build_global_snapshot(a_share_env: Optional[dict] = None) -> dict:
    """
    构建全球资产快照。

    Args:
        a_share_env: 可选的 A股环境字典（从 cio_agent._derive_a_share_env 获取），
                     若不传则 A股 标记为「未连接」。

    Returns:
        快照字典，含 risk_state / assets / narrative / has_data。
    """
    snap: dict[str, Any] = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "has_data": False,
    }

    try:
        # ── Macro ──
        dxy = _latest_value("DXY")
        us10y = _latest_value("US10Y")
        tips = _latest_value("TIPS")
        btc = _latest_value("BTC")

        # 从 TIPS 和 US10Y 推算实际利率
        real_yield = None
        if tips and us10y and tips.get("value") and us10y.get("value"):
            # TIPS 是价格指数，实际收益率 ≈ (100/TIPS_price * (US10Y+100)) - 100，粗略估算
            # 更简单：如果 TIPS 价格>100 则实际利率为负
            real_yield = round(us10y["value"] - (110 - tips["value"]), 2)

        macro = {
            "dxy": {**dxy, "label": "美元指数"} if dxy else None,
            "us10y": {**us10y, "label": "美债10Y"} if us10y else None,
            "tips": {**tips, "label": "TIPS"} if tips else None,
            "btc": {**btc, "label": "比特币"} if btc else None,
        }
        if real_yield is not None:
            macro["real_yield"] = {"value": real_yield, "label": "实际利率(估)"}

        # ── Commodity ──
        factors = _latest_commodity_factor()
        commodity = {}
        for f in factors:
            commodity[f["symbol"]] = {
                "name": f["name"],
                "category": f["category"],
                "score": f["total_score"],
                "stage": f["stage"],
                "summary": _summarize_commodity(f),
                "dimensions": {
                    "宏观": f["macro"], "资金": f["fund"],
                    "技术": f["technical"], "风险": f["risk"],
                },
            }

        # ── Equity ──
        equity: dict[str, Any] = {}
        if a_share_env:
            equity["a_share"] = {
                "status": a_share_env.get("status", "未知"),
                "direction": a_share_env.get("direction"),
                "can_buy": a_share_env.get("can_buy"),
                "breadth_pct": a_share_env.get("breadth_pct"),
                "top_sector": a_share_env.get("top_sector"),
                "summary": f"A股: {a_share_env.get('status', '未知')}",
            }

        # Global equities quick look
        for sym, label in [("NDX", "纳指"), ("SOXX", "半导体ETF"), ("NKY", "日经")]:
            v = _latest_value(sym)
            if v:
                equity[sym.lower()] = {"name": label, "latest_date": v["date"], "value": v["value"]}

        # ── Risk State ──
        macro_raw = {k: v for k, v in {
            "dxy": dxy, "us10y": us10y, "btc": btc,
        }.items() if v}
        risk_state = _derive_risk_state(macro_raw)

        # ── Narrative ──
        commodity_scores = [f["total_score"] for f in factors if f.get("total_score") is not None]
        avg_commodity = sum(commodity_scores) / len(commodity_scores) if commodity_scores else None

        narrative_parts = [f"风险偏好={risk_state['label']}"]
        if dxy and dxy.get("value"):
            narrative_parts.append(f"DXY={dxy['value']:.1f}")
        if us10y and us10y.get("value"):
            narrative_parts.append(f"美债10Y={us10y['value']:.2f}%")
        if avg_commodity is not None:
            strong = [f["name"] for f in factors if f.get("total_score", 0) >= 60]
            weak = [f["name"] for f in factors if f.get("total_score", 0) is not None and f["total_score"] < 55]
            if strong:
                narrative_parts.append(f"商品偏强:{'+'.join(strong)}")
            if weak:
                narrative_parts.append(f"商品偏弱:{'+'.join(weak)}")

        narrative = "；".join(narrative_parts)

        snap.update({
            "risk_state": risk_state,
            "assets": {
                "equity": equity,
                "commodity": commodity,
                "macro": {k: v for k, v in macro.items() if v},
            },
            "narrative": narrative,
            "has_data": True,
        })

    except Exception as e:
        snap["error"] = str(e)
        snap["has_data"] = False

    return snap


def format_snapshot_text(snap: dict) -> str:
    """将快照格式化为可读文本（用于日报嵌入或 CLI 输出）。"""
    if not snap.get("has_data"):
        err = snap.get("error", "")
        return f"全球资产快照暂不可用{f'（{err}）' if err else ''}"

    lines = []
    rs = snap.get("risk_state", {})
    lines.append(f"全球资产快照 · {snap.get('date', '?')}")
    lines.append("")
    lines.append(f"风险状态: {rs.get('label', '?')} （置信度: {'高' if (rs.get('score') or 0) > 60 or (rs.get('score') or 0) < 30 else '中'}）")

    # Macro
    macro = snap.get("assets", {}).get("macro", {})
    if macro:
        lines.append("")
        lines.append("宏观:")
        for key in ["dxy", "us10y", "tips", "btc", "real_yield"]:
            item = macro.get(key)
            if item:
                val = item.get("value")
                label = item.get("label", key)
                if isinstance(val, float):
                    if key == "dxy":
                        lines.append(f"  {label}: {val:.1f}")
                    elif key == "btc":
                        lines.append(f"  {label}: ${val:,.0f}")
                    elif "yield" in key.lower() or "Y" in label:
                        lines.append(f"  {label}: {val:.2f}%")
                    else:
                        lines.append(f"  {label}: {val}")
                else:
                    lines.append(f"  {label}: {val}")

    # Commodity
    comm = snap.get("assets", {}).get("commodity", {})
    if comm:
        lines.append("")
        lines.append("商品:")
        for sym in ["CU0", "AU0", "SC0"]:
            item = comm.get(sym)
            if item:
                summary = item.get("summary", f"{item.get('name')}: {item.get('stage')}")
                lines.append(f"  {summary}")

    # Equity
    eq = snap.get("assets", {}).get("equity", {})
    if eq:
        lines.append("")
        lines.append("股票:")
        ashare = eq.get("a_share")
        if ashare:
            lines.append(f"  A股: {ashare.get('summary', ashare.get('status', '?'))}")
        for sym in ["ndx", "soxx", "nky"]:
            item = eq.get(sym)
            if item:
                lines.append(f"  {item.get('name', sym)}: {item.get('value')} ({item.get('latest_date', '?')})")

    # Narrative
    narr = snap.get("narrative", "")
    if narr:
        lines.append("")
        lines.append(f"环境总结: {narr}")

    # Note
    lines.append("")
    lines.append("— 仅观察，不构成投资建议 —")

    return "\n".join(lines)


# ── CLI 测试 ───────────────────────────────────────────────────
if __name__ == "__main__":
    snap = build_global_snapshot()
    print(format_snapshot_text(snap))
    print()
    print("=== JSON ===")
    print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
