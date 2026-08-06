# -*- coding: utf-8 -*-
"""
Risk Governance Layer（Phase 2.0）— 风险治理层（旁路观察 / 飞行记录仪）

定位：在 1.9B 的 Risk Budget RULE 之上，加一层"状态机治理"观测，把系统从
  "风险高 → 降仓"
升级为可审计的：
  "识别风险状态 + 危机年龄 + 恢复确认 + 机会成本控制 + 信号一致性 → 记录"

⚠️ Governance Layer Independence Rule（用户 2026-08-04 铁律）：
  Phase 2.0 阶段，Governance Layer **只记录、评估、审计**，
  **不允许反向修改 CIO Decision**。它是飞行记录仪，不是自动驾驶。
  否则会出现 Risk Engine→Governance→改 Risk Engine→再证明有效 的循环验证污染。

设计原则（对齐冻结纪律）：
  - 不碰 Layer1 评分模型、不加新数据源。
  - 仅消费已有：regime_history.risk_score（真实信号）+ market_daily 广度（已有宽度表）。
  - 阈值用【文档默认值】，非历史回测拟合。
  - 恢复为【渐进式 step ramp】，不做硬反转，避免熊市反弹陷阱。
"""
import sqlite3, json, os, sys, datetime
from risk_budget import score_to_budget

DB = os.path.join(os.path.dirname(__file__), 'database', 'vibe_research.db')
GOVERNANCE_VERSION = '2.0'

CRISIS_AGING_REVIEW = 30     # 第30天提示复核
CRISIS_AGING_FORCE = 90      # 第90天强制回答
RECOVERY_STEP = 0.10         # 每次确认 +10% 权益（渐进，仅记录，不改决策）
RECOVERY_SCORE = 55          # score 回到此值视为修复
OPP_COST_EQUITY = 0.30       # 权益 <= 此值视为"防御中"
OPP_COST_BREADTH = 0.60      # 上涨家数占比 > 此值视为广度恢复


def latest_breadth(as_of=None):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    cur = con.cursor()
    if as_of:
        cur.execute("SELECT * FROM market_daily WHERE date<=? ORDER BY date DESC LIMIT 1", (as_of,))
    else:
        cur.execute("SELECT * FROM market_daily ORDER BY date DESC LIMIT 1")
    r = cur.fetchone(); con.close()
    if not r:
        return None
    up = r['up_count'] or 0
    dn = r['down_count'] or 0
    return {'up_count': up, 'down_count': dn,
            'emotion_score': r['emotion_score'], 'stage': r['stage'],
            'ratio': (up / (up + dn) if (up + dn) > 0 else None)}


def govern(score, days_in_crisis=0, breadth=None):
    """纯函数：对一个 score + 危机持续天数 + 广度，产出治理判定（不改任何决策）。"""
    b = score_to_budget(score)
    mode = b['mode']
    equity = b['equity']
    alerts = []
    # 1) Crisis Aging
    if mode == 'crisis':
        days_in_crisis += 1
        if days_in_crisis == CRISIS_AGING_REVIEW:
            alerts.append(f"Crisis Aging: 持续{days_in_crisis}天且市场未继续恶化 → 触发复核(考虑部分恢复)")
        if days_in_crisis >= CRISIS_AGING_FORCE:
            alerts.append(f"Crisis Aging: 持续{days_in_crisis}天 → 须回答为何仍低仓,否则强制部分恢复")
    # 广度恢复判定（coincident 信号，仅作 sanity-check，非领先）
    breadth_ok = False
    if breadth and breadth.get('ratio') is not None:
        breadth_ok = breadth['ratio'] >= OPP_COST_BREADTH
    elif breadth and (breadth.get('emotion_score') or 0) > 0:
        breadth_ok = True
    # 2) Recovery Protocol（Crisis 镜像，渐进；本层仅记录信号，不执行）
    recovery_signal = (score >= RECOVERY_SCORE) and breadth_ok
    # 3) Opportunity Cost Monitor
    opp_cost = (equity <= OPP_COST_EQUITY) and breadth_ok
    if opp_cost:
        alerts.append("Opportunity Cost: 低仓(<=30%)但广度恢复(上涨家数>60%) → 防御可能错误")
    return {'equity': equity, 'mode': mode, 'budget': b,
            'days_in_crisis': days_in_crisis, 'recovery_signal': recovery_signal,
            'opportunity_cost': opp_cost, 'alerts': alerts, 'breadth_ok': breadth_ok}


def consistency_confidence(score, breadth=None):
    """信号一致性置信度（非收益预测）：Risk Score 方向 vs 广度/趋势 是否共振。

    high  = 信号与市场同向确认（看多且市场强 / 防御且市场弱）
    low   = 信号与市场背离（看多但市场弱 / 防御中但市场强→机会成本风险）
    medium= 其余
    """
    br = breadth['ratio'] if breadth else None
    stage = breadth['stage'] if breadth else None
    risk_on = score >= RECOVERY_SCORE
    confirm_up = (br is not None and br >= 0.55) or (stage and '上涨' in stage)
    confirm_down = (br is not None and br <= 0.45) or (stage and '下跌' in stage)
    if risk_on and confirm_up:
        return 'high'
    if (not risk_on) and confirm_down:
        return 'high'
    if risk_on and confirm_down:
        return 'low'
    if (not risk_on) and confirm_up:
        return 'low'
    return 'medium'


def decision_conflict_type(score, breadth=None):
    """判定信号-市场背离的具体冲突类型（仅当一致性为 low 时有意义）。

    与 Failure Log 区分（用户 2026-08-04 末提案）：
      - Failure Log  : 记录"结果错误"（病情，滞后；如降仓后市场涨30%）
      - Conflict     : 记录"决策依据之间不一致"（症状，提前；如风险高但广度强）
    Conflict 往往早于 Failure，类似医学"症状出现即记录，不等恶化"。
    返回 None 或 'risk_vs_breadth' / 'risk_vs_trend' / 'signal_vs_market'。
    """
    if breadth is None:
        return None
    br = breadth.get('ratio') if isinstance(breadth, dict) else None
    stage = breadth.get('stage') if isinstance(breadth, dict) else None
    risk_on = score >= RECOVERY_SCORE
    up = (br is not None and br >= 0.55) or (stage and '上涨' in stage)
    dn = (br is not None and br <= 0.45) or (stage and '下跌' in stage)
    if (not risk_on) and up:
        return 'risk_vs_breadth'       # 防御信号 vs 广度强势 → 过度保护风险
    if risk_on and dn:
        return 'risk_vs_breadth'       # 扩张信号 vs 广度弱势 → 冒进风险
    if (not risk_on) and stage and '下跌' in stage:
        return 'risk_vs_trend'
    if risk_on and stage and '上涨' in stage:
        return 'risk_vs_trend'
    if up or dn:
        return 'signal_vs_market'
    return None


def governance_observation(score, prev_days_in_crisis=0, prev_state='normal', breadth=None):
    """旁路观测：返回治理状态字段，**绝不修改 CIO 决策**。

    days_in_crisis        : 危机持续计数（仅当连续处于 crisis 时 +1）
    recovery_stage        : 离开危机后的首个非危机日标 'active'，否则 None
    failure_type_candidate: 若将来被证明错，最可能的失败类别（前瞻标记）
    decision_confidence   : 信号一致性置信度
    """
    g = govern(score, prev_days_in_crisis, breadth)
    mode = g['mode']
    if prev_state == 'crisis' and mode == 'crisis':
        days = prev_days_in_crisis + 1
    elif mode == 'crisis':
        days = 1
    else:
        days = 0
    recovery_stage = 'active' if (mode != 'crisis' and prev_state == 'crisis') else None
    cand = None
    if g['opportunity_cost']:
        cand = 'false_positive'
    elif recovery_stage == 'active' and not g['breadth_ok']:
        cand = 'recovery_failure'
    dc = consistency_confidence(score, breadth)
    conflict_type = decision_conflict_type(score, breadth) if dc == 'low' else None
    return {
        'risk_governance_state': mode,
        'days_in_crisis': days,
        'recovery_stage': recovery_stage,
        'opportunity_cost_flag': 1 if g['opportunity_cost'] else 0,
        'failure_type_candidate': cand,
        'decision_conflict_type': conflict_type,
        'governance_version': GOVERNANCE_VERSION,
        'decision_confidence': dc,
        'alerts': g['alerts'],
    }


def produce_governed(as_of=None):
    """演示用：CIO 决策 + 治理观测。治理观测已内置于 cio_decision_engine.produce_decision
    （旁路附加 governance_observation，绝不覆盖 CIO 的 allocation / action，遵守 Independence Rule）。
    此处仅透传，避免重复计算。"""
    from cio_decision_engine import produce_decision
    dec = produce_decision(as_of=as_of, use_budget=True)
    return dec


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    d = produce_governed()
    out = os.path.join(os.path.dirname(__file__), '..', 'output', 'governed_latest.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(json.dumps(d, ensure_ascii=False, indent=2))
