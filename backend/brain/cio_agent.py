# -*- coding: utf-8 -*-
"""
cio_agent.py —— 首席投资官 Agent（Chief Investment Officer）
=============================================================
整个系统的最终决策者。不计算任何指标，只做三件事：

1. 阅读前面八个 Agent + 研究员 Agent 的结论
2. 检查跨层矛盾（\"AI主线\"推荐\"纺织龙头\"→ 报警）
3. 输出《投资决策备忘录》13段 Trading OS 结构

设计原则：
  - 规则驱动（非 LLM）：每一段都有明确的数据→结论映射
  - 证据链必附：观点 + 证据 + 置信度标注
  - 全球→A股必关联：不孤立看任何一个市场
  - 条件前置：交易永远是\"如果X，则Y\"，不是预测
  - 历史映照：查询相似行情历史胜率

十三段结构（Trading OS）：
  ① 安检清单（Pre-flight Checklist）—— 6项二值判定
  ② 核心观点（Investment Thesis）
  ③ 证据链（Evidence Chain）
  ④ 资金地图（Money Map）
  ⑤ 赔率表（Odds Table）—— 按赔率排序
  ⑥ 投资主线（Main Lines）—— 含why/risk bullets
  ⑦ 机会成本（Opportunity Cost）
  ⑧ 市场结构（Market Structure）
  ⑨ 交易计划（Trading Plan）
  ⑩ 风险与反例（Risk & Counter）
  ⑪ 催化剂日历（Catalyst Calendar）—— 未来一周关键事件
  ⑫ 行动清单（Action List）—— 明日时间戳
  ⑬ 历史经验（Historical Context）

输入：brain_report.json + decision_tree.json + researcher memo
输出：InvestmentDecisionMemo dataclass
"""
from __future__ import annotations
import os
import json
import sys
import datetime
import re
from dataclasses import dataclass, field
from typing import Optional

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUTPUT = os.path.join(ROOT, "output")

# 资金迁移引擎（Capital Migration Engine）：回答「钱有没有/去哪/我怎么办」
from capital_migration import build as _build_capital_migration
# 因果推理引擎（Causal Reasoning）：为什么 / 炒的是哪条产业链
from causal_reasoning import build as _causal_build
# 情景推演引擎（Scenario Engine）：明日最大摆动变量 → 条件分支
from scenario_engine import build as _build_scenario
# 学习复盘中心（Learning & Review Center）：预测日志 + T+1 回放 + 模式成败率
from learning_center import build as _build_learning, log_prediction as _log_prediction
# 投资委员会（真实 IC 辩论）：L1~L8 支持/反对 + 原因 + 加权投票
from committee.investment_committee import decide as _ic_decide
# ── 取精华：移植自 AI-Portfolio-Compass（MIT License）──
# 持仓分层引擎（classifier.py，纯规则零LLM）
from position_layer import build as _build_position_layer
# 交易复盘纪律引擎（trade_review.py，规则化事实标签）
from trade_review import build as _build_trade_review
# 数据新鲜度矩阵（freshness.py，全数据源时效评估，升级 date_guard）
from data_freshness import build as _build_freshness
# 今日行动清单卡（DecisionCard 聚合，零LLM）
from action_cards import build as _build_action_cards
from decision_tree import report_date as _report_date


def _pct(v):
    """格式化涨跌比（自动检测0-1小数 vs 0-100百分数）。"""
    if v is None:
        return "?"
    if 0 < v < 1:
        return f"{v*100:.0f}"
    return f"{v:.0f}"


# ═══════════════════════════════════════════════════════
#  InvestmentDecisionMemo 数据结构
# ═══════════════════════════════════════════════════════

@dataclass
class ThesisBlock:
    """① 核心观点"""
    headline: str = ""                     # 投资主张：一句话
    explanation: str = ""                  # 展开说明（2-3句）
    conviction: str = ""                   # 确信度：高/中/低
    global_a_share_link: str = ""          # 全球→A股传导逻辑


@dataclass
class EvidenceBlock:
    """② 证据链"""
    claims: list = field(default_factory=list)  # [{claim, evidence, data_points, type: 数据支持/推测}]
    uncertainty: list = field(default_factory=list)  # 仍不确定的地方
    cross_layer_conflicts: list = field(default_factory=list)  # 跨层矛盾


@dataclass
class MoneyMapBlock:
    """③ 资金地图"""
    migration_narrative: str = ""          # 资金迁移叙事
    from_sectors: list = field(default_factory=list)
    to_sectors: list = field(default_factory=list)
    pattern: str = ""
    pattern_explanation: str = ""          # 为什么是这种模式
    time_dimension: list = field(default_factory=list)  # [{sector, trend_5d, trend_20d}]
    inflection_signals: list = field(default_factory=list)  # 拐点信号


@dataclass
class MainLine:
    """单条投资主线"""
    sector: str = ""
    stage: str = ""                        # 启动/发酵/高潮/退潮
    persistence: str = ""
    star_rating: int = 0                   # 1-5星
    sort_score: float = 0.0                # 排序分（资金持续性>事件驱动）
    net_today: float = 0
    net_5d: float = 0
    trend_5d: str = ""                     # 连续流入/流出/震荡
    trend_20d: str = ""                    # 首次进入前三/持续在榜/新进
    inflection: bool = False               # 是否拐点
    chain_position: str = ""               # 在产业链中的位置
    has_leader: bool = False               # 是否有龙头共振
    why_bullets: list = field(default_factory=list)    # ✓ 为什么看好（每条一个bullet）
    risk_bullets: list = field(default_factory=list)   # ⚠ 风险（每条一个）
    success_prob: float = 0.0              # 成功概率（0-100）
    upside_pct: float = 0.0                # 上涨空间%
    downside_pct: float = 0.0              # 下跌风险%
    odds_ratio: float = 0.0                # 赔率 = upside/downside
    is_event_driven: bool = False          # 是否事件驱动（事件驱动排序降级）


@dataclass
class TradingPlanBlock:
    """⑤ 交易计划"""
    opportunities: list = field(default_factory=list)  # [{tier, name, conditions, give_up, rationale}]
    no_opportunity: bool = False
    no_opportunity_reason: str = ""


@dataclass
class RiskBlock:
    """⑥ 风险与反例"""
    falsification: list = field(default_factory=list)  # [{scenario, if_condition, then_conclusion}]
    upcoming_events: list = field(default_factory=list)
    biggest_risk: str = ""


@dataclass
class HistoricalBlock:
    """⑦ 历史经验"""
    has_data: bool = False
    similar_period_desc: str = ""          # 相似行情描述
    win_rate: Optional[float] = None       # 胜率
    avg_return: Optional[float] = None     # 平均收益
    sample_count: int = 0                  # 样本数
    conclusion: str = ""                   # 一句话结论
    backtest_available: bool = False       # 回测数据是否可获取


@dataclass
class CrossAssetBlock:
    """跨资产资金情报（黄金 / 大宗商品 / ETF / 沪深港通）

    数据源：output/gold_report.json + output/flow_report.json
    （Gold Decision Engine + Capital Flow Engine 的产出）。
    这是用户最想看到、但过去只在 HTML 资金情报中心里、推送备忘录里完全没有的板块。
    """
    has_data: bool = False
    gold_price: float = 0.0
    gold_change_pct: float = 0.0
    gold_signal: str = ""                  # 黄金驱动叙事（一句话）
    commodities: list = field(default_factory=list)   # [{name_cn, change_pct, a_share_link}]
    etf_top_inflow: list = field(default_factory=list)   # [{name, shares_change_pct, amount_yi}]
    etf_top_outflow: list = field(default_factory=list)
    north_net: float = 0.0                 # 北向净买入（亿）
    south_net: float = 0.0                 # 南向净买入（亿）
    flow_score_overall: int = 0
    flow_one_liner: str = ""


@dataclass
class ObservationBlock:
    """关系/规律引擎产出（Relationship & Observation Engine）。

    回答"今天市场教会了我们什么新规律 / 哪些跨资产关系正在增强或失效"。
    这是用户要求的研究框架核心模块之一，置于备忘录最顶端（第一页头条）。
    """
    has_data: bool = False
    headline: str = ""                      # 今日最重要的新发现
    discoveries: list = field(default_factory=list)  # [{type,label,regime,corr,confidence,note}]


@dataclass
class CROBlock:
    """CRO（首席研究官）总裁定词 —— 编排各引擎，每日三问。

    数据来源：output/cro_report.json（cro_agent.py 产出）。
    位置：备忘录置于最顶端，是整份报告的"总纲/头条"。
    """
    has_data: bool = False
    verdict: str = ""                        # 总裁定性：偏进攻/结构市/偏防守
    score: float = 0.0                       # 合成风险偏好分 0-100
    confidence: float = 0.0                  # 裁定置信度
    q1_headline: str = ""                    # Q1 今天交易什么
    q1_sectors: list = field(default_factory=list)   # [{name,net,chg,leader}]
    q2_headline: str = ""                    # Q2 最大边际变化
    q2_bullets: list = field(default_factory=list)
    q3_headline: str = ""                    # Q3 市场教会我们什么
    q3_bullets: list = field(default_factory=list)


@dataclass
class GlobalMarketBlock:
    """全球市场固定看板（问题三）。

    用户要求每天固定盯：纳指/SOXX/韩国KOSPI/台湾加权/恒生科技/美元/美债2Y/美债10Y/
    TIPS/黄金/铜/原油/BTC。已接入的真实指数填日涨跌+强度星；被沙箱数据墙挡住的
    明确标"未接入"，绝不编造数字。
    """
    has_data: bool = False
    board: list = field(default_factory=list)   # [{name, importance, change_pct, star, status, note}]
    one_liner: str = ""


@dataclass
class CapitalFlowBlock:
    """资金迁移（问题一）：流不是价。

    ETF净申购/赎回（份额变化，真实）、南向/北向（真实）、商品方向（真实）
    → 迁移表(资金/去向/强度★) + AI一句话。这是用户最想看的"钱到底去哪了"。
    """
    has_data: bool = False
    etf_total_net_yi: float = 0.0       # ETF整体净申购(亿)，负=净赎回
    south_net_yi: float = 0.0
    north_net_yi: float = 0.0
    etf_top_inflow: list = field(default_factory=list)   # [{name, shares_change_pct, amount_yi}]
    etf_top_outflow: list = field(default_factory=list)
    migration: list = field(default_factory=list)  # [{source, target, star, note}]
    one_liner: str = ""


@dataclass
class MarketMovieBlock:
    """市场电影（用户缺失模块）：基于可得数据重构的今日叙事时间线。

    明确标注"非分钟级实时行情"——本系统只抓日级数据，分钟级事件需另接 tick 源。
    """
    has_data: bool = False
    disclaimer: str = "基于日级数据重构，非分钟级实时行情"
    scenes: list = field(default_factory=list)  # [{time, event, implication}]
    summary: str = ""


@dataclass
class NarrativeBlock:
    """Narrative Engine —— 「为什么」块（用户审计问题二）。

    对今日资金净流入 Top 板块给出可解释因果链：
        宏观/全球驱动 → 产业逻辑（产业链位置） → 实时催化（真实新闻） → 结论。
    诚实优先：新闻做情绪判定，资金与新闻背离时明确标注；新闻拉不到时 has_news=False。
    """
    has_data: bool = False
    has_news: bool = False                 # 是否成功接入实时新闻
    news_count: int = 0
    headline: str = ""                     # 今日最强资金主线
    narratives: list = field(default_factory=list)  # [{board,net_now,chg_pct,leader,theme,
                                                    #   chain_logic,global_note,catalysts,verdict,
                                                    #   divergence,confidence,one_liner}]
    disclaimer: str = "板块资金为上一交易日收盘；实时新闻为当日盘中，二者日期可能不同"


@dataclass
class PanQianBlock:
    """盘前纪要（公众号「盘前纪要」）—— 叙事/催化/情绪层补充输入。

    数据源：output/panqian_YYYYMMDD.json（panqian_parser.py 产出）。
    回答"盘前市场在聊什么 / 哪些题材有事件催化 / 连板高度与情绪热度 / 哪里有雷"。
    与系统量化层互补（我们的量化强、叙事弱），不替代任何引擎。
    合规：个人研究用途，内容源自公众号，切勿再分发。
    """
    has_data: bool = False
    article_date: str = ""
    source_url: str = ""
    headline: str = ""                     # 自动摘要：热点N/连板最高M板/地雷K条…
    sections: dict = field(default_factory=dict)   # {key: {title, raw, items}}
    section_order: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    risk_flags: list = field(default_factory=list)  # 地雷阵：减持/风险/利空/解禁


@dataclass
class IndustryChainBlock:
    """L3.5 产业链推理 —— Serenity 式「供应链瓶颈」研究（确定性，无 LLM）。

    数据源：output/industry_chain_report.json（industry_chain_agent 产出）。
    回答"热点板块里，谁是真正的瓶颈环节 / 哪些个股最靠近瓶颈（候选）/
    哪些只是盘前热榜蹭热点（降级）"。这是研究层，不是决策层；
    候选的'客户认证/产能'等若缺数据源显式标 data_gap，绝不编造。
    """
    has_data: bool = False
    stage: str = ""
    narrative: str = ""
    bottlenecks: list = field(default_factory=list)   # [{sector, segment, score, fund_validated, candidates, reason}]
    candidates: list = field(default_factory=list)    # [{name, bottlenecks, evidence}]
    downgraded: list = field(default_factory=list)     # [{stock, reason}]
    gaps: list = field(default_factory=list)


@dataclass
class InvestmentDecisionMemo:
    """完整的投资决策备忘录"""
    trade_date: str = ""
    generated_at: str = ""
    can_buy: str = ""                      # YES/NO/CAUTION (来自投资委员会 IC，权威决策)
    position_pct: str = ""                 # 仓位护栏（来自 IC）
    confidence_overall: int = 0
    confidence_bars: dict = field(default_factory=dict)  # 改为定性：{layer: {direction, reason, risk}}
    committee: dict = field(default_factory=dict)  # 投资委员会（IC）结论：can_buy/方向/仓位/主要逻辑/风险摘要/评分板

    thesis: ThesisBlock = field(default_factory=ThesisBlock)
    evidence: EvidenceBlock = field(default_factory=EvidenceBlock)
    money_map: MoneyMapBlock = field(default_factory=MoneyMapBlock)
    main_lines: list = field(default_factory=list)  # [MainLine, ...]
    trading_plan: TradingPlanBlock = field(default_factory=TradingPlanBlock)
    risk: RiskBlock = field(default_factory=RiskBlock)
    historical: HistoricalBlock = field(default_factory=HistoricalBlock)

    # ── Trading OS 新增模块 ──
    preflight: dict = field(default_factory=dict)          # 安检清单报告
    data_health: dict = field(default_factory=dict)        # 数据健康体检（Data Integrity Layer 闸门）
    market_structure: dict = field(default_factory=dict)   # 市场结构（谁在赚钱）
    opportunity_cost: dict = field(default_factory=dict)   # 机会成本分析
    action_list: list = field(default_factory=list)        # 明日行动清单
    odds_table: list = field(default_factory=list)         # 赔率表
    catalyst_calendar: dict = field(default_factory=dict)  # 催化剂日历（未来一周事件）
    cross_asset: "CrossAssetBlock" = field(default_factory=CrossAssetBlock)  # 跨资产资金：黄金/大宗商品/ETF/沪深港通
    observation: "ObservationBlock" = field(default_factory=ObservationBlock)  # 关系/规律：今日新发现
    cro: "CROBlock" = field(default_factory=CROBlock)  # CRO 总裁定词（最顶端总纲）
    # ── 审计升级新增（用户买方晨会标准）──
    global_market: "GlobalMarketBlock" = field(default_factory=GlobalMarketBlock)  # 全球市场固定看板（问题三）
    capital_flow: "CapitalFlowBlock" = field(default_factory=CapitalFlowBlock)      # 资金迁移：流不是价（问题一）
    market_movie: "MarketMovieBlock" = field(default_factory=MarketMovieBlock)      # 市场电影：今日叙事时间线（缺失模块）
    narrative: "NarrativeBlock" = field(default_factory=NarrativeBlock)             # 「为什么」引擎：板块因果链（问题二）
    panqian: "PanQianBlock" = field(default_factory=PanQianBlock)                    # 盘前纪要：叙事/催化/情绪补充输入
    industry_chain: "IndustryChainBlock" = field(default_factory=IndustryChainBlock)  # L3.5 产业链推理（研究层，非决策层）

    # ── 范式转移：资金迁移块（日报第一页：一句话结论+迁移图+反证+我怎么办）──
    migration: dict = field(default_factory=dict)  # capital_migration.build() 输出
    # ── 范式转移：因果推理块（为什么 / 炒的是哪条产业链）──
    causal: dict = field(default_factory=dict)  # causal_reasoning.build() 输出
    # ── 范式转移：真实 IC 辩论块（L1~L8 支持/反对 + 原因 + 加权投票）──
    debate: dict = field(default_factory=dict)  # investment_committee.decide() 的 debate/weighted_vote/verdict
    # ── 范式转移：情景推演块（明日最大摆动变量 → 条件分支 → 赢家/输家）──
    scenario: dict = field(default_factory=dict)  # scenario_engine.build() 输出
    # ── 范式转移：学习复盘块（预测日志 + T+1 回放 + 模式成败率）──
    learning: dict = field(default_factory=dict)  # learning_center.build() 输出
    # ── 取精华：移植自 AI-Portfolio-Compass（MIT License）──
    position_layer: dict = field(default_factory=dict)  # position_layer.build() 持仓分层
    trade_review: dict = field(default_factory=dict)    # trade_review.build() 交易复盘纪律
    freshness: dict = field(default_factory=dict)       # data_freshness.build() 数据新鲜度矩阵
    action_cards: dict = field(default_factory=dict)    # action_cards.build() 今日行动清单卡(DecisionCard)
    journal_logged: int = 0                    # Phase 2：当日自动写入 trade_journal 的 signal 条数


# ═══════════════════════════════════════════════════════
#  产业链星级映射（板块→产业链→层级星级）
# ═══════════════════════════════════════════════════════

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
    """匹配板块到产业链。"""
    for key, chain in CHAIN_DETAIL.items():
        if key in sector_name:
            return chain
    return None


def _rating_stars(n: int) -> str:
    """数字星级→符号。"""
    return "★" * n + "☆" * (5 - n)


# ═══════════════════════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════════════════════

def _load_data():
    """加载所有数据源。"""
    brain = {}
    tree = {}

    bp = os.path.join(OUTPUT, "brain_report.json")
    if os.path.exists(bp):
        with open(bp, "r", encoding="utf-8") as f:
            brain = json.load(f)

    tp = os.path.join(OUTPUT, "decision_tree.json")
    if os.path.exists(tp):
        with open(tp, "r", encoding="utf-8") as f:
            tree = json.load(f)

    return brain, tree


# ═══════════════════════════════════════════════════════
#  ① 核心观点（Investment Thesis）
# ═══════════════════════════════════════════════════════

def _build_thesis(brain, tree) -> ThesisBlock:
    """合成唯一投资主张。"""
    l0 = brain.get("L0", {})
    gn = l0.get("global_narrative", {})
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:3]
    l3 = layers.get("L3_industry", {}) or {}
    l1 = layers.get("L1_global_macro", {}) or {}
    sentiment = layers.get("sentiment", {}) or {}

    decision = brain.get("decision", {})
    can_buy = decision.get("can_buy", "UNKNOWN")

    # ── 提炼核心叙事 ──
    global_narrative = gn.get("narrative_name", "")
    a_story = gn.get("a_story", "")
    true_driver = gn.get("true_driver", "")

    main_names = [m.get("sector", "") for m in mains if m.get("sector")]
    stage_dist = l4.get("stage_distribution", {})
    n_retreat = stage_dist.get("退潮", 0)

    # 市场状态判断
    up_ratio = sentiment.get("up_ratio", 50)
    up_pct = round(up_ratio * 100) if up_ratio < 1 else up_ratio  # 0-1小数→百分数
    if up_ratio > 0.6 and n_retreat < 20:
        market_state = "偏强"
    elif up_ratio < 0.4 or n_retreat > 40:
        market_state = "偏弱"
    else:
        market_state = "震荡分化"

    # ── 构建核心观点 ──
    # 获取安检清单的失败条件摘要
    failed_conditions = ""
    try:
        from brain.trading_rules import run_preflight
        pf = run_preflight(tree, ic_signal=_ic_calibration_signal())
        if pf.failed_summary:
            failed_items = [f"{f['condition']}: {f['reason'][:40]}" for f in pf.failed_summary[:4]]
            failed_conditions = "；".join(failed_items)
    except Exception:
        pass

    if main_names and can_buy == "YES":
        top = mains[0]
        top_stage = top.get("stage", "")
        headline = (
            f"今日核心观点：市场交易的是「{main_names[0]}」主导的结构性行情"
            f"——{a_story or '资金与产业形成共振'}。"
            f"当前处于「{top_stage}」阶段，继续以{main_names[0]}为主线。"
        )
        conviction = "中-高"

    elif main_names and can_buy == "CAUTION":
        top = mains[0]
        top_stage = top.get("stage", "")
        headline = (
            f"今日核心观点：市场整体进入高风险轮动环境，"
            f"「{main_names[0]}」是唯一仍保持资金持续流入的方向，"
            f"但尚未形成足够强的板块共振（{n_retreat}个板块退潮）。"
            f"因此继续以观察为主，不建议追高。"
        )
        conviction = "中"

    elif main_names and can_buy == "NO":
        top = mains[0]
        headline = (
            f"今日核心观点：不交易。"
            f"{main_names[0]}虽获资金关注，但全市场{n_retreat}个板块退潮（上涨仅{up_pct}%）。"
            f"安检清单仅通过部分条件。防守优于进攻，等待条件满足。"
        )
        conviction = "高"
        if failed_conditions:
            headline += f"\n失败项：{failed_conditions}"

    elif can_buy == "NO":
        headline = (
            f"今日核心观点：不交易。"
            f"{n_retreat}个板块退潮，上涨家数仅{_pct(up_ratio)}%。"
            f"不交易本身就是最好的交易。"
        )
        conviction = "高"
        if failed_conditions:
            headline += f"\n失败项：{failed_conditions}"

    else:
        headline = f"今日核心观点：市场{market_state}，热点分散，缺乏持续共识。观望为主。"
        conviction = "低"

    # ── 全球→A股关联 ──
    global_a_share_link = ""
    if global_narrative and main_names:
        # 判断A股是跟随还是独立
        l1_dir = (l1.get("read", "") or "").lower()
        us_down = "下跌" in l1_dir or "bear" in l1_dir or "回调" in l1_dir
        a_story_lower = a_story.lower() if a_story else ""
        independent = "国产" in a_story_lower or "自主" in a_story_lower

        if us_down and independent:
            global_a_share_link = (
                f"海外：纳指承压（{l1.get('read','')[:60]}），"
                f"但A股半导体/科技出现相对独立走势——"
                f"资金交易的不是「全球AI」，而是「国产替代」。"
                f"这是关键的Narrative分歧，需持续观察。"
            )
        elif us_down:
            global_a_share_link = (
                f"海外：纳指承压，A股同样受拖累。"
                f"全球风险偏好下降，A股科技板块难以独立走强。"
            )
        else:
            global_a_share_link = (
                f"全球：交易「{global_narrative}」（{true_driver or '数据待确认'}），"
                f"A股{'同步跟随' if not independent else '呈现独立分化'}。"
            )

    # ── 展开说明 ──
    top3_names = [m.get("sector", "") for m in mains[:3]]
    explanation = (
        f"市场状态：{market_state}（上涨{_pct(up_ratio)}%/{n_retreat}板块退潮）。"
        f"主线方向：{' > '.join(top3_names) if top3_names else '无'}"
        f"{'，成交额维持第一梯队' if top3_names else ''}。"
    )
    if global_a_share_link:
        explanation += f"\n全球关联：{global_a_share_link}"

    return ThesisBlock(
        headline=headline,
        explanation=explanation,
        conviction=conviction,
        global_a_share_link=global_a_share_link,
    )


# ═══════════════════════════════════════════════════════
#  ② 证据链（Evidence Chain）
# ═══════════════════════════════════════════════════════

def _build_evidence(brain, tree) -> EvidenceBlock:
    """为每个观点附上证据。"""
    layers = tree.get("layers", {})
    l1 = layers.get("L1_global_macro", {}) or {}
    l2 = layers.get("L2_china_macro", {}) or {}
    l3 = layers.get("L3_industry", {}) or {}
    l4 = layers.get("L4_consensus", {}) or {}
    sentiment = layers.get("sentiment", {}) or {}
    l0 = brain.get("L0", {})

    claims = []
    uncertainty = []

    mains = l4.get("main_lines", [])[:5]
    stage_dist = l4.get("stage_distribution", {})
    n_retreat = stage_dist.get("退潮", 0)
    up_ratio = sentiment.get("up_ratio", 0)

    # Claim 1: 主线判断
    top = mains[0] if mains else None
    if top:
        top_sector = top.get("sector", "")
        top_net = top.get("net_now", 0)
        top_net_5d = top.get("net_5d", 0)
        claims.append({
            "claim": f"「{top_sector}」是今日主线板块",
            "evidence": (
                f"净流入{top_net:.1f}亿，5日累计{top_net_5d:.0f}亿，"
                f"涨幅{top.get('chg_pct',0):+.2f}%"
            ),
            "data_points": f"资金排名第1，5日趋势{'持续流入' if top_net_5d > 0 else '回流'}",
            "type": "数据支持",
        })
        # 退潮
        if n_retreat > 30:
            claims.append({
                "claim": "市场处于高风险轮动环境",
                "evidence": f"{n_retreat}个板块处于退潮阶段，上涨家数仅{_pct(up_ratio)}%",
                "data_points": f"退潮板块数={n_retreat}，涨跌比={_pct(up_ratio)}%",
                "type": "数据支持",
            })
            uncertainty.append(
                f"主线板块持续流入但退潮板块过多——"
                f"这是「结构性行情」还是「存量抱团」？需要明天确认"
            )
    else:
        claims.append({
            "claim": "今日无主线板块",
            "evidence": "没有板块同时满足净流入>0、涨幅>1%的条件",
            "data_points": "",
            "type": "数据支持",
        })

    # Claim 2: 全球→A股关联
    gn = l0.get("global_narrative", {})
    if gn.get("narrative_name"):
        truth_driver = gn.get("true_driver") or ""
        claims.append({
            "claim": f"全球交易「{gn['narrative_name']}」",
            "evidence": truth_driver[:100] if truth_driver else "跨资产信号不够一致，暂未形成明确全球叙事",
            "data_points": f"置信度{(gn.get('match_score',0) or 0)*100:.0f}%",
            "type": "部分支持" if (gn.get('match_score',0) or 0) < 0.7 else "数据支持",
        })

    # Claim 3: 产业趋势
    l3_read = l3.get("read", "")
    if l3_read:
        claims.append({
            "claim": "AI仍是中长期产业主线",
            "evidence": l3_read[:100],
            "data_points": "",
            "type": "推测",
        })

    # ── 跨层矛盾检测 ──
    conflicts = _detect_cross_layer_conflicts(brain, tree)
    if conflicts:
        uncertainty.extend(conflicts)

    return EvidenceBlock(
        claims=claims,
        uncertainty=uncertainty,
        cross_layer_conflicts=[c for c in conflicts if "冲突" in c],
    )


def _detect_cross_layer_conflicts(brain, tree):
    """检测跨层矛盾。"""
    conflicts = []
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    l5 = layers.get("L5_leader", {}) or {}
    l7 = layers.get("L7_risk", {}) or {}

    mains = l4.get("main_lines", [])[:3]
    main_sectors = [m.get("sector", "") for m in mains]
    leaders = l5.get("leaders", {})

    decision = brain.get("decision", {})
    can_buy = decision.get("can_buy", "")
    risk_composite = l7.get("composite", 0)

    # 检测1: 高风险但建议买入
    if can_buy in ("YES",) and risk_composite > 70:
        conflicts.append(
            f"⚠️ 矛盾：L7风险评分{risk_composite}（高风险），但决策建议{can_buy}——"
            f"请人工复核仓位是否合理"
        )

    # 检测2: 龙头不在主线板块内
    if leaders and main_sectors:
        for sec, ld in leaders.items():
            if "error" in ld:
                continue
            # 检查sec是否在主线板块内
            in_main = any(ms in sec for ms in main_sectors)
            if not in_main:
                names = []
                for k in ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"]:
                    n = (ld.get(k, {}) or {}).get("name", "")
                    if n:
                        names.append(f"{k.split('龙头')[0]}:{n}")
                if names:
                    conflicts.append(
                        f"⚠️ 矛盾：龙头分析锁定「{sec}」（{'、'.join(names[:2])}），"
                        f"但L4共识主线是{'、'.join(main_sectors[:2])}——"
                        f"龙头不在主线内，逻辑断裂。建议仅从主线板块成分股中选龙头。"
                    )

    # 检测3: 低风险但建议不买
    if can_buy == "NO" and risk_composite < 40:
        conflicts.append(
            f"⚠️ 矛盾：L7风险评分{risk_composite}（低风险），但决策建议NO——"
            f"需确认是因为主线缺失还是其他原因"
        )

    return conflicts


# ═══════════════════════════════════════════════════════
#  ③ 资金地图（Money Map）
# ═══════════════════════════════════════════════════════

def _build_money_map(tree) -> MoneyMapBlock:
    """构建资金地图，含时间维度。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])
    early = l4.get("early_watch", [])

    sorted_sectors = sorted(mains, key=lambda x: x.get("net_now", 0), reverse=True)
    top_inflow = [s for s in sorted_sectors[:5] if s.get("net_now", 0) > 0]
    top_outflow = [s for s in sorted_sectors[-5:] if s.get("net_now", 0) < -0.1]
    top_outflow.reverse()

    # 资金模式判断
    if len(top_inflow) <= 2 and top_inflow:
        pattern = "集中攻击"
        explanation = f"资金高度集中在{len(top_inflow)}个板块，其余板块资金分散——这是主线确立的信号，不是轮动"
    elif len(top_inflow) >= 5:
        pattern = "分散轮动"
        explanation = f"资金在{len(top_inflow)}个方向试探，无明显主线——这是存量博弈的特征，不是进攻信号"
    elif top_outflow:
        defensive = ["银行", "煤炭", "电力", "钢铁", "石油", "公用事业"]
        out_def = [s for s in top_outflow if any(d in s.get("sector", "") for d in defensive)]
        if len(out_def) >= 2:
            pattern = "防守→进攻切换"
            explanation = "红利/防御板块资金流出，转向成长——这是风险偏好提升的信号，值得关注持续性"
        else:
            pattern = "存量轮动"
            explanation = "资金在板块间切换，但总量未见放大——观望信号"
    else:
        pattern = "存量博弈"
        explanation = "资金小幅轮动，无明确方向——场外观望"

    # 迁移叙事
    if top_inflow and top_outflow:
        in_names = [s["sector"] for s in top_inflow[:3]]
        out_names = [s["sector"] for s in top_outflow[:3]]
        in_total = sum(s.get("net_now", 0) for s in top_inflow)
        out_total = abs(sum(s.get("net_now", 0) for s in top_outflow))
        narrative = (
            f"资金从{'、'.join(out_names)}（流出{out_total:.0f}亿）"
            f" → {'、'.join(in_names)}（流入{in_total:.0f}亿）"
        )
    elif top_inflow:
        in_names = [s["sector"] for s in top_inflow[:3]]
        in_total = sum(s.get("net_now", 0) for s in top_inflow)
        narrative = f"资金集中流入{'、'.join(in_names)}（共{in_total:.0f}亿），存量博弈特征明显"
    else:
        narrative = "全市场资金净流出，无明显流入方向"

    # 时间维度（5日/20日趋势）
    time_dimension = []
    inflection_signals = []
    for m in mains[:8]:
        sector = m.get("sector", "")
        net_now = m.get("net_now", 0)
        net_5d = m.get("net_5d", 0)
        net_20d = m.get("net_20d", None)

        # 5日趋势
        if net_5d > 20:
            trend_5d = "连续大幅流入"
        elif net_5d > 0:
            trend_5d = "小幅净流入"
        elif net_5d > -10:
            trend_5d = "小幅净流出"
        else:
            trend_5d = "连续流出"

        # 20日趋势（从mains列表推断——如果在top3且之前不在，是拐点）
        trend_20d = "持续活跃" if net_now > 0 else "走弱"
        inflection = False
        # 检测拐点：5日累计转正但今日净流入很小→可能到位
        if net_5d > 20 and net_now < 2:
            inflection_signals.append(f"「{sector}」5日累计{net_5d:.0f}亿但今日仅{net_now:.1f}亿——可能是增量资金衰减信号")
            inflection = True
        # 检测拐点：5日累计为负但今日大幅流入→可能反转
        if net_5d < -10 and net_now > 5:
            inflection_signals.append(f"「{sector}」5日累计{net_5d:.0f}亿但今日大幅流入{net_now:.0f}亿——可能拐点")
            inflection = True

        time_dimension.append({
            "sector": sector,
            "net_today": net_now,
            "net_5d": net_5d,
            "trend_5d": trend_5d,
            "trend_20d": trend_20d,
            "inflection": inflection,
        })

    from_list = [{"name": s["sector"], "net": s.get("net_now", 0), "chg": s.get("chg_pct", 0)}
                 for s in top_outflow[:4]] if top_outflow else []
    to_list = [{"name": s["sector"], "net": s.get("net_now", 0), "chg": s.get("chg_pct", 0),
                "stage": s.get("stage", "")}
               for s in top_inflow[:4]] if top_inflow else []

    return MoneyMapBlock(
        migration_narrative=narrative,
        from_sectors=from_list,
        to_sectors=to_list,
        pattern=pattern,
        pattern_explanation=explanation,
        time_dimension=time_dimension,
        inflection_signals=inflection_signals,
    )


# ═══════════════════════════════════════════════════════
#  ④ 投资主线（Main Lines）—— 星级产业链
# ═══════════════════════════════════════════════════════

def _build_main_lines(tree, brain) -> list:
    """构建投资主线，含星级评分、赔率、why/risk bullets。
    
    排序逻辑重写（用户要求）：资金持续性 > 事件驱动。
    排序分 = (5日趋势分 × 2) + 阶段分 + 龙头分 - 事件驱动惩罚。
    """
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:8]
    l5 = layers.get("L5_leader", {}) or {}
    leaders = l5.get("leaders", {})

    result = []
    for m in mains:
        sector = m.get("sector", "")
        stage = m.get("stage", "")
        net_now = m.get("net_now", 0)
        net_5d = m.get("net_5d", 0)
        chg = m.get("chg_pct", 0)

        # ── 星级评分 ──
        stars = 0
        if net_now > 0:
            stars += 1
        if net_5d > 10:
            stars += 1
        if stage in ("赚钱效应", "一致性"):
            stars += 2
        elif stage == "资金流入":
            stars += 1
        if stage == "退潮":
            stars = max(0, stars - 2)
        if abs(chg) >= 2:
            stars = min(5, stars + 1)
        stars = max(0, min(5, stars))

        # ── 持续性 ──
        if net_now > 0 and net_5d > 0:
            persistence = "持续流入"
        elif net_now > 0 and net_5d < 0:
            persistence = "今日回流（5日仍流出）"
        elif net_now < 0 and net_5d < 0:
            persistence = "持续流出"
        else:
            persistence = "今日流出（5日仍流入）"

        # ── 趋势 ──
        if net_5d > 20:
            trend_5d = "连续大幅流入"
        elif net_5d > 0:
            trend_5d = "小幅净流入"
        elif net_5d > -10:
            trend_5d = "小幅净流出"
        else:
            trend_5d = "连续流出"
        trend_20d = "持续在榜"

        # ── 产业链 ──
        chain = _match_chain(sector)
        chain_position = ""
        if chain:
            chain_layers = chain["layers"]
            for i, layer in enumerate(chain_layers):
                keywords = layer.replace(" ", "").split("/")
                if any(kw and kw in sector for kw in keywords):
                    chain_position = f"{chain['name']} → {layer}"
                    break
            if not chain_position:
                chain_position = chain["name"]

        # ── 龙头共振 ──
        has_leader_resonance = False
        leader_name = ""
        if leaders:
            for sec, ld in leaders.items():
                if sector in sec or sec in sector:
                    ca = (ld.get("产业龙头", {}) or {}).get("name", "")
                    fund = (ld.get("资金龙头", {}) or {}).get("name", "")
                    tech = (ld.get("技术龙头", {}) or {}).get("name", "")
                    sent = (ld.get("情绪龙头", {}) or {}).get("name", "")
                    names = [n for n in [ca, fund, tech, sent] if n and not n.startswith("ST")]
                    from collections import Counter
                    top_name, top_count = Counter(names).most_common(1)[0] if names else ("", 0)
                    if top_count >= 3:
                        has_leader_resonance = True
                        leader_name = top_name
                    break

        # ── 判断事件驱动 ──
        is_event_driven = False
        event_keywords = ["油气", "石油", "煤炭", "电力", "农业", "黄金", "军工", "房地产"]
        if any(kw in sector for kw in event_keywords) and net_5d <= 0 and net_now > 0:
            is_event_driven = True  # 今日涨但5日流出 → 事件驱动

        # ── 排序分（新逻辑：资金持续性权重×2）──
        sort_score = 0.0
        # 5日趋势分（×2）
        if net_5d > 20:
            sort_score += 4.0
        elif net_5d > 0:
            sort_score += 2.0
        elif net_5d > -5:
            sort_score += 1.0
        # 阶段分
        if stage in ("赚钱效应", "一致性"):
            sort_score += 3.0
        elif stage == "资金流入":
            sort_score += 2.0
        elif stage == "退潮":
            sort_score -= 2.0
        # 龙头分
        if has_leader_resonance:
            sort_score += 2.0
        # 事件驱动惩罚
        if is_event_driven:
            sort_score -= 2.0
        # 退潮大环境惩罚
        stage_dist = l4.get("stage_distribution", {})
        n_retreat = stage_dist.get("退潮", 0)
        if n_retreat > 40:
            sort_score -= 1.0

        # ── Why bullets（自动生成）──
        why_bullets = []
        if net_5d > 0:
            why_bullets.append(f"✓ 连续资金流入（5日累计{net_5d:+.0f}亿）")
        else:
            why_bullets.append(f"✓ 今日资金流入{net_now:+.1f}亿")
        if chain_position:
            why_bullets.append(f"✓ 属于{chain_position}")
        if has_leader_resonance:
            why_bullets.append(f"✓ 龙头一致（{leader_name}，{sector}核心）")
        if stage in ("赚钱效应", "一致性"):
            why_bullets.append(f"✓ 处于「{stage}」——赚钱效应已验证")

        # ── Risk bullets ──
        risk_bullets = []
        if is_event_driven:
            risk_bullets.append("⚠ 事件驱动，持续≤2.4天（历史均值）")
        if net_5d < 0 and net_now > 0:
            risk_bullets.append(f"⚠ 今日回流但5日仍流出{net_5d:+.0f}亿——可能一日游")
        if stage == "退潮":
            risk_bullets.append("⚠ 处于退潮阶段")
        if not has_leader_resonance:
            risk_bullets.append("⚠ 未形成龙头共振")

        # ── 赔率估算 ──
        success_prob = 50.0
        if has_leader_resonance:
            success_prob += 15
        if net_5d > 10:
            success_prob += 10
        if stage == "赚钱效应":
            success_prob += 10
        elif stage == "退潮":
            success_prob -= 20
        if is_event_driven:
            success_prob -= 15
        success_prob = max(5, min(90, success_prob))

        # 空间/风险（基于近期波动）
        upside = abs(chg) * 3 if abs(chg) > 0 else 5  # 简化为日涨跌幅×3
        downside = abs(chg) * 2 if abs(chg) > 0 else 3
        odds = upside / downside if downside > 0 else 0

        result.append(MainLine(
            sector=sector,
            stage=stage,
            persistence=persistence,
            star_rating=stars,
            sort_score=sort_score,
            net_today=net_now,
            net_5d=net_5d,
            trend_5d=trend_5d,
            trend_20d=trend_20d,
            inflection=(net_5d > 20 and net_now < 2) or (net_5d < -10 and net_now > 5),
            chain_position=chain_position,
            has_leader=has_leader_resonance,
            why_bullets=why_bullets,
            risk_bullets=risk_bullets,
            success_prob=success_prob,
            upside_pct=round(upside, 1),
            downside_pct=round(downside, 1),
            odds_ratio=round(odds, 1),
            is_event_driven=is_event_driven,
        ))

    # ── 排序：sort_score 降序（资金持续性优先）──
    result.sort(key=lambda x: x.sort_score, reverse=True)

    # ── 全局独立标签 ──
    l1 = layers.get("L1_global_macro", {}) or {}
    l1_read = (l1.get("read", "") or "").lower()
    global_risk_off = "下跌" in l1_read or "避险" in l1_read or "回调" in l1_read
    if global_risk_off:
        for ml in result:
            if any(kw in ml.sector for kw in ["半导体", "AI", "计算机", "通信", "科技"]):
                if ml.sort_score >= 2.0:
                    ml.chain_position = f"{ml.chain_position} | ⚡ 全球风险off中独立走强"
                    break

    return result


# ═══════════════════════════════════════════════════════
#  ⑤ 交易计划（Trading Plan）—— A/B/C 三级
# ═══════════════════════════════════════════════════════

def _build_trading_plan(brain, tree, main_lines_data) -> TradingPlanBlock:
    """构建 A/B/C 三级交易计划。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    sentiment = layers.get("sentiment", {}) or {}
    up_ratio = sentiment.get("up_ratio", 0)
    stage_dist = l4.get("stage_distribution", {})
    n_retreat = stage_dist.get("退潮", 0)

    opportunities = []

    # A级：板块共振 + 龙头共振 + 赚钱效应 → 可买入（但需用户确认图形）
    a_candidates = [m for m in main_lines_data
                    if m.star_rating >= 4
                    and m.stage in ("赚钱效应", "一致性")
                    and m.persistence == "持续流入"]
    for m in a_candidates:
        opportunities.append({
            "tier": "A",
            "name": m.sector,
            "conditions": [
                f"{m.sector}成交额继续维持第一梯队",
                f"龙头股（参考L5）继续领涨",
                f"板块内涨跌比>60%（扩散确认）",
            ],
            "give_up": [
                f"{m.sector}成交额跌出前三",
                f"龙头股跌破前日低点",
                f"板块净流入转负",
            ],
            "rationale": f"{m.star_rating}星级板块，{m.stage}阶段，{m.persistence}，链条完整。买入前需人工确认图形买点。",
        })

    # B级：资金持续流入但共识未完全形成 → 观察，满足条件可买
    b_candidates = [m for m in main_lines_data
                    if m.star_rating >= 3
                    and m.stage in ("资金流入",)
                    and m not in a_candidates]
    for m in b_candidates[:2]:
        opportunities.append({
            "tier": "B",
            "name": m.sector,
            "conditions": [
                f"{m.sector}连续3天净流入",
                f"板块成交额放大至全市场前3",
                f"龙头股出现共振（至少2/4指向同一只）",
            ],
            "give_up": [
                f"明日净流入转负",
                f"龙头分歧加大（4龙头指向不同个股）",
            ],
            "rationale": f"{m.star_rating}星级板块，{m.stage}阶段，{m.persistence}。共识正在形成，需确认条件满足后买入。",
        })

    # C级：事件驱动/反弹 → 仅短线，严格止损
    c_candidates = [m for m in main_lines_data
                    if m.star_rating >= 2
                    and m.stage in ("讨论", "资金流入")
                    and m not in a_candidates
                    and m not in b_candidates]
    for m in c_candidates[:2]:
        opportunities.append({
            "tier": "C",
            "name": m.sector,
            "conditions": [
                f"{m.sector}明日继续净流入",
                f"出现明确催化事件",
                f"板块涨幅>2%",
            ],
            "give_up": [
                "次日低开或净流出",
                "持有不超过3天",
                "止损-5%",
            ],
            "rationale": f"{m.star_rating}星级板块，{m.stage}阶段。仅为短线机会，不具备中线逻辑支撑。",
        })

    # 无机会判断
    no_opportunity = len(opportunities) == 0
    no_opportunity_reason = ""
    if no_opportunity:
        if n_retreat > 40:
            no_opportunity_reason = f"全市场{n_retreat}个板块处于退潮阶段，上涨家数仅{_pct(up_ratio)}%——防守优于进攻。等待退潮板块数降至20以下再考虑入场。"
        elif not main_lines_data:
            no_opportunity_reason = "无板块同时满足资金流入+阶段确认的条件——市场缺乏一致性。"
        else:
            no_opportunity_reason = "所有主线板块星级不足3星——资金未形成有效共识，不建议交易。"

    return TradingPlanBlock(
        opportunities=opportunities,
        no_opportunity=no_opportunity,
        no_opportunity_reason=no_opportunity_reason,
    )


# ═══════════════════════════════════════════════════════
#  ⑥ 风险与反例（Risk & Counter）
# ═══════════════════════════════════════════════════════

def _build_risk(brain, tree, main_lines_data) -> RiskBlock:
    """构建风险与反例分析。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    l7 = layers.get("L7_risk", {}) or {}
    mains = l4.get("main_lines", [])[:5]
    stage_dist = l4.get("stage_distribution", {})

    falsification = []

    # 1. 每条主线的证伪条件
    for m in mains[:3]:
        sector = m.get("sector", "")
        net = m.get("net_now", 0)
        stage = m.get("stage", "")

        if net > 0 and stage != "退潮":
            falsification.append({
                "scenario": f"如果 {sector} 成交额跌出前三",
                "if_condition": f"{sector} 成交额排名跌出全市场前三",
                "then_conclusion": "说明今日只是短期轮动，非真正主线，需重新评估方向",
            })
        if stage in ("赚钱效应", "一致性"):
            falsification.append({
                "scenario": f"如果 {sector} 明日净流入转负",
                "if_condition": f"{sector} 主力资金净流出",
                "then_conclusion": "赚钱效应可能中断，从A级降至B级，减仓至轻仓",
            })
        if stage == "资金流入" and net > 3:
            falsification.append({
                "scenario": f"如果 {sector} 连续3天净流入且扩散到产业链下游",
                "if_condition": "产业链下游（如光模块→PCB→服务器）同步上涨",
                "then_conclusion": "主线升级为A级机会，可加大关注",
            })

    # 2. 全局条件
    if stage_dist.get("退潮", 0) > 30:
        falsification.append({
            "scenario": "如果明日退潮板块数增至40+",
            "if_condition": "退潮板块数继续增加",
            "then_conclusion": "全面退潮风险加大，建议减仓至0-10%",
        })

    n_retreat = stage_dist.get("退潮", 0)
    sentiment = layers.get("sentiment", {}) or {}
    up_ratio = sentiment.get("up_ratio", 0)

    # 3. 反例（目前判断是NO，但如果...）
    if n_retreat > 40 and up_ratio < 40:
        falsification.append({
            "scenario": "如果明日上涨家数恢复至60%+且主线成交额重夺第一",
            "if_condition": "赚钱效应恢复 + 主线回归",
            "then_conclusion": "今日悲观判断可能过于保守，可重新评估为CAUTION甚至YES",
        })

    # 4. 事件风险
    try:
        from catalyst_calendar import get_upcoming_catalysts
        ref = datetime.date.today()
        cats = get_upcoming_catalysts(ref, days_ahead=7) or []
    except Exception:
        cats = []

    upcoming = []
    for c in cats:
        upcoming.append({
            "date": str(c.get("date", "")),
            "name": c.get("name", ""),
            "country": c.get("country", ""),
            "impact": c.get("impact", ""),
            "days_until": c.get("days_until", 0),
        })

    # 关键事件风险
    high_impact = [c for c in upcoming if c.get("impact") == "high"]
    for c in high_impact[:3]:
        falsification.append({
            "scenario": f"关注 {c['date']} {c['name']}",
            "if_condition": f"{'超预期' if 'CPI' in c['name'] else '不及预期'}",
            "then_conclusion": "当前所有逻辑需要重新定价，建议事件前降低仓位",
        })

    biggest_risk = (
        f"全市场{n_retreat}个板块退潮，上涨家数仅{_pct(up_ratio)}%。"
        f"若明日主线无法接力，全面退潮风险加大。"
    ) if n_retreat > 30 else "最大的风险是主线持续性不足——今日流入方向若明日转弱，市场将回到无共识状态。"

    return RiskBlock(
        falsification=falsification,
        upcoming_events=upcoming,
        biggest_risk=biggest_risk,
    )


# ═══════════════════════════════════════════════════════
#  ⑦ 历史经验（Historical Context）
# ═══════════════════════════════════════════════════════

def _build_historical(brain, tree) -> HistoricalBlock:
    """查询相似行情历史胜率（Phase 2：判断/执行分离）。"""
    decision = brain.get("decision", {})
    confidence_overall = brain.get("confidence", {}).get("overall", 0)

    # 1) 优先用 trade_journal 回放（判断 vs 执行）
    try:
        from narrative_layers import reconcile_journal
        rec = reconcile_journal()
    except Exception:
        rec = None
    if rec and rec.get("ok"):
        j = rec.get("judgment", {})
        e = rec.get("execution", {})
        try:
            import sqlite3 as _sq
            db_path = os.path.join(ROOT, "database", "vibe_research.db")
            _c = _sq.connect(db_path)
            n_sig = _c.execute(
                "SELECT COUNT(*) FROM trade_journal WHERE rec_type='signal'").fetchone()[0]
            n_trade = _c.execute(
                "SELECT COUNT(*) FROM trade_journal WHERE rec_type='trade'").fetchone()[0]
            _c.close()
        except Exception:
            n_sig = j.get("n", 0) + j.get("na", 0) + j.get("pending", 0)
            n_trade = 0
        if n_sig > 0:
            parts = []
            jr = j.get("rate")
            if jr is not None:
                parts.append(f"系统判断命中率 {jr}%（{j['right']}对/{j['wrong']}错，样本{j['n']}）")
            else:
                parts.append(f"已落库 {n_sig} 条信号，判断回放样本积累中（{j.get('pending',0)}条待次日数据）")
            cap = e.get("capture_rate")
            if cap is not None:
                parts.append(f"执行跟单率 {cap}%（判断对且跟单 {e['executed']} 条）")
            if e.get("discipline_error"):
                parts.append(f"执行纪律误差 {e['discipline_error']} 次（错过利润 {e['missed_profit']}/逆向跟单 {e['acted_on_wrong']}）")
            conclusion = "⑧ 学习进化已通电（判断/执行分离）：" + "；".join(parts) \
                         + f"。当前置信度 {confidence_overall}%。"
            return HistoricalBlock(
                has_data=True,
                similar_period_desc=f"基于 trade_journal 回放（信号 {n_sig} 条 / 执行录入 {n_trade} 条）的判断-执行分离分析。",
                win_rate=jr,
                avg_return=None,
                sample_count=n_sig,
                conclusion=conclusion,
                backtest_available=True,
            )

    # 2) 回退：backtest 快照
    backtest_available = False
    win_rate = None
    avg_return = None
    sample_count = 0

    archive_dir = os.path.join(OUTPUT, "archive")
    if os.path.isdir(archive_dir):
        snapshots = sorted([f for f in os.listdir(archive_dir) if f.endswith(".json")])
        if len(snapshots) >= 5:
            backtest_available = True
            try:
                results = []
                for snap in snapshots[-5:]:
                    path = os.path.join(archive_dir, snap)
                    with open(path, "r", encoding="utf-8") as f:
                        s = json.load(f)
                    if s.get("hit") is not None:
                        results.append(s)
                if results:
                    sample_count = len(results)
                    win_rate = sum(1 for r in results if r.get("hit")) / sample_count * 100
                    avg_return = sum(r.get("next_day_return", 0) or 0 for r in results) / sample_count
            except Exception:
                pass

    if backtest_available and win_rate is not None:
        return HistoricalBlock(
            has_data=True,
            similar_period_desc=(
                f"基于近{sample_count}个交易日的brain决策回测："
                f"置信度{confidence_overall}%区间胜率{win_rate:.0f}%，"
                f"平均次日收益{avg_return:+.2f}%"
            ) if avg_return is not None else f"近{sample_count}日回测数据可用",
            win_rate=win_rate,
            avg_return=avg_return,
            sample_count=sample_count,
            conclusion=(
                f"回测胜率{win_rate:.0f}%——"
                f"{'高于50%，系统判断有效性初步验证' if win_rate > 50 else '低于50%，系统判断需要优化'}。"
                f"系统判断信号已自动落库，录入实际交易可进一步区分执行纪律。"
            ),
            backtest_available=True,
        )

    # 3) 无数据
    return HistoricalBlock(
        has_data=False,
        similar_period_desc="",
        conclusion=f"历史数据库为空（trade_journal 信号=0条，archive快照={sample_count}份）。"
                   f"盘前/收盘后 produce() 会自动把系统判断写入 trade_journal，次日即可回放判断命中率。",
        backtest_available=backtest_available,
    )


# ═══════════════════════════════════════════════════════
#  ⑧ 安检清单（Pre-flight Checklist）—— Trading OS 核心
# ═══════════════════════════════════════════════════════

def _ic_calibration_signal() -> dict:
    """构造 IC 自校准信号 dict，供 preflight 反哺使用。

    取自 learning_center.prediction_feedback()：IC 方向命中率（预测回放 T+1 实际市场）。
    信号口径：{available, accuracy, n, pos_scale}；命中率<40% 时 preflight 会强制降级。
    """
    try:
        from learning_center import prediction_feedback
        pf = prediction_feedback()
        return {
            "available": bool(pf.get("applied")),
            "accuracy": pf.get("accuracy"),
            "n": pf.get("count", 0),
            "pos_scale": pf.get("pos_scale", 1.0),
        }
    except Exception:
        return {"available": False, "accuracy": None, "n": 0, "pos_scale": 1.0}


def _build_preflight(tree) -> dict:
    """运行安检清单（含系统自校准第7项），将结果转为可序列化的字典。"""
    try:
        from brain.trading_rules import run_preflight
        pf = run_preflight(tree, ic_signal=_ic_calibration_signal())
        return {
            "verdict": pf.verdict,
            "verdict_reason": pf.verdict_reason,
            "passed_count": pf.passed_count,
            "total_count": pf.total_count,
            "required": pf.required,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "reason": c.reason,
                    "detail": c.detail,
                }
                for c in pf.checks
            ],
            "failed_summary": pf.failed_summary,
            "calibration": pf.calibration,
        }
    except Exception as e:
        return {"error": str(e), "verdict": "ERROR"}


def _build_data_health() -> dict:
    """数据健康体检（Data Integrity Layer）。失败时降级为空块，绝不让日报崩溃。"""
    try:
        from data_health import check as _dh_check
        return _dh_check()
    except Exception as e:  # noqa
        return {
            "trade_date": "", "checks": [], "trade_allowed": True, "failed": [],
            "summary": f"（数据健康模块暂不可用：{e}）",
            "n_stocks": 0, "flow_cov": 0.0, "cap_cov": 0.0,
        }


# ═══════════════════════════════════════════════════════
#  ⑨ 市场结构（Market Structure）—— 谁在赚钱
# ═══════════════════════════════════════════════════════

def _build_market_structure(tree) -> dict:
    """分析市场结构：谁在赚钱？风格切换？"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:10]
    sentiment = layers.get("sentiment", {}) or {}
    up_ratio = sentiment.get("up_ratio", 0)
    up_pct = round(up_ratio * 100) if 0 < up_ratio < 1 else up_ratio

    # 分类板块：成长/防御/周期
    growth = []
    defensive = []
    cyclical = []
    growth_kw = ["半导体", "计算机", "通信", "消费电子", "传媒", "自动化", "IT", "软件", "AI"]
    defensive_kw = ["银行", "煤炭", "电力", "公用事业", "钢铁", "石油", "医药", "医疗"]
    cyclical_kw = ["汽车", "光伏", "房地产", "建材", "化工", "有色"]

    for m in mains:
        sector = m.get("sector", "")
        net = m.get("net_now", 0)
        if any(kw in sector for kw in growth_kw):
            growth.append({"name": sector, "net": net})
        elif any(kw in sector for kw in defensive_kw):
            defensive.append({"name": sector, "net": net})
        elif any(kw in sector for kw in cyclical_kw):
            cyclical.append({"name": sector, "net": net})

    # 判断风格
    growth_net = sum(g.get("net", 0) for g in growth)
    defensive_net = sum(d.get("net", 0) for d in defensive)
    cyclical_net = sum(c.get("net", 0) for c in cyclical)

    if growth_net > 0 and defensive_net < 0:
        style = "进攻型 —— 资金从防御流向成长，风险偏好上升"
    elif defensive_net > 0 and growth_net < 0:
        style = "防守型 —— 资金涌入防御板块，市场避险"
    elif cyclical_net > 0 and growth_net < 0 and defensive_net < 0:
        style = "周期轮动 —— 资金从成长/防御流向周期，博弈经济复苏"
    else:
        style = "混沌 —— 各类资金方向不一，无明显风格偏好"

    # 谁赚钱
    if up_pct > 50:
        who_makes_money = f"多数人赚钱（上涨{up_pct}%）——散户活跃，注意机构借机出货"
    elif up_pct > 30:
        who_makes_money = f"少数人赚钱（上涨{up_pct}%）——机构主导，选股>择时"
    else:
        who_makes_money = f"几乎没人赚钱（上涨仅{up_pct}%）——空仓跑赢99%"

    return {
        "style": style,
        "who_makes_money": who_makes_money,
        "growth_net": round(growth_net, 1),
        "defensive_net": round(defensive_net, 1),
        "cyclical_net": round(cyclical_net, 1),
        "growth_sectors": [g["name"] for g in growth[:3] if g["net"] > 0],
        "defensive_sectors": [d["name"] for d in defensive[:3] if d["net"] > 0],
    }


# ═══════════════════════════════════════════════════════
#  ⑩ 机会成本分析（Opportunity Cost）
# ═══════════════════════════════════════════════════════

def _build_opportunity_cost(tree, main_lines_data) -> dict:
    """分析不做某板块的机会成本。"""
    if not main_lines_data:
        return {"has_analysis": False, "message": "无足够数据做机会成本分析"}

    # 找到事件驱动板块（排名高但持续性差的）
    event_driven = [m for m in main_lines_data if m.is_event_driven]
    # 找到资金持续板块
    money_continuous = [m for m in main_lines_data if m.net_5d > 0 and not m.is_event_driven]

    analysis = []
    for ed in event_driven[:2]:
        # 历史统计：事件驱动平均持续2.4天
        analysis.append({
            "sector": ed.sector,
            "type": "event_driven",
            "message": (
                f"不做{ed.sector}的原因：事件驱动板块历史上平均持续2.4天。"
                f"今日{ed.net_today:+.1f}亿流入但5日累计{ed.net_5d:+.0f}亿——"
                f"事件驱动追高风险大于回报。"
            ),
            "history_avg_duration": 2.4,
        })

    for mc in money_continuous[:2]:
        analysis.append({
            "sector": mc.sector,
            "type": "money_continuous",
            "message": (
                f"错过{mc.sector}的代价：连续流入（5日{mc.net_5d:+.0f}亿），"
                f"处于「{mc.stage}」阶段。如果明天继续流入+龙头确认，"
                f"机会成本将上升——建议明天优先观察。"
            ),
        })

    return {
        "has_analysis": len(analysis) > 0,
        "items": analysis,
    }


# ═══════════════════════════════════════════════════════
#  ⑪ 明日行动清单（Action List）—— Trading OS 核心
# ═══════════════════════════════════════════════════════

def _build_action_list(tree, main_lines_data, preflight) -> list:
    """生成明天的具体行动清单（时间戳+条件）。"""
    actions = []
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    main_names = [m.sector for m in main_lines_data[:3]]

    # 优先级-1的主线
    top = main_lines_data[0] if main_lines_data else None

    # 09:35 — 开盘确认资金方向
    if top:
        actions.append({
            "time": "09:35",
            "action": f"看{top.sector}是否资金第一",
            "condition": f"{top.sector}开盘净流入>0且排名前3",
            "if_fail": "放弃今日交易计划，继续观望",
        })

    # 10:00 — 龙头确认
    has_leader = any(m.has_leader for m in main_lines_data[:3])
    if has_leader:
        leader_sectors = [m for m in main_lines_data[:3] if m.has_leader]
        ls = leader_sectors[0]
        actions.append({
            "time": "10:00",
            "action": f"看{ls.sector}龙头是否封板",
            "condition": f"龙头股涨停或涨幅>7%",
            "if_fail": f"龙头弱则{ls.sector}不可追",
        })
    else:
        actions.append({
            "time": "10:00",
            "action": "看是否有板块出现龙头共振（至少3/4指向同一只）",
            "condition": "盘中监测L5数据更新",
            "if_fail": "无龙头共振则不交易",
        })

    # 11:00 — 成交额确认
    actions.append({
        "time": "11:00",
        "action": "看全市场成交额是否突破1.5万亿（半日）",
        "condition": "半日成交额>7500亿（全日前20日均量×80%）",
        "if_fail": "缩量则退潮风险加大，减仓或空仓",
    })

    # 13:30 — 午后扩散确认
    if main_names and len(main_names) >= 2:
        actions.append({
            "time": "13:30",
            "action": f"看主线是否从{main_names[0]}扩散到{main_names[1]}",
            "condition": f"{main_names[1]}涨幅>1%且净流入>0",
            "if_fail": "扩散失败=存量博弈，不宜加仓",
        })

    # 14:30 — 尾盘抄底信号
    sentiment = layers.get("sentiment", {}) or {}
    up_ratio = sentiment.get("up_ratio", 0)
    up_pct = round(up_ratio * 100) if 0 < up_ratio < 1 else up_ratio
    if up_pct < 30:
        actions.append({
            "time": "14:30",
            "action": "看尾盘是否有抄底资金入场（急跌+放量）",
            "condition": "指数跌幅收窄+成交量突然放大",
            "if_fail": "尾盘继续缩量下跌→明天可能更低，不等了",
        })
    else:
        actions.append({
            "time": "14:30",
            "action": "看尾盘资金是否延续上午方向",
            "condition": "主线板块14:30净流入仍为正",
            "if_fail": "尾盘出货=明天大概率低开，减仓",
        })

    return actions


# ═══════════════════════════════════════════════════════
#  ⑫ 赔率表（Odds Table）—— 所有机会按赔率排序
# ═══════════════════════════════════════════════════════

def _build_odds_table(main_lines_data) -> list:
    """构建赔率表，按赔率从高到低排序。"""
    odds_list = []
    for m in main_lines_data:
        if m.star_rating < 2 or m.stage == "退潮":
            continue
        odds_list.append({
            "sector": m.sector,
            "stage": m.stage,
            "success_prob": m.success_prob,
            "upside": m.upside_pct,
            "downside": m.downside_pct,
            "odds_ratio": m.odds_ratio,
            "star_rating": m.star_rating,
            "tier": "A" if m.star_rating >= 4 and not m.is_event_driven
                    else "B" if m.star_rating >= 3 else "C",
            "is_event_driven": m.is_event_driven,
        })

    # 按赔率降序
    odds_list.sort(key=lambda x: x["odds_ratio"], reverse=True)
    return odds_list[:6]

# ═══════════════════════════════════════════════════════
#  ⑬ 催化剂日历（Catalyst Calendar）—— 未来一周关键事件
# ═══════════════════════════════════════════════════════

_IMP_STARS = {"high": 5, "medium": 4, "low": 3}
_WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _build_catalyst_calendar() -> dict:
    """获取未来两周关键经济事件，按日期排序，带影响评级。

    数据来源：catalyst_calendar.py 规则推算（零网络请求）。
    覆盖中美 CPI/PMI/NFP/FOMC/LPR/M2/GDP + 每周初请失业金。
    """
    try:
        from catalyst_calendar import get_upcoming_catalysts
        ref = datetime.date.today()
        raw = get_upcoming_catalysts(ref, days_ahead=14)
    except Exception as e:
        return {"has_data": False, "error": str(e), "events": [], "next_high_impact": None, "week_summary": "催化剂日历暂不可用"}

    if not raw:
        return {"has_data": False, "events": [], "next_high_impact": None, "week_summary": "未来两周无重大经济数据发布"}

    events = []
    next_high = None
    for c in raw:
        imp = c.get("importance", "low")
        stars_n = _IMP_STARS.get(imp, 3)
        # 解析日期 → 中文格式
        try:
            d = datetime.date.fromisoformat(c["expected_date"])
            date_cn = f"{d.month}月{d.day}日({_WEEKDAYS_CN[d.weekday()]})"
        except Exception:
            date_cn = c.get("expected_date", "?")
            d = None

        ev = {
            "date": c["expected_date"],
            "date_cn": date_cn,
            "days_until": c.get("days_until", 0),
            "name": c.get("name", ""),
            "country": c.get("country", ""),
            "importance": imp,
            "impact_stars": "★" * stars_n + "☆" * (5 - stars_n),
            "description": c.get("description", ""),
            "watch_fields": c.get("watch_fields", []),
            "catalyst_type": c.get("catalyst_type", ""),
        }
        events.append(ev)

        # 记录第一个 high-impact 事件
        if next_high is None and imp == "high" and c.get("days_until", 0) >= 0:
            next_high = ev

    # 按 days_until 排序
    events.sort(key=lambda x: (x["days_until"], x["date"]))

    # 生成本周摘要
    high_events = [e for e in events if e["importance"] == "high"]
    if high_events:
        parts = [f"{e['date_cn']} {e['name']}" for e in high_events[:4]]
        week_summary = f"重点关注：{'、'.join(parts)}"
    else:
        week_summary = "未来两周无 high-impact 事件"

    return {
        "has_data": True,
        "events": events,
        "next_high_impact": next_high,
        "week_summary": week_summary,
        "total_count": len(events),
        "high_count": len(high_events),
    }


def _build_cross_asset() -> CrossAssetBlock:
    """构建跨资产资金情报：黄金 / 大宗商品 / ETF / 沪深港通。

    数据来自 Gold Decision Engine (gold_report.json) 与
    Capital Flow Engine (flow_report.json) 的产出文件，
    这两个引擎在 brain 流水线中先于 CIO Agent 运行并写入 output/。
    """
    block = CrossAssetBlock()

    # ── 黄金（Gold Engine）──
    gp = os.path.join(OUTPUT, "gold_report.json")
    if os.path.exists(gp):
        try:
            g = json.load(open(gp, encoding="utf-8"))
            block.gold_price = float(g.get("gold_price", 0) or 0)
            block.gold_change_pct = float(g.get("gold_change_pct", 0) or 0)
            nv = g.get("narrative", {}) or {}
            theme = nv.get("primary_theme", "") or ""
            block.gold_signal = f"{theme}（驱动评分{nv.get('confidence', 0) or 0:.0f}）"[:60]
            block.has_data = True
        except Exception:
            pass

    # ── 资金流（Capital Flow Engine）──
    fp = os.path.join(OUTPUT, "flow_report.json")
    if os.path.exists(fp):
        try:
            f = json.load(open(fp, encoding="utf-8"))
            fs = f.get("flow_score", {}) or {}
            block.flow_score_overall = int(fs.get("overall", 0) or 0)
            block.flow_one_liner = (fs.get("one_liner") or "")[:80]

            # 商品行情（取能源/贵金属/工业里波动最大的几个）
            comm = f.get("commodity", {}) or {}
            picked = []
            for cat in ("energy", "precious", "industrial"):
                for it in (comm.get(cat) or [])[:2]:
                    picked.append({
                        "name_cn": it.get("name_cn", "") or it.get("name", ""),
                        "change_pct": round(float(it.get("change_pct", 0) or 0), 2),
                        "a_share_link": it.get("a_share_link", "") or "",
                    })
            block.commodities = picked[:6]

            # ETF 份额变化 TOP
            etf = f.get("etf_flow_summary", {}) or {}
            for item in (etf.get("top_inflow") or [])[:3]:
                block.etf_top_inflow.append({
                    "name": item.get("name", ""),
                    "shares_change_pct": round(float(item.get("shares_change_pct", 0) or 0), 2),
                    "amount_yi": round(float(item.get("amount", 0) or 0) / 1e8, 1),
                })
            for item in (etf.get("top_outflow") or [])[:3]:
                block.etf_top_outflow.append({
                    "name": item.get("name", ""),
                    "shares_change_pct": round(float(item.get("shares_change_pct", 0) or 0), 2),
                    "amount_yi": round(float(item.get("amount", 0) or 0) / 1e8, 1),
                })

            # 沪深港通
            inst = f.get("institution", {}) or {}
            hsgt = inst.get("hsgt", {}) or {}
            block.north_net = round(float(hsgt.get("north_net", 0) or 0), 1)
            block.south_net = round(float(hsgt.get("south_net", 0) or 0), 1)

            block.has_data = True
        except Exception:
            pass

    return block


def _build_observations() -> ObservationBlock:
    """读取 Relationship Engine 产出，构建"今日新发现"块。"""
    block = ObservationBlock()
    rp = os.path.join(OUTPUT, "relationship_report.json")
    if not os.path.exists(rp):
        return block
    try:
        rep = json.load(open(rp, encoding="utf-8"))
    except Exception:
        return block
    block.has_data = True
    block.headline = rep.get("headline", "")
    block.discoveries = rep.get("discoveries", []) or []
    return block


def _build_cro() -> CROBlock:
    """读取 CRO（首席研究官）总裁定词，置于备忘录最顶端。"""
    block = CROBlock()
    cp = os.path.join(OUTPUT, "cro_report.json")
    if not os.path.exists(cp):
        return block
    try:
        c = json.load(open(cp, encoding="utf-8"))
    except Exception:
        return block
    block.has_data = True
    block.verdict = c.get("verdict", "")
    block.score = c.get("score", 0.0) or 0.0
    block.confidence = c.get("confidence", 0.0) or 0.0
    q1 = c.get("q1", {}) or {}
    q2 = c.get("q2", {}) or {}
    q3 = c.get("q3", {}) or {}
    block.q1_headline = q1.get("headline", "")
    block.q1_sectors = q1.get("sectors", []) or []
    block.q2_headline = q2.get("headline", "")
    block.q2_bullets = q2.get("bullets", []) or []
    block.q3_headline = q3.get("headline", "")
    block.q3_bullets = q3.get("bullets", []) or []
    return block


# ═══════════════════════════════════════════════════════
#  审计升级：全球市场固定看板 / 资金迁移 / 市场电影
# ═════════════════════════════════════════════════════

_GLOBAL_BOARD_SPEC = [
    # (显示名, 内部代码, 重要度星, 数据源)
    ("纳斯达克", "NDX", 5, "blocked"),
    ("SOXX半导体ETF", "SOXX", 5, "blocked"),
    ("韩国KOSPI", "KS11", 5, "sina"),
    ("台湾加权", "TWII", 5, "sina"),
    ("恒生科技", "HSTECH", 5, "blocked"),
    ("美元指数", "DXY", 5, "blocked"),
    ("美债2Y", "US2Y", 5, "blocked"),
    ("美债10Y", "US10Y", 5, "blocked"),
    ("TIPS", "TIPS", 5, "blocked"),
    ("黄金", "GC", 5, "flow"),
    ("铜", "HG", 4, "flow"),
    ("原油", "CL", 4, "flow"),
    ("BTC", "BTC", 3, "blocked"),
]


def _global_latest_change(symbol):
    """返回 (change_pct, date) 最近一日相对前一日涨跌；无数据返回 (None, None)。"""
    try:
        import sqlite3
        db = os.path.join(ROOT, "database", "vibe_research.db")
        con = sqlite3.connect(db)
        rows = con.execute(
            "SELECT date, close FROM global_history WHERE symbol=? "
            "ORDER BY date DESC LIMIT 2", (symbol,)).fetchall()
        con.close()
        if len(rows) < 2:
            return None, None
        d1, c1 = rows[0]
        d0, c0 = rows[1]
        if not c0:
            return None, None
        return (c1 - c0) / c0 * 100, d1
    except Exception:
        return None, None


def _build_global_market() -> GlobalMarketBlock:
    """全球市场固定看板：已接入填真实日涨跌，未接入明确标'未接入'。"""
    block = GlobalMarketBlock()
    # 商品日涨跌来自 Capital Flow Engine
    comm = {}
    fp = os.path.join(OUTPUT, "flow_report.json")
    if os.path.exists(fp):
        try:
            f = json.load(open(fp, encoding="utf-8"))
            for cat in ("energy", "precious", "industrial"):
                for it in (f.get("commodity", {}).get(cat) or []):
                    comm[it.get("name")] = it.get("change_pct", 0)
        except Exception:
            pass
    flow_map = {"GC": "黄金", "HG": "铜", "CL": "原油"}
    board = []
    for name, sym, imp, src in _GLOBAL_BOARD_SPEC:
        if src == "sina":
            chg, dt = _global_latest_change(sym)
            if chg is not None:
                board.append({"name": name, "importance": imp, "change_pct": round(chg, 2),
                              "star": imp, "status": "ok", "note": f"{dt} 真实"})
            else:
                board.append({"name": name, "importance": imp, "change_pct": None,
                              "star": imp, "status": "empty", "note": "暂无数据"})
        elif src == "flow":
            chg = comm.get(sym)
            if chg is not None:
                board.append({"name": name, "importance": imp, "change_pct": round(chg, 2),
                              "star": imp, "status": "ok", "note": "flow 实时"})
            else:
                board.append({"name": name, "importance": imp, "change_pct": None,
                              "star": imp, "status": "empty", "note": "暂无数据"})
        else:  # blocked / 外部数据：若 global_history 已回填则自动点亮
            chg, dt = _global_latest_change(sym)
            if chg is not None:
                board.append({"name": name, "importance": imp, "change_pct": round(chg, 2),
                              "star": imp, "status": "ok", "note": f"{dt} 真实(回填)"})
            else:
                board.append({"name": name, "importance": imp, "change_pct": None,
                              "star": imp, "status": "blocked", "note": "沙箱网络限制·未接入"})
    block.board = board
    ok = [b for b in board if b["status"] == "ok"]
    blocked = [b for b in board if b["status"] == "blocked"]
    parts = []
    for b in ok:
        arrow = "↑" if b["change_pct"] > 0 else "↓"
        parts.append(f"{b['name']}{arrow}{abs(b['change_pct']):.1f}%")
    block.one_liner = ("全球：" + "，".join(parts) + "。") if parts else "全球数据不足。"
    if blocked:
        block.one_liner += (f" {len(blocked)}项（纳指/SOXX/美元/美债/TIPS/恒生科技/BTC）"
                            f"因沙箱网络限制未接入，需在可联网机器回填 global_history。")
    block.has_data = True
    return block


def _build_capital_flow() -> CapitalFlowBlock:
    """资金迁移：流不是价。用真实 ETF份额变化/南向/商品方向合成迁移表 + AI一句话。"""
    block = CapitalFlowBlock()
    fp = os.path.join(OUTPUT, "flow_report.json")
    if not os.path.exists(fp):
        return block
    try:
        f = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return block
    es = f.get("etf_flow_summary", {}) or {}
    block.etf_total_net_yi = round(float(es.get("total_main_inflow", 0) or 0) / 1e8, 1)
    hsgt = (f.get("institution", {}) or {}).get("hsgt", {}) or {}
    block.south_net_yi = round(float(hsgt.get("south_net", 0) or 0), 1)
    block.north_net_yi = round(float(hsgt.get("north_net", 0) or 0), 1)
    for it in (es.get("top_inflow") or [])[:3]:
        block.etf_top_inflow.append({
            "name": it.get("name", ""),
            "shares_change_pct": round(float(it.get("shares_change_pct", 0) or 0), 2),
            "amount_yi": round(float(it.get("amount", 0) or 0) / 1e8, 1),
        })
    for it in (es.get("top_outflow") or [])[:2]:
        block.etf_top_outflow.append({
            "name": it.get("name", ""),
            "shares_change_pct": round(float(it.get("shares_change_pct", 0) or 0), 2),
            "amount_yi": round(float(it.get("amount", 0) or 0) / 1e8, 1),
        })
    # 迁移表：用真实信号（流的方向，不是价格）
    mig = []
    if block.south_net_yi > 30:
        mig.append({"source": "南向资金", "target": "港股(创新药/科技)",
                    "star": 5, "note": f"净买入{block.south_net_yi:.0f}亿，机构借道港股通加仓"})
    if block.etf_top_inflow:
        top = block.etf_top_inflow[0]
        mig.append({"source": "ETF净申购", "target": top["name"],
                    "star": 4, "note": f"份额+{top['shares_change_pct']:.1f}%（{top['amount_yi']:.0f}亿），硬科技获增量"})
    comm = f.get("commodity", {}) or {}
    up = [it.get("name_cn") for it in (comm.get("energy") or []) if (it.get("change_pct") or 0) > 0]
    if up:
        mig.append({"source": "商品资金", "target": "、".join(up[:2]),
                    "star": 3, "note": "能源/资源品走强"})
    if block.etf_total_net_yi < 0:
        mig.append({"source": "ETF整体", "target": "净赎回(存量腾挪)",
                    "star": 2, "note": f"全市场ETF净赎回{abs(block.etf_total_net_yi):.0f}亿——存量搬家非增量入场"})
    block.migration = mig
    q1 = (f.get("intelligence", {}) or {}).get("q1_global", "") or ""
    block.one_liner = (q1[:160] if q1 else "资金流向分化，无明显方向。")
    block.has_data = True
    return block


def _build_market_movie() -> MarketMovieBlock:
    """市场电影：基于日级数据重构的今日叙事时间线（非分钟级实时）。"""
    block = MarketMovieBlock()
    scenes = []
    south = 0.0
    # 1) 亚洲科技风险偏好（真实：KOSPI/TWII 日涨跌）
    ks, ks_d = _global_latest_change("KS11")
    tw, tw_d = _global_latest_change("TWII")
    if ks is not None:
        arrow = "走强" if ks > 0 else "走弱"
        ev = f"韩国KOSPI {arrow} {ks:+.1f}%"
        if tw is not None:
            ev += f"，台湾加权 {tw:+.1f}%"
        scenes.append({"time": "隔夜·亚洲", "event": ev,
                       "implication": f"亚洲科技风险偏好{'上升' if ks > 0 else '回落'}（{ks_d}真实）"})
    # 2) 商品/美元定调
    fp = os.path.join(OUTPUT, "flow_report.json")
    gold_chg = oil_chg = None
    if os.path.exists(fp):
        try:
            f = json.load(open(fp, encoding="utf-8"))
            for cat in ("energy", "precious"):
                for it in (f.get("commodity", {}).get(cat) or []):
                    if it.get("name") == "GC":
                        gold_chg = it.get("change_pct")
                    if it.get("name") == "CL":
                        oil_chg = it.get("change_pct")
        except Exception:
            pass
    cm = []
    if gold_chg is not None:
        cm.append(f"黄金{gold_chg:+.1f}%")
    if oil_chg is not None:
        cm.append(f"原油{oil_chg:+.1f}%")
    if cm:
        scenes.append({"time": "09:00前·定调", "event": "商品：" + "，".join(cm),
                       "implication": "决定资源与避险基调（美元/美债未接入）"})
    # 3) 资金流（真实：南向 + ETF净申购）
    if os.path.exists(fp):
        try:
            f = json.load(open(fp, encoding="utf-8"))
            hsgt = (f.get("institution", {}) or {}).get("hsgt", {}) or {}
            south = round(float(hsgt.get("south_net", 0) or 0), 1)
            es = f.get("etf_flow_summary", {}) or {}
            top_in = (es.get("top_inflow") or [])
            if south > 30:
                scenes.append({"time": "全天·港股通", "event": f"南向资金净买入港股 {south:.0f}亿",
                               "implication": "机构借道港股通加仓创新药/科技，港股分流部分风险偏好"})
            if top_in:
                t0 = top_in[0]
                scenes.append({"time": "全天·ETF",
                               "event": f"ETF净申购集中于{t0.get('name','')}(+{t0.get('shares_change_pct',0):.1f}%)",
                               "implication": "硬科技（半导体设备）获增量资金，而非存量板块"})
        except Exception:
            pass
    # 4) 催化剂（明日/本周）
    cats = _build_catalyst_calendar().get("events", [])[:3]
    for c in cats:
        scenes.append({"time": f"{c['date_cn']}({c['days_until']}天后)",
                       "event": f"催化：{c['name']}",
                       "implication": ("重点" if c["importance"] == "high" else "留意")
                       + "：" + "、".join(c.get("watch_fields", [])[:2])})
    # 5) 主线收尾
    scenes.append({"time": "收盘·主线", "event": "全天主线：AI/半导体设备",
                   "implication": "资金在做'存量腾挪到硬科技'；若明日ETF续申购+韩国不弱，则AI链延续"})
    block.scenes = scenes
    # 摘要
    ks_b = (ks or 0) > 0
    south_txt = f"，南向{south:.0f}亿加港股" if south > 30 else ""
    block.summary = (
        f"今日叙事（日级重构）：亚洲科技{'偏强' if ks_b else '中性'}{south_txt}"
        f"；ETF净申购集中于硬科技——资金在做存量腾挪到AI硬科技，而非全面进攻。"
    )
    block.has_data = True
    return block


def _build_narrative() -> NarrativeBlock:
    """「为什么」引擎：读取 narrative_report.json（由 narrative_engine.py 生成）。"""
    block = NarrativeBlock()
    rp = os.path.join(OUTPUT, "narrative_report.json")
    if not os.path.exists(rp):
        return block
    try:
        rep = json.load(open(rp, encoding="utf-8"))
    except Exception:
        return block
    block.has_data = True
    block.has_news = rep.get("has_news", False)
    block.news_count = rep.get("news_count", 0)
    block.headline = rep.get("headline", "")
    block.narratives = rep.get("narratives", []) or []
    return block


def _build_panqian() -> PanQianBlock:
    """盘前纪要：读取 output/panqian_YYYYMMDD.json（由 panqian_parser.py 生成）。

    取文件名日期最新的一篇（盘前纪要每日一篇，latest 即当日）。
    文件缺失 / 解析失败 → 安全降级 has_data=False，不进 memo。
    """
    block = PanQianBlock()
    if not os.path.isdir(OUTPUT):
        return block
    cands = sorted(
        (f for f in os.listdir(OUTPUT)
         if re.match(r"panqian_\d{8}\.json$", f)),   # 仅匹配 dated 文章，排除 panqian_feed.json
        reverse=True,
    )
    if not cands:
        return block
    rp = os.path.join(OUTPUT, cands[0])
    try:
        rep = json.load(open(rp, encoding="utf-8"))
    except Exception:
        return block
    block.has_data = True
    block.article_date = rep.get("article_date", "")
    block.source_url = rep.get("source_url", "")
    block.headline = rep.get("headline", "")
    block.sections = rep.get("sections", {}) or {}
    block.section_order = rep.get("section_order", []) or []
    block.stats = rep.get("stats", {}) or {}
    block.risk_flags = rep.get("risk_flags", []) or []
    return block


def _build_industry_chain() -> "IndustryChainBlock":
    """L3.5 产业链推理：读取 output/industry_chain_report.json（由 industry_chain_agent.py 生成）。

    文件缺失 / 解析失败 → 安全降级 has_data=False，不进 memo。
    该 json 由 L3.5 agent 在编排器运行期写入（与本 memo 同一轮），数据天然新鲜。
    """
    block = IndustryChainBlock()
    rp = os.path.join(OUTPUT, "industry_chain_report.json")
    if not os.path.exists(rp):
        return block
    try:
        rep = json.load(open(rp, encoding="utf-8"))
    except Exception:
        return block
    raw = rep.get("raw") or {}
    block.has_data = True
    block.stage = rep.get("stage", "")
    block.narrative = rep.get("narrative", "")
    block.bottlenecks = raw.get("bottlenecks", []) or []
    block.candidates = raw.get("candidates", []) or []
    block.downgraded = raw.get("downgraded_themes", []) or []
    block.gaps = raw.get("gaps", []) or []
    return block



def produce() -> InvestmentDecisionMemo:
    """CIO Agent 的主产出。Trading OS 模式。"""
    brain, tree = _load_data()
    now = datetime.datetime.now()

    memo = InvestmentDecisionMemo()
    # 报告日 = 真实交易日（修复『报告日落后 latest_date』根因 bug）
    memo.trade_date = _report_date()
    memo.generated_at = now.isoformat(timespec="seconds")

    decision = brain.get("decision", {})
    # ★ 投资委员会（IC）为唯一权威决策出口：can_buy / 方向 / 仓位 / 主要逻辑 / 风险
    committee = brain.get("committee") or decision or {}
    # 仓位护栏必须反映最新学习反哺：brain["committee"] 可能来自过期缓存，
    # 用当日最新 learning_feedback 重算 position_pct（can_buy 不受 pos_scale 影响，保持不变）。
    try:
        _db = _build_debate_block(brain)
        if _db.get("position_pct"):
            committee = dict(committee)
            committee["position_pct"] = _db["position_pct"]
            committee["learning_note"] = _db.get("learning_note")
    except Exception:
        pass
    memo.can_buy = committee.get("can_buy", "UNKNOWN")
    memo.position_pct = committee.get("position_pct", "")
    memo.committee = committee
    memo.confidence_overall = brain.get("confidence", {}).get("overall", 0)

    # ── 安检清单（保留为信息性子检查，不再覆盖 IC 权威决策）──
    memo.preflight = _build_preflight(tree)

    # ── 数据健康体检（Data Integrity Layer 闸门：失败 → 禁止交易）──
    memo.data_health = _build_data_health()

    # ── 定性置信度（不再显示数字，显示 Bullish/原因/风险） ──
    memo.confidence_bars = {}
    results = brain.get("results", {})
    for layer_name in ["L1", "L2", "L3", "L4", "L5", "sentiment", "fundamental"]:
        layer_data = results.get(layer_name, {})
        if isinstance(layer_data, dict):
            score = layer_data.get("score", 0) or 0
            narrative = layer_data.get("narrative", "") or ""
            dir_label = "Bullish" if score >= 70 else "Neutral" if score >= 50 else "Bearish"
            memo.confidence_bars[layer_name] = {
                "direction": dir_label,
                "reason": narrative[:80] if narrative else "",
                "risk": (layer_data.get("risk_note") or "")[:60],
            }
    if not memo.confidence_bars:
        memo.confidence_bars["总体"] = {"direction": "Neutral", "reason": "数据不足", "risk": ""}

    # ── 构建各段 ──
    memo.thesis = _build_thesis(brain, tree)
    main_lines_data = _build_main_lines(tree, brain)

    memo.evidence = _build_evidence(brain, tree)
    memo.money_map = _build_money_map(tree)
    memo.main_lines = main_lines_data
    memo.trading_plan = _build_trading_plan(brain, tree, main_lines_data)
    memo.risk = _build_risk(brain, tree, main_lines_data)
    # ── ⑧ 学习进化：先回放 trade_journal（判断/执行分离），让历史块反映真实命中率 ──
    try:
        from narrative_layers import reconcile_journal
        reconcile_journal()
    except Exception:
        pass
    memo.historical = _build_historical(brain, tree)

    # ── Trading OS 新增 ──
    memo.market_structure = _build_market_structure(tree)
    memo.opportunity_cost = _build_opportunity_cost(tree, main_lines_data)
    memo.action_list = _build_action_list(tree, main_lines_data, memo.preflight)
    memo.odds_table = _build_odds_table(main_lines_data)
    memo.catalyst_calendar = _build_catalyst_calendar()
    memo.cross_asset = _build_cross_asset()
    memo.observation = _build_observations()
    memo.cro = _build_cro()

    # ── 审计升级新增（买方晨会标准）──
    memo.global_market = _build_global_market()
    memo.capital_flow = _build_capital_flow()
    memo.market_movie = _build_market_movie()
    memo.narrative = _build_narrative()
    memo.panqian = _build_panqian()
    memo.industry_chain = _build_industry_chain()

    # ── 范式转移：资金迁移块（日报第一页）──
    memo.migration = _build_migration_block()

    # ── 范式转移：因果推理块（为什么 / 产业链下钻）──
    memo.causal = _build_causal_block(memo.migration)

    # ── 范式转移：真实 IC 辩论块（L1~L8 投票裁决）──
    memo.debate = _build_debate_block(brain)

    # ── 范式转移：情景推演块（明日最大摆动变量 → 条件分支）──
    memo.scenario = _build_scenario_block()

    # ── 范式转移：学习复盘块（预测日志 + T+1 回放 + 模式成败率）──
    # 先记录当日完整预测（幂等：同日 produce 不重复），再构建复盘块
    try:
        _log_prediction(memo)
    except Exception:
        pass
    memo.learning = _build_learning_block()

    # ── 取精华：移植自 AI-Portfolio-Compass（MIT）──
    memo.position_layer = _build_position_layer_block()
    memo.trade_review = _build_trade_review_block()
    memo.freshness = _build_freshness_block()
    memo.action_cards = _build_action_cards_block(memo)

    # ── ⑧ 交易日志通电：把当日系统判断自动落库为 signal 记录（判断侧）──
    try:
        from narrative_layers import log_daily_signals
        memo.journal_logged = log_daily_signals(memo)
    except Exception:
        pass

    return memo


def _build_migration_block() -> dict:
    """调用资金迁移引擎，失败时降级为空块，绝不让日报崩溃。"""
    try:
        return _build_capital_migration()
    except Exception as e:  # noqa
        return {
            "trade_date": "", "rating": 0,
            "thesis": f"（资金迁移引擎暂不可用：{e}）",
            "has_history": False, "sector_theme": "", "diverge": "",
            "rotation": {"out_top": [], "in_top": [], "reversal_in": [],
                         "sustained_in": [], "chains": [], "detail": []},
            "cross_asset": {"sentence": "", "signals": [], "themes": {}, "consensus": ""},
            "falsification": [], "what_to_do": "", "focus": "", "avoid": "",
        }


def _build_causal_block(migration: dict) -> dict:
    """调用因果推理引擎（为什么 / 产业链下钻），失败时降级为空块。"""
    try:
        mig = migration or {}
        focus = []
        if mig.get("focus"):
            focus.append(mig["focus"])
        focus += (mig.get("rotation", {}) or {}).get("in_top", [])[:3]
        # 去重保序
        seen, uniq = set(), []
        for s in focus:
            if s and s not in seen:
                seen.add(s); uniq.append(s)
        from causal_reasoning import build as _causal_build
        return _causal_build(focus_sectors=uniq[:4] if uniq else None)
    except Exception as e:  # noqa
        return {
            "trade_date": "", "focus": [], "causes": {}, "chain_insights": {},
            "unknown_list": [], "news_count": 0,
            "error": f"（因果推理引擎暂不可用：{e}）",
        }


def _build_debate_block(brain: dict) -> dict:
    """调用投资委员会（真实 IC 辩论），失败时降级为空块。"""
    try:
        results = (brain or {}).get("results", {})
        conflicts = (brain or {}).get("conflicts", []) or []
        confidence = (brain or {}).get("confidence", {}) or {}
        # 始终用最新的学习反哺信号：learning_log 每日变化，brain_report.json 缓存可能过期，
        # 若依赖旧缓存会导致「IC 命中率已下降但仓位护栏未收紧」的失真。缓存仅作兜底。
        try:
            from learning_feedback import learning_feedback
            feedback = learning_feedback()
        except Exception:
            feedback = (brain or {}).get("learning_feedback", {}) or {}
        d = _ic_decide(results, conflicts, confidence, feedback)
        return {
            "can_buy": d.get("can_buy"),
            "direction": d.get("direction"),
            "position_pct": d.get("position_pct"),
            "debate": d.get("debate", []),
            "weighted_vote": d.get("weighted_vote", {}),
            "verdict": d.get("verdict", ""),
            "hard_no": d.get("hard_no", []),
        }
    except Exception as e:  # noqa
        return {
            "can_buy": "", "direction": "", "position_pct": "",
            "debate": [], "weighted_vote": {}, "verdict": "",
            "hard_no": [],
            "error": f"（投资委员会辩论引擎暂不可用：{e}）",
        }


def _build_scenario_block() -> dict:
    """调用情景推演引擎（明日最大摆动变量 → 条件分支），失败时降级为空块。"""
    try:
        return _build_scenario()
    except Exception as e:  # noqa
        return {
            "trade_date": "", "variables": [], "summary": "",
            "key_switches": [], "n_variables": 0,
            "error": f"（情景推演引擎暂不可用：{e}）",
        }


def _build_learning_block() -> dict:
    """调用学习复盘中心（预测日志 + T+1 回放 + 模式成败率），失败时降级为空块。"""
    try:
        return _build_learning()
    except Exception as e:  # noqa
        return {
            "trade_date": "", "n_predictions": 0, "n_replayed": 0,
            "ic_accuracy": None, "scenario_accuracy": None,
            "patterns": [], "recent": [],
            "self_note": "学习复盘中心暂不可用，系统继续积累预测样本。",
            "low_sample": True, "min_replay": 3,
            "error": f"（学习复盘引擎暂不可用：{e}）",
        }


def _build_position_layer_block() -> dict:
    """调用持仓分层引擎（移植 AI-Portfolio-Compass classifier，MIT）。失败时降级。"""
    try:
        return _build_position_layer()
    except Exception as e:  # noqa
        return {"has_data": False, "n_holdings": 0, "holdings": [],
                "layer_distribution": {}, "weight_by_layer": {}, "overrides": {},
                "summary": f"（持仓分层引擎暂不可用：{e}）"}


def _build_trade_review_block() -> dict:
    """调用交易复盘纪律引擎（移植 AI-Portfolio-Compass trade_review，MIT）。失败时降级。"""
    try:
        return _build_trade_review()
    except Exception as e:  # noqa
        return {"has_data": False, "n_trades": 0, "reviews": [], "stats": {},
                "summary": f"（交易复盘引擎暂不可用：{e}）"}


def _build_freshness_block() -> dict:
    """调用数据新鲜度矩阵（移植 AI-Portfolio-Compass freshness，MIT）。失败时降级。"""
    try:
        return _build_freshness()
    except Exception as e:  # noqa
        return {"health": "UNKNOWN", "matrix": [], "alerts": [],
                "summary": f"（数据新鲜度引擎暂不可用：{e}）"}


def _build_action_cards_block(memo) -> dict:
    """调用今日行动清单卡聚合（DecisionCard 风格，零LLM）。失败时降级。"""
    try:
        return _build_action_cards(memo)
    except Exception as e:  # noqa
        return {"recommendation": "观望", "confidence": "低", "priority": "P2",
                "reasons": ["行动卡聚合失败"], "risks": [str(e)],
                "key_prices": [], "action_required": ["维持观望"],
                "holding_actions": [], "review_actions": []}


# ═══════════════════════════════════════════════════════
#  CLI 测试
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    memo = produce()
    print(f"═══ 投资决策备忘录 {memo.trade_date} ═══")
    print(f"决策: {memo.can_buy}  置信度: {memo.confidence_overall}%")
    print()
    print(f"【① 核心观点】{memo.thesis.conviction}确信度")
    print(f"  {memo.thesis.headline}")
    if memo.thesis.global_a_share_link:
        print(f"  全球关联: {memo.thesis.global_a_share_link[:200]}")
    print()
    print(f"【② 证据链】{len(memo.evidence.claims)}个主张")
    for c in memo.evidence.claims:
        print(f"  [{c['type']}] {c['claim'][:80]}")
        print(f"          → {c['evidence'][:100]}")
    if memo.evidence.uncertainty:
        print(f"  不确定: {memo.evidence.uncertainty[0][:120]}")
    if memo.evidence.cross_layer_conflicts:
        for cf in memo.evidence.cross_layer_conflicts:
            print(f"  {cf[:150]}")
    print()
    print(f"【③ 资金地图】{memo.money_map.pattern}")
    print(f"  {memo.money_map.migration_narrative}")
    for td in memo.money_map.time_dimension[:3]:
        print(f"    {td['sector']}: 5日{td['trend_5d']} 20日{td['trend_20d']}{' ⚡拐点' if td['inflection'] else ''}")
    if memo.money_map.inflection_signals:
        for sig in memo.money_map.inflection_signals[:2]:
            print(f"  → {sig}")
    print()
    print(f"【④ 投资主线】{len(memo.main_lines)}条")
    for ml in memo.main_lines[:5]:
        stars = "★" * ml.star_rating + "☆" * (5 - ml.star_rating)
        chain = f" ({ml.chain_position})" if ml.chain_position else ""
        print(f"  {stars} {ml.sector}: {ml.stage}({ml.persistence}){chain}")
    print()
    print(f"【⑤ 交易计划】")
    if memo.trading_plan.no_opportunity:
        print(f"  无机会: {memo.trading_plan.no_opportunity_reason[:150]}")
    else:
        for op in memo.trading_plan.opportunities:
            print(f"  {op['tier']}级: {op['name']}")
            print(f"    条件: {'; '.join(op['conditions'][:2])}")
            print(f"    放弃: {'; '.join(op['give_up'][:2])}")
    print()
    print(f"【⑥ 风险与反例】")
    print(f"  最大风险: {memo.risk.biggest_risk[:150]}")
    for f in memo.risk.falsification[:3]:
        print(f"  → {f['scenario'][:100]}: 如果「{f['if_condition'][:60]}」→ {f['then_conclusion'][:80]}")
    print()
    print(f"【⑦ 历史经验】")
    print(f"  {memo.historical.conclusion}")
    print()
    print(f"【🎯 今日行动清单卡（DecisionCard · MIT移植）】")
    ac = memo.action_cards
    print(f"  建议: {ac.get('recommendation')} | 置信: {ac.get('confidence')} | 优先级: {ac.get('priority')}")
    for a in ac.get("action_required", [])[:6]:
        print(f"    • {a}")
    print()
    print(f"【🗂 持仓分层（MIT移植）】{memo.position_layer.get('summary','')[:160]}")
    print(f"【🔁 交易复盘（MIT移植）】{memo.trade_review.get('summary','')[:160]}")
    print(f"【🩺 数据新鲜度（MIT移植）】{memo.freshness.get('summary','')[:160]}")
