# -*- coding: utf-8 -*-
"""
情景推演引擎 (Scenario Engine)
================================
回答买方每天第三个真问题的延伸——「明天会发生什么 / 我怎么办」：

    * 不是罗列事件日历（catalyst_calendar 已做），而是识别「明日最大摆动变量」；
    * 为每个变量构造 2~3 个条件分支（超预期 / 符合 / 落空）；
    * 每分支映射「受益板块 / 受损板块 + 基准概率 + 确认信号」；
    * 板块赢家/输家只对当前真实流向的板块下结论，绝不凭空编造；
    * 给出「失效开关」——哪个信号出现 → 基准情景失效。

与 catalyst_calendar（事件列表）的本质区别：
    事件日历回答「哪天有什么会」；情景引擎回答「若 X 发生 → 谁赢谁输」。

输入（只读，不修改任何既有产物）：
    output/sector_mainline.json   (90 板块 net_now / chg_pct / leader)
    output/flow_report.json       (ETF 申购/赎回榜 + 南向)
    output/panqian_feed.json      (盘前纪要叙事事件)
    output/brain_report.json      (L2/L7 信号，宏观/风险变量)
    database/vibe_research.db     (global_history: SOXX/KOSPI/科创50)

输出：build() -> dict
    trade_date, variables[], summary, key_switches[], n_variables
    variables[i] = {id,title,why,source,evidence,branches[],base_case,implication}
    branches[j]  = {name,weight,market,winners[],losers[],watch}
"""
import os
import json
import sqlite3
from collections import Counter
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
DB_PATH = os.path.join(ROOT, "database", "vibe_research.db")

# ── 板块主题归类（赢家/输家解析始终基于当前真实流向）──
THEME_KW = {
    "科技AI": ["AI", "人工智能", "半导体", "芯片", "通信", "5G", "算力", "机器人", "科创",
             "互联网", "恒生科技", "港股通互联网", "传媒", "游戏", "软件", "云计算", "大数据",
             "电子", "计算机", "元件", "光模块", "PCB", "消费电子", "光学"],
    "医药": ["医疗", "医药", "生物", "创新药", "CXO", "中药", "制药", "疫苗", "实验猴",
            "化学制药", "生物制品", "医疗器械", "医疗服务"],
    "消费": ["消费", "白酒", "食品", "饮料", "家电", "汽车", "零售", "免税"],
    "金融": ["证券", "银行", "保险", "金融", "多元金融"],
    "新能源": ["新能源", "光伏", "锂电", "电池", "电力设备", "风电", "储能", "电网"],
    "周期": ["有色", "煤炭", "钢铁", "化工", "石油", "建材", "航运", "工程机械"],
    "黄金": ["黄金", "贵金属"],
    "地产链": ["地产", "房地产", "建材", "家居", "建筑"],
    "军工": ["军工", "国防", "航空装备"],
}


def _theme_of(name):
    for theme, kws in THEME_KW.items():
        if any(k in name for k in kws):
            return theme
    return "其他"


# ── 加载 ──
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
                "chg_pct": float(s.get("chg_pct") or 0),
                "leader": s.get("leader", ""),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows, d.get("trade_date")


def _pick(sectors, themes, direction="in", topn=3):
    """从当前真实流向板块中，按主题解析赢家(direction=in)/输家(direction=out)。
    若无匹配，回退到按 net_now 排序的当前最强/最弱板块（始终诚实）。
    '其他' 主题不参与筛选（避免把未分类板块误判为赢/输家）。"""
    themes = {t for t in themes if t and t != "其他"}
    matched = []
    for s in sectors:
        if direction == "in" and s["net_now"] <= 0:
            continue
        if direction == "out" and s["net_now"] >= 0:
            continue
        stheme = _theme_of(s["sector"])
        if stheme in themes or any(k in s["sector"] for k in themes):
            matched.append(s["sector"])
    if not matched:
        src = sorted(sectors, key=lambda x: x["net_now"], reverse=(direction == "in"))
        matched = [s["sector"] for s in src[:topn]]
    return matched[:topn]


# ═══════════════════════════════════════════════════════
#  变量探测器 1：资金持续性（每天第一个真问题的延伸——钱明天还来吗）
# ═══════════════════════════════════════════════════════
def _var_capital(flow, sectors):
    if not flow:
        return None
    etf = flow.get("etf_flow_summary") or {}
    inflow = etf.get("top_inflow", []) or []
    outflow = etf.get("top_outflow", []) or []
    if not inflow:
        return None
    inst = flow.get("institution") or {}
    south_net = float((inst.get("hsgt") or {}).get("south_net") or 0)
    buy_names = [e.get("name", "") for e in inflow[:5]]
    sell_names = [e.get("name", "") for e in outflow[:5]]
    buy_themes = [t for t in (_theme_of(n) for n in buy_names) if t != "其他"]
    sell_themes = [t for t in (_theme_of(n) for n in sell_names) if t != "其他"]
    dom_buy = Counter(buy_themes).most_common(1)[0][0] if buy_themes else "科技AI"
    dom_sell = Counter(sell_themes).most_common(1)[0][0] if sell_themes else "医药"

    evidence = (f"ETF净申购主攻 {'、'.join(buy_names[:3])}（{'/'.join(dict.fromkeys(buy_themes[:3]))}）；"
                f"南向净买入 {south_net:.0f}亿；但 {'、'.join(sell_names[:3])} 遭净赎回"
                f"（{'/'.join(dict.fromkeys(sell_themes[:3]))}），内部分化")

    branches = [
        {
            "name": "延续净申购",
            "weight": 50,
            "market": f"风险偏好维持，{dom_buy}方向延续，资金继续做多硬科技/港股通",
            "winners": _pick(sectors, set(buy_themes), "in"),
            "losers": _pick(sectors, set(sell_themes), "out"),
            "watch": "若申购榜连续3日同主题 → 主线确认；若单日巨量后转赎 → 短线见顶",
        },
        {
            "name": "转净赎回",
            "weight": 30,
            "market": "增量资金断供，本轮轮动中断，市场回流红利/防御或旧主线",
            "winners": (_pick(sectors, ["金融", "消费", "周期"], "in")
                        or _pick(sectors, [], "in")),
            "losers": _pick(sectors, set(buy_themes), "out"),
            "watch": "若ETF整体转净赎回 → 迁移引擎反证触发，判断失效，降仓至护栏下限",
        },
        {
            "name": "分化加剧",
            "weight": 20,
            "market": "仅少数细分（如半导体设备/证券）获申购，其余退潮，结构性而非全面",
            "winners": _pick(sectors, ["科技AI", "金融"], "in")[:2],
            "losers": _pick(sectors, ["医药", "消费"], "out")[:2],
            "watch": "观察申购是否集中于1-2个细分，若是则只做最强细分、不做扩散",
        },
    ]
    base = (f"基准情景：延续净申购概率最高（{branches[0]['weight']}%），{dom_buy}方向延续；"
            f"但{dom_sell}链遭赎回显示内部分化，宜做结构而非追高")
    impl = ("我怎么办：盯紧ETF申购榜是否连续；若转净赎回立即降仓至护栏下限，"
            "不接高位赎回方向（如医药/恒生科技）。")
    return {
        "id": "capital_persistence",
        "title": "变量一 · 增量资金能否延续净申购（钱明天还来吗）",
        "why": "这是每天第一个真问题『今天有没有钱』的延续；ETF申购+南向是本轮行情的水位表",
        "source": "flow_report.json · ETF申购/赎回榜 + 南向",
        "evidence": evidence,
        "branches": branches,
        "base_case": base,
        "implication": impl,
    }


# ═══════════════════════════════════════════════════════
#  变量探测器 2：产业催化兑现（盘前纪要中的确定性事件）
# ═══════════════════════════════════════════════════════
_CATALYST_KW = ["IPO", "上会", "备案", "公布", "披露", "发布", "发布会", "大会",
                "签约", "中标", "业绩预告", "扭亏", "投产", "获批", "过审", "审议", "进展"]


def _var_industry(panqian, sectors):
    if not panqian:
        return None
    feed = panqian.get("narrative_feed", []) or []
    events = []
    for it in feed:
        theme = it.get("theme", "") or ""
        if any(k in theme for k in _CATALYST_KW):
            events.append(theme)
    seen, uniq = set(), []
    for e in events:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    if not uniq:
        return None
    top = uniq[:3]
    ev_text = "；".join(top)
    has_ipo = any(k in ev_text for k in ["IPO", "上会", "备案", "进展"])
    has_ai = any(k in ev_text for k in ["AI", "手机", "机器人", "发布", "大会"])
    win_themes = {"科技AI", "金融"}
    if has_ipo:
        win_themes.add("金融")
    if has_ai:
        win_themes.add("科技AI")

    branches = [
        {
            "name": "兑现/超预期",
            "weight": 40,
            "market": "催化落地且超预期 → 映射标的+相关产业链启动，风险偏好抬升",
            "winners": _pick(sectors, win_themes, "in"),
            "losers": [],
            "watch": "若IPO过审/AI手机发布亮眼 → 参与映射标的（参股/产业链）",
        },
        {
            "name": "符合预期",
            "weight": 35,
            "market": "事件如期但无超预期 → 资金浅尝辄止，回流已验证主线",
            "winners": _pick(sectors, ["科技AI", "金融"], "in")[:2],
            "losers": [],
            "watch": "若发布/上会平淡 → 不追高题材，等主线放量确认",
        },
        {
            "name": "落空/延期",
            "weight": 25,
            "market": "事件延期或终止 → 题材证伪，映射标的兑现回落",
            "winners": _pick(sectors, ["金融"], "in")[:1],
            "losers": _pick(sectors, ["科技AI", "消费"], "out")[:2],
            "watch": "若IPO上会延期/终止、AI手机发布平淡 → 题材股兑现，回避高位映射标的",
        },
    ]
    base = (f"基准情景：事件如期但超预期有限（{branches[1]['weight']}%），"
            f"资金浅炒后回流已验证主线（半导体/证券）")
    impl = ("我怎么办：近端事件窗口不追高映射标的（参股/题材），等事件确认再加；"
            "若IPO过审+AI手机超预期，消费电子/证券有弹性可顺势。")
    return {
        "id": "industry_catalyst",
        "title": "变量二 · 近端产业催化兑现（盘前纪要确定性事件）",
        "why": f"盘前纪要明确事件：{ev_text[:54]}… 这是明日最确定的题材摆动源",
        "source": "panqian_feed.json · 叙事事件",
        "evidence": ev_text[:120],
        "branches": branches,
        "base_case": base,
        "implication": impl,
    }


# ═══════════════════════════════════════════════════════
#  变量探测器 3：外部/全球 或 宏观政策（回退）
# ═══════════════════════════════════════════════════════
def _global_change(symbols):
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


_GLOB_LABEL = {"SOXX": "美股半导体SOXX", "KS11": "韩国KOSPI", "000688": "科创50"}


def _var_external(flow, sectors, results, panqian=None):
    g = _global_change(["SOXX", "KS11", "000688"])
    g = {k: v for k, v in g.items() if v is not None}
    if g:
        up = {k: v for k, v in g.items() if v > 0}
        down = {k: v for k, v in g.items() if v < 0}
        if up and not down:
            ev = "、".join(f"{_GLOB_LABEL[k]} 近两日 +{v}%" for k, v in up.items()) + "，全球科技风险偏好回暖"
            bull_w, flat_w, bear_w = 50, 30, 20
        elif down and not up:
            ev = "、".join(f"{_GLOB_LABEL[k]} 近两日 {v}%" for k, v in down.items()) + "，全球科技风险偏好回落"
            bull_w, flat_w, bear_w = 20, 30, 50
        else:
            ev = "全球科技分化（" + "、".join(f"{_GLOB_LABEL[k]} {v:+}%" for k, v in g.items()) + "）"
            bull_w, flat_w, bear_w = 35, 35, 30
        branches = [
            {
                "name": "外围 risk-on 延续",
                "weight": bull_w,
                "market": "A股半导体/AI硬件/港股通映射延续",
                "winners": _pick(sectors, ["科技AI"], "in"),
                "losers": [],
                "watch": "隔夜SOXX/KOSPI收涨 → 次日科技高开延续",
            },
            {
                "name": "震荡无方向",
                "weight": flat_w,
                "market": "外围平稳，A股走自身资金逻辑（看ETF/南向）",
                "winners": _pick(sectors, ["科技AI", "金融"], "in")[:2],
                "losers": [],
                "watch": "外围无方向 → 以资金面为准",
            },
            {
                "name": "外围 risk-off",
                "weight": bear_w,
                "market": "全球科技回撤 → A股科技承压，红利/防御占优",
                "winners": _pick(sectors, ["金融", "周期"], "in")[:2],
                "losers": _pick(sectors, ["科技AI"], "out")[:2],
                "watch": "SOXX/KOSPI 单日跌>2% → 科技减仓，转金融/红利防御",
            },
        ]
        base = (f"基准情景：全球科技{'回暖' if (up and not down) else ('回落' if (down and not up) else '分化')}，"
                f"A股以自身资金逻辑为主（{branches[0]['weight']}%延续 / {branches[2]['weight']}%回撤）")
        impl = "我怎么办：开盘前看隔夜SOXX/KOSPI；若risk-off则科技减仓、转金融/红利防御。"
        return {
            "id": "global_risk",
            "title": "变量三 · 全球科技风险偏好（隔夜映射）",
            "why": "A股半导体/AI/港股通对隔夜美股科技与韩国科技链高度敏感，是每日外部摆动源",
            "source": "global_history (SOXX/KOSPI/科创50)",
            "evidence": ev,
            "branches": branches,
            "base_case": base,
            "implication": impl,
        }
    # 全球数据缺失 → 回退宏观/政策变量（可复用盘前纪要宏观关键词）
    return _var_macro(panqian=panqian, sectors=sectors, results=results)


_MACRO_KW = ["GDP", "CPI", "PMI", "PPI", "LPR", "MLF", "降准", "降息", "议息",
             "社融", "信贷", "数据公布", "经济工作会议", "国常会"]


def _var_macro(panqian, sectors, results):
    found = []
    try:
        from catalyst_calendar import get_upcoming_catalysts
        cats = get_upcoming_catalysts(datetime.now().strftime("%Y-%m-%d"), days_ahead=7) or []
        for c in cats:
            nm = (c.get("name") or "")
            if any(k in nm for k in _MACRO_KW):
                found.append(nm)
    except Exception:
        pass
    if not found and panqian:
        for it in panqian.get("narrative_feed", []) or []:
            t = it.get("theme", "") or ""
            if any(k in t for k in _MACRO_KW):
                found.append(t)
    if not found:
        return None
    ev = "；".join(found[:3])
    branches = [
        {
            "name": "超预期宽松/向好",
            "weight": 35,
            "market": "顺周期/金融/地产链占优，风险偏好抬升",
            "winners": _pick(sectors, ["金融", "周期", "消费"], "in"),
            "losers": [],
            "watch": "若降准/降息/数据超预期 → 加仓顺周期",
        },
        {
            "name": "符合预期",
            "weight": 40,
            "market": "成长/科技延续，结构行情不变",
            "winners": _pick(sectors, ["科技AI"], "in")[:2],
            "losers": [],
            "watch": "若政策平淡 → 维持科技成长",
        },
        {
            "name": "低于预期/收紧",
            "weight": 25,
            "market": "避险/红利占优，成长承压",
            "winners": _pick(sectors, ["金融", "周期"], "in")[:1],
            "losers": _pick(sectors, ["科技AI"], "out")[:2],
            "watch": "若数据走弱/收紧 → 降仓成长转防御",
        },
    ]
    base = f"基准情景：政策/数据符合预期（{branches[1]['weight']}%），成长科技延续"
    impl = "我怎么办：重大宏观窗口前不重仓赌方向，等数据落地后再调结构。"
    return {
        "id": "macro_policy",
        "title": "变量三 · 宏观/政策变量（数据窗口）",
        "why": f"近端宏观事件：{ev[:50]}… 是风格切换（顺周期 vs 成长）的总开关",
        "source": "catalyst_calendar / panqian_feed",
        "evidence": ev[:120],
        "branches": branches,
        "base_case": base,
        "implication": impl,
    }


# ═══════════════════════════════════════════════════════
#  汇总
# ═══════════════════════════════════════════════════════
def _make_summary(variables):
    if not variables:
        return "暂无足够数据生成明日情景推演。"
    parts = [v.get("base_case", "") for v in variables if v.get("base_case")]
    if parts:
        return "明日情景总览：" + "；".join(parts[:3]) + "。"
    return "明日最大摆动变量：" + "、".join(
        v["title"].split("·")[-1].strip() for v in variables) + "。"


def build(save=True):
    """构建情景推演报告。返回 dict（见模块 docstring）。"""
    sectors, td = _load_sectors()
    if not sectors:
        return {"trade_date": td, "variables": [], "summary": "板块数据缺失，情景推演无法进行",
                "key_switches": [], "n_variables": 0, "error": "no sector data"}
    flow = _load_json(os.path.join(OUT, "flow_report.json"))
    panqian = _load_json(os.path.join(OUT, "panqian_feed.json"))
    brain = _load_json(os.path.join(OUT, "brain_report.json")) or {}
    results = brain.get("results", {}) or {}

    variables = []
    v1 = _var_capital(flow, sectors)
    if v1:
        variables.append(v1)
    v2 = _var_industry(panqian, sectors)
    if v2:
        variables.append(v2)
    v3 = _var_external(flow, sectors, results, panqian)
    if v3:
        variables.append(v3)
    variables = variables[:3]

    # 失效开关：取每变量权重最低分支的 watch
    switches = []
    for v in variables:
        if v.get("branches"):
            weakest = min(v["branches"], key=lambda b: b["weight"])
            if weakest.get("watch"):
                switches.append(f"{v['title'].split('·')[-1].strip()}：{weakest['watch']}")

    report = {
        "trade_date": td,
        "variables": variables,
        "summary": _make_summary(variables),
        "key_switches": switches,
        "n_variables": len(variables),
    }
    if save:
        try:
            json.dump(report, open(os.path.join(OUT, "scenario_report.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception:
            pass
    return report


if __name__ == "__main__":
    r = build()
    print(f"交易日: {r['trade_date']}  变量数: {r['n_variables']}")
    print(f"\n【总览】{r['summary']}")
    for v in r["variables"]:
        print(f"\n── {v['title']}")
        print(f"   依据: {v['evidence']}")
        for b in v["branches"]:
            w = b["winners"]
            l = b["losers"]
            print(f"   ▸ {b['name']}({b['weight']}%)：{b['market']}")
            if w:
                print(f"       赢家: {w}")
            if l:
                print(f"       输家: {l}")
        print(f"   基准: {v['base_case']}")
        print(f"   我办: {v['implication']}")
    if r["key_switches"]:
        print("\n【失效开关】")
        for s in r["key_switches"]:
            print(f"   ⚠ {s}")
