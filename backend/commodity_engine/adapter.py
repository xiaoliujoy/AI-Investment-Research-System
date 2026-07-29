# -*- coding: utf-8 -*-
"""
commodity_engine/adapter.py —— 统一资产信号适配器（Phase 1.5 / 1.8 协议基础）

职责：把 Commodity Engine 的内部评分（commodity_factor_daily + analysis JSON）
      与数据健康置信度（commodity_health.json）转换为 CIO 可消费的
      统一 AssetSignal 协议结构。

═══════════════════════════════════════════════════════════════
统一结构（AssetSignal）——
  asset       资产大类（commodity）
  symbol      标的代码（AU0 / CU0 / SC0）
  name        中文名（沪金 / 沪铜 / 原油）
  category    细分品类（贵金属 / 有色 / 能源）
  score       综合评分 0-100（来自 commodity_factor_daily.total_score）
  stage       阶段（上涨趋势 / 震荡整理 / 下跌趋势）
  confidence  数据置信度（高 / 中 / 低 ← HEALTHY / WATCH / STALE）
  drivers     主要驱动（list[str]，来自 analysis.主要驱动）
  risks       风险提示（list[str]，来自 analysis.风险提示）
  detail      解释型明细（dict：维度 / 宏观环境 / 策略建议）

输出 build_commodity_signals() -> dict：
  {
    "asset_class": "commodity",
    "generated_at": str,
    "health_overall": str,         # HEALTHY / WATCH / STALE
    "confidence_overall": str,     # 高 / 中 / 低
    "signals": [AssetSignal, ...], # 标准化商品信号（按 score 降序）
    "commodity_env": str,          # 商品环境判读（一句话）
    "opportunity_ranking": [...],  # 商品内部机会排序（不含配置比例）
    "has_data": bool,
  }

Phase 1.8 提示：未来 A股 / ETF / 债券 的 adapter 也输出同构 AssetSignal，
CIO 统一消费后做跨资产排序（Global Asset Block）。本文件只负责「商品」一侧。
═══════════════════════════════════════════════════════════════

用法：
  python commodity_engine/adapter.py        # 打印标准化商品信号 + 机会排序
"""
from __future__ import annotations

import os
import sys
import json
import datetime

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from database.models import get_db  # noqa: E402

# 健康文件（与 commodity_engine/health.py 共用输出约定）
_HEALTH_PATH = os.path.join(_BACKEND, "output", "commodity_health.json")

# 健康状态 → 置信度中文
_HEALTH_TO_CONF = {"HEALTHY": "高", "WATCH": "中", "STALE": "低"}

# 三品种：内盘交易核心（与 scoring.PAIRS 保持一致）
PAIRS = {
    "AU0": {"name": "沪金", "category": "贵金属"},
    "CU0": {"name": "沪铜", "category": "有色"},
    "SC0": {"name": "原油", "category": "能源"},
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
# 单资产信号转换
# =============================================================================
def _to_signal(symbol: str, factor: dict, health: dict) -> dict:
    """把一个品种的最新评分 + 健康置信度转换为统一 AssetSignal。"""
    meta = PAIRS.get(symbol, {"name": symbol, "category": ""})
    a = factor.get("analysis_obj", {}) or {}
    fresh = (health.get("freshness", {}) or {}).get(symbol, {}) or {}
    status = fresh.get("status", "HEALTHY")
    return {
        "asset": "commodity",
        "symbol": symbol,
        "name": meta["name"],
        "category": meta["category"],
        "score": factor.get("total_score"),
        "stage": factor.get("stage", ""),
        "confidence": _HEALTH_TO_CONF.get(status, "中"),
        "drivers": a.get("主要驱动", []) or [],
        "risks": a.get("风险提示", []) or [],
        "detail": {
            "dimensions": a.get("维度", {}),
            "macro_env": a.get("宏观环境", ""),
            "strategy": a.get("策略建议", ""),
            "date": factor.get("date", ""),
        },
    }


# =============================================================================
# 商品环境判读 + 机会排序
# =============================================================================
def _commodity_env(signals: list) -> str:
    """根据三品种信号生成一句话商品环境判读。"""
    if not signals:
        return "商品数据暂不可用，无法判读环境。"
    scores = [s["score"] for s in signals if s["score"] is not None]
    avg = sum(scores) / len(scores) if scores else 50
    ups = [s for s in signals if s["stage"] == "上涨趋势"]
    downs = [s for s in signals if s["stage"] == "下跌趋势"]
    ordered = sorted(signals, key=lambda x: (x["score"] or 0), reverse=True)
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
        tail = f"；{top['name']}（{top['score']}·{top['stage']}）相对强于" \
               f"{weak['name']}（{weak['score']}·{weak['stage']}）"
    return f"商品{mood}（均值 {avg:.0f}）{tail}。"


def _opportunity_ranking(signals: list) -> list:
    """商品内部机会排序（按 score 降序，不含配置比例）。"""
    ordered = sorted(signals, key=lambda x: (x["score"] or 0), reverse=True)
    rank = []
    for i, s in enumerate(ordered, 1):
        note = "关注突破跟进" if s["stage"] == "上涨趋势" else (
            "等待企稳信号" if s["stage"] == "下跌趋势" else "区间观望，放量再跟进")
        rank.append({
            "rank": i,
            "symbol": s["symbol"],
            "name": s["name"],
            "score": s["score"],
            "stage": s["stage"],
            "confidence": s["confidence"],
            "note": note,
        })
    return rank


# =============================================================================
# 对外入口
# =============================================================================
def build_commodity_signals() -> dict:
    """构建标准化商品信号包（供 CIO 消费）。

    失败时降级：has_data=False + 空列表，绝不让上游崩溃。
    """
    try:
        health = _load_health()
        factors = _load_factor_latest()
        signals = []
        for sym in PAIRS:
            if sym in factors:
                signals.append(_to_signal(sym, factors[sym], health))
        signals.sort(key=lambda x: (x["score"] or 0), reverse=True)

        overall = health.get("overall", "")
        conf_overall = _HEALTH_TO_CONF.get(overall, "中" if overall else "未知")

        return {
            "asset_class": "commodity",
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "health_overall": overall,
            "confidence_overall": conf_overall,
            "signals": signals,
            "commodity_env": _commodity_env(signals),
            "opportunity_ranking": _opportunity_ranking(signals),
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
            "has_data": False,
            "error": str(e),
        }


if __name__ == "__main__":
    pkg = build_commodity_signals()
    print(f"\n=== Commodity AssetSignal 包（{pkg['generated_at']}）===")
    print(f"健康整体: {pkg['health_overall']}  置信度: {pkg['confidence_overall']}  "
          f"有数据: {pkg['has_data']}")
    print(f"商品环境: {pkg['commodity_env']}\n")
    print("--- AssetSignal（按评分降序）---")
    for s in pkg["signals"]:
        print(f"  [{s['symbol']}] {s['name']}({s['category']})  评分{s['score']}  "
              f"{s['stage']}  置信{s['confidence']}")
        if s["drivers"]:
            print(f"     驱动: {'；'.join(s['drivers'])}")
        if s["risks"]:
            print(f"     风险: {'；'.join(s['risks'])}")
    print("\n--- 商品内部机会排序 ---")
    for r in pkg["opportunity_ranking"]:
        print(f"  #{r['rank']} {r['name']}（{r['symbol']}）评分{r['score']} {r['stage']} "
              f"· {r['note']}")
