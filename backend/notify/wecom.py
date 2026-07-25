# -*- coding: utf-8 -*-
"""企业微信群机器人 Webhook 推送（markdown 消息）。"""
import json
import urllib.request
from .render import build_view, fmt_money

API = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


def _post(webhook, payload, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(webhook, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _md(view):
    v = view
    lines = []
    lines.append(f"# 📊 每日研投看板 {v['trade_date']}")
    rk = v["risk"]
    lines.append(f"> 综合风险 <font color=\"warning\">{rk['composite']}</font> ｜ "
                 f"建议仓位 <font color=\"info\">{rk['position']}</font> ｜ "
                 f"上涨家数占比 {rk['up_ratio']}%")
    lines.append("")
    lines.append("**① 主线板块（资金共识）**")
    for m in v["mains"][:6]:
        color = "warning" if m["net_now"] >= 0 else "comment"
        lines.append(f"> {m['sector']} 〔{m['stage']}〕 净流入 <font color=\"{color}\">{fmt_money(m['net_now'])}</font> ｜ {m['reason'][:40]}")
    if v["leaders"]:
        lines.append("")
        lines.append("**② 龙头体系**")
        for ld in v["leaders"]:
            parts = " ／ ".join(f"{role[0]}{ld[role]}" for role in ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"] if role in ld)
            lines.append(f"> {ld['sector']}：{parts}")
    if v["candidates"]:
        lines.append("")
        lines.append("**③ 突破候选（人工看图定买卖）**")
        for c in v["candidates"][:6]:
            lines.append(f"> {c['name']}({c['code']}) {c['breakout']} 风险{c['risk_score']:.0f} 成交{c['amount_yi']:.0f}亿")
    lines.append("")
    lines.append("> 本看板由量化系统生成，仅供研究，不构成投资建议。")
    return "\n".join(lines)


def push(webhook, tree):
    """推送决策树到企业微信。返回 (ok, resp)。"""
    view = build_view(tree)
    md = _md(view)
    resp = _post(webhook, {"msgtype": "markdown", "markdown": {"content": md}})
    ok = resp.get("errcode") == 0
    return ok, resp
