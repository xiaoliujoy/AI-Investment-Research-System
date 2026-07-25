# -*- coding: utf-8 -*-
"""
Market Narrative Intelligence Engine
=====================================
市场叙事引擎：从跨资产价格变动推断市场在交易什么叙事，
拆解事实 vs 推断，验证因果链，生成反事实分析。

回答五个日常问题：
1. 今天市场在交易什么叙事（Narrative）？
2. 这个叙事的证据有哪些？哪些只是推断？
3. 市场共识已经走到什么阶段？
4. 这个叙事最可能被什么数据或事件证伪？
5. 如果叙事失效，资金最可能流向哪里？

设计原则：
  - 规则驱动（非 LLM）：可解释、可复现、无幻觉
  - 数据 best-effort：缺数据标记 gap，不阻断
  - 叙事 ≠ 因果：区分「市场在交易什么」和「什么真的导致了什么」
  - 真正的驱动变量：不停留在表面事件，指向底层驱动力
"""
from __future__ import annotations
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# ── 事件驱动日历 ──
try:
    from catalyst_calendar import run as _catalyst_run
    _HAS_CALENDAR = True
except Exception:
    _HAS_CALENDAR = False


def _safe_catalysts(narrative_id):
    """安全获取 catalyst 列表，失败返回空列表。"""
    if not _HAS_CALENDAR:
        return []
    try:
        cat = _catalyst_run(narrative_id, days_ahead=14)
        return cat.get("upcoming_catalysts", [])
    except Exception:
        return []

# ── 显著性阈值 ──
MOVE_THRESHOLD = 1.0      # |涨跌幅| > 1% 视为显著
EXTREME_THRESHOLD = 3.0   # |涨跌幅| > 3% 视为极端

# ═══════════════════════════════════════════════════════
#  叙事模式库
#  每个模式定义：触发条件 → 因果链 → 置信度 → 最弱环节 → 反事实
# ═══════════════════════════════════════════════════════

NARRATIVE_PATTERNS = [
    # ── 1. 通胀恐慌 ──
    {
        "id": "inflation_fear",
        "name": "通胀恐慌",
        "name_en": "Inflation Fear",
        "headline_template": "市场在交易「战争→油价→通胀→加息」链，而非避险",
        "triggers": {
            "oil": "up",
            "gold": "down",
            "btc": "down",
            "usd": "up",
        },
        "chain": [
            {"step": "地缘事件 / 供给冲击", "type": "event", "verifiable": True,  "confidence": 0.95},
            {"step": "油价上涨",            "type": "data",   "verifiable": True,  "confidence": 0.95},
            {"step": "通胀预期上升",        "type": "inference", "verifiable": False, "confidence": 0.80},
            {"step": "加息预期增强",        "type": "inference", "verifiable": True,  "confidence": 0.60},
            {"step": "实际利率上升",        "type": "inference", "verifiable": True,  "confidence": 0.85},
            {"step": "黄金 / BTC / 成长股下跌", "type": "data", "verifiable": True,  "confidence": 0.90},
        ],
        "weakest_link": "通胀预期 → 加息预期",
        "weakest_reason": (
            "若就业恶化或经济快速衰退，即使油价上涨，Fed 也可能按兵不动。"
            "需同时关注就业、PMI、失业率，而非只看油。"
        ),
        "true_driver": "美国实际利率（10Y TIPS），而非战争本身",
        "counterfactual": {
            "condition": "CPI 低于预期 / 非农就业走弱 / ISM PMI 跌破荣枯线",
            "flow": "美元下跌 → 黄金反弹 → BTC 反弹 → 纳指反弹 → 整个逻辑链反转",
        },
        "consensus_note": "若所有分析师都在喊「通胀→加息」，一致性过高，反转风险增大。",
        "a_share_impact": "全球加息预期 → 外资流出压力 → A 股成长股承压、防御/资源板块相对占优",
    },
    # ── 2. 避险交易 ──
    {
        "id": "risk_off",
        "name": "避险交易",
        "name_en": "Risk-Off",
        "headline_template": "市场在交易「地缘风险→避险」，而非通胀",
        "triggers": {
            "gold": "up",
            "btc": "down",
            "usd": "up",
            "equity": "down",
        },
        "chain": [
            {"step": "地缘风险 / 黑天鹅事件",  "type": "event", "verifiable": True,  "confidence": 0.95},
            {"step": "风险偏好下降 (VIX↑)",   "type": "inference", "verifiable": True, "confidence": 0.85},
            {"step": "避险资产上涨 (黄金/美元)", "type": "data", "verifiable": True,  "confidence": 0.90},
            {"step": "风险资产下跌 (BTC/股票)",  "type": "data", "verifiable": True,  "confidence": 0.90},
        ],
        "weakest_link": "避险持续时间",
        "weakest_reason": "地缘风险消退后避险买盘迅速反转，黄金可能回落。避险交易通常持续数天到数周。",
        "true_driver": "VIX 与风险偏好，而非单一地缘事件",
        "counterfactual": {
            "condition": "地缘局势缓和 / 避险情绪消退",
            "flow": "黄金回落 → 风险资产反弹 → USD 走弱 → VIX 回落",
        },
        "consensus_note": "避险交易持续时间短，追高避险资产风险大。",
        "a_share_impact": "外资流出 → A 股短期承压，但避险情绪消退后往往有反弹",
    },
    # ── 3. 流动性扩张 ──
    {
        "id": "liquidity_expansion",
        "name": "流动性扩张",
        "name_en": "Liquidity Expansion",
        "headline_template": "市场在交易「宽松预期→流动性扩张」，风险与避险资产同涨",
        "triggers": {
            "gold": "up",
            "btc": "up",
            "equity": "up",
            "usd": "down",
        },
        "chain": [
            {"step": "货币政策宽松预期 / 降息信号",     "type": "event", "verifiable": True,  "confidence": 0.85},
            {"step": "流动性扩张预期",                 "type": "inference", "verifiable": False, "confidence": 0.90},
            {"step": "风险资产上涨 (股票 / BTC)",       "type": "data", "verifiable": True,  "confidence": 0.85},
            {"step": "避险资产同步上涨 (黄金)",         "type": "data", "verifiable": True,  "confidence": 0.80},
        ],
        "weakest_link": "宽松预期是否兑现",
        "weakest_reason": "若通胀反弹或经济数据超预期，Fed 可能维持鹰派，宽松预期落空。",
        "true_driver": "央行资产负债表 / 流动性预期",
        "counterfactual": {
            "condition": "通胀超预期 / Fed 鹰派表态",
            "flow": "风险资产回调 → 美元反弹 → 黄金回落 → BTC 下跌",
        },
        "consensus_note": "流动性扩张叙事下，黄金和 BTC 同涨是关键信号（区别于避险模式）。",
        "a_share_impact": "全球流动性扩张 → 外资流入 → A 股成长/券商占优",
    },
    # ── 4. 衰退交易 ──
    {
        "id": "recession_trade",
        "name": "衰退交易",
        "name_en": "Recession Trade",
        "headline_template": "市场在交易「经济衰退→降息预期」，商品跌、黄金涨、股票跌",
        "triggers": {
            "oil": "down",
            "gold": "up",
            "equity": "down",
            "usd": "down",
        },
        "chain": [
            {"step": "经济数据恶化 (PMI / 就业)",       "type": "event", "verifiable": True,  "confidence": 0.90},
            {"step": "衰退预期上升",                   "type": "inference", "verifiable": False, "confidence": 0.85},
            {"step": "降息预期增强",                   "type": "inference", "verifiable": True,  "confidence": 0.80},
            {"step": "风险资产下跌 / 避险上涨",        "type": "data", "verifiable": True,  "confidence": 0.85},
        ],
        "weakest_link": "衰退预期 → 降息预期",
        "weakest_reason": "若通胀粘性较强，Fed 可能在衰退中维持高利率，降息预期落空。",
        "true_driver": "PMI / 就业数据与 Fed 反应函数",
        "counterfactual": {
            "condition": "经济数据超预期反弹",
            "flow": "风险资产反弹 → 黄金回落 → 油价反弹 → 美元走强",
        },
        "consensus_note": "衰退交易中黄金表现取决于实际利率走向，并非纯粹避险。",
        "a_share_impact": "全球衰退 → 出口链承压 → A 股防御/内需板块占优",
    },
    # ── 5. 成长股抛售 ──
    {
        "id": "growth_selloff",
        "name": "成长股抛售",
        "name_en": "Growth Selloff",
        "headline_template": "市场在交易「利率上升→成长股估值杀」，科技/BTC 跌、黄金稳",
        "triggers": {
            "equity": "down",
            "btc": "down",
            "gold": "up",
        },
        "chain": [
            {"step": "利率上升 / 估值压力",            "type": "event", "verifiable": True,  "confidence": 0.85},
            {"step": "高估值成长股承压",              "type": "inference", "verifiable": True,  "confidence": 0.85},
            {"step": "科技股 / BTC 下跌",             "type": "data", "verifiable": True,  "confidence": 0.90},
            {"step": "资金转向防御 / 价值",           "type": "inference", "verifiable": True,  "confidence": 0.75},
        ],
        "weakest_link": "利率上升 → 成长股下跌",
        "weakest_reason": "若盈利增长强劲，成长股可在高利率环境下维持估值。",
        "true_driver": "实际利率与企业盈利",
        "counterfactual": {
            "condition": "盈利超预期 / Fed 暗示降息",
            "flow": "科技股反弹 → BTC 反弹 → 价值股相对走弱",
        },
        "consensus_note": "成长股抛售的深度取决于盈利前景，而非纯粹利率。",
        "a_share_impact": "A 股科技/半导体承压，资金可能转向高股息/消费",
    },
    # ── 6. 商品超级周期 ──
    {
        "id": "commodity_supercycle",
        "name": "商品超级周期",
        "name_en": "Commodity Supercycle",
        "headline_template": "市场在交易「供给约束→商品全面上涨」，油金铜齐涨、美元跌",
        "triggers": {
            "oil": "up",
            "gold": "up",
            "copper": "up",
            "usd": "down",
        },
        "chain": [
            {"step": "供给约束 / 需求复苏",           "type": "event", "verifiable": True,  "confidence": 0.85},
            {"step": "商品全面上涨",                  "type": "data", "verifiable": True,  "confidence": 0.95},
            {"step": "通胀预期上升",                  "type": "inference", "verifiable": False, "confidence": 0.80},
            {"step": "美元走弱 (商品计价)",           "type": "data", "verifiable": True,  "confidence": 0.85},
        ],
        "weakest_link": "供给约束持续性",
        "weakest_reason": "若供给约束缓解或需求走弱，商品涨幅可能迅速回吐。",
        "true_driver": "全球供需平衡与美元周期",
        "counterfactual": {
            "condition": "供给恢复 / 全球需求走弱",
            "flow": "商品回落 → 美元反弹 → 通胀预期降温",
        },
        "consensus_note": "商品超级周期需要供给+需求双驱动，单一因素难以持续。",
        "a_share_impact": "A 股有色/煤炭/石化受益，制造业成本承压",
    },
]


# ═══════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════

def _get_move(chg_pct):
    """涨跌幅 → 方向: up / down / flat / None"""
    if chg_pct is None:
        return None
    try:
        v = float(chg_pct)
    except (TypeError, ValueError):
        return None
    if v > MOVE_THRESHOLD:
        return "up"
    if v < -MOVE_THRESHOLD:
        return "down"
    return "flat"


def _match_narrative(moves, raw_changes):
    """将检测到的资产变动匹配到叙事模式，返回得分排序的候选列表。"""
    scores = []
    for pattern in NARRATIVE_PATTERNS:
        triggers = pattern["triggers"]
        match_count = 0
        total = 0
        mismatches = []
        matched_assets = []

        for asset, direction in triggers.items():
            actual = moves.get(asset)
            if actual is None:
                # 数据缺失，不参与计分但记录
                continue
            total += 1
            if direction == "flat":
                if actual in ("flat", None):
                    match_count += 1
                    matched_assets.append(asset)
                else:
                    mismatches.append(f"{asset} 预期平稳 实际{actual}")
            elif actual == direction:
                match_count += 1
                matched_assets.append(asset)
            else:
                mismatches.append(f"{asset} 预期{direction} 实际{actual}")

        if total == 0:
            continue

        score = match_count / total
        # 惩罚 mismatch（方向完全相反的）
        penalty = len(mismatches) * 0.15
        adjusted_score = max(0, score - penalty)

        scores.append({
            "pattern": pattern,
            "score": adjusted_score,
            "raw_score": score,
            "match_count": match_count,
            "total": total,
            "mismatches": mismatches,
            "matched_assets": matched_assets,
        })

    scores.sort(key=lambda x: x["score"], reverse=True)
    return scores


def _assess_consensus_stage(raw_changes):
    """评估共识生命周期阶段。"""
    if not raw_changes:
        return "数据不足", "无法评估共识阶段"

    extreme_count = sum(
        1 for v in raw_changes.values()
        if v is not None and abs(v) > EXTREME_THRESHOLD
    )
    significant_count = sum(
        1 for v in raw_changes.values()
        if v is not None and abs(v) > MOVE_THRESHOLD
    )

    if extreme_count >= 3:
        return "过度一致（高潮区）", (
            "多个资产出现极端波动（>3%），市场一致性过高。"
            "这通常是叙事接近高潮的信号——所有人都在交易同一个故事，反转风险增大。"
        )
    if significant_count >= 4:
        return "强化中", (
            "多个资产同步确认叙事方向，共识正在强化。"
            "这是叙事最有力的阶段，但也开始接近过度一致的边界。"
        )
    if significant_count >= 2:
        return "形成中", (
            "叙事正在被市场验证，部分资产已确认方向。"
            "此时入场性价比较高，但需等待更多确认。"
        )
    return "弱信号", "跨资产变动不够一致，叙事信号较弱，可能处于板块轮动或消息真空期。"


def _build_headline_detail(pattern, moves, raw_changes):
    """构建详细的市场定价描述。"""
    parts = []
    asset_labels = {
        "oil": "原油", "gold": "黄金", "btc": "BTC",
        "usd": "美元", "equity": "美股", "copper": "铜",
    }
    for asset, direction in pattern["triggers"].items():
        chg = raw_changes.get(asset)
        if chg is not None:
            label = asset_labels.get(asset, asset)
            icon = "📈" if chg > 0 else "📉" if chg < 0 else "➡️"
            parts.append(f"{label} {icon}{chg:+.2f}%")

    moves_str = " · ".join(parts) if parts else "数据不足"
    return (
        f"{pattern['headline_template']}\n"
        f"跨资产信号：{moves_str}\n"
        f"真正的驱动变量是「{pattern['true_driver']}」，而非表面事件。"
    )


def _build_verification_table(pattern, moves, raw_changes):
    """构建「事实 vs 推断」验证表。"""
    # 资产关键词映射
    asset_keywords = {
        "oil": ["油", "原油"],
        "gold": ["黄金", "金"],
        "btc": ["BTC", "比特币"],
        "usd": ["美元", "USD"],
        "equity": ["股票", "成长股", "科技股", "纳指", "美股"],
        "copper": ["铜"],
    }
    table = []
    for link in pattern["chain"]:
        # 检查这个数据环节是否有实际数据支持
        supported = None
        if link["type"] == "data":
            supported = False
            for asset, direction in pattern["triggers"].items():
                kws = asset_keywords.get(asset, [])
                if any(kw in link["step"] for kw in kws):
                    if moves.get(asset) == direction:
                        supported = True
                        break

        table.append({
            "step": link["step"],
            "type": link["type"],
            "type_label": {"event": "事件", "data": "市场数据", "inference": "推断"}[link["type"]],
            "verifiable": link["verifiable"],
            "verifiable_label": "✅ 可验证" if link["verifiable"] else "❌ 不可验证",
            "confidence": link["confidence"],
            "confidence_label": f"{int(link['confidence'] * 100)}%",
            "supported": supported,
        })
    return table


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def analyze(market_data):
    """
    主入口：接收跨资产行情数据，返回叙事分析结果。

    market_data 可选键：
        oil:    {change_pct, price}
        gold:   {change_pct, price}
        btc:    {change_pct, price}
        usd:    {change_pct, price}  (或 dxy)
        equity: {change_pct}
        copper: {change_pct}
        vix:    float
        ust10y: float
    """
    # 1. 提取显著变动
    moves = {}
    raw_changes = {}

    for key in ("oil", "gold", "btc", "usd", "dxy", "equity", "copper"):
        val = market_data.get(key)
        if val and isinstance(val, dict):
            chg = val.get("change_pct") or val.get("chg")
            if chg is not None:
                moves[key] = _get_move(chg)
                raw_changes[key] = round(float(chg), 2) if chg is not None else None

    # dxy → usd 别名
    if "usd" not in moves and "dxy" in moves:
        moves["usd"] = moves["dxy"]
        raw_changes["usd"] = raw_changes.get("dxy")

    # 美股指数 → equity
    if "equity" not in moves:
        us_indices = market_data.get("us_indices") or []
        if us_indices:
            avg_chg = sum(
                (u.get("chg") or 0) for u in us_indices
            ) / len(us_indices)
            moves["equity"] = _get_move(avg_chg)
            raw_changes["equity"] = round(avg_chg, 2)

    # 2. 匹配叙事模式
    matches = _match_narrative(moves, raw_changes)

    # 3. 无匹配 → 返回中性结果
    if not matches or matches[0]["score"] < 0.35:
        return _build_no_narrative(moves, raw_changes, market_data)

    best = matches[0]
    pattern = best["pattern"]

    # 4. 构建因果链
    decomposition = _build_verification_table(pattern, moves, raw_changes)

    # 5. 评估共识阶段
    consensus_stage, consensus_note = _assess_consensus_stage(raw_changes)

    # 6. 构建结果
    headline = pattern["headline_template"]
    headline_detail = _build_headline_detail(pattern, moves, raw_changes)

    result = {
        "headline": headline,
        "headline_detail": headline_detail,
        "narrative_id": pattern["id"],
        "narrative_name": pattern["name"],
        "narrative_name_en": pattern["name_en"],
        "match_score": round(best["score"], 2),
        "match_count": best["match_count"],
        "match_total": best["total"],
        "mismatches": best["mismatches"],
        "alternatives": [
            {
                "name": m["pattern"]["name"],
                "score": round(m["score"], 2),
                "mismatches": m["mismatches"],
            }
            for m in matches[1:3] if m["score"] >= 0.3
        ],
        "moves": moves,
        "raw_changes": raw_changes,
        "decomposition": decomposition,
        "causal_chain": [link["step"] for link in pattern["chain"]],
        "confidence_chain": [
            {"step": link["step"], "confidence": link["confidence"]}
            for link in pattern["chain"]
        ],
        "weakest_link": pattern["weakest_link"],
        "weakest_reason": pattern["weakest_reason"],
        "true_driver": pattern["true_driver"],
        "counterfactual": pattern["counterfactual"],
        "consensus_stage": consensus_stage,
        "consensus_note": consensus_note,
        "a_share_impact": pattern.get("a_share_impact", ""),
    }

    # ── 事件驱动日历：将证伪条件映射到具体日期 ──
    if _HAS_CALENDAR:
        try:
            cat = _catalyst_run(pattern["id"], days_ahead=14)
            result["upcoming_catalysts"] = cat["upcoming_catalysts"]
            result["falsification_catalysts"] = cat["falsification_catalysts"]
            result["falsification_text"] = cat["falsification_text"]
            result["next_high_impact"] = cat["next_high_impact"]
            # 增强 q4：原始条件 + 具体日期
            orig_cond = pattern["counterfactual"]["condition"]
            q4_enhanced = orig_cond
            # 找到最相关的 catalyst（与证伪条件最匹配的）
            fals_cats = cat["falsification_catalysts"][:3]
            if fals_cats:
                date_parts = []
                for c in fals_cats:
                    d = c["days_until"]
                    if d < 0:
                        continue
                    timing = "今日" if d == 0 else "明日" if d == 1 else f"{d}天后"
                    # 解析日期
                    try:
                        import datetime as _dt
                        parsed = _dt.datetime.fromisoformat(c["expected_date"]).date()
                        date_cn = f"{parsed.month}月{parsed.day}日"
                    except Exception:
                        date_cn = c["expected_date"]
                    fields = "、".join(c["watch_fields"][:2])
                    date_parts.append(f"{c['name']}({date_cn},{timing}):关注{fields}")
                if date_parts:
                    q4_enhanced = orig_cond + "\n\n证伪窗口：\n" + "\n".join(date_parts)
            result["q4_falsification"] = q4_enhanced
        except Exception:
            result["upcoming_catalysts"] = []
            result["falsification_catalysts"] = []
            result["falsification_text"] = ""
            result["next_high_impact"] = None
    else:
        result["upcoming_catalysts"] = []
        result["falsification_catalysts"] = []
        result["falsification_text"] = ""
        result["next_high_impact"] = None

    # ── 五个日常问题 ──
    result["q1_narrative"] = headline
    result["q2_decomposition"] = decomposition
    result["q3_consensus"] = f"{consensus_stage}：{consensus_note}"
    result["q5_capital_flow"] = pattern["counterfactual"]["flow"]

    return result


def _build_no_narrative(moves, raw_changes, market_data):
    """无明确叙事时的结果。"""
    regime = market_data.get("regime", "")
    parts = []
    asset_labels = {"oil": "原油", "gold": "黄金", "btc": "BTC", "usd": "美元", "equity": "美股", "copper": "铜"}
    for asset, chg in raw_changes.items():
        label = asset_labels.get(asset, asset)
        icon = "📈" if chg > 0 else "📉" if chg < 0 else "➡️"
        parts.append(f"{label} {icon}{chg:+.2f}%")
    moves_str = " · ".join(parts) if parts else "数据不足"

    return {
        "headline": "市场缺乏明确跨资产叙事",
        "headline_detail": f"跨资产变动不够一致，难以识别单一叙事驱动。\n当前信号：{moves_str}\n可能处于板块轮动或消息真空期。",
        "narrative_id": None,
        "narrative_name": "无明确叙事",
        "narrative_name_en": "No Clear Narrative",
        "match_score": 0,
        "match_count": 0,
        "match_total": 0,
        "mismatches": [],
        "alternatives": [],
        "moves": moves,
        "raw_changes": raw_changes,
        "decomposition": [],
        "causal_chain": [],
        "confidence_chain": [],
        "weakest_link": None,
        "weakest_reason": None,
        "true_driver": None,
        "counterfactual": {"condition": "N/A", "flow": "N/A"},
        "consensus_stage": "弱信号",
        "consensus_note": "跨资产变动不够一致，不宜过度解读单日波动。",
        "a_share_impact": "",
        "upcoming_catalysts": [] if not _HAS_CALENDAR else _safe_catalysts(None),
        "falsification_catalysts": [] if not _HAS_CALENDAR else _safe_catalysts(None),
        "falsification_text": "",
        "next_high_impact": None,
        "q1_narrative": "市场缺乏明确跨资产叙事",
        "q2_decomposition": [],
        "q3_consensus": "弱信号：不宜过度解读单日波动",
        "q4_falsification": "N/A",
        "q5_capital_flow": "N/A",
    }


# ═══════════════════════════════════════════════════════
#  数据收集（复用 L1 layer1_global）
# ═══════════════════════════════════════════════════════

def collect_market_data(l1_raw=None):
    """
    从 L1 原始数据收集跨资产市场数据。

    优先使用传入的 l1_raw（避免重复网络请求）；
    若未传入，则自行调用 layer1_global()。
    """
    if l1_raw is None:
        try:
            from narrative_layers import layer1_global
            l1_raw = layer1_global()
        except Exception as e:
            return {"error": str(e), "gaps": ["layer1_global failed"]}

    data = l1_raw.get("data", {})
    gaps = l1_raw.get("gaps", [])

    market_data = {}

    # 商品（来自 macro 模块）
    for key in ("oil", "gold", "btc", "copper", "dxy"):
        val = data.get(key)
        if val and isinstance(val, dict):
            market_data[key] = {
                "change_pct": val.get("change_pct"),
                "price": val.get("price"),
            }

    # dxy → usd
    if "dxy" in market_data and "usd" not in market_data:
        market_data["usd"] = market_data["dxy"]

    # 美股指数
    us_indices = data.get("us_indices") or []
    if us_indices:
        market_data["us_indices"] = us_indices
        avg_chg = sum((u.get("chg") or 0) for u in us_indices) / len(us_indices)
        market_data["equity"] = {"change_pct": round(avg_chg, 2)}

    # VIX
    vix = data.get("vix")
    if vix is not None:
        market_data["vix"] = vix

    # 美债 10Y
    ust10y = data.get("ust10y")
    if ust10y is not None:
        market_data["ust10y"] = ust10y

    # 离岸人民币
    cnh = data.get("cnh")
    if cnh:
        market_data["cnh"] = cnh

    # 北向 / 南向
    for key in ("north", "south"):
        val = data.get(key)
        if val:
            market_data[key] = val

    # 恒生
    hsi = data.get("hsi")
    if hsi:
        market_data["hsi"] = hsi

    market_data["gaps"] = gaps
    market_data["regime"] = data.get("regime", "")
    market_data["regime_note"] = data.get("regime_note", "")

    return market_data


def run(l1_raw=None):
    """
    完整流程：收集数据 → 分析叙事。
    供 narrative_l0.build() 调用。

    Parameters
    ----------
    l1_raw : dict, optional
        L1 layer1_global() 的原始返回。传入则复用，避免重复网络请求。

    Returns
    -------
    dict
        叙事分析结果，包含 headline / decomposition / causal_chain /
        counterfactual / consensus_stage / 五个日常问题等。
    """
    market_data = collect_market_data(l1_raw)
    if market_data.get("error"):
        return {
            "headline": "市场叙事引擎数据不可用",
            "headline_detail": f"数据收集失败：{market_data['error']}",
            "narrative_id": None,
            "narrative_name": "数据不可用",
            "gaps": market_data.get("gaps", []),
        }
    result = analyze(market_data)
    result["gaps"] = market_data.get("gaps", [])
    result["regime"] = market_data.get("regime", "")
    return result


if __name__ == "__main__":
    # 独立测试
    import json
    r = run()
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
