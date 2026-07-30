# -*- coding: utf-8 -*-
"""
commodity_engine/adapter.py —— 商品 → Asset Intelligence Protocol 适配器（Phase 1.8）

职责：把 Commodity Engine 的内部评分（commodity_factor_daily + analysis JSON）
      与数据健康置信度（commodity_health.json）转换为 CIO 可消费的
      统一 Asset Intelligence Protocol（AIP）结构。

═══════════════════════════════════════════════════════════════
统一结构（AIP · AssetIntelligence）——
  asset_class  "commodity"
  symbol       标的代码（AU0 / CU0 / SC0）
  name         中文名（沪金 / 沪铜 / 原油）
  state        语义化状态（上行-避险 / 震荡-周期 / 下行-供给 ...）
  score        综合评分 0-100（来自 commodity_factor_daily.total_score）
  trend        up / down / sideways（由 stage 派生，统一动量口径）
  drivers      主要驱动（list[str]，来自 analysis.主要驱动）
  risks        风险提示（list[str]，来自 analysis.风险提示）
  confidence   数据置信度 0-1 浮点（HEALTHY→1.0 / WATCH→0.6 / STALE→0.3）
  detail       解释型明细（dict：品类 / 维度 / 宏观环境 / 策略建议 / 日期）
  confidence_label  展示用中文标签（高/中/低，由 confidence 派生）

输出 build_commodity_signals() -> dict：
  {
    "asset_class": "commodity",
    "generated_at": str,
    "health_overall": str,         # HEALTHY / WATCH / STALE
    "confidence_overall": str,     # 高 / 中 / 低（整体健康 → 整体置信）
    "signals": [AssetIntelligence(dict), ...],  # AIP 标准化商品信号（按 score 降序）
    "commodity_env": str,          # 商品环境判读（一句话）
    "opportunity_ranking": [...],  # 商品内部机会排序（不含配置比例）
    "protocol_health": dict,       # AIP 协议健康检查（Step 5）
    "has_data": bool,
  }

Phase 1.8 边界：本文件只改变「输出语言」，不动评分逻辑（scoring.py）。
债券 / ETF / 现金 / Crypto / FX 的 adapter 见 asset_intelligence 空壳注册，
不在此编造评分。
═══════════════════════════════════════════════════════════════

用法：
  python commodity_engine/adapter.py        # 打印 AIP 商品信号 + 机会排序 + 协议健康
"""
from __future__ import annotations

import os
import sys
import json
import datetime

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from database.models import get_db
from asset_intelligence.protocol import (
    AssetIntelligence,
    confidence_label,
    derive_trend_from_stage,
)
from asset_intelligence.validator import validate_and_clean, run_protocol_health

# 健康文件（与 commodity_engine/health.py 共用输出约定）
_HEALTH_PATH = os.path.join(_BACKEND, "output", "commodity_health.json")

# 健康状态 → 置信度（数值，AIP §7：HEALTHY→1.0 / WATCH→0.6 / STALE→0.3）
_HEALTH_TO_CONF_NUM = {"HEALTHY": 1.0, "WATCH": 0.6, "STALE": 0.3}
# 健康状态 → 中文标签（整体置信展示）
_HEALTH_TO_CONF_LABEL = {"HEALTHY": "高", "WATCH": "中", "STALE": "低"}

# 三品种：内盘交易核心（与 scoring.PAIRS 保持一致）
PAIRS = {
    "AU0": {"name": "沪金", "category": "贵金属"},
    "CU0": {"name": "沪铜", "category": "有色"},
    "SC0": {"name": "原油", "category": "能源"},
}

# 语义化状态映射（AIP §3：commodity state = 方向 + 修饰）
_STATE_MAP = {
    "AU0": {"上涨趋势": "上行-避险", "下跌趋势": "下行-避险", "震荡整理": "震荡-避险"},
    "CU0": {"上涨趋势": "上行-周期", "下跌趋势": "下行-周期", "震荡整理": "震荡-周期"},
    "SC0": {"上涨趋势": "上行-供给", "下跌趋势": "下行-供给", "震荡整理": "震荡-供给"},
}


# =============================================================================
# 数据加载
# =============================================================================
def _load_health() -> dict:
    """读取 commodity_health.json（不存在则返回空）。"""
    if not os.path.exists(_HEALTH_PATH):
        return {}
    try:
        with open(_HEALTH_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_factor_latest() -> dict:
    """读取 commodity_factor_daily 每品种最新一行，按 symbol 索引。"""
    conn = get_db()
    conn.row_factory = __import__("sqlite3").Row
    rows = conn.execute(
        "SELECT f.* FROM commodity_factor_daily f "
        "JOIN (SELECT symbol, MAX(date) md FROM commodity_factor_daily GROUP BY symbol) t "
        "ON f.symbol=t.symbol AND f.date=t.md ORDER BY f.symbol").fetchall()
    conn.close()
    out = {}
    for r in rows:
        d = dict(r)
        try:
            d["analysis_obj"] = json.loads(d["analysis"]) if d.get("analysis") else {}
        except Exception:
            d["analysis_obj"] = {}
        out[d["symbol"]] = d
    return out


# =============================================================================
# 单资产信号转换（→ AIP）
# =============================================================================
def _to_signal(symbol: str, factor: dict, health: dict) -> dict:
    """把一个品种的最新评分 + 健康置信度转换为统一 AssetIntelligence（AIP）。"""
    meta = PAIRS.get(symbol, {"name": symbol, "category": ""})
    a = factor.get("analysis_obj", {}) or {}
    fresh = (health.get("freshness", {}) or {}).get(symbol, {}) or {}
    status = fresh.get("status", "HEALTHY")
    stage = factor.get("stage", "")
    state = _STATE_MAP.get(symbol, {}).get(stage, stage or "震荡")
    trend = derive_trend_from_stage(stage)
    conf = _HEALTH_TO_CONF_NUM.get(status, 0.6)
    drivers = a.get("主要驱动", []) or []
    risks = a.get("风险提示", []) or []

    ai = AssetIntelligence(
        asset_class="commodity",
        symbol=symbol,
        name=meta["name"],
        state=state,
        score=(factor.get("total_score") or 0.0),
        trend=trend,
        drivers=drivers,
        risks=risks,
        confidence=conf,
        detail={
            "category": meta["category"],
            "dimensions": a.get("维度", {}),
            "macro_env": a.get("宏观环境", ""),
            "strategy": a.get("策略建议", ""),
            "date": factor.get("date", ""),
        },
    )
    # 过校验 + 自动清洗（clamp / 补默认），保证下游 CIO 永不吃到脏数据
    cleaned, _ = validate_and_clean(ai)
    cleaned["confidence_label"] = confidence_label(cleaned["confidence"])
    return cleaned


# =============================================================================
# 商品环境判读 + 机会排序
# =============================================================================
def _commodity_env(signals: list) -> str:
    """根据三品种信号生成一句话商品环境判读（基于 trend / state）。"""
    if not signals:
        return "商品数据暂不可用，无法判读环境。"
    scores = [s["score"] for s in signals if s.get("score") is not None]
    avg = sum(scores) / len(scores) if scores else 50
    ups = [s for s in signals if s.get("trend") == "up"]
    downs = [s for s in signals if s.get("trend") == "down"]
    ordered = sorted(signals, key=lambda x: (x.get("score") or 0), reverse=True)
    top = ordered[0] if ordered else None
    weak = ordered[-1] if ordered else None

    if avg >= 60 and len(ups) >= 2:
        mood = "整体偏强"
    elif avg <= 45 or len(downs) >= 2:
        mood = "整体偏弱"
    else:
        mood = "分化整理"

    tail = ""
    if top and weak and top["symbol"] != weak["symbol"]:
        tail = (f"；{top['name']}（{top['score']}·{top['state']}）相对强于"
                f"{weak['name']}（{weak['score']}·{weak['state']}）")
    return f"商品{mood}（均值 {avg:.0f}）{tail}。"


def _opportunity_ranking(signals: list) -> list:
    """商品内部机会排序（按 score 降序，不含配置比例）。"""
    ordered = sorted(signals, key=lambda x: (x.get("score") or 0), reverse=True)
    rank = []
    for i, s in enumerate(ordered, 1):
        note = ("关注突破跟进" if s.get("trend") == "up" else
                ("等待企稳信号" if s.get("trend") == "down" else "区间观望，放量再跟进"))
        rank.append({
            "rank": i,
            "symbol": s["symbol"],
            "name": s["name"],
            "score": s["score"],
            "state": s["state"],
            "trend": s["trend"],
            "confidence": s["confidence"],
            "confidence_label": s.get("confidence_label", confidence_label(s.get("confidence", 0))),
            "note": note,
        })
    return rank


# =============================================================================
# 对外入口
# =============================================================================
def build_commodity_signals() -> dict:
    """构建标准化商品 AIP 信号包（供 CIO 消费）。

    失败时降级：has_data=False + 空列表，绝不让上游崩溃。
    """
    try:
        health = _load_health()
        factors = _load_factor_latest()
        signals = []
        for sym in PAIRS:
            if sym in factors:
                signals.append(_to_signal(sym, factors[sym], health))
        signals.sort(key=lambda x: (x.get("score") or 0), reverse=True)

        overall = health.get("overall", "")
        conf_overall = _HEALTH_TO_CONF_LABEL.get(overall, "中" if overall else "未知")

        # AIP 协议健康检查（Step 5）：每天核对整批信号的协议合规
        protocol_health = run_protocol_health(signals)

        return {
            "asset_class": "commodity",
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "health_overall": overall,
            "confidence_overall": conf_overall,
            "signals": signals,
            "commodity_env": _commodity_env(signals),
            "opportunity_ranking": _opportunity_ranking(signals),
            "protocol_health": protocol_health,
            "has_data": bool(signals),
        }
    except Exception as e:  # noqa
        return {
            "asset_class": "commodity",
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "health_overall": "",
            "confidence_overall": "未知",
            "signals": [],
            "commodity_env": f"商品信号生成失败：{e}",
            "opportunity_ranking": [],
            "protocol_health": {"overall": "FAIL", "n_signals": 0,
                                "checks": {}, "error": str(e)},
            "has_data": False,
            "error": str(e),
        }


if __name__ == "__main__":
    pkg = build_commodity_signals()
    print(f"\n=== Commodity AIP 包（{pkg['generated_at']}）===")
    print(f"健康整体: {pkg['health_overall']}  置信度: {pkg['confidence_overall']}  "
          f"有数据: {pkg['has_data']}")
    ph = pkg.get("protocol_health", {})
    print(f"协议健康: {ph.get('overall')}（{ph.get('n_signals')} 个信号）")
    print(f"商品环境: {pkg['commodity_env']}\n")
    print("--- AssetIntelligence（按评分降序）---")
    for s in pkg["signals"]:
        print(f"  [{s['symbol']}] {s['name']}({s['detail'].get('category','')})  评分{s['score']}  "
              f"状态{s['state']} 趋势{s['trend']}  置信{s['confidence_label']}({s['confidence']})")
        if s["drivers"]:
            print(f"     驱动: {'；'.join(s['drivers'])}")
        if s["risks"]:
            print(f"     风险: {'；'.join(s['risks'])}")
    print("\n--- 商品内部机会排序 ---")
    for r in pkg["opportunity_ranking"]:
        print(f"  #{r['rank']} {r['name']}（{r['symbol']}）评分{r['score']} {r['state']} "
              f"· {r['note']}")
