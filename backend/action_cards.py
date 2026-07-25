# -*- coding: utf-8 -*-
"""
action_cards.py —— 今日行动清单卡 / DecisionCard（Personal AI Research System）
================================================================================

移植自开源项目 AI-Portfolio-Compass（MIT License,
https://github.com/Elian-dan/AI-Portfolio-Compass-public）的
`backend/app/models.py` 中 **DecisionCard** schema 的思想：

    recommendation / confidence / reasons / risks / key_prices /
    action_required / priority

但原项目的 DecisionCard 由 LLM 生成（带"推断"性质）。我们做"取其精华去其糟粕"：
  - 精华：这个 *结构化今日行动卡* 的字段设计非常适合作为日报第一页的
    "我怎么办"。我们保留字段结构。
  - 去糟粕：我们**不**用 LLM 编一张卡，而是把前面 4 个规则引擎
    （资金迁移 / 真实 IC 辩论 / 情景推演 / 持仓分层 / 交易复盘）的结论
    **聚合**成一张事实驱动的卡。每一个 action_required 都能回溯到某个
    规则引擎的输出，绝不凭空生成。
  - 数据源：来自本系统已有引擎，零新增外部依赖。

输入：CIO produce() 组装好的 memo（含 migration / debate / scenario /
      position_layer / trade_review 等 dict 字段）。
输出：build(memo) -> DecisionCard 风格 dict。
"""
from __future__ import annotations

import datetime


def _can_buy_to_reco(can_buy: str) -> str:
    return {"YES": "进攻", "CAUTION": "结构性机会·谨慎",
            "NO": "不交易", "UNKNOWN": "观望"}.get(can_buy, "观望")


def build(memo) -> dict:
    """把多条规则引擎结论聚合成一张今日行动卡。memo 为 InvestmentDecisionMemo。"""
    migration = getattr(memo, "migration", None) or {}
    debate = getattr(memo, "debate", None) or {}
    scenario = getattr(memo, "scenario", None) or {}
    position_layer = getattr(memo, "position_layer", None) or {}
    trade_review = getattr(memo, "trade_review", None) or {}

    can_buy = getattr(memo, "can_buy", "UNKNOWN")
    conf = getattr(memo, "confidence_overall", 0)

    # ── 1. 总建议 + 优先级 ──
    recommendation = _can_buy_to_reco(can_buy)
    hard_no = debate.get("hard_no") or []
    priority = "P0" if can_buy == "NO" else ("P1" if can_buy == "CAUTION" else "P1")

    # ── 2. reasons（聚合各引擎支持/反对）──
    reasons = []
    if migration.get("thesis"):
        reasons.append(f"资金迁移：{migration['thesis'][:90]}")
    if debate.get("verdict"):
        reasons.append(f"投资委员会：{debate['verdict'][:90]}")
    if scenario.get("summary"):
        reasons.append(f"情景：{scenario['summary'][:90]}")
    if not reasons:
        reasons.append("各引擎暂无明确结论，按观望处理。")

    # ── 3. risks（来自辩论反对票 + 情景失效开关 + 复盘止损拖延）──
    risks = []
    for d in (debate.get("debate") or []):
        if d.get("stance") == "oppose" and d.get("argument"):
            risks.append(f"反对意见：{d['argument'][:80]}")
    for sw in (scenario.get("key_switches") or []):
        if isinstance(sw, str):
            risks.append(f"失效开关：{sw[:80]}")
    if trade_review.get("stop_delay_examples"):
        ex = trade_review["stop_delay_examples"][0]
        risks.append(f"止损拖延：{ex['name'] or ex['code']} 浮亏{ex['ret_latest']}% 未处理")
    if not risks:
        risks.append("暂无明显反对信号。")

    # ── 4. key_prices（关键观察位：主线/情景赢家）──
    key_prices = []
    focus = migration.get("focus") or ""
    if focus:
        key_prices.append(f"主线「{focus}」：明日开盘须维持资金净流入第一")
    for v in (scenario.get("variables") or [])[:2]:
        winners = v.get("winners") or []
        losers = v.get("losers") or []
        if winners:
            key_prices.append(f"若{v.get('name','')}超预期 → 看多：{'、'.join(winners[:3])}")
        if losers:
            key_prices.append(f"若{v.get('name','')}落空 → 回避：{'、'.join(losers[:3])}")

    # ── 5. action_required（今日必做，按优先级）──
    action_required = []
    if can_buy == "NO":
        action_required.append("【P0】今日不交易。只做复盘与观察，等待条件满足。")
    # 来自持仓分层：遗留/短线处置
    if position_layer.get("has_data"):
        for h in position_layer.get("holdings", [])[:6]:
            if h["layer"] == "遗留观察仓" and h["pl_ratio"] <= -15:
                action_required.append(f"【P1】处理遗留仓 {h['name']}（浮亏{h['pl_ratio']}%，"
                                        f"持有{h['data_days']}天）：要么加仓摊薄、要么止损，勿长期挂着。")
            if h["layer"] == "短期交易仓":
                action_required.append(f"【P2】短线仓 {h['name']}：设好止盈/止损，避免做成长期。")
    # 来自交易复盘：卖飞/追高反思
    if trade_review.get("has_data"):
        for r in trade_review.get("reviews", [])[:3]:
            if r["label"] in ("卖飞", "买到短线高位", "止损拖延"):
                action_required.append(f"【P1】复盘 {r['name'] or r['code']}：{r['label']}"
                                        f"（{r['note']}）")
    # 来自迁移：focus 板块条件
    if migration.get("what_to_do"):
        action_required.append(f"【P1】{migration['what_to_do'][:100]}")
    # 来自情景：最大摆动变量
    for v in (scenario.get("variables") or [])[:1]:
        if v.get("base_probability") is not None:
            action_required.append(f"【P2】盯紧「{v.get('name','')}」："
                                    f"基准概率{v['base_probability']*100:.0f}%，"
                                    f"结果公布前后降低仓位暴露。")
    if not action_required:
        action_required.append("【P2】无明显行动信号，维持现有仓位，盘中复核主线资金方向。")

    # ── 6. holding_actions / review_actions（明细）──
    holding_actions = []
    if position_layer.get("has_data"):
        for h in position_layer.get("holdings", []):
            if h["layer"] == "核心长期仓":
                holding_actions.append(f"{h['name']}：核心长期，忽略短期波动，按定投/持有。")
            elif h["layer"] == "中期配置仓":
                holding_actions.append(f"{h['name']}：中期配置，到达目标价可部分了结。")
            elif h["layer"] == "短期交易仓":
                holding_actions.append(f"{h['name']}：短线，严格止损，不恋战。")
            elif h["layer"] == "遗留观察仓":
                holding_actions.append(f"{h['name']}：遗留，制定明确的去留计划。")
    review_actions = []
    if trade_review.get("has_data"):
        for r in trade_review.get("reviews", [])[:5]:
            review_actions.append(f"{r['name'] or r['code']}（{r['side']} {r['deal_time']}）："
                                   f"{r['label']} — {r['note']}")

    # 置信度定性
    conf_label = "高" if conf >= 65 else ("中" if conf >= 45 else "低")

    return {
        "recommendation": recommendation,
        "confidence": conf_label,
        "priority": priority,
        "can_buy": can_buy,
        "reasons": reasons,
        "risks": risks,
        "key_prices": key_prices,
        "action_required": action_required,
        "holding_actions": holding_actions,
        "review_actions": review_actions,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    import pprint
    # 独立测试需要一个 mock memo；此处仅打印 schema 说明
    pprint.pprint({
        "schema": ["recommendation", "confidence", "priority", "can_buy",
                   "reasons", "risks", "key_prices", "action_required",
                   "holding_actions", "review_actions"],
    })
