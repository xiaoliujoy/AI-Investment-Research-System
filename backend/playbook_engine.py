# -*- coding: utf-8 -*-
"""
综合 · 方向验证层（每日方向 · 验证简报 / Daily Playbook）
=========================================================
把八层决策树的读数收敛成「今日方向是什么、为什么、验证通过的主线候选有哪些」。
职责边界（用户明确，2026-07-11｜两阶段）：
  阶段①【决定方向】＝宏观+产业（L1/L2/L3）定方向；
  阶段②【验证方向】＝资金+基本面+情绪（L4/L5/基本面验证/情绪）验证方向是否得到确认。
  价格行为（买点/卖点/图形）完全由用户人工操作，系统不越界、不给买卖指令。
  不用管个股成交额、不用管 ma20/ma60（按用户范围收窄）。

输入：decision_tree 的 layers（L1-L8 + sentiment）+ DB（stock_daily / stock_info / industry_map / sector_crosswalk）
输出：playbook dict（thesis / focus / candidates / sentiment / position / reasoning_chain / blind_spots / filter_status / boundary / read）

设计原则：
  - 规则版：透明、可回溯，不黑箱。
  - 复用 decision_tree._resolve_main_members（同花顺名→东财成分股，已排除指数/转债/ETF）。
  - 候选范围 = 验证通过的「主线板块」之成分股（圈定），按量比活跃度排序；
    硬过滤(20MA/市值/量比阈值/成交额)由用户人工在图表上做，系统只圈不替定。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decision_tree as dt


def resolve_main_members(main_sectors):
    """复用决策树跨表映射，并对 0 命中板块做 industry_map 兜底（如 游戏→游戏Ⅱ/Ⅲ）。"""
    mc, c2s = dt._resolve_main_members(main_sectors)
    for thx in main_sectors:
        if thx not in set(c2s.values()):
            for r in dt.q("SELECT stock_code FROM industry_map "
                          "WHERE industry_name=? OR industry_name LIKE ?",
                          (thx, thx + '%')):
                mc.add(r["stock_code"])
                c2s[r["stock_code"]] = thx
    return mc, c2s


def pick_focus(l4, top_n=5):
    """从 L4 main_lines 选非退潮的前 top_n 作为今日主线；高潮标注风险。"""
    lines = (l4 or {}).get("main_lines") or []
    return [r for r in lines if r.get("stage") != "退潮"][:top_n]


def circle_candidates(date, members, code2sector, per_sector=12, sector_chg=None):
    """圈定主线板块成分股（不做硬过滤）。按量比活跃度排序，供用户人工看图定买卖。
    严格不触碰 个股成交额(amount) / ma20 / ma60（用户边界）。
    sector_chg: {板块名: 板块涨跌幅%}，用于加「相对板块强弱」提示列（强于/弱于），纯提示不越界。"""
    if not members:
        return {}, False
    mc = list(members)
    ph = ",".join("?" * len(mc))
    rows = dt.q(f"""
        SELECT s.code, COALESCE(i.name,'') AS name, s.close, s.change_pct, s.volume_ratio,
               s.market_cap
        FROM stock_daily s LEFT JOIN stock_info i ON s.code=i.code
        WHERE s.date=? AND s.code IN ({ph})
          AND s.code NOT LIKE '88%' AND s.code NOT LIKE '11%'
          AND s.code NOT LIKE '12%' AND s.code NOT LIKE '5%'
        ORDER BY s.volume_ratio DESC
    """, [date, *mc])
    try:
        from fill_market_cap import cap_bucket
    except Exception:
        def cap_bucket(_):
            return "—"
    by_sector = {}
    for r in rows:
        r["name"] = (r["name"] or "").replace(" ", "")
        r["vol_ratio"] = round(r["volume_ratio"], 2) if r["volume_ratio"] is not None else None
        r["change_pct"] = round(r["change_pct"], 2) if r["change_pct"] is not None else None
        r["market_cap"] = round(r["market_cap"], 1) if r.get("market_cap") else None
        r["cap_bucket"] = cap_bucket(r.get("market_cap"))
        sec = code2sector.get(r["code"], "其他")
        if sector_chg and sec in sector_chg and r["change_pct"] is not None:
            diff = round(r["change_pct"] - sector_chg[sec], 2)
            r["vs_sector"] = diff
            r["rel"] = "强于" if diff > 0.3 else ("弱于" if diff < -0.3 else "持平")
        else:
            r["vs_sector"] = None
            r["rel"] = "-"
        by_sector.setdefault(sec, []).append(r)
    return {sec: stks[:per_sector] for sec, stks in by_sector.items()}, True


def _regime_tag(rd):
    """从【xxx：yyy】读里提取 yyy（regime 标签）。"""
    if not rd or "【" not in rd:
        return ""
    inside = rd.split("【", 1)[1].split("】", 1)[0]
    return inside.split("：", 1)[-1] if "：" in inside else inside


def build_thesis(layers, focus, sentiment, position_advice):
    l1 = layers.get("L1_global_macro", {})
    l2 = layers.get("L2_china_macro", {})
    l3 = layers.get("L3_industry", {})
    fund = layers.get("fundamental") or {}
    macro_dir = " / ".join(x for x in (_regime_tag(l1.get("read")), _regime_tag(l2.get("read"))) if x)
    ti = l3.get("top_industries") or []
    ind_names = "、".join(t["name"] for t in ti[:3]) or "待研究"
    focus_names = "、".join(r["sector"] for r in focus) or "暂无明确主线"
    highs = [r["sector"] for r in focus if r.get("stage") == "高潮"]
    risk_note = (f"⚠ {('、'.join(highs))} 处高潮，警惕追高/赶顶"
                 if highs else "主线尚处发酵/赚钱效应阶段，风险可控")
    sent_txt = ""
    if sentiment and sentiment.get("state"):
        sent_txt = f"情绪温度：{sentiment['state']}（{sentiment.get('verdict','')}）"
    # 基本面一句话
    fsec = fund.get("sectors") or []
    driven = [s["sector"] for s in fsec if s.get("verdict") == "业绩驱动"]
    over = [s["sector"] for s in fsec if "估值偏高" in (s.get("verdict") or "")]
    fund_txt = ""
    if fsec:
        fund_txt = (f"基本面：业绩驱动 {('、'.join(driven) or '无')}；"
                    f"估值偏高 {('、'.join(over) or '无')}（回答：业绩推动 or 估值炒作）。")
        cred = f"方向可信度：{len(driven)}/{len(fsec)} 个主线有业绩支撑。"
    else:
        cred = ""
    thesis = (
        f"【决定方向】宏观+产业：{macro_dir or '见各层'} ｜ 未来6月景气 {ind_names}。\n"
        f"【验证方向】资金+基本面+情绪：资金主线 {focus_names}；{fund_txt}{sent_txt}{cred}\n"
        f"候选范围：聚焦上述 1-3 个板块，板块内成分股已圈定（按量比活跃度排序）；"
        f"硬过滤(20MA/市值/量比/成交额)与图形买点由你人工做，系统只圈不替定。\n"
        f"风险护栏：{risk_note}。\n"
        f"买卖/图形由你人工定 —— 系统只做到「决定方向 + 验证方向」。"
    )
    return thesis


def reasoning_chain(layers, focus, sentiment):
    l1 = layers.get("L1_global_macro", {})
    l2 = layers.get("L2_china_macro", {})
    l3 = layers.get("L3_industry", {})
    l4 = layers.get("L4_consensus", {})
    fund = layers.get("fundamental") or {}
    steps = []
    steps.append(("①【决定方向】宏观", f"{_regime_tag(l1.get('read')) or '中性'} ｜ {_regime_tag(l2.get('read')) or '待定'}（外围环境定调）"))
    ti = l3.get("top_industries") or []
    steps.append(("②【决定方向】产业",
                  "未来6月景气赛道：" + ("、".join(f"{t['name']}({t.get('phase','-')})"
                                              for t in ti[:3]) or "待研究")))
    fl = [r for r in (l4.get("main_lines") or []) if r.get("stage") != "退潮"][:3]
    steps.append(("③【验证方向】资金共识",
                  "验证通过的资金主线：" + ("、".join(f"{r['sector']}({r['stage']})" for r in fl) or "无")))
    fsec = fund.get("sectors") or []
    fparts = []
    driven = [s["sector"] for s in fsec if s.get("verdict") == "业绩驱动"]
    over = [s["sector"] for s in fsec if "估值偏高" in (s.get("verdict") or "")]
    if fsec:
        fparts.append("业绩驱动板块：" + ("、".join(driven) or "无"))
        fparts.append("估值偏高板块：" + ("、".join(over) or "无"))
    else:
        fparts.append("基本面验证待接入")
    steps.append(("④【验证方向】基本面（业绩 vs 估值）",
                  "；".join(fparts) + "（回答：上涨是业绩推动还是估值炒作）"))
    sent_txt = (f"情绪温度：{sentiment['state']}（{sentiment.get('verdict','')}）" if sentiment and sentiment.get("state") else "情绪温度待接入")
    steps.append(("⑤【验证方向】情绪温度", sent_txt))
    steps.append(("⑥ 候选范围（板块成分股，已圈定）",
                  "方向经资金+基本面+情绪三维验证通过后，主线板块成分股已圈出，按量比活跃度排序；图形/买点/硬过滤由你人工定"))
    steps.append(("⑦ 纪律护栏",
                  "仓位见 L7 三维风险预算；高潮/估值偏高板块不追高；你的止损纪律照旧（破位即走），系统不代定"))
    return steps


def blind_spots(layers, focus, sentiment):
    bs = []
    highs = [r["sector"] for r in focus if r.get("stage") == "高潮"]
    if highs:
        bs.append(f"高潮板块 {('、'.join(highs))} 多信号共振，易赶顶，仅可低吸不可追高。")
    if sentiment and sentiment.get("gaps"):
        bs.append("情绪数据缺口：" + "、".join(str(g) for g in sentiment["gaps"]))
    l8 = layers.get("L8_learning", {})
    if (l8.get("count") or 0) == 0:
        bs.append("学习进化空转：交易日志 0 条，月度模式统计未启动，闭环待你录入首笔交易。")
    l1 = layers.get("L1_global_macro", {})
    if l1.get("gaps"):
        bs.append("全球宏观部分指标缺失：" + "、".join(str(g) for g in l1["gaps"]))
    return bs


def build_playbook(layers, trade_date, per_sector=12):
    """综合 8 层读数 + 情绪验证，产出每日方向·验证简报。"""
    l4 = layers.get("L4_consensus", {})
    focus = pick_focus(l4)
    members, code2sector = (set(), {})
    if focus:
        members, code2sector = resolve_main_members([r["sector"] for r in focus])
    # 板块涨跌幅：用于候选「相对板块强弱」提示（纯提示，不替用户定买卖）
    sector_chg = {r["sector"]: (r.get("chg_pct") or 0) for r in (l4.get("main_lines") or [])}
    candidates = {}
    if members:
        candidates, _ = circle_candidates(trade_date, members, code2sector, per_sector, sector_chg)
    # 情绪验证（资金+情绪验证 · 情绪半边）
    sentiment = layers.get("sentiment") or {}
    # 仓位建议来自 L7（三维风险预算）
    l7 = layers.get("L7_risk", {})
    position_advice = l7.get("position") or l7.get("position_advice")
    if not position_advice:
        position_advice = (l7.get("read") or "依风险预算自定（L7 未给建议）")[:70]
    thesis = build_thesis(layers, focus, sentiment, position_advice)
    chain = reasoning_chain(layers, focus, sentiment)
    return {
        "trade_date": trade_date,
        "boundary": "两阶段：①决定方向=宏观+产业(L1/L2/L3)；②验证方向=资金+基本面+情绪(L4/L5/基本面验证/情绪)。价格行为(买点/卖点/图形)由你人工定，系统不越界。",
        "thesis": thesis,
        "focus_sectors": [{"sector": r["sector"], "stage": r["stage"],
                           "consensus_strength": r.get("consensus_strength"),
                           "risk": r.get("risk", False)} for r in focus],
        "candidates": [{"sector": sec, "stocks": stks} for sec, stks in candidates.items()],
        "sentiment": sentiment,
        "position_advice": position_advice,
        "reasoning_chain": [{"step": s, "detail": d} for s, d in chain],
        "blind_spots": blind_spots(layers, focus, sentiment),
        "filter_status": {
            "ma20_gt_ma60": "user_manual",
            "amount_gt_10yi": "user_manual",
            "market_cap_100_1000yi": "user_manual",
            "volume_ratio_order": True,
            "note": "候选仅圈定，硬过滤(20MA/市值/成交额)+图形买点由你人工完成",
        },
        "read": thesis,  # 供推送端继承
    }


if __name__ == "__main__":
    import json
    tree = json.load(open(os.path.join(dt.OUT, "decision_tree.json"), encoding="utf-8"))
    pb = build_playbook(tree["layers"], tree["trade_date"])
    print("== THESIS ==")
    print(pb["thesis"])
    print("\n== FOCUS ==", [f["sector"] for f in pb["focus_sectors"]])
    print("== CANDIDATES ==", {c["sector"]: len(c["stocks"]) for c in pb["candidates"]})
    print("== FILTER STATUS ==", pb["filter_status"])
    print("== BLIND SPOTS ==")
    for b in pb["blind_spots"]:
        print("  -", b)
