# -*- coding: utf-8 -*-
"""
position_layer.py —— 持仓分层引擎（Personal AI Research System）
================================================================

移植自开源项目 AI-Portfolio-Compass（MIT License,
https://github.com/Elian-dan/AI-Portfolio-Compass-public）的
`backend/app/services/classifier.py` 的 **纯规则仓位分层逻辑**。

「取其精华去其糟粕」适配说明：
  - 精华：classify_position() 是纯规则、零 LLM 依赖、可解释、可移植。
    我们把这套规则原样保留（标注 MIT 出处），因为它正好补上我们
    Trading OS 在「个人账户持仓怎么分层」上的空白。
  - 去糟粕：原项目耦合 Futu/OpenD 券商适配器、LLM 行为画像。
    我们全部去掉，改用用户本地维护的 output/holdings.json（人工记账），
    并把人工 override 持久化到 output/position_layer_overrides.json。
  - 数据源：我们自己的 TDX 本地数据 + 用户手工 holdings.json，不依赖任何商业源。

仓位层级（与原项目一致）：
  - 核心长期仓（>=180天 / ETF多次加仓）
  - 中期配置仓（21~180天）
  - 短期交易仓（<21天 / 有完整买卖闭环 / 期权·杠杆ETF<21天）
  - 遗留观察仓（深套>30%且持有>180天 / 无买入记录）

输入：
  output/holdings.json            用户维护的持仓台账（缺失则优雅降级）
  output/position_layer_overrides.json  人工层级 override（可选）

输出：build() 返回 dict，供 CIO memo + research_memo 渲染。
"""
from __future__ import annotations

import os
import json
import datetime
from dataclasses import dataclass, field
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
HOLDINGS_PATH = os.path.join(OUT, "holdings.json")
OVERRIDES_PATH = os.path.join(OUT, "position_layer_overrides.json")

# 持仓层级常量（与原项目 POSITION_LAYERS 对齐）
LAYER_CORE = "核心长期仓"
LAYER_MID = "中期配置仓"
LAYER_SHORT = "短期交易仓"
LAYER_LEGACY = "遗留观察仓"
ALL_LAYERS = [LAYER_CORE, LAYER_MID, LAYER_SHORT, LAYER_LEGACY]

# 阈值（与原项目一致，单位：天 / 浮亏比例）
SHORT_HOLD_DAYS = 21          # 持有 < 21 天 -> 短期
CORE_HOLD_DAYS = 180          # 持有 >= 180 天 -> 核心长期
DEEP_LOSS_RATIO = -0.30       # 浮亏 > 30% 且长期 -> 遗留观察
ETF_ADD_COUNT = 3             # ETF 加仓 >= 3 次 -> 核心长期


@dataclass
class PositionFacts:
    """单只持仓的原始事实（由 holdings.json 一行 + 派生字段构成）。"""
    code: str = ""
    name: str = ""
    asset_type: str = "A股"          # A股 / ETF / 期权 / 港股 / 美股 ...
    position_weight: float = 0.0     # 0~1，占组合比重
    first_buy_time: str = ""         # 首次买入日期 YYYY-MM-DD
    buy_count: int = 0
    sell_count: int = 0
    has_round_trip: bool = False     # 是否有完整买卖闭环（买过也卖过）
    profit_loss_ratio: float = 0.0   # 浮盈亏比例，+0.08 = 赚8%，-0.35 = 亏35%
    is_leveraged_etf: bool = False
    manual_layer: str = ""           # 人工指定层级（最高优先级）
    data_days: int = 0               # 派生：持有天数（首次买入至今）


@dataclass
class LayerResult:
    layer: str
    source: str          # manual / rule / override
    confidence: float    # 0~1
    reason: str


def classify_position(facts: PositionFacts) -> LayerResult:
    """纯规则仓位分层（移植自 AI-Portfolio-Compass classifier.py，MIT）。

    优先级链：
      manual_layer 指定 > 期权/杠杆ETF且<21天 > 深套遗留 > 闭环/短线 >
      核心长期(>=180天或ETF多次加仓) > 中期(21~180天)
    """
    # 1) 人工 override 最高优先级
    if facts.manual_layer:
        return LayerResult(facts.manual_layer, "manual", 1.0,
                           f"人工指定层级：{facts.manual_layer}")

    # 2) 期权 / 杠杆 ETF 且持有 < 21 天 -> 短期
    if (facts.asset_type == "期权" or facts.is_leveraged_etf) and facts.data_days < SHORT_HOLD_DAYS:
        return LayerResult(LAYER_SHORT, "rule", 0.9,
                           "期权/杠杆ETF且持有<21天，按短线处理")

    # 3) 无买入记录 / 深套>30%且持有>180天 -> 遗留观察
    if facts.buy_count == 0 or (facts.profit_loss_ratio <= DEEP_LOSS_RATIO
                                 and facts.data_days > CORE_HOLD_DAYS):
        return LayerResult(LAYER_LEGACY, "rule", 0.8,
                           "无买入记录或深套>30%且持有>180天 -> 转入遗留观察")

    # 4) 有完整买卖闭环 / 持有 < 21 天 -> 短期
    if facts.has_round_trip or facts.data_days < SHORT_HOLD_DAYS:
        return LayerResult(LAYER_SHORT, "rule", 0.85,
                           "有完整买卖闭环或持有<21天 -> 短期交易仓")

    # 5) 持有 >= 180 天 -> 核心长期
    if facts.data_days >= CORE_HOLD_DAYS:
        return LayerResult(LAYER_CORE, "rule", 0.8,
                           f"持有>=180天（{facts.data_days}天）-> 核心长期仓")

    # 6) ETF 多次加仓 -> 核心长期
    if facts.asset_type == "ETF" and facts.buy_count >= ETF_ADD_COUNT:
        return LayerResult(LAYER_CORE, "rule", 0.75,
                           f"ETF累计加仓{facts.buy_count}次 -> 核心长期仓")

    # 7) 其余 21~180 天 -> 中期配置
    return LayerResult(LAYER_MID, "rule", 0.7,
                       f"持有21~180天（{facts.data_days}天）-> 中期配置仓")


# ═══════════════════════════════════════════════════════
#  数据加载 / 持久化
# ═══════════════════════════════════════════════════════

def load_overrides() -> dict:
    if not os.path.exists(OVERRIDES_PATH):
        return {}
    try:
        with open(OVERRIDES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_override(code: str, layer: str) -> bool:
    """把人工层级 override 持久化到 output/position_layer_overrides.json。"""
    if layer not in ALL_LAYERS:
        return False
    ov = load_overrides()
    ov[code] = layer
    try:
        with open(OVERRIDES_PATH, "w", encoding="utf-8") as f:
            json.dump(ov, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _derive_days(first_buy_time: str) -> int:
    if not first_buy_time:
        return 0
    try:
        d = datetime.date.fromisoformat(first_buy_time[:10])
        return max(0, (datetime.date.today() - d).days)
    except Exception:
        return 0


def load_holdings() -> list:
    """读取用户维护的持仓台账 output/holdings.json。缺失/损坏 -> 空列表。"""
    if not os.path.exists(HOLDINGS_PATH):
        return []
    try:
        with open(HOLDINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("holdings", [])
    if not isinstance(data, list):
        return []
    out = []
    for h in data:
        if not isinstance(h, dict) or not h.get("code"):
            continue
        # 杠杆 ETF 识别：名称含「杠杆」「倍数」「(看多)」等
        name = (h.get("name") or "")
        is_lev = bool(h.get("is_leveraged_etf")) or any(
            k in name for k in ("杠杆", "倍数ETF", "双倍", "三倍", "2x", "3x"))
        fbt = h.get("first_buy_time") or h.get("first_buy") or ""
        buy = int(h.get("buy_count") or 0)
        sell = int(h.get("sell_count") or 0)
        facts = PositionFacts(
            code=str(h.get("code")),
            name=name,
            asset_type=h.get("asset_type") or _guess_asset_type(name),
            position_weight=float(h.get("position_weight") or 0),
            first_buy_time=fbt,
            buy_count=buy,
            sell_count=sell,
            has_round_trip=bool(h.get("has_round_trip", sell > 0 and buy > 0)),
            profit_loss_ratio=float(h.get("profit_loss_ratio") or 0),
            is_leveraged_etf=is_lev,
            manual_layer=str(h.get("manual_layer") or ""),
            data_days=int(h.get("data_days") or _derive_days(fbt)),
        )
        out.append(facts)
    return out


def _guess_asset_type(name: str) -> str:
    n = name or ""
    if "ETF" in n or "基金" in n:
        return "ETF"
    if "购" in n or "购权" in n or "期权" in n:
        return "期权"
    return "A股"


# ═══════════════════════════════════════════════════════
#  主构建
# ═══════════════════════════════════════════════════════

def build() -> dict:
    """持仓分层主构建。无 holdings.json -> has_data=False 优雅降级。"""
    holdings = load_holdings()
    overrides = load_overrides()

    if not holdings:
        return {
            "has_data": False,
            "n_holdings": 0,
            "holdings": [],
            "layer_distribution": {},
            "weight_by_layer": {},
            "overrides": overrides,
            "summary": "暂无持仓台账（output/holdings.json）。"
                      "维护该文件后本模块会自动分层；不影响其他引擎。",
        }

    classified = []
    layer_dist: dict = {k: 0 for k in ALL_LAYERS}
    weight_by_layer: dict = {k: 0.0 for k in ALL_LAYERS}

    for f in holdings:
        # 应用 override（若 holdings 行未写 manual_layer，但 overrides 有）
        if not f.manual_layer and f.code in overrides:
            f.manual_layer = overrides[f.code]
        res = classify_position(f)
        layer_dist[res.layer] = layer_dist.get(res.layer, 0) + 1
        w = f.position_weight or 0.0
        weight_by_layer[res.layer] = weight_by_layer.get(res.layer, 0.0) + w
        classified.append({
            "code": f.code,
            "name": f.name,
            "asset_type": f.asset_type,
            "weight_pct": round(w * 100, 2),
            "layer": res.layer,
            "source": res.source,
            "confidence": round(res.confidence, 2),
            "reason": res.reason,
            "pl_ratio": round(f.profit_loss_ratio * 100, 2),
            "data_days": f.data_days,
        })

    # 按层级排序输出（核心长期在前），同层按权重降序
    order = {LAYER_CORE: 0, LAYER_MID: 1, LAYER_SHORT: 2, LAYER_LEGACY: 3}
    classified.sort(key=lambda x: (order.get(x["layer"], 9), -x["weight_pct"]))

    total_w = sum(weight_by_layer.values()) or 1.0
    weight_pct_by_layer = {k: round(v / total_w * 100, 1)
                           for k, v in weight_by_layer.items()}

    # 一句话摘要
    core_w = weight_pct_by_layer.get(LAYER_CORE, 0)
    short_w = weight_pct_by_layer.get(LAYER_SHORT, 0)
    legacy_w = weight_pct_by_layer.get(LAYER_LEGACY, 0)
    summary = (f"共{len(classified)}只持仓：核心长期{core_w}% / "
               f"中期{weight_pct_by_layer.get(LAYER_MID,0)}% / "
               f"短期{short_w}% / 遗留{legacy_w}%。")
    if legacy_w >= 30:
        summary += "⚠ 遗留观察仓占比偏高，建议优先处理深套标的。"
    if short_w >= 50:
        summary += "短线仓位过重，注意交易频率。"

    return {
        "has_data": True,
        "n_holdings": len(classified),
        "holdings": classified,
        "layer_distribution": layer_dist,
        "weight_by_layer": weight_pct_by_layer,
        "overrides": overrides,
        "summary": summary,
    }


if __name__ == "__main__":
    import pprint
    pprint.pprint(build())
