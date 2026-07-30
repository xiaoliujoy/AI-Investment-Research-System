# -*- coding: utf-8 -*-
"""
asset_intelligence/asset_intelligence_health.py —— AIP 协议健康检查（Phase 1.8 Step 5）

每天检查整批 AssetIntelligence 信号的协议合规，类似 commodity_health，但：
  - 不新增数据库表（Phase 1.8 边界）；结果先以 JSON / 内存对象流动，
    待 Phase 1.9 Backtest Dashboard 时再决定是否统一落库。
  - 检查项（呼应 _DB_PATH 可靠性教训，防黑盒 / 空输出 / 污染）：
      field_completeness  字段完整（防空输出）
      confidence_range    confidence ∈ [0,1]
      drivers_nonempty    drivers 非空（防黑盒）
      score_range         score ∈ [0,100]
      asset_class_valid   asset_class 合法（防污染）
      trend_valid         trend ∈ {up,down,sideways}

用法：
  from asset_intelligence.asset_intelligence_health import run_protocol_health, format_health
  rep = run_protocol_health(signals)
  print(format_health(rep))
"""
from __future__ import annotations

from asset_intelligence.validator import run_protocol_health as _run


def run_protocol_health(signals: list) -> dict:
    """委托 validator 的整批检查（此处作为协议健康模块的对外入口）。"""
    return _run(signals)


def format_health(report: dict) -> str:
    """把协议健康检查报告格式化为可读文本。"""
    overall = report.get("overall", "UNKNOWN")
    n = report.get("n_signals", 0)
    lines = [f"协议健康: {overall}（{n} 个信号）"]
    for name, c in (report.get("checks", {}) or {}).items():
        mark = "✅" if c.get("ok") else "⚠️"
        lines.append(f"  {mark} {name}: 通过{c.get('pass',0)} / 失败{c.get('fail',0)}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 自测：构造一批混合信号
    from asset_intelligence.protocol import make_cash_hold, make_skeleton
    sigs = [
        make_cash_hold(),
        make_skeleton("bond", "US10Y", "美债10Y"),
        make_skeleton("fx", "DXY", "美元指数"),
    ]
    rep = run_protocol_health(sigs)
    print(format_health(rep))
