# -*- coding: utf-8 -*-
"""
Narrative Engine —— 「为什么」引擎（用户审计问题二的核心）

目标：对今日资金净流入 Top 板块，给出可解释的因果链：
    宏观/全球驱动 → 产业逻辑（产业链位置） → 实时催化（真实新闻） → 结论。

设计原则：
  1. 真实优先：实时新闻来自 akshare 东财全球快讯（本沙箱清代理后可达），带时间戳。
  2. 诚实优先：新闻做情绪判定（涨/利好 vs 跌/利空），若新闻与资金方向背离，明确标注「背离」。
  3. 优雅降级：新闻拉不到时，仅用内置产业链逻辑 + 资金数据，has_news=False，绝不编造。
  4. 全局联动：科技类板块关联 KOSPI/TWII 当日涨跌（亚洲 AI 风险偏好）。

输出：output/narrative_report.json
依赖：output/sector_mainline.json（板块资金）、output/global_history（经 backfill）
"""
import os
import sys
import json
import re
import datetime

# 给所有 requests（含 akshare）注入默认超时，防止新闻抓取挂起
import requests
_ORIG_REQUEST = requests.Session.request
def _request_with_timeout(self, method, url, **kwargs):
    kwargs.setdefault("timeout", 20)
    return _ORIG_REQUEST(self, method, url, **kwargs)
requests.Session.request = _request_with_timeout

# 修正：DB 在 backend/database（原 ".." 误指到上层目录，导致 global_driver 静默读空库）
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "vibe_research.db")
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
CACHE_DIR = os.path.join(OUTPUT, ".narrative_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ───────────────────────────────────────────────────────────
#  产业链知识库：板块 → 产业逻辑 / 关键词 / 主题
#  关键词用于新闻命中；logic 用于结构性「为什么」
# ───────────────────────────────────────────────────────────
INDUSTRY_CHAIN = {
    "通信设备": {
        "theme": "AI算力·网络连接",
        "keywords": ["光模块", "交换机", "CPO", "算力网络", "5G", "6G", "卫星通信", "光通信", "数据中心", "通信设备"],
        "logic": "AI算力产业链的「网络连接层」：光模块/交换机/CPO 直接受益于全球云厂与AI算力 Capex 上行，是算力扩张的硬件前置。",
        "global": True,
    },
    "元件": {
        "theme": "AI硬件·被动/互连",
        "keywords": ["元件", "PCB", "被动", "MLCC", "电容", "电感", "覆铜板", "CCL"],
        "logic": "电子上游基础件：PCB/被动元件是AI服务器与终端的刚需耗材，量价随终端创新（AI手机/服务器）共振。",
        "global": True,
    },
    "半导体": {
        "theme": "AI芯片·国产替代",
        "keywords": ["半导体", "芯片", "晶圆", "光刻", "存储", "封测", "EDA", "国产替代", "算力芯片"],
        "logic": "科技行情的「心脏」：AI算力芯片 + 国产替代双主线；对全球半导体周期（SOXX/费城半导体）与韩台科技链高度敏感。",
        "global": True,
    },
    "消费电子": {
        "theme": "AI终端·换机",
        "keywords": ["消费电子", "手机", "AI手机", "苹果", "iPhone", "可穿戴", "PC", "平板"],
        "logic": "AI终端落地层：AI手机/PC 换机周期 + 果链创新，是半导体与元件需求的下游出口。",
        "global": True,
    },
    "光学光电子": {
        "theme": "显示·感知",
        "keywords": ["光学", "面板", "LED", "MiniLED", "摄像头", "感知", "显示"],
        "logic": "显示与感知层：面板周期回暖 + 车载/AI视觉需求，是消费电子的配套环节。",
        "global": False,
    },
    "互联网电商": {
        "theme": "消费·平台",
        "keywords": ["电商", "互联网", "消费", "直播", "零售", "社零", "网购", "平台"],
        "logic": "消费复苏的「渠道层」：受社零/消费数据、平台政策与AI降本增效驱动，对内需政策敏感。",
        "global": False,
    },
    "工业金属": {
        "theme": "周期·制造上游",
        "keywords": ["铜", "铝", "工业金属", "有色", "金属", "电解", "冶炼", "矿业"],
        "logic": "制造业与电网上游：铜铝价格受全球制造业PMI、电网投资、供给扰动驱动，是经济景气的同步指标。",
        "global": True,
    },
    "有色金属": {
        "theme": "周期·资源",
        "keywords": ["有色", "铜", "铝", "锂", "钴", "镍", "黄金", "资源", "矿业"],
        "logic": "资源品：工业金属（铜铝）+ 能源金属（锂钴镍）+ 贵金属，受全球供需与美元周期共同定价。",
        "global": True,
    },
    "贵金属": {
        "theme": "避险·实际利率",
        "keywords": ["黄金", "白银", "贵金属", "避险", "实际利率"],
        "logic": "避险与实际利率交易：与美元指数、美债实际利率（TIPS）负相关，是组合的对冲层。",
        "global": True,
    },
    "计算机": {
        "theme": "软件·AI应用",
        "keywords": ["计算机", "软件", "AI应用", "信创", "算力服务", "SaaS", "国产化"],
        "logic": "AI应用与国产化层：大模型应用落地 + 信创替代，是算力需求的下游兑现。",
        "global": False,
    },
    "传媒": {
        "theme": "AI应用·内容",
        "keywords": ["传媒", "游戏", "影视", "AI应用", "内容", "短剧"],
        "logic": "AI内容生成落地层：游戏/影视/广告受AI降本与版号政策驱动。",
        "global": False,
    },
    "医药": {
        "theme": "创新药·刚需",
        "keywords": ["医药", "创新药", "生物", "CXO", "医保", "临床", "制药"],
        "logic": "刚性需求 + 出海逻辑：创新药BD出海、医保谈判与老龄化需求，受政策与临床数据驱动。",
        "global": False,
    },
    "港股通创新药": {
        "theme": "南向·创新药",
        "keywords": ["创新药", "生物", "CXO", "医药", "港股"],
        "logic": "南向资金偏好的高弹性标的：创新药出海 + 港股估值修复，与南向净流入高度相关。",
        "global": False,
    },
    "国防军工": {
        "theme": "装备·改革",
        "keywords": ["军工", "国防", "航空", "航天", "船舶", "导弹", "装备"],
        "logic": "装备建设 + 改革：受装备采购周期、国企改革与地缘事件驱动，弱宏观相关。",
        "global": False,
    },
    "电力设备": {
        "theme": "新能源·电网",
        "keywords": ["电力设备", "光伏", "风电", "储能", "电网", "变压器", "逆变器"],
        "logic": "能源转型硬件：光伏/储能/电网设备，受国内外装机与电网投资驱动，产能过剩是主要压制。",
        "global": True,
    },
    "汽车": {
        "theme": "智驾·出海",
        "keywords": ["汽车", "智能驾驶", "新能源", "零部件", "出海", "Robotaxi"],
        "logic": "智能化 + 出海：智驾渗透率提升与整车出海，是制造链的需求引擎。",
        "global": False,
    },
    "机器人": {
        "theme": "具身智能",
        "keywords": ["机器人", "人形", "减速器", "具身", "执行器", "丝杠"],
        "logic": "具身智能主题：人形机器人量产预期驱动零部件（减速器/丝杠）主题行情，高弹性高波动。",
        "global": False,
    },
    "CPO": {
        "theme": "AI算力·光互连",
        "keywords": ["CPO", "光模块", "光互连", "硅光"],
        "logic": "AI算力光互连前沿：CPO/硅光是数据中心带宽瓶颈的解法，弹性高于传统光模块。",
        "global": True,
    },
    "人工智能": {
        "theme": "AI主线总括",
        "keywords": ["人工智能", "AI", "大模型", "算力", "语料"],
        "logic": "AI主线总括：映射算力—模型—应用全链条，是本轮科技行情的总命题。",
        "global": True,
    },
}

# 情绪词典
POS = ["涨", "升", "利好", "订单", "中标", "突破", "增长", "扩产", "合作", "超预期", "爆发",
       "加码", "上调", "需求", "复苏", "拐点", "创新高", "大增", "扩围", "落地", "签约"]
NEG = ["跌", "走弱", "领跌", "风险", "制裁", "下滑", "亏损", "下调", "暂停", "调查", "利空",
       "承压", "过剩", "放缓", "萎缩", "下挫", "重挫", "暴跌", "预警", "退市", "违约"]


# ═════════════════════════════════════════════════════
#  新闻语料（实时，带缓存）
# ═════════════════════════════════════════════════════
def _clear_proxy():
    for v in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
        os.environ.pop(v, "")


def fetch_news_corpus(force=False):
    """拉取东财全球快讯，缓存到 .narrative_cache，返回 [{title,summary,time}]。失败则回退缓存。"""
    today = datetime.date.today().strftime("%Y%m%d")
    cache = os.path.join(CACHE_DIR, f"news_{today}.json")
    if not force and os.path.exists(cache):
        try:
            return json.load(open(cache, encoding="utf-8"))
        except Exception:
            pass
    corpus = []
    try:
        _clear_proxy()
        import akshare as ak
        df = ak.stock_info_global_em()
        for _, r in df.iterrows():
            title = str(r.get("标题", "") or "")
            summary = str(r.get("摘要", "") or "")[:160]
            t = str(r.get("发布时间", "") or "")[:16]
            if title:
                corpus.append({"title": title, "summary": summary, "time": t})
        json.dump(corpus, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        # 优雅降级：尝试读旧缓存
        if os.path.exists(cache):
            try:
                return json.load(open(cache, encoding="utf-8"))
            except Exception:
                pass
        corpus = []
    return corpus


# ═════════════════════════════════════════════════════
#  辅助
# ═════════════════════════════════════════════════════
def _sentiment(text):
    s = 0
    for w in POS:
        if w in text:
            s += 1
    for w in NEG:
        if w in text:
            s -= 1
    if s > 0:
        return "positive"
    if s < 0:
        return "negative"
    return "neutral"


def _global_driver():
    """读 global_history 最新一日 KOSPI/TWII/NKY 涨跌（亚洲科技风险偏好）。"""
    out = {}
    try:
        import sqlite3
        con = sqlite3.connect(DB, timeout=30)
        for sym, name in [("KS11", "韩国KOSPI"), ("TWII", "台湾加权"), ("NKY", "日经225")]:
            cur = con.execute(
                "SELECT date, close, change_pct FROM global_history WHERE symbol=? "
                "ORDER BY date DESC LIMIT 2", (sym,))
            rows = cur.fetchall()
            if len(rows) >= 2:
                chg = (rows[0][1] - rows[1][1]) / rows[1][1] * 100
                out[sym] = {"name": name, "date": rows[0][0], "change_pct": round(chg, 2)}
        con.close()
    except Exception:
        pass
    return out


# 聚合类标题：非具体催化，仅作兜底，不进入头条催化
NOISE_TITLES = ["新闻精选", "盘前必读", "财经早参", "早知道", "盘后公告", "晚报", "午间复盘",
                "早间新闻", "财经早餐", "三大指数", "收评", "午评", "早评", "盘前策略", "电报汇总"]


def _match_news(board, chain, corpus):
    kws = chain.get("keywords", [])
    scored = []
    for c in corpus:
        title = c["title"]
        blob = title + c["summary"]
        if not any(k in blob for k in kws):
            continue
        # 标题命中权重高于摘要，聚合类标题降权
        title_hit = sum(1 for k in kws if k in title)
        summ_hit = sum(1 for k in kws if k in c["summary"])
        is_noise = any(n in title for n in NOISE_TITLES)
        score = title_hit * 2 + summ_hit - (3 if is_noise else 0)
        if score <= 0:
            continue
        scored.append({**c, "sentiment": _sentiment(blob), "_score": score, "title_hit": title_hit})
    scored.sort(key=lambda x: (x["_score"], x["time"]), reverse=True)
    return scored[:3]


def _confidence(chain_known, hits, leader):
    score = 0
    if chain_known:
        score += 0.35
    if leader:
        score += 0.1
    # 仅「标题命中」的催化计入置信（摘要命中为弱关联，不加分）
    title_hits = sum(1 for h in hits if h.get("title_hit", 0) > 0)
    score += min(0.4, 0.2 * title_hits)
    # 新闻最新度加权（仅标题命中）
    now = datetime.datetime.now()
    for h in hits:
        if h.get("title_hit", 0) <= 0:
            continue
        try:
            dt = datetime.datetime.strptime(h["time"], "%Y-%m-%d %H:%M")
            if (now - dt).total_seconds() < 86400:
                score += 0.05
        except Exception:
            pass
    return round(min(0.95, score), 2)


# ═════════════════════════════════════════════════════
#  主流程
# ═════════════════════════════════════════════════════
def run() -> dict:
    # 1) 板块资金
    sm_path = os.path.join(OUTPUT, "sector_mainline.json")
    boards = []
    trade_date = ""
    if os.path.exists(sm_path):
        sm = json.load(open(sm_path, encoding="utf-8"))
        trade_date = sm.get("trade_date", "")
        boards = sm.get("top10_net_inflow", []) or []

    # 2) 新闻语料
    corpus = fetch_news_corpus()
    has_news = len(corpus) > 0

    # 3) 全球驱动
    gdrv = _global_driver()

    # 4) 逐板块构建叙事
    narratives = []
    for b in boards:
        name = b.get("sector", "")
        chain = INDUSTRY_CHAIN.get(name)
        chain_known = chain is not None
        hits = _match_news(name, chain, corpus) if (chain_known and has_news) else []
        sent = "neutral"
        if hits:
            ps = sum(1 for h in hits if h["sentiment"] == "positive")
            ns = sum(1 for h in hits if h["sentiment"] == "negative")
            sent = "positive" if ps > ns else ("negative" if ns > ps else "neutral")
        # 仅「标题命中」的催化才算强信号（摘要命中为间接关联）
        title_hits = [h for h in hits if h.get("title_hit", 0) > 0]

        # 资金方向（净流入为正）
        net = b.get("net_now", 0) or 0
        flow_dir = "in" if net > 0 else "out"

        # 背离检测：资金流入但新闻偏空，或流出但新闻偏多
        divergence = (flow_dir == "in" and sent == "negative") or \
                     (flow_dir == "out" and sent == "positive")

        # 全球联动句
        global_note = ""
        if chain and chain.get("global") and gdrv:
            parts = []
            for sym in ("KS11", "TWII"):
                if sym in gdrv:
                    g = gdrv[sym]
                    arrow = "走强" if g["change_pct"] > 0 else "走弱"
                    parts.append(f"{g['name']}{arrow}({g['change_pct']:+.2f}%)")
            if parts:
                global_note = "亚洲科技链：" + "、".join(parts) + "。"

        # 结论：共振需「标题命中」的催化支撑，避免摘要噪声误判
        resonant_pos = any(h["sentiment"] == "positive" for h in title_hits)
        resonant_neg = any(h["sentiment"] == "negative" for h in title_hits)
        if divergence:
            verdict = "⚠️ 背离：资金面与新闻面信号相反，需人工确认方向"
        elif flow_dir == "in" and resonant_pos:
            verdict = "资金+催化共振，主线成立"
        elif flow_dir == "in" and resonant_neg:
            verdict = "资金流入但催化偏空，警惕冲高回落"
        elif flow_dir == "in":
            verdict = "资金主导，原因暂未明确（资金驱动），继续观察"
        elif flow_dir == "out" and resonant_neg:
            verdict = "资金流出+催化偏空，回避"
        else:
            verdict = "资金流出，暂观望"

        logic = chain["logic"] if chain_known else "（该板块暂无内置产业链逻辑，仅作资金面描述）"
        theme = chain["theme"] if chain_known else ""

        # one_liner：优先用标题命中催化
        top_cat = next((h for h in hits if h.get("title_hit", 0) > 0), hits[0] if hits else None)
        if top_cat:
            one_liner = f"{logic} 实时催化：{top_cat['title']}（{top_cat['time'][-5:]}）"
        else:
            one_liner = logic

        narratives.append({
            "board": name,
            "net_now": round(net, 2),
            "chg_pct": b.get("chg_pct"),
            "leader": b.get("leader", ""),
            "theme": theme,
            "chain_logic": logic,
            "global_note": global_note,
            "catalysts": [{"title": h["title"], "time": h["time"],
                           "sentiment": h["sentiment"], "title_hit": h.get("title_hit", 0) > 0}
                          for h in hits],
            "news_count": len(hits),
            "news_sentiment": sent,
            "flow_dir": flow_dir,
            "divergence": divergence,
            "verdict": verdict,
            "confidence": _confidence(chain_known, hits, b.get("leader")),
            "one_liner": one_liner,
        })

    # 头条：最强共振 or 最高净流入
    headline = ""
    if narratives:
        ranked = sorted(narratives, key=lambda x: (x["net_now"], x["confidence"]), reverse=True)
        top = ranked[0]
        headline = f"今日最强资金主线：{top['board']}（净流入 {top['net_now']} 亿）" + \
                   (f" — {top['theme']}" if top["theme"] else "")

    report = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "news_date": datetime.date.today().isoformat(),
        "has_news": has_news,
        "news_count": len(corpus),
        "global_driver": gdrv,
        "headline": headline,
        "narratives": narratives,
    }
    out = os.path.join(OUTPUT, "narrative_report.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return report


if __name__ == "__main__":
    rep = run()
    print(f"has_news={rep['has_news']} news_count={rep['news_count']} boards={len(rep['narratives'])}")
    print("headline:", rep["headline"])
    for n in rep["narratives"][:6]:
        print(f"  {n['board']} | 净流入{n['net_now']}亿 | 新闻{n['news_count']}条({n['news_sentiment']}) | "
              f"{'背离' if n['divergence'] else ''}{n['verdict']}")
        if n["catalysts"]:
            print(f"     催化: {n['catalysts'][0]['title'][:46]} [{n['catalysts'][0]['time'][-5:]}]")
