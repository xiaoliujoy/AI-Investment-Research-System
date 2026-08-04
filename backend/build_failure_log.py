# -*- coding: utf-8 -*-
"""
Risk Budget Failure Log（Phase 2.0 升级：5类错误分类）

目的：记录 Risk Budget / Risk Temperature 系统在哪些情形下失效或该动未动，
      把系统从"永远正确"升级为"知道自己何时可能错"。这是 AI 投资系统
      自己的"错误数据库"。

Phase 2.0 升级（用户 2026-08-04）：增加 failure_type 分类，未来得到
可统计的失败模式分布：
  - false_positive            误降仓（狼来了）：该防御时防御了，但市场随后恢复
  - false_negative            该降未降：重大下跌前未提前降风险
  - recovery_failure          恢复太慢：危机解除后久未恢复正常风险
  - asset_correlation_failure 防御资产失效（如股债双杀）
  - signal_drift              模型失效（信号预测力漂移/转负）
  - manual / systemic         人工复盘 / 系统级发现

设计原则（对齐治理红线）：
  - 诚实优先：actual_outcome 未判定时填 'pending'，root_cause / lesson 留空待回填。
  - signal_type 区分 real_risk_score / proxy_sim / manual / systemic。

用法：
  python build_failure_log.py                 # 初始化 + 播种 + 展示
  python build_failure_log.py --show          # 仅展示
  python build_failure_log.py --taxonomy      # 按 failure_type 统计
  python build_failure_log.py --add "ep" "2020-02-01" "2020-03-31" "ctx" --signal proxy_sim --type false_negative
  python build_failure_log.py --export        # 导出 JSON
"""
import sqlite3, json, os, sys, datetime

DB = os.path.join(os.path.dirname(__file__), 'database', 'vibe_research.db')
TODAY = datetime.date.today().strftime('%Y-%m-%d')


def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _conn()
    con.execute('''CREATE TABLE IF NOT EXISTS risk_budget_failure_log(
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        episode         TEXT,
        period_start    TEXT,
        period_end      TEXT,
        market_context  TEXT,
        signal_type     TEXT,
        failure_type    TEXT,
        system_state    TEXT,
        actual_outcome  TEXT,
        outcome_detail  TEXT,
        root_cause      TEXT,
        lesson          TEXT,
        created_at      TEXT
    )''')
    con.commit()
    con.close()


# 历史情景种子（system_state 由 risk_budget_stress_sim 回填）
# failure_type 标为该类情景所检验的"失败模式"类别；实际结果由模拟判定
SEED = [
    dict(episode="2015 A股股灾", period_start="2015-06-12", period_end="2015-08-26",
         market_context="上证从5178跌至2850，两月-45%；杠杆踩踏、流动性枯竭；千股跌停常态化。",
         signal_type="proxy_sim", failure_type="false_negative",
         system_state="PENDING(proxy)", actual_outcome="pending"),
    dict(episode="2018 贸易战熊市", period_start="2018-01-24", period_end="2019-01-04",
         market_context="全年震荡下行，沪深300 -25%；去杠杆+贸易摩擦；无显著反弹。",
         signal_type="proxy_sim", failure_type="false_negative",
         system_state="PENDING(proxy)", actual_outcome="pending"),
    dict(episode="2020 疫情崩盘", period_start="2020-01-20", period_end="2020-03-23",
         market_context="春节后开盘熔断式下跌，全球流动性危机；但3月下旬V型反转。",
         signal_type="proxy_sim", failure_type="false_negative",
         system_state="PENDING(proxy)", actual_outcome="pending"),
    dict(episode="2022 股债双杀", period_start="2022-01-01", period_end="2022-10-31",
         market_context="股票跌、债券也跌（理财净值回撤）；防御资产失效；人民币贬值。",
         signal_type="proxy_sim", failure_type="asset_correlation_failure",
         system_state="PENDING(proxy)", actual_outcome="pending"),
    dict(episode="全周期代理信号过触发(系统级)", period_start="2010-01-01", period_end="2026-08-04",
         market_context="代理分在4026日中触发Crisis 1039日(~26%)，因A股频繁20-30%调整且恢复；"
                       "全周期Calmar 0.189<固定60/40 0.217，证明信号若'狼来了'会拖累风险调整后收益。",
         signal_type="systemic", failure_type="false_positive",
         system_state="Crisis触发1039天/最低权益20%", actual_outcome="design_risk",
         root_cause="代理分滞后+阈值过敏，无法区分真危机与常态修正",
         lesson="真实Risk Temperature必须选择性触发Crisis，否则动态策略全周期跑输固定60/40"),
]


def seed():
    con = _conn()
    cur = con.cursor()
    n = cur.execute('SELECT COUNT(*) FROM risk_budget_failure_log').fetchone()[0]
    if n > 0:
        con.close()
        return n
    for s in SEED:
        con.execute('''INSERT INTO risk_budget_failure_log
            (episode,period_start,period_end,market_context,signal_type,failure_type,system_state,actual_outcome,root_cause,lesson,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (s['episode'], s['period_start'], s['period_end'], s['market_context'],
             s['signal_type'], s['failure_type'], s['system_state'], s['actual_outcome'],
             s.get('root_cause', ''), s.get('lesson', ''), TODAY))
    con.commit()
    con.close()
    return len(SEED)


def show():
    con = _conn()
    rows = con.execute('SELECT * FROM risk_budget_failure_log ORDER BY period_start').fetchall()
    con.close()
    print(f"\n=== Risk Budget Failure Log（{len(rows)} 条）===")
    for r in rows:
        print(f"\n[{r['id']}] {r['episode']}  ({r['period_start']}~{r['period_end']})")
        print(f"    类型: {r['failure_type']}  | 信号: {r['signal_type']}  | 结果: {r['actual_outcome']}")
        print(f"    市场背景: {r['market_context']}")
        if r['system_state']:
            print(f"    系统状态: {r['system_state']}")
        if r['outcome_detail']:
            print(f"    实际结果: {r['outcome_detail']}")
        if r['root_cause']:
            print(f"    根因:     {r['root_cause']}")
        if r['lesson']:
            print(f"    教训:     {r['lesson']}")


def taxonomy():
    con = _conn()
    rows = con.execute('SELECT failure_type, COUNT(*) c FROM risk_budget_failure_log '
                       'GROUP BY failure_type ORDER BY c DESC').fetchall()
    con.close()
    print("\n=== Failure Type 分布 ===")
    for r in rows:
        print(f"  {r['failure_type']}: {r['c']} 条")


def add(episode, start, end, context, signal='manual', ftype='manual'):
    con = _conn()
    con.execute('''INSERT INTO risk_budget_failure_log
        (episode,period_start,period_end,market_context,signal_type,failure_type,actual_outcome,created_at)
        VALUES(?,?,?,?,?,?,?,?)''',
        (episode, start, end, context, signal, ftype, 'pending', TODAY))
    con.commit()
    con.close()
    print(f"added: {episode} (type={ftype})")


def export():
    con = _conn()
    rows = con.execute('SELECT * FROM risk_budget_failure_log ORDER BY period_start').fetchall()
    con.close()
    data = [dict(r) for r in rows]
    out = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'output', f'failure_log_{TODAY}.json'))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print('exported', out)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    args = sys.argv[1:]
    if '--show' in args:
        init_db(); show()
    elif '--taxonomy' in args:
        init_db(); taxonomy()
    elif '--export' in args:
        init_db(); export()
    elif '--add' in args:
        i = args.index('--add')
        signal = 'manual'; ftype = 'manual'
        if '--signal' in args:
            signal = args[args.index('--signal') + 1]
        if '--type' in args:
            ftype = args[args.index('--type') + 1]
        init_db()
        add(args[i+1], args[i+2], args[i+3], args[i+4] if len(args) > i+4 else '', signal, ftype)
    else:
        init_db()
        n = seed()
        print(f"seeded/exists: {n} entries")
        show()
        taxonomy()
