# -*- coding: utf-8 -*-
"""Investment Committee（投资委员会）—— 唯一决策出口。

不做研究，只汇总 Research Center（L1~L8）的评分 / 证据 / 概率 / 冲突，
输出唯一投资决策。规则透明（方向投票 + 强否决），非黑箱模型。

入口：decide(results, conflicts=None, confidence=None, feedback=None)
  results    : dict  orchestrator 的 ctx.results（含 FLOW/L1..L8/L3_5/L4/L5/... 各层结果）
  conflicts  : list  跨层冲突检测结果
  confidence : dict  聚合后的置信度（含 overall）
  feedback   : dict  L8 学习反哺信号（applied/pos_scale/sector_bias/...）

返回 InvestmentCommitteeDecision（dict）：
  can_buy        : "YES" / "NO" / "CAUTION"
  direction      : "bullish" / "bearish" / "neutral"
  position_pct   : 仓位护栏字符串（如 "30-50%"）
  main_logic     : 主要逻辑串联（关键证据句）
  risk_summary   : 风险摘要（否决项 + 冲突）
  scoreboard     : Research Center 各层 [{layer, direction, confidence, title}]
  hard_no        : 强否决原因列表
  bull / bear    : 投票计数
  learning_note  : L8 反哺提示（若有）
  overall_confidence : 聚合总置信度
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# Research Center（研究中枢）= L1~L8 八层分析引擎（逻辑层，不做决策）
RESEARCH_CENTER_LAYERS = ["L1", "L2", "L3", "L3_5", "L4", "L5", "L6", "L7", "L8"]

# 参与方向投票的研究层（数据情报 / 宏观 / 产业 / 资金 / 共识 / 龙头 / 情绪 / 基本面）
_VOTE_LAYERS = ["FLOW", "L1", "L2", "L3", "L3_5", "L4", "L5", "sentiment", "fundamental"]


# ── 真实 IC 辩论：L1~L8 支持/反对 + 原因 + 加权投票 ──
# (层名, 中文, 投票权重) —— 权重反映该层对"现在能不能买"的决定性
_DEBATE_LAYERS = [
    ("L1", "全球宏观", 1.5),
    ("L2", "中国宏观", 1.5),
    ("L3", "产业趋势", 1.3),
    ("L3_5", "产业链推理", 1.0),
    ("L4", "资金共识", 1.6),
    ("L5", "龙头体系", 1.2),
    ("L6", "交易执行", 0.8),
    ("L7", "风险控制", 2.0),
    ("L8", "学习进化", 1.0),
    ("FLOW", "资金情报", 1.2),
    ("sentiment", "市场情绪", 1.0),
    ("fundamental", "基本面", 1.0),
]

_VOTE_CN = {"support": "支持", "oppose": "反对", "neutral": "中性", "absent": "缺席"}


def _layer_vote(d):
    """方向 → 对'现在做多'的投票。"""
    if d in ("bullish", "neutral_bullish"):
        return "support"
    if d in ("bearish", "bearish_weak"):
        return "oppose"
    return "neutral"


def _layer_argument(layer, r, results):
    """为某一研究层生成一句辩论发言（支持/反对的论据，点到即止）。"""
    r = r or {}
    sig = r.get("signal") or {}
    raw = r.get("raw") or {}
    d = sig.get("direction")
    conf = r.get("confidence")
    title = r.get("title") or layer

    if layer == "L1":
        regime = sig.get("regime") or (raw.get("data") or {}).get("regime")
        return f"外围「{regime or '信号中性'}」，对 A 股风险偏好无显著指引"

    if layer == "L2":
        regime = sig.get("regime") or (raw.get("data") or {}).get("regime")
        return f"中国宏观「{regime or '中性'}」，货币信用环境偏弱"

    if layer == "L3":
        top = sig.get("top") or []
        if top:
            return f"产业主线「{'、'.join(top[:2])}」已被资金验证，趋势向上"
        return "产业趋势缺乏明确主线验证"

    if layer == "L3_5":
        chain = sig.get("chain_name") or raw.get("theme") or ""
        if chain:
            return f"产业链「{chain}」逻辑通顺，上中下游共振"
        return "产业链逻辑偏正面但缺乏强共振证据"

    if layer == "L4":
        lines = raw.get("main_lines") or []
        dist = raw.get("stage_distribution") or {}
        n = len(lines)
        crowd = dist.get("高潮", 0) + dist.get("退潮", 0)
        tot = sum(dist.values()) if dist else 0
        pct = int(round(100 * crowd / tot)) if tot else 0
        if n:
            return f"{n} 条资金主线确认，但高潮+退潮占比 {pct}%，拥挤度高、追涨风险大"
        return "资金共识未形成明确主线"

    if layer == "L5":
        n = sig.get("leader_count") or 0
        if n:
            return f"{n} 个板块确认龙头，结构健康、赚钱效应可延续"
        return "龙头体系尚未确认，主线缺乏领涨标的"

    if layer == "L6":
        return "交易执行交人工（看图定买点），系统不自动下单，权限保留在人"

    if layer == "L7":
        comp = sig.get("composite")
        pos = sig.get("position") or raw.get("position")
        lvl = sig.get("risk_level") or ""
        if comp is not None:
            return f"综合风险 {comp}（{lvl}），仓位护栏 {pos}"
        return "风险控制数据缺失"

    if layer == "L8":
        cnt = raw.get("count") if isinstance(raw, dict) else None
        if cnt:
            return f"交易日志 {cnt} 笔，历史胜率反哺已启动"
        return "交易日志暂无记录，胜率反哺未启动（样本不足，暂列中性）"

    if layer == "FLOW":
        fs = sig.get("flow_score")
        if fs is not None:
            return f"资金情报 {fs} 分（{sig.get('direction', '')}），决定整体水位"
        return "资金情报缺失"

    if layer == "sentiment":
        st = sig.get("state") or sig.get("regime")
        if st:
            return f"市场情绪「{st}」"
        return "情绪数据缺失"

    if layer == "fundamental":
        driven = sig.get("driven")
        if driven:
            return f"{driven} 个主线有业绩驱动，上涨更可持续"
        return "主线业绩驱动证据不足"

    # 通用兜底
    return f"{title}：方向 {d or '中性'}，置信度 {conf}"


def _build_debate(results):
    """汇总各研究层辩论发言 + 加权投票。"""
    rows = []
    w_sup = w_opp = w_neu = 0.0
    sup_layers, opp_layers, neu_layers = [], [], []
    for layer, name, weight in _DEBATE_LAYERS:
        r = (results or {}).get(layer)
        if not isinstance(r, dict):
            rows.append({
                "layer": layer, "name": name, "vote": "absent", "weight": weight,
                "confidence": None, "argument": "（本层未运行 / 数据缺失）"
            })
            continue
        d = (r.get("signal") or {}).get("direction")
        vote = _layer_vote(d)
        conf = r.get("confidence")
        arg = _layer_argument(layer, r, results)
        rows.append({
            "layer": layer, "name": name, "vote": vote, "weight": weight,
            "confidence": conf, "argument": arg
        })
        if vote == "support":
            w_sup += weight; sup_layers.append(name)
        elif vote == "oppose":
            w_opp += weight; opp_layers.append(name)
        else:
            w_neu += weight; neu_layers.append(name)
    total = w_sup + w_opp + w_neu
    ratio = f"{len(sup_layers)}支持:{len(opp_layers)}反对:{len(neu_layers)}中性"
    weighted_ratio = (f"支持权 {w_sup:.1f} : 反对权 {w_opp:.1f} : 中性权 {w_neu:.1f}"
                      if total else "")
    return {
        "rows": rows,
        "support": w_sup, "oppose": w_opp, "neutral": w_neu,
        "support_layers": sup_layers, "oppose_layers": opp_layers,
        "neutral_layers": neu_layers,
        "ratio": ratio, "weighted_ratio": weighted_ratio, "total_weight": total,
    }


def _dir(results, layer):
    return (results.get(layer) or {}).get("signal", {}).get("direction")


def _scoreboard(results):
    board = []
    for L in RESEARCH_CENTER_LAYERS:
        r = results.get(L)
        if not isinstance(r, dict):
            continue
        board.append({
            "layer": L,
            "direction": (r.get("signal") or {}).get("direction"),
            "confidence": r.get("confidence"),
            "title": r.get("title", ""),
        })
    return board


def decide(results, conflicts=None, confidence=None, feedback=None):
    """汇总 Research Center 产出 → 唯一投资决策。"""
    results = results or {}
    conflicts = conflicts or []
    confidence = confidence or {}
    feedback = feedback or {}

    # ── 1) 方向投票 ──
    bull = bear = 0
    for layer in _VOTE_LAYERS:
        d = _dir(results, layer)
        if d in ("bullish", "neutral_bullish"):
            bull += 1
        elif d in ("bearish", "bearish_weak"):
            bear += 1

    # 市场综合风险（L7）加重权重
    l7 = results.get("L7") or {}
    comp = (l7.get("raw") or {}).get("composite")
    if comp is not None:
        if comp >= 70:
            bear += 2
        elif comp < 50:
            bull += 1

    # ── 2) 强否决（任一成立即 NO）──
    hard_no = []
    if _dir(results, "L1") == "bearish":
        hard_no.append("全球避险主导")
    if _dir(results, "FLOW") == "bearish":
        hard_no.append("资金面流出主导")
    if _dir(results, "sentiment") in ("退潮", "冰点"):
        hard_no.append("情绪退潮/冰点")
    if comp is not None and comp >= 70:
        hard_no.append(f"综合风险高({comp})")

    if hard_no:
        can_buy = "NO"
    elif bear > bull and bear >= 3:
        can_buy = "NO"
    elif bull > bear:
        can_buy = "YES"
    else:
        can_buy = "CAUTION"

    # ── 3) 主要逻辑串联（关键证据）──
    reasons = []
    confirmed = (results.get("L3") or {}).get("signal", {}).get("top") or []
    if confirmed:
        reasons.append(f"产业「{'、'.join(confirmed[:2])}」已被资金验证")
    nlead = (results.get("L5") or {}).get("signal", {}).get("leader_count", 0)
    if nlead > 0:
        reasons.append(f"{nlead} 个板块确认龙头")
    l1r = (results.get("L1") or {}).get("signal", {}).get("regime")
    if l1r:
        reasons.append(f"外围「{l1r}」")
    flow_sig = (results.get("FLOW") or {}).get("signal", {}) or {}
    if flow_sig.get("flow_score") is not None:
        reasons.append(f"资金情报{flow_sig['flow_score']}分({flow_sig.get('direction', '')})")
    st = (results.get("sentiment") or {}).get("signal", {}).get("state")
    if st:
        reasons.append(f"情绪「{st}」")
    fd = (results.get("fundamental") or {}).get("signal", {}) or {}
    if fd.get("driven"):
        reasons.append(f"{fd['driven']} 个主线有业绩驱动")
    if not reasons:
        reasons.append("各层信号中性、缺乏共振")

    # ── 4) L8 学习反哺（历史胜率 → 仅观察/记录；pos_scale 已冻结，不进入生产仓位）──
    # v0.2 PRD §8.6 + Phase 1C 红线：pos_scale 不得自动影响生产 position_pct。
    # 生产仓位只来自既有 IC + Risk Budget cap（l7.raw.position）。pos_scale 仍计算、仍记录，
    # 但仅供人工复核（研究用），绝不再改写 position。
    learning_note = None
    pos0 = (l7.get("raw") or {}).get("position", "30-50%")
    position = pos0
    if feedback.get("applied"):
        scale = feedback.get("pos_scale", 1.0)
        if scale and scale < 0.999:
            try:
                from learning_feedback import _scale_position
                new_pos = _scale_position(pos0, scale)
                if new_pos != pos0:
                    # 仅记录供人工复核（研究用），绝不改生产仓位
                    learning_note = (
                        f"[pos_scale 已冻结·仅记录] 历史胜率反哺本应将仓位护栏 "
                        f"{pos0} → {new_pos}（pos_scale={scale}），未应用"
                    )
            except Exception:
                pass
        sb = feedback.get("sector_bias", {}) or {}
        mains = ((results.get("L4") or {}).get("raw") or {}).get("main_lines") or []
        focus = [str(m.get("sector")) for m in mains if m.get("sector")]
        hit = [f"{s}{sb[s]:+.1f}" for s in focus if s in sb]
        if hit:
            reasons.append("历史胜率偏置：" + "、".join(hit))

    # ── 5) 风险摘要（否决项 + 冲突）──
    risk_parts = list(hard_no)
    for c in conflicts[:3]:
        risk_parts.append(c.get("desc") or c.get("type") or "层间冲突")
    risk_summary = "；".join(risk_parts) if risk_parts else "未见显著风险信号"

    # ── 6) 真实 IC 辩论（L1~L8 支持/反对 + 原因 + 加权投票）──
    debate = _build_debate(results)
    w_sup, w_opp, w_neu = debate["support"], debate["oppose"], debate["neutral"]
    if w_sup >= 2.0 and w_sup > w_opp * 1.25:
        w_verdict = "YES"
    elif w_opp >= 2.0 and w_opp > w_sup * 1.25:
        w_verdict = "NO"
    else:
        w_verdict = "CAUTION"
    if hard_no:
        verdict = f"⛔ 强否决触发（{'；'.join(hard_no)}）→ 裁决 NO"
    elif w_verdict == can_buy:
        dom = "支持" if w_sup > w_opp else ("反对" if w_opp > w_sup else "分歧")
        verdict = f"加权投票 {debate['ratio']}｜{dom}占优 → 裁决 {can_buy}"
    else:
        verdict = (f"加权投票 {debate['ratio']}｜建议 {w_verdict}，"
                   f"最终裁决 {can_buy}（强否决/简单多数优先）")

    return {
        "can_buy": can_buy,
        "direction": ("bullish" if bull > bear else "bearish" if bear > bull else "neutral"),
        "position_pct": position,
        "main_logic": "；".join(reasons),
        "risk_summary": risk_summary,
        "scoreboard": _scoreboard(results),
        "hard_no": hard_no,
        "bull": bull,
        "bear": bear,
        "learning_note": learning_note,
        "overall_confidence": (confidence.get("overall")
                                if isinstance(confidence, dict) else confidence),
        # ── Slice 3：真实 IC 辩论 ──
        "debate": debate["rows"],
        "weighted_vote": {
            "support": w_sup, "oppose": w_opp, "neutral": w_neu,
            "support_layers": debate["support_layers"],
            "oppose_layers": debate["oppose_layers"],
            "neutral_layers": debate["neutral_layers"],
            "ratio": debate["ratio"],
            "weighted_ratio": debate["weighted_ratio"],
        },
        "verdict": verdict,
    }


if __name__ == "__main__":
    # 独立运行：从最新 brain_report.json 读取 results 跑一遍 IC
    import json
    p = os.path.join(BASE, "output", "brain_report.json")
    if not os.path.exists(p):
        print("缺少 output/brain_report.json，请先跑 orchestrator.run()")
    else:
        rep = json.load(open(p, encoding="utf-8"))
        d = decide(rep.get("results", {}), rep.get("conflicts"),
                   rep.get("confidence"), rep.get("learning_feedback"))
        print("IC 决策:", d["can_buy"], "| 方向:", d["direction"],
              "| 仓位:", d["position_pct"])
        print("主要逻辑:", d["main_logic"])
        print("风险摘要:", d["risk_summary"])
