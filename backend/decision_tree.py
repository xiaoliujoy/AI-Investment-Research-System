# -*- coding: utf-8 -*-
"""
八层决策树 · 每日操作系统输出骨架
=================================
把各层数据/方法论组装成一份「每日决策树」JSON + HTML 看板。

当前数据就绪度：
  L4 资金共识  ← backend/output/sector_mainline.json（已跑通）
  L6 交易执行  ← stock_daily 技术字段（tech_fill 已回填）
  L1/L2/L3/L5/L7/L8 ← 方法论占位，标注「待接入」

运行：python decision_tree.py
"""
import sqlite3, json, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
DB = os.path.join(BASE, "database", "vibe_research.db")
os.makedirs(OUT, exist_ok=True)


def q(sql, args=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def latest_date():
    # MAX(date) 走索引；再限定最近 60 天窗口内 GROUP BY（避开全表扫描），
    # 取 high_20d 已回填且当日行数>4000 的最近完整交易日（避开 07-10 仅5行的部分导入）。
    maxd = q("SELECT MAX(date) AS d FROM stock_daily")[0]["d"]
    lo = (datetime.date.fromisoformat(maxd) - datetime.timedelta(days=60)).isoformat()
    rows = q("SELECT date FROM stock_daily WHERE date>=? AND high_20d IS NOT NULL "
             "GROUP BY date HAVING COUNT(*) > 4000 ORDER BY date DESC", (lo,))
    return rows[0]["date"] if rows else maxd


def report_date():
    """报告日（memo 标题/文件名所用日期）—— 修复『报告日落后』根因 bug。

    原逻辑：memo.trade_date 直接取 latest_date()，而 latest_date 来自
    stock_daily 最新交易日（通达信仅导入到 T-2），导致日报文件名/标题每天
    落后真实交易日约 1~2 天（如 07-15 数据却标成 07-15，盘前纪要已是 07-17）。

    现改为取下列候选的较大者：
      · 今天（自然日，即『X月X日日报』，通常最大）
      · stock_daily 最新交易日
      · sector_mainline.json 的 trade_date（板块层已到 T-1）
      · 盘前纪要 panqian_feed.json 的 article_date（已到今天）
    若系统时钟异常早于数据，则回退到数据最新日，避免报告日倒挂。
    """
    today = datetime.date.today().isoformat()
    cand = []  # 不再把 today 作为候选：未收盘时 today 会超前于数据实际最新日，导致 memo 文件名/标题错配（如 7/23 上午补 7/22 数据却标 07-23）。today 仅在所有数据候选缺失时兜底。
    # stock_daily 最新日
    try:
        md = q("SELECT MAX(date) AS d FROM stock_daily")[0]["d"]
        if md:
            cand.append(md)
    except Exception:
        pass
    # sector_mainline 交易日
    try:
        sm = json.load(open(os.path.join(OUT, "sector_mainline.json"), encoding="utf-8"))
        td = sm.get("trade_date") or (sm.get("meta") or {}).get("trade_date")
        if td:
            cand.append(td)
    except Exception:
        pass
    # 盘前纪要 article_date
    try:
        pf = json.load(open(os.path.join(OUT, "panqian_feed.json"), encoding="utf-8"))
        ad = pf.get("article_date")
        if ad:
            cand.append(ad)
    except Exception:
        pass
    if not cand:
        cand = [today]
    return max(cand)



# ---------- L4 资金共识（接共识生命周期引擎） ----------
def layer4_consensus():
    p = os.path.join(OUT, "sector_mainline.json")
    if not os.path.exists(p):
        return {"status": "待接入", "note": "先跑 build_sector_mainline.py"}
    from consensus_engine import consensus_for_layers
    return consensus_for_layers(p)


# ---------- L6 交易执行（刚突破/即将突破候选，主线板块内过滤） ----------
def _resolve_main_members(main_sectors):
    """同花顺主线板块名 -> (member_codes_set, code2thx_sector)。经 sector_crosswalk 解析到东财板块。"""
    code2sector = {}
    if not main_sectors:
        return set(), code2sector
    ph = ",".join("?" * len(main_sectors))
    # 同花顺名 -> 东财板块代码
    em = {r["thx_name"]: r["em_code"] for r in
          q(f"SELECT thx_name, em_code FROM sector_crosswalk WHERE thx_name IN ({ph})", main_sectors)}
    for thx in main_sectors:
        ec = em.get(thx)
        if not ec:
            continue
        for r in q("SELECT stock_code FROM industry_map WHERE industry_code=? "
                   "AND stock_code NOT LIKE '88%' AND stock_code NOT LIKE '11%' "
                   "AND stock_code NOT LIKE '12%' AND stock_code NOT LIKE '5%'", (ec,)):
            code2sector[r["stock_code"]] = thx
    return set(code2sector), code2sector


def layer6_execution(date, main_sectors=None, leader_codes=None):
    """价格行为（买点/卖点/图形）100% 归用户人工，系统只做到「定方向 + 验证」。
    候选范围已由 playbook 的「候选范围」按板块成分股圈定（不含硬过滤），
    故本层不再用 个股成交额/ma20/ma60 计算突破候选，仅作边界声明。
    L7 的个股风险维度因此降级（仅市场+行业），已在 L7 状态中标注。"""
    return {"status": "你人工（系统不越界）",
            "note": "价格行为（买点/卖点/图形）由你人工看图表定，系统不输出突破候选、不替你定买卖。"
                    "候选范围见上方「每日方向·验证简报」的板块成分股圈定。",
            "candidates": [], "risk_map": {}}
    # 以下为历史实现（已停用，系统不再进入）：原用 amount/ma20/ma60 算突破候选
    if main_sectors:
        if not member_codes:
            return {"status": "已接入(主线板块内过滤)",
                    "note": "主线板块未能解析到成分股(跨表缺失)；请检查 sector_crosswalk/industry_map",
                    "candidates": [], "risk_map": {}}
        ph = ",".join("?" * len(member_codes))
        where = f"AND s.code IN ({ph})"
        args = [date] + list(member_codes)
    else:
        where = ""
        args = [date]
    rows = q(f"""
        SELECT s.code, COALESCE(i.name,'') AS name, s.close, s.high_20d, s.low_20d, s.ma20, s.ma60,
               s.volume_ratio, s.amount, s.change_pct, s.turnover_rate, s.is_new_high_20d
        FROM stock_daily s LEFT JOIN stock_info i ON s.code = i.code
        WHERE s.date=?
          AND s.high_20d IS NOT NULL
          AND s.amount > 10            -- amount 单位=亿元（日成交额>10亿）
          AND s.code NOT LIKE '88%'    -- 排除指数/行业占位行
          AND s.code NOT LIKE '11%' AND s.code NOT LIKE '12%'  -- 排除可转债
          AND s.code NOT LIKE '5%'      -- 排除ETF/基金
          AND (s.is_new_high_20d=1 OR s.close >= s.high_20d*0.98)
        {where}
        ORDER BY s.volume_ratio DESC
    """, args)
    out = []
    for r in rows:
        r["breakout"] = "刚突破" if r["is_new_high_20d"] == 1 else "即将突破"
        r["ma_trend"] = "多头" if (r["ma20"] and r["ma60"] and r["ma20"] > r["ma60"]) else "非多头"
        r["amount_yi"] = round(r["amount"], 1)  # amount 已为亿元
        r["sector"] = code2sector.get(r["code"])
        r["name"] = (r["name"] or "").replace(" ", "")
        out.append(r)
    # 个股风险维度（L7 用，逐只标注）
    risk_map = {}
    try:
        from risk_stock import compute_stock_risk
        risk_map = compute_stock_risk(date, out, leader_codes=set(leader_codes or []))
        for r in out:
            r["risk"] = risk_map.get(r["code"])
    except Exception as e:
        print("  [L6 个股风险] 计算失败:", repr(e)[:80])
    status = "已接入(主线板块内过滤)" if main_sectors else "已接入(全市场扫描)"
    return {"status": status,
            "note": "个股硬过滤(20MA/市值/量比)由用户自做；此表仅列突破候选",
            "candidates": out, "risk_map": risk_map}


# ---------- L5 龙头体系（四龙头 + 板块净额本地聚合） ----------
def layer5_leaders(date, main_sectors):
    if not main_sectors:
        return {"status": "待接入", "note": "无主线板块"}
    try:
        from leader_engine import compute_leaders, load_net_flow
        net, ndate = load_net_flow()
        data = compute_leaders(date, main_sectors, net)
        return {"status": "已接入(四龙头+板块净额本地聚合)",
                "net_date": ndate, "leaders": data}
    except Exception as e:
        return {"status": "待接入", "note": repr(e)[:150]}


# ---------- L7 风险预算（市场 + 行业 + 个股，三维各0-100，越高越险） ----------
def layer7_risk(date, l4=None, l6=None):
    rows = q("SELECT change_pct FROM stock_daily WHERE date=? AND amount>0", (date,))
    n = len(rows)
    if n == 0:
        return {"status": "待接入"}
    up = sum(1 for r in rows if r["change_pct"] is not None and r["change_pct"] > 0)
    up_ratio = up / n
    # 市场风险：上涨家数占比越高，风险越低（0-100）
    risk_market = round((1 - up_ratio) * 100)
    # 行业风险：主线中处「高潮/退潮」比例越高 → 越拥挤/越危险（0-100）
    risk_industry = None
    if l4 and l4.get("stage_distribution"):
        dist = l4["stage_distribution"]
        tot = sum(dist.values())
        late = dist.get("高潮", 0) + dist.get("退潮", 0)
        risk_industry = round(late / tot * 100) if tot else None
    # 个股风险：基于当日主线板块成分股（与 playbook 同源），不依赖 L6（L6 已为边界声明）
    risk_stock = None
    worst = None
    try:
        from risk_stock import compute_stock_risk, aggregate
        from playbook_engine import resolve_main_members
        lines = (l4 or {}).get("main_lines") or []
        focus_sectors = [r["sector"] for r in lines if r.get("stage") != "退潮"][:5]
        if focus_sectors:
            members, _ = resolve_main_members(focus_sectors)
            if members:
                cands = [{"code": c} for c in members]
                rm = compute_stock_risk(date, cands)
                if rm:
                    agg = aggregate(rm)
                    risk_stock = agg["risk_stock"]
                    worst = agg["worst"]
    except Exception as e:
        print("  [L7 个股风险] 计算失败:", repr(e)[:80])
    # 综合：三维加权平均（市场必在，行业/个股缺失则权重归一）
    parts = []
    if risk_industry is not None:
        parts.append((risk_industry, 0.30))
    if risk_stock is not None:
        parts.append((risk_stock, 0.25))
    parts.append((risk_market, 0.45))
    tw = sum(w for _, w in parts)
    composite = round(sum(v * w for v, w in parts) / tw)
    if composite < 30:
        pos = "80-100%"
    elif composite < 50:
        pos = "50-80%"
    elif composite < 70:
        pos = "30-50%"
    else:
        pos = "<30%（或空仓）"
    dim_ok = (risk_industry is not None) + (risk_stock is not None)
    status = "已接入(市场+行业+个股三维)" if dim_ok == 2 else "骨架(市场风险分已算，行业/个股分待接入)"
    return {"status": status,
            "risk_market": risk_market, "up_ratio": round(up_ratio * 100, 1),
            "risk_industry": risk_industry, "risk_stock": risk_stock, "worst_stock": worst,
            "composite": composite, "position": pos}


# ---------- 情绪验证（资金+情绪验证 · 情绪半边） ----------
def layer_sentiment(date):
    try:
        from sentiment import market_sentiment
        return market_sentiment(date)
    except Exception as e:
        return {"status": "待接入", "note": repr(e)[:150], "gaps": [], "read": ""}


# ---------- 占位层 ----------
def stub(status, note):
    return {"status": status, "note": note}


def main():
    date = latest_date()
    l4 = layer4_consensus()
    main_sectors = [r["sector"] for r in l4.get("main_lines", [])]
    # L5 先算（取龙头代码，供 L6 个股风险标注「是否龙头」）
    l5 = layer5_leaders(date, main_sectors)
    leader_codes = set()
    if l5.get("leaders"):
        for sec, v in l5["leaders"].items():
            if "error" in v:
                continue
            for role in ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"]:
                ld = (v.get(role) or {})
                if ld.get("code"):
                    leader_codes.add(ld["code"])
    l6 = layer6_execution(date, main_sectors, leader_codes=leader_codes)
    l7 = layer7_risk(date, l4, l6)
    # 叙事层（L1/L2/L3/L8）独立容错，单层失败不影响其他层
    try:
        from narrative_layers import (layer1_global, layer2_china,
                                      layer3_industry, layer8_learning)
        l1 = layer1_global()
        l2 = layer2_china()
        l3 = layer3_industry(l4)
        l8 = layer8_learning()
    except Exception as e:
        l1 = l2 = l3 = l8 = {"status": "待接入", "note": repr(e)[:120], "gaps": []}
    # 情绪验证（资金+情绪验证 · 情绪半边），独立容错
    try:
        from sentiment import market_sentiment
        l_sent = market_sentiment(date)
    except Exception as e:
        l_sent = {"status": "待接入", "note": repr(e)[:120], "gaps": [], "read": ""}
    # 板块级基本面验证（验证方向 · 第③维：业绩 vs 估值），独立容错
    try:
        from fundamental_engine import layer_fundamental
        focus_for_fund = [r["sector"] for r in l4.get("main_lines", [])
                          if r.get("stage") != "退潮"][:5]
        l_fund = layer_fundamental(focus_for_fund)
    except Exception as e:
        l_fund = {"status": "待接入", "note": repr(e)[:120], "gaps": [], "read": ""}
    tree = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "trade_date": date,
        "layers": {
            "L1_global_macro": l1,
            "L2_china_macro": l2,
            "L3_industry": l3,
            "L4_consensus": l4,
            "L5_leader": l5,
            "L6_execution": l6,
            "L7_risk": l7,
            "L8_learning": l8,
            "sentiment": l_sent,
            "fundamental": l_fund,
        },
    }
    try:
        from playbook_engine import build_playbook
        tree["playbook"] = build_playbook(tree["layers"], date)
    except Exception as e:
        print("  [playbook] 生成失败:", repr(e)[:120])
    json.dump(tree, open(os.path.join(OUT, "decision_tree.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print("decision_tree.json written, trade_date=", date)
    return tree


def render_html(tree):
    L = tree["layers"]

    # 数据源溯源（step1 多源容错）
    ds = {}
    try:
        ds = json.load(open(os.path.join(OUT, "sector_mainline.json"), encoding="utf-8")).get("data_sources", {})
    except Exception:
        pass

    def c(v):
        try:
            f = float(v); return "#e23c3c" if f > 0 else ("#1ba784" if f < 0 else "#555")
        except Exception:
            return "#555"

    def badge(st):
        color = {"已接入": "#1ba784", "已接入(全市场扫描，待接 step2 板块过滤)": "#e6a23c",
                 "骨架(市场风险分已算，产业/个股分待接入)": "#e6a23c",
                 "骨架(市场+行业+个股三维)": "#1ba784", "AI主导": "#409eff",
                 "待接入": "#909399"}.get(st, "#909399")
        return f'<span class="badge" style="background:{color}">{st}</span>'

    def nbadge(st):
        color = {"已接入": "#1ba784", "部分接入": "#e6a23c", "AI主导": "#409eff",
                 "待接入": "#909399", "数据缺口": "#f56c6c"}.get(st, "#909399")
        return f'<span class="badge" style="background:{color}">{st}</span>'

    def render_narrative(layer):
        if not layer:
            return f"<p>{nbadge('待接入')} 无数据</p>"
        st = layer.get("status", "待接入")
        html = f"<p>{nbadge(st)} {layer.get('read','')}</p>"
        gaps = layer.get("gaps") or []
        if gaps:
            html += f"<p class='muted'>数据缺口：{'；'.join(str(g) for g in gaps)}</p>"
        return html

    def risk_cell(risk):
        if not risk:
            return "<span class='muted'>-</span>"
        sc = risk.get("score", 0)
        col = "#1ba784" if sc < 35 else ("#e6a23c" if sc < 60 else "#e23c3c")
        tags = " ".join(risk.get("flags", [])[:3])
        return f"<b style='color:{col}'>{sc}</b><br><span class='muted'>{tags}</span>"

    # L4 资金共识（共识生命周期）
    STAGE_COLOR = {"事件": "#909399", "讨论": "#909399", "资金流入": "#409eff",
                   "赚钱效应": "#67c23a", "一致性": "#e6a23c", "高潮": "#e23c3c", "退潮": "#f56c6c"}
    l4 = L["L4_consensus"]
    l4_html = ""
    if l4.get("main_lines"):
        l4_html = "".join(
            f"<tr><td class='sec'>{r['sector']}</td>"
            f"<td><span class='stage' style='background:{STAGE_COLOR.get(r['stage'],'#909399')}'>{r['stage']}</span>"
            f"<span class='muted'>{r['consensus_strength']}</span></td>"
            f"<td class='num' style='color:{c(r.get('net_now'))}'>{r.get('net_now')}</td>"
            f"<td class='num' style='color:{c(r.get('net_5d'))}'>{r.get('net_5d')}</td>"
            f"<td class='reason'>{r.get('reason','')}</td></tr>"
            for r in l4["main_lines"])
    else:
        l4_html = f"<tr><td colspan=5>{l4.get('note','-')}</td></tr>"
    # 早期观察（潜在新主线）
    early = l4.get("early_watch") or []
    early_html = "".join(
        f"<tr><td class='sec'>{r['sector']}</td>"
        f"<td class='num' style='color:{c(r.get('net_now'))}'>{r.get('net_now')}</td>"
        f"<td class='num'>{r.get('vol_trend')}</td>"
        f"<td class='num' style='color:{c(r.get('chg_pct'))}'>{r.get('chg_pct')}%</td></tr>"
        for r in early) or "<tr><td colspan=4>无</td></tr>"

    # L6
    l6 = L["L6_execution"]
    l6_html = "".join(
        f"<tr><td class='sec'>{r['name']}<span class='code'>{r['code']}</span></td>"
        f"<td class='muted'>{r.get('sector','')}</td>"
        f"<td><b style='color:#e23c3c'>{r['breakout']}</b> · {r['ma_trend']}</td>"
        f"<td class='num'>{r['amount_yi']}亿</td>"
        f"<td class='num'>{r['volume_ratio']}</td>"
        f"<td class='num' style='color:{c(r['change_pct'])}'>{r['change_pct']}%</td>"
        f"<td class='num'>{risk_cell(r.get('risk'))}</td></tr>"
        for r in l6.get("candidates", [])) or "<tr><td colspan=7>无突破候选</td></tr>"

    # L7
    l7 = L["L7_risk"]
    l7_html = (f"<div class='riskbox'>"
               f"市场风险分 <b>{l7.get('risk_market')}</b> ｜ 上涨家数占比 <b>{l7.get('up_ratio')}%</b><br>"
               f"行业风险分 <b>{l7.get('risk_industry')}</b> ｜ 个股风险分 <b>{l7.get('risk_stock')}</b>"
               f"{('（最险个股 '+str((l7.get('worst_stock') or {}).get('code',''))+' 分 '+str((l7.get('worst_stock') or {}).get('score',''))+'）') if l7.get('worst_stock') else ''}<br>"
               f"综合风险分 <b>{l7.get('composite')}</b> → 建议仓位 <b style='color:#e23c3c'>{l7.get('position')}</b>"
               f"<br><span class='muted'>三维加权：市场0.45 + 行业0.30 + 个股0.25（各0-100，越高越险）</span></div>")

    def render_playbook(pb):
        if not pb:
            return "<p>综合层未生成</p>"
        focus = pb.get("focus_sectors", [])
        focus_html = " ".join(
            f"<span class='chip'>{f['sector']}<small>{f['stage']}{' ⚠' if f.get('risk') else ''}</small></span>"
            for f in focus) or "<span class='muted'>暂无主线</span>"
        cand_html = ""
        for blk in pb.get("candidates", []):
            sec = blk["sector"]
            rows = "".join(
                f"<tr><td>{s['code']}</td><td>{s['name'] or '-'}</td>"
                f"<td class='num'>{s['close']}</td>"
                f"<td class='num' style='color:{c(s['change_pct'])}'>{s['change_pct']}%</td>"
                f"<td class='num'>{s['vol_ratio']}</td>"
                + (f"<td class='num' style='color:{c(s['vs_sector'])}'>{s['vs_sector']:+}%</td>"
                   if s.get('vs_sector') is not None else "<td class='num'>-</td>")
                + (f"<td class='num muted'>{(str(s['market_cap'])+'亿') if s.get('market_cap') else ''}"
                   f"<br><span class='code'>{s.get('cap_bucket','—')}</span></td>")
                for s in blk["stocks"])
            cand_html += (f"<h4>{sec}（{len(blk['stocks'])}只 · 按量比活跃度排序，仅圈定）</h4>"
                          f"<table><tr><th>代码</th><th>名称</th><th>收盘</th>"
                          f"<th class='num'>涨跌幅</th><th class='num'>量比</th>"
                          f"<th class='num'>相对板块</th><th class='num'>市值区间</th></tr>{rows}</table>")
        if not cand_html:
            cand_html = "<p class='muted'>主线板块未能解析到成分股（跨表缺失），候选范围为空；请检查 sector_crosswalk / industry_map。</p>"
        chain_html = "".join(
            f"<li><b>{s['step']}</b> — {s['detail']}</li>" for s in pb.get("reasoning_chain", []))
        bs = pb.get("blind_spots", [])
        bs_html = "".join(f"<li>{b}</li>" for b in bs) or "<li class='muted'>无明显盲点</li>"
        head = ("<h2 style='margin:0 0 6px;color:#e6a23c'>每日方向 · 验证简报 "
                "<span class='ai'>宏观+产业决定方向 → 资金+基本面+情绪验证方向</span></h2>")
        scope = ("<div class='scope'>系统职责分两阶段：<b>① 决定方向</b>＝宏观+产业（L1/L2/L3）｜"
                 "<b>② 验证方向</b>＝资金+基本面+情绪（L4/L5/基本面验证/情绪）。"
                 "买卖 / 图形（价格行为）100% 由你人工定，系统不越界、不给买卖指令。</div>")
        sent = pb.get("sentiment") or {}
        sent_line = (f"<p class='muted'>情绪温度：<b>{sent.get('state','-')}</b> ｜ {sent.get('verdict','')}</p>"
                     if sent.get("state") else "")
        return (head + scope
                + f"<div class='thesis'>{pb['thesis'].replace(chr(10),'<br>')}</div>"
                + f"<p><b>验证通过的主线：</b>{focus_html}</p>"
                + sent_line
                + f"<p class='muted'>候选仅圈定：按量比活跃度排序；硬过滤（20MA/市值/成交额）+ 图形买点 由你人工完成。</p>"
                f"<div class='twocol'><div><h4>候选范围（板块成分股·已圈定，供你人工看图定买卖）</h4>{cand_html}</div>"
                f"<div><h4>推理链（为什么是这些）</h4><ol>{chain_html}</ol>"
                f"<h4>盲点与提示</h4><ul>{bs_html}</ul></div></div>"
                f"<p class='muted'>风险护栏（非买卖指令）：{pb.get('position_advice','-')}</p>")

    cards = []
    cards.append(("<h2>① 全球宏观 <span class='ai'>AI+数据</span></h2>", render_narrative(L["L1_global_macro"])))
    cards.append(("<h2>② 中国宏观 <span class='ai'>AI+数据</span></h2>", render_narrative(L["L2_china_macro"])))

    # ③ 产业趋势：结构化 Top3（产业≠板块）
    def render_l3(layer):
        if not layer or not layer.get("top_industries"):
            return render_narrative(layer)
        st = layer.get("status", "AI主导")
        DRV = {"技术革命": "#409eff", "国产替代": "#67c23a",
               "周期涨价": "#e6a23c", "政策驱动": "#e23c3c"}
        PHASE = {"早期": "#909399", "潜伏": "#909399", "加速": "#67c23a",
                 "分歧": "#e6a23c", "兑现": "#e23c3c"}
        rows = ""
        for i, t in enumerate(layer["top_industries"], 1):
            dc = DRV.get(t["driver"], "#909399")
            pc = PHASE.get(t["phase"], "#909399")
            conf = ("<span style='color:#1ba784'>✓ " +
                    "/".join(m["board"] for m in t.get("matched_boards", [])) + "</span>") \
                if t.get("confirmed") else "<span class='muted'>潜伏·待验证</span>"
            rows += (
                f"<tr><td class='sec'>{i}. {t['name']}"
                f"<br><span class='stage' style='background:{dc}'>{t['driver']}</span></td>"
                f"<td><span class='stage' style='background:{pc}'>{t['phase']}</span><br>{conf}</td>"
                f"<td class='reason'>催化：{t['catalyst']}<br>验证：{t['verify']}"
                f"<br><span style='color:#c0392b'>风险：{t['risk']}</span></td></tr>")
        gaps = layer.get("gaps") or []
        gap_html = (f"<p class='muted'>提示：{'；'.join(str(g) for g in gaps)}</p>") if gaps else ""
        # 延伸观察：Top3 之外的候选产业（all_ranked 4-8 名）
        watch = ""
        for i, t in enumerate(layer.get("all_ranked", [])[3:8], 4):
            dc = DRV.get(t["driver"], "#909399")
            mark = ("✓ " + "/".join(m["board"] for m in t.get("matched_boards", []))) \
                if t.get("confirmed") else "待验证"
            watch += (f"<span class='chip' style='background:{dc}'>{i}. {t['name']}"
                      f"<small>{t['phase']}·{mark}</small></span>")
        watch_html = (f"<p class='sub'>延伸观察（候选产业 4–8 名）</p><div>{watch}</div>") if watch else ""
        # 整体研判（read 末句）
        verdict = layer.get("read", "").split("整体研判：")
        verdict_html = (f"<p class='sub'>整体研判：{verdict[-1]}</p>") if len(verdict) > 1 else ""
        return (f"<p>{nbadge(st)} 未来6个月 Top3｜<b>产业≠板块</b>，板块只做验证</p>"
                f"<table><tr><th>产业/驱动</th><th>阶段/验证</th><th>催化·验证·风险</th></tr>{rows}</table>"
                f"{watch_html}{verdict_html}{gap_html}")

    # ⑧ 学习进化：结构化复盘
    def render_learning(layer):
        if not layer or not layer.get("count"):
            return render_narrative(layer)
        st = layer.get("status", "已接入")
        months = layer.get("by_month") or {}
        mrows = "".join(
            f"<tr><td>{m}</td><td class='num'>{v['n']}</td>"
            f"<td class='num' style='color:{c(v['win_rate'])}'>{v['win_rate']}%</td>"
            f"<td class='num' style='color:{c(v['pnl_sum'])}'>{v['pnl_sum']}%</td>"
            f"<td class='num'>{v['pnl_avg']}%</td></tr>"
            for m, v in months.items()) or "<tr><td colspan=5>无</td></tr>"
        secs = layer.get("by_sector") or {}
        srows = "".join(
            f"<tr><td class='sec'>{s}</td><td class='num'>{v['n']}</td>"
            f"<td class='num' style='color:{c(v['win_rate'])}'>{v['win_rate']}%</td>"
            f"<td class='num' style='color:{c(v['pnl_avg'])}'>{v['pnl_avg']}%</td></tr>"
            for s, v in sorted(secs.items(), key=lambda kv: (kv[1]['win_rate'] or 0), reverse=True)) \
            or "<tr><td colspan=4>无</td></tr>"
        ins = layer.get("insights") or []
        ins_html = "".join(f"<li>{x}</li>" for x in ins) or "<li>样本尚少，继续积累以提炼稳定模式。</li>"
        overall = (f"共 {layer['count']} 笔 ｜ 胜率 <b style='color:{c(layer.get('win_rate'))}'>{layer.get('win_rate')}%</b>"
                   f" ｜ 平均盈亏 <b style='color:{c(layer.get('avg_pnl'))}'>{layer.get('avg_pnl')}%</b>"
                   f" ｜ 累计 <b style='color:{c(layer.get('total_pnl'))}'>{layer.get('total_pnl')}%</b>")
        return (f"<p>{nbadge(st)} {overall}</p>"
                f"<p class='sub'>月度复盘</p>"
                f"<table><tr><th>月份</th><th class='num'>笔数</th><th class='num'>胜率</th><th class='num'>累计盈亏</th><th class='num'>均盈亏</th></tr>{mrows}</table>"
                f"<p class='sub'>板块胜率榜（反哺选股偏好）</p>"
                f"<table><tr><th>板块</th><th class='num'>笔数</th><th class='num'>胜率</th><th class='num'>均盈亏</th></tr>{srows}</table>"
                f"<p class='sub'>系统自动迭代建议</p><ul class='ins'>{ins_html}</ul>")

    cards.append(("<h2>③ 产业趋势 <span class='ai'>AI主导</span></h2>", render_l3(L["L3_industry"])))
    cards.append(("<h2>④ 资金共识 <span class='ai'>AI+量化</span></h2>",
                  f"<p>{badge(l4['status'])} 交易日 {l4.get('trade_date')} ｜ 覆盖 {l4.get('sector_count')} 行业 ｜ "
                  f"阶段分布 {l4.get('stage_distribution')}</p>"
                  f"<p class='muted'>数据源冗余：资金流={ds.get('flow')} ｜ 成交额={ds.get('amount')} ｜ "
                  f"tushare可用={ds.get('tushare_available')}（第3源待激活）</p>"
                  f"<table><tr><th>板块</th><th>共识阶段/强度</th><th class='num'>当日净额</th><th class='num'>5日净额</th><th>判定理由</th></tr>{l4_html}</table>"
                  f"<p class='sub'>早期观察（潜在新主线，资金刚进场）：</p>"
                  f"<table><tr><th>板块</th><th class='num'>当日净额</th><th class='num'>量能比</th><th class='num'>涨跌幅</th></tr>{early_html}</table>"))
    # L5 四龙头
    l5 = L["L5_leader"]
    ROLS = [("产业龙头", "#409eff"), ("资金龙头", "#e23c3c"), ("技术龙头", "#67c23a"), ("情绪龙头", "#e6a23c")]
    if l5.get("leaders"):
        l5_html = ""
        for sec, v in l5["leaders"].items():
            if "error" in v:
                l5_html += (f"<tr><td class='sec'>{sec}</td><td colspan=4 class='muted'>"
                            f"⚠ {v.get('error')}</td></tr>")
                continue
            row = f"<tr><td class='sec' rowspan=4>{sec}<br><span class='muted'>{v['member_count']}只 · 本地净额{v['sector_net_main']}亿</span></td>"
            for i, (role, col) in enumerate(ROLS):
                ld = v.get(role) or {}
                nm = ld.get("name") or "-"
                cd = ld.get("code") or ""
                chg = ld.get("change_pct")
                net = ld.get("net_main")
                extra = f"主力{net}亿" if net is not None else f"成交额{ld.get('amount_yi')}亿"
                row += (f"<td><span class='stage' style='background:{col}'>{role}</span></td>"
                        f"<td class='sec'>{nm}<span class='code'>{cd}</span></td>"
                        f"<td class='num' style='color:{c(chg)}'>{chg}%</td>"
                        f"<td class='num'>{extra}</td></tr>" +
                        ("" if i == 3 else "<tr>"))
            l5_html += row
        l5_body = (f"<p>{badge(l5['status'])} 个股资金流日期 {l5.get('net_date')}</p>"
                   f"<table><tr><th>板块</th><th>角色</th><th>个股</th><th class='num'>涨跌幅</th><th class='num'>资金</th></tr>{l5_html}</table>")
    else:
        l5_body = f"<p>{badge(l5['status'])} {l5.get('note','')}</p>"
    cards.append(("<h2>⑤ 龙头体系 <span class='ai'>程序+AI</span></h2>", l5_body))

    # 情绪验证（资金+情绪验证 · 情绪半边）
    l_sent = L.get("sentiment") or {}

    def render_sentiment(layer):
        if not layer or not layer.get("state"):
            return render_narrative(layer)
        st = layer.get("status", "已接入")
        s = layer.get("state", "")
        SC = {"冰点": "#909399", "低迷": "#909399", "回暖": "#67c23a",
              "活跃": "#409eff", "高潮": "#e23c3c", "退潮": "#f56c6c"}
        col = SC.get(s, "#909399")
        return (f"<p>{nbadge(st)} 情绪状态：<span class='stage' style='background:{col}'>{s}</span> "
                f"｜ 综合打分 <b>{layer.get('score')}</b></p>"
                f"<p class='muted'>市场宽度：上涨{layer.get('up')}/下跌{layer.get('down')}"
                f"（占比{layer.get('up_ratio', 0) * 100:.0f}%）｜ 涨停{layer.get('zt')}/跌停{layer.get('dt')}｜ "
                f"连板高度 {layer.get('board_height')} 板"
                f"{('｜ 量能比 ' + str(layer.get('vol_ratio'))) if layer.get('vol_ratio') is not None else ''}</p>"
                f"<p>{layer.get('verdict', '')}</p>")

    cards.append(("<h2>情绪验证 <span class='ai'>程序</span></h2>", render_sentiment(l_sent)))

    # 板块级基本面验证（验证方向 · 第③维：业绩 vs 估值）
    l_fund = L.get("fundamental") or {}

    def render_fundamental(layer):
        if not layer or not layer.get("sectors"):
            return (f"<p>{nbadge(layer.get('status', '待接入'))} "
                    f"{layer.get('read', '暂无主线，跳过基本面验证')}</p>")
        st = layer.get("status", "已接入")
        VC = {"业绩驱动": "#67c23a", "业绩好·估值偏高": "#e6a23c",
              "估值偏高·业绩疲软": "#e23c3c", "业绩承压": "#909399",
              "混合/中性": "#909399", "数据不足": "#909399"}
        rows = ""
        for s in layer["sectors"]:
            vc = VC.get(s["verdict"], "#909399")
            rv = "—" if s.get("rev_yoy_med") is None else f"{s['rev_yoy_med']:+}%"
            nv = "—" if s.get("np_yoy_med") is None else f"{s['np_yoy_med']:+}%"
            pe = "—" if s.get("pe_med") is None else f"{s['pe_med']}"
            rows += (f"<tr><td class='sec'>{s['sector']}<br><span class='muted'>{s['n_stocks']}只</span></td>"
                     f"<td class='num'>{rv}</td><td class='num'>{nv}</td>"
                     f"<td class='num'>{pe}</td>"
                     f"<td><span class='stage' style='background:{vc}'>{s['verdict']}</span></td></tr>")
        read = layer.get("read", "")
        return (f"<p>{nbadge(st)} 回答「上涨是业绩推动，还是估值炒作」｜ 业绩取 {layer.get('period')} 报告期</p>"
                f"<table><tr><th>板块</th><th class='num'>营收同比(中位)</th>"
                f"<th class='num'>净利同比(中位)</th><th class='num'>PE(中位)</th><th>判定</th></tr>{rows}</table>"
                f"<p class='muted'>{read}</p>")

    cards.append(("<h2>基本面验证 <span class='ai'>业绩 vs 估值</span></h2>",
                  render_fundamental(l_fund)))

    cards.append(("<h2>⑥ 交易执行 <span class='ai'>你人工</span></h2>",
                  f"<p>{badge(l6['status'])} {l6.get('note')}</p>"))
    cards.append(("<h2>⑦ 风险控制 <span class='ai'>程序</span></h2>", l7_html))
    cards.append(("<h2>⑧ 学习进化 <span class='ai'>AI</span></h2>", render_learning(L["L8_learning"])))

    html = f"""<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
 body{{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;background:#f5f6f8;margin:0;padding:24px;color:#222}}
 h1{{font-size:21px;margin:0 0 4px}} .meta{{color:#888;font-size:13px;margin-bottom:20px}}
 .grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;align-items:start}}
 .card{{background:#fff;border-radius:10px;padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
 .card h2{{font-size:15px;margin:0 0 10px;color:#333}}
 .ai{{font-size:11px;color:#999;font-weight:400;margin-left:6px}}
 p{{font-size:13px;line-height:1.6;margin:6px 0}}
 table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}}
 th,td{{padding:6px 8px;text-align:left;border-bottom:1px solid #f0f0f0}}
 th{{color:#999;font-weight:600;background:#fafafa}} td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 td.sec{{font-weight:600}} .code{{color:#bbb;font-size:11px;margin-left:4px}}
 .stage{{display:inline-block;color:#fff;font-size:11px;padding:1px 7px;border-radius:9px;margin-right:4px}}
 .reason{{font-size:11px;color:#888;max-width:360px}} .sub{{font-size:12px;color:#e6a23c;margin:10px 0 4px;font-weight:600}}
 .badge{{color:#fff;font-size:11px;padding:2px 8px;border-radius:10px}}
 .riskbox{{background:#fff8f0;border:1px solid #ffe0b0;border-radius:8px;padding:12px;font-size:13px;line-height:1.8}}
 .muted{{color:#aaa;font-size:12px}}
 .ins{{margin:4px 0 4px 18px;padding:0}} .ins li{{font-size:12.5px;line-height:1.55;margin:2px 0}}
 .playbook{{border:2px solid #e6a23c;background:#fffdf5}}
 .scope{{background:#eef7ff;border:1px solid #bcdcff;color:#2c5f8a;border-radius:6px;padding:8px 10px;font-size:12.5px;line-height:1.5;margin:6px 0 10px}}
 .thesis{{font-size:14.5px;line-height:1.7;background:#fff;border-left:4px solid #e6a23c;border-radius:4px;padding:10px 12px;margin:8px 0;white-space:normal}}
 .chip{{display:inline-block;background:#409eff;color:#fff;border-radius:12px;padding:3px 11px;margin:3px 5px 3px 0;font-size:13px}}
 .chip small{{opacity:.85;font-size:11px;margin-left:3px}}
 .twocol{{display:flex;gap:22px;flex-wrap:wrap;margin-top:8px}} .twocol>div{{flex:1;min-width:300px}}
 .twocol h4{{font-size:13px;color:#e6a23c;margin:10px 0 4px}} .twocol ol{{margin:4px 0 4px 18px;padding:0}} .twocol ol li{{font-size:12.5px;line-height:1.6;margin:3px 0}}
</style></head><body>
<h1>个人A股交易研究操作系统 · 八层决策树</h1>
<div class=meta>生成 {tree['generated_at']} ｜ 交易日 {tree['trade_date']} ｜ 每天回答8个问题，而非直接给买卖</div>
"""
    pb_banner = tree.get("playbook")
    if pb_banner:
        html += f"<div class='card playbook'>{render_playbook(pb_banner)}</div>\n"
    html += "<div class=grid>\n"
    for h, b in cards:
        html += f"<div class=card>{h}{b}</div>\n"
    html += "</div></body></html>"
    open(os.path.join(OUT, "decision_tree.html"), "w", encoding="utf-8").write(html)
    print("decision_tree.html written")


if __name__ == "__main__":
    t = main()
    render_html(t)
