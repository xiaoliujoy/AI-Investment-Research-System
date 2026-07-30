# -*- coding: utf-8 -*-
"""
asset_intelligence/validator.py —— AIP 根因防御校验（Phase 1.8）

呼应 Phase 1.6 的 `_DB_PATH` 可靠性教训：协议层把「字段搬运」变成「字段契约」，
任何 adapter 输出都必须过校验，防止黑盒 / 空输出 / 污染下游 CIO。

校验规则（docs/asset-intelligence-protocol.md §8）：
  1. 字段完整     : 必填键存在且非 None
  2. confidence   : ∈ [0, 1]，越界自动 clamp（记录 issue）
  3. drivers 非空 : ≥1 条，否则补默认「数据不足，信号待验证」
  4. risks 非空   : ≥1 条，否则补默认「数据不足，信号待验证」
  5. score        : ∈ [0, 100]，越界自动 clamp
  6. asset_class  : ∈ ASSET_CLASSES 白名单，否则拒绝
  7. trend        : ∈ {up, down, sideways}

降级不崩溃是总原则：validate() 永不抛异常，只返回 issue 列表。
"""
from __future__ import annotations

import datetime

from asset_intelligence.protocol import (
    ASSET_CLASSES,
    TRENDS,
    clamp_confidence,
    clamp_score,
)

_REQUIRED = ("asset_class", "symbol", "name", "state", "score", "trend")
_DEFAULT_DRIVER = "数据不足，信号待验证"
_DEFAULT_RISK = "数据不足，信号待验证"


def validate(obj) -> list[str]:
    """校验一个 AssetIntelligence / dict，返回 issue 字符串列表（空 = 通过）。

    只检查、不改值；需要清理请用 validate_and_clean()。
    """
    issues: list[str] = []
    d = obj.to_dict() if hasattr(obj, "to_dict") else dict(obj or {})

    # 1. 字段完整
    for k in _REQUIRED:
        if k not in d or d.get(k) is None or d.get(k) == "":
            issues.append(f"字段缺失/空: {k}")
    # drivers / risks 存在性
    if not isinstance(d.get("drivers"), (list, tuple)) or len(d.get("drivers") or []) == 0:
        issues.append("drivers 为空（需 ≥1 条因果驱动）")
    if not isinstance(d.get("risks"), (list, tuple)) or len(d.get("risks") or []) == 0:
        issues.append("risks 为空（需 ≥1 条失效条件）")

    # 2. confidence 范围
    conf = d.get("confidence")
    try:
        cf = float(conf)
    except (TypeError, ValueError):
        issues.append("confidence 非数值")
    else:
        if cf < 0 or cf > 1:
            issues.append(f"confidence 越界: {conf}（应 ∈ [0,1]，将 clamp）")

    # 5. score 范围
    score = d.get("score")
    try:
        sc = float(score)
    except (TypeError, ValueError):
        issues.append("score 非数值")
    else:
        if sc < 0 or sc > 100:
            issues.append(f"score 越界: {score}（应 ∈ [0,100]，将 clamp）")

    # 6. asset_class 白名单
    if d.get("asset_class") not in ASSET_CLASSES:
        issues.append(f"asset_class 非法: {d.get('asset_class')!r}（不在白名单）")

    # 7. trend 合法
    if d.get("trend") not in TRENDS:
        issues.append(f"trend 非法: {d.get('trend')!r}（应 ∈ {sorted(TRENDS)}）")

    return issues


def validate_and_clean(obj) -> tuple[dict, list[str]]:
    """校验 + 自动清洗（clamp 越界、补默认驱动/风险），返回 (cleaned_dict, issues)。

    返回的是已清理的纯 dict（可由 AssetIntelligence.from_dict 重建），
    即使存在非致命 issue 也尽量产出可用对象，避免下游崩溃。
    """
    d = obj.to_dict() if hasattr(obj, "to_dict") else dict(obj or {})
    issues = validate(d)

    # clamp
    d["score"] = clamp_score(d.get("score", 0.0))
    d["confidence"] = clamp_confidence(d.get("confidence", 0.0))

    # 补默认驱动/风险（非空约束）
    if not (d.get("drivers") or []):
        d["drivers"] = [_DEFAULT_DRIVER]
    if not (d.get("risks") or []):
        d["risks"] = [_DEFAULT_RISK]

    # 未知 trend → sideways（不拒绝，降级修正）
    if d.get("trend") not in TRENDS:
        d["trend"] = "sideways"

    return d, issues


def run_protocol_health(signals: list) -> dict:
    """协议健康检查（Step 5，类 commodity_health）：每天检查整批信号的协议合规。

    返回 JSON 结构（不落库，先经内存/JSON 流动，待 Phase 1.9 决定是否落库）：
      {
        "generated_at": str,
        "overall": "PASS" | "WARN" | "FAIL",
        "n_signals": int,
        "checks": { 检查名: {"pass": int, "fail": int, "ok": bool} },
      }
    """
    checks = {
        "field_completeness": {"pass": 0, "fail": 0},
        "confidence_range": {"pass": 0, "fail": 0},
        "drivers_nonempty": {"pass": 0, "fail": 0},
        "score_range": {"pass": 0, "fail": 0},
        "asset_class_valid": {"pass": 0, "fail": 0},
        "trend_valid": {"pass": 0, "fail": 0},
    }
    for s in (signals or []):
        d = s.to_dict() if hasattr(s, "to_dict") else dict(s or {})
        # field completeness
        if all(d.get(k) not in (None, "") for k in _REQUIRED) and \
           isinstance(d.get("drivers"), (list, tuple)) and (d.get("drivers") or []) and \
           isinstance(d.get("risks"), (list, tuple)) and (d.get("risks") or []):
            checks["field_completeness"]["pass"] += 1
        else:
            checks["field_completeness"]["fail"] += 1
        # confidence range
        try:
            cf = float(d.get("confidence"))
            if 0 <= cf <= 1:
                checks["confidence_range"]["pass"] += 1
            else:
                checks["confidence_range"]["fail"] += 1
        except (TypeError, ValueError):
            checks["confidence_range"]["fail"] += 1
        # drivers nonempty
        if (d.get("drivers") or []):
            checks["drivers_nonempty"]["pass"] += 1
        else:
            checks["drivers_nonempty"]["fail"] += 1
        # score range
        try:
            sc = float(d.get("score"))
            if 0 <= sc <= 100:
                checks["score_range"]["pass"] += 1
            else:
                checks["score_range"]["fail"] += 1
        except (TypeError, ValueError):
            checks["score_range"]["fail"] += 1
        # asset_class valid
        if d.get("asset_class") in ASSET_CLASSES:
            checks["asset_class_valid"]["pass"] += 1
        else:
            checks["asset_class_valid"]["fail"] += 1
        # trend valid
        if d.get("trend") in TRENDS:
            checks["trend_valid"]["pass"] += 1
        else:
            checks["trend_valid"]["fail"] += 1

    for c in checks.values():
        c["ok"] = c["fail"] == 0

    fails = sum(c["fail"] for c in checks.values())
    overall = "PASS" if fails == 0 else ("WARN" if fails <= 2 else "FAIL")

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "overall": overall,
        "n_signals": len(signals or []),
        "checks": checks,
    }
