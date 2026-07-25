# -*- coding: utf-8 -*-
"""Flow Agent - Capital Flow Engine brain integration.

Inserts as L0 Global Flow in the orchestrator, before L1 Global Macro.
Collects commodity + ETF + institution data, answers 5 questions,
produces Flow Score, and feeds signals back to the brain.

Contract: run(ctx) -> AgentResult -> ctx.put("FLOW")
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from dataclasses import asdict
from datetime import datetime

BACK = Path(__file__).resolve().parent.parent.parent
if str(BACK) not in sys.path:
    sys.path.insert(0, str(BACK))

from brain.agents.base_agent import make_result, AgentResult


def run(ctx):
    """Flow Agent entry point. Called by brain orchestrator."""
    try:
        from capital_flow.data_adapter.commodity_data import get_commodity_snapshot
        from capital_flow.data_adapter.etf_data import get_etf_flow
        from capital_flow.data_adapter.institution_data import get_institution_flow
        from capital_flow.scoring.flow_scorer import calc_flow_score
        from capital_flow.intelligence.five_questions import answer_five_questions
    except ImportError as e:
        res = make_result(
            "FLOW", "资金情报中心",
            "neutral",
            "【资金引擎】模块导入失败",
            raw={"error": str(e)},
            confidence=0,
            gaps=["flow_engine_import_failed"],
        )
        ctx.put("FLOW", res.to_dict())
        return res

    try:
        # Step 1: Commodity data
        commodity = get_commodity_snapshot()

        # Step 2: ETF fund flow
        etf_flow = get_etf_flow()

        # Step 3: Institution flow (depends on ETF for national team)
        institution = get_institution_flow(etf_snap=etf_flow)

        # Step 4: Gold data from existing gold_engine (if available)
        gold_data = None
        gold_ctx = ctx.get("GOLD")
        if gold_ctx:
            gold_raw = gold_ctx.get("raw") or {}
            gold_factors = gold_raw.get("factors") or {}
            gold_data = {
                "dxy": gold_factors.get("dxy", 0),
                "us_10y_yield": gold_factors.get("us_10y_yield", 0),
                "tips_10y_yield": gold_factors.get("tips_10y_yield", 0),
                "gold_price": gold_factors.get("gold_price", 0),
            }

        # Step 5: Flow Score
        flow_score = calc_flow_score(
            commodity_snap=commodity,
            etf_snap=etf_flow,
            institution_flow=institution,
            gold_data=gold_data,
        )

        # Step 6: Five Questions
        intelligence = answer_five_questions(
            commodity_snap=commodity,
            etf_snap=etf_flow,
            institution_flow=institution,
            gold_data=gold_data,
        )

        # Determine direction for brain
        if flow_score.overall >= 65:
            direction = "bullish"
        elif flow_score.overall >= 45:
            direction = "neutral"
        else:
            direction = "bearish"

        # Build narrative
        narrative_text = (
            "【资金情报 | Flow Score %d/100】\n"
            "%s\n\n"
            "Q1 全球: %s\n"
            "Q3 ETF: %s"
        ) % (flow_score.overall, intelligence.one_liner,
             intelligence.q1_global[:60], intelligence.q3_etf[:60])

        # Build raw data
        raw = {
            "intelligence": asdict(intelligence),
            "flow_score": asdict(flow_score),
            "commodity": asdict(commodity),
            "etf_flow": asdict(etf_flow),
            "institution": asdict(institution),
        }

        # Gaps
        gaps = list(set(
            (commodity.gaps or []) + (etf_flow.gaps or []) + (institution.gaps or [])
        ))

        # Confidence based on data coverage
        confidence = 80
        if "no_prev_shares" in gaps:
            confidence -= 15  # lower confidence without ETF share comparison
        if "china_futures_closed" in gaps:
            confidence -= 5
        if len(gaps) > 3:
            confidence -= 10

        res = make_result(
            "FLOW", "资金情报中心",
            direction,
            narrative_text,
            raw=raw,
            signal={
                "direction": direction,
                "flow_score": flow_score.overall,
                "risk_appetite": commodity.risk_appetite,
                "etf_inflow_count": len([e for e in etf_flow.top_inflow if e.shares_change > 0]) if etf_flow.top_inflow else 0,
            },
            confidence=confidence,
            risk_note="数据缺口: %s" % ", ".join(gaps) if gaps else "",
            gaps=gaps,
            upstream="（源头：商品%d只/ETF%d只/南向%.0f亿）" % (
                len(commodity.all_items), 
                len(etf_flow.broad) + len(etf_flow.industry) + len(etf_flow.theme) + len(etf_flow.gold) + len(etf_flow.overseas),
                institution.hsgt.south_net,
            ),
        )

        ctx.put("FLOW", res.to_dict())

        # Write reports
        _write_reports(intelligence, flow_score, commodity, etf_flow, institution)

        return res

    except Exception as e:
        import traceback
        res = make_result(
            "FLOW", "资金情报中心",
            "neutral",
            "【资金引擎】运行异常: %s" % e,
            raw={"error": str(e), "trace": traceback.format_exc()[-200:]},
            confidence=0,
            gaps=["flow_engine_runtime_error"],
        )
        ctx.put("FLOW", res.to_dict())
        return res


def _write_reports(intelligence, flow_score, commodity, etf_flow, institution):
    """Write JSON and HTML reports."""
    output_dir = BACK / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    report = {
        "generated_at": intelligence.timestamp,
        "intelligence": asdict(intelligence),
        "flow_score": asdict(flow_score),
        "commodity": asdict(commodity),
        "etf_flow_summary": {
            "broad_count": len(etf_flow.broad),
            "industry_count": len(etf_flow.industry),
            "theme_count": len(etf_flow.theme),
            "gold_count": len(etf_flow.gold),
            "overseas_count": len(etf_flow.overseas),
            "top_inflow": [asdict(e) for e in etf_flow.top_inflow[:5]],
            "top_outflow": [asdict(e) for e in etf_flow.top_outflow[:5]],
            "broad_flow_summary": etf_flow.broad_flow_summary,
            "total_main_inflow": etf_flow.total_main_inflow,
            "gaps": etf_flow.gaps,
        },
        "institution": asdict(institution),
    }
    json_path = output_dir / "flow_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # HTML
    html = _render_html(intelligence, flow_score, commodity, etf_flow, institution)
    html_path = output_dir / "flow_report.html"
    html_path.write_text(html, encoding="utf-8")


def _render_html(intelligence, flow_score, commodity, etf_flow, institution) -> str:
    """Render flow report as HTML."""
    # Score badge color
    score = flow_score.overall
    if score >= 70:
        badge_color = "#d32f2f"  # red = bullish (Chinese convention)
    elif score >= 50:
        badge_color = "#888"
    else:
        badge_color = "#388e3c"  # green = bearish

    stars = chr(9733) * flow_score.overall_stars + chr(9734) * (5 - flow_score.overall_stars)

    # Flow score layers
    score_rows = ""
    for layer in [flow_score.m1_global, flow_score.m2_cross_asset, flow_score.m3_etf, flow_score.m4_sector, flow_score.m5_individual]:
        l_stars = chr(9733) * layer.stars + chr(9734) * (5 - layer.stars)
        l_color = "#d32f2f" if layer.score >= 65 else ("#388e3c" if layer.score < 40 else "#888")
        dir_cn = "流入" if layer.direction == "inflow" else ("流出" if layer.direction == "outflow" else "中性")
        score_rows += """
        <tr>
          <td>%s</td><td>%s</td>
          <td style="color:%s;font-weight:bold">%s</td>
          <td>%s</td>
          <td>%s</td>
          <td style="font-size:11px;color:#666">%s</td>
        </tr>""" % (layer.name, layer.name_cn, l_color, layer.score, l_stars, dir_cn, layer.detail)

    # Commodity table
    comm_rows = ""
    for item in commodity.all_items:
        c_color = "#d32f2f" if item.change_pct > 0 else "#388e3c"
        comm_rows += """
        <tr>
          <td>%s</td><td>%s</td>
          <td style="color:%s">%+.2f%%</td>
          <td>%.2f</td>
          <td style="font-size:11px;color:#666">%s</td>
        </tr>""" % (item.category, item.name_cn, c_color, item.change_pct, item.price, item.a_share_link)

    # ETF top inflow
    etf_inflow_rows = ""
    for e in etf_flow.top_inflow[:8]:
        change_str = "+%.0f万份" % (e.shares_change / 1e4) if e.shares_change != 0 else "N/A"
        etf_inflow_rows += """
        <tr>
          <td>%s</td><td>%s</td>
          <td style="color:#d32f2f">%s</td>
          <td>%.2f</td><td>%.1f亿</td>
        </tr>""" % (e.code, e.name[:14], change_str, e.price, e.amount / 1e8)

    # ETF top outflow
    etf_outflow_rows = ""
    for e in etf_flow.top_outflow[:5]:
        change_str = "%.0f万份" % (e.shares_change / 1e4) if e.shares_change != 0 else "N/A"
        etf_outflow_rows += """
        <tr>
          <td>%s</td><td>%s</td>
          <td style="color:#388e3c">%s</td>
          <td>%.2f</td><td>%.1f亿</td>
        </tr>""" % (e.code, e.name[:14], change_str, e.price, e.amount / 1e8)

    # Institution
    inst_lines = ""
    if institution.hsgt.south_net != 0:
        inst_lines += "<p>南向资金净流入: <b>%.0f亿元</b></p>" % institution.hsgt.south_net
    if institution.national_team:
        for nt in institution.national_team:
            color = "#d32f2f" if nt.action == "增持" else "#388e3c"
            inst_lines += '<p>国家队<span style="color:%s;font-weight:bold">%s</span> %s (%.0f万份)</p>' % (
                color, nt.action, nt.etf_name[:8], nt.shares_change / 1e4)

    gaps_str = ", ".join(set(
        (commodity.gaps or []) + (etf_flow.gaps or []) + (institution.gaps or [])
    )) or "无"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Capital Flow Intelligence - {datetime.now().strftime('%Y-%m-%d')}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8f9fa;color:#333;line-height:1.7;padding:20px;max-width:1000px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#0d47a1,#1565c0);color:#fff;padding:24px;border-radius:12px;margin-bottom:20px}}
.header h1{{font-size:22px;font-weight:500}}
.header .score{{font-size:36px;font-weight:500;margin:8px 0}}
.header .stars{{font-size:20px;color:#ffd700}}
.card{{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card h2{{font-size:16px;font-weight:500;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #1565c0}}
.q-card{{background:#fff;border-radius:12px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);border-left:4px solid #1565c0}}
.q-card h3{{font-size:14px;color:#1565c0;margin-bottom:8px}}
.q-card pre{{font-size:13px;white-space:pre-wrap;font-family:inherit;line-height:1.8}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f5f5f5;font-weight:500;font-size:12px;color:#666}}
.badge{{display:inline-block;padding:6px 16px;border-radius:20px;font-size:20px;font-weight:500;color:#fff;background:{badge_color}}}
.note{{font-size:12px;color:#999;margin-top:8px}}
.gaps{{font-size:11px;color:#e65100;margin-top:4px}}
</style>
</head>
<body>
<div class="header">
  <h1>Capital Flow Intelligence</h1>
  <div class="score">{score} <span style="font-size:16px">/ 100</span></div>
  <div class="stars">{stars}</div>
  <div style="font-size:14px;opacity:.9;margin-top:8px">{intelligence.one_liner}</div>
</div>

<div class="card">
  <h2>Flow Score (5-Layer Capital Flow)</h2>
  <table>
    <tr><th>层级</th><th>名称</th><th>评分</th><th>星级</th><th>方向</th><th>详情</th></tr>
    {score_rows}
  </table>
</div>

<div class="q-card">
  <h3>Q1: 今天全球资金流向哪里？</h3>
  <pre>{intelligence.q1_global}</pre>
</div>

<div class="q-card">
  <h3>Q2: 今天中国资金流向哪里？</h3>
  <pre>{intelligence.q2_china}</pre>
</div>

<div class="q-card">
  <h3>Q3: ETF资金在买什么？</h3>
  <pre>{intelligence.q3_etf}</pre>
</div>

<div class="q-card">
  <h3>Q4: 商品市场在交易什么？</h3>
  <pre>{intelligence.q4_commodity}</pre>
</div>

<div class="q-card">
  <h3>Q5: 这些资金流向会如何影响A股？</h3>
  <pre>{intelligence.q5_a_share}</pre>
</div>

<div class="card">
  <h2>商品期货行情</h2>
  <table>
    <tr><th>类别</th><th>品种</th><th>涨跌幅</th><th>价格</th><th>A股关联</th></tr>
    {comm_rows}
  </table>
</div>

<div class="card">
  <h2>ETF净申购TOP</h2>
  <table>
    <tr><th>代码</th><th>名称</th><th>份额变化</th><th>价格</th><th>成交额</th></tr>
    {etf_inflow_rows}
  </table>
</div>

<div class="card">
  <h2>ETF净赎回TOP</h2>
  <table>
    <tr><th>代码</th><th>名称</th><th>份额变化</th><th>价格</th><th>成交额</th></tr>
    {etf_outflow_rows}
  </table>
</div>

<div class="card">
  <h2>机构资金</h2>
  {inst_lines if inst_lines else '<p style="color:#999">暂无机构资金数据</p>'}
</div>

<div class="card" style="font-size:12px;color:#999">
  <p>Capital Flow Engine v1.0 | 数据源: akshare(商品/ETF/HSGT) + gold_engine</p>
  <div class="gaps">数据缺口: {gaps_str}</div>
  <p>本报告为AI辅助分析，不构成投资建议。</p>
</div>
</body>
</html>"""
