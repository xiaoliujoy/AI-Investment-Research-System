# -*- coding: utf-8 -*-
"""
panqian_parser.py —— 公众号「盘前纪要」解析器（Phase 1）

把一篇盘前纪要（纯文本 / markdown / 微信文章 URL）解析成结构化 JSON，
作为本系统「叙事 / 催化 / 情绪」层的补充输入。

设计原则（对标用户方法论）：
  - 系统只「解析 + 圈定 + 配数据」，不替用户做买卖决策；
  - 纯结构化解析（正则 + 字典命中），不依赖 LLM，确定、可复现、零费用；
  - 解析失败/格式不符时安全降级：保留原始分段文本（sections.raw），
    绝不编造字段，memo 块至少能展示原文摘要；
  - 股票标注优先用 6 位代码（落库于 stock_info），名字命中做辅助。

盘前纪要典型 8 段结构（公众号模板化，高度一致）：
  一、热点事件   二、公告精选   三、全球市场   四、连板涨停
  五、机构游资   六、股价新高   七、新股申购   八、人气热榜

产物：output/panqian_YYYYMMDD.json
同时（自动）触发 panqian_ingest.derive_feed → output/panqian_feed.json

用法：
  python panqian_parser.py article_2026-07-15.txt
  python panqian_parser.py "https://mp.weixin.qq.com/s/xxxx" --date 2026-07-15
  python panqian_parser.py -            # 从 stdin 读（粘贴后 Ctrl-D）
"""
from __future__ import annotations

import os
import re
import sys
import json
import datetime
import argparse

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")

# ── 段规范：按「中文数字 / 阿拉伯数字 / 【】」三种常见标题形态命中 ──
# 顺序即展示顺序；key 用于落库与下游消费。
SECTION_SPECS = [
    ("hotspot",    "热点事件", r"(热点|题材|主题|事件)"),
    ("announce",   "公告精选", r"(公告|财报|业绩|减持|合同|中标|解禁)"),
    ("global",     "全球市场", r"(全球|外围|美股|港股|(?<![\u4e00-\u9fa5])欧股(?![\u4e00-\u9fa5])|汇率|商品|期货|原油|黄金)"),
    ("limit_up",   "连板涨停", r"(连板|涨停|梯队|高度)"),
    ("institution","机构游资", r"(机构|游资|龙虎|席位|北上|外资)"),
    ("new_high",   "股价新高", r"(新高|创历史|阶段高)"),
    ("new_stock",  "新股申购", r"(新股|申购|上市|打新)"),
    ("hot_list",   "人气热榜", r"(人气|热榜|热度|同花顺|东财|排行)"),
]

# 段落探测优先级：越具体的越先匹配，避免「连板梯队和涨停事件」被「事件」误判为热点。
_SECTION_DETECT = [
    ("limit_up",    r"连板|涨停|梯队|高度"),
    ("announce",    r"公告|财报|业绩|减持|合同|中标|解禁"),
    ("global",      r"全球|外围|美股|港股|欧股|汇率|商品|期货|原油|黄金"),
    ("new_high",    r"新高|创历史|阶段高"),
    ("hot_list",    r"人气|热榜|同花顺|东财|排行"),
    ("institution", r"机构|游资|龙虎|席位|北上|外资"),
    ("new_stock",   r"新股|申购|上市|打新"),
    ("hotspot",     r"热点|题材|主题|事件"),
]

# 已知段标题（No.N 行尾可能粘着，作为 rest 出现时跳过，避免计入条目数）
_SECTION_TITLES = {
    "热点事件", "盘前热点事件", "公告精选", "全球市场", "连板涨停",
    "连板梯队和涨停事件", "机构游资", "股价新高", "新股申购", "人气热榜",
}

_CN_NUM = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}

# 公告类型关键词（用于从公告段抽「利好/利空/减持/风险」地雷）
ANNOUNCE_TYPES = {
    "利好": ["利好", "签订", "签署", "中标", "中标合同", "获订单", "重大合同", "项目中标",
            "中标金额", "预增", "扭亏", "回购", "增持", "扩产", "获批", "合作",
            "采购", "投资", "设立", "出资", "合资", "收购", "增资", "定增"],
    "利空": ["利空", "预减", "亏损", "下调", "退市", "立案", "处罚", "业绩下滑", "商誉减值", "暴雷"],
    "减持": ["减持", "股东拟减持", "拟减持", "套现"],
    "风险": ["风险", "警示", "ST", "暂停上市", "违规", "问询", "监管", "诉讼", "担保", "质押", "暂停", "解禁"],
    "解禁": ["解禁", "限售解禁", "首发解禁"],
}

RISK_TYPES = ("减持", "风险", "利空", "解禁")


# ═══════════════════════════════════════════════════════
#  股票标注（代码优先，名字辅助）
# ═══════════════════════════════════════════════════════

def _norm_name(s):
    """股票名归一化：去空白 + 全角Ａ→半角A（stock_info 常存「京东方Ａ」）。"""
    return re.sub(r"\s+", "", s or "").replace("Ａ", "A")


def _load_stock_map():
    """返回 {code: name, norm_name: code}。失败返回空（降级为不标注）。"""
    code2name, name2code = {}, {}
    try:
        import sqlite3
        db = os.path.join(BASE, "database", "vibe_research.db")
        if os.path.exists(db):
            con = sqlite3.connect(db)
            for code, name in con.execute(
                    "SELECT code, name FROM stock_info WHERE name IS NOT NULL AND name<>''"):
                code2name[str(code).strip()] = _norm_name(name)
                nm = _norm_name(name)
                if len(nm) >= 2:
                    name2code.setdefault(nm, str(code).strip())
            con.close()
    except Exception:
        pass
    return code2name, name2code


def _tag_stocks(text, code2name, name2code):
    """从一段文本抽取命中的股票（代码优先，名字辅助）。返回去重 list[code]。"""
    found = []
    seen = set()
    # 1) 6 位代码（仅认 stock_info 里存在的，避免误命中日期/序号）
    for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", text):
        c = m.group(1)
        if c in code2name and c not in seen:
            seen.add(c); found.append(c)
    # 2) 名字子串命中（归一化去空格 + 全角Ａ→半角A 后比对）
    norm = _norm_name(text)
    for nm, code in name2code.items():
        if len(nm) >= 3 and nm in norm and code not in seen:
            seen.add(code); found.append(code)
    return found


# ═══════════════════════════════════════════════════════
#  分段
# ═══════════════════════════════════════════════════════

def _match_section_key(line):
    """按段落探测优先级（_SECTION_DETECT）把一行映射到 key；命中不到返回 None。"""
    for key, rgx in _SECTION_DETECT:
        if re.search(rgx, line):
            return key
    return None


def _split_sections(text):
    """把正文切成 {key: raw_text}。

    真实排版（盘前纪要）：顶层用「No.1 盘前热点事件 … No.8 人气热榜」分隔，
    内部二级小标题才是「一、二、…」「1、2、…」。因此**优先用 No.N 作为段落边界**；
    仅当全文无 No. 标记（极少数变体）时，才回退到「中文数字序数 / 关键词」旧逻辑。
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    no_re = re.compile(r"^\s*No\.?\s*(\d{1,2})\b")
    use_no = sum(1 for ln in lines if no_re.match(ln)) >= 2

    segments = {}            # key -> list[str]
    order = []               # 保持出现顺序
    buf = []
    cur_key = None

    def flush():
        if cur_key is not None:
            segments.setdefault(cur_key, [])
            if cur_key not in order:
                order.append(cur_key)
            segments[cur_key].extend(buf)

    if use_no:
        for ln in lines:
            m = no_re.match(ln)
            if m:
                key = _match_section_key(ln)
                if key is None:                       # 兜底：按 No. 序数定位
                    idx = min(int(m.group(1)) - 1, len(SECTION_SPECS) - 1)
                    key = SECTION_SPECS[idx][0]
                if key != cur_key:
                    flush()
                    cur_key = key
                    buf = []
                # WebFetch 常把「No.N 标题」与首段内容挤在同一行，
                # 若直接 continue 会吞掉该行剩余内容（如 No.8 热榜 / No.6 新高）。
                # 故保留标题之后的内容；纯段标题（恰等于段名/已知段标题）则跳过，避免计数虚高。
                rest = ln[m.end():].strip()
                if rest and rest not in _SECTION_TITLES:
                    buf.append(rest)
                continue
            if cur_key is not None:
                buf.append(ln)
        flush()
    else:
        # 回退：原逻辑（中文数字序数 / 关键词命中；阿拉伯/【】视为子条目）
        head_re = re.compile(
            r"^\s*(?:([一二三四五六七八九十]+)|(\d{1,2}))\s*[、.．\s]\s*([^、\s]{1,12})"
            r"|^\s*【([^】]{1,12})】"
        )
        kw_map = [(k, re.compile(rgx)) for k, rgx in _SECTION_DETECT]
        for ln in lines:
            m = head_re.match(ln)
            matched_key = None
            if m:
                title = (m.group(3) or m.group(4) or "")
                if m.group(1) and m.group(1) in _CN_NUM and 1 <= _CN_NUM[m.group(1)] <= len(SECTION_SPECS):
                    matched_key = SECTION_SPECS[_CN_NUM[m.group(1)] - 1][0]
                else:
                    for key, rgx in kw_map:
                        if rgx.search(title):
                            matched_key = key
                            break
            if matched_key and matched_key != cur_key:
                flush()
                cur_key = matched_key
                buf = []
                continue
            if cur_key is not None:
                buf.append(ln)
        flush()

    # 没切到任何段（格式异常）→ 整篇作为「热点事件」原始段兜底
    if not segments:
        segments["hotspot"] = lines
        order.append("hotspot")
    return {k: "\n".join(segments[k]).strip() for k in order}, order


# ═══════════════════════════════════════════════════════
#  逐段条目提取
# ═══════════════════════════════════════════════════════

_DISCLAIMER = ("不构成投资建议", "基于互联网信息整理", "研究学习", "市场认知能力",
               "仅供参考", "本文内容")


def _iter_lines(raw):
    for ln in raw.splitlines():
        s = ln.strip()
        # 跳过纯标题/空行/分隔线
        if not s or re.fullmatch(r"[=\-—\s]{3,}", s):
            continue
        # 文末免责声明等噪声可能和正文挤在同一行（WebFetch 常见），
        # 只裁掉从首个免责词到行尾的部分，不整行丢弃，避免热榜/新高等内容被误删。
        for k in _DISCLAIMER:
            idx = s.find(k)
            if idx >= 0:
                s = s[:idx].strip()
        if not s:
            continue
        yield s


def _extract_announce(line, code2name, name2code):
    atype, detail = "其他", line
    for t, kws in ANNOUNCE_TYPES.items():
        if any(k in line for k in kws):
            atype = t
            break
    # 公告常带「：」/「:」分隔 类型与内容
    m = re.match(r"^(利好|利空|减持|风险|解禁|中标|签订|合作|预增|预减|回购|增持)\s*[:：]?\s*(.*)$", line)
    if m and atype == "其他":
        atype, detail = m.group(1), (m.group(2) or line)
    return {"type": atype, "stocks": _tag_stocks(line, code2name, name2code), "detail": detail}


def _extract_limit_up(line, code2name, name2code):
    days = None
    m = re.search(r"(\d+)\s*连板", line)
    if not m:
        m = re.search(r"(\d+)\s*板", line)
    if m:
        days = int(m.group(1))
    reason = ""
    rm = re.search(r"[：:]\s*(.*)$", line)
    if rm:
        reason = rm.group(1).strip()
    return {"days": days, "stocks": _tag_stocks(line, code2name, name2code), "reason": reason}


def _extract_new_high(line, code2name, name2code):
    kind = "新高"
    count = None
    sector = ""
    if "历史" in line:
        kind = "历史新高"
    else:
        m = re.search(r"(\d+)\s*日新[高]", line)
        if m:
            kind = f"{m.group(1)}日新高"
    m2 = re.search(r"创新高\s*(\d+)\s*家", line)
    if m2:
        count = int(m2.group(1))
    m3 = re.search(r"主要集中在\s*([\u4e00-\u9fa5A-Za-z]+)", line)
    if m3:
        sector = m3.group(1)
    return {"stocks": _tag_stocks(line, code2name, name2code), "kind": kind,
            "count": count, "sector": sector}


_PLATFORMS = {"同花顺", "东方财富", "通达信", "大智慧", "新浪财经", "雪球"}


def _extract_hot_names(s):
    """从热榜行抽取全部列出的股票名（含不在 stock_info 的）。

    热榜是权威的「市场注意力」数据，源文明确列出几只就该保留几只，
    不能因主数据缺名而静默丢弃（否则 长鑫科技 这类未入库标的会被漏掉）。
    """
    body = re.split(r"[:：]", s, maxsplit=1)[1] if re.search(r"[:：]", s) else s
    # 去掉可能残留在 body 里的另一平台前缀（WebFetch 偶发压行）
    body = re.sub(r"^(同花顺热榜|东方财富热榜|东财热榜|新浪热榜)\s*", "", body)
    out, seen = [], set()
    for t in re.split(r"[、，,\s]+", body):
        t = _norm_name(t).strip("（）()（）")
        if not t or t in _PLATFORMS:
            continue
        if re.fullmatch(r"[一-鿿A-Za-z·]{2,7}", t) and not re.search(r"\d", t):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _extract_hot_list(line, code2name, name2code):
    s = line.strip()
    rank = None
    src = ""
    # 真实排版：同花顺热榜：… / 东方财富热榜：…（无前置序号）→ 按来源定 rank
    if "同花顺" in s:
        src, rank = "同花顺热榜", 1
    elif "东财" in s or "东方财富" in s:
        src, rank = "东方财富热榜", 2
    m = re.match(r"^(\d+)\s*[\.、]?\s*(.*)$", s)
    if m and m.group(1).isdigit() and rank is None:
        rank = int(m.group(1))
    reason = ""
    rm = re.search(r"[：:]\s*(.*)$", s)
    if rm:
        reason = rm.group(1).strip()
    if not src and any(k in s for k in ("人气", "热榜")):
        src = "热榜"
    stocks = _tag_stocks(line, code2name, name2code)
    names = _extract_hot_names(s)
    # 剔除平台自身（同花顺/东方财富等被 source 文案误标为个股）
    stocks = [c for c in stocks if code2name.get(c) not in _PLATFORMS]
    return {"rank": rank, "stocks": stocks, "names": names, "reason": reason, "source": src}


# ── 地雷阵专项解析（治「停复牌/异动公告」被压行导致真地雷漏检、摘帽被误判）──
_LANDMINE_STRONG = ["减持", "被搜查", "立案", "处罚", "诉讼", "退市", "暴雷", "逮捕",
                    "反垄断", "问询", "监管", "违规", "警示", "套现"]
_LANDMINE_BLOCK_RE = re.compile(r"地雷阵[:：]?\s*(.*?)(?:五[、.．]|六[、.．]|动态更新|\Z)", re.S)
_ENTRY_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z·]{2,8})[：:](.*?)(?=[\u4e00-\u9fa5A-Za-z·]{2,8}[：:]|\Z)", re.S)
_SECTION_LABELS = {"地雷阵", "异动公告", "停复牌", "日常公告", "半年报业绩",
                   "公告精选", "连板梯队", "人气热榜"}


def _classify_landmine(desc):
    if "减持" in desc or "套现" in desc:
        return "减持"
    if any(k in desc for k in ("被搜查", "立案", "处罚", "诉讼", "退市", "暴雷",
                               "反垄断", "问询", "监管", "违规", "警示")):
        return "风险"
    if "利空" in desc:
        return "利空"
    return "风险"


def _extract_landmines(announce_raw, code2name, name2code):
    """从公告段的『地雷阵』子块抽取真实地雷（股票名：描述 + 强风险词）。

    边界用「已知股票名 + ：」锚定，desc 取到下一个股票名之前，
    避免「股东拟减持2.09%股份首华燃气」把尾字「股份」误并入下一名字。
    仅当块内无已知股票名时才回退到关键词锚定（_ENTRY_RE）。
    """
    risk = []
    mb = _LANDMINE_BLOCK_RE.search(announce_raw or "")
    if not mb:
        return risk
    block = mb.group(1)
    # 1) 优先：已知股票名 + ： 作为条目边界
    names_sorted = sorted(name2code.keys(), key=len, reverse=True)
    positions = []
    for nm in names_sorted:
        for m in re.finditer(re.escape(nm) + r"[：:]", block):
            s = m.start()
            e = s + len(nm)
            # 双向区间重叠才跳过（保留最长名字），避免「起点早于已有终点」误杀前置条目
            if any(s < ps + len(pn) and ps < e for ps, pn in positions):
                continue
            positions.append((s, nm))
    positions.sort()
    if positions:
        for i, (pos, nm) in enumerate(positions):
            start = pos + len(nm) + 1
            end = positions[i + 1][0] if i + 1 < len(positions) else len(block)
            desc = block[start:end].strip()
            if nm in _SECTION_LABELS:
                continue
            if not any(k in desc for k in _LANDMINE_STRONG):
                continue
            risk.append({"stock": name2code.get(nm, nm), "type": _classify_landmine(desc),
                         "detail": (nm + "：" + desc)[:80]})
        return risk
    # 2) 回退：块内无已知股票名时，按「名称：描述 + 强风险词」抽取
    for name, desc in _ENTRY_RE.findall(block):
        if name in _SECTION_LABELS:
            continue
        if not any(k in desc for k in _LANDMINE_STRONG):
            continue
        risk.append({"stock": name2code.get(name, name), "type": _classify_landmine(desc),
                     "detail": (name + "：" + desc)[:80]})
    return risk


def _extract_global(line, code2name, name2code):
    # 全球段：识别 市场名 + 涨跌幅
    m = re.search(r"([\u4e00-\u9fa5A-Za-z\.]{1,10})[)\s（(]*([\+\-]?\d+(?:\.\d+)?)\s*%", line)
    market = m.group(1) if m else ""
    chg = float(m.group(2)) if m else None
    return {"market": market, "change_pct": chg, "note": line}


def parse_section(key, raw, code2name, name2code):
    items = []
    for ln in _iter_lines(raw):
        if key == "announce":
            items.append(_extract_announce(ln, code2name, name2code))
        elif key == "limit_up":
            items.append(_extract_limit_up(ln, code2name, name2code))
        elif key == "new_high":
            items.append(_extract_new_high(ln, code2name, name2code))
        elif key == "hot_list":
            # WebFetch 可能把多平台热榜压到同一行（「同花顺热榜：…东方财富热榜：…」），
            # 按平台标记拆行后再逐条解析，避免两源合并成一条、漏掉 rank=2。
            for piece in re.split(r"(?=同花顺热榜|东方财富热榜|东财热榜|新浪热榜)", ln):
                piece = piece.strip()
                if piece:
                    items.append(_extract_hot_list(piece, code2name, name2code))
        elif key == "global":
            items.append(_extract_global(ln, code2name, name2code))
        else:
            # hotspot / institution / new_stock：通用条目（标股票 + 原文）
            # WebFetch 可能把段标题（如「盘前热点事件一、昨日热点」）压进首行，
            # 以已知段标题开头的噪声行跳过（不影响 hot_list 独立分支）。
            if any(ln.startswith(t) for t in _SECTION_TITLES):
                continue
            items.append({"stocks": _tag_stocks(ln, code2name, name2code), "text": ln})
    return items


# ═══════════════════════════════════════════════════════
#  主解析
# ═══════════════════════════════════════════════════════

def parse_article(text: str) -> dict:
    """把文章正文解析为结构化 dict。"""
    code2name, name2code = _load_stock_map()
    segs, order = _split_sections(text)

    sections = {}
    stats = {}
    risk_flags = []
    for key in order:
        raw = segs[key]
        title = next((t for k, t, _ in SECTION_SPECS if k == key), key)
        items = parse_section(key, raw, code2name, name2code)
        # 过滤掉「没标到股票且没语义」的空条目（保留原文在 raw）
        sections[key] = {"title": title, "raw": raw, "items": items}
        stats[key] = len(items)
    # 地雷阵：专项解析公告段子块（不再用整行关键词+必须有代码，避免漏检/误判）
    risk_flags = _extract_landmines(segs.get("announce", ""), code2name, name2code)

    # 自动摘要（无 LLM）
    top_hot = [it for it in sections.get("hotspot", {}).get("items", []) if it.get("stocks")][:3]
    max_chain = 0
    for it in sections.get("limit_up", {}).get("items", []):
        if it.get("days"):
            max_chain = max(max_chain, it["days"])
    nh_count = 0
    for it in sections.get("new_high", {}).get("items", []):
        if it.get("count"):
            nh_count = max(nh_count, it["count"])
    headline = (f"热点 {stats.get('hotspot',0)} 条 · 连板最高 {max_chain} 板 · "
                f"地雷 {len(risk_flags)} 条 · 新高 {nh_count or stats.get('new_high',0)}"
                f" · 热榜 {stats.get('hot_list',0)}")

    return {
        "source": "盘前纪要",
        "article_date": "",          # 由调用方填入
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_url": "",
        "sections": sections,
        "section_order": order,
        "stats": stats,
        "risk_flags": risk_flags,
        "headline": headline,
    }


def _detect_date(text, filename, arg_date):
    if arg_date:
        return arg_date
    # 文件名 panqian_2026-07-15.txt
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filename or "")
    if m:
        return m.group(1)
    # 正文 2026-07-15 或 7月15日
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if m:
        y = datetime.date.today().year
        return f"{y}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return datetime.date.today().isoformat()


# ═══════════════════════════════════════════════════════
#  输入获取（文件 / stdin / URL）
# ═══════════════════════════════════════════════════════

def _fetch_url(url):
    """尽力而为地拉微信文章正文。失败抛异常，由调用方降级提示。"""
    import requests
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Referer": "https://mp.weixin.qq.com/",
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    # 微信返回 HTML，简单抽取 <article> 文本；若安装了 html2text/bs4 也可用
    html = r.text
    # 优先 <script> 之外的正文：取 <article ...>...</article> 或 <div id="js_content">...</div>
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>', html, re.S)
    body = m.group(1) if m else html
    # 去标签
    text = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def run_cli(argv=None):
    ap = argparse.ArgumentParser(description="盘前纪要解析器")
    ap.add_argument("input", help="文章 .txt 路径 / 微信文章 URL / -（stdin）")
    ap.add_argument("--date", help="文章日期 YYYY-MM-DD（缺省自动探测）")
    ap.add_argument("--url", action="store_true", help="强制把 input 当 URL")
    ap.add_argument("--no-ingest", action="store_true", help="只解析不生成 feed")
    args = ap.parse_args(argv)

    # 1) 取正文
    raw_text = None
    is_url = args.url or (isinstance(args.input, str) and args.input.startswith("http"))
    if args.input == "-":
        raw_text = sys.stdin.read()
    elif is_url:
        try:
            raw_text = _fetch_url(args.input)
        except Exception as e:
            print(f"[盘前纪要] URL 抓取失败：{e}\n请改为把文章复制保存为 .txt 再解析。", file=sys.stderr)
            return 1
    elif os.path.exists(args.input):
        with open(args.input, encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()
    else:
        print(f"[盘前纪要] 找不到输入：{args.input}", file=sys.stderr)
        return 1

    # 2) 解析
    parsed = parse_article(raw_text)
    adate = _detect_date(raw_text, args.input if not is_url else "", args.date)
    parsed["article_date"] = adate
    if is_url:
        parsed["source_url"] = args.input

    # 3) 写盘前纪要 JSON
    os.makedirs(OUT, exist_ok=True)
    out_path = os.path.join(OUT, f"panqian_{adate.replace('-', '')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    print(f"[盘前纪要] 解析完成 → {out_path}")
    print(f"  摘要：{parsed['headline']}")
    print(f"  分段：{', '.join(f'{k}={parsed['stats'].get(k,0)}' for k in parsed['section_order'])}")
    if parsed["risk_flags"]:
        print(f"  ⚠️ 地雷阵 {len(parsed['risk_flags'])} 条：",
              "; ".join(f"{r['stock']}({r['type']})" for r in parsed["risk_flags"][:5]))

    # 4) 触发 inge
    if not args.no_ingest:
        try:
            from panqian_ingest import derive_feed
            feed_path = derive_feed(parsed)
            print(f"[盘前纪要] 派生 feed → {feed_path}")
        except Exception as e:
            print(f"[盘前纪要] feed 生成跳过：{e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
