# -*- coding: utf-8 -*-
"""
asset_intelligence/validation/returns.py —— 前向收益引擎（Phase 1.9-B1 共享）

为 signal_eval / confidence_eval 提供「信号日 → 未来 N 日收益 / 最大回撤」的计算。
数据来源（只读，不新增表）：

  - 商品（AU0/CU0/SC0）：commodity_daily.close（真实价格序列）
  - A股聚合（CN_EQ_ALL）：stock_daily 每日全市场均值涨跌% → 累乘净值序列
    （与 regime_history 中 a_share 远期收益的口径一致）

设计边界：
  - 不预测：本模块只做「已发生收益的回看统计」，供验证层消费。
  - 现金(CASH)与空壳(skeleton)不参与（由调用方按 symbol / enabled 过滤）。
  - 信号日若处于序列末端（不足 horizon 步）→ 返回 None，绝不外推。
"""
from __future__ import annotations

from typing import Optional

from db import get_conn

# 需要前向收益的商品标的（与 commodity_factor_daily / universe 口径一致）
_COMM_SYMBOLS = ("AU0", "CU0", "SC0")


def load_price_series(need_a_share: bool = False,
                       date_min: Optional[str] = None,
                       date_max: str = None) -> dict:
    """返回 {symbol: (sorted_dates, values)}。

    values 对商品 = close；对 CN_EQ_ALL = 由每日均值涨跌% 累乘的净值（起点 1.0）。

    性能与健壮性（生产教训）：
      - 商品序列仅 3 万行，全量加载成本低。
      - A股聚合（CN_EQ_ALL）来自 2335 万行的 stock_daily：绝不全表 GROUP BY。
        仅当 need_a_share=True 且给定日期区间时才做「区间受限」聚合，
        否则跳过（当前资产认知历史多为商品信号，A股序列常不需要）。
    """
    conn = get_conn()
    cur = conn.cursor()
    series: dict[str, tuple[list[str], list[float]]] = {}

    # 1) 商品真实价格（防御：表缺失时跳过，不影响其他序列）
    for sym in _COMM_SYMBOLS:
        try:
            cur.execute(
                "SELECT date, close FROM commodity_daily WHERE symbol=? ORDER BY date", (sym,))
            rows = cur.fetchall()
        except Exception:
            rows = []
        if rows:
            series[sym] = ([r[0] for r in rows], [float(r[1]) for r in rows])

    # 2) A股聚合净值（CN_EQ_ALL 的远期收益代理）—— 区间受限，避免全表扫描
    if need_a_share:
        try:
            if date_min and date_max:
                cur.execute(
                    "SELECT date, AVG(change_pct) FROM stock_daily "
                    "WHERE date BETWEEN ? AND ? GROUP BY date ORDER BY date",
                    (date_min, date_max))
            else:
                # 无区间线索时不扫全表（代价过高），直接跳过 A股序列
                cur.execute("SELECT 1")
            ash = cur.fetchall()
        except Exception:
            ash = []
        if ash and ash != [(1,)]:
            dates, vals, nav = [], [], 1.0
            for d, m in ash:
                if m is None:
                    continue
                nav *= (1.0 + float(m) / 100.0)
                dates.append(d)
                vals.append(nav)
            if dates:
                series["CN_EQ_ALL"] = (dates, vals)

    conn.close()
    return series


def fwd_metrics(series: dict, symbol: str, date: str,
                horizon: int = 5) -> Optional[tuple[float, float]]:
    """信号日 symbol/date 的后 horizon 步指标 → (fwd_return_pct, max_drawdown_pct)。

    定位规则：取序列中 <= date 的最近点作为起点；不足 horizon 步 → None。
    """
    if symbol not in series:
        return None
    dates, vals = series[symbol]
    idx = None
    for i, d in enumerate(dates):
        if d <= date:
            idx = i
        else:
            break
    if idx is None or idx + horizon >= len(dates):
        return None
    c0 = vals[idx]
    if not c0:
        return None
    c1 = vals[idx + horizon]
    ret = (c1 / c0 - 1.0) * 100.0
    window = vals[idx: idx + horizon + 1]
    peak = max(window)
    dd = (min(window) / peak - 1.0) * 100.0 if peak else 0.0
    return (ret, dd)
