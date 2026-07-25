# -*- coding: utf-8 -*-
"""
research_memo.py —— 投资决策备忘录渲染器（Trading OS 13段格式）
=================================================================
将 cio_agent 输出的 InvestmentDecisionMemo 渲染为三端推送格式：

十三段结构（Trading OS 转型后）：
  ① 安检清单（Pre-flight Checklist）—— 6项通过/失败
  ② 核心观点（Investment Thesis）
  ③ 证据链（Evidence Chain）
  ④ 资金地图（Money Map）
  ⑤ 赔率表（Odds Table）—— 按赔率排序
  ⑥ 投资主线（Main Lines）—— 含why/risk bullets + 星级产业链
  ⑦ 机会成本（Opportunity Cost）—— 为什么不做某板块
  ⑧ 市场结构（Market Structure）—— 谁在赚钱
  ⑨ 交易计划（Trading Plan）—— A/B/C
  ⑩ 风险与反例（Risk & Counter）
  ⑪ 催化剂日历（Catalyst Calendar）—— 未来一周关键事件
  ⑫ 行动清单（Action List）—— 明日时间戳
  ⑬ 历史经验（Historical Context）
"""
from __future__ import annotations
import json
import re
import time
import hmac
import hashlib
import base64
import urllib.request


def _pct(v):
    if v is None:
        return "?"
    if 0 < v < 1:
        return f"{v*100:.0f}"
    return f"{v:.0f}"


def _stars(n):
    return "★" * n + "☆" * (5 - n)


def _dec_emoji(can_buy):
    return {"YES": "🟢", "NO": "🔴", "CAUTION": "🟡"}.get(can_buy, "⚪")


def _dec_color(can_buy):
    return {"YES": "warning", "NO": "comment", "CAUTION": "info"}.get(can_buy, "comment")


def _od_grade(odds):
    """赔率等级。"""
    if odds >= 3:
        return "S"
    if odds >= 2:
        return "A"
    if odds >= 1.3:
        return "B"
    return "C"


# ── 盘前纪要：个股代码→名称解析（best-effort，失败降级为代码）──
_PN_CACHE = None


def _code2name():
    global _PN_CACHE
    if _PN_CACHE is not None:
        return _PN_CACHE
    m = {}
    try:
        import os as _os
        import sqlite3 as _sq
        db = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..",
                           "database", "vibe_research.db")
        if _os.path.exists(db):
            con = _sq.connect(db)
            for code, name in con.execute("SELECT code, name FROM stock_info"):
                m[str(code).strip()] = name
            con.close()
    except Exception:
        pass
    _PN_CACHE = m
    return m


def _pn(code):
    """代码→名称（拿不到就原样返回代码）。"""
    if not code:
        return ""
    return _code2name().get(str(code).strip(), str(code))


def _clean_ann(detail):
    """去掉公告原文自带的类型前缀（利好：/减持：…），避免与渲染标签重复。"""
    return re.sub(r"^(利好|利空|减持|风险|解禁|中标|签订|合作|预增|预减|回购|增持)[：:]\s*", "", detail or "").strip()


def _panqian_md_lines(pq, compact=False):
    """把 PanQianBlock 渲染为 markdown 行列表。compact=True 用于企微精简推送。"""
    lines = [f"**📋 盘前纪要（{pq.article_date}）**  _{pq.headline}_"]
    secs = pq.sections or {}
    cap = 3 if compact else 4

    hots = (secs.get("hotspot", {}) or {}).get("items", []) or []
    hots_show = [it for it in hots if it.get("stocks")] or hots
    if hots_show:
        parts = []
        for it in hots_show[:cap]:
            txt = (it.get("text") or "")[:44]
            stk = "→" + "、".join(_pn(c) for c in it.get("stocks", [])[:3]) if it.get("stocks") else ""
            parts.append(f"{txt}{stk}")
        lines.append("🔥 热点：" + "；".join(parts))

    ann = (secs.get("announce", {}) or {}).get("items", []) or []
    if ann:
        good = [it for it in ann if it.get("type") == "利好"][:2]
        bad = [it for it in ann if it.get("type") in ("利空", "减持", "风险", "解禁")][:2]
        if good:
            lines.append("📌 利好：" + "；".join(_clean_ann(it.get("detail", ""))[:34] for it in good))
        if bad:
            lines.append("⚠️ 风险：" + "；".join(_clean_ann(it.get("detail", ""))[:34] for it in bad))

    lu = (secs.get("limit_up", {}) or {}).get("items", []) or []
    if lu:
        chains = sorted({it.get("days") for it in lu if it.get("days")}, reverse=True)
        if chains:
            lines.append("🔝 连板：" + "、".join(f"{d}板" for d in chains[:6]))

    if not compact:
        nh = (secs.get("new_high", {}) or {}).get("items", []) or []
        if nh:
            stks, cnt, sec = [], None, ""
            for it in nh[:8]:
                stks.extend(_pn(c) for c in it.get("stocks", []))
                if it.get("count"):
                    cnt = max(cnt or 0, it["count"])
                if it.get("sector"):
                    sec = it["sector"]
            if stks:
                lines.append(f"📈 新高：{'、'.join(stks)}")
            elif cnt:
                lines.append(f"📈 新高：{cnt}家" + (f"（集中于{sec}）" if sec else ""))
        hl = (secs.get("hot_list", {}) or {}).get("items", []) or []
        if hl:
            parts = []
            for it in hl[:4]:
                src = it.get("source") or (f"{it.get('rank')}." if it.get("rank") else "")
                stks = "、".join(_pn(c) for c in it.get("stocks", [])[:6])
                if src and stks:
                    parts.append(f"{src}：{stks}")
                elif stks:
                    parts.append(stks)
            if parts:
                lines.append("🔥 热榜：" + "；".join(parts))

    if pq.risk_flags:
        lines.append("💣 地雷阵：" + "；".join(
            f"{_pn(r.get('stock',''))}({r.get('type','')})" for r in pq.risk_flags[:4]))
    return lines


def _industry_chain_md_lines(blk, compact=False):
    """把 IndustryChainBlock（L3.5 产业链推理）渲染为 markdown 行列表。
    compact=True 用于企微精简推送（只列瓶颈+候选，省略降级明细）。"""
    if not blk or not blk.has_data:
        return []
    lines = [f"**🔗 L3.5 产业链推理（{blk.stage}）**  _{blk.narrative}_"]
    # 瓶颈环节 Top（raw 中已按 score 降序）
    bns = blk.bottlenecks or []
    cap = 4 if compact else 6
    if bns:
        parts = []
        for b in bns[:cap]:
            flag = "✅" if b.get("fund_validated") else "⚪"
            parts.append(f"{flag}{b.get('segment', '')}")
        lines.append("⛓️ 瓶颈环节：" + "；".join(parts))
    # 候选个股（最靠近瓶颈）
    cands = blk.candidates or []
    if cands:
        parts = []
        for c in cands[:6]:
            ev = "、".join(c.get("evidence", []) or [])
            parts.append(f"{c.get('name', '')}({ev})" if ev else c.get("name", ""))
        lines.append("🎯 候选：" + "、".join(parts))
    # 蹭热点降级（仅完整版展示）
    downs = blk.downgraded or []
    if downs and not compact:
        lines.append("🚫 蹭热点降级：" + "、".join(d.get("stock", "") for d in downs[:8]))
    return lines


def _fmt_disc(d):
    """格式化一条"今日新发现"（供各渲染器复用）。返回 (标题, 说明)。"""
    conf = int((d.get("confidence") or 0) * 100)
    if d.get("type") == "human":
        return (f"🧠【假设】{d.get('label','')}（置信{conf}%，{d.get('regime','待验证')}）",
                d.get("note", ""))
    tag = {"增强": "📈", "减弱": "📉", "脱钩": "🔌", "稳定": "➖"}.get(d.get("regime"), "•")
    corr = d.get("corr")
    corr_s = f"{corr:+.2f}" if isinstance(corr, (int, float)) else "?"
    return (f"{tag}【{d.get('regime')}】{d.get('label','')} 相关{corr_s}（置信{conf}%）",
            d.get("note", ""))


# ═══════════════════════════════════════════════════════
#  企微 Markdown
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
#  资金迁移块（范式转移：日报第一页 = 一句话结论+迁移图+反证+我怎么办）
# ═══════════════════════════════════════════════════════

def _mig_stars(m):
    n = max(0, min(5, int(m.get("rating", 0) or 0)))
    return "★" * n + "☆" * (5 - n)


def _migration_md(memo):
    """资金迁移块 markdown（wecom / serverchan 用）。返回行列表。"""
    m = getattr(memo, "migration", None) or {}
    if not m.get("thesis"):
        return []
    L = ["## 🧭 资金迁移 · 一句话结论（日报第一页）",
         f"**{_mig_stars(m)}**  {m['thesis']}"]
    rot = m.get("rotation", {}) or {}
    if rot.get("out_top") or rot.get("in_top"):
        L += ["",
              f"**资金离开**：{', '.join(rot.get('out_top', [])[:4])}",
              f"**资金进入**：{', '.join(rot.get('in_top', [])[:4])}"]
    chains = rot.get("chains", []) or []
    if chains:
        L.append(f"**迁移链**：{' ｜ '.join(chains[:3])}")
    ca = (m.get("cross_asset", {}) or {}).get("sentence")
    if ca:
        L += ["", f"**跨资产闭环**：{ca}"]
    fals = m.get("falsification", []) or []
    if fals:
        L.append("**反证决策树**（若以下发生 → 本次判断失效）：")
        for f in fals:
            tag = "⚠️已触发" if f.get("triggered") else "监测中"
            L.append(f"> - 若 {f.get('if','')} → {f.get('then','')} 〔{tag}〕")
    if m.get("what_to_do"):
        L += ["", f"**我怎么办**：{m['what_to_do']}"]
    L += ["", "---", ""]
    return L


def _migration_condensed(memo):
    """精简企微推送用的资金迁移块。"""
    m = getattr(memo, "migration", None) or {}
    if not m.get("thesis"):
        return []
    L = [f"> 🧭 **资金迁移 {_mig_stars(m)}**",
         f"> {m['thesis']}"]
    rot = m.get("rotation", {}) or {}
    if rot.get("chains"):
        L.append(f"> 迁移：{' ｜ '.join(rot['chains'][:2])}")
    if m.get("what_to_do"):
        L.append(f"> 我怎么办：{m['what_to_do']}")
    L.append("")
    return L


def _migration_html(memo):
    """资金迁移块 HTML（_memo_html 用）。"""
    m = getattr(memo, "migration", None) or {}
    if not m.get("thesis"):
        return ""
    rot = m.get("rotation", {}) or {}
    chains = " ｜ ".join(rot.get("chains", [])[:3])
    ca = (m.get("cross_asset", {}) or {}).get("sentence", "")
    fals_items = ""
    for f in m.get("falsification", []) or []:
        cls = "triggered" if f.get("triggered") else "watch"
        label = "⚠️已触发" if f.get("triggered") else "监测中"
        fals_items += (f"<li>若 {_esc(f.get('if',''))} → {_esc(f.get('then',''))} "
                       f"<span class='{cls}'>{label}</span></li>")
    return f"""
<section class="mig">
  <h2>🧭 资金迁移 · 一句话结论 <span class="stars">{_mig_stars(m)}</span></h2>
  <p class="thesis">{_esc(m['thesis'])}</p>
  <div class="mig-grid">
    <div><span class="lab">资金离开</span><br>{_esc('、'.join(rot.get('out_top',[])[:4]) or '—')}</div>
    <div><span class="lab">资金进入</span><br>{_esc('、'.join(rot.get('in_top',[])[:4]) or '—')}</div>
  </div>
  {f"<p><span class='lab'>迁移链</span> {_esc(chains)}</p>" if chains else ""}
  {f"<p><span class='lab'>跨资产闭环</span> {_esc(ca)}</p>" if ca else ""}
  {f"<p><span class='lab'>我怎么办</span> {_esc(m.get('what_to_do',''))}</p>" if m.get('what_to_do') else ""}
  {f"<details class='fals'><summary>反证决策树（若以下发生 → 判断失效）</summary><ul>{fals_items}</ul></details>" if fals_items else ""}
</section>
"""


def _migration_feishu(memo):
    """资金迁移块 飞书 card 元素（prepend 到 elements 顶部）。"""
    m = getattr(memo, "migration", None) or {}
    if not m.get("thesis"):
        return []
    rot = m.get("rotation", {}) or {}
    lines = [f"**🧭 资金迁移 {_mig_stars(m)}**", m['thesis']]
    if rot.get("out_top") or rot.get("in_top"):
        lines.append(f"离开：{', '.join(rot.get('out_top',[])[:3])} ｜ 进入：{', '.join(rot.get('in_top',[])[:3])}")
    chains = rot.get("chains", []) or []
    if chains:
        lines.append("迁移：" + " ｜ ".join(chains[:2]))
    ca = (m.get("cross_asset", {}) or {}).get("sentence")
    if ca:
        lines.append(f"跨资产：{ca}")
    if m.get("what_to_do"):
        lines.append(f"我怎么办：{m['what_to_do']}")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]


def _causal_md(memo):
    """因果推理块 markdown（wecom / serverchan 用）。返回行列表。"""
    c = getattr(memo, "causal", None) or {}
    if not (c or {}).get("causes"):
        return []
    L = ["## 🧩 因果推理 · 为什么（钱为什么去那）"]
    causes = c["causes"]
    ci = c.get("chain_insights", {}) or {}
    for sec, cd in causes.items():
        L.append(f"- **{sec}**：{cd.get('display', '')}")
        if sec in ci:
            ins = ci[sec]
            L.append(f"  ↳ 产业链：{ins[:120]}{'…' if len(ins) > 120 else ''}")
    if c.get("unknown_list"):
        L.append(f"- ⚠️ 仅资金驱动、未找到具体催化：{'、'.join(c['unknown_list'])}"
                 f"（原因未知，继续观察）")
    L += ["", "---", ""]
    return L


def _causal_condensed(memo):
    """因果推理块 精简企微推送。"""
    c = getattr(memo, "causal", None) or {}
    if not (c or {}).get("causes"):
        return []
    parts = []
    for sec, cd in c["causes"].items():
        if cd.get("status") == "found":
            ev = (cd.get("evidence") or [{}])[0].get("text", "") if cd.get("evidence") else cd.get("driver", "")
            parts.append(f"{sec}:{ev[:16]}")
        else:
            parts.append(f"{sec}:资金驱动")
    return [f"**因果** {'；'.join(parts)}", ""]


def _causal_feishu(memo):
    """因果推理块 飞书 card 元素（prepend 到迁移块之后）。"""
    c = getattr(memo, "causal", None) or {}
    if not (c or {}).get("causes"):
        return []
    lines = ["**🧩 因果推理 · 为什么**"]
    ci = c.get("chain_insights", {}) or {}
    for sec, cd in c["causes"].items():
        lines.append(f"**{sec}**：{cd.get('display', '')}")
        if sec in ci:
            lines.append(f"↳ {ci[sec][:90]}")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]


def _causal_html(memo):
    """因果推理块 HTML（_memo_html 用）。"""
    c = getattr(memo, "causal", None) or {}
    if not (c or {}).get("causes"):
        return ""
    body = ""
    ci = c.get("chain_insights", {}) or {}
    for sec, cd in c["causes"].items():
        body += f'<p><b>{_esc(sec)}</b>：{_esc(cd.get("display", ""))}</p>'
        if sec in ci:
            body += f'<p class="link">↳ 产业链：{_esc(ci[sec])}</p>'
    if c.get("unknown_list"):
        body += (f'<p class="note">⚠️ 仅资金驱动、未找到具体催化：'
                 f'{_esc("、".join(c["unknown_list"]))}（原因未知，继续观察）</p>')
    return (f'<div class="sec causal"><div class="h">🧩 因果推理 · 为什么'
            f'（钱为什么去那）</div><div class="b">{body}</div></div>')


# ── Slice 3：真实 IC 辩论块（L1~L8 支持/反对 + 原因 + 加权投票）──
_VOTE_ICON = {"support": "🟢", "oppose": "🔴", "neutral": "⚪", "absent": "⚫"}


def _debate_md(memo):
    """IC 辩论块 markdown（wecom 全版 / serverchan 用）。返回行列表。"""
    d = getattr(memo, "debate", None) or {}
    rows = d.get("debate") or []
    wv = d.get("weighted_vote") or {}
    verdict = d.get("verdict") or ""
    if not rows:
        return []
    L = ["## 🏛 投资委员会 · 真实辩论（L1~L8 投票）"]
    if verdict:
        L.append(f"**裁决**：{verdict}")
    if wv.get("ratio"):
        L.append(f"**加权投票**：{wv['ratio']} ｜ {wv.get('weighted_ratio', '')}")
    L.append("")
    for r in rows:
        v = r.get("vote")
        icon = _VOTE_ICON.get(v, "⚪")
        name = r.get("name", "")
        arg = r.get("argument", "")
        L.append(f"- {icon} **{name}**：{arg}")
    L += ["", "---", ""]
    return L


def _debate_condensed(memo):
    """IC 辩论块 精简企微推送（只给裁决 + 加权投票 + 支持/反对方）。"""
    d = getattr(memo, "debate", None) or {}
    wv = d.get("weighted_vote") or {}
    verdict = d.get("verdict") or ""
    if not wv.get("ratio"):
        return []
    sup = "、".join(wv.get("support_layers", []) or [])
    opp = "、".join(wv.get("oppose_layers", []) or [])
    L = [f"> 🏛 **IC辩论 {wv['ratio']}**"]
    if verdict:
        L.append(f"> {verdict}")
    if sup:
        L.append(f"> 支持方：{sup}")
    if opp:
        L.append(f"> 反对方：{opp}")
    L.append("")
    return L


def _debate_feishu(memo):
    """IC 辩论块 飞书 card 元素（prepend 到顶部）。"""
    d = getattr(memo, "debate", None) or {}
    rows = d.get("debate") or []
    wv = d.get("weighted_vote") or {}
    verdict = d.get("verdict") or ""
    if not rows:
        return []
    lines = ["**🏛 投资委员会 · 真实辩论**"]
    if verdict:
        lines.append(f"**裁决**：{verdict}")
    if wv.get("ratio"):
        lines.append(f"加权投票：{wv['ratio']}")
    for r in rows:
        v = r.get("vote")
        icon = _VOTE_ICON.get(v, "⚪")
        lines.append(f"{icon} {r.get('name', '')}：{r.get('argument', '')}")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]


def _debate_html(memo):
    """IC 辩论块 HTML（_memo_html 用）。"""
    d = getattr(memo, "debate", None) or {}
    rows = d.get("debate") or []
    wv = d.get("weighted_vote") or {}
    verdict = d.get("verdict") or ""
    if not rows:
        return ""
    items = ""
    for r in rows:
        v = r.get("vote")
        cls = {"support": "sup", "oppose": "opp", "neutral": "neu", "absent": "abs"}.get(v, "neu")
        name = r.get("name", "")
        arg = r.get("argument", "")
        conf = r.get("confidence")
        cinfo = f" <span class='conf'>置信{conf}</span>" if conf is not None else ""
        items += f'<li class="{cls}"><b>{_esc(name)}</b>{cinfo}：{_esc(arg)}</li>'
    wv_line = ""
    if wv.get("ratio"):
        wv_line = (f'<p><span class="lab">加权投票</span> {_esc(wv["ratio"])}'
                   f' ｜ {_esc(wv.get("weighted_ratio", ""))}</p>')
    verdict_line = f'<p class="verdict">{_esc(verdict)}</p>' if verdict else ""
    return (f'<div class="sec debate"><div class="h">🏛 投资委员会 · 真实辩论'
            f'（L1~L8 投票）</div><div class="b">{verdict_line}{wv_line}'
            f'<ul class="debate-rows">{items}</ul></div></div>')


# ── Slice 4：情景推演块（明日最大摆动变量 → 条件分支）──
def _scenario_md(memo):
    """情景推演块 markdown（wecom 全版 / serverchan 用）。返回行列表。"""
    s = getattr(memo, "scenario", None) or {}
    variables = s.get("variables") or []
    if not variables:
        return []
    L = ["## 🎲 情景推演 · 明日最大摆动变量（若 X → 谁赢谁输）"]
    if s.get("summary"):
        L.append(f"> {s['summary']}")
    L.append("")
    for v in variables:
        L.append(f"### {v.get('title', '')}")
        if v.get("evidence"):
            L.append(f"依据：{v['evidence']}")
        for b in v.get("branches", []):
            w = b.get("winners") or []
            l = b.get("losers") or []
            wtxt = f"｜赢家：{('、'.join(w))}" if w else ""
            ltxt = f"｜输家：{('、'.join(l))}" if l else ""
            L.append(f"- **{b.get('name', '')}（{b.get('weight', '')}%）**："
                     f"{b.get('market', '')}{wtxt}{ltxt}")
        if v.get("base_case"):
            L.append(f"  - 基准：{v['base_case']}")
        if v.get("implication"):
            L.append(f"  - 我办：{v['implication']}")
    if s.get("key_switches"):
        L.append("")
        L.append("**⚠️ 失效开关**：")
        for sw in s["key_switches"]:
            L.append(f"- {sw}")
    L += ["", "---", ""]
    return L


def _scenario_condensed(memo):
    """情景推演块 精简企微推送（只给变量数 + 基准总览 + 分支概率 + 失效开关）。"""
    s = getattr(memo, "scenario", None) or {}
    variables = s.get("variables") or []
    if not variables:
        return []
    L = [f"> 🎲 **情景推演（{s.get('n_variables', '')}变量）**"]
    if s.get("summary"):
        L.append(f"> {s['summary']}")
    for v in variables:
        title = v.get("title", "").split("·")[-1].strip()
        br = " / ".join(f"{b.get('name', '')}{b.get('weight', '')}%"
                        for b in v.get("branches", []))
        L.append(f"> · {title}：{br}")
    if s.get("key_switches"):
        L.append(f"> ⚠ 失效：{('；'.join(s['key_switches']))[:110]}")
    L.append("")
    return L


def _scenario_feishu(memo):
    """情景推演块 飞书 card 元素（prepend 到顶部）。"""
    s = getattr(memo, "scenario", None) or {}
    variables = s.get("variables") or []
    if not variables:
        return []
    lines = ["**🎲 情景推演 · 明日最大摆动变量**"]
    if s.get("summary"):
        lines.append(f"> {s['summary']}")
    for v in variables:
        lines.append(f"**{v.get('title', '')}**")
        for b in v.get("branches", []):
            w = b.get("winners") or []
            l = b.get("losers") or []
            extra = ""
            if w:
                extra += f" 赢:{('、'.join(w))}"
            if l:
                extra += f" 输:{('、'.join(l))}"
            lines.append(f"- {b.get('name', '')}({b.get('weight', '')}%)："
                         f"{b.get('market', '')}{extra}")
    if s.get("key_switches"):
        lines.append("⚠ 失效：" + "；".join(s["key_switches"]))
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]


def _scenario_html(memo):
    """情景推演块 HTML（_memo_html 用）。"""
    s = getattr(memo, "scenario", None) or {}
    variables = s.get("variables") or []
    if not variables:
        return ""
    cards = ""
    for v in variables:
        br_html = ""
        for b in v.get("branches", []):
            w = b.get("winners") or []
            l = b.get("losers") or []
            wtxt = f'<span class="win">赢：{_esc("、".join(w))}</span>' if w else ""
            ltxt = f'<span class="lose">输：{_esc("、".join(l))}</span>' if l else ""
            br_html += (f'<div class="branch"><b>{_esc(b.get("name", ""))} '
                        f'({b.get("weight", "")}%)</b>：{_esc(b.get("market", ""))} '
                        f'{wtxt} {ltxt}</div>')
        ev = f'<p class="ev">{_esc(v.get("evidence", ""))}</p>' if v.get("evidence") else ""
        bc = f'<p class="base">{_esc(v.get("base_case", ""))}</p>' if v.get("base_case") else ""
        im = (f'<p class="impl">{_esc(v.get("implication", ""))}</p>'
              if v.get("implication") else "")
        cards += (f'<div class="var"><div class="vt">{_esc(v.get("title", ""))}</div>'
                  f'{ev}{br_html}{bc}{im}</div>')
    sw = ""
    if s.get("key_switches"):
        sw = ('<p class="switches">⚠️ 失效开关：'
              + _esc("；".join(s["key_switches"])) + '</p>')
    summ = f'<p class="summ">{_esc(s["summary"])}</p>' if s.get("summary") else ""
    return (f'<div class="sec scenario"><div class="h">🎲 情景推演 · 明日最大摆动变量'
            f'（若 X → 谁赢谁输）</div><div class="b">{summ}{cards}{sw}</div></div>')


# ── Slice 5：学习复盘中心（预测日志 + T+1 回放 + 模式成败率）──
def _learning_md(memo):
    """学习复盘块 markdown（wecom 全版 / serverchan 用）。返回行列表。"""
    L0 = getattr(memo, "learning", None) or {}
    if not (L0 or {}).get("n_predictions"):
        return []
    L = ["## 📚 学习复盘 · 预测回放与模式成败率"]
    acc = L0.get("ic_accuracy")
    sacc = L0.get("scenario_accuracy")
    head = (f"已记录 {L0['n_predictions']} 条预测，回放 {L0['n_replayed']} 条｜"
            f"IC 方向命中率 {acc if acc is not None else '—'}%；"
            f"情景分支命中率 {sacc if sacc is not None else '—'}%")
    L.append(f"> {head}")
    if L0.get("patterns"):
        L.append("**模式规律**：")
        for p in L0["patterns"]:
            L.append(f"- {p['label']}：{p['note']}")
    if L0.get("recent"):
        L.append("**近期复盘**：")
        for r in L0["recent"][-5:]:
            agg = r.get("market_agg")
            agg_s = f"{agg}" if agg is not None else "—"
            L.append(f"- {r['date']} IC={r['ic']} → {r['outcome']} "
                     f"市场广度={agg_s} {r['ic_hit']} {r['scenario_hit']}")
    L.append(f"> 💡 {L0.get('self_note','')}")
    L += ["", "---", ""]
    return L


def _research_board_line(memo):
    """Research Board 精简一行（用于 condensed 推送）。"""
    d = getattr(memo, "debate", None) or {}
    rows = d.get("debate") or []
    if not rows:
        bars = getattr(memo, "confidence_bars", {}) or {}
        if not bars:
            return ""
        bulls = sum(1 for v in bars.values() if isinstance(v, dict) and v.get("direction") == "Bullish")
        bears = sum(1 for v in bars.values() if isinstance(v, dict) and v.get("direction") == "Bearish")
        return f"📊 **⑧ 研究员**：看多{bulls} 看空{bears} 中性{len(bars)-bulls-bears}"
    sups = sum(1 for r in rows if r.get("vote") == "support")
    opps = sum(1 for r in rows if r.get("vote") == "oppose")
    neus = len(rows) - sups - opps
    return f"📊 **⑧ 研究员**：支持{sups} 反对{opps} 中性{neus}"


def _learning_condensed(memo):
    """学习复盘块 精简企微推送。"""
    L0 = getattr(memo, "learning", None) or {}
    if not (L0 or {}).get("n_predictions"):
        return []
    acc = L0.get("ic_accuracy")
    txt = (f"> 📚 学习复盘：回放 {L0['n_replayed']}/{L0['n_predictions']} 条，"
           f"IC命中率 {acc if acc is not None else '—'}%")
    return [txt, ""]


def _learning_feishu(memo):
    """学习复盘块 飞书 card 元素（prepend 到顶部）。"""
    L0 = getattr(memo, "learning", None) or {}
    if not (L0 or {}).get("n_predictions"):
        return []
    acc = L0.get("ic_accuracy")
    sacc = L0.get("scenario_accuracy")
    lines = ["**📚 学习复盘 · 预测回放**"]
    lines.append(f"回放 {L0['n_replayed']}/{L0['n_predictions']} 条｜IC命中率 "
                 f"{acc if acc is not None else '—'}%｜情景 {sacc if sacc is not None else '—'}%")
    if L0.get("patterns"):
        for p in L0["patterns"][:2]:
            lines.append(f"▸ {p['label']}：{p['note']}")
    lines.append(f"💡 {L0.get('self_note','')}")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]


def _learning_html(memo):
    """学习复盘块 HTML（_memo_html 用）。"""
    L0 = getattr(memo, "learning", None) or {}
    if not (L0 or {}).get("n_predictions"):
        return ""
    acc = L0.get("ic_accuracy")
    sacc = L0.get("scenario_accuracy")
    head = (f"已记录 <b>{L0['n_predictions']}</b> 条预测，回放 <b>{L0['n_replayed']}</b> 条｜"
            f"IC 方向命中率 <b>{acc if acc is not None else '—'}%</b>｜"
            f"情景分支命中率 <b>{sacc if sacc is not None else '—'}%</b>")
    pat = ""
    for p in L0.get("patterns", []) or []:
        pat += f'<li>{_esc(p["label"])}：{_esc(p["note"])}</li>'
    rec = ""
    for r in L0.get("recent", []) or []:
        agg = r.get("market_agg")
        agg_s = f"{agg}" if agg is not None else "—"
        rec += (f'<tr><td>{_esc(r["date"])}</td><td>{_esc(str(r["ic"]))}</td>'
                f'<td>{_esc(str(r["outcome"]))}</td><td>{_esc(agg_s)}</td>'
                f'<td>{_esc(r["ic_hit"])}</td><td>{_esc(r["scenario_hit"])}</td></tr>')
    return (f'<div class="sec learning"><div class="h">📚 学习复盘 · 预测回放与模式成败率'
            f'（系统越跑越准）</div><div class="b">'
            f'<p class="lh">{head}</p>'
            + (f'<p class="lab">模式规律</p><ul class="pat">{pat}</ul>' if pat else "")
            + (f'<p class="lab">近期复盘</p><table class="rectab"><tr>'
               f'<th>预测日</th><th>IC</th><th>回放日</th><th>市场广度</th>'
               f'<th>方向</th><th>情景</th></tr>{rec}</table>' if rec else "")
            + f'<p class="self">💡 {_esc(L0.get("self_note",""))}</p>'
            f'</div></div>')


# ═══════════════════════════════════════════════════════
#  取精华：AI-Portfolio-Compass 移植块（MIT License）渲染
#  position_layer / trade_review / freshness / action_cards
#  每块提供 md / condensed / feishu / html 四种渲染
# ═══════════════════════════════════════════════════════

# ---------- 持仓分层 ----------
def _position_layer_md(memo):
    d = getattr(memo, "position_layer", None) or {}
    if not (d or {}).get("has_data"):
        return []
    L = ["## 🗂 持仓分层（MIT移植）", f"> {d.get('summary','')}"]
    for h in d.get("holdings", [])[:12]:
        L.append(f"- {h['name']}({h['asset_type']}) 权重{h['weight_pct']}% · "
                 f"**{h['layer']}** · 浮亏{h['pl_ratio']}% · 持有{h['data_days']}天")
    L += ["", "---", ""]
    return L

def _position_layer_condensed(memo):
    d = getattr(memo, "position_layer", None) or {}
    if not (d or {}).get("has_data"):
        return []
    return [f"> 🗂 持仓分层：{d.get('summary','')[:120]}", ""]

def _position_layer_feishu(memo):
    d = getattr(memo, "position_layer", None) or {}
    if not (d or {}).get("has_data"):
        return []
    lines = ["**🗂 持仓分层（MIT移植）**", d.get("summary", "")]
    for h in d.get("holdings", [])[:8]:
        lines.append(f"▸ {h['name']} {h['weight_pct']}% · {h['layer']} · 浮亏{h['pl_ratio']}%")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]

def _position_layer_html(memo):
    d = getattr(memo, "position_layer", None) or {}
    if not (d or {}).get("has_data"):
        return ""
    dist = d.get("layer_distribution", {})
    chips = "".join(f'<span class="pl-chip">{_esc(k)} {v}</span>' for k, v in dist.items() if v)
    rows = ""
    for h in d.get("holdings", [])[:15]:
        cls = {"核心长期仓": "core", "中期配置仓": "mid",
               "短期交易仓": "short", "遗留观察仓": "legacy"}.get(h["layer"], "")
        rows += (f'<tr class="pl-{cls}"><td>{_esc(h["name"])}</td><td>{_esc(h["asset_type"])}</td>'
                 f'<td>{h["weight_pct"]}%</td><td><b>{_esc(h["layer"])}</b></td>'
                 f'<td>{h["pl_ratio"]}%</td><td>{h["data_days"]}天</td>'
                 f'<td class="note">{_esc(h["reason"])}</td></tr>')
    return (f'<div class="sec position"><div class="h">🗂 持仓分层（MIT移植）</div>'
            f'<div class="b"><p class="lh">{_esc(d.get("summary",""))}</p>'
            f'<p>{chips}</p>'
            f'<table class="rectab"><tr><th>标的</th><th>类型</th><th>权重</th>'
            f'<th>层级</th><th>浮亏</th><th>持有</th><th>依据</th></tr>{rows}</table>'
            f'</div></div>')


# ---------- 交易复盘纪律 ----------
def _trade_review_md(memo):
    d = getattr(memo, "trade_review", None) or {}
    if not (d or {}).get("has_data"):
        return []
    L = ["## 🔁 交易复盘纪律（MIT移植）", f"> {d.get('summary','')}"]
    for r in d.get("reviews", [])[:12]:
        r1 = f"{r['ret_1d']:+}%" if r['ret_1d'] is not None else "—"
        r5 = f"{r['ret_5d']:+}%" if r['ret_5d'] is not None else "—"
        rl = f"{r['ret_latest']:+}%" if r['ret_latest'] is not None else "—"
        flag = " ⚠止损拖延" if r.get("stop_delay") else ""
        L.append(f"- {r['name'] or r['code']} {r['side']} {r['deal_time']}："
                 f"**{r['label']}**{flag} — {r['note']}（1日{r1}/5日{r5}/最新{rl}）")
    L += ["", "---", ""]
    return L

def _trade_review_condensed(memo):
    d = getattr(memo, "trade_review", None) or {}
    if not (d or {}).get("has_data"):
        return []
    return [f"> 🔁 交易复盘：{d.get('summary','')[:120]}", ""]

def _trade_review_feishu(memo):
    d = getattr(memo, "trade_review", None) or {}
    if not (d or {}).get("has_data"):
        return []
    lines = ["**🔁 交易复盘纪律（MIT移植）**", d.get("summary", "")]
    for r in d.get("reviews", [])[:8]:
        flag = " ⚠" if r.get("stop_delay") else ""
        lines.append(f"▸ {r['name'] or r['code']} {r['side']}：{r['label']}{flag}")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]

def _trade_review_html(memo):
    d = getattr(memo, "trade_review", None) or {}
    if not (d or {}).get("has_data"):
        return ""
    rows = ""
    for r in d.get("reviews", [])[:15]:
        bad = r['label'] in ("卖飞", "买到短线高位", "止损拖延") or r.get("stop_delay")
        cls = " bad" if bad else ""
        r1 = f"{r['ret_1d']:+}%" if r['ret_1d'] is not None else "—"
        r5 = f"{r['ret_5d']:+}%" if r['ret_5d'] is not None else "—"
        rl = f"{r['ret_latest']:+}%" if r['ret_latest'] is not None else "—"
        rows += (f'<tr class="tr{cls}"><td>{_esc(r["name"] or r["code"])}</td>'
                 f'<td>{r["side"]}</td><td>{r["deal_time"]}</td>'
                 f'<td><b>{_esc(r["label"])}</b></td><td>{r1}</td><td>{r5}</td><td>{rl}</td>'
                 f'<td class="note">{_esc(r["note"])}</td></tr>')
    return (f'<div class="sec trade"><div class="h">🔁 交易复盘纪律（MIT移植 · 事实标签）</div>'
            f'<div class="b"><p class="lh">{_esc(d.get("summary",""))}</p>'
            f'<table class="rectab"><tr><th>标的</th><th>方向</th><th>成交日</th>'
            f'<th>事实标签</th><th>1日</th><th>5日</th><th>最新</th><th>说明</th></tr>{rows}</table>'
            f'</div></div>')


# ---------- 数据新鲜度矩阵 ----------
def _freshness_md(memo):
    d = getattr(memo, "freshness", None) or {}
    if not (d or {}).get("matrix"):
        return []
    L = ["## 🩺 数据新鲜度矩阵（MIT移植）", f"> {d.get('summary','')}"]
    for m in d.get("matrix", []):
        icon = {"fresh": "✅", "aging": "⚠️", "stale": "❌", "unknown": "❓"}.get(m["status"], "")
        L.append(f"- {icon} {m['label']}：{m['note']}")
    L += ["", "---", ""]
    return L

def _freshness_condensed(memo):
    d = getattr(memo, "freshness", None) or {}
    if not (d or {}).get("matrix"):
        return []
    return [f"> 🩺 数据新鲜度：{d.get('summary','')[:120]}", ""]

def _freshness_feishu(memo):
    d = getattr(memo, "freshness", None) or {}
    if not (d or {}).get("matrix"):
        return []
    lines = ["**🩺 数据新鲜度矩阵（MIT移植）**", d.get("summary", "")]
    for m in d.get("matrix", [])[:10]:
        icon = {"fresh": "✅", "aging": "⚠️", "stale": "❌", "unknown": "❓"}.get(m["status"], "")
        lines.append(f"{icon} {m['label']}：{m['note']}")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]

def _freshness_html(memo):
    d = getattr(memo, "freshness", None) or {}
    if not (d or {}).get("matrix"):
        return ""
    rows = ""
    for m in d.get("matrix", []):
        st = m["status"]
        rows += (f'<tr class="fr-{st}"><td>{_esc(m["label"])}</td>'
                 f'<td>{_esc(str(m["as_of"]))}</td>'
                 f'<td>{m["age_days"] if m["age_days"] is not None else "—"}</td>'
                 f'<td><span class="st st-{st}">{st}</span></td>'
                 f'<td class="note">{_esc(m["note"])}</td></tr>')
    return (f'<div class="sec fresh"><div class="h">🩺 数据新鲜度矩阵（MIT移植 · 升级date_guard）</div>'
            f'<div class="b"><p class="lh">{_esc(d.get("summary",""))}</p>'
            f'<table class="rectab"><tr><th>数据源</th><th>最新</th><th>滞后</th>'
            f'<th>状态</th><th>说明</th></tr>{rows}</table>'
            f'<p class="self">基准 TDX 最新交易日：{_esc(str(d.get("tdx_latest","")))}</p>'
            f'</div></div>')


# ---------- 今日行动清单卡（DecisionCard 聚合） ----------
def _action_cards_md(memo):
    d = getattr(memo, "action_cards", None) or {}
    if not (d or {}).get("recommendation"):
        return []
    L = ["## 🎯 今日行动清单卡（DecisionCard · MIT移植）",
         f"> **建议：{d.get('recommendation')}** ｜ 置信：{d.get('confidence')} ｜ 优先级：{d.get('priority')}"]
    if d.get("reasons"):
        L.append("**理由**：")
        for x in d["reasons"][:3]:
            L.append(f"- {x}")
    if d.get("risks"):
        L.append("**风险**：")
        for x in d["risks"][:3]:
            L.append(f"- {x}")
    if d.get("action_required"):
        L.append("**今日必做**：")
        for x in d["action_required"][:6]:
            L.append(f"- {x}")
    L += ["", "---", ""]
    return L

def _action_cards_condensed(memo):
    d = getattr(memo, "action_cards", None) or {}
    if not (d or {}).get("recommendation"):
        return []
    head = f"> 🎯 今日：{d.get('recommendation')}({d.get('confidence')})｜{d.get('priority')}"
    out = [head]
    for a in d.get("action_required", [])[:2]:
        out.append(f">   • {a[:90]}")
    out.append("")
    return out

def _action_cards_feishu(memo):
    d = getattr(memo, "action_cards", None) or {}
    if not (d or {}).get("recommendation"):
        return []
    lines = [f"**🎯 今日行动卡（{d.get('recommendation')}·{d.get('confidence')}·{d.get('priority')}）**"]
    for a in d.get("action_required", [])[:6]:
        lines.append(f"▸ {a}")
    return [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]

def _action_cards_html(memo):
    d = getattr(memo, "action_cards", None) or {}
    if not (d or {}).get("recommendation"):
        return ""
    reasons = "".join(f"<li>{_esc(x)}</li>" for x in d.get("reasons", [])[:4])
    risks = "".join(f"<li>{_esc(x)}</li>" for x in d.get("risks", [])[:4])
    acts = "".join(f'<li class="act">{_esc(x)}</li>' for x in d.get("action_required", [])[:8])
    kp = "".join(f"<li>{_esc(x)}</li>" for x in d.get("key_prices", [])[:4])
    return (f'<div class="sec action"><div class="h">🎯 今日行动清单卡（DecisionCard · MIT移植）</div>'
            f'<div class="b"><p class="banner">建议 <b>{_esc(d.get("recommendation",""))}</b> ｜ '
            f'置信 <b>{_esc(d.get("confidence",""))}</b> ｜ 优先级 <b>{_esc(d.get("priority",""))}</b></p>'
            + (f'<p class="lab">理由</p><ul class="pat">{reasons}</ul>' if reasons else "")
            + (f'<p class="lab">风险</p><ul class="pat">{risks}</ul>' if risks else "")
            + (f'<p class="lab">关键观察位</p><ul class="pat">{kp}</ul>' if kp else "")
            + f'<p class="lab">今日必做</p><ul class="acts">{acts}</ul>'
            f'</div></div>')


def _ic_verdict_html(memo):
    """IC Verdict — 投资委员会裁决（合并 debate + committee, 9段结构第①块）。"""
    d = getattr(memo, "debate", None) or {}
    rows = d.get("debate") or []
    wv = d.get("weighted_vote") or {}
    verdict = d.get("verdict") or ""
    com = getattr(memo, "committee", {}) or {}
    can_buy = memo.can_buy or com.get("can_buy", "—")
    conf = memo.confidence_overall or com.get("overall_confidence", "—")
    pos = com.get("position_pct", "—")

    supports = [r for r in rows if r.get("vote") == "support"][:3]
    opposes = [r for r in rows if r.get("vote") == "oppose"][:3]

    sups = "".join(f'<li><b>✓</b> {_esc(r.get("argument","")[:100])}</li>' for r in supports)
    opps = "".join(f'<li><b>✗</b> {_esc(r.get("argument","")[:100])}</li>' for r in opposes)

    dec_cls = "yes" if str(can_buy).upper() == "YES" else ("watch" if str(can_buy).upper() == "CAUTION" else "no")

    return (f'<div class="sec icv"><div class="h">① IC Verdict · 投资委员会裁决</div>'
            f'<div class="b">'
            f'<div class="icv-top"><span class="icv-dec {dec_cls}">{_esc(str(can_buy))}</span>'
            f'<span class="icv-stat">置信 {conf}%</span>'
            f'<span class="icv-stat">仓位 {_esc(str(pos))}</span></div>'
            f'<div class="icv-cols">'
            f'<div class="icv-col sup-col"><div class="icv-lbl sup-hd">支持</div><ul>{sups or "<li>—</li>"}</ul></div>'
            f'<div class="icv-col opp-col"><div class="icv-lbl opp-hd">反对</div><ul>{opps or "<li>—</li>"}</ul></div>'
            f'</div>'
            f'<p class="icv-reason">{_esc(verdict)}</p>'
            f'</div></div>')


def _evidence_html(memo):
    """Evidence — 统一决策证据（合并 因果推理/板块因果/证据链/安检, 9段结构第⑥块）。"""
    items = []
    causal = getattr(memo, "causal", None) or {}
    nar = getattr(memo, "narrative", None)
    pf = getattr(memo, "preflight", None) or {}
    e = memo.evidence

    # ① 资金证据
    if causal.get("display"):
        items.append(f'<li class="ev-cat cat-funds"><b>资金</b><span>{_esc(causal["display"][:160])}</span></li>')
    elif e and e.claims:
        for c in e.claims[:1]:
            items.append(f'<li class="ev-cat cat-funds"><b>资金</b><span>→ {_esc(c.get("evidence","")[:120])}</span></li>')

    # ② 产业证据
    if causal.get("chain_summary"):
        items.append(f'<li class="ev-cat cat-ind"><b>产业</b><span>{_esc(causal["chain_summary"][:160])}</span></li>')

    # ③ 新闻证据
    if nar and nar.has_data and nar.narratives:
        for n in nar.narratives[:2]:
            if n.get("catalysts"):
                cat = n["catalysts"][0]
                items.append(f'<li class="ev-cat cat-news"><b>新闻</b><span>{_esc(n["board"])}：{_esc(cat.get("title","")[:100])}</span></li>')

    # ④ 全球证据
    gm = getattr(memo, "global_market", None)
    if gm and gm.has_data and gm.one_liner:
        items.append(f'<li class="ev-cat cat-global"><b>全球</b><span>{_esc(gm.one_liner[:140])}</span></li>')

    # ⑤ 安检失败
    if pf.get("checks"):
        fails = [c for c in pf["checks"] if not c.get("passed")]
        if fails:
            ftxt = "；".join(_esc(c.get("reason", "")) for c in fails[:3])
            items.append(f'<li class="ev-cat cat-risk"><b>风险</b><span>{ftxt[:160]}</span></li>')

    if not items:
        # fallback: use thesis headline as summary evidence
        if memo.thesis and memo.thesis.headline:
            items.append(f'<li class="ev-cat cat-funds"><b>摘要</b><span>{_esc(memo.thesis.headline[:200])}</span></li>')
        else:
            return ""

    return (f'<div class="sec evid"><div class="h">⑥ Evidence · 决策证据</div>'
            f'<div class="b"><ul class="ev-lst">{"".join(items)}</ul></div></div>')


def _research_board_html(memo):
    """Research Board — 八层研究员精简投票表（9段结构第⑧块）。"""
    d = getattr(memo, "debate", None) or {}
    rows = d.get("debate") or []
    if not rows:
        bars = getattr(memo, "confidence_bars", {}) or {}
        if not bars:
            return ""
        # fallback from confidence_bars if no debate data
        arrow = {"Bullish": "↑", "Neutral": "→", "Bearish": "↓"}
        icon = {"Bullish": "bull", "Neutral": "neu", "Bearish": "bear"}
        trows = ""
        for layer, v in sorted(bars.items()):
            if not isinstance(v, dict):
                continue
            d_ = v.get("direction", "?")
            a = arrow.get(d_, "?")
            cls = icon.get(d_, "neu")
            trows += f'<tr class="{cls}"><td>{_esc(layer)}</td><td>{a}</td><td class="ri">{_esc(str(v.get("confidence","")))}{"%" if v.get("confidence") else ""}</td></tr>'
        return (f'<div class="sec rbd"><div class="h">⑧ Research Board · 研究员投票</div>'
                f'<div class="b"><table class="rbd-tbl"><tr><th>层</th><th>方向</th><th>置信</th></tr>{trows}</table></div></div>')

    icon = {"support": "✓", "oppose": "✗", "neutral": "○", "absent": "—"}
    trows = ""
    for r in rows:
        v = r.get("vote", "neutral")
        trows += (f'<tr class="{v}"><td>{_esc(r.get("name",""))}</td>'
                  f'<td class="vi">{icon.get(v, "○")}</td>'
                  f'<td class="ri">{r.get("confidence") or ""}</td></tr>')
    return (f'<div class="sec rbd"><div class="h">⑧ Research Board · 研究员投票</div>'
            f'<div class="b"><table class="rbd-tbl">{trows}</table></div></div>')


def _action_list_html(memo):
    """Action List — 合并决策卡 + 明日行动清单 + 交易计划（9段结构第⑤块）。"""
    parts = []
    # ── 决策卡（来自 action_cards.py）
    ac = _action_cards_html(memo)
    if ac:
        parts.append(ac)
    # ── 明日行动清单
    al = getattr(memo, "action_list", []) or []
    if al:
        acts = "".join(
            f'<li class="act"><b>{_esc(a["time"])}</b> {_esc(a["action"])}'
            f'<br><span class="ev">条件：{_esc(a.get("condition","")[:80])}</span></li>'
            for a in al[:5])
        parts.append(f'<div class="act-sub"><div class="act-sub-hd">📋 明日行动清单</div><ul>{acts}</ul></div>')
    # ── 交易计划
    tp = memo.trading_plan
    if tp and tp.no_opportunity:
        parts.append(f'<p class="act-note">🚫 今日无交易机会 — {_esc(tp.no_opportunity_reason)}</p>')
    elif tp and tp.opportunities:
        ops = "".join(
            f'<li class="act"><b>{_esc(op["tier"])}级 {_esc(op["name"])}</b>'
            f'<br><span class="ev">条件：{_esc("；".join(op.get("conditions",[])[:2]))}</span></li>'
            for op in tp.opportunities[:3])
        parts.append(f'<div class="act-sub"><div class="act-sub-hd">🎯 交易计划</div><ul>{ops}</ul></div>')
    if not parts:
        return ""
    inner = "".join(parts)
    return (f'<div class="sec actl"><div class="h">⑤ Action List · 今日行动清单</div>'
            f'<div class="b">{inner}</div></div>')


def _wecom_md(memo):
    """企微群机器人 markdown（9段 Trading OS 版）。"""
    lines = []
    cro = getattr(memo, "cro", None)
    ca = getattr(memo, "cross_asset", None)
    gm = getattr(memo, "global_market", None)
    cf = getattr(memo, "capital_flow", None)
    mv = getattr(memo, "market_movie", None)
    obs = getattr(memo, "observation", None)
    pq = getattr(memo, "panqian", None)
    ic = getattr(memo, "industry_chain", None)

    emoji = _dec_emoji(memo.can_buy)
    color = _dec_color(memo.can_buy)

    # 标题
    lines.append(f"# {emoji} 投资决策备忘录 {memo.trade_date}")

    # ① IC Verdict（合并 debate + IC结论，移到第一块）
    d = getattr(memo, "debate", None) or {}
    wv = d.get("weighted_vote") or {}
    s_sup = wv.get("supports", 0) if isinstance(wv, dict) else 0
    s_opp = wv.get("opposes", 0) if isinstance(wv, dict) else 0
    verdict = d.get("verdict", "") or ""
    com = getattr(memo, "committee", {}) or {}
    pos_pct = com.get("position_pct", "—")
    ic_line = f"> ① IC裁决：<font color=\"{color}\">**{memo.can_buy}**</font>"
    ic_line += f" | 仓位{pos_pct} | 支持{s_sup}:反对{s_opp}"
    if verdict:
        ic_line += f" | {verdict[:60]}"
    if com.get("main_logic"):
        ic_line += f" · {com['main_logic'][:80]}"
    lines.append(ic_line)
    if memo.confidence_bars:
        bar_parts = []
        for layer, v in sorted(memo.confidence_bars.items()):
            if isinstance(v, dict):
                part = f"{layer}:{v.get('direction','?')}"
                if layer in ("L5", "fundamental") and v.get("reason"):
                    part += f" · {v['reason'][:30]}"
                bar_parts.append(part)
            else:
                bar_parts.append(f"{layer}:{v}")
        lines.append(f"> 分项：{' · '.join(bar_parts[:8])}")
    lines.append("")
    # ①-b 真实 IC 辩论（逐层支持/反对方 + 论据）
    lines.extend(_debate_md(memo))

    # ② Today's Trade（CRO Q1/Q2/Q3 - 移到第二块）
    if cro and cro.has_data:
        lines.append("## 🧭 ② Today's Trade · CRO总裁定词")
        lines.append(f"> **裁定：{cro.verdict}** | 偏好分 {cro.score:.0f} | 置信 {cro.confidence:.0%}")
        if cro.q1_headline:
            lines.append(f"> **Q1 今天交易什么**：{cro.q1_headline}")
        if cro.q2_headline:
            lines.append(f"> **Q2 最大边际变化**：{cro.q2_headline}")
            for _b in (cro.q2_bullets or [])[:6]:
                lines.append(f"> · {_b}")
        if cro.q3_headline:
            lines.append(f"> **Q3 市场教会我们什么**：{cro.q3_headline}")
        lines.append("")

    # ③ Money Flow（_migration_md）
    lines.extend(_migration_md(memo))

    # ④ Scenario（_scenario_md）
    lines.extend(_scenario_md(memo))

    # ⑤ Action List（merge _action_cards_md + 明日行动清单 + 交易计划）
    act_lines = _action_cards_md(memo)
    # 明日行动清单
    al = getattr(memo, "action_list", []) or []
    if al:
        act_lines.append("## 📋 明日行动清单")
        for a in al[:5]:
            act_lines.append(f"> **{a['time']}** | {a['action']}")
            act_lines.append(f">   条件：{a['condition'][:80]}")
            act_lines.append(f">   失败：{a['if_fail'][:80]}")
        act_lines.append("")
    # 交易计划
    tp = getattr(memo, "trading_plan", None)
    if tp:
        act_lines.append("## 🎯 交易计划")
        if tp.no_opportunity:
            act_lines.append(f"> 🚫 今日无交易机会 — {tp.no_opportunity_reason[:150]}")
        else:
            for op in tp.opportunities[:3]:
                emoji_op = {"A": "🔥", "B": "📋", "C": "⚡"}.get(op["tier"], "")
                act_lines.append(f"> {emoji_op} **{op['tier']}级 {op['name']}**：{'；'.join(op['conditions'][:2])}")
                act_lines.append(f">    放弃条件：{'；'.join(op['give_up'][:2])}")
        act_lines.append("")
    if act_lines:
        lines.extend(act_lines)

    # ⑥ Evidence（merge _causal_md + narrative 为什么 合并为一段）
    cau_lines = _causal_md(memo)
    nar = getattr(memo, "narrative", None)
    if nar and nar.has_data and nar.narratives:
        cau_lines.append("## 🔍 为什么（板块领涨因果链）")
        cau_lines.append(f"> _{nar.disclaimer}_" + (
            f" · 实时新闻已接入（{nar.news_count}条）" if nar.has_news else
            " · 实时新闻未接入，仅产业链逻辑"))
        for n in nar.narratives[:5]:
            flag = " ⚠️背离" if n.get("divergence") else ""
            cau_lines.append(f"> **{n['board']}**（净流入{n['net_now']}亿，龙头{n.get('leader','')}）{flag}")
            cau_lines.append(f">   {n['one_liner'][:160]}")
            if n.get("verdict"):
                cau_lines.append(f">   → {n['verdict']}（置信{n['confidence']:.0%}）")
        cau_lines.append("")
    if cau_lines:
        lines.extend(cau_lines)

    # ⑦ Market Story（market_movie - 下移）
    if mv and mv.has_data and mv.scenes:
        lines.append("## 🎬 ⑦ Market Story · 市场电影（今日故事）")
        lines.append(f"> _{mv.disclaimer}_")
        for s in mv.scenes:
            lines.append(f"> **[{s.get('time','')}]** {s.get('event','')} → {s.get('implication','')}")
        lines.append(f"> {mv.summary}")
        lines.append("")

    # ⑧ Research Board（精简一行投票）
    rbd = _research_board_line(memo)
    if rbd:
        lines.append(f"## 📊 ⑧ Research Board")
        lines.append(f"> {rbd}")
        lines.append("")

    # ⑨ Learning（_learning_md - 移到末位）
    lines.extend(_learning_md(memo))

    # ——— 附录 ———
    # 跨资产
    if ca and ca.has_data:
        lines.append("## 附录 · 跨资产资金")
        if ca.gold_price:
            arrow = "📈" if ca.gold_change_pct >= 0 else "📉"
            lines.append(f"> 🥇 **黄金** {arrow}{ca.gold_change_pct:+.2f}% "
                         f"（${ca.gold_price:,.0f}） {ca.gold_signal}")
        if ca.commodities:
            comm_str = " · ".join(
                f"{c['name_cn']}{c['change_pct']:+.1f}%" for c in ca.commodities[:5])
            lines.append(f"> 🛢️ **商品** {comm_str}")
        if ca.north_net or ca.south_net:
            lines.append(f"> 🔁 **沪深港通** 北向{ca.north_net:+.0f}亿 / 南向{ca.south_net:+.0f}亿")
        if ca.etf_top_inflow:
            etf_str = "、".join(
                f"{e['name']}(+{e['shares_change_pct']:.1f}%)" for e in ca.etf_top_inflow[:3])
            lines.append(f"> 📊 **ETF净申购** {etf_str}")
        if ca.etf_top_outflow:
            etf_out = "、".join(
                f"{e['name']}({e['shares_change_pct']:.1f}%)" for e in ca.etf_top_outflow[:2])
            lines.append(f"> 📉 **ETF净赎回** {etf_out}")
        if ca.flow_one_liner:
            lines.append(f"> 🌐 资金情报：{ca.flow_one_liner}")
        lines.append("")

    # 全球市场看板
    if gm and gm.has_data and gm.board:
        lines.append("## 附录 · 全球市场看板")
        for b in gm.board:
            if b["status"] == "ok" and b["change_pct"] is not None:
                chg = f"{b['change_pct']:+.1f}%"
            elif b["status"] == "blocked":
                chg = "未接入"
            else:
                chg = "—"
            lines.append(f"> {b['name']}（{'★'*b['importance']}）{chg}")
        lines.append(f"> AI一句话：{gm.one_liner}")
        lines.append("")

    # 资金面明细
    if cf and cf.has_data:
        lines.append("## 附录 · 资金面明细（流，不是价）")
        if cf.etf_total_net_yi:
            sign = "净赎回" if cf.etf_total_net_yi < 0 else "净申购"
            lines.append(f"> ETF整体：{sign} {abs(cf.etf_total_net_yi):.0f}亿")
        lines.append(f"> 沪深港通：南向 {cf.south_net_yi:+.0f}亿" + (f" / 北向 {cf.north_net_yi:+.0f}亿" if cf.north_net_yi else " / 北向未披露"))
        for m in cf.migration:
            lines.append(f"> {m['source']} → {m['target']} {'★'*m['star']}（{m['note']}）")
        lines.append(f"> AI一句话：{cf.one_liner}")
        lines.append("")

    # 新发现
    if obs and obs.has_data and obs.discoveries:
        lines.append("## 附录 · 今日新发现")
        for i, d_ in enumerate(obs.discoveries[:4], 1):
            dt_, dn_ = _fmt_disc(d_)
            lines.append(f"> {i}. {dt_}")
            if dn_:
                lines.append(f">    {dn_[:150]}")
        lines.append("")

    # 持仓分层 / 复盘 / 新鲜度
    lines.extend(_position_layer_md(memo))
    lines.extend(_trade_review_md(memo))
    lines.extend(_freshness_md(memo))

    # 盘前纪要
    if pq and pq.has_data:
        lines.extend(_panqian_md_lines(pq, compact=False))
    # L3.5 产业链推理
    if ic and ic.has_data:
        lines.extend(_industry_chain_md_lines(ic, compact=False))

    lines.append("")
    lines.append("> 💡 CIO Agent 生成 · 仅供研究，不构成投资建议。")
    return "\n".join(lines)


def _wecom_md_condensed(memo, max_bytes=3900):
    """企微 markdown 精简版（9段核心，控制在 4096 字节内）。"""
    t = memo.thesis
    cro = getattr(memo, "cro", None)
    ca = getattr(memo, "cross_asset", None)
    gm = getattr(memo, "global_market", None)
    cf = getattr(memo, "capital_flow", None)
    mv = getattr(memo, "market_movie", None)
    obs = getattr(memo, "observation", None)
    pq = getattr(memo, "panqian", None)
    ic = getattr(memo, "industry_chain", None)

    emoji = _dec_emoji(memo.can_buy)
    color = _dec_color(memo.can_buy)

    L = []
    L.append(f"# {emoji} 投资决策 {memo.trade_date}")

    # ① IC Verdict（合并 debate + IC 结论，第一行）
    d = getattr(memo, "debate", None) or {}
    wv = d.get("weighted_vote") or {}
    s_sup = wv.get("supports", 0) if isinstance(wv, dict) else 0
    s_opp = wv.get("opposes", 0) if isinstance(wv, dict) else 0
    verdict = d.get("verdict", "") or ""
    com = getattr(memo, "committee", {}) or {}
    pos_pct = com.get("position_pct", "—")
    vic = f"> ① IC裁决：<font color=\"{color}\">**{memo.can_buy}**</font>"
    vic += f" | 仓位{pos_pct} | 支持{s_sup}:反对{s_opp}"
    if verdict:
        vic += f" | {verdict[:60]}"
    L.append(vic)
    L.append("")
    # ①-b 真实 IC 辩论（支持/反对方，补 ① 只给计数之不足）
    L.extend(_debate_condensed(memo))

    # ② Today's Trade（CRO Q1）
    if cro and cro.has_data:
        q1 = cro.q1_headline[:90] if cro.q1_headline else cro.verdict
        L.append(f"🧭 **② 今天交易**：{q1}")
        L.append("")

    # ③ Money Flow
    L.extend(_migration_condensed(memo))

    # ④ Scenario
    L.extend(_scenario_condensed(memo))

    # ⑤ Action List
    L.extend(_action_cards_condensed(memo))

    # ⑥ Evidence（统一：因果+叙事合一行）
    L.extend(_causal_condensed(memo))
    # 叙事证据合入上面 causal 行，不再独立「为什么」

    # ⑦ Market Story（下移）
    if mv and mv.has_data:
        L.append(f"📽 **⑦ 故事**：{mv.summary[:56]}")
        L.append("")

    # ⑧ Research Board（精简投票一行）
    rbd_s = _research_board_line(memo)
    if rbd_s:
        L.append(rbd_s)
        L.append("")

    # ⑨ Learning（末位）
    L.extend(_learning_condensed(memo))

    # ——— 附录 ———
    # 跨资产
    if ca and ca.has_data:
        parts = []
        if ca.gold_price:
            parts.append(f"🥇黄金{ca.gold_change_pct:+.1f}%")
        if ca.commodities:
            parts.append("🛢️" + "/".join(
                f"{c['name_cn'][:4]}{c['change_pct']:+.1f}%" for c in ca.commodities[:3]))
        if ca.north_net or ca.south_net:
            parts.append(f"🔁南向{ca.south_net:+.0f}亿")
        if ca.etf_top_inflow:
            parts.append("📊ETF净申购" + "/".join(
                e['name'][:6] for e in ca.etf_top_inflow[:2]))
        if parts:
            L.append("**跨资产** " + " · ".join(parts))
            L.append("")
    # 全球
    if gm and gm.has_data:
        okk = [b["name"] for b in gm.board if b["status"] == "ok" and b["change_pct"] is not None]
        L.append(f"**全球** {'/'.join(okk[:4])}（纳指等未接入）")
        L.append("")
    # 资金面
    if cf and cf.has_data:
        mig_s = "、".join(f"{m['source']}→{m['target']}" for m in cf.migration[:2])
        L.append(f"**资金面** {mig_s}")
        L.append("")
    # 新发现
    if obs and obs.has_data and obs.discoveries:
        for d_ in obs.discoveries[:2]:
            dt_, _ = _fmt_disc(d_)
            L.append(f"🌟 **新发现** {dt_}")
        L.append("")
    # 核心观点（作为总结）
    if t and t.headline:
        L.append(f"**核心**：{t.headline[:90]}")
        L.append("")
    # 持仓/复盘/新鲜度
    L.extend(_position_layer_condensed(memo))
    L.extend(_trade_review_condensed(memo))
    L.extend(_freshness_condensed(memo))
    # 盘前
    if pq and pq.has_data:
        L.extend(_panqian_md_lines(pq, compact=True))
    # L3.5
    if ic and ic.has_data:
        L.extend(_industry_chain_md_lines(ic, compact=True))

    L.append("> 完整报告见飞书卡片 / HTML")
    md = "\n".join(L)
    if len(md.encode("utf-8")) > max_bytes:
        while L and len("\n".join(L).encode("utf-8")) > max_bytes:
            L.pop()
        md = "\n".join(L)
    return md


# ═══════════════════════════════════════════════════════
#  飞书 卡片
# ═══════════════════════════════════════════════════════

def _feishu_card(memo):
    """飞书 interactive card（9段 Trading OS 版）。"""
    emoji = _dec_emoji(memo.can_buy)
    color = _dec_color(memo.can_buy)
    t = memo.thesis
    elements = []

    # ── 标题块（决策 emoji + can_buy）──
    conf_bars = ""
    if memo.confidence_bars:
        parts = []
        for layer, v in sorted(memo.confidence_bars.items()):
            if isinstance(v, dict):
                dir_ = v.get("direction", "?")
                arrow = {"Bullish": "↑", "Neutral": "→", "Bearish": "↓"}.get(dir_, "?")
                part = f"{layer}:{arrow}"
                if layer in ("L5", "fundamental") and v.get("reason"):
                    part += f" · {v['reason'][:30]}"
                parts.append(part)
            else:
                parts.append(f"{layer}:{v}")
        conf_bars = " | " + " · ".join(parts[:8])
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content":
                 f"{emoji} **决策 {memo.can_buy}** | 置信度 **{memo.confidence_overall}%** | 确信度 {t.conviction}{conf_bars}"}
    })
    elements.append({"tag": "hr"})

    # ① IC Verdict — merged debate + committee, one line
    d = getattr(memo, "debate", None) or {}
    wv = d.get("weighted_vote") or {}
    verdict = d.get("verdict", "") or ""
    com = getattr(memo, "committee", {}) or {}
    icv_lines = ["**① IC Verdict · 投资委员会裁决**"]
    if com:
        if com.get("main_logic"):
            icv_lines.append(f"主要逻辑：{com['main_logic']}")
        if com.get("risk_summary"):
            icv_lines.append(f"风险：{com['risk_summary']}")
        if com.get("position_pct"):
            icv_lines.append(f"仓位护栏：{com['position_pct']}")
    if verdict:
        icv_lines.append(f"裁决：{verdict}")
    if wv.get("ratio"):
        icv_lines.append(f"加权投票：{wv['ratio']}")
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(icv_lines)}})
    # ①-b 真实 IC 辩论（逐层支持/反对方，补 ① 只给裁决/比例之不足）
    elements.extend(_debate_feishu(memo))
    elements.append({"tag": "hr"})

    # ② Today's Trade — CRO Q1/Q2/Q3
    cro = getattr(memo, "cro", None)
    if cro and cro.has_data:
        cro_lines = ["**② Today's Trade · CRO 总裁定词**"]
        cro_lines.append(f"**裁定：{cro.verdict}** | 偏好分 {cro.score:.0f} | 置信 {cro.confidence:.0%}")
        if cro.q1_headline:
            cro_lines.append(f"**Q1 今天交易什么**：{cro.q1_headline}")
        if cro.q2_headline:
            cro_lines.append(f"**Q2 最大边际变化**：{cro.q2_headline}")
            for _b in (cro.q2_bullets or [])[:6]:
                cro_lines.append(f"· {_b}")
        if cro.q3_headline:
            cro_lines.append(f"**Q3 市场教会我们什么**：{cro.q3_headline}")
        if cro.q1_sectors:
            secs = "、".join(s.get("name", "") for s in cro.q1_sectors[:3])
            cro_lines.append(f"主攻板块：{secs}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(cro_lines)}})
        elements.append({"tag": "hr"})

    # ③ Money Flow — _migration_feishu
    mig_els = _migration_feishu(memo)
    if mig_els:
        elements.extend(mig_els)
        elements.append({"tag": "hr"})

    # ④ Scenario
    sce_els = _scenario_feishu(memo)
    if sce_els:
        elements.extend(sce_els)
        elements.append({"tag": "hr"})

    # ⑤ Action List — merged action_cards + 交易计划 + 明日行动清单
    al_lines = ["**⑤ Action List · 今日行动清单**"]
    ac = getattr(memo, "action_cards", None) or {}
    if ac.get("recommendation"):
        al_lines.append(f"🎯 **行动卡（{ac.get('recommendation')}·{ac.get('confidence')}·{ac.get('priority')}）**")
        for a in ac.get("action_required", [])[:6]:
            al_lines.append(f"▸ {a}")
    al = getattr(memo, "action_list", []) or []
    if al:
        al_lines.append("📋 **明日行动清单**")
        for a in al[:5]:
            al_lines.append(f"**{a['time']}** | {a['action']}")
            al_lines.append(f"  条件：{a['condition'][:100]}")
            al_lines.append(f"  失败：{a['if_fail'][:100]}")
            al_lines.append("")
    tp = memo.trading_plan
    if tp.no_opportunity:
        al_lines.append("🚫 **今日无交易机会**")
        al_lines.append(tp.no_opportunity_reason[:200])
    else:
        al_lines.append("🎯 **交易计划**")
        for op in tp.opportunities[:4]:
            tier_emoji = {"A": "🔥", "B": "📋", "C": "⚡"}.get(op["tier"], "📌")
            al_lines.append(f"{tier_emoji} **{op['tier']}级**：{op['name']}")
            al_lines.append(f"  ✅ {'；'.join(op['conditions'][:2])}")
            al_lines.append(f"  ❌ {'；'.join(op['give_up'][:2])}")
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(al_lines)}})
    elements.append({"tag": "hr"})

    # ⑥ Evidence — merged causal + narrative
    ev_lines = ["**⑥ Evidence · 决策证据**"]
    c = getattr(memo, "causal", None) or {}
    if c.get("causes"):
        ci = c.get("chain_insights", {}) or {}
        for sec, cd in c["causes"].items():
            ev_lines.append(f"**{sec}**：{cd.get('display', '')}")
            if sec in ci:
                ev_lines.append(f"↳ {ci[sec][:90]}")
    nar = getattr(memo, "narrative", None)
    if nar and nar.has_data and nar.narratives:
        for n in nar.narratives[:5]:
            flag = " ⚠️背离" if n.get("divergence") else ""
            ev_lines.append(f"- **{n['board']}**（净流入{n['net_now']}亿，龙头{n.get('leader','')}）{flag}")
            ev_lines.append(f"  {n['one_liner'][:150]}")
            if n.get("verdict"):
                ev_lines.append(f"  → {n['verdict']}（置信{n['confidence']:.0%}）")
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(ev_lines)}})
    elements.append({"tag": "hr"})

    # ⑦ Market Story — movie block
    mv = getattr(memo, "market_movie", None)
    if mv and mv.has_data and mv.scenes:
        mv_lines = ["**⑦ Market Story · 市场电影（今日故事）**  _" + mv.disclaimer + "_"]
        for s in mv.scenes:
            mv_lines.append(f"- **[{s.get('time','')}]** {s.get('event','')} → {s.get('implication','')}")
        mv_lines.append(f"\n{mv.summary}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(mv_lines)}})
        elements.append({"tag": "hr"})

    # ⑧ Research Board — one line vote summary
    rb_line = _research_board_line(memo)
    if rb_line:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": rb_line}})
        elements.append({"tag": "hr"})

    # ⑨ Learning
    learn_els = _learning_feishu(memo)
    if learn_els:
        elements.extend(learn_els)
        elements.append({"tag": "hr"})

    # ── Appendix ──
    # 跨资产
    ca = getattr(memo, "cross_asset", None)
    if ca and ca.has_data:
        ca_lines = ["**跨资产资金**"]
        if ca.gold_price:
            arrow = "📈" if ca.gold_change_pct >= 0 else "📉"
            ca_lines.append(f"🥇 **黄金** {arrow}{ca.gold_change_pct:+.2f}%（${ca.gold_price:,.0f}）{ca.gold_signal}")
        if ca.commodities:
            ca_lines.append("🛢️ **商品** " + " · ".join(
                f"{c['name_cn']}{c['change_pct']:+.1f}%" for c in ca.commodities[:5]))
        if ca.north_net or ca.south_net:
            ca_lines.append(f"🔁 **沪深港通** 北向{ca.north_net:+.0f}亿 / 南向{ca.south_net:+.0f}亿")
        if ca.etf_top_inflow:
            ca_lines.append("📊 **ETF净申购** " + "、".join(
                f"{e['name']}(+{e['shares_change_pct']:.1f}%)" for e in ca.etf_top_inflow[:3]))
        if ca.etf_top_outflow:
            ca_lines.append("📉 **ETF净赎回** " + "、".join(
                f"{e['name']}({e['shares_change_pct']:.1f}%)" for e in ca.etf_top_outflow[:2]))
        if ca.flow_one_liner:
            ca_lines.append(f"🌐 资金情报：{ca.flow_one_liner}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(ca_lines)}})
        elements.append({"tag": "hr"})

    # 全球
    gm = getattr(memo, "global_market", None)
    if gm and gm.has_data and gm.board:
        gm_lines = ["**🌏 全球市场看板**"]
        for b in gm.board:
            if b["status"] == "ok" and b["change_pct"] is not None:
                chg = f"{b['change_pct']:+.1f}%"
            elif b["status"] == "blocked":
                chg = "未接入"
            else:
                chg = "—"
            gm_lines.append(f"- {b['name']}（{'★'*b['importance']}）{chg}")
        gm_lines.append(f"\nAI一句话：{gm.one_liner}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(gm_lines)}})
        elements.append({"tag": "hr"})

    # 资金面
    cf = getattr(memo, "capital_flow", None)
    if cf and cf.has_data:
        cf_lines = ["**🌐 资金面明细（流，不是价）**"]
        if cf.etf_total_net_yi:
            sign = "净赎回" if cf.etf_total_net_yi < 0 else "净申购"
            cf_lines.append(f"ETF整体：{sign} {abs(cf.etf_total_net_yi):.0f}亿")
        cf_lines.append(f"沪深港通：南向 {cf.south_net_yi:+.0f}亿" + (f" / 北向 {cf.north_net_yi:+.0f}亿" if cf.north_net_yi else " / 北向未披露"))
        for m in cf.migration:
            cf_lines.append(f"- {m['source']} → {m['target']} {'★'*m['star']}（{m['note']}）")
        cf_lines.append(f"\nAI一句话：{cf.one_liner}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(cf_lines)}})
        elements.append({"tag": "hr"})

    # 新发现
    obs = getattr(memo, "observation", None)
    if obs and obs.has_data and obs.discoveries:
        disc_lines = ["**🌟 今日新发现**"]
        for i, disc in enumerate(obs.discoveries[:4], 1):
            dt_, dn_ = _fmt_disc(disc)
            disc_lines.append(f"{i}. {dt_}")
            if dn_:
                disc_lines.append(f"  {dn_[:150]}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(disc_lines)}})
        elements.append({"tag": "hr"})

    # 盘前
    pq = getattr(memo, "panqian", None)
    if pq and pq.has_data:
        pq_lines = _panqian_md_lines(pq, compact=False)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(pq_lines)}})
        elements.append({"tag": "hr"})

    # L3.5 产业链
    ic = getattr(memo, "industry_chain", None)
    if ic and ic.has_data:
        ic_lines = _industry_chain_md_lines(ic, compact=False)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(ic_lines)}})
        elements.append({"tag": "hr"})

    # 持仓/复盘/新鲜度
    for fn in (_position_layer_feishu, _trade_review_feishu, _freshness_feishu):
        els = fn(memo)
        if els:
            elements.extend(els)
            elements.append({"tag": "hr"})

    elements.append({"tag": "note", "elements": [{"tag": "plain_text",
                   "content": f"CIO Agent ({memo.generated_at[:16]}) · 仅供研究不构成投资建议"}]})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text",
                       "content": f"{emoji} 投资决策备忘录 {memo.trade_date}"},
            "template": color,
        },
        "elements": elements,
    }


# ═══════════════════════════════════════════════════════
#  Server酱 微信推送
# ═══════════════════════════════════════════════════════

def _serverchan_md(memo):
    """Server酱微信推送（9段 Trading OS 版）。"""
    cro = getattr(memo, "cro", None)
    ca = getattr(memo, "cross_asset", None)
    gm = getattr(memo, "global_market", None)
    cf = getattr(memo, "capital_flow", None)
    mv = getattr(memo, "market_movie", None)
    nar = getattr(memo, "narrative", None)
    obs = getattr(memo, "observation", None)
    pq = getattr(memo, "panqian", None)
    ic = getattr(memo, "industry_chain", None)
    tp = getattr(memo, "trading_plan", None)
    al = getattr(memo, "action_list", []) or []

    lines = []
    emoji = _dec_emoji(memo.can_buy)

    lines.append(f"## {emoji} 投资决策备忘录 {memo.trade_date}")

    # ① IC Verdict（合并 debate + IC结论，一行）
    d = getattr(memo, "debate", None) or {}
    wv = d.get("weighted_vote") or {}
    s_sup = wv.get("supports", 0) if isinstance(wv, dict) else 0
    s_opp = wv.get("opposes", 0) if isinstance(wv, dict) else 0
    verdict = d.get("verdict", "") or ""
    com = getattr(memo, "committee", {}) or {}
    pos_pct = com.get("position_pct", "—")
    ic_line = f"### ① IC裁决：**{memo.can_buy}** | 仓位{pos_pct} | 支持{s_sup}:反对{s_opp}"
    if verdict:
        ic_line += f" | {verdict[:60]}"
    if com.get("main_logic"):
        ic_line += f" · {com['main_logic'][:80]}"
    lines.append(ic_line)
    if memo.confidence_bars:
        bar_parts = []
        for layer, v in list(memo.confidence_bars.items())[:6]:
            if isinstance(v, dict):
                part = f"{layer}:{v.get('direction','?')}"
                if layer in ("L5", "fundamental") and v.get("reason"):
                    part += f" · {v['reason'][:30]}"
                bar_parts.append(part)
            else:
                bar_parts.append(f"{layer}:{v}")
        lines.append(f"分项：{' · '.join(bar_parts)}")
    lines.append("")
    # ①-b 真实 IC 辩论（逐层支持/反对方 + 论据）
    lines.extend(_debate_md(memo))

    # ② Today's Trade（CRO Q1/Q2/Q3）
    if cro and cro.has_data:
        lines.append("### 🧭 ② Today's Trade · CRO总裁定词")
        lines.append(f"**裁定：{cro.verdict}** | 偏好分 {cro.score:.0f} | 置信 {cro.confidence:.0%}")
        if cro.q1_headline:
            lines.append(f"**Q1 今天交易什么**：{cro.q1_headline}")
        if cro.q2_headline:
            lines.append(f"**Q2 最大边际变化**：{cro.q2_headline}")
            for _b in (cro.q2_bullets or [])[:6]:
                lines.append(f"· {_b}")
        if cro.q3_headline:
            lines.append(f"**Q3 市场教会我们什么**：{cro.q3_headline}")
        lines.append("")

    # ③ Money Flow（资金迁移）
    lines.extend(_migration_md(memo))

    # ④ Scenario（情景推演）
    lines.extend(_scenario_md(memo))

    # ⑤ Action List（合并 action_cards + 明日行动清单 + 交易计划）
    act_lines = _action_cards_md(memo)
    if al:
        act_lines.append("### 📋 明日行动清单")
        for a in al[:5]:
            act_lines.append(f"**{a['time']}** {a['action']}")
            act_lines.append(f"  失败→{a['if_fail'][:80]}")
        act_lines.append("")
    if tp:
        act_lines.append("### 🎯 交易计划")
        if tp.no_opportunity:
            act_lines.append(f"🚫 今日无交易机会 — {tp.no_opportunity_reason[:150]}")
        else:
            for op in tp.opportunities[:3]:
                tier_emoji = {"A": "🔥", "B": "📋", "C": "⚡"}.get(op["tier"], "")
                act_lines.append(f"{tier_emoji} **{op['tier']}级 {op['name']}**")
                act_lines.append(f"  条件：{'；'.join(op['conditions'][:2])}")
                act_lines.append(f"  放弃：{'；'.join(op['give_up'][:2])}")
        act_lines.append("")
    if act_lines:
        lines.extend(act_lines)

    # ⑥ Evidence（合并 causal + narrative）
    cau_lines = _causal_md(memo)
    if nar and nar.has_data and nar.narratives:
        cau_lines.append("### 🔍 为什么（板块领涨因果链）")
        cau_lines.append(f"_{nar.disclaimer}_" + (
            f" · 实时新闻已接入（{nar.news_count}条）" if nar.has_news else
            " · 实时新闻未接入，仅产业链逻辑"))
        for n in nar.narratives[:5]:
            flag = " ⚠️背离" if n.get("divergence") else ""
            cau_lines.append(f"- **{n['board']}**（净流入{n['net_now']}亿，龙头{n.get('leader','')}）{flag}")
            cau_lines.append(f"  {n['one_liner'][:160]}")
            if n.get("verdict"):
                cau_lines.append(f"  → {n['verdict']}（置信{n['confidence']:.0%}）")
        cau_lines.append("")
    if cau_lines:
        lines.extend(cau_lines)

    # ⑦ Market Story（市场电影）
    if mv and mv.has_data and mv.scenes:
        lines.append("### 🎬 ⑦ Market Story · 市场电影（今日故事）")
        lines.append(f"_{mv.disclaimer}_")
        for s in mv.scenes:
            lines.append(f"- **[{s.get('time','')}]** {s.get('event','')} → {s.get('implication','')}")
        lines.append(f"{mv.summary}")
        lines.append("")

    # ⑧ Research Board（一行投票摘要）
    rbd = _research_board_line(memo)
    if rbd:
        lines.append("### 📊 ⑧ Research Board")
        lines.append(rbd)
        lines.append("")

    # ⑨ Learning（学习复盘，末位）
    lines.extend(_learning_md(memo))

    # ——— 附录 ———
    # 跨资产资金
    if ca and ca.has_data:
        lines.append("### 附录 · 跨资产资金")
        if ca.gold_price:
            arrow = "📈" if ca.gold_change_pct >= 0 else "📉"
            lines.append(f"🥇 **黄金** {arrow}{ca.gold_change_pct:+.2f}%（${ca.gold_price:,.0f}）{ca.gold_signal}")
        if ca.commodities:
            comm_str = " · ".join(
                f"{c['name_cn']}{c['change_pct']:+.1f}%" for c in ca.commodities[:5])
            lines.append(f"🛢️ **商品** {comm_str}")
        if ca.north_net or ca.south_net:
            lines.append(f"🔁 **沪深港通** 北向{ca.north_net:+.0f}亿 / 南向{ca.south_net:+.0f}亿")
        if ca.etf_top_inflow:
            etf_str = "、".join(
                f"{e['name']}(+{e['shares_change_pct']:.1f}%)" for e in ca.etf_top_inflow[:3])
            lines.append(f"📊 **ETF净申购** {etf_str}")
        if ca.etf_top_outflow:
            etf_out = "、".join(
                f"{e['name']}({e['shares_change_pct']:.1f}%)" for e in ca.etf_top_outflow[:2])
            lines.append(f"📉 **ETF净赎回** {etf_out}")
        if ca.flow_one_liner:
            lines.append(f"🌐 资金情报：{ca.flow_one_liner}")
        lines.append("")

    # 全球市场看板
    if gm and gm.has_data and gm.board:
        lines.append("### 附录 · 全球市场看板")
        for b in gm.board:
            if b["status"] == "ok" and b["change_pct"] is not None:
                chg = f"{b['change_pct']:+.1f}%"
            elif b["status"] == "blocked":
                chg = "未接入"
            else:
                chg = "—"
            lines.append(f"- {b['name']}（{'★'*b['importance']}）{chg}")
        lines.append(f"AI一句话：{gm.one_liner}")
        lines.append("")

    # 资金面明细
    if cf and cf.has_data:
        lines.append("### 附录 · 资金面明细（流，不是价）")
        if cf.etf_total_net_yi:
            sign = "净赎回" if cf.etf_total_net_yi < 0 else "净申购"
            lines.append(f"ETF整体：{sign} {abs(cf.etf_total_net_yi):.0f}亿")
        lines.append(f"沪深港通：南向 {cf.south_net_yi:+.0f}亿" + (f" / 北向 {cf.north_net_yi:+.0f}亿" if cf.north_net_yi else " / 北向未披露"))
        for m in cf.migration:
            lines.append(f"- {m['source']} → {m['target']} {'★'*m['star']}（{m['note']}）")
        lines.append(f"AI一句话：{cf.one_liner}")
        lines.append("")

    # 今日新发现
    if obs and obs.has_data and obs.discoveries:
        lines.append("### 附录 · 今日新发现")
        for i, d_ in enumerate(obs.discoveries[:4], 1):
            dt_, dn_ = _fmt_disc(d_)
            lines.append(f"{i}. {dt_}")
            if dn_:
                lines.append(f"  {dn_[:150]}")
        lines.append("")

    # 盘前纪要
    if pq and pq.has_data:
        lines.extend(_panqian_md_lines(pq, compact=False))
    # L3.5 产业链推理
    if ic and ic.has_data:
        lines.extend(_industry_chain_md_lines(ic, compact=False))

    # 持仓分层 / 复盘 / 新鲜度
    lines.extend(_position_layer_md(memo))
    lines.extend(_trade_review_md(memo))
    lines.extend(_freshness_md(memo))

    lines.append("")
    lines.append("> CIO Agent 生成 · 仅供研究不构成投资建议")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
#  推送接口
# ═══════════════════════════════════════════════════════

def push_wecom(webhook: str, memo) -> tuple:
    """推送到企业微信（使用精简版，规避 4096 字节上限）。"""
    md = _wecom_md_condensed(memo)
    payload = {"msgtype": "markdown", "markdown": {"content": md}}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(webhook, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
        return resp.get("errcode") == 0, resp
    except Exception as e:
        return False, str(e)[:200]


def push_feishu(webhook: str, memo, secret: str = None) -> tuple:
    """推送到飞书。"""
    card = _feishu_card(memo)
    body = {"msg_type": "interactive", "card": card}
    if secret:
        ts = str(int(time.time()))
        string_to_sign = f"{ts}\n{secret}"
        hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                             digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        body["timestamp"] = ts
        body["sign"] = sign
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(webhook, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
        ok = resp.get("code") == 0 or resp.get("StatusMessage") == "success"
        return ok, resp
    except Exception as e:
        return False, str(e)[:200]


def push_serverchan(sendkey: str, memo) -> tuple:
    """推送到 Server酱（微信）。"""
    API = "https://sctapi.ftqq.com"
    md = _serverchan_md(memo)
    title = f"投资决策 {memo.trade_date} | {memo.can_buy} 置信度{memo.confidence_overall}%"
    url = f"{API}/{sendkey}.send"
    payload = {"title": title, "desp": md}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
        return resp.get("code") == 0, resp
    except Exception as e:
        return False, str(e)[:200]


# ═══════════════════════════════════════════════════════
#  本地 HTML 备忘录（可打开复核，含 ⑭ 跨资产资金）
# ═══════════════════════════════════════════════════════

def _esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _memo_html(memo):
    """生成本地可打开的 HTML 版 Trading OS 备忘录（9段核心 + 附录）。"""
    ca = getattr(memo, "cross_asset", None)
    obs = getattr(memo, "observation", None)
    cro = getattr(memo, "cro", None)
    gm = getattr(memo, "global_market", None)
    cf = getattr(memo, "capital_flow", None)
    mv = getattr(memo, "market_movie", None)
    pq = getattr(memo, "panqian", None)
    ic = getattr(memo, "industry_chain", None)

    dec_color = {"YES": "#2e7d32", "NO": "#c62828", "CAUTION": "#ef6c00"}.get(memo.can_buy, "#555")
    parts = []

    # 标题
    parts.append(f'<h1 style="color:{dec_color}">投资决策备忘录 {_esc(memo.trade_date)} '
                 f'<span class="dec" style="background:{dec_color}">{_esc(memo.can_buy)}</span></h1>')
    parts.append(f'<p class="sub">置信度 <b>{memo.confidence_overall}%</b> · 生成于 {_esc(memo.generated_at[:16])}</p>')

    # ═══════ 9段核心结构 ═══════
    # ① IC Verdict（投资委员会裁决：YES/NO + 支持/反对 + 仓位）
    icv = _ic_verdict_html(memo)
    if icv:
        parts.append(icv)

    # ①-b 真实 IC 辩论（L1~L8 逐层支持/反对 + 论据，补 ① 只截断 100 字之不足）
    dbh = _debate_html(memo)
    if dbh:
        parts.append(dbh)

    # ② Today's Trade（CRO 总裁定词：Q1/Q2/Q3，前置到第二块）
    if cro and cro.has_data:
        cro_body = (f'<p><b>裁定：{_esc(cro.verdict)}</b> | 偏好分 {cro.score:.0f} | 置信 {cro.confidence:.0%}</p>')
        if cro.q1_headline:
            cro_body += f'<p><b>Q1 今天交易什么：</b>{_esc(cro.q1_headline)}</p>'
        if cro.q2_headline:
            cro_body += f'<p><b>Q2 最大边际变化：</b>{_esc(cro.q2_headline)}</p>'
            for _b in (cro.q2_bullets or [])[:6]:
                cro_body += f'<p class="ev">· {_esc(_b)}</p>'
        if cro.q3_headline:
            cro_body += f'<p><b>Q3 市场教会我们什么：</b>{_esc(cro.q3_headline)}</p>'
        parts.append(f'<div class="sec cro"><div class="h">② Today\'s Trade · 今天交易什么</div>'
                     f'<div class="b">{cro_body}</div></div>')

    # ③ Money Flow（资金迁移：昨天→今天→明天）
    parts.append(_migration_html(memo))

    # ③-b 因果推理（钱为什么去那：驱动 hunt + 产业链下钻）
    cbh = _causal_html(memo)
    if cbh:
        parts.append(cbh)

    # ④ Scenario（情景推演：明日最大摆动变量）
    parts.append(_scenario_html(memo))

    # ⑤ Action List（合并：决策卡 + 明日行动清单 + 交易计划）
    alh = _action_list_html(memo)
    if alh:
        parts.append(alh)

    # ⑥ Evidence（统一决策证据：资金/产业/新闻/全球/风险）
    evi = _evidence_html(memo)
    if evi:
        parts.append(evi)

    # ⑦ Market Story（市场叙事，下移）
    if mv and mv.has_data and mv.scenes:
        mv_body = f'<p class="disc"><i>🎬 {_esc(mv.disclaimer)}</i></p>'
        mv_items = ""
        for s in mv.scenes:
            mv_items += (f'<li><b>[{_esc(s.get("time",""))}]</b> {_esc(s.get("event",""))}'
                         f'<br><span class="ev">→ {_esc(s.get("implication",""))}</span></li>')
        mv_body += f'<ul>{mv_items}</ul>'
        mv_body += f'<p class="link">{_esc(mv.summary)}</p>'
        parts.append(f'<div class="sec movie"><div class="h">⑦ Market Story · 今日叙事</div>'
                     f'<div class="b">{mv_body}</div></div>')

    # ⑧ Research Board（研究员投票表）
    rbd = _research_board_html(memo)
    if rbd:
        parts.append(rbd)

    # ⑨ Learning（学习复盘，末位）
    parts.append(_learning_html(memo))

    # ═══════ 附录（仅供参考，不编号） ═══════
    parts.append('<div class="appendix-hd">—— 附录 · 参考数据 ——</div>')

    # 跨资产资金
    if ca and ca.has_data:
        ca_html = ""
        if ca.gold_price:
            arrow = "▲" if ca.gold_change_pct >= 0 else "▼"
            ca_html += (f'<p>🥇 <b>黄金</b> {arrow}{ca.gold_change_pct:+.2f}%'
                        f'（${ca.gold_price:,.0f}）{_esc(ca.gold_signal)}</p>')
        if ca.commodities:
            ca_html += '<p>🛢️ <b>商品</b> ' + " · ".join(
                f'{_esc(c["name_cn"])}{c["change_pct"]:+.1f}%' for c in ca.commodities[:5]) + '</p>'
        if ca.north_net or ca.south_net:
            ca_html += (f'<p>🔁 <b>沪深港通</b> 北向{ca.north_net:+.0f}亿 / '
                        f'南向{ca.south_net:+.0f}亿</p>')
        if ca.etf_top_inflow:
            ca_html += '<p>📊 <b>ETF净申购</b> ' + "、".join(
                f'{_esc(e["name"])}(+{e["shares_change_pct"]:.1f}%)' for e in ca.etf_top_inflow[:3]) + '</p>'
        if ca.etf_top_outflow:
            ca_html += '<p>📉 <b>ETF净赎回</b> ' + "、".join(
                f'{_esc(e["name"])}({e["shares_change_pct"]:.1f}%)' for e in ca.etf_top_outflow[:2]) + '</p>'
        if ca.flow_one_liner:
            ca_html += f'<p>🌐 资金情报：{_esc(ca.flow_one_liner)}</p>'
        parts.append(f'<div class="sec ca"><div class="h">🌐 跨资产资金</div>'
                     f'<div class="b">{ca_html}</div></div>')

    # 资金面明细
    if cf and cf.has_data:
        cf_body = ""
        if cf.etf_total_net_yi:
            sign = "净赎回" if cf.etf_total_net_yi < 0 else "净申购"
            cf_body += f'<p>ETF整体：<b>{sign} {abs(cf.etf_total_net_yi):.0f}亿</b>（存量腾挪 ⇄ 增量入场）</p>'
        if cf.south_net_yi or cf.north_net_yi:
            cf_body += (f'<p>沪深港通：南向 <b>{cf.south_net_yi:+.0f}亿</b>'
                        f'{" · 北向 %.0f亿" % cf.north_net_yi if cf.north_net_yi else " · 北向未披露"}</p>')
        if cf.migration:
            rows = "".join(
                f'<tr><td>{_esc(m["source"])}</td><td>→ {_esc(m["target"])}</td>'
                f'<td>{"★"*m["star"]}{"☆"*(5-m["star"])}</td>'
                f'<td>{_esc(m["note"])}</td></tr>' for m in cf.migration)
            cf_body += ('<table><tr><th>资金</th><th>去向</th><th>强度</th><th>说明</th></tr>'
                        f'{rows}</table>')
        cf_body += f'<p class="link">AI一句话：{_esc(cf.one_liner)}</p>'
        parts.append(f'<div class="sec flow"><div class="h">🌐 资金面明细</div>'
                     f'<div class="b">{cf_body}</div></div>')

    # 全球看板
    if gm and gm.has_data and gm.board:
        g_rows = ""
        for b in gm.board:
            if b["status"] == "ok" and b["change_pct"] is not None:
                chg = f'{b["change_pct"]:+.1f}%'
                col = "#c62828" if b["change_pct"] < 0 else "#2e7d32"
                cell = f'<td style="color:{col};font-weight:700">{chg}</td>'
            elif b["status"] == "blocked":
                cell = '<td style="color:#999">未接入</td>'
            else:
                cell = '<td style="color:#999">—</td>'
            g_rows += (f'<tr><td>{_esc(b["name"])}</td>'
                       f'<td>{"★"*b["importance"]}{"☆"*(5-b["importance"])}</td>'
                       f'{cell}<td style="color:#999;font-size:12px">{_esc(b["note"])}</td></tr>')
        gm_body = ('<table><tr><th>全球资产</th><th>重要度</th><th>今日</th><th>来源</th></tr>'
                   f'{g_rows}</table>')
        gm_body += f'<p class="link">AI一句话：{_esc(gm.one_liner)}</p>'
        parts.append(f'<div class="sec globe"><div class="h">🌏 全球市场看板</div>'
                     f'<div class="b">{gm_body}</div></div>')

    # 今日新发现
    if obs and obs.has_data and obs.discoveries:
        ditems = ""
        for i, d in enumerate(obs.discoveries[:4], 1):
            dt_, dn_ = _fmt_disc(d)
            ditems += f'<li><b>{i}. {_esc(dt_)}</b>'
            if dn_:
                ditems += f'<br><span class="ev">{_esc(dn_[:160])}</span>'
            ditems += '</li>'
        parts.append(f'<div class="sec disc"><div class="h">🌟 今日新发现</div>'
                     f'<div class="b"><ul>{ditems}</ul></div></div>')

    # 盘前纪要
    if pq and pq.has_data:
        pq_html = ""
        for ln in _panqian_md_lines(pq, compact=False):
            h = _esc(ln).replace("**", "").replace("_", "")
            pq_html += h + "<br>"
        parts.append(f'<div class="sec panqian"><div class="h">📋 盘前纪要（{_esc(pq.article_date)}）</div>'
                     f'<div class="b">{pq_html}</div></div>')

    # L3.5 产业链推理
    if ic and ic.has_data:
        ic_html = ""
        for ln in _industry_chain_md_lines(ic, compact=False):
            h = _esc(ln).replace("**", "").replace("_", "")
            ic_html += h + "<br>"
        parts.append(f'<div class="sec ichain"><div class="h">🔗 L3.5 产业链推理</div>'
                     f'<div class="b">{ic_html}</div></div>')

    # 持仓/交易复盘/新鲜度
    parts.append(_position_layer_html(memo))
    parts.append(_trade_review_html(memo))
    parts.append(_freshness_html(memo))

    parts.append('<p class="foot">CIO Agent 生成 · 仅供研究，不构成投资建议</p>')

    css = """
    body{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
         max-width:820px;margin:24px auto;padding:0 16px;color:#1a1a1a;background:#fafafa}
    h1{font-size:22px;margin-bottom:2px}
    .dec{color:#fff;padding:2px 10px;border-radius:10px;font-size:14px;margin-left:8px}
    .sub{color:#777;margin-top:0;font-size:13px}
    .sec{background:#fff;border:1px solid #eee;border-radius:10px;padding:12px 16px;margin:12px 0;
         box-shadow:0 1px 3px rgba(0,0,0,.04)}
    .sec.ca{border:2px solid #c9a227;background:#fffdf5}
    .sec.disc{border:2px solid #6b46c1;background:#faf7ff}
    .sec.disc .h{border-left-color:#6b46c1}
    .sec.cro{border:2px solid #2b6cb0;background:#f5f9ff}
    .sec.cro .h{border-left-color:#2b6cb0}
    .sec.movie{border:2px solid #b7791f;background:#fffaf0}
    .sec.movie .h{border-left-color:#b7791f}
    .sec.flow{border:2px solid #2f855a;background:#f0fff4}
    .sec.flow .h{border-left-color:#2f855a}
    .sec.globe{border:2px solid #4c51bf;background:#f5f6ff}
    .sec.globe .h{border-left-color:#4c51bf}
    .sec.narr{border:2px solid #319795;background:#f0fbfb}
    .sec.narr .h{border-left-color:#319795}
    .sec.panqian{border:2px solid #c2185b;background:#fdf2f8}
    .sec.panqian .h{border-left-color:#c2185b}
    .sec.ichain{border:2px solid #c05621;background:#fdf6f0}
    .sec.ichain .h{border-left-color:#c05621}
    .mig{background:#fff;border:2px solid #dd6b20;border-radius:10px;padding:12px 16px;margin:12px 0;
         box-shadow:0 1px 3px rgba(0,0,0,.04)}
    .mig h2{font-size:15px;margin:0 0 8px;color:#9c4221;border-left:4px solid #dd6b20;padding-left:8px}
    .mig .stars{color:#dd6b20;letter-spacing:2px}
    .mig .thesis{font-size:15px;font-weight:600;line-height:1.7;margin:6px 0 10px}
    .mig-grid{display:flex;gap:16px;margin:8px 0}
    .mig-grid>div{flex:1;background:#fffaf0;border:1px solid #feebc8;border-radius:8px;padding:8px 10px;font-size:13px}
    .mig .lab{display:inline-block;background:#feebc8;color:#9c4221;font-size:12px;padding:1px 6px;border-radius:6px;margin-right:6px}
    .mig .fals{margin-top:8px;font-size:13px}
    .mig .fals .triggered{color:#c53030;font-weight:700}
    .mig .fals .watch{color:#718096;font-size:12px}
    .sec.causal{border:2px solid #2c7a7b;background:#f0fbfb}
    .sec.causal .h{border-left-color:#2c7a7b}
    .sec.causal p{margin:6px 0;line-height:1.7}
    .sec.causal .note{color:#c05621;font-size:13px}
    .sec.debate{border:2px solid #553c9a;background:#faf5ff}
    .sec.debate .h{border-left-color:#553c9a}
    .sec.debate .verdict{font-weight:700;font-size:15px;color:#44337a;margin:4px 0 8px}
    .sec.debate .lab{display:inline-block;background:#e9d8fd;color:#553c9a;font-size:12px;padding:1px 6px;border-radius:6px;margin-right:6px}
    .sec.debate .debate-rows{list-style:none;padding:0;margin:0}
    .sec.debate .debate-rows li{margin:6px 0;padding:8px 10px;border-radius:8px;font-size:13px;line-height:1.6;border-left:4px solid #cbd5e0;background:#fff}
    .sec.debate .debate-rows li.sup{border-left-color:#38a169;background:#f0fff4}
    .sec.debate .debate-rows li.opp{border-left-color:#e53e3e;background:#fff5f5}
    .sec.debate .debate-rows li.neu{border-left-color:#a0aec0;background:#f7fafc}
    .sec.debate .debate-rows li.abs{border-left-color:#cbd5e0;background:#f7fafc;color:#718096}
    .sec.debate .debate-rows li .conf{color:#718096;font-size:12px}
    table.nar{width:100%;border-collapse:collapse;margin-top:6px}
    table.nar td{border-top:1px solid #d6ebeb;padding:6px 8px;vertical-align:top;font-size:13px}
    table.nar td:first-child{width:34%;white-space:nowrap;color:#234e52}
    .warn{color:#c53030;font-weight:700}
    .h{font-weight:700;font-size:15px;color:#222;margin-bottom:8px;border-left:4px solid #2b6cb0;padding-left:8px}
    .sec.ca .h{border-left-color:#c9a227}
    .b{font-size:14px;line-height:1.7}
    ul{margin:6px 0;padding-left:20px} li{margin:4px 0}
    .ok{color:#2e7d32} .bad{color:#c62828}
    .ev{color:#666;font-size:13px}
    .link{color:#1565c0;font-size:13px}
    table{border-collapse:collapse;width:100%;font-size:13px}
    th,td{border:1px solid #eee;padding:5px 8px;text-align:left}
    th{background:#f3f6fb}
    .foot{color:#999;font-size:12px;text-align:center;margin-top:18px}
    .sec.scenario{border:2px solid #5a67d8;background:#f5f7ff}
    .sec.scenario .h{border-left-color:#5a67d8}
    .sec.scenario .summ{font-weight:700;color:#3c366b;margin:4px 0 10px}
    .sec.scenario .var{margin:10px 0;padding:10px;border-radius:8px;background:#fff;border-left:4px solid #a3bffa}
    .sec.scenario .vt{font-weight:700;color:#434190;font-size:14px;margin-bottom:4px}
    .sec.scenario .branch{margin:5px 0;font-size:13px;line-height:1.6}
    .sec.scenario .win{color:#2e7d32;font-size:12px;margin-left:6px}
    .sec.scenario .lose{color:#c62828;font-size:12px;margin-left:6px}
    .sec.scenario .base{color:#4a5568;font-size:13px;margin:4px 0}
    .sec.scenario .impl{color:#c05621;font-size:13px}
    .sec.scenario .switches{color:#c53030;font-size:12px;margin-top:8px}
    .sec.learning{border:2px solid #2f855a;background:#f0fdf4}
    .sec.learning .h{border-left-color:#2f855a}
    .sec.learning .lh{font-weight:700;color:#276749;margin:4px 0 10px;font-size:14px}
    .sec.learning .lab{color:#2f855a;font-weight:700;font-size:13px;margin:10px 0 4px}
    .sec.learning .pat{margin:4px 0 8px}
    .sec.learning .pat li{font-size:13px;line-height:1.6;color:#22543d}
    .sec.learning .rectab{border-collapse:collapse;width:100%;margin:4px 0 8px;font-size:12px}
    .sec.learning .rectab th,.sec.learning .rectab td{border:1px solid #c6f6d5;padding:4px 6px;text-align:center}
    .sec.learning .rectab th{background:#c6f6d5;color:#22543d}
    .sec.learning .self{color:#2c7a7b;font-size:13px;margin-top:8px;background:#e6fffa;padding:8px;border-radius:6px}
    .sec.position{border:2px solid #975a16;background:#fffaf0}
    .sec.position .h{border-left-color:#975a16}
    .sec.position .pl-chip{display:inline-block;background:#feebc8;color:#975a16;font-size:12px;padding:1px 7px;border-radius:6px;margin:2px 4px 2px 0}
    .sec.position .pl-core{background:#f0fff4}.sec.position .pl-mid{background:#ebf8ff}
    .sec.position .pl-short{background:#fff5f5}.sec.position .pl-legacy{background:#f7fafc;color:#718096}
    .sec.trade{border:2px solid #2c5282;background:#ebf8ff}
    .sec.trade .h{border-left-color:#2c5282}
    .sec.trade .tr.bad{background:#fff5f5}
    .sec.trade .tr.bad td:first-child{color:#c53030;font-weight:700}
    .sec.fresh{border:2px solid #553c9a;background:#faf5ff}
    .sec.fresh .h{border-left-color:#553c9a}
    .sec.fresh .st{padding:1px 6px;border-radius:6px;font-size:12px}
    .sec.fresh .st-fresh{background:#c6f6d5;color:#22543d}
    .sec.fresh .st-aging{background:#feebc8;color:#975a16}
    .sec.fresh .st-stale{background:#fed7d7;color:#9b2c2c}
    .sec.fresh .st-unknown{background:#e2e8f0;color:#4a5568}
    .sec.fresh .fr-stale{background:#fff5f5}.sec.fresh .fr-aging{background:#fffaf0}
    .sec.action{border:2px solid #1a365d;background:#ebf8ff}
    .sec.action .h{border-left-color:#1a365d}
    .sec.action .banner{font-weight:700;color:#1a365d;font-size:15px;margin:4px 0 10px}
    .sec.action .lab{color:#2c5282;font-weight:700;font-size:13px;margin:10px 0 4px}
    .sec.action .acts{list-style:none;padding:0;margin:0}
    .sec.action .acts .act{margin:6px 0;padding:8px 10px;border-radius:8px;font-size:13px;line-height:1.6;background:#fff;border-left:4px solid #4299e1}
    /* IC Verdict */
    .sec.icv{border:2px solid #1a365d;background:#f0f4ff}
    .sec.icv .h{border-left-color:#1a365d}
    .icv-top{display:flex;align-items:center;gap:16px;margin:6px 0 12px}
    .icv-dec{display:inline-block;padding:4px 16px;border-radius:8px;font-size:18px;font-weight:800;color:#fff}
    .icv-dec.yes{background:#2e7d32}.icv-dec.no{background:#c62828}.icv-dec.watch{background:#ef6c00}
    .icv-stat{color:#4a5568;font-size:14px;font-weight:600}
    .icv-cols{display:flex;gap:16px;margin:8px 0}
    .icv-col{flex:1;background:#fff;border-radius:8px;padding:10px 12px}
    .icv-col.sup-col{border-left:4px solid #38a169}
    .icv-col.opp-col{border-left:4px solid #e53e3e}
    .icv-lbl{font-weight:700;font-size:13px;margin-bottom:6px}
    .sup-hd{color:#2e7d32}.opp-hd{color:#c62828}
    .icv-col ul{margin:0;padding-left:18px;font-size:13px}
    .icv-col li{margin:3px 0;line-height:1.5}
    .icv-reason{color:#4a5568;font-size:13px;margin-top:8px;font-style:italic}
    /* Evidence */
    .sec.evid{border:2px solid #2c7a7b;background:#f0fbfb}
    .sec.evid .h{border-left-color:#2c7a7b}
    .ev-lst{list-style:none;padding:0;margin:0}
    .ev-cat{margin:6px 0;padding:8px 10px;border-radius:8px;font-size:13px;line-height:1.6;background:#fff;display:flex;gap:10px}
    .ev-cat b{flex-shrink:0;width:40px;color:#fff;text-align:center;border-radius:6px;padding:1px 4px;font-size:12px}
    .cat-funds b{background:#dd6b20}.cat-ind b{background:#2b6cb0}
    .cat-news b{background:#c05621}.cat-global b{background:#553c9a}
    .cat-risk b{background:#c62828}
    .ev-cat span{color:#4a5568}
    /* Research Board */
    .sec.rbd{border:2px solid #6b46c1;background:#faf7ff}
    .sec.rbd .h{border-left-color:#6b46c1}
    .rbd-tbl{width:100%;border-collapse:collapse;font-size:13px}
    .rbd-tbl th{background:#e9d8fd;color:#44337a;padding:5px 8px;text-align:left}
    .rbd-tbl td{padding:4px 8px;border-bottom:1px solid #e9d8fd}
    .rbd-tbl tr.support td:first-child{color:#2e7d32;font-weight:600}
    .rbd-tbl tr.oppose td:first-child{color:#c62828;font-weight:600}
    .rbd-tbl tr.neutral td:first-child{color:#718096}
    .rbd-tbl tr.absent td{color:#a0aec0}
    .rbd-tbl .vi{text-align:center;font-weight:700;font-size:16px}
    .rbd-tbl .ri{text-align:right;color:#718096;font-size:12px}
    .rbd-tbl tr.bull td:first-child{color:#2e7d32;font-weight:600}
    .rbd-tbl tr.bear td:first-child{color:#c62828;font-weight:600}
    .rbd-tbl tr.neu td:first-child{color:#718096}
    /* Action List */
    .sec.actl{border:2px solid #1a365d;background:#ebf8ff}
    .sec.actl .h{border-left-color:#1a365d}
    .act-sub{margin:8px 0;padding:8px 12px;background:#fff;border-radius:8px;border-left:4px solid #4299e1}
    .act-sub-hd{font-weight:700;color:#2c5282;font-size:13px;margin-bottom:4px}
    .act-sub ul{margin:0;padding-left:0;list-style:none}
    .act-sub li.act{margin:4px 0;font-size:13px;line-height:1.6}
    .act-note{color:#c05621;font-size:13px;margin:6px 0}
    /* Appendix */
    .appendix-hd{text-align:center;color:#a0aec0;font-size:13px;margin:20px 0 8px;letter-spacing:2px}
    """
    return (f'<html><head><meta charset="utf-8">'
            f'<title>投资决策备忘录 {_esc(memo.trade_date)}</title>'
            f'<style>{css}</style></head><body>'
            + "".join(parts) + '</body></html>')


def write_memo_html(memo, path):
    """写出本地 HTML 备忘录文件。"""
    html = _memo_html(memo)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# ═══════════════════════════════════════════════════════
#  CLI 测试
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")
    from brain.cio_agent import produce
    memo = produce()
    print("=== 企微格式 ===\n")
    print(_wecom_md(memo)[:4000])
    print("\n...\n")
    print("=== Server酱格式 ===\n")
    print(_serverchan_md(memo)[:4000])
