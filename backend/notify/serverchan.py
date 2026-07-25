# -*- coding: utf-8 -*-
"""Server酱（sct.ftqq.com）微信推送。"""
import json
import urllib.request
from .render import build_view, fmt_money

API = "https://sctapi.ftqq.com"


def _post(url, data, timeout=15):
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _markdown(view):
    v = view
    rk = v["risk"]
    lines = []

    # 标题
    lines.append(f"## 每日研投看板 {v['trade_date']}")
    lines.append("")

    # 风险概览
    lines.append(f"**综合风险** {rk['composite']} | "
                 f"**建议仓位** {rk['position']} | "
                 f"上涨家数占比 {rk['up_ratio']}%")
    lines.append("")

    # 主线板块
    if v["mains"]:
        lines.append("---")
        lines.append("")
        lines.append("### ① 主线板块（资金共识）")
        for m in v["mains"][:6]:
            sign = "+" if m["net_now"] >= 0 else ""
            lines.append(f"- **{m['sector']}** [{m['stage']}] "
                        f"净流入 {sign}{fmt_money(m['net_now'])} | {m['reason'][:36]}")

    # 龙头
    if v["leaders"]:
        lines.append("")
        lines.append("### ② 龙头体系")
        for ld in v["leaders"]:
            parts = " / ".join(
                f"{role[0]}{ld[role]}" for role in ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"]
                if role in ld)
            lines.append(f"- **{ld['sector']}**：{parts}")

    # 候选
    if v["candidates"]:
        lines.append("")
        lines.append("### ③ 候选范围（供你人工看图定买卖）")
        for c in v["candidates"][:6]:
            lines.append(f"- **{c['name']}**({c['code']}) {c['breakout']} "
                        f"风险{c['risk_score']:.0f} 成交{c['amount_yi']:.0f}亿")

    # 阶段分布
    sd = v.get("stage_distribution", {})
    if sd:
        dist_parts = [f"{k}={v}" for k, v in sorted(sd.items()) if v > 0]
        if dist_parts:
            lines.append("")
            lines.append(f"> 板块共识阶段：{' | '.join(dist_parts)}")

    lines.append("")
    lines.append("> 本看板由量化系统生成，仅供研究，不构成投资建议。")
    return "\n".join(lines)


def push(sendkey, tree):
    """推送决策树到 Server酱（微信通知）。返回 (ok, resp)。"""
    view = build_view(tree)
    md = _markdown(view)
    title = f"研投看板 {view['trade_date']} | 风险{view['risk']['composite']} 仓位{view['risk']['position']}"
    url = f"{API}/{sendkey}.send"
    try:
        resp = _post(url, {"title": title, "desp": md})
        ok = resp.get("code") == 0
        return ok, resp
    except Exception as e:
        return False, str(e)[:200]
