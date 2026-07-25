# -*- coding: utf-8 -*-
"""飞书群自定义机器人 Webhook 推送（interactive 卡片，支持签名校验）。"""
import json
import time
import hmac
import hashlib
import base64
import urllib.request
from .render import build_view, fmt_money


def _sign(secret):
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()
    return timestamp, base64.b64encode(hmac_code).decode("utf-8")


def _post(webhook, body, timeout=15):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(webhook, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _card(view):
    v = view
    rk = v["risk"]
    elements = []
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content":
                 f"**综合风险** {rk['composite']} ｜ **建议仓位** {rk['position']} ｜ "
                 f"上涨家数占比 {rk['up_ratio']}%"}
    })
    if v["mains"]:
        lines = ["**① 主线板块（资金共识）**"]
        for m in v["mains"][:6]:
            lines.append(f"- {m['sector']} 〔{m['stage']}〕 净流入 {fmt_money(m['net_now'])} ｜ {m['reason'][:36]}")
        lines.append("")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})
    if v["leaders"]:
        lines = ["**② 龙头体系**"]
        for ld in v["leaders"]:
            parts = " ／ ".join(f"{role[0]}{ld[role]}" for role in ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"] if role in ld)
            lines.append(f"- {ld['sector']}：{parts}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})
    if v["candidates"]:
        lines = ["**③ 突破候选（人工看图定买卖）**"]
        for c in v["candidates"][:6]:
            lines.append(f"- {c['name']}({c['code']}) {c['breakout']} 风险{c['risk_score']:.0f} 成交{c['amount_yi']:.0f}亿")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})
    elements.append({"tag": "hr"})
    elements.append({"tag": "note", "elements": [{"tag": "plain_text",
                   "content": "量化系统生成，仅供研究，不构成投资建议。"}]})
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text",
                   "content": f"📊 每日研投看板 {v['trade_date']}"}, "template": "blue"},
        "elements": elements,
    }


def push(webhook, tree, secret=None):
    """推送决策树到飞书。返回 (ok, resp)。"""
    view = build_view(tree)
    card = _card(view)
    body = {"msg_type": "interactive", "card": card}
    if secret:
        ts, sign = _sign(secret)
        body["timestamp"] = ts
        body["sign"] = sign
    resp = _post(webhook, body)
    ok = resp.get("code") == 0 or resp.get("StatusMessage") == "success"
    return ok, resp
