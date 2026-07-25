# -*- coding: utf-8 -*-
"""Flow Intelligence - 资金情报中心.

每天自动回答5个固定问题:
  Q1: 今天全球资金流向哪里？
  Q2: 今天中国资金流向哪里？
  Q3: ETF资金在买什么？
  Q4: 商品市场在交易什么？
  Q5: 这些资金流向会如何影响A股？

This is the highest-value module: "如果你的AI每天能够把这五个问题回答清楚，
它对交易决策的价值，会远远超过再增加几十个技术指标。"
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class FlowIntelligence:
    """5-question flow intelligence report."""
    timestamp: str = ""
    q1_global: str = ""       # 今天全球资金流向哪里？
    q2_china: str = ""        # 今天中国资金流向哪里？
    q3_etf: str = ""          # ETF资金在买什么？
    q4_commodity: str = ""    # 商品市场在交易什么？
    q5_a_share: str = ""      # 这些资金流向会如何影响A股？
    one_liner: str = ""       # 一句话总结


def _fmt_change(pct: float) -> str:
    """Format percentage change with direction."""
    if pct > 0:
        return "+%.2f%%" % pct
    return "%.2f%%" % pct


def _q1_global(commodity_snap, gold_data=None, institution_flow=None) -> str:
    """Q1: 今天全球资金流向哪里？"""
    lines = []

    # Commodity direction
    if commodity_snap and commodity_snap.all_items:
        up = [i for i in commodity_snap.all_items if i.change_pct > 0.5]
        down = [i for i in commodity_snap.all_items if i.change_pct < -0.5]
        if up:
            up_str = "、".join(["%s(%s)" % (i.name_cn, _fmt_change(i.change_pct)) for i in up[:4]])
            lines.append("商品上涨: %s" % up_str)
        if down:
            down_str = "、".join(["%s(%s)" % (i.name_cn, _fmt_change(i.change_pct)) for i in down[:4]])
            lines.append("商品下跌: %s" % down_str)

    # Risk appetite
    if commodity_snap and commodity_snap.risk_appetite:
        ra_map = {"risk_on": "风险偏好上升", "risk_off": "避险情绪升温", "neutral": "风险偏好中性"}
        lines.append(ra_map.get(commodity_snap.risk_appetite, "风险偏好不明"))

    # DXY and rates
    if gold_data:
        if gold_data.get("dxy"):
            dxy = gold_data["dxy"]
            dxy_dir = "走弱" if dxy < 100 else ("走强" if dxy > 104 else "震荡")
            lines.append("美元指数%.2f(%s)" % (dxy, dxy_dir))
        if gold_data.get("us_10y_yield"):
            y10 = gold_data["us_10y_yield"]
            lines.append("美债10Y收益率%.2f%%" % y10)

    # Southbound (global -> HK)
    if institution_flow and institution_flow.hsgt.south_net != 0:
        s = institution_flow.hsgt.south_net
        if s > 50:
            lines.append("南向资金大幅流入港股(%.0f亿)" % s)
        elif s > 10:
            lines.append("南向资金小幅流入港股(%.0f亿)" % s)

    if not lines:
        return "全球资金流向数据不足，无法判断。"

    # Synthesize
    if commodity_snap and commodity_snap.risk_appetite == "risk_off":
        summary = "全球资金从风险资产流向避险资产。"
    elif commodity_snap and commodity_snap.risk_appetite == "risk_on":
        summary = "全球资金流向风险资产，大宗商品走强。"
    else:
        summary = "全球资金流向分化，无明显方向。"

    return summary + "\n" + "；".join(lines)


def _q2_china(etf_snap, institution_flow=None) -> str:
    """Q2: 今天中国资金流向哪里？"""
    lines = []

    if etf_snap:
        # Broad ETF flow direction
        broad_inflow = [e for e in etf_snap.broad if e.shares_change > 0 and e.is_key]
        broad_outflow = [e for e in etf_snap.broad if e.shares_change < 0 and e.is_key]
        if broad_inflow:
            names = "、".join([e.name.replace("ETF", "")[:6] for e in broad_inflow[:3]])
            lines.append("宽基ETF净申购: %s" % names)
        if broad_outflow:
            names = "、".join([e.name.replace("ETF", "")[:6] for e in broad_outflow[:3]])
            lines.append("宽基ETF净赎回: %s" % names)

        # Industry/theme direction
        industry_inflow = [e for e in etf_snap.industry if e.shares_change > 5e6]
        if industry_inflow:
            names = "、".join([e.name.replace("ETF", "")[:8] for e in sorted(industry_inflow, key=lambda x: -x.shares_change)[:3]])
            lines.append("行业ETF资金流入: %s" % names)

        theme_inflow = [e for e in etf_snap.theme if e.shares_change > 5e6]
        if theme_inflow:
            names = "、".join([e.name.replace("ETF", "")[:8] for e in sorted(theme_inflow, key=lambda x: -x.shares_change)[:3]])
            lines.append("主题ETF资金流入: %s" % names)

    if institution_flow:
        # Southbound
        s = institution_flow.hsgt.south_net
        if s > 10:
            lines.append("南向资金流入港股(%.0f亿)" % s)
        elif s < -10:
            lines.append("南向资金流出港股(%.0f亿)" % s)

        # National team
        if institution_flow.national_team:
            for nt in institution_flow.national_team[:2]:
                lines.append("国家队%s %s (%.0f万份)" % (nt.action, nt.etf_name[:8], nt.shares_change / 1e4))

    if not lines:
        return "中国资金流向数据不足。"

    # Synthesize direction
    if etf_snap and "no_prev_shares" in (etf_snap.gaps or []):
        return "（首日运行，无份额变化对比数据）\n" + "；".join(lines)

    return "；".join(lines)


def _q3_etf(etf_snap) -> str:
    """Q3: ETF资金在买什么？"""
    if not etf_snap:
        return "ETF数据不足。"

    lines = []

    if "no_prev_shares" in (etf_snap.gaps or []):
        lines.append("（首日运行，明天起可跟踪份额变化）")
        # Still show today's volume leaders
        vol_leaders = sorted(
            etf_snap.broad + etf_snap.industry + etf_snap.theme,
            key=lambda x: -x.amount
        )[:5]
        if vol_leaders:
            lines.append("今日成交额最大ETF:")
            for e in vol_leaders:
                lines.append("  %s 成交%.1f亿" % (e.name[:12], e.amount / 1e8))
        return "\n".join(lines)

    # Top inflow (net purchase)
    inflow = [e for e in etf_snap.top_inflow if e.shares_change > 0]
    if inflow:
        lines.append("ETF净申购TOP:")
        for e in inflow[:5]:
            lines.append("  %s +%s万份 (%+.2f%%) 成交%.1f亿" % (
                e.name[:14], f"{e.shares_change/1e4:.0f}", e.shares_change_pct, e.amount / 1e8))

    # Top outflow (net redemption)
    outflow = [e for e in etf_snap.top_outflow if e.shares_change < 0]
    if outflow:
        lines.append("ETF净赎回TOP:")
        for e in outflow[:3]:
            lines.append("  %s %s万份 (%+.2f%%) 成交%.1f亿" % (
                e.name[:14], f"{e.shares_change/1e4:.0f}", e.shares_change_pct, e.amount / 1e8))

    # Gold ETF flow
    if etf_snap.gold:
        for e in etf_snap.gold:
            if e.shares_change != 0:
                direction = "流入" if e.shares_change > 0 else "流出"
                lines.append("黄金ETF(%s)份额%s %.0f万份" % (e.name[:8], direction, abs(e.shares_change) / 1e4))

    return "\n".join(lines) if lines else "ETF份额无显著变化。"


def _q4_commodity(commodity_snap) -> str:
    """Q4: 商品市场在交易什么？"""
    if not commodity_snap or not commodity_snap.all_items:
        return "商品数据不足。"

    lines = []
    by_cat = {"energy": [], "precious": [], "industrial": [], "agriculture": []}
    for item in commodity_snap.all_items:
        if item.category in by_cat:
            by_cat[item.category].append(item)

    cat_names = {"energy": "能源", "precious": "贵金属", "industrial": "工业金属", "agriculture": "农产品"}

    for cat, items in by_cat.items():
        if not items:
            continue
        up = [i for i in items if i.change_pct > 0.5]
        down = [i for i in items if i.change_pct < -0.5]
        flat = [i for i in items if abs(i.change_pct) <= 0.5]

        if up and not down:
            detail = "、".join(["%s(%s)" % (i.name_cn, _fmt_change(i.change_pct)) for i in up])
            lines.append("%s: 整体上涨 — %s" % (cat_names[cat], detail))
        elif down and not up:
            detail = "、".join(["%s(%s)" % (i.name_cn, _fmt_change(i.change_pct)) for i in down])
            lines.append("%s: 整体下跌 — %s" % (cat_names[cat], detail))
        elif up and down:
            up_str = "、".join(["%s(%s)" % (i.name_cn, _fmt_change(i.change_pct)) for i in up])
            down_str = "、".join(["%s(%s)" % (i.name_cn, _fmt_change(i.change_pct)) for i in down])
            lines.append("%s: 分化 — 涨[%s] 跌[%s]" % (cat_names[cat], up_str, down_str))
        else:
            lines.append("%s: 整体平稳" % cat_names[cat])

    # A-share implications
    implications = []
    for item in commodity_snap.all_items:
        if item.change_pct > 2 and item.a_share_link:
            implications.append("利好A股: %s" % item.a_share_link)
        elif item.change_pct < -2 and item.a_share_link:
            implications.append("利空A股: %s" % item.a_share_link)
    if implications:
        lines.append("")
        lines.extend(implications[:3])

    return "\n".join(lines)


def _q5_a_share(commodity_snap, etf_snap, institution_flow, gold_data=None) -> str:
    """Q5: 这些资金流向会如何影响A股？"""
    lines = []
    bullish_factors = []
    bearish_factors = []

    # Commodity signals
    if commodity_snap:
        if commodity_snap.risk_appetite == "risk_on":
            bullish_factors.append("全球风险偏好上升，利好周期股")
        elif commodity_snap.risk_appetite == "risk_off":
            bearish_factors.append("全球避险情绪升温，压制风险资产")

        for item in commodity_snap.all_items:
            if item.change_pct > 3 and item.a_share_link:
                bullish_factors.append("%s大涨利好%s" % (item.name_cn, item.a_share_link))
            elif item.change_pct < -3 and item.a_share_link:
                bearish_factors.append("%s大跌利空%s" % (item.name_cn, item.a_share_link))

    # ETF signals
    if etf_snap and "no_prev_shares" not in (etf_snap.gaps or []):
        inflow = [e for e in etf_snap.top_inflow if e.shares_change > 0]
        if inflow:
            top_inflow_name = inflow[0].name[:10] if inflow else ""
            bullish_factors.append("ETF净申购(%s)，增量资金入场" % top_inflow_name)

        outflow = [e for e in etf_snap.top_outflow if e.shares_change < -5e6]
        if len(outflow) >= 3:
            bearish_factors.append("多只ETF遭净赎回，资金可能撤离")

    # Institution signals
    if institution_flow:
        if institution_flow.hsgt.south_net > 50:
            bearish_factors.append("南向资金大幅流入港股(%.0f亿)，可能分流A股资金" % institution_flow.hsgt.south_net)
        if institution_flow.national_team:
            for nt in institution_flow.national_team:
                if nt.action == "增持":
                    bullish_factors.append("国家队增持%s" % nt.etf_name[:8])

    # Gold/DXY signals
    if gold_data:
        dxy = gold_data.get("dxy", 0)
        if dxy and dxy > 105:
            bearish_factors.append("美元走强(DXY=%.2f)，新兴市场承压" % dxy)
        elif dxy and dxy < 98:
            bullish_factors.append("美元走弱(DXY=%.2f)，利好新兴市场" % dxy)

    # Synthesize
    bull_count = len(bullish_factors)
    bear_count = len(bearish_factors)

    if bull_count > bear_count + 1:
        verdict = "整体偏多：资金流向对A股构成支撑。"
    elif bear_count > bull_count + 1:
        verdict = "整体偏空：资金流向对A股构成压力。"
    else:
        verdict = "整体中性：多空因素交织，需等待方向确认。"

    lines.append(verdict)
    if bullish_factors:
        lines.append("利好因素:")
        for f in bullish_factors[:4]:
            lines.append("  + %s" % f)
    if bearish_factors:
        lines.append("利空因素:")
        for f in bearish_factors[:4]:
            lines.append("  - %s" % f)

    return "\n".join(lines)


def answer_five_questions(commodity_snap=None, etf_snap=None,
                          institution_flow=None, gold_data=None) -> FlowIntelligence:
    """Answer the 5 daily flow intelligence questions."""
    fi = FlowIntelligence(timestamp=datetime.now().isoformat())

    fi.q1_global = _q1_global(commodity_snap, gold_data, institution_flow)
    fi.q2_china = _q2_china(etf_snap, institution_flow)
    fi.q3_etf = _q3_etf(etf_snap)
    fi.q4_commodity = _q4_commodity(commodity_snap)
    fi.q5_a_share = _q5_a_share(commodity_snap, etf_snap, institution_flow, gold_data)

    # One-liner summary
    parts = []
    if commodity_snap and commodity_snap.risk_appetite:
        ra_map = {"risk_on": "风险偏好上升", "risk_off": "避险升温", "neutral": "风险中性"}
        parts.append(ra_map.get(commodity_snap.risk_appetite, ""))
    if etf_snap and etf_snap.top_inflow and etf_snap.top_inflow[0].shares_change > 0:
        parts.append("ETF净申购%s" % etf_snap.top_inflow[0].name[:8])
    if institution_flow and institution_flow.hsgt.south_net > 30:
        parts.append("南向%.0f亿" % institution_flow.hsgt.south_net)
    fi.one_liner = "；".join(p for p in parts if p) if parts else "资金流向中性，无明显方向"

    return fi
