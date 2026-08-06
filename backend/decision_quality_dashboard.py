# -*- coding: utf-8 -*-
"""
Decision Quality Dashboard（Phase 2.0）— Checkpoint C 四指标

指标（用户定义，2026-08-04；第 4 项于 2026-08-04 末增补）：
  - Crisis Precision = 成功Crisis次数 / 全部Crisis次数       目标 > 70%
  - Miss Rate       = 重大下跌前未提前降风险的比例           目标 < 20%
  - Recovery Speed  = 危机解除后恢复正常风险的天数           目标 < 60天
  - Decision Conflict Rate = 冲突决策次数 / 全部决策次数      目标 < 25%(暂定, Checkpoint C 前钉死)

现状：真实 cio_decision_history 仅 1 条(2026-08-04)，远不足以计算。
本脚本产出"框架 + 当前占位"，随真实信号累积自动填充；诚实地标注 insufficient_data。
分母定义（验收前必须钉死，否则指标可游戏化）：
  - "Crisis 事件"：未来 60 日出现 >= 20% 回撤的窗口起点。
  - "成功 Crisis"：触发 Crisis 后该窗口确实发生 >= 20% 回撤。
  - "Miss"：发生 >= 20% 回撤但前 20 日未触发 Crisis。
  - "冲突决策"：decision_conflict_type IS NOT NULL（信号-市场依据不一致，提前症状）。
  - "有价值冲突"：risk高但后来真跌（Risk 领先）；"无价值冲突"：risk高市场续涨（过度防御）。
"""
import sqlite3, json, os, datetime

DB = os.path.join(os.path.dirname(__file__), 'database', 'vibe_research.db')
OUT = os.path.join(os.path.dirname(__file__), '..', 'output')
TODAY = datetime.date.today().strftime('%Y-%m-%d')


def compute():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    n_dec = con.execute("SELECT COUNT(*) FROM cio_decision_history").fetchone()[0]
    n_fail = con.execute("SELECT COUNT(*) FROM risk_budget_failure_log").fetchone()[0]
    n_crisis = con.execute(
        "SELECT COUNT(*) FROM cio_decision_history WHERE alloc_mode='crisis'").fetchone()[0]
    n_conflict = con.execute(
        "SELECT COUNT(*) FROM cio_decision_history WHERE decision_conflict_type IS NOT NULL").fetchone()[0]
    con.close()
    conflict_rate = (n_conflict / n_dec) if n_dec else None
    return {
        'generated_at': TODAY,
        'data_points': {'cio_decisions': n_dec, 'crisis_decisions': n_crisis,
                        'conflict_decisions': n_conflict,
                        'failure_log_entries': n_fail},
        'checkpoint_c_targets': {'crisis_precision_gt': 0.70, 'miss_rate_lt': 0.20,
                                'recovery_days_lt': 60,
                                'decision_conflict_rate_lt': 0.25},
        'metrics': {'crisis_precision': None, 'miss_rate': None, 'recovery_speed': None,
                    'decision_conflict_rate': conflict_rate},
        'status': 'insufficient_data' if n_dec < 30 else 'computable',
        'denominator_definitions': {
            'crisis_event': '未来60日出现>=20%回撤的窗口起点',
            'success_crisis': '触发Crisis后该窗口确实发生>=20%回撤',
            'miss': '发生>=20%回撤但前20日未触发Crisis',
            'conflict_decision': 'decision_conflict_type IS NOT NULL（信号-市场依据不一致）',
            'valuable_conflict': 'risk高但后来真跌（Risk领先）',
            'worthless_conflict': 'risk高市场续涨（过度防御）',
        },
        'note': '真实 decision history 不足 30 条，四指标暂不可计算；'
                '框架已就绪，待 Checkpoint C(2026-12-31) 信号累积后自动填充。'
                'Conflict Rate 目标 25% 为暂定值，验收前需钉死。',
    }


def main():
    r = compute()
    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, f'decision_quality_{TODAY}.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    mp = os.path.join(OUT, f'decision_quality_{TODAY}.md')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write('# Decision Quality Dashboard（Phase 2.0 · Checkpoint C）\n\n')
        f.write(f'> 生成 {r["generated_at"]} ｜ 状态：**{r["status"]}**\n\n')
        f.write(f'- cio_decision_history 样本：{r["data_points"]["cio_decisions"]} 条'
                f'（其中 Crisis：{r["data_points"]["crisis_decisions"]}）\n')
        f.write(f'- failure_log 条目：{r["data_points"]["failure_log_entries"]} 条\n\n')
        f.write('## Checkpoint C 四指标（目标）\n')
        f.write(f'- **Crisis Precision** > {r["checkpoint_c_targets"]["crisis_precision_gt"]*100:.0f}%\n')
        f.write(f'- **Miss Rate** < {r["checkpoint_c_targets"]["miss_rate_lt"]*100:.0f}%\n')
        f.write(f'- **Recovery Speed** < {r["checkpoint_c_targets"]["recovery_days_lt"]} 天\n')
        f.write(f'- **Decision Conflict Rate** < {r["checkpoint_c_targets"]["decision_conflict_rate_lt"]*100:.0f}%'
                f'（暂定，验收前钉死）\n\n')
        f.write(f'- 当前冲突决策：{r["data_points"]["conflict_decisions"]} 条\n\n')
        f.write('### 分母定义（验收前钉死，防游戏化）\n')
        for k, v in r['denominator_definitions'].items():
            f.write(f'- {k}: {v}\n')
        f.write(f'\n> {r["note"]}\n')
    print('saved', jp)
    print('saved', mp)
    return r


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    main()
