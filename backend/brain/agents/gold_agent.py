#!/usr/bin/env python3
"""Gold Agent — bridges Gold Decision Engine into the Brain orchestration system.

Follows the same Agent contract as other brain agents:
  run(ctx) → AgentResult → ctx.put("GOLD")

Location in orchestrator chain: after L1 (Global Macro), before L2 (China Macro).
Gold signals feed into L1 global macro calibration.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACK = Path(__file__).resolve().parent.parent.parent
if str(BACK) not in sys.path:
    sys.path.insert(0, str(BACK))

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime

from brain.agents.base_agent import make_result, AgentResult


@dataclass
class GoldMemo:
    """Complete gold decision memo — 6 sections + 1 sentence."""
    timestamp: str
    one_liner: str              # ① 今日黄金一句话
    market_trading: str          # ② 市场交易什么
    reasoning: str               # ③ 推理链
    current_cycle: str           # ④ 当前周期
    catalysts: str               # ⑤ 未来一周催化剂
    action: str                  # ⑥ 操作建议
    composite_score: float = 0.0
    direction: str = ""
    data_gaps: list = field(default_factory=list)


def run(ctx):
    """Gold Agent entry point. Called by brain orchestrator.
    
    Args:
        ctx: ReasoningContext from brain.context
    
    Returns:
        AgentResult with gold memo in raw field
    """
    try:
        from gold_engine.data_adapter.gold_data import get_gold_factors_cached
        from gold_engine.scoring.drive_scorer import score_drive_factors
        from gold_engine.narrative.detector import detect_narrative
        from gold_engine.cycle.state_machine import detect_cycle
        from gold_engine.reasoning.chain import build_reasoning_chain
        from gold_engine.plan.trading_plan import generate_plan
        from gold_engine.risk.radar import scan_risks
    except ImportError as e:
        res = make_result(
            "GOLD", "黄金决策引擎",
            "neutral", 
            "【黄金引擎】模块导入失败，跳过黄金分析",
            raw={"error": str(e)},
            confidence=0,
            gaps=["gold_engine_import_failed"],
        )
        ctx.put("GOLD", res.to_dict())
        return res
    
    try:
        # Step 1: Collect data
        gf = get_gold_factors_cached()
        
        # Step 2: Score factors (L1)
        ds = score_drive_factors(gf)
        
        # Step 3: Detect narrative (L2)
        narrative = detect_narrative(ds)
        
        # Step 4: Detect cycle (L3)
        cycle = detect_cycle(ds, gf)
        
        # Step 5: Build reasoning chain (L4)
        reasoning = build_reasoning_chain(ds, gf, narrative)
        
        # Step 6: Generate trading plan (L5)
        plan = generate_plan(ds, narrative, cycle)
        
        # Step 7: Scan risks (L6)
        radar = scan_risks()
        
        # Build gold memo
        memo = GoldMemo(
            timestamp=gf.timestamp,
            one_liner=_build_one_liner(gf, ds, narrative),
            market_trading=narrative.narrative_text,
            reasoning=_format_reasoning(reasoning),
            current_cycle=_format_cycle(cycle, ds),
            catalysts=_format_radar(radar),
            action=_format_action(plan, cycle),
            composite_score=ds.composite_score,
            direction=ds.direction,
            data_gaps=gf.gaps,
        )
        
        # Determine stage for brain
        if ds.composite_score >= 65:
            stage = "bullish"
        elif ds.composite_score >= 45:
            stage = "neutral"
        else:
            stage = "bearish"
        
        # Build agent result
        narrative_text = (
            f"【黄金：{cycle.phase_name_cn} | 评分{ds.composite_score:.0f} | {plan.signal_level}】\n"
            f"{memo.one_liner}"
        )
        
        res = make_result(
            "GOLD", "黄金决策引擎",
            stage,
            narrative_text,
            raw={
                "gold_memo": asdict(memo),
                "drive_score": asdict(ds),
                "narrative": asdict(narrative),
                "cycle": asdict(cycle),
                "reasoning": asdict(reasoning),
                "plan": asdict(plan),
                "radar": asdict(radar),
                "factors": asdict(gf),
            },
            signal={"direction": stage, "composite": ds.composite_score, "phase": cycle.current_phase},
            confidence=ds.confidence,
            risk_note=f"数据缺口: {', '.join(gf.gaps)}" if gf.gaps else "",
            gaps=gf.gaps,
            upstream=f"（源头：金价${gf.gold_price:.0f}/DXY{gf.dxy:.2f}/实际利率{gf.tips_10y_yield or '?'}%）",
        )
        
        ctx.put("GOLD", res.to_dict())
        
        # Write gold report files
        _write_reports(memo, ds, narrative, cycle, reasoning, plan, radar, gf)
        
        return res
        
    except Exception as e:
        res = make_result(
            "GOLD", "黄金决策引擎",
            "neutral",
            f"【黄金引擎】运行异常: {e}",
            raw={"error": str(e)},
            confidence=0,
            gaps=["gold_engine_runtime_error"],
        )
        ctx.put("GOLD", res.to_dict())
        return res


def _build_one_liner(gf, ds, narrative) -> str:
    """Build a single-sentence gold summary."""
    direction_map = {
        "bullish": "看涨",
        "neutral_bullish": "偏多",
        "neutral": "中性震荡",
        "neutral_bearish": "偏空",
        "bearish": "看跌",
    }
    dir_cn = direction_map.get(ds.direction, "信号不明")
    
    if gf.gold_price > 0:
        price_str = f"${gf.gold_price:.0f} ({gf.gold_change_pct:+.1f}%)"
    else:
        price_str = "价格数据缺失"
    
    return (
        f"黄金{price_str}，综合评分{ds.composite_score:.0f}/{dir_cn}。"
        f"今日交易主题：{narrative.primary_theme}。{ds.summary}"
    )


def _format_reasoning(reasoning) -> str:
    """Format reasoning chain as text."""
    if not reasoning.chain:
        return "推理链暂无数据"
    
    lines = []
    for i, link in enumerate(reasoning.chain):
        marker = "⚠️" if not link.has_data else "↓"
        lines.append(f"  {link.from_event}")
        lines.append(f"  {marker} {link.to_event} [{link.confidence:.0f}%]")
    
    lines.append(f"\n  综合可信度: {reasoning.overall_confidence:.0f}%")
    return "\n".join(lines)


def _format_cycle(cycle, ds) -> str:
    """Format cycle state as text."""
    lines = [
        f"当前: {cycle.phase_name_cn}",
        f"建议: {cycle.suggested_action}",
        f"信号: {', '.join(cycle.signals[:4])}",
        f"置信度: {cycle.confidence:.0f}%",
    ]
    return "\n".join(lines)


def _format_radar(radar) -> str:
    """Format risk radar as text."""
    lines = [radar.summary, "", "本周风险事件:"]
    for event in radar.current_week_events[:5]:
        stars = "★" * event.stars + "☆" * (5 - event.stars)
        lines.append(f"  {stars} {event.name}: {event.note}")
    lines.append("")
    if radar.next_week_events:
        lines.append("下周关注:")
        for event in radar.next_week_events[:3]:
            stars = "★" * event.stars + "☆" * (5 - event.stars)
            lines.append(f"  {stars} {event.name}")
    return "\n".join(lines)


def _format_action(plan, cycle) -> str:
    """Format action recommendation as text."""
    lines = [
        plan.summary,
        "",
        f"仓位建议: {plan.position_guidance}",
        "",
        "条件规则:",
    ]
    for rule in plan.conditions:
        lines.append(f"  [{rule.priority}] 如果 {rule.condition}")
        lines.append(f"       → {rule.action}")
    
    return "\n".join(lines)


def _write_reports(memo, ds, narrative, cycle, reasoning, plan, radar, gf):
    """Write gold report JSON and HTML to output directory."""
    output_dir = BACK / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON report
    report = {
        "generated_at": memo.timestamp,
        "gold_price": gf.gold_price,
        "gold_change_pct": gf.gold_change_pct,
        "memo": asdict(memo),
        "drive_score": asdict(ds),
        "narrative": asdict(narrative),
        "cycle": asdict(cycle),
        "reasoning": asdict(reasoning),
        "plan": asdict(plan),
        "radar": asdict(radar),
        "factors": asdict(gf),
    }
    
    json_path = output_dir / "gold_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    
    # HTML report
    html = _render_html(memo, ds, narrative, cycle, reasoning, plan, radar, gf)
    html_path = output_dir / "gold_report.html"
    html_path.write_text(html, encoding="utf-8")


def _render_html(memo, ds, narrative, cycle, reasoning, plan, radar, gf) -> str:
    """Render gold report as HTML."""
    signal_colors = {
        "bullish": "#d32f2f", "neutral_bullish": "#e64a19",
        "neutral": "#888", "neutral_bearish": "#1976d2",
        "bearish": "#388e3c",
    }
    signal_cn = {
        "bullish": "看涨", "neutral_bullish": "偏多",
        "neutral": "中性", "neutral_bearish": "偏空",
        "bearish": "看跌",
    }
    
    color = signal_colors.get(ds.direction, "#888")
    dir_cn = signal_cn.get(ds.direction, "中性")
    
    # Factor table rows
    factor_rows = ""
    for f in ds.factors:
        f_color = "#d32f2f" if "bull" in f.direction else ("#388e3c" if "bear" in f.direction else "#888")
        f_dir = "看涨" if "bull" in f.direction else ("看跌" if "bear" in f.direction else "中性")
        factor_rows += f"""
        <tr>
          <td>{'★'*f.weight}{'☆'*(5-f.weight)}</td>
          <td>{f.name}</td>
          <td style="color:{f_color}">{f_dir}</td>
          <td>{f.score:.0f}</td>
          <td>{f.value}</td>
          <td style="font-size:11px;color:#666">{f.note}</td>
        </tr>"""
    
    # Event table rows
    event_rows = ""
    for e in radar.current_week_events[:5]:
        event_rows += f"""
        <tr>
          <td>{'★'*e.stars}{'☆'*(5-e.stars)}</td>
          <td>{e.name}</td>
          <td>{e.date}</td>
          <td>{e.impact_direction}</td>
          <td style="font-size:11px">{e.note}</td>
        </tr>"""
    
    # Chain rows
    chain_rows = ""
    for link in reasoning.chain:
        has = "✅" if link.has_data else "⚠️"
        chain_rows += f"""
        <tr>
          <td>{link.from_event}</td>
          <td style="font-size:18px">→</td>
          <td>{link.to_event}</td>
          <td style="color:{'#d32f2f' if link.confidence < 50 else '#2e7d32'}">{link.confidence:.0f}%</td>
          <td>{has}</td>
        </tr>"""
    
    # Conditions
    cond_rows = ""
    for rule in plan.conditions:
        priority_color = {"A": "#d32f2f", "B": "#e65100", "C": "#1976d2"}.get(rule.priority, "#888")
        cond_rows += f"""
        <tr>
          <td style="color:{priority_color};font-weight:bold">{rule.priority}级</td>
          <td>{rule.condition}</td>
          <td>{rule.action}</td>
        </tr>"""
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold Decision Engine - {datetime.now().strftime('%Y-%m-%d')}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8f9fa;color:#333;line-height:1.6;padding:20px;max-width:900px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#ffd700;padding:24px;border-radius:12px;margin-bottom:20px}}
.header h1{{font-size:22px;font-weight:500}}
.header .price{{font-size:36px;font-weight:500;margin:8px 0}}
.header .sub{{font-size:14px;opacity:.8}}
.card{{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card h2{{font-size:16px;font-weight:500;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #ffd700}}
.score-badge{{display:inline-block;padding:6px 16px;border-radius:20px;font-size:20px;font-weight:500;color:#fff;background:{color}}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f5f5f5;font-weight:500;font-size:12px;color:#666}}
.note{{font-size:12px;color:#999;margin-top:8px}}
.gaps{{font-size:11px;color:#e65100;margin-top:4px}}
</style>
</head>
<body>
<div class="header">
  <h1>Gold Decision Engine</h1>
  <div class="price">${gf.gold_price:.0f} <span style="font-size:16px;color:{'#d32f2f' if gf.gold_change_pct >= 0 else '#388e3c'}">{gf.gold_change_pct:+.1f}%</span></div>
  <div class="sub">DXY {gf.dxy:.2f} | 10Y {gf.us_10y_yield:.2f}% | GLD ${gf.gld_price:.0f}</div>
</div>

<div class="card">
  <h2>① 今日黄金一句话</h2>
  <p style="font-size:15px;font-weight:500">{memo.one_liner}</p>
  <div style="margin-top:12px">
    <span class="score-badge">{ds.composite_score:.0f} · {dir_cn}</span>
    <span style="margin-left:12px;color:#666;font-size:13px">置信度 {ds.confidence:.0f}%</span>
  </div>
</div>

<div class="card">
  <h2>② 市场在交易什么？</h2>
  <pre style="font-size:13px;white-space:pre-wrap;font-family:inherit;line-height:1.8">{memo.market_trading}</pre>
</div>

<div class="card">
  <h2>③ 因果推理链</h2>
  <pre style="font-size:13px;white-space:pre-wrap;font-family:inherit;line-height:1.8">{memo.reasoning}</pre>
</div>

<div class="card">
  <h2>④ 黄金周期</h2>
  <pre style="font-size:13px;white-space:pre-wrap;font-family:inherit;line-height:1.8">{memo.current_cycle}</pre>
</div>

<div class="card">
  <h2>⑤ 风险雷达</h2>
  <pre style="font-size:13px;white-space:pre-wrap;font-family:inherit;line-height:1.8">{memo.catalysts}</pre>
</div>

<div class="card">
  <h2>⑥ 操作建议</h2>
  <pre style="font-size:13px;white-space:pre-wrap;font-family:inherit;line-height:1.8">{memo.action}</pre>
</div>

<div class="card">
  <h2>驱动因子明细</h2>
  <table>
    <tr><th>权重</th><th>因子</th><th>方向</th><th>评分</th><th>数值</th><th>注释</th></tr>
    {factor_rows}
  </table>
  <div class="note">评分基于8因子加权模型，方向=因子对黄金的影响方向</div>
  {'<div class="gaps">⚠️ 数据缺口: ' + ', '.join(gf.gaps) + '</div>' if gf.gaps else ''}
</div>

<div class="card">
  <h2>本周风险事件</h2>
  <table>
    <tr><th>重要性</th><th>事件</th><th>日期</th><th>方向</th><th>说明</th></tr>
    {event_rows}
  </table>
</div>

<div class="card" style="font-size:12px;color:#999">
  <p>黄金决策引擎 v1.0 | 数据源: thsdk(GLD/DXY/XAU) + akshare(美债/Fed) + neodata(WGC/TIPS)</p>
  <p>本报告为AI辅助分析，不构成投资建议。买卖决策由用户自行判断。</p>
</div>
</body>
</html>"""
