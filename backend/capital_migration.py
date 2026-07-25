# -*- coding: utf-8 -*-
"""
资本迁移引擎 (Capital Migration Engine)
=======================================
回答买方每天真正的三个问题：
    1. 今天有没有钱？   -> flow 总分 / ETF 申购 / 南向
    2. 钱去哪了？       -> 板块轮动图（离开谁 / 进入谁 / 迁移链）
    3. 我怎么办？       -> 一句话结论 + 反证决策树

与静态"排行榜"的本质区别：
    * 不只看今日净流入绝对值，而是看「5日曾流出、今日转正」的 *轮动* 信号；
    * 若有历史快照，进一步算 day-over-day 净流变化，给出「昨天→今天」迁移链；
    * 跨资产闭环：把 ETF申购 / 南向 / 国家队 / (SOXX+KOSPI+科创50) 多路信号
      合成一句「N路资金全部指向 X」；
    * 每个结论都附反证决策树（若 X 发生 → 判断失效），绝不写"催化待确认"。

输入（只读，不修改任何既有产物）：
    output/sector_mainline.json  (90 板块 net_now/net_5d/chg_pct/amount)
    output/flow_report.json      (ETF 申购榜 / 南向 / 国家队 / 五问文本)
    output/sector_flow_history.json (本引擎自己维护的每日快照，供 day-over-day)
    backend/database/vibe_research.db -> global_history (SOXX/KOSPI/科创50，若有)

输出：build() 返回 dict，结构见 build()  docstring。
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
HISTORY_PATH = os.path.join(OUT, "sector_flow_history.json")
DB_PATH = os.path.join(ROOT, "database", "vibe_research.db")

# ETF / 主题关键词（用于跨资产闭环归类）
THEME_KEYWORDS = {
    "科技AI": ["AI", "人工智能", "半导体", "芯片", "通信", "5G", "算力", "机器人",
             "科创", "互联网", "恒生科技", "港股通互联网", "传媒", "游戏", "软件",
             "云计算", "大数据", "电子", "计算机", "信息"],
    "医药": ["医疗", "医药", "生物", "创新药", "CXO", "中药", "制药", "疫苗"],
    "消费": ["消费", "白酒", "食品", "饮料", "家电", "汽车", "零售"],
    "金融": ["证券", "银行", "保险", "金融"],
    "新能源": ["新能源", "光伏", "锂电", "电池", "电力设备"],
    "周期": ["有色", "煤炭", "钢铁", "化工", "石油", "建材", "航运"],
    "黄金": ["黄金"],
}


def _classify_theme(name):
    for theme, kws in THEME_KEYWORDS.items():
        for kw in kws:
            if kw in name:
                return theme
    return "其他"


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
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
                "chg_pct": float(s.get("chg_pct") or 0),
                "amount_today": float(s.get("amount_today") or 0),
                "amount_prev": float(s.get("amount_prev") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows, d.get("trade_date")


def _stars_from_flow(flow):
    fs = (flow or {}).get("flow_score", {})
    if isinstance(fs, dict) and fs.get("overall_stars"):
        return int(fs["overall_stars"])
    if isinstance(fs, dict) and fs.get("overall"):
        return max(1, min(5, round(int(fs["overall"]) / 20)))
    return 3


def _build_rotation(sectors, prev_map):
    """板块轮动：离开谁 / 进入谁 / 迁移链。"""
    if not sectors:
        return {"out_top": [], "in_top": [], "chains": [], "detail": []}

    # 今日净流出的（钱离开）
    out = sorted([s for s in sectors if s["net_now"] < 0],
                 key=lambda x: x["net_now"])[:5]
    # 今日净流入的
    inn = sorted([s for s in sectors if s["net_now"] > 0],
                 key=lambda x: x["net_now"], reverse=True)
    # 轮动进入 = 5日曾流出、今日转正（资金切换信号最强）
    reversal_in = [s for s in inn if s["net_5d"] < 0]
    sustained_in = [s for s in inn if s["net_5d"] >= 0]

    in_top = (reversal_in + sustained_in)[:6]

    # day-over-day 迁移链（需历史）
    chains = []
    if prev_map:
        # 昨日净流出最多 -> 今日净流入最多 的配对
        prev_out = sorted(
            [(sec["sector"], prev_map.get(sec["sector"], 0)) for sec in sectors
             if prev_map.get(sec["sector"], 0) < 0],
            key=lambda x: x[1])[:3]
        cur_in = (reversal_in + sustained_in)[:3]
        for i in range(min(len(prev_out), len(cur_in))):
            chains.append(f"{prev_out[i][0]}（昨净流出） → {cur_in[i]['sector']}（今净流入）")
    else:
        # 无历史：用横截面轮动表示「离开 X，进入 Y」
        for i in range(min(len(out), len(in_top))):
            chains.append(f"{out[i]['sector']}（净流出） → {in_top[i]['sector']}（净流入）")

    detail = []
    for s in reversal_in:
        detail.append(f"{s['sector']}：5日净流 {s['net_5d']:+.1f}亿 但今日转正 +{s['net_now']:.1f}亿（资金回流）")
    for s in sustained_in[:3]:
        detail.append(f"{s['sector']}：持续流入（5日 {s['net_5d']:+.1f}亿，今 +{s['net_now']:.1f}亿）")

    return {
        "out_top": [s["sector"] for s in out],
        "in_top": [s["sector"] for s in in_top],
        "reversal_in": [s["sector"] for s in reversal_in],
        "sustained_in": [s["sector"] for s in sustained_in],
        "chains": chains,
        "detail": detail,
    }


def _global_change(symbols):
    """从 global_history 读最新两个交易日涨跌（SOXX/KOSPI/科创50 等）。"""
    if not os.path.exists(DB_PATH):
        return {}
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        out = {}
        for sym in symbols:
            cur.execute(
                "SELECT close FROM global_history WHERE symbol=? "
                "ORDER BY date DESC LIMIT 2", (sym,))
            rows = cur.fetchall()
            if len(rows) == 2:
                a, b = rows[1][0], rows[0][0]
                out[sym] = round((b - a) / a * 100, 2) if a else None
        con.close()
        return out
    except Exception:
        return {}


def _build_cross_asset(flow):
    """跨资产闭环：把 ETF申购 / 南向 / 国家队 / 全球 合成一句。"""
    if not flow:
        return {"sentence": "跨资产数据缺失", "signals": [], "themes": {}}
    etf = (flow.get("etf_flow_summary") or {}).get("top_inflow", []) or []
    inst = flow.get("institution") or {}
    south = inst.get("south_direction", "")
    south_net = float((inst.get("hsgt") or {}).get("south_net") or 0)
    nation = inst.get("national_team") or []

    # ETF 主题归类
    theme_cnt = {}
    etf_names = []
    for e in etf:
        nm = e.get("name", "")
        th = _classify_theme(nm)
        theme_cnt[th] = theme_cnt.get(th, 0) + 1
        etf_names.append(nm)
    # 南向主题
    south_theme = _classify_theme(south + " 港股通互联网")
    # 国家队（宽基托底，非方向主题）
    nation_broad = any(k in " ".join([str(n) for n in nation]) for k in ["沪深300", "上证50", "中证500", "创业板"])

    # 全球（SOXX/KOSPI/科创50）
    g = _global_change(["SOXX", "KS11", "000688"])  # KS11=KOSPI, 000688=科创50
    global_up = {k: v for k, v in g.items() if v is not None and v > 0}
    global_down = {k: v for k, v in g.items() if v is not None and v < 0}

    signals = []
    if etf_names:
        signals.append("ETF净申购主攻：" + "、".join(etf_names[:3]))
    if south_net:
        signals.append(f"南向净买入 {south_net:.0f}亿（{south}）")
    if nation_broad:
        signals.append("国家队增持宽基ETF（托底）")
    for k, v in global_up.items():
        label = {"SOXX": "SOXX", "KS11": "韩国KOSPI", "000688": "科创50"}.get(k, k)
        signals.append(f"{label} 近两日 +{v}%")

    # 跨资产自身的共识主题（仅基于 ETF/南向/全球，不含 A股板块）
    dom = max(theme_cnt, key=theme_cnt.get) if theme_cnt else "其他"
    consensus = dom if theme_cnt else None

    if signals:
        sentence = "跨资产：" + "；".join(signals[:3]) + "。"
    else:
        sentence = "跨资产信号不足，继续观察。"

    if global_down:
        sentence += " 但 " + "、".join(
            f"{'KOSPI' if k=='KS11' else ('科创50' if k=='000688' else k)} {v}%"
            for k, v in global_down.items()) + " 走弱，需警惕外溢。"

    return {"sentence": sentence, "signals": signals,
            "themes": theme_cnt, "consensus": consensus,
            "global": g}


def _build_falsification(rotation, cross, stars):
    """反证决策树：列出让结论失效的条件，并标注当前是否已触发。"""
    tree = []
    # 1. ETF 停止申购 / 转净赎回
    etf_redeem = any("赎回" in s for s in (cross.get("signals") or []))
    tree.append({
        "if": "ETF 由净申购转为持续净赎回",
        "then": "增量资金断供，本轮轮动失效",
        "triggered": etf_redeem,
    })
    # 2. 南向转净流出
    tree.append({
        "if": "南向资金由净流入转为净流出",
        "then": "港股/科技共识松动",
        "triggered": False,
    })
    # 3. 全球(韩国/SOXX/科创50)转弱
    g = cross.get("global") or {}
    weak = any(v is not None and v < 0 for v in g.values())
    tree.append({
        "if": "韩国KOSPI / SOXX / 科创50 集体下跌",
        "then": "全球风险偏好回落，A股科技承压",
        "triggered": weak,
    })
    # 4. 龙头断板
    tree.append({
        "if": "今日最强流入板块龙头股断板/跌破前低",
        "then": "主线证伪，资金回流旧主线或退潮",
        "triggered": False,
    })
    return tree


def build(trade_date=None, save=True):
    """构建资金迁移报告。

    返回 dict:
        trade_date, rating(1-5星), thesis(一句话结论),
        has_history(bool),
        rotation{out_top,in_top,reversal_in,sustained_in,chains,detail},
        cross_asset{sentence,signals,themes,consensus,global},
        falsification[{if,then,triggered}],
        what_to_do(我怎么办)
    """
    sectors, td = _load_sectors()
    flow = _load_json(os.path.join(OUT, "flow_report.json"))
    trade_date = trade_date or td or datetime.now().strftime("%Y-%m-%d")

    # 历史快照
    hist = _load_json(HISTORY_PATH) or {}
    prev_map = hist.get("last", {})
    last_date = hist.get("last_date")
    # 真实历史 = 快照日 ≠ 今日数据日（同日重跑的快照是自身，不能当"昨日"）
    has_history = bool(prev_map) and bool(last_date) and last_date != trade_date

    rotation = _build_rotation(sectors, prev_map if has_history else None)
    cross = _build_cross_asset(flow)
    stars = _stars_from_flow(flow)

    # 一句话结论
    inn = rotation["in_top"]
    out = rotation["out_top"]
    reversal = rotation["reversal_in"]
    focus = reversal[0] if reversal else (inn[0] if inn else "无明显主线")
    avoid = out[0] if out else ""

    # A股板块轮动主题 vs 跨资产共识主题 -> 背离检测
    sector_themes = [_classify_theme(s) for s in inn[:6]]
    from collections import Counter
    sector_theme = Counter(sector_themes).most_common(1)[0][0] if sector_themes else "其他"
    diverge_note = ""
    if cross.get("consensus") and sector_theme not in ("其他",) \
            and cross["consensus"] != sector_theme:
        diverge_note = (f"（注意背离：A股板块今日实际转向【{sector_theme}】，"
                        f"而 ETF/南向仍偏好【{cross['consensus']}】，内外不同步需警惕）")
        stars = min(stars, 3)  # 背离日降低置信

    if inn and out:
        thesis = (f"存量资金切换、非全面牛市：今日资金从 "
                  f"{'、'.join(out[:3])} 流出，转向 "
                  f"{'、'.join(inn[:3])}"
                  f"（{'其中 ' + '、'.join(reversal[:2]) + ' 为5日曾流出今日回流' if reversal else '持续流入'}）。"
                  f"{cross.get('sentence','')}{diverge_note}")
    elif inn:
        thesis = f"资金整体偏多，主攻 {'、'.join(inn[:3])}。{cross.get('sentence','')}{diverge_note}"
    elif out:
        thesis = f"资金整体偏谨慎，{'、'.join(out[:3])} 净流出居前。{cross.get('sentence','')}{diverge_note}"
    else:
        thesis = "板块资金信号平淡。" + cross.get("sentence", "")

    # 我怎么办
    if avoid and rotation["reversal_in"]:
        what_to_do = (f"观察 {focus}（资金今日回流、待放量确认）；"
                      f"不宜追高已高潮的 {avoid}。")
    elif inn:
        what_to_do = f"观察 {focus}；等待放量确认再加仓，不追一致预期。"
    else:
        what_to_do = "未见明确资金主线，控仓观望，等轮动信号。"

    fals = _build_falsification(rotation, cross, stars)

    report = {
        "trade_date": trade_date,
        "rating": stars,
        "thesis": thesis,
        "has_history": has_history,
        "sector_theme": sector_theme,
        "diverge": diverge_note,
        "rotation": rotation,
        "cross_asset": cross,
        "falsification": fals,
        "what_to_do": what_to_do,
        "focus": focus,
        "avoid": avoid,
    }

    if save:
        _save_snapshot(trade_date, sectors)
    return report


def _save_snapshot(trade_date, sectors):
    """落盘今日快照，供明日 day-over-day 迁移。"""
    hist = _load_json(HISTORY_PATH) or {"history": {}}
    snap = {s["sector"]: s["net_now"] for s in sectors}
    hist["history"] = hist.get("history", {})
    hist["history"][trade_date] = snap
    # 同日重跑不覆盖“昨日”快照，避免自引用污染 day-over-day
    if hist.get("last_date") != trade_date:
        hist["last"] = snap
        hist["last_date"] = trade_date
    # 只保留最近 30 天
    dates = sorted(hist["history"].keys())
    for old in dates[:-30]:
        hist["history"].pop(old, None)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    r = build()
    print(f"交易日: {r['trade_date']}  评级: {'★'*r['rating']}{'☆'*(5-r['rating'])}")
    print(f"\n【一句话结论】\n{r['thesis']}")
    print(f"\n【资金离开】 {r['rotation']['out_top']}")
    print(f"【资金进入】 {r['rotation']['in_top']}")
    print(f"【轮动回流】 {r['rotation']['reversal_in']}")
    print("\n【迁移链】")
    for c in r["rotation"]["chains"]:
        print("  -", c)
    print(f"\n【跨资产闭环】\n  {r['cross_asset']['sentence']}")
    print(f"\n【我怎么办】 {r['what_to_do']}")
    print("\n【反证决策树】")
    for f in r["falsification"]:
        tag = "⚠️已触发" if f["triggered"] else "监测中"
        print(f"  - 若 {f['if']} → {f['then']}  [{tag}]")
    print(f"\n[快照] has_history={r['has_history']} -> 已写入 sector_flow_history.json")
