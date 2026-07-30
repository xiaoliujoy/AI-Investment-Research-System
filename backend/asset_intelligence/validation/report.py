# -*- coding: utf-8 -*-
"""
asset_intelligence/validation/report.py —— 验证报告生成器（Phase 1.9-B1）

把 regime / signal / confidence 三个验证模块汇总为
`Trading OS Intelligence Validation Report v0.1`：

  - 不预测，只验证「观察体系是否具备统计意义上的决策价值」。
  - 输出 JSON 到 output/dashboard/validation_report.json（暂不落库复杂表）。
  - 每段标注样本量与结论可信度，避免系统产生虚假确定性（样本不足风险）。

后续（B2）再据此做可视化（Regime 时间线 / Score 分布 / 收益箱线 / 命中率）。
"""
from __future__ import annotations

import datetime
import json
import os
import sys

# 允许直接 `python asset_intelligence/validation/report.py` 运行：
# 把 backend 根注入 sys.path（脚本目录会被优先加入，但 backend 不在其中）。
_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from asset_intelligence.validation.regime_eval import regime_effectiveness
from asset_intelligence.validation.signal_eval import signal_ranking_ability
from asset_intelligence.validation.confidence_eval import confidence_calibration
from asset_intelligence.history import history_summary

# backend 根（report.py 位于 backend/asset_intelligence/validation/）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _overall_caveat(regime: dict, signal: dict, conf: dict,
                   hist: dict) -> str:
    parts = []
    if regime.get("total_samples", 0) < 100:
        parts.append("Regime 样本偏少，环境有效性结论可信度有限。")
    # 历史累积状态：区分「已落库」与「可验证」
    n_days = hist.get("n_days", 0)
    recorded = signal.get("recorded_signals", 0) + conf.get("recorded_signals", 0)
    validatable = signal.get("total_signals", 0) + conf.get("total_signals", 0)
    if recorded == 0:
        parts.append(
            "资产认知历史暂无样本（需先累积每日 memo 落库），"
            "信号排序能力与置信度校准暂不可用。")
    else:
        if validatable == 0:
            parts.append(
                f"历史已累积 {n_days} 天、{recorded} 个信号已落库，但可验证样本=0"
                f"（最新信号尚无未来交易日数据，待时间流逝后自动解锁）；"
                f"当前无法验证排序/校准能力。")
        else:
            parts.append(
                f"历史已累积 {n_days} 天、{recorded} 个已落库信号，"
                f"其中 {validatable} 个已有未来收益可验证。")
    parts.append(
        "样本量不足覆盖完整周期前，本报告任何结论仅用于方法验证，"
        "不构成投资规则；Phase 2 Regime Engine 须待验证稳定后启动。")
    return " ".join(parts)


def build_report() -> dict:
    regime = regime_effectiveness()
    signal = signal_ranking_ability()
    conf = confidence_calibration()
    hist = history_summary()
    return {
        "report": "Trading OS Intelligence Validation Report",
        "version": "v0.1",
        "phase": "1.9-B1",
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "不预测，只验证观察体系（Regime / Asset Intelligence / Confidence）"
                 "是否具备统计意义上的决策价值。",
        "history_accumulation": hist,
        "regime_effectiveness": regime,
        "signal_ranking_ability": signal,
        "confidence_calibration": conf,
        "overall_caveat": _overall_caveat(regime, signal, conf, hist),
    }


def write_report(path: str = None) -> str:
    """生成并写入 validation_report.json（默认 output/dashboard/）。"""
    if path is None:
        path = os.path.join(_ROOT, "output", "dashboard", "validation_report.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rep = build_report()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    return path


def render_text(rep: dict = None) -> str:
    """人类可读文本摘要（CLI / 日志用）。"""
    rep = rep or build_report()
    L = [f"{rep['report']} {rep['version']}  ({rep['phase']})",
         f"生成时间：{rep['generated_at']}",
         "=" * 52, ""]
    # 0) 历史累积（Phase 1.9-C 观察落库稳定性）
    h = rep.get("history_accumulation", {})
    L.append(f"[0] 历史累积  已落库天数={h.get('n_days')}  "
             f"总行数={h.get('total_rows')}  "
             f"最新日={h.get('latest_date')}  "
             f"最新日真实信号={h.get('latest_day_enabled_signals')}")
    L.append(f"     已记录信号(待验证+可验证)="
             f"{rep['signal_ranking_ability'].get('recorded_signals', 0) + rep['confidence_calibration'].get('recorded_signals', 0)}；"
             f"当前可验证(有未来收益)={rep['signal_ranking_ability'].get('total_signals', 0) + rep['confidence_calibration'].get('total_signals', 0)}")
    # 1) Regime
    rg = rep["regime_effectiveness"]
    L.append("")
    L.append(f"[1] Regime 状态有效性  总样本={rg['total_samples']}")
    for r in rg["rows"]:
        L.append(f"  {r['risk_state']:<9} n={r['n']:<4} "
                 f"A股20d={r['a_share_20d']} 胜率={r['a_share_20d_win_rate']}% "
                 f"黄金20d={r['gold_20d']} [{r['reliability']}]")
    # 2) Signal
    sg = rep["signal_ranking_ability"]
    L.append("")
    L.append(f"[2] Score 排序能力  可验证信号数={sg['total_signals']}  "
             f"(已记录={sg['recorded_signals']})")
    for t in sg["tiers"]:
        L.append(f"  {t['tier']:<7} n={t['n']:<4} "
                 f"20d收益={t['avg_ret_20d']} 胜率={t['win_rate_20d']}% "
                 f"最大回撤={t['avg_max_dd_20d']} [{t['reliability']}]")
    # 3) Confidence
    cf = rep["confidence_calibration"]
    L.append("")
    L.append(f"[3] Confidence 校准  可验证信号数={cf['total_signals']}  "
             f"(已记录={cf['recorded_signals']})")
    for l in cf["levels"]:
        L.append(f"  {l['confidence']:<7} n={l['n']:<4} "
                 f"20d收益={l['avg_ret_20d']} 正确率={l['correct_rate_20d']}% "
                 f"[{l['reliability']}]")
    diag = cf.get("diagnosis", {})
    if diag:
        L.append(f"  诊断：{diag.get('status')} (gap={diag.get('gap_high_minus_low')})")
    # caveat
    L.append("")
    L.append("结论可信度提示：")
    L.append(f"  {rep['overall_caveat']}")
    return "\n".join(L)


if __name__ == "__main__":
    path = write_report()
    print(render_text())
    print(f"\n✅ 报告已写入：{path}")
