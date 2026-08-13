# -*- coding: utf-8 -*-
"""
risk_guard.py —— v0.2 Phase 1C Risk Guard Adapter（PRD §6，行为零变化）。

设计红线（最高优先级）：
  - 只【读取】既有 L7.raw.composite（唯一来源：decision_tree.py:232-246 写入
    results.L7.raw.composite）。不重新计算 composite。
  - 映射 risk_state：<30 LOW / 30-50 MEDIUM / 50-70 HIGH / >=70 EXTREME。
  - 只有 EXTREME（即既有 comp>=70）→ veto=True。
    这与既有 IC 的 hard_no 完全一致（investment_committee.decide() L245-249：
    comp>=70 → hard_no["综合风险高(comp)"] → can_buy=NO）。
  - 解析既有 position 字符串为 numeric（position_limit_min/max/label）。
  - 不新增任何风险条件：无 Volatility / Correlation / Liquidity / Drawdown Engine
    （这些属 P1 Risk Center，不在本 PRD 范围）。
  - 本模块【不接管】生产裁决。Phase 1C 期间它只计算并返回评估；
    生产裁决仍由既有 IC 决定（PRD §7 Shadow Mode：shadow_mode=1 时
    Risk Guard 仅记录 shadow_veto，绝不改写生产 can_buy/position/verdict）。

本模块是"风险映射"的唯一权威。write_decision_ledger 与后续 Shadow/Replay
都应调用本模块，禁止在别处重复实现映射逻辑（防止漂移）。
"""
from __future__ import annotations

import re


def risk_state_from_composite(comp) -> str:
    """映射既有 L7 composite → risk_state。

    <30 LOW / 30-50 MEDIUM / 50-70 HIGH / >=70 EXTREME（越高越危险）。
    与 Golden Master / write_decision_ledger / IC hard_no 完全一致。
    composite 为 None 时返回 "NULL"（数据缺失，不臆测）。
    """
    if comp is None:
        return "NULL"
    try:
        c = float(comp)
    except Exception:
        return "NULL"
    if c < 30:
        return "LOW"
    if c < 50:
        return "MEDIUM"
    if c < 70:
        return "HIGH"
    return "EXTREME"


def parse_position_limit(s):
    """解析既有 position 字符串为 numeric (min, max, label)。

    例：'30-50%' -> (0.30, 0.50, '30-50%')
        '<30%（或空仓）' -> (0.0, 0.30, '<30%')
        '80-100%' -> (0.80, 1.00, '80-100%')
    无法解析 -> (None, None, 原字符串)
    """
    if not s:
        return (None, None, None)
    s = str(s)
    if "80-100" in s or "80~100" in s:
        return (0.80, 1.00, "80-100%")
    if "50-80" in s or "50~80" in s:
        return (0.50, 0.80, "50-80%")
    if "30-50" in s or "30~50" in s:
        return (0.30, 0.50, "30-50%")
    nums = re.findall(r"(\d+(?:\.\d+)?)", s)
    if nums:
        v = float(nums[0])
        if v <= 30:
            return (0.0, v / 100.0, f"<{int(v)}%")
    return (None, None, s)


def _extract_composite(results: dict):
    l7 = (results or {}).get("L7") or {}
    raw = l7.get("raw") if isinstance(l7.get("raw"), dict) else {}
    return raw.get("composite")


def _extract_position(results: dict, brain: dict = None):
    """优先用 L7.raw.position（Risk Budget 口径），回退 committee.position_pct。"""
    l7 = (results or {}).get("L7") or {}
    raw = l7.get("raw") if isinstance(l7.get("raw"), dict) else {}
    pos = raw.get("position")
    if not pos and brain:
        pos = (brain.get("committee") or {}).get("position_pct")
    return pos


def assess(results: dict, brain: dict = None) -> dict:
    """核心：对一次系统运行的既有风险输出做【只读】评估，返回结构化结论。

    参数：
      results : decision_tree 产出的 results 字典（含 results.L7.raw.composite）
      brain   : 可选，完整 brain_report 字典（用于回退读取 committee.position_pct）
    返回：
      {
        composite, risk_state, veto(bool), veto_reason,
        position_limit_min, position_limit_max, position_limit_label, source
      }
    不改变任何外部状态、不修改生产裁决。
    """
    comp = _extract_composite(results)
    risk_state = risk_state_from_composite(comp)

    veto = False
    veto_reason = None
    if comp is not None:
        try:
            if float(comp) >= 70:
                veto = True
                veto_reason = f"综合风险高({comp})"
        except Exception:
            pass

    pos = _extract_position(results, brain)
    pmin, pmax, plabel = parse_position_limit(pos)

    return {
        "composite": comp,
        "risk_state": risk_state,
        "veto": veto,
        "veto_reason": veto_reason,
        "position_limit_min": pmin,
        "position_limit_max": pmax,
        "position_limit_label": plabel,
        "source": "results.L7.raw.composite",
    }


def assess_brain(brain: dict) -> dict:
    """便捷入口：直接吃完整 brain_report 字典。"""
    return assess((brain or {}).get("results", {}), brain=brain)
