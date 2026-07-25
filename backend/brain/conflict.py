# -*- coding: utf-8 -*-
"""
跨层冲突检测：总指挥的"矛盾检查器"。

用户核心批评之一：原来八层是平行模块，会各说各话（如全球避险却建议重仓）。
这里让上下文里的各层方向信号互相校验，任何打架都显式暴露出来，
既给用户警示，也作为拉低总置信度的依据。

每条冲突：{rule, severity(HIGH/MEDIUM/LOW), layers, desc}
"""
from .context import ReasoningContext  # noqa


def _dir(ctx, layer):
    return (ctx.get(layer) or {}).get("signal", {}).get("direction")


def _pos_bucket(pos):
    if not pos:
        return "low"
    if "80%" in pos or "100%" in pos:
        return "high"
    if "50%" in pos:
        return "mid"
    return "low"


def detect(ctx):
    conflicts = []
    l7 = ctx.get("L7") or {}
    pos = (l7.get("raw") or {}).get("position", "")
    pos_b = _pos_bucket(pos)

    # 1. 全球避险 vs 高仓位
    if _dir(ctx, "L1") in ("bearish", "bearish_weak") and pos_b in ("mid", "high"):
        conflicts.append({"rule": "全球避险 ↔ 高仓位", "severity": "HIGH",
                          "layers": ["L1", "L7"],
                          "desc": f"L1 外围{_dir(ctx,'L1')}，但 L7 风险预算仍给 {pos}，方向矛盾，应降仓。"})

    # 2. 紧货币+紧信用（防御）vs 进攻
    if _dir(ctx, "L2") == "bearish":
        conflicts.append({"rule": "紧缩环境 ↔ 进攻", "severity": "MEDIUM",
                          "layers": ["L2", "L7"],
                          "desc": "L2 处于紧货币+紧信用（防御格局），不宜积极进攻。"})

    # 3. 主线拥挤（高潮+退潮占比高）vs 激进
    l4raw = (ctx.get("L4") or {}).get("raw") or {}
    dist = l4raw.get("stage_distribution") or {}
    tot = sum(dist.values()) or 1
    late = dist.get("高潮", 0) + dist.get("退潮", 0)
    if tot and late / tot > 0.5:
        conflicts.append({"rule": "主线拥挤 ↔ 激进", "severity": "HIGH",
                          "layers": ["L4", "L7"],
                          "desc": f"L4 主线中高潮+退潮占比 {round(late/tot*100)}%，已拥挤/退潮，不宜追高。"})

    # 4. 情绪退潮/冰点 vs 买入
    st = (ctx.get("sentiment") or {}).get("signal", {}).get("state")
    if st in ("退潮", "冰点"):
        conflicts.append({"rule": "情绪退潮 ↔ 买入", "severity": "HIGH",
                          "layers": ["sentiment"],
                          "desc": f"情绪验证为「{st}」，亏钱效应扩散，不宜买入。"})

    # 5. 产业未被资金验证 vs 强买入
    l3raw = (ctx.get("L3") or {}).get("raw") or {}
    top = l3raw.get("top_industries") or []
    if top and not any(t.get("confirmed") for t in top):
        conflicts.append({"rule": "产业未验证 ↔ 强买入", "severity": "MEDIUM",
                          "layers": ["L3", "L7"],
                          "desc": "L3 主导产业均未被资金板块验证（潜伏），交易上应等确认再介入。"})

    # 5b. L3.5 产业链推理：蹭热点降级 vs L4 强共识
    l35raw = (ctx.get("L3_5") or {}).get("raw") or {}
    downgraded = l35raw.get("downgraded_themes") or []
    if downgraded and _dir(ctx, "L4") in ("bullish", "neutral_bullish"):
        conflicts.append({"rule": "蹭热点降级 ↔ L4强共识", "severity": "MEDIUM",
                          "layers": ["L3_5", "L4"],
                          "desc": f"L3.5 将 {len(downgraded)} 个盘前热榜主题降级（缺资金验证/产业链瓶颈支撑），"
                                  f"但 L4 板块共识偏多，需甄别是真主线还是情绪蹭热度。"})

    # 6. 基本面估值偏高·业绩疲软 vs 重仓
    fundraw = (ctx.get("fundamental") or {}).get("raw") or {}
    fsectors = fundraw.get("sectors") or []
    over = [s for s in fsectors if "估值偏高" in (s.get("verdict") or "")]
    driven = [s for s in fsectors if s.get("verdict") == "业绩驱动"]
    if over and not driven and pos_b in ("mid", "high"):
        conflicts.append({"rule": "估值偏高 ↔ 重仓", "severity": "MEDIUM",
                          "layers": ["fundamental", "L7"],
                          "desc": f"验证主线中 {len(over)} 个板块估值偏高且业绩未跟上，重仓风险大。"})

    # 7. 龙头缺失 vs 买入
    l5raw = (ctx.get("L5") or {}).get("raw") or {}
    if not l5raw.get("leaders"):
        conflicts.append({"rule": "龙头缺失 ↔ 买入", "severity": "MEDIUM",
                          "layers": ["L5"],
                          "desc": "L5 未确认任何板块龙头，缺代表性标的，难以形成一致预期。"})

    # 8. 黄金周期过热 ↔ 高仓位
    gold = ctx.get("GOLD") or {}
    gold_raw = gold.get("raw") or {}
    gold_cycle = gold_raw.get("cycle") or {}
    gold_phase = gold_cycle.get("current_phase", "")
    if gold_phase in ("euphoria", "correction") and pos_b in ("mid", "high"):
        conflicts.append({"rule": "黄金周期过热 ↔ 高仓位", "severity": "MEDIUM",
                          "layers": ["GOLD", "L7"],
                          "desc": f"黄金处于「{gold_phase}」阶段，通常预示调整风险，高仓位需谨慎。"})

    # 9. 黄金与美元的异常背离（弱美元理应支撑黄金）
    gold_signal = gold.get("signal", {}) or {}
    gold_dir = gold_signal.get("direction", "")
    if gold_dir == "bearish" and _dir(ctx, "L1") == "bearish":
        # 两者都 bearish 是正常的（强美元+弱黄金），不冲突
        pass
    elif gold_dir == "bearish" and _dir(ctx, "L1") in ("bullish", "neutral_bullish"):
        conflicts.append({"rule": "黄金走弱 ↔ 美元走弱", "severity": "LOW",
                          "layers": ["GOLD", "L1"],
                          "desc": "黄金与美元同步走弱属异常背离，需关注是否受其他因子（如利率）主导。"})

    # 10. 黄金强烈避险叙事 vs 权益市场乐观
    gold_narrative = gold_raw.get("narrative") or {}
    gold_theme = gold_narrative.get("primary_theme", "")
    if "避险" in str(gold_theme) and _dir(ctx, "sentiment") not in ("退潮", "冰点"):
        # 黄金说避险，但A股情绪正常 → 低级别注意
        pass  # 不同市场，暂不告警

    # 11. 资金面流出 ↔ 全球宏观乐观（FLOW bearish vs L1 bullish）
    flow = ctx.get("FLOW") or {}
    flow_dir = (flow.get("signal") or {}).get("direction", "")
    if flow_dir == "bearish" and _dir(ctx, "L1") in ("bullish", "neutral_bullish"):
        conflicts.append({"rule": "资金流出 ↔ 宏观乐观", "severity": "HIGH",
                          "layers": ["FLOW", "L1"],
                          "desc": "资金情报显示流出（Flow Score偏低），但 L1 全球宏观偏乐观，方向矛盾。"})
    elif flow_dir == "bullish" and _dir(ctx, "L1") == "bearish":
        conflicts.append({"rule": "资金流入 ↔ 宏观悲观", "severity": "MEDIUM",
                          "layers": ["FLOW", "L1"],
                          "desc": "资金情报显示流入，但 L1 全球宏观悲观，需确认资金流向的持续性。"})

    # 12. ETF 赎回潮 ↔ 高仓位（资金撤离权益工具）
    flow_raw = flow.get("raw") or {}
    etf_sum = (flow_raw.get("etf_flow") or {}).get("total_main_inflow", 0)
    if etf_sum and etf_sum < -5e8 and pos_b in ("mid", "high"):
        conflicts.append({"rule": "ETF赎回潮 ↔ 高仓位", "severity": "MEDIUM",
                          "layers": ["FLOW", "L7"],
                          "desc": f"ETF 主力净流出 {abs(etf_sum)/1e8:.0f}亿，权益工具遭赎回，高仓位需谨慎。"})

    # 13. 商品 risk_off ↔ A股进攻
    flow_signal = flow.get("signal") or {}
    if flow_signal.get("risk_appetite") == "risk_off" and _dir(ctx, "L4") in ("bullish", "neutral_bullish"):
        conflicts.append({"rule": "商品避险 ↔ A股进攻", "severity": "MEDIUM",
                          "layers": ["FLOW", "L4"],
                          "desc": "商品市场风险偏好下降（risk-off），但 A 股板块共识偏多，需警惕联动风险。"})

    return conflicts
