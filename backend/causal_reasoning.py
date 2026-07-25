# -*- coding: utf-8 -*-
"""
因果推理引擎 (Causal Reasoning Engine)
======================================
回答买方每天的第三个真问题的一部分——「为什么」：
    钱为什么去那？谁在推动？证据是否充分？

与"排行榜 / 催化待确认"的本质区别：
    * 不只说"净流入60亿"，而是追因：ETF申购 / 放量 / 新闻关键词 / 产业链位置；
    * 多源驱动 hunt：ETF净申购匹配 → 成交额放量 → 新闻催化关键词 → 结构性产业链逻辑；
    * **找不到就诚实写"原因未知。资金驱动。继续观察。"** 绝不写"催化待确认"；
    * 产业链下钻：把重点板块映射到深度产业链（如 医药→创新药/CXO/实验猴/ADC），
      再检查产业链各环节今日是否同步净流入 → 自动推出
      "炒的不是[板块]，而是[产业链环节]（如研发链）"。

输入（只读，不修改既有产物）：
    output/sector_mainline.json   (板块 net_now/net_5d/chg_pct/amount_today/amount_prev)
    output/flow_report.json       (ETF 申购榜 top_inflow)
    narrative_engine.fetch_news_corpus()  (东财全球快讯 200 条，带时间戳)
    narrative_engine.INDUSTRY_CHAIN      (板块→theme/logic/keywords)

输出：build(focus_sectors) -> dict
    causes:        {sector: {driver, status, display, structural, evidence[]}}
    chain_insights:{sector: 一句话产业链洞察}
    unknown_list:  [sector...]  (未找到具体驱动，仅资金驱动)
"""
import os
import json
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")

# ── 深度产业链映射：板块/主题 → 产业链环节 ──────────────────────
# 用于"炒的是X链不是板块本身"的自动推断。segments 用于匹配
# sector_mainline 中同名/含名板块，验证产业链多环节是否同步流入。
DEEP_CHAINS = {
    "医药": {
        "name": "医药创新链",
        "segments": ["创新药", "CXO", "实验猴", "ADC", "原料药", "BD", "医疗服务",
                      "生物制品", "化学制药", "中药"],
        "logic": "研发—临床—制造—服务全链条：本轮由创新药BD出海 + 临床数据驱动，"
                 "资金沿研发链向上游服务（CXO/实验猴）与下游制造扩散。",
    },
    "半导体": {
        "name": "AI算力硬件链",
        "segments": ["半导体", "芯片", "设备", "材料", "存储", "封测", "光模块",
                      "PCB", "元件", "通信设备", "消费电子"],
        "logic": "算力芯片 → 设备/材料 → 光模块/PCB → 终端，是全球AI Capex 扩张的"
                 "硬件前置，对 SOXX/韩国科技链高度敏感。",
    },
    "大金融": {
        "name": "市场Beta链",
        "segments": ["证券", "保险", "银行", "多元金融"],
        "logic": "不是券商自身基本面，而是市场情绪 + 成交额 + 两融的杠杆表达；"
                 "成交放量即确认。",
    },
    "AI应用": {
        "name": "AI内容/应用链",
        "segments": ["游戏", "传媒", "影视", "广告", "计算机", "软件"],
        "logic": "大模型应用落地层：游戏/影视/广告受AI降本与政策驱动，是算力需求的下游兑现。",
    },
    "新能源": {
        "name": "能源转型链",
        "segments": ["光伏", "储能", "电网", "变压器", "风电", "电力设备"],
        "logic": "国内外装机 + 电网投资驱动，产能过剩是主要压制。",
    },
    "机器人": {
        "name": "具身智能链",
        "segments": ["机器人", "减速器", "丝杠", "传感器", "执行器"],
        "logic": "人形机器人量产预期驱动零部件主题，高弹性高波动。",
    },
}

# 重点板块 → 深度链归属
SECTOR_TO_CHAIN = {
    "证券": "大金融", "保险": "大金融", "银行": "大金融", "多元金融": "大金融",
    "化学制药": "医药", "生物制品": "医药", "医疗服务": "医药", "中药": "医药",
    "医药": "医药", "医疗器械": "医药", "生物制药": "医药",
    "游戏": "AI应用", "传媒": "AI应用", "计算机": "AI应用", "软件开发": "AI应用",
    "半导体": "半导体", "元件": "半导体", "通信设备": "半导体",
    "消费电子": "半导体", "光学光电子": "半导体",
    "电力设备": "新能源", "光伏设备": "新能源",
    "机器人": "机器人", "自动化设备": "机器人",
}

# 新闻驱动关键词（出现即视为具体催化线索）
DRIVER_KW = ["降准", "降息", "LPR", "利率", "合并", "重组", "并购", "借壳", "IPO",
             "再融资", "定增", "政策", "利好", "订单", "中标", "签约", "业绩",
             "预告", "扩产", "加码", "补贴", "批准", "获批", "出海", "BD", "授权"]


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return None


def _load_sectors():
    d = _load_json(os.path.join(OUT, "sector_mainline.json"))
    if not d:
        return [], None
    rows = []
    for s in d.get("sectors", []):
        try:
            rows.append({
                "sector": s["sector"],
                "net_now": float(s.get("net_now") or 0),
                "net_5d": float(s.get("net_5d") or 0),
                "amount_today": float(s.get("amount_today") or 0),
                "amount_prev": float(s.get("amount_prev") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows, d.get("trade_date")


def _load_flow():
    return _load_json(os.path.join(OUT, "flow_report.json"))


def _etf_match(sector, chain_theme, flow):
    """ETF 申购榜中是否出现该板块/主题的 ETF（增量资金借道）。"""
    etf = (flow or {}).get("etf_flow_summary", {}).get("top_inflow", []) or []
    kws = [sector] + ([chain_theme] if chain_theme else [])
    hits = []
    for e in etf:
        nm = e.get("name", "")
        if any(k in nm for k in kws):
            hits.append(nm)
    return hits


def _volume_expand(sector_row):
    """成交额放量判断。返回 (是否放量, 描述)。"""
    a_t = sector_row.get("amount_today") or 0
    a_p = sector_row.get("amount_prev") or 0
    if a_t <= 0 or a_p <= 0:
        return False, ""
    ratio = a_t / a_p
    if ratio >= 1.15:
        pct = (ratio - 1) * 100
        return True, f"板块成交额放量（{a_p:.0f}亿→{a_t:.0f}亿，+{pct:.0f}%），量能放大确认"
    return False, ""


def _news_driver(sector, chain_name, corpus):
    """新闻语料中是否出现 (板块/链名) + 驱动关键词。返回 (标题, 时间) 或 None。"""
    kws = [sector, chain_name] if chain_name else [sector]
    for item in corpus:
        text = (item.get("title", "") or "") + " " + (item.get("summary", "") or "")
        if not text.strip():
            continue
        if not any(k in text for k in kws):
            continue
        if any(dk in text for dk in DRIVER_KW):
            return item.get("title", ""), item.get("time", "")
    return None


def _chain_insight(sector, rows):
    """产业链下钻：重点板块 → 深度链 → 各环节今日是否同步净流入。"""
    chain_key = SECTOR_TO_CHAIN.get(sector)
    if not chain_key:
        return ""
    chain = DEEP_CHAINS.get(chain_key)
    if not chain:
        return ""
    segs = chain["segments"]
    inflow_segs = []
    for r in rows:
        sname = r["sector"]
        if r["net_now"] > 0 and any(seg in sname for seg in segs):
            inflow_segs.append(sname)
    # 去重并保持顺序
    seen, uniq = set(), []
    for s in inflow_segs:
        if s not in seen:
            seen.add(s); uniq.append(s)
    if len(uniq) >= 2:
        return (f"资金实则在炒「{chain['name']}」而非单押 {sector}："
                f"{'、'.join(uniq[:4])} 同步净流入，"
                f"说明沿产业链多环节共振扩散。{chain['logic']}")
    return ""


def build(focus_sectors=None, save=True):
    """构建因果推理报告。

    focus_sectors: 重点板块列表（如迁移引擎 focus + 主线）。为 None 时取净流入 Top4。
    返回 dict: causes / chain_insights / unknown_list / focus
    """
    sectors, trade_date = _load_sectors()
    if not sectors:
        return {"trade_date": trade_date, "causes": {}, "chain_insights": {},
                "unknown_list": [], "focus": []}
    flow = _load_flow()

    # 新闻语料（真实、带时间戳；失败优雅降级为空）
    corpus = []
    try:
        from narrative_engine import fetch_news_corpus
        corpus = fetch_news_corpus() or []
    except Exception:
        corpus = []

    row_map = {r["sector"]: r for r in sectors}

    if not focus_sectors:
        focus = [r["sector"] for r in sorted(sectors, key=lambda x: x["net_now"], reverse=True)[:4]]
    else:
        focus = [s for s in focus_sectors if s in row_map]
        # 不足则补净流入榜
        if len(focus) < 3:
            extra = [r["sector"] for r in sorted(sectors, key=lambda x: x["net_now"], reverse=True)
                     if r["sector"] not in focus]
            focus += extra[: (3 - len(focus))]

    # 产业链归属（用于 ETF/新闻 匹配的主题词）
    try:
        from narrative_engine import INDUSTRY_CHAIN
        chain_theme_of = lambda s: (INDUSTRY_CHAIN.get(s, {}) or {}).get("theme", "")
        logic_of = lambda s: (INDUSTRY_CHAIN.get(s, {}) or {}).get("logic", "")
    except Exception:
        chain_theme_of = lambda s: ""
        logic_of = lambda s: ""

    causes = {}
    chain_insights = {}
    unknown_list = []

    for sec in focus:
        row = row_map.get(sec)
        if not row:
            continue
        theme = chain_theme_of(sec)
        evidence = []

        # 1) ETF 申购匹配
        etf_hits = _etf_match(sec, theme, flow)
        if etf_hits:
            evidence.append(("etf", f"增量资金借道「{etf_hits[0]}」申购（位列ETF申购榜）"))

        # 2) 成交额放量
        vol_ok, vol_txt = _volume_expand(row)
        if vol_ok:
            evidence.append(("volume", vol_txt))

        # 3) 新闻催化关键词
        chain_name = DEEP_CHAINS.get(SECTOR_TO_CHAIN.get(sec, ""), {}).get("name", "")
        news_hit = _news_driver(sec, chain_name, corpus)
        if news_hit:
            evidence.append(("news", f"新闻催化：《{news_hit[0]}》（{news_hit[1]}）"))

        # 结构性产业链逻辑（始终可用，作为上下文，不作为"驱动"）
        structural = logic_of(sec) or DEEP_CHAINS.get(SECTOR_TO_CHAIN.get(sec, ""), {}).get("logic", "")

        # 决定 display
        if evidence:
            ev = evidence[0]  # 优先级 etf>volume>news（append 顺序即优先级）
            driver = ev[1]
            status = "found"
            display = f"因为{driver}。"
        else:
            status = "unknown"
            driver = ""
            suffix = f"（结构性逻辑：{structural}）" if structural else ""
            display = f"原因未知。资金驱动。继续观察。{suffix}"

        causes[sec] = {
            "driver": driver,
            "status": status,
            "display": display,
            "structural": structural,
            "evidence": [{"type": t, "text": x} for t, x in evidence],
        }
        if status == "unknown":
            unknown_list.append(sec)

        # 产业链下钻洞察
        ci = _chain_insight(sec, sectors)
        if ci:
            chain_insights[sec] = ci

    report = {
        "trade_date": trade_date,
        "focus": focus,
        "causes": causes,
        "chain_insights": chain_insights,
        "unknown_list": unknown_list,
        "news_count": len(corpus),
    }
    if save:
        try:
            json.dump(report, open(os.path.join(OUT, "causal_report.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception:
            pass
    return report


if __name__ == "__main__":
    r = build()
    print(f"交易日: {r['trade_date']}  新闻条数: {r['news_count']}  重点: {r['focus']}")
    print("\n【因果推理 · 为什么】")
    for sec, c in r["causes"].items():
        print(f"  ▸ {sec} [{c['status']}]: {c['display']}")
        if sec in r["chain_insights"]:
            print(f"     产业链：{r['chain_insights'][sec][:90]}...")
    if r["unknown_list"]:
        print(f"\n未找到具体驱动（仅资金驱动）：{r['unknown_list']}")
