# -*- coding: utf-8 -*-
"""
asset_intelligence/validation/regime_eval.py —— Regime 状态有效性验证（Phase 1.9-B1 · 问题①）

来源：regime_history（Phase 1.7 已逐日回溯 risk_state + 远期收益）。

回答：不同环境下，市场后续表现如何？—— 即「状态定义是否有决策价值」。
  - Risk Off 是否真意味着风险下降 / 收益更差？
  - Risk On 是否真对应更好表现？

不预测：只统计「过去该状态下，未来 N 日平均收益 / 胜率」。
结论可信度随样本量标注（呼应样本不足风险）。
"""
from __future__ import annotations

from typing import Optional

from db import get_conn


def _r(x: Optional[float]) -> Optional[float]:
    return round(float(x), 2) if x is not None else None


def _reliability(n: int) -> str:
    if n == 0:
        return "无样本"
    if n < 30:
        return "低（样本不足）"
    if n < 100:
        return "中（样本有限）"
    return "较高"


def regime_effectiveness() -> dict:
    """按 risk_state 分组统计远期收益与胜率。"""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT risk_state, COUNT(*),
                   AVG(fwd_5d_a_share), AVG(fwd_20d_a_share),
                   AVG(fwd_5d_gold),   AVG(fwd_20d_gold)
            FROM regime_history
            GROUP BY risk_state
            ORDER BY risk_state
        """)
        groups = cur.fetchall()
    except Exception:
        groups = []
    rows = []
    total = 0
    for r in groups:
        state, n = r[0], int(r[1])
        total += n
        # 胜率：该状态下 A股 20 日收益 > 0 的比例
        try:
            cur2 = conn.cursor()
            cur2.execute(
                "SELECT COUNT(*) FROM regime_history "
                "WHERE risk_state=? AND fwd_20d_a_share IS NOT NULL AND fwd_20d_a_share > 0",
                (state,))
            win = cur2.fetchone()[0]
        except Exception:
            win = 0
        win_rate = round(win / n * 100.0, 1) if n else None
        rows.append({
            "risk_state": state,
            "n": n,
            "a_share_5d": _r(r[2]),
            "a_share_20d": _r(r[3]),
            "gold_5d": _r(r[4]),
            "gold_20d": _r(r[5]),
            "a_share_20d_win_rate": win_rate,
            "reliability": _reliability(n),
        })
    conn.close()
    return {"rows": rows, "total_samples": total}
