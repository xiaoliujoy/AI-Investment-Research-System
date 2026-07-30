# -*- coding: utf-8 -*-
"""
asset_intelligence/universe.py —— 统一资产宇宙快照（Phase 1.8-C）

把任意资产类别混合的 List[AssetIntelligence] 汇总为一个「统一资产宇宙快照」。
这是 Phase 1.9 Regime Backtest Dashboard 的标准输入结构：稳定、可序列化、
不依赖 CIO，因此 Dashboard 可以独立演化而不被 CIO 主干牵制。

设计原则：
  - 零外部依赖（不 import DB / CIO / 任何引擎），只做汇总 + 协议健康 + 降序排序。
  - 不产配置比例（边界：score 仅排序，不分配 %）。
  - 降级不崩溃：空输入 → n_assets=0 + 健康 FAIL 感知（由 run_protocol_health 决定），
    下游可据 n_assets=0 判「无资产可观察」。
"""
from __future__ import annotations

import datetime

from asset_intelligence.validator import run_protocol_health


def _to_dict(a):
    """AssetIntelligence / dict → 纯 dict（兼容两类输入）。"""
    if hasattr(a, "to_dict"):
        return a.to_dict()
    return dict(a or {})


def build_universe_snapshot(assets: list) -> dict:
    """汇总跨资产信号为统一宇宙快照。

    Args:
        assets: List[AssetIntelligence | dict]，可混合 commodity / equity / cash / bond / ...

    Returns:
        {
          "generated_at":   str,
          "n_assets":       int,
          "asset_classes":  list[str],     # 去重排序后的资产类别（白名单语义）
          "assets":         list[dict],    # 按 score 降序（跨资产同台比较的核心）
          "protocol_health": dict,         # run_protocol_health 结果（整体合规审计）
          "note":           str,
        }

    边界：本函数不解释 score（方向含义由各自 adapter 负责），只做降序 + 体检 + 包装。
    """
    ordered = [_to_dict(a) for a in (assets or [])]
    # 跨资产同台比较：统一按 score 降序（score 已是各 adapter 归一化到 0-100 的强弱）
    ordered.sort(key=lambda x: (x.get("score") or 0), reverse=True)

    asset_classes = sorted({a.get("asset_class") for a in ordered if a.get("asset_class")})
    # 协议健康检查（整批快照合规，不落库，先经内存/JSON 流动）
    protocol_health = run_protocol_health(ordered)

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "n_assets": len(ordered),
        "asset_classes": asset_classes,
        "assets": ordered,
        "protocol_health": protocol_health,
        "note": ("统一资产宇宙快照（AIP）：跨资产同台比较，按 score 降序；"
                 "不含配置比例。Phase 1.9 Regime Backtest Dashboard 标准输入。"),
    }
