# -*- coding: utf-8 -*-
"""
L0 Market Narrative：总指挥定调。

用户痛点：原日报只堆分数，没有"今天到底在交易什么"的叙事（Narrative）。
机构晨会先一句话定调，再展开推理。

本模块综合 L1-L4 + sentiment + fundamental 的结论，生成：
  headline : 一句话"今天市场在交易什么（而非什么）"
  body     : 资金扩散路径 + 龙头确认 + 阶段警示 + 情绪/基本面注脚

关键修正：严格区分「资金主线板块（交易维度）」与「产业逻辑（6个月维度）」，
避免 headline 与 body 视角打架（用户强调：产业≠板块）。

2026-07-13 升级：接入 Market Narrative Intelligence 引擎，
在 A 股板块叙事之外，新增全球跨资产叙事拆解（事实 vs 推断、因果链置信度、
反事实分析、共识阶段），回答用户提出的五个日常问题。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .context import ReasoningContext  # noqa


def build(ctx):
    l1 = ctx.get("L1") or {}
    l3 = ctx.get("L3") or {}
    l4 = ctx.get("L4") or {}
    sent = ctx.get("sentiment") or {}
    fund = ctx.get("fundamental") or {}

    l3raw = l3.get("raw") or {}
    l4raw = l4.get("raw") or {}
    top = l3raw.get("top_industries") or []
    confirmed = [t for t in top if t.get("confirmed")]
    conf_names = [t["name"] for t in confirmed[:2]]
    main_lines = l4raw.get("main_lines") or []
    board_names = [str(m.get("sector")) for m in main_lines[:3]]
    top_boards = "、".join(board_names[:2]) if board_names else "无明显主线"

    # —— 主题：并列「资金主线板块」与「中长期产业验证方向」，不强行因果关联 ——
    if conf_names:
        theme = f"{top_boards}（资金主线）；中长期产业验证方向：{('、'.join(conf_names))}"
    else:
        theme = top_boards

    # —— "而非什么"：区分泛主题与实际主线 ——
    not_what = ""
    if conf_names and ("AI" in conf_names[0]) and board_names and \
            any(("国产" in b or "半导体" in b or "GPU" in b or "算力" in b) for b in board_names[:2]):
        not_what = "，而非泛AI应用"

    # —— 资金扩散路径：取主线前 3 板块 ——
    path = ""
    if len(board_names) >= 2:
        path = f"资金先攻{board_names[0]}、扩散至{'、'.join(board_names[1:])}"

    # —— 龙头确认 ——
    l5raw = (ctx.get("L5") or {}).get("raw") or {}
    has_leader = bool(l5raw.get("leaders"))
    leader_txt = "龙头已确认" if has_leader else "龙头尚待确认"

    # —— 阶段警示 ——
    dist = l4raw.get("stage_distribution") or {}
    tot = sum(dist.values()) or 1
    late = dist.get("高潮", 0) + dist.get("退潮", 0)
    stage_warn = ""
    if tot and late / tot > 0.5:
        stage_warn = "，多数主线处高潮/退潮区、宜去弱留强"

    # —— 情绪注脚 ——
    st = sent.get("signal", {}).get("state")
    sent_txt = f"，情绪{st}" if st else ""

    # —— 基本面注脚 ——
    fsectors = (fund.get("raw") or {}).get("sectors") or []
    driven = [s for s in fsectors if s.get("verdict") == "业绩驱动"]
    fund_txt = ""
    if driven:
        fund_txt = "，且方向有业绩支撑"
    elif fsectors:
        fund_txt = "，但上涨偏资金/情绪驱动、业绩未完全跟上"

    # —— 产业≠板块 洞察：当天最强板块是否被中长期产业验证 ——
    note_diff = ""
    if confirmed and board_names:
        top_board = board_names[0]
        in_confirmed = any(
            top_board and top_board in (mb.get("board", "") or "")
            for t in confirmed for mb in t.get("matched_boards", [])
        )
        if not in_confirmed:
            note_diff = "（当天最强板块与中长期被验证产业不完全重合：交易性机会≠产业性机会，注意区分。）"

    headline = f"今天市场在交易：{theme}{not_what}。"
    body = f"{path}；{leader_txt}{sent_txt}{fund_txt}{stage_warn}{note_diff}"

    # ── 全球跨资产叙事引擎 ──
    global_narrative = None
    try:
        from narrative_intelligence import run as ni_run
        l1_raw = l1.get("raw")
        global_narrative = ni_run(l1_raw)
    except Exception as e:
        global_narrative = {"headline": "叙事引擎不可用", "headline_detail": str(e)}

    # ── 合成 headline：全球叙事 + A 股板块 ──
    gn = global_narrative or {}
    gn_head = gn.get("headline", "")
    if gn_head and gn_head != "市场缺乏明确跨资产叙事" and "不可用" not in gn_head:
        headline = f"【全球】{gn_head}　【A 股】{theme}{not_what}。"
        # 全球叙事对 A 股的影响提示
        a_impact = gn.get("a_share_impact", "")
        if a_impact:
            body = f"全球叙事→A 股影响：{a_impact}。　{body}"

    return {
        "headline": headline,
        "body": body,
        "theme": theme,
        "confirmed_industries": conf_names,
        "global_narrative": global_narrative,
    }
