# -*- coding: utf-8 -*-
"""
置信度：启发式聚合（非黑箱模型，符合用户"系统要透明"的要求）。

- 每层 Agent 自行给出 0-100 置信度（基于数据覆盖度 + 信号清晰度）。
- 总置信度 = 各层加权聚合 × 冲突惩罚系数。
- 越接近"最后一公里决策"的层权重越高（L4/L5/L7/sentiment 是定方向与定仓的关键）。
"""
from .context import ReasoningContext  # noqa

# 各层在最终决策中的权重
WEIGHTS = {
    "L4": 0.18, "L7": 0.16, "L5": 0.14, "sentiment": 0.14,
    "FLOW": 0.12, "L1": 0.10, "L3": 0.10, "GOLD": 0.10, "L2": 0.08, "fundamental": 0.06,
    "L6": 0.02, "L8": 0.02,
}


def coverage_conf(gaps, max_ok=2, full=90):
    """数据覆盖度 → 置信度：缺口越多越低。"""
    n = len(gaps or [])
    if n == 0:
        return full
    if n <= max_ok:
        return max(55, full - n * 12)
    return max(30, full - n * 18)


def aggregate_overall(results, conflicts):
    num, den = 0.0, 0.0
    for layer, w in WEIGHTS.items():
        r = results.get(layer)
        if not r:
            continue
        c = r.get("confidence")
        if c is None:
            continue
        num += c * w
        den += w
    base = round(num / den) if den else 0
    # 冲突惩罚：高严重度重罚，暴露"层间打架"会显著拉低总置信度
    penalty = 1.0
    for cf in conflicts:
        if cf.get("severity") == "HIGH":
            penalty -= 0.12
        elif cf.get("severity") == "MEDIUM":
            penalty -= 0.06
    penalty = max(0.6, round(penalty, 2))
    overall = max(0, min(100, round(base * penalty)))
    return {"overall": overall, "base": base, "penalty": penalty}
