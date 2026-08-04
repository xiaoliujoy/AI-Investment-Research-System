# backend/cio_decision_engine.py
"""
CIO Decision Engine — Portfolio Decision Layer（战略层 / 组合决策层）

输入：regime_history + asset_intelligence_history（仅消费现有数据，不新增数据源）
输出：基于 Regime A/B/C 的战略配置建议（股/金/债/现），不自动交易。

映射基线（用户 2026-08-04 给定）：
  A 风险扩张(Risk On):   股75 金10 债10 现5
  B 正常震荡(Neutral):   股55 金15 债25 现5
  C 风险收缩(Risk Off):  股25 金20 债45 现10

该层是"战略配置+战术调整"框架的决策出口：
  Regime Engine(现有 regime_history) → 本引擎映射配置 → 历史验证(backtest)
不碰 Layer1 评分模型、不扩展日报、不新增数据源（冻结口径一致）。
"""
import sqlite3, json, os
from risk_budget import score_to_budget, budget_to_text, STRATEGIC_EQUITY_FLOOR
from risk_governance import governance_observation, latest_breadth  # Phase 2.0-A 旁路观测(不改决策)

DB = os.path.join(os.path.dirname(__file__), 'database', 'vibe_research.db')

REGIME_LABEL = {'A': '风险扩张', 'B': '正常震荡', 'C': '风险收缩'}

# Regime 类 -> 配置基线（资产类别权重，合计 100）
REGIME_ALLOC = {
    'A': {'equity': 75, 'gold': 10, 'bond': 10, 'cash': 5, 'confidence': 0.80},
    'B': {'equity': 55, 'gold': 15, 'bond': 25, 'cash': 5, 'confidence': 0.60},
    'C': {'equity': 25, 'gold': 20, 'bond': 45, 'cash': 10, 'confidence': 0.85},
}
RISK_STATE_TO_CLASS = {'Risk On': 'A', 'Neutral': 'B', 'Risk Off': 'C'}

# 初始核心基准（用户 core60），用于生成"加/减配"动作
CORE_EQUITY_BENCHMARK = 60


def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _conn()
    con.execute('''CREATE TABLE IF NOT EXISTS cio_decision_history(
        date          TEXT PRIMARY KEY,
        regime_class  TEXT,
        risk_state    TEXT,
        risk_score    REAL,
        alloc_equity  REAL,
        alloc_gold    REAL,
        alloc_bond    REAL,
        alloc_cash    REAL,
        alloc_mode    TEXT,
        action        TEXT,
        confidence    REAL,
        reasons_json  TEXT,
        source        TEXT,
        -- Phase 2.0-A 治理观测字段（飞行记录仪，不改决策）
        risk_governance_state TEXT,
        days_in_crisis INTEGER,
        recovery_stage TEXT,
        opportunity_cost_flag INTEGER,
        failure_type_candidate TEXT,
        governance_version TEXT,
        decision_confidence TEXT
    )''')
    try:
        con.execute('ALTER TABLE cio_decision_history ADD COLUMN alloc_mode TEXT')
    except Exception:
        pass
    for col, ctype in [
        ('risk_governance_state', 'TEXT'),
        ('days_in_crisis', 'INTEGER'),
        ('recovery_stage', 'TEXT'),
        ('opportunity_cost_flag', 'INTEGER'),
        ('failure_type_candidate', 'TEXT'),
        ('governance_version', 'TEXT'),
        ('decision_confidence', 'TEXT'),
    ]:
        try:
            con.execute(f'ALTER TABLE cio_decision_history ADD COLUMN {col} {ctype}')
        except Exception:
            pass
    con.commit()
    con.close()


def _latest_regime(as_of=None):
    con = _conn()
    cur = con.cursor()
    if as_of:
        cur.execute('SELECT * FROM regime_history WHERE date<=? ORDER BY date DESC LIMIT 1', (as_of,))
    else:
        cur.execute('SELECT * FROM regime_history ORDER BY date DESC LIMIT 1')
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def _latest_aip(as_of=None):
    con = _conn()
    cur = con.cursor()
    if as_of:
        d = as_of
    else:
        d = cur.execute('SELECT MAX(date) FROM asset_intelligence_history').fetchone()[0]
    if not d:
        con.close()
        return [], None
    cur.execute(
        'SELECT asset_class,symbol,name,score,state,trend,confidence '
        'FROM asset_intelligence_history WHERE date=?', (d,))
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows], d


def _prior_governance(date):
    """读上一日已落库的治理状态，供 crisis 连续天数计数（旁路观测连续性，不改决策）。"""
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "SELECT risk_governance_state, days_in_crisis FROM cio_decision_history "
        "WHERE date < ? ORDER BY date DESC LIMIT 1", (date,))
    row = cur.fetchone()
    con.close()
    if row:
        return {'days_in_crisis': row['days_in_crisis'] or 0,
                'state': row['risk_governance_state'] or 'normal'}
    return {'days_in_crisis': 0, 'state': 'normal'}


def produce_decision(as_of=None, use_budget=True):
    """生成某日（默认最新）的 CIO 配置建议。不写库。

    use_budget=True  → 走 Risk Budget 连续预算（score_to_budget），v1.1 默认路径
    use_budget=False → 走原 A/B/C 离散映射（--legacy 对照）
    """
    rg = _latest_regime(as_of)
    if not rg:
        return None
    rs = rg['risk_state']
    score = rg['risk_score']
    cls = RISK_STATE_TO_CLASS.get(rs, 'B')

    reasons = [f"Regime={rs}（类 {cls} {REGIME_LABEL[cls]}）；Risk Temperature(score)={score}"]

    if use_budget:
        b = score_to_budget(score)
        alloc = {'equity': int(round(b['equity'] * 100)),
                 'gold': int(round(b['gold'] * 100)),
                 'bond': int(round(b['bond'] * 100)),
                 'cash': int(round(b['cash'] * 100))}
        mode = b['mode']
        reasons.append(budget_to_text(b, score))
        # 置信度：正常模式 + 已验证中段(40-65) → 较高；危机模式(零样本) → 较低
        if mode == 'crisis':
            confidence = 0.50
        elif 40 <= score <= 65:
            confidence = 0.70
        else:
            confidence = 0.60
    else:
        base = REGIME_ALLOC[cls]
        alloc = {'equity': base['equity'], 'gold': base['gold'],
                 'bond': base['bond'], 'cash': base['cash']}
        mode = 'legacy_' + cls
        confidence = base['confidence']
        reasons.append(f"Legacy A/B/C 映射 {cls}：股{base['equity']}% 金{base['gold']}% 债{base['bond']}% 现{base['cash']}%")

    drv = rg.get('risk_drivers') or ''
    if drv:
        reasons.append(f"宏观驱动: {drv}")

    cs = rg.get('commodity_states')
    if cs:
        try:
            cs = json.loads(cs) if isinstance(cs, str) else cs
        except Exception:
            cs = {}
        if isinstance(cs, dict) and cs:
            reasons.append("商品状态: " + ", ".join(f"{k}={v}" for k, v in cs.items()))

    aip, _ = _latest_aip(as_of)
    eq = [a for a in aip if a['asset_class'] == 'equity']
    if eq:
        e = eq[0]
        reasons.append(f"权益AIP: {e['name']} score={e['score']} state={e['state']}")

    delta = alloc['equity'] - CORE_EQUITY_BENCHMARK
    if delta > 0:
        action = f"加配权益至 {alloc['equity']}%（高于核心基准 {CORE_EQUITY_BENCHMARK}%，提升风险暴露）"
    elif delta < 0:
        action = f"减配权益至 {alloc['equity']}%（低于核心基准 {CORE_EQUITY_BENCHMARK}%，偏防御）"
    else:
        action = "维持核心基准权益配置"

    invalid = [
        "恢复条件：未来2周 上涨家数占比>60% 且 score回升≥55 且流动性改善 → 恢复至 50-65 档",
        "加防御条件：score跌破35 且 跌停>涨停2倍 → 触发 30-40 档，不待月度会议",
        "模型失效条件：连续3月 score↔回撤相关性转负(Pearson<0) → 暂停动态，退回静态60/30/10",
    ]

    # Phase 2.0-A 旁路治理观测（仅记录，不改决策）
    prior_gov = _prior_governance(rg['date'])
    breadth_obs = latest_breadth(rg['date'])
    gov_obs = governance_observation(score, prior_gov['days_in_crisis'], prior_gov['state'], breadth_obs)

    return {
        'date': rg['date'],
        'governance_observation': gov_obs,
        'regime_class': cls,
        'risk_state': rs,
        'risk_score': score,
        'allocation': alloc,
        'alloc_mode': mode,
        'action': action,
        'confidence': confidence,
        'reasons': reasons,
        'invalid_conditions': invalid,
        'note': "机会仓10%为独立 overlay（高置信度主题），不计入上述核心配置；"
                "本引擎只生成建议，不自动交易。",
    }


def save_decision(dec):
    if not dec:
        return
    init_db()
    con = _conn()
    gov = dec.get('governance_observation') or {}
    con.execute('''INSERT OR REPLACE INTO cio_decision_history
        (date,regime_class,risk_state,risk_score,alloc_equity,alloc_gold,alloc_bond,alloc_cash,alloc_mode,action,confidence,reasons_json,source,
         risk_governance_state,days_in_crisis,recovery_stage,opportunity_cost_flag,failure_type_candidate,governance_version,decision_confidence)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (dec['date'], dec['regime_class'], dec['risk_state'], dec['risk_score'],
         dec['allocation']['equity'], dec['allocation']['gold'], dec['allocation']['bond'], dec['allocation']['cash'],
         dec.get('alloc_mode'), dec['action'], dec['confidence'], json.dumps(dec['reasons'], ensure_ascii=False),
         'cio_decision_engine',
         gov.get('risk_governance_state'), gov.get('days_in_crisis'), gov.get('recovery_stage'),
         gov.get('opportunity_cost_flag'), gov.get('failure_type_candidate'),
         gov.get('governance_version'), gov.get('decision_confidence')))
    con.commit()
    con.close()


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    use_budget = '--legacy' not in sys.argv
    init_db()
    dec = produce_decision(use_budget=use_budget)
    save_decision(dec)
    print(json.dumps(dec, ensure_ascii=False, indent=2))
