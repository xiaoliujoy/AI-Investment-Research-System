# -*- coding: utf-8 -*-
"""
hot_scan.py — 刘晓脱口秀「热点雷达」采集器

职责：
    每天产出一份结构化热点池，作为脱口秀 Writer 的原料之一（三层筛选器第一层：
    「大家在讨论什么」）。本脚本只负责「采集 + 结构化 + 粗分类」，不做「刘晓式
    连接」——那个留给 Writer Engine / 人工。

数据源（全部免登录、本地可跑）：
    L1 财经（稳定，来自 akshare venv）：
        - stock_info_global_em   东财快讯（财经 + 部分社会要闻，~200 条）
        - stock_hot_rank_em     东财热股榜（~100 条，个股情绪温度计）
    L2 大众（全品类，来自今日头条公开接口）：
        - https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc
    L3 手动（可选，你贴的微博/抖音/小红书热点）：
        - backend/hot_manual.md（格式见文件底部说明）

输出：
    backend/output/hot_pool_YYYY-MM-DD.md
    backend/output/hot_pool_YYYY-MM-DD.json

用法：
    python hot_scan.py                  # 抓今天
    python hot_scan.py --date 2026-08-19
    python hot_scan.py --only headline  # 只抓头条大众榜
    python hot_scan.py --only finance   # 只抓财经（快讯+热股榜）
"""
import os
import sys
import json
import argparse
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

HEADLINE_URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ---------------------------------------------------------------------------
# 大众热点分类
#   优先级：头条官方 InterestCategory（list 标签）> 关键词命中
# ---------------------------------------------------------------------------
_INTEREST_MAP = {
    "news_politics": "时政", "politics": "时政", "news_world": "时政", "world": "时政",
    "news_military": "时政", "military": "时政",
    "news_society": "社会", "society": "社会",
    "news_finance": "财经", "finance": "财经", "stock": "财经", "news_stock": "财经",
    "news_house": "财经", "house": "财经",
    "news_entertainment": "娱乐", "entertainment": "娱乐", "fun": "娱乐", "fun_news": "娱乐",
    "news_sports": "体育", "sports": "体育",
    "news_tech": "科技", "tech": "科技", "digital": "科技",
    "news_edu": "教育", "education": "教育",
    "news_health": "民生", "health": "民生", "news_baby": "民生", "baby": "民生",
    "news_food": "民生", "food": "民生", "news_travel": "民生", "travel": "民生",
    "news_car": "其他", "car": "其他", "news_game": "其他", "game": "其他",
}


def map_interest(v):
    if isinstance(v, list):
        for x in v:
            if x in _INTEREST_MAP:
                return _INTEREST_MAP[x]
    elif isinstance(v, str) and v in _INTEREST_MAP:
        return _INTEREST_MAP[v]
    return None


_CATEGORY_RULES = [
    ("娱乐", ["明星", "综艺", "电影", "电视剧", "歌手", "演唱会", "票房", "导演", "主演", "脱口秀", "选秀", "爱豆", "偶像", "网红", "主播", "直播", "剧集", "影片", "大片", "代言", "身材", "出演", "角色", "粉丝", "组合", "单曲", "专辑", "综艺"]),
    ("体育", ["国足", "世界杯", "奥运", "联赛", "夺冠", "球队", "球员", "篮球", "足球", "羽毛球", "乒乓", "游泳", "田径", "教练", "梅西", "C罗", "NBA", "CBA", "马拉松", "冬奥", "球星"]),
    ("财经", ["股票", "基金", "股市", "A股", "美股", "港股", "楼市", "房价", "经济", "央行", "降息", "加息", "GDP", "黄金", "比特币", "通胀", "理财", "券商", "上市", "财报", "净利润", "市值", "IPO", "汇率", "人民币", "救市", "国债", "收益率", "消费", "市场", "投资", "融资", "破产", "裁员", "散户", "板块", "成交额"]),
    ("科技", ["AI", "人工智能", "芯片", "半导体", "手机", "发布", "华为", "苹果", "小米", "特斯拉", "机器人", "大模型", "算力", "新能源", "自动驾驶", "卫星", "火箭", "航天", "量子", "互联网", "算法", "数据"]),
    ("教育", ["高考", "中考", "考研", "大学", "高校", "学校", "教育部", "留学生", "学区", "补课", "教师", "招生", "专业", "论文", "报到", "学费"]),
    ("时政", ["主席", "总统", "外交部", "制裁", "战争", "会谈", "峰会", "联合国", "国务院", "部委", "政策", "条例", "法案", "选举", "阅兵", "航母", "军演", "院士", "将军", "国防", "外交", "中方", "美方", "俄", "冲突", "声明", "领导人"]),
    ("社会", ["地震", "台风", "暴雨", "洪水", "火灾", "事故", "车祸", "坠", "失联", "遇难", "救援", "判刑", "逮捕", "诈骗", "通报", "调查", "曝光", "维权", "判决", "法院", "警察", "卖淫", "枪击", "腐败", "谣言", "被捕", "案件", "落马", "查处", "打拐", "拐卖"]),
    ("民生", ["工资", "养老金", "医保", "社保", "物价", "菜价", "油价", "电费", "物业费", "房租", "就业", "失业", "退休", "生育", "结婚", "离婚", "养老", "补贴", "生活费", "彩礼", "房价"]),
]


def classify(text):
    t = text or ""
    for cat, kws in _CATEGORY_RULES:
        for kw in kws:
            if kw in t:
                return cat
    return "其他"


# ---------------------------------------------------------------------------
# 采集器
# ---------------------------------------------------------------------------
def scan_eastmoney_news(limit=30):
    """东财快讯：财经 + 社会要闻。market_related=True。"""
    import akshare as ak
    items = []
    try:
        df = ak.stock_info_global_em()
    except Exception as e:
        return [], f"东财快讯失败: {type(e).__name__}: {str(e)[:120]}"
    for _, row in df.head(limit).iterrows():
        title = str(row.get("标题", "")).strip()
        if not title:
            continue
        items.append({
            "src": "eastmoney_news",
            "category": "财经" if classify(title) == "其他" else classify(title),
            "title": title,
            "time": str(row.get("发布时间", "")).strip(),
            "url": str(row.get("链接", "")).strip(),
            "summary": str(row.get("摘要", "")).strip()[:160],
            "market_related": True,
            "hot": None,
        })
    return items, f"OK {len(items)}"


def scan_eastmoney_hot_rank(limit=20):
    """东财热股榜：个股情绪温度计。market_related=True。"""
    import akshare as ak
    items = []
    try:
        df = ak.stock_hot_rank_em()
    except Exception as e:
        return [], f"热股榜失败: {type(e).__name__}: {str(e)[:120]}"
    for i, (_, row) in enumerate(df.head(limit).iterrows(), 1):
        name = str(row.get("股票名称", "")).strip()
        chg = str(row.get("涨跌幅", "")).strip()
        title = f"{name} {chg}%"
        items.append({
            "src": "eastmoney_hot",
            "category": "财经",
            "title": title,
            "rank": i,
            "url": "",
            "summary": f"东财热股榜第{i}名，最新价 {str(row.get('最新价','')).strip()}",
            "market_related": True,
            "hot": None,
        })
    return items, f"OK {len(items)}"


def scan_headline(limit=50):
    """今日头条热榜：全品类大众热点。market_related=False（留给 Writer 联想）。"""
    import requests
    items = []
    try:
        r = requests.get(HEADLINE_URL, timeout=20, headers=UA)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        return [], f"头条热榜失败: {type(e).__name__}: {str(e)[:120]}"
    for i, it in enumerate(data[:limit], 1):
        title = str(it.get("Title") or it.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "src": "headline",
            "category": map_interest(it.get("InterestCategory")) or classify(title),
            "title": title,
            "rank": i,
            "url": str(it.get("Url") or it.get("url") or it.get("ActionUrl") or "").strip(),
            "summary": str(it.get("QueryWord") or it.get("queryWord") or "").strip()[:80],
            "market_related": False,
            "hot": it.get("HotValue") or it.get("hotValue") or None,
        })
    return items, f"OK {len(items)}"


def scan_manual(date_str):
    """手动输入：读 backend/hot_manual.md，按行解析。格式见文件底部。"""
    path = os.path.join(ROOT, "hot_manual.md")
    if not os.path.exists(path):
        return [], "无手动输入文件"
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 支持「- 标题」或「标题」两种；可选「[类别] 标题」
            t = line.lstrip("- ").strip()
            cat = "其他"
            if t.startswith("[") and "]" in t:
                cat = t[1:t.index("]")].strip()
                t = t[t.index("]") + 1:].strip()
            items.append({
                "src": "manual",
                "category": cat,
                "title": t,
                "rank": None,
                "url": "",
                "summary": "手动输入",
                "market_related": None,
                "hot": None,
            })
    return items, f"OK {len(items)}"


# ---------------------------------------------------------------------------
# 去重 + 输出
# ---------------------------------------------------------------------------
def _norm(s):
    return "".join(ch for ch in str(s) if ch.isalnum())


def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = _norm(it["title"])[:20]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def render_md(date_str, all_items, stats):
    lines = []
    lines.append(f"# 刘晓脱口秀热点池 · {date_str}\n")
    lines.append("> 三层筛选器第一层「大家在讨论什么」。第三层「刘晓式连接」由 Writer 完成。\n")
    lines.append(f"> 统计：财经 {stats['finance']} 条 · 大众 {stats['headline']} 条 · 手动 {stats['manual']} 条 · 合计 {len(all_items)} 条\n")

    groups = {
        "📊 财经（东财快讯 + 热股榜）": [i for i in all_items if i["src"] in ("eastmoney_news", "eastmoney_hot")],
        "🌐 大众热点（今日头条）": [i for i in all_items if i["src"] == "headline"],
        "✍️ 手动输入（你贴的）": [i for i in all_items if i["src"] == "manual"],
    }
    for gname, gitems in groups.items():
        if not gitems:
            continue
        lines.append(f"\n## {gname}\n")
        for idx, it in enumerate(gitems, 1):
            rank = f"#{it['rank']} " if it.get("rank") else ""
            src_tag = {"eastmoney_news": "快讯", "eastmoney_hot": "热股", "headline": "头条", "manual": "手动"}[it["src"]]
            lines.append(f"{idx}. **[{src_tag}]{rank}{it['category']}** {it['title']}")
            meta = []
            if it.get("time"):
                meta.append(f"时间 {it['time']}")
            if it.get("hot"):
                meta.append(f"热度 {it['hot']}")
            if it.get("url"):
                meta.append(f"链接 {it['url']}")
            if meta:
                lines.append(f"   {' | '.join(meta)}")
            if it.get("summary") and it["summary"] != "手动输入":
                lines.append(f"   {it['summary']}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="刘晓脱口秀热点雷达")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y-%m-%d"), help="热点池日期")
    ap.add_argument("--only", choices=["finance", "headline", "manual", "all"], default="all")
    args = ap.parse_args()
    date_str = args.date

    finance_items, f_msg = [], "skip"
    headline_items, h_msg = [], "skip"
    manual_items, m_msg = [], "skip"

    if args.only in ("finance", "all"):
        n1, f_msg = scan_eastmoney_news()
        n2, _ = scan_eastmoney_hot_rank()
        finance_items = n1 + n2
    if args.only in ("headline", "all"):
        headline_items, h_msg = scan_headline()
    if args.only in ("manual", "all"):
        manual_items, m_msg = scan_manual(date_str)

    all_items = dedupe(finance_items + headline_items + manual_items)
    stats = {"finance": len(finance_items), "headline": len(headline_items), "manual": len(manual_items)}

    md = render_md(date_str, all_items, stats)
    md_path = os.path.join(OUT, f"hot_pool_{date_str}.md")
    json_path = os.path.join(OUT, f"hot_pool_{date_str}.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "items": all_items, "stats": stats,
                   "debug": {"finance": f_msg, "headline": h_msg, "manual": m_msg}},
                  f, ensure_ascii=False, indent=2)

    print(f"热点池已生成: {md_path}")
    print(f"  财经 {stats['finance']} · 大众 {stats['headline']} · 手动 {stats['manual']} · 合计 {len(all_items)}")
    print(f"  debug: finance=[{f_msg}] headline=[{h_msg}] manual=[{m_msg}]")


if __name__ == "__main__":
    main()
