# -*- coding: utf-8 -*-
"""
Risk Budget Rule Stress Simulation（Phase 1.9C — P0，用户建议的"稳定性验证"）

⚠️ 诚实声明（最高优先级）：
  本脚本使用的 Risk Score 是【价格衍生的代理信号 PROXY】，不是真实的
  regime_history.risk_score（Risk Temperature）。真实信号仅存在于 2025-07 之后，
  无法在 2015/2018/2020/2022 回放。因此：

    ✅ 本测试验证的是「Risk Budget RULE 本身的机制」
       （非线性防御曲线 + Crisis Protocol 阈值 + 调仓纪律）
       在真实历史极端行情下的表现。
    ❌ 本测试【不】验证真实 Risk Temperature 信号的预测力——
       那是另一回事，必须等实时信号累积到 Checkpoint C(2026-12-31) 后做。

  代理信号是【滞后】的（由价格自身派生），所以它是该规则"最差情形"的下界：
  真实信号若含领先成分（宽度/资金流/情绪），理论上可更早降暴露；若与价格背离则更差。
  结论不可外推为"模型已通过长周期验证"。

方法：
  - 收益序列：全A等权日收益（stock_daily 构造，与 1.9B 完全一致，保证可比）
  - 代理压力分 proxy_score(0-100)：由等权序列的 20日动量 / 60日最大回撤 / 20日波动 合成
  - 三策略对比：A 100%权益 / B 固定60-40 / C AI Risk Budget(代理分) —— 同 1.9B 成本模型
  - 四段历史情景：2015股灾 / 2018熊市 / 2020疫情 / 2022股债双杀（含全周期 2010-2026）
"""
import sqlite3, json, os, sys, datetime, math
from collections import Counter

DB = os.path.join(os.path.dirname(__file__), 'database', 'vibe_research.db')
OUT = os.path.join(os.path.dirname(__file__), '..', 'output')
TODAY = datetime.date.today().strftime('%Y-%m-%d')

VALID_PREFIX = ('60', '00', '30', '68')
CAP = 0.21
RF_ANNUAL = 0.02
RF_DAILY = (1.0 + RF_ANNUAL) ** (1.0 / 252) - 1.0
COST_RATE = 0.002
REBAL_DEVIATION = 0.10
COOLDOWN_DAYS = 20
MONTH_DAYS = 21
HIST_START = '2010-01-01'

from risk_budget import score_to_budget

EPISODES = {
    '2015_股灾':   ('2015-06-01', '2015-09-30'),
    '2018_熊市':   ('2018-01-01', '2018-12-31'),
    '2020_疫情':   ('2020-01-20', '2020-04-30'),
    '2022_股债双杀': ('2022-01-01', '2022-12-31'),
}


def connect():
    con = sqlite3.connect(DB)
    con.execute('PRAGMA busy_timeout=15000')
    return con


def build_equal_weight_index(con, start=HIST_START):
    cur = con.cursor()
    cur.execute("SELECT date, code, close FROM stock_daily WHERE date >= ? ORDER BY code, date", (start,))
    rows = cur.fetchall()
    daily_sum, daily_cnt, prev = {}, {}, {}
    for date, code, close in rows:
        if close is None or close <= 0:
            prev[code] = close
            continue
        p = prev.get(code)
        if p and p > 0:
            r = close / p - 1.0
            if -CAP <= r <= CAP:
                daily_sum[date] = daily_sum.get(date, 0.0) + r
                daily_cnt[date] = daily_cnt.get(date, 0) + 1
        prev[code] = close
    return {d: daily_sum[d] / daily_cnt[d] for d in daily_sum if daily_cnt[d] > 0}


def build_proxy_scores(idx):
    """由等权序列自身派生滞后压力分（PROXY，非真实信号）。"""
    dates = sorted(idx.keys())
    rets = {dates[i]: idx[dates[i]] for i in range(len(dates))}
    # 预计算累计收益以便算回撤
    cum = {}
    c = 1.0
    for d in dates:
        c *= (1 + idx[d]); cum[d] = c
    lut = {}
    for i, d in enumerate(dates):
        if i < 60:
            lut[d] = 50.0
            continue
        # 20日动量
        mom20 = cum[d] / cum[dates[i-20]] - 1.0
        # 60日最大回撤
        window = [cum[dates[j]] for j in range(i-60, i+1)]
        peak = max(window)
        dd60 = min(window) / peak - 1.0
        # 20日波动
        vol20 = math.sqrt(sum((idx[dates[j]] - sum(idx[dates[k]] for k in range(i-20, i))/20.0)**2 for j in range(i-20, i+1)) / 20.0)
        # 合成压力 S in [0,1]
        S = (0.45 * max(0.0, -mom20/0.08)
             + 0.35 * max(0.0, -dd60/0.15)
             + 0.20 * max(0.0, vol20/0.025))
        S = max(0.0, min(1.0, S))
        lut[d] = (1.0 - S) * 100.0
    return lut


def sim_buyhold(dates, idx):
    return [idx[d] for d in dates]


def sim_fixed(dates, idx):
    return [0.60 * idx[d] + 0.40 * RF_DAILY for d in dates]


def sim_risk_budget(dates, idx, score_lut, track=False):
    rets, ws, crisis_days, min_eq = [], [], 0, 1.0
    cur_w = None
    last_rebal = -999
    for i, d in enumerate(dates):
        sc = 50.0
        for j in range(i, -1, -1):
            s = score_lut.get(dates[j])
            if s is not None:
                sc = s
                break
        b = score_to_budget(sc)
        target_w = b['equity']
        cost = 0.0
        if cur_w is None:
            cur_w = target_w
            last_rebal = i
        else:
            can_month = (i - last_rebal) >= MONTH_DAYS
            dev = abs(target_w - cur_w)
            cooldown_ok = (i - last_rebal) >= COOLDOWN_DAYS
            if can_month and dev >= REBAL_DEVIATION and cooldown_ok:
                cost = COST_RATE * dev
                cur_w = target_w
                last_rebal = i
        if b['mode'] == 'crisis':
            crisis_days += 1
        min_eq = min(min_eq, cur_w)
        port_ret = cur_w * idx[d] + (1.0 - cur_w) * RF_DAILY - cost
        rets.append(port_ret)
        if track:
            ws.append((d, round(cur_w*100, 1), round(sc, 1), b['mode']))
    if track:
        return rets, {'min_equity': round(min_eq*100, 1), 'crisis_days': crisis_days, 'weights': ws}
    return rets


def metrics(rets):
    n = len(rets)
    if n == 0:
        return {}
    curve = [1.0]
    for r in rets:
        curve.append(curve[-1] * (1.0 + r))
    years = n / 252.0
    final = curve[-1]
    cagr = (final ** (1.0/years) - 1.0) if final > 0 and years > 0 else None
    peak = curve[0]; mdd = 0.0; in_dd = False; rec_start = 0; recovery = None
    for k in range(1, len(curve)):
        if curve[k] > peak:
            peak = curve[k]
        dd = curve[k]/peak - 1.0
        if dd < mdd:
            mdd = dd
        if dd < 0 and not in_dd:
            in_dd = True; rec_start = k
        if in_dd and curve[k] >= peak:
            in_dd = False
            if recovery is None:
                recovery = k - rec_start
    if in_dd:
        recovery = None
    mean = sum(rets)/n
    var = sum((r-mean)**2 for r in rets)/n
    std = math.sqrt(var) if var > 0 else 0.0
    sharpe = mean/std*math.sqrt(252.0) if std > 0 else 0.0
    calmar = cagr/abs(mdd) if (mdd < 0 and cagr is not None) else None
    worst_month = 0.0
    for k in range(0, len(curve) - MONTH_DAYS):
        m = curve[k+MONTH_DAYS]/curve[k] - 1.0
        if m < worst_month:
            worst_month = m
    return {
        'n_days': n, 'final_mult': round(final, 3),
        'cagr': round(cagr*100, 2) if cagr is not None else None,
        'max_dd': round(mdd*100, 2),
        'sharpe': round(sharpe, 3),
        'calmar': round(calmar, 3) if calmar is not None else None,
        'recovery': '未恢复' if recovery is None else recovery,
        'worst_month': round(worst_month*100, 2),
    }


def main():
    con = connect()
    print('[1] building equal-weight index (>=%s)...' % HIST_START)
    idx = build_equal_weight_index(con)
    print(f'    days={len(idx)} ({min(idx)}~{max(idx)})')
    print('[2] building PROXY stress scores...')
    plu = build_proxy_scores(idx)
    con.close()

    dates_all = sorted(idx.keys())

    def slice_dates(a, b):
        return [d for d in dates_all if a <= d <= b]

    results = {'generated_at': TODAY, 'warning': 'PROXY_SIMULATION_NOT_REAL_SIGNAL',
               'method': {'return_series': '全A等权日收益(stock_daily)', 'score_source': '价格衍生代理分(PROXY,滞后)',
                          'cost_model': '月度+偏离10%+20日冷却+0.2%成本', 'hist_start': HIST_START}}
    results['full_period'] = {}
    ra = sim_buyhold(dates_all, idx); rb = sim_fixed(dates_all, idx); rc, track = sim_risk_budget(dates_all, idx, plu, track=True)
    results['full_period']['range'] = f'{dates_all[0]}~{dates_all[-1]}'
    results['full_period']['A_BuyHold'] = metrics(ra)
    results['full_period']['B_Fixed60_40'] = metrics(rb)
    results['full_period']['C_AI_RiskBudget_PROXY'] = metrics(rc)
    results['full_period']['C_equity_stats'] = {'min_equity': track['min_equity'], 'crisis_days': track['crisis_days']}

    results['episodes'] = {}
    fail_updates = []
    for name, (a, b) in EPISODES.items():
        dd = slice_dates(a, b)
        if len(dd) < 20:
            continue
        ra = sim_buyhold(dd, idx); rb = sim_fixed(dd, idx); rc, tr = sim_risk_budget(dd, idx, plu, track=True)
        ma, mb, mc = metrics(ra), metrics(rb), metrics(rc)
        dd_a = ma['max_dd']; dd_c = mc['max_dd']
        improved = (dd_c > dd_a + 3)  # C 回撤比 A 低 >3pct 视为"有效降险"
        outcome = 'success' if improved else ('partial' if dd_c > dd_a else 'failure')
        results['episodes'][name] = {
            'range': f'{a}~{b}', 'n_days': len(dd),
            'A_BuyHold': ma, 'B_Fixed60_40': mb, 'C_AI_RiskBudget_PROXY': mc,
            'C_min_equity': tr['min_equity'], 'C_crisis_days': tr['crisis_days'],
            'proxy_outcome': outcome,
        }
        fail_updates.append((name, tr['min_equity'], tr['crisis_days'], dd_a, dd_c, outcome))

    # 落盘
    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, f'risk_budget_stress_sim_{TODAY}.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print('saved', jp)

    md = render_markdown(results)
    mp = os.path.join(OUT, f'risk_budget_stress_sim_{TODAY}.md')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write(md)
    print('saved', mp)

    html = render_html(results)
    hp = os.path.join(OUT, f'risk_budget_stress_sim_{TODAY}.html')
    with open(hp, 'w', encoding='utf-8') as f:
        f.write(html)
    print('saved', hp)

    # 回填 Failure Log 的 system_state（代理规则在该情景的行为）
    update_failure_log(fail_updates)
    return results


def update_failure_log(fail_updates):
    import sqlite3 as _sql
    con = _sql.connect(DB)
    for name, min_eq, crisis_days, dd_a, dd_c, outcome in fail_updates:
        state = (f"PROXY规则: 情景期最低权益={min_eq}%, Crisis触发={crisis_days}天; "
                 f"最大回撤 A={dd_a}% / C={dd_c}%; 代理判定={outcome}")
        con.execute("UPDATE risk_budget_failure_log SET system_state=?, actual_outcome=? "
                    "WHERE episode LIKE ?", (state, outcome, f'%{name.split("_")[0]}%'))
    con.commit()
    con.close()
    print('updated failure_log system_state for', len(fail_updates), 'episodes')


def render_markdown(res):
    L = []
    L.append('# Risk Budget Rule Stress Simulation（Phase 1.9C · PROXY 模拟）\n')
    L.append('> ⚠️ **本测试使用价格衍生代理信号(PROXY)，不是真实 Risk Temperature。**')
    L.append('> 真实信号仅存在于 2025-07 之后，无法在 2015/2018/2020/2022 回放。')
    L.append('> 本测试仅验证 **Risk Budget RULE 机制**（非线性防御曲线 + Crisis Protocol + 调仓纪律）在真实历史极端行情下的表现；')
    L.append('> **不**验证真实信号预测力。代理信号滞后，结论为该规则的"最差情形下界"，不可外推为模型已通过长周期验证。\n')
    L.append(f'> 生成 {res["generated_at"]} ｜ 收益序列=全A等权(stock_daily) ｜ 成本模型={res["method"]["cost_model"]}\n')
    fp = res['full_period']
    L.append('## 全周期（%s）三策略\n' % fp['range'])
    L.append('| 指标 | A:100%权益 | B:固定60/40 | C:AI Risk Budget(PROXY) |')
    L.append('|---|---|---|---|')
    for key, fmt in [('final_mult','{:.3f}x'),('cagr','{:.2f}'),('max_dd','{:.2f}'),
                     ('sharpe','{:.3f}'),('calmar','{:.3f}'),('recovery','{}'),('worst_month','{:.2f}')]:
        def g(d):
            v = d.get(key) if d else None
            if v is None: return '—'
            return fmt.format(v)
        L.append(f'| {key} | {g(fp["A_BuyHold"])} | {g(fp["B_Fixed60_40"])} | {g(fp["C_AI_RiskBudget_PROXY"])} |')
    L.append(f'\n> C 权益暴露: 最低 {fp["C_equity_stats"]["min_equity"]}%, Crisis 触发 {fp["C_equity_stats"]["crisis_days"]} 天\n')
    L.append('## 四段历史极端情景\n')
    for name, e in res['episodes'].items():
        L.append(f'### {name}（{e["range"]}, {e["n_days"]}日）— 代理判定: {e["proxy_outcome"]}')
        L.append(f'- 最大回撤: A={e["A_BuyHold"]["max_dd"]}% / B={e["B_Fixed60_40"]["max_dd"]}% / C={e["C_AI_RiskBudget_PROXY"]["max_dd"]}%')
        L.append(f'- 最差单月: A={e["A_BuyHold"]["worst_month"]}% / C={e["C_AI_RiskBudget_PROXY"]["worst_month"]}%')
        L.append(f'- C 最低权益={e["C_min_equity"]}%, Crisis触发={e["C_crisis_days"]}天')
        L.append('')
    L.append('## 解读与诚实限制\n')
    L.append('1. 若 C 在四段情景均显著降低最大回撤 → Risk Budget RULE 的防御机制有效（即使仅用滞后价格信号）。')
    L.append('2. 代理信号滞后：规则在崩盘**进行中**才降仓，无法逃顶；真实 Risk Temperature 若含领先成分可能更早，若与价格背离则更差。')
    L.append('3. **真正验收**：真实 Risk Temperature 长周期预测力须等信号累积至 Checkpoint C(2026-12-31) 后，用实时 decision history 回测。')
    L.append('4. 幸存者偏差：stock_daily 仅含当前上市股，历史权益收益向上偏（但三策略同序列可比）。')
    return '\n'.join(L)


def render_html(res):
    fp = res['full_period']
    def row(key, fmt):
        def g(d):
            v = d.get(key) if d else None
            return '—' if v is None else fmt.format(v)
        return f'<tr><td>{key}</td><td>{g(fp["A_BuyHold"])}</td><td>{g(fp["B_Fixed60_40"])}</td><td>{g(fp["C_AI_RiskBudget_PROXY"])}</td></tr>'
    eps = ''
    for name, e in res['episodes'].items():
        eps += (f'<div class="box"><b>{name}</b> （{e["range"]}）— 代理判定: {e["proxy_outcome"]}<br>'
                f'最大回撤 A={e["A_BuyHold"]["max_dd"]}% / C={e["C_AI_RiskBudget_PROXY"]["max_dd"]}% ｜ '
                f'C最低权益={e["C_min_equity"]}% ｜ Crisis触发={e["C_crisis_days"]}天</div>')
    return f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Risk Budget Stress Sim 1.9C</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1218;color:#e6e6e6;padding:32px}}
h1{{color:#ff7f7f}}h2{{color:#7fd1ff}}.warn{{background:#3a1f1f;border:1px solid #803030;color:#ffd0d0;padding:14px;border-radius:8px;line-height:1.7}}
table{{border-collapse:collapse;margin:16px 0;width:100%}}td,th{{border:1px solid #2a2f3a;padding:8px 10px;text-align:center}}
th{{background:#1a2030;color:#9fb3c8}}tr:nth-child(even){{background:#161b24}}.box{{background:#161b24;border:1px solid #2a2f3a;border-radius:8px;padding:12px;margin:10px 0}}
.note{{color:#9aa7b5;font-size:13px;line-height:1.6}}</style></head><body>
<h1>Risk Budget Rule Stress Simulation（Phase 1.9C · PROXY）</h1>
<div class="warn"><b>⚠️ 诚实声明：</b>本测试使用<b>价格衍生代理信号(PROXY)</b>，<b>不是真实 Risk Temperature</b>。
真实信号仅存在于 2025-07 之后，无法在 2015/2018/2020/2022 回放。本测试仅验证
<b>Risk Budget RULE 机制</b>（非线性防御曲线 + Crisis Protocol + 调仓纪律）在真实历史极端行情下的表现；
<b>不</b>验证真实信号预测力。代理信号滞后，结论为该规则的"最差情形下界"，不可外推为模型已通过长周期验证。</div>
<h2>全周期 {fp['range']} 三策略</h2>
<table><tr><th>指标</th><th>A:100%权益</th><th>B:固定60/40</th><th>C:AI Risk Budget(PROXY)</th></tr>
{row('final_mult','{:.3f}x')}{row('cagr','{:.2f}')}{row('max_dd','{:.2f}')}{row('sharpe','{:.3f}')}{row('calmar','{:.3f}')}{row('recovery','{}')}{row('worst_month','{:.2f}')}</table>
<p class="note">C 权益暴露: 最低 {fp['C_equity_stats']['min_equity']}%, Crisis 触发 {fp['C_equity_stats']['crisis_days']} 天</p>
<h2>四段历史极端情景</h2>{eps}
<p class="note">限制：代理信号滞后（崩盘中才降仓，无法逃顶）；真实信号长周期验证须等 Checkpoint C(2026-12-31)；
stock_daily 幸存者偏差向上偏（三策略同序列可比）。</p>
</body></html>'''


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    main()
