# -*- coding: utf-8 -*-
"""
researcher_agent.py —— 研究员Agent
===================================
从"数据汇总"跃迁到"研究推理"。

输入：brain_report.json + decision_tree.json + narrative_intelligence 输出
输出：四部分研究备忘录（回答10个问题）

设计原则：
  - 规则驱动（非 LLM）：可解释、可复现、无幻觉
  - 从数据推断结论，而非罗列数据
  - 每句话都有数据支撑，区分"数据支持"和"推测"
  - 输出适合三端推送（企微 markdown / 飞书卡片 / Server酱）

四部分结构：
  第一部分：市场故事（今天交易什么 / 为什么 / 一句话金句）
  第二部分：资金行为（钱从哪里流到哪里 / 最大超预期 / 产业链聚焦）
  第三部分：交易机会（真正龙头 / 主线阶段 / 明天观察什么）
  第四部分：风险（逻辑失效条件 / 事件日历）
"""
from __future__ import annotations
import os
import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional
from decision_tree import report_date as _report_date

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)  # backend/
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUTPUT = os.path.join(ROOT, "output")

# ── 辅助函数 ──

def _safe(v, d=None):
    return v if v is not None else d

def _fmt_pct(x):
    """+1.5% 格式化。"""
    try:
        return f"{x:+.2f}%"
    except Exception:
        return "-"

def _fmt_money(x, unit="亿"):
    """+9.7亿 格式化。"""
    try:
        return f"{x:+.1f}{unit}"
    except Exception:
        return "-"

def _fmt_score(s, low=50, med=70):
    """分数→标签。"""
    if s is None:
        return "未知"
    if s >= med:
        return "偏多"
    if s >= low:
        return "中性偏空"
    return "偏空"

def _conf_tag(c):
    """置信度→标签。"""
    if c is None:
        return "推测"
    if c >= 0.8:
        return "数据支持"
    if c >= 0.5:
        return "部分支持"
    return "推测"


# ═══════════════════════════════════════════════════════
#  ResearchMemo 数据结构
# ═══════════════════════════════════════════════════════

@dataclass
class Part1Narrative:
    """第一部分：市场故事"""
    headline: str = ""                    # 今天最重要的一句话（Q10）
    what_trading: str = ""                # 今天市场在交易什么（Q1）
    why_market_moved: str = ""            # 为什么涨/跌（Q3）
    why_detail: list = field(default_factory=list)  # 可能驱动因素列表
    confidence: str = ""                  # 综合置信度


@dataclass
class Part2MoneyFlow:
    """第二部分：资金行为"""
    migration: str = ""                   # 资金迁移路径（Q2）
    from_sectors: list = field(default_factory=list)   # 流出板块
    to_sectors: list = field(default_factory=list)     # 流入板块
    pattern: str = ""                     # 模式：集中攻击/分散轮动/防守切换
    biggest_surprise: str = ""            # 最大超预期（Q4）
    surprise_detail: str = ""             # 超预期细节
    industry_chain: str = ""              # 产业链聚焦（Q5）
    chain_layers: list = field(default_factory=list)   # 产业链层级（含星级+时间维度）


@dataclass
class Part3Trading:
    """第三部分：交易机会"""
    real_leader: str = ""                 # 真正龙头判断（Q6）
    leader_detail: str = ""               # 龙头详情
    no_real_leader: bool = False          # 是否没有真正龙头
    mainline_stages: list = field(default_factory=list)  # 每条主线阶段（Q7）
    tomorrow_watch: list = field(default_factory=list)   # 明天观察（Q8）


@dataclass
class Part4Risk:
    """第四部分：风险"""
    falsification: list = field(default_factory=list)    # 证伪条件（Q9）
    catalyst_events: list = field(default_factory=list)  # 事件日历
    biggest_risk: str = ""                # 最大风险
    risk_position: str = ""               # 风险护栏


@dataclass
class ResearchMemo:
    """完整研究备忘录"""
    trade_date: str = ""
    generated_at: str = ""
    can_buy: str = ""                     # YES/NO/CAUTION
    confidence_score: int = 0
    part1: Part1Narrative = field(default_factory=Part1Narrative)
    part2: Part2MoneyFlow = field(default_factory=Part2MoneyFlow)
    part3: Part3Trading = field(default_factory=Part3Trading)
    part4: Part4Risk = field(default_factory=Part4Risk)


# ═══════════════════════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════════════════════

def _load_data():
    """加载所有数据源。"""
    brain = {}
    tree = {}
    ni = {}

    bp = os.path.join(OUTPUT, "brain_report.json")
    if os.path.exists(bp):
        with open(bp, "r", encoding="utf-8") as f:
            brain = json.load(f)

    tp = os.path.join(OUTPUT, "decision_tree.json")
    if os.path.exists(tp):
        with open(tp, "r", encoding="utf-8") as f:
            tree = json.load(f)

    # 尝试加载 narrative_intelligence 直接输出
    try:
        from narrative_intelligence import run as ni_run
        ni = ni_run() or {}
    except Exception:
        pass

    return brain, tree, ni


# ═══════════════════════════════════════════════════════
#  Q1: 今天市场在交易什么
# ═══════════════════════════════════════════════════════

def _answer_q1(brain, tree, ni):
    """从 L0 + narrative_intelligence 合成叙事。"""
    l0 = brain.get("L0", {})
    gn = l0.get("global_narrative", {})

    headline = gn.get("headline", "")
    if not headline or headline == "数据不可用":
        # 降级：用 L0 主题
        theme = l0.get("theme", "")
        industries = l0.get("confirmed_industries", [])
        if theme and industries:
            headline = f"市场交易的是「{theme}」，资金集中在{'、'.join(industries[:3])}"
        else:
            headline = "今日市场情绪中性，无明显主线叙事"

    # 从 narrative 拆解更具体的"交易什么"
    narrative_name = gn.get("narrative_name", "")
    true_driver = gn.get("true_driver", "")
    weakest_link = gn.get("weakest_link", "")
    match_score = gn.get("match_score", 0)
    a_story = gn.get("a_story", "")

    # 构建中国市场具体叙事
    # 用 L4 主线板块 + L3 产业趋势来具象化
    layers = tree.get("layers", {})
    l3 = layers.get("L3_industry", {}) or {}
    l3_top = l3.get("top_industries", [])
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:3]

    main_names = [m.get("sector", "") for m in mains if m.get("sector")]

    # 生成具体的一句话
    if main_names and a_story:
        what = f"今天市场交易的是「{main_names[0]}」主导行情——{a_story}。{'、'.join(main_names[1:])} 跟涨，但尚未形成全面扩散。"
    elif main_names:
        top_net = mains[0].get("net_now", 0)
        top_stage = mains[0].get("stage", "")
        flow_desc = "资金持续流入" if top_net > 0 else "资金小幅流出"
        what = f"今天市场交易的是「{main_names[0]}」板块——{flow_desc}，当前处于「{top_stage}」阶段。{'、'.join(main_names[1:])} 辅助跟涨。"
    else:
        what = "今日无明显主线，资金分散，市场缺乏共识方向。"

    # 全局叙事（如有）
    if narrative_name:
        what += f" 跨资产视角：全球交易「{narrative_name}」，{true_driver or '驱动变量待确认'}。"

    # 置信度
    if match_score >= 0.8:
        conf = "数据支持"
    elif match_score >= 0.5:
        conf = "部分支持"
    else:
        conf = "推测"

    return what, conf


# ═══════════════════════════════════════════════════════
#  Q2: 钱从哪里流向哪里
# ═══════════════════════════════════════════════════════

def _answer_q2(tree):
    """分析资金迁移路径。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])
    early = l4.get("early_watch", [])

    # 按净流入排序，取前5和后5
    sorted_sectors = sorted(mains, key=lambda x: x.get("net_now", 0), reverse=True)
    top_inflow = [s for s in sorted_sectors[:5] if s.get("net_now", 0) > 0]
    top_outflow = [s for s in sorted_sectors[-5:] if s.get("net_now", 0) < 0]
    top_outflow.reverse()  # 从最负到次负

    # 筛选出有实际净流出的板块（不在 top_inflow 中的）
    all_out = [s for s in sorted_sectors if s.get("net_now", 0) < -0.1]

    # 构建迁移描述
    if top_inflow and all_out:
        in_names = [s["sector"] for s in top_inflow]
        out_names = [s["sector"] for s in all_out]
        in_total = sum(s.get("net_now", 0) for s in top_inflow)
        out_total = abs(sum(s.get("net_now", 0) for s in all_out))
        migration = (
            f"资金从{'、'.join(out_names[:3])}（共流出{out_total:.0f}亿）"
            f" → {'、'.join(in_names[:3])}（共流入{in_total:.0f}亿）。"
        )
        from_list = [{"name": s["sector"], "net": s.get("net_now", 0), "chg": s.get("chg_pct", 0)}
                     for s in all_out[:4]]
        to_list = [{"name": s["sector"], "net": s.get("net_now", 0), "chg": s.get("chg_pct", 0),
                    "stage": s.get("stage", "")}
                   for s in top_inflow[:4]]
    elif top_inflow:
        in_names = [s["sector"] for s in top_inflow]
        in_total = sum(s.get("net_now", 0) for s in top_inflow)
        migration = (
            f"今日主线板块资金集中流入{'、'.join(in_names[:3])}（共{in_total:.0f}亿），"
            f"其余板块资金变化不大，存量博弈特征明显。"
        )
        from_list = []
        to_list = [{"name": s["sector"], "net": s.get("net_now", 0), "chg": s.get("chg_pct", 0),
                    "stage": s.get("stage", "")}
                   for s in top_inflow[:4]]
    else:
        migration = "今日全市场资金净流出，无明显流入方向，建议观望。"
        from_list = [{"name": s["sector"], "net": s.get("net_now", 0), "chg": s.get("chg_pct", 0)}
                     for s in sorted_sectors[:4]]
        to_list = []

    # 资金模式判断
    if len(top_inflow) <= 2 and top_inflow and top_inflow[0].get("net_now", 0) > 3:
        pattern = "集中攻击 —— 资金高度集中在1-2个板块"
    elif len(top_inflow) >= 5:
        pattern = "分散轮动 —— 资金在多个方向试探，无明显主线"
    elif top_outflow and len(top_outflow) >= 3:
        # 检查是否是红利/防御板块流出
        defensive = ["银行", "煤炭", "电力", "钢铁", "石油"]
        out_defensive = [s for s in top_outflow if any(d in s["sector"] for d in defensive)]
        if len(out_defensive) >= 2:
            pattern = "防守→进攻切换 —— 红利/防御板块资金流出，转向成长板块"
        else:
            pattern = "存量轮动 —— 资金在板块间切换，总量未见放大"
    else:
        pattern = "存量博弈 —— 资金小幅轮动，无明确方向"

    return migration, from_list, to_list, pattern


# ═══════════════════════════════════════════════════════
#  Q3: 市场为什么涨/跌
# ═══════════════════════════════════════════════════════

def _answer_q3(brain, tree):
    """分析涨跌背后的可能驱动。"""
    layers = tree.get("layers", {})
    l1 = layers.get("L1_global_macro", {}) or {}
    l2 = layers.get("L2_china_macro", {}) or {}
    l3 = layers.get("L3_industry", {}) or {}
    l4 = layers.get("L4_consensus", {}) or {}
    sentiment = layers.get("sentiment", {}) or {}
    sentiment_state = sentiment.get("state", "")
    up_ratio_raw = sentiment.get("up_ratio", 0)
    up_ratio_pct = round(up_ratio_raw * 100) if 0 < up_ratio_raw < 1 else up_ratio_raw

    drivers = []

    # 1. 宏观驱动
    l1_read = l1.get("read", "")
    l2_read = l2.get("read", "")
    l1_score = l1.get("score", 0) if isinstance(l1.get("score"), (int, float)) else 0
    l2_score = l2.get("score", 0) if isinstance(l2.get("score"), (int, float)) else 0
    if l1_read:
        drivers.append({
            "factor": "全球宏观",
            "detail": l1_read[:100],
            "type": "数据支持" if l1_score >= 70 else "部分支持",
            "data_points": f"L1得分{l1_score}，美元/商品/美股综合判定",
        })
    if l2_read:
        drivers.append({
            "factor": "中国宏观",
            "detail": l2_read[:100],
            "type": "数据支持" if l2_score >= 70 else "部分支持",
            "data_points": f"L2得分{l2_score}，PMI/M2/社融/CPI综合判定",
        })

    # 2. 产业趋势
    l3_read = l3.get("read", "")
    l3_score = l3.get("score", 0) if isinstance(l3.get("score"), (int, float)) else 0
    if l3_read:
        drivers.append({
            "factor": "产业趋势",
            "detail": l3_read[:100],
            "type": "推测" if l3_score < 70 else "部分支持",
            "data_points": f"L3得分{l3_score}，产业方向判定",
        })

    # 3. 资金共识
    mains = l4.get("main_lines", [])[:3]
    for m in mains:
        reason = m.get("reason", "")
        if reason:
            drivers.append({
                "factor": f"板块驱动: {m['sector']}",
                "detail": reason[:80],
                "type": "数据支持",
                "data_points": (
                    f"今日净流入{_fmt_money(m.get('net_now', 0))}，"
                    f"5日累计{_fmt_money(m.get('net_5d', 0))}，"
                    f"阶段「{m.get('stage', '')}」"
                ),
            })

    # 4. 情绪
    if up_ratio_pct > 70:
        drivers.append({
            "factor": "市场情绪",
            "detail": f"上涨家数占比{up_ratio_pct}%，赚钱效应强",
            "type": "数据支持",
            "data_points": f"涨跌比{up_ratio_pct}%，市场广度偏强",
        })
    elif up_ratio_pct < 30:
        drivers.append({
            "factor": "市场情绪",
            "detail": f"上涨家数仅{up_ratio_pct}%，市场普跌",
            "type": "数据支持",
            "data_points": f"涨跌比{up_ratio_pct}%，市场广度偏弱",
        })

    # 合成一句话
    if drivers:
        top_drivers = drivers[:3]
        parts = [f"{d['factor']}：{d['detail']}" for d in top_drivers]
        why = "；".join(parts)
    else:
        why = "无明显宏观/产业驱动信号，市场可能受短期情绪或事件驱动。"

    return why, drivers


# ═══════════════════════════════════════════════════════
#  Q4: 最大超预期
# ═══════════════════════════════════════════════════════

def _answer_q4(tree):
    """识别今日最大超预期（涨跌幅偏离+5日趋势反转）。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])

    # 按涨跌幅绝对值排序
    by_chg = sorted(mains, key=lambda x: abs(x.get("chg_pct", 0)), reverse=True)
    surprise_parts = []

    for s in by_chg[:5]:
        chg = s.get("chg_pct", 0)
        if abs(chg) >= 3:
            direction = "暴涨" if chg > 0 else "暴跌"
            net_now = s.get("net_now", 0)
            net_5d = s.get("net_5d", 0)

            # 趋势反转检测
            reversal = ""
            if net_now > 0 and net_5d < -3:
                reversal = "（趋势反转：5日累计仍流出，今日大幅回流）"
            elif net_now < 0 and net_5d > 3:
                reversal = "（趋势反转：5日累计仍流入，今日急转流出）"
            elif net_now > 2 and net_5d < 0:
                reversal = "（短线拐点：5日流出今日急转流入）"

            surprise_parts.append(
                f"{s['sector']} {direction} {_fmt_pct(chg)}，"
                f"净流入{_fmt_money(net_now)}"
                f"（5日{_fmt_money(net_5d)}）{reversal}"
            )

    if surprise_parts:
        biggest = surprise_parts[0]
        detail = "\n".join(surprise_parts[:3])
    else:
        # 检查是否有方向性异常（涨跌<3%但资金大幅流入）
        by_net = sorted(mains, key=lambda x: abs(x.get("net_now", 0)), reverse=True)
        net_surprises = [s for s in by_net[:3] if abs(s.get("net_now", 0)) > 5]
        if net_surprises:
            biggest = (
                f"{net_surprises[0]['sector']} 净流入{_fmt_money(net_surprises[0].get('net_now', 0))}"
                f"但涨幅仅{_fmt_pct(net_surprises[0].get('chg_pct', 0))}（量价背离值得关注）"
            )
            detail = "\n".join(
                f"{s['sector']} 净流入{_fmt_money(s.get('net_now', 0))}"
                f"（5日{_fmt_money(s.get('net_5d', 0))}）" 
                for s in net_surprises
            )
        else:
            biggest = "今日无显著超预期板块，涨跌幅均在正常范围内。"
            detail = "所有板块涨跌幅均在±3%以内，资金流动平稳。"

    return biggest, detail


# ═══════════════════════════════════════════════════════
#  Q5: 最值得关注的产业链
# ═══════════════════════════════════════════════════════

def _answer_q5(tree):
    """根据主线板块推断产业链聚焦层级。
    
    修复：
    - 使用与 cio_agent 一致的 CHAIN_DETAIL 映射（含产业链层级定义）
    - 每层加星级评分（0-5★），依据：该层板块是否在主线中、净流入幅度、共识阶段
    - 加时间维度：5日趋势（连续流入/震荡/流出）、20日是否首次进入
    """
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:8]

    # ── 产业链星级映射（与 cio_agent 共享） ──
    CHAIN_DETAIL = {
        "半导体": {
            "name": "AI算力产业链",
            "layers": ["GPU/芯片", "先进封装", "PCB/载板", "服务器", "光模块"],
        },
        "半导体及元件": {
            "name": "AI算力产业链",
            "layers": ["GPU/芯片", "先进封装", "PCB/载板", "服务器", "光模块"],
        },
        "计算机设备": {
            "name": "AI算力产业链",
            "layers": ["服务器", "交换机", "存储"],
        },
        "通信": {
            "name": "AI算力产业链",
            "layers": ["光模块", "光通信", "交换机"],
        },
        "计算机": {
            "name": "AI应用产业链",
            "layers": ["基础软件", "云计算", "数据服务", "安全"],
        },
        "消费电子": {
            "name": "AI终端产业链",
            "layers": ["芯片/SoC", "终端组装", "结构件", "显示面板"],
        },
        "传媒": {
            "name": "AI内容产业链",
            "layers": ["游戏", "广告营销", "影视制作", "出版"],
        },
        "汽车": {
            "name": "新能源车产业链",
            "layers": ["整车", "动力电池", "零部件", "智能化"],
        },
        "自动化设备": {
            "name": "机器人产业链",
            "layers": ["伺服/电机", "减速器", "控制器", "传感器"],
        },
        "光伏": {
            "name": "新能源产业链",
            "layers": ["硅料/硅片", "电池片", "组件", "逆变器/电站"],
        },
        "化学制药": {
            "name": "创新药产业链",
            "layers": ["创新药", "CXO", "仿制药", "原料药"],
        },
        "医疗器械": {
            "name": "医疗器械产业链",
            "layers": ["大型设备", "IVD诊断", "耗材", "家用医疗"],
        },
        "银行": {
            "name": "金融/红利",
            "layers": ["银行", "保险", "券商"],
        },
        "煤炭": {
            "name": "能源/周期",
            "layers": ["煤炭", "石油", "电力"],
        },
        "房地产开发": {
            "name": "地产链",
            "layers": ["开发商", "建材", "家居", "物业"],
        },
    }

    def _match_chain(sector_name: str):
        for key, chain in CHAIN_DETAIL.items():
            if key in sector_name:
                return chain
        return None

    def _rating_stars(n: int) -> str:
        return "★" * n + "☆" * (5 - n)

    def _compute_layer_star(layer_name: str, mains, all_sectors_in_chain):
        """计算产业链单层的星级（0-5）。
        
        评分维度：
        - 该层是否有对应板块在主线中（+1★）
        - 该层板块净流入>0（+1★）
        - 该层板块处于"赚钱效应"阶段（+2★）或"资金流入"阶段（+1★）
        - 5日累计净流入>0（+1★）
        """
        stars = 0
        for m in mains:
            ms = m.get("sector", "")
            # 匹配：板块名包含层级关键词
            layer_kws = [kw.strip() for kw in layer_name.replace(" ", "").split("/")]
            matched = any(kw in ms for kw in layer_kws) or \
                      any(ms_kw in layer_name for ms_kw in ms.replace("半导体及元件", "芯片").split("半导体"))
            if not matched:
                continue
            # 基础分：在主线里
            stars += 1
            # 今日净流入
            if m.get("net_now", 0) > 0:
                stars += 1
            # 共识阶段
            stage = m.get("stage", "")
            if stage == "赚钱效应":
                stars += 2
            elif stage == "资金流入":
                stars += 1
            # 5日持续流入
            if m.get("net_5d", 0) > 0:
                stars += 1
            break  # 一个layer只匹配最近的主线板块
        
        return min(stars, 5), stars

    # ── 按主线优先级匹配产业链 ──
    chain_found = None
    sorted_keys = sorted(CHAIN_DETAIL.keys(), key=len, reverse=True)
    for m in mains:
        name = m.get("sector", "")
        for key in sorted_keys:
            if key in name:
                chain_found = CHAIN_DETAIL[key]
                break
        if chain_found:
            break

    if chain_found:
        layers_list = [s.strip() for s in chain_found["layers"]]
        chain_name = chain_found["name"]

        # 计算每层的星级+时间维度
        chain_layer_details = []
        for layer in layers_list:
            star, raw = _compute_layer_star(layer, mains, layers_list)
            # 找匹配的主线板块获取时间维度
            layer_net_5d = 0
            layer_trend_5d = "无数据"
            layer_trend_20d = "无数据"
            layer_sector = ""
            for m in mains:
                ms = m.get("sector", "")
                layer_kws = [kw.strip() for kw in layer.replace(" ", "").split("/")]
                if any(kw in ms for kw in layer_kws):
                    layer_sector = ms
                    net_5d = m.get("net_5d", 0)
                    net_now = m.get("net_now", 0)
                    layer_net_5d = net_5d
                    # 5日趋势
                    if net_5d > 3 and net_now > 0:
                        layer_trend_5d = "连续大幅流入"
                    elif net_5d > 0 and net_now > 0:
                        layer_trend_5d = "小幅净流入"
                    elif net_5d < 0 and net_now > 0:
                        layer_trend_5d = "今日回流（5日仍流出）"
                    elif net_5d < 0 and net_now < -1:
                        layer_trend_5d = "连续流出"
                    else:
                        layer_trend_5d = "震荡"
                    # 20日趋势（简化：看是否在主线前3）
                    rank = next((i+1 for i, mm in enumerate(mains) if mm.get("sector") == ms), 99)
                    if rank <= 3:
                        layer_trend_20d = f"主线排名#{rank}，资金活跃"
                    elif rank <= 8:
                        layer_trend_20d = f"主线排名#{rank}，辅助方向"
                    else:
                        layer_trend_20d = "不在主线"
                    break

            chain_layer_details.append({
                "layer": layer,
                "star_rating": star,
                "stars_display": _rating_stars(star),
                "sector": layer_sector,
                "trend_5d": layer_trend_5d,
                "trend_20d": layer_trend_20d,
                "net_5d": layer_net_5d,
            })

        # 构建展示文本
        max_star = max((l["star_rating"] for l in chain_layer_details), default=0)
        active_layers = [l for l in chain_layer_details if l["star_rating"] >= 2]
        
        if active_layers:
            top_layer = active_layers[0]
            chain_text = (
                f"「{chain_name}」—— 资金集中在 **{top_layer['layer']}** 层"
                f"（{top_layer['stars_display']}，{top_layer['trend_5d']}）"
            )
            if len(active_layers) > 1:
                chain_text += f"，{active_layers[1]['layer']} 层跟随（{active_layers[1]['stars_display']}）"
        else:
            chain_text = f"「{chain_name}」—— 各层资金分散，无显著聚焦层级"

        return chain_text, chain_layer_details

    # 降级：无产业链匹配
    top_names = [m.get("sector", "") for m in mains[:3]]
    fallback_layers = [{"layer": n, "star_rating": 0, "stars_display": "☆☆☆☆☆",
                        "sector": n, "trend_5d": "无数据", "trend_20d": "无数据", "net_5d": 0}
                       for n in top_names]
    chain_text = " → ".join(top_names) if top_names else "无明显产业链关联"
    return chain_text, fallback_layers


# ═══════════════════════════════════════════════════════
#  Q6: 今天真正的龙头是谁
# ═══════════════════════════════════════════════════════

def _is_st(name):
    """过滤 ST/退市 股票。"""
    if not name:
        return False
    return name.startswith("ST") or name.startswith("*ST") or name.startswith("退")


def _sector_in_main_lines(sector_name, main_line_sectors):
    """检查板块名是否在主线板块集合中（精确+模糊匹配）。"""
    if sector_name in main_line_sectors:
        return True
    # 模糊匹配：主线"半导体" 应匹配 leader 中的"半导体及元件"
    for mls in main_line_sectors:
        if mls in sector_name or sector_name in mls:
            return True
    return False


def _answer_q6(tree):
    """判断真正龙头（四龙头共振分析）。
    
    修复：龙头必须从 L4 主线板块成分股里选 —— 
    如果某个板块（如"纺织"）不在一线主线中，即便四龙头共振也不纳入。
    """
    layers = tree.get("layers", {})
    l5 = layers.get("L5_leader", {}) or {}
    l4 = layers.get("L4_consensus", {}) or {}
    leaders = l5.get("leaders", {})

    # ── 获取主线板块集合 ──
    main_lines = l4.get("main_lines", [])
    main_line_sectors = {m.get("sector", "") for m in main_lines if m.get("sector")}
    # 也收录 early_watch（可能有次日爆发）
    early_watch = l4.get("early_watch", [])
    for ew in early_watch:
        if isinstance(ew, dict):
            main_line_sectors.add(ew.get("sector", ""))

    real_leaders = []
    filtered_count = 0  # 追踪被过滤的板块数（诊断用）
    for sec, ld in leaders.items():
        if "error" in ld:
            continue

        # ── 关键修复：只分析主线板块内的龙头 ──
        if not _sector_in_main_lines(sec, main_line_sectors):
            filtered_count += 1
            continue

        ca = ld.get("产业龙头", {}) or {}
        fund = ld.get("资金龙头", {}) or {}
        tech = ld.get("技术龙头", {}) or {}
        sentiment_l = ld.get("情绪龙头", {}) or {}

        ca_name = ca.get("name", "")
        fund_name = fund.get("name", "")
        tech_name = tech.get("name", "")
        sent_name = sentiment_l.get("name", "")

        # 共振分析：名字相同 = 共振（过滤ST股）
        all_names = [n for n in [ca_name, fund_name, tech_name, sent_name] if n and not _is_st(n)]
        if not all_names:
            continue

        # 统计频率
        from collections import Counter
        name_counts = Counter(all_names)
        top_name, top_count = name_counts.most_common(1)[0]

        if top_count >= 3:
            real_leaders.append({
                "sector": sec,
                "name": top_name,
                "resonance": f"四龙头中{top_count}个指向{top_name}，高度共振",
                "strong": True,
                "detail": f"产业龙头:{ca_name} 资金龙头:{fund_name} 技术龙头:{tech_name} 情绪龙头:{sent_name}",
            })
        elif top_count == 2:
            real_leaders.append({
                "sector": sec,
                "name": top_name,
                "resonance": f"四龙头中{top_count}个指向{top_name}，部分共振",
                "strong": False,
                "detail": f"产业龙头:{ca_name} 资金龙头:{fund_name} 技术龙头:{tech_name} 情绪龙头:{sent_name}",
            })
        else:
            real_leaders.append({
                "sector": sec,
                "name": "无共振",
                "resonance": "四龙头各自指向不同个股，未形成共振",
                "strong": False,
                "detail": f"产业:{ca_name} 资金:{fund_name} 技术:{tech_name} 情绪:{sent_name}",
            })

    # 判断是否有真正龙头
    strong_leaders = [l for l in real_leaders if l.get("strong")]
    if strong_leaders:
        sl = strong_leaders[0]
        leader_text = f"真正核心：{sl['name']}（{sl['sector']}），{sl['resonance']}"
        leader_detail = sl["detail"]
        no_real_leader = False
    elif real_leaders:
        # 检查是否有部分共振
        partial = [l for l in real_leaders if l.get("name") != "无共振"]
        if partial:
            p = partial[0]
            leader_text = f"今日未形成高度共振，主线板块{p['sector']}的{p['name']}有部分共振（2/4），需观察。"
            leader_detail = p["detail"]
            no_real_leader = True
        else:
            leader_text = "今天主线板块内没有形成真正龙头。各板块四龙头分散，资金未达成共识。"
            leader_detail = ""
            no_real_leader = True
    elif filtered_count > 0 and not real_leaders:
        # 有板块数据但都不在主线中
        leader_text = f"L5扫描了{len(leaders)}个板块（{filtered_count}个非主线已过滤），主线板块内未形成龙头共振。"
        leader_detail = ""
        no_real_leader = True
    else:
        leader_text = "数据不足，无法判断龙头共振情况。"
        leader_detail = ""
        no_real_leader = True

    return leader_text, leader_detail, no_real_leader, real_leaders


# ═══════════════════════════════════════════════════════
#  Q7: 每条主线在哪个阶段
# ═══════════════════════════════════════════════════════

def _answer_q7(tree):
    """每条主线独立判断共识生命周期阶段。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:8]

    STAGE_DESC = {
        "讨论": "初期讨论，资金观望，需确认",
        "资金流入": "资金开始流入，共识正在形成",
        "赚钱效应": "已经形成赚钱效应，资金涌入加速",
        "一致性": "高度一致，追高风险加大",
        "高潮": "接近高潮，注意退潮信号",
        "退潮": "资金流出，共识瓦解",
    }

    stages = []
    for m in mains:
        s = m.get("stage", "未知")
        desc = STAGE_DESC.get(s, s)
        net = m.get("net_now", 0)
        net_5d = m.get("net_5d", 0)

        # 额外判断持续性
        if net > 0 and net_5d > 0:
            persistence = "持续流入"
        elif net > 0 and net_5d < 0:
            persistence = "今日回流（5日累计仍流出）"
        elif net < 0 and net_5d < 0:
            persistence = "持续流出"
        else:
            persistence = "今日流出（5日累计仍流入）"

        stages.append({
            "sector": m["sector"],
            "stage": s,
            "desc": desc,
            "persistence": persistence,
            "net_today": net,
            "net_5d": net_5d,
            "chg": m.get("chg_pct", 0),
        })

    return stages


# ═══════════════════════════════════════════════════════
#  Q8: 明天重点观察什么
# ═══════════════════════════════════════════════════════

def _answer_q8(tree, real_leaders_data, mainline_stages):
    """根据当前状态推导明天关键观察点。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:5]
    sentiment = layers.get("sentiment", {}) or {}

    watch = []

    # 1. 主线持续性
    for m in mains[:3]:
        name = m.get("sector", "")
        if m.get("stage") in ("赚钱效应", "资金流入"):
            watch.append(f"{name}是否维持成交额第一梯队")
        elif m.get("stage") == "退潮":
            watch.append(f"{name}能否止跌企稳（关键支撑位反弹）")

    # 2. 龙头晋级（过滤ST股）
    has_real = any(l.get("strong") for l in (real_leaders_data or []))
    if has_real:
        for l in (real_leaders_data or []):
            if l.get("strong") and not _is_st(l.get("name", "")):
                watch.append(f"{l['name']}（{l['sector']}）能否继续领涨")
    else:
        watch.append("龙头能否从分散走向共振（至少3/4指向同一只）")

    # 3. 扩散判断
    if len(mains) >= 3:
        names = [m.get("sector", "") for m in mains[:3]]
        watch.append(f"主线是否从{names[0]}扩散到{'、'.join(names[1:])}（观察涨跌幅联动）")

    # 4. 成交额
    watch.append("全市场成交额是否继续放大（缩量则可能退潮）")

    # 5. 情绪
    up_ratio = sentiment.get("up_ratio", 0)
    up_pct = round(up_ratio * 100) if 0 < up_ratio < 1 else up_ratio
    if up_ratio > 70:
        watch.append(f"上涨家数占比{up_pct}%，警惕过热后的分化")
    elif up_ratio < 30:
        watch.append(f"上涨家数仅{up_pct}%，观察是否有抄底资金入场")

    # 6. 资金流向变化
    watch.append("开盘30分钟资金是否延续今日方向（观察主力净流入是否放大）")

    # 补充事件观察
    try:
        from catalyst_calendar import get_upcoming_catalysts
        import datetime
        ref = datetime.date.today()
        cats = get_upcoming_catalysts(ref, days_ahead=3) or []
        high_impact = [c for c in cats if c.get("impact") == "high"]
        if high_impact:
            for c in high_impact[:2]:
                watch.append(f"事件：{c['name']}（{c['date']}，{c.get('country','')}）")
    except Exception:
        pass

    return watch[:8]


# ═══════════════════════════════════════════════════════
#  Q9: 哪些逻辑失效
# ═══════════════════════════════════════════════════════

def _answer_q9(brain, tree, mainline_stages):
    """推导可能的逻辑失效条件。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:5]

    fals = []

    # 1. 主线退潮条件
    for m in mains[:3]:
        name = m.get("sector", "")
        net = m.get("net_now", 0)
        if net > 0 and m.get("stage") != "退潮":
            fals.append(f"如果 {name} 成交额跌出前三 → 说明今日只是短期轮动，非真正主线")
            if m.get("stage") == "赚钱效应":
                fals.append(f"如果 {name} 明日净流入转负 → 赚钱效应可能中断，转为退潮")

    # 2. 龙头失效条件（从 narrative_intelligence 获取）
    gn = brain.get("L0", {}).get("global_narrative", {})
    fals_text = gn.get("falsification_text", "")
    if fals_text:
        fals.append(f"叙事证伪：{fals_text[:120]}")

    # 3. 全局失效条件
    stage_dist = l4.get("stage_distribution", {})
    if stage_dist.get("退潮", 0) > 40:
        fals.append("如果退潮板块数继续增加至50+ → 全市场退潮，建议全面减仓")

    # 4. 催化剂证伪
    try:
        from catalyst_calendar import get_upcoming_catalysts
        import datetime
        ref = datetime.date.today()
        cats = get_upcoming_catalysts(ref, days_ahead=7) or []
        high_impact = [c for c in cats if c.get("impact") == "high"]
        for c in high_impact[:2]:
            fals.append(f"关注 {c['date']} {c['name']}：若{'超预期' if 'CPI' in c.get('name','') else '不及预期'}，当前逻辑需要重新定价")
    except Exception:
        pass

    return fals[:6]


# ═══════════════════════════════════════════════════════
#  Q10: 今天最重要的一句话（金句）
# ═══════════════════════════════════════════════════════

def _answer_q10(what_trading, money_pattern, mainline_stages, real_leader, can_buy):
    """从所有分析中提炼一句话金句。"""
    # 基础：今天在交易什么
    if not what_trading or len(what_trading) < 10:
        return "今日市场信号混杂，建议观望。"

    # 提取主线方向
    if mainline_stages:
        top = mainline_stages[0]
        sector = top["sector"]
        stage = top["stage"]

        if stage == "赚钱效应" and "集中攻击" in money_pattern:
            return f"今天不是在炒作概念，而是在重新定价「{sector}」——资金高度集中，共识正在强化。"
        elif stage == "资金流入":
            return f"资金开始向「{sector}」聚拢，共识仍在形成阶段，今天的关键问题是明天能否延续。"
        elif stage == "退潮":
            return f"「{sector}」正在退潮。今天不是进攻的日子，是确认退潮幅度和寻找下一个方向的日子。"
        elif stage == "讨论":
            return f"「{sector}」进入讨论视野，但资金尚未确认。今天在看，明天才能决定。"
        elif "防守" in money_pattern:
            return f"资金从成长轮动到防御。今天交易的是「避险」，不是「机会」。"

    # 降级：用 can_buy 结果
    if can_buy == "NO":
        return "今天市场缺乏确定性机会。不交易本身就是最好的交易。"
    elif can_buy == "CAUTION":
        return "市场有方向但共识不足。可以观察，但还不该出手。"

    return "今日市场有结构性机会，但热点轮动快，需精选个股。"


# ═══════════════════════════════════════════════════════
#  主入口：生产研究备忘录
# ═══════════════════════════════════════════════════════

def produce() -> ResearchMemo:
    """生产一份完整的研究备忘录。"""
    import datetime

    brain, tree, ni = _load_data()

    memo = ResearchMemo()
    # 报告日 = 真实交易日（修复『报告日落后 latest_date』根因 bug）
    memo.trade_date = _report_date()
    memo.generated_at = datetime.datetime.now().isoformat(timespec="seconds")

    # 决策结论
    decision = brain.get("decision", {})
    memo.can_buy = decision.get("can_buy", "UNKNOWN")
    memo.confidence_score = brain.get("confidence", {}).get("overall", 0)

    # ── 第一部分：市场故事 ──
    what_trading, q1_conf = _answer_q1(brain, tree, ni)
    why_moved, drivers = _answer_q3(brain, tree)
    gold_sentence = _answer_q10(what_trading, "", [], "", memo.can_buy)

    memo.part1 = Part1Narrative(
        headline=gold_sentence,
        what_trading=what_trading,
        why_market_moved=why_moved,
        why_detail=drivers,
        confidence=q1_conf,
    )

    # ── 第二部分：资金行为 ──
    migration, from_list, to_list, pattern = _answer_q2(tree)
    biggest_surprise, surprise_detail = _answer_q4(tree)
    chain_text, chain_layers = _answer_q5(tree)

    memo.part2 = Part2MoneyFlow(
        migration=migration,
        from_sectors=from_list,
        to_sectors=to_list,
        pattern=pattern,
        biggest_surprise=biggest_surprise,
        surprise_detail=surprise_detail,
        industry_chain=chain_text,
        chain_layers=chain_layers,
    )

    # ── 第三部分：交易机会 ──
    leader_text, leader_detail, no_real_leader, real_leaders = _answer_q6(tree)
    mainline_stages = _answer_q7(tree)
    tomorrow_watch = _answer_q8(tree, real_leaders, mainline_stages)

    memo.part3 = Part3Trading(
        real_leader=leader_text,
        leader_detail=leader_detail,
        no_real_leader=no_real_leader,
        mainline_stages=[{
            "sector": s["sector"],
            "stage": s["stage"],
            "desc": s["desc"],
            "persistence": s["persistence"],
        } for s in mainline_stages],
        tomorrow_watch=tomorrow_watch,
    )

    # ── 第四部分：风险 ──
    falsification = _answer_q9(brain, tree, mainline_stages)

    # 事件日历
    catalyst_events_list = []
    try:
        from catalyst_calendar import get_upcoming_catalysts
        import datetime
        ref = datetime.date.today()
        cats = get_upcoming_catalysts(ref, days_ahead=7) or []
        for c in cats:
            catalyst_events_list.append({
                "date": str(c.get("date", "")),
                "name": c.get("name", ""),
                "country": c.get("country", ""),
                "impact": c.get("impact", ""),
                "days_until": c.get("days_until", 0),
            })
    except Exception:
        pass

    layers = tree.get("layers", {})
    l7 = layers.get("L7_risk", {}) or {}
    l4_for_risk = layers.get("L4_consensus", {}) or {}
    risk_up_ratio = l7.get("up_ratio", 0)
    risk_up_pct = round(risk_up_ratio * 100) if 0 < risk_up_ratio < 1 else risk_up_ratio
    risk_position = f"综合风险{l7.get('composite','?')}分，建议仓位{l7.get('position','?')}"

    memo.part4 = Part4Risk(
        falsification=falsification,
        catalyst_events=catalyst_events_list,
        biggest_risk=f"全市场退潮板块达{l4_for_risk.get('stage_distribution',{}).get('退潮',0)}个，"
                     f"上涨家数仅{risk_up_pct}%。若明日无主线接力，全面退潮风险加大。",
        risk_position=risk_position,
    )

    # 更新金句（有了完整上下文后）
    memo.part1.headline = _answer_q10(
        what_trading, pattern, mainline_stages,
        leader_text, memo.can_buy
    )

    return memo


# ═══════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    memo = produce()
    print(f"=== 研究备忘录 {memo.trade_date} ===")
    print(f"决策: {memo.can_buy}  置信度: {memo.confidence_score}")
    print()
    print("【第一部分：市场故事】")
    print(f"  金句: {memo.part1.headline}")
    print(f"  交易什么: {memo.part1.what_trading}")
    print(f"  为什么: {memo.part1.why_market_moved}")
    print()
    print("【第二部分：资金行为】")
    print(f"  迁移: {memo.part2.migration}")
    print(f"  模式: {memo.part2.pattern}")
    print(f"  超预期: {memo.part2.biggest_surprise}")
    print(f"  产业链: {memo.part2.industry_chain}")
    print()
    print("【第三部分：交易机会】")
    print(f"  龙头: {memo.part3.real_leader}")
    for s in memo.part3.mainline_stages[:5]:
        print(f"    {s['sector']}: {s['stage']}({s['desc']}) {s['persistence']}")
    print("  明天观察:")
    for w in memo.part3.tomorrow_watch:
        print(f"    - {w}")
    print()
    print("【第四部分：风险】")
    print(f"  最大风险: {memo.part4.biggest_risk}")
    print(f"  仓位: {memo.part4.risk_position}")
    for f in memo.part4.falsification:
        print(f"  - {f}")
