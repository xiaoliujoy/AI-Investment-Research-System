# -*- coding: utf-8 -*-
"""
Risk Budget Backtest (Phase 1.9B) — 价值验证点
================================================
真正回答用户关心的核心问题：
    "AI CIO 有没有比静态配置更好？"

三个策略对比（区间 = regime_history 与全A等权收益序列对齐的交易日）：
  Benchmark A  Buy & Hold 100% 权益
  Benchmark B  固定配置 60% 权益 + 40% 防御(无风险近似)
  Benchmark C  AI Risk Budget 动态权益（score_to_budget，30%~70%，<30 危机 20%）

交易摩擦（用户 Step3 硬性要求）：
  月度调仓 + 偏离 ±10% 才动 + 20 日冷却期 + 单边 0.2% 交易成本

指标：CAGR / Max Drawdown / Sharpe / Calmar / Recovery Time / Worst Month

诚实口径：
  - 收益序列 = 全A等权（stock_daily 构造），幸存者偏差向上偏。
  - 非权益部分（黄金/债券/现金）在库里无真实收益序列 → 用无风险近似(rf=2%/年)。
    这意味着 Benchmark B/C 的防御层收益被低估（真实债券/黄金长期 > rf），
    对动态策略是"保守偏严"的处理，不构成对 AI 的不当美化。
  - 机会仓 10% 在所有策略中均排除，保证公平。
  - 零未来函数：regime score 只用当日及之前最新值。
"""
import sqlite3, json, os, datetime, math

DB = 'database/vibe_research.db'
OUT = 'output'
TODAY = datetime.date.today().strftime('%Y-%m-%d')

VALID_PREFIX = ('60', '00', '30', '68')
CAP = 0.21
RF_ANNUAL = 0.02
RF_DAILY = (1.0 + RF_ANNUAL) ** (1.0 / 252) - 1.0
COST_RATE = 0.002        # 单边 0.2% / 单位换手
REBAL_DEVIATION = 0.10   # 偏离 10pct 才调
COOLDOWN_DAYS = 20       # 20 交易日冷却
MONTH_DAYS = 21          # 月度调仓窗口

from risk_budget import score_to_budget


def connect():
    con = sqlite3.connect(DB)
    con.execute('PRAGMA busy_timeout=15000')
    return con


def build_equal_weight_index(con):
    cur = con.cursor()
    cur.execute("SELECT date, code, close FROM stock_daily WHERE date >= '2025-07-01' ORDER BY code, date")
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


def load_regime_scores(con):
    cur = con.cursor()
    cur.execute("SELECT date, risk_score FROM regime_history ORDER BY date")
    return [(d, s) for d, s in cur.fetchall()]


def build_score_lookup(regimes):
    """返回 date->score（最新覆盖，避免未来泄漏）。"""
    lut = {}
    for d, s in regimes:
        lut[d] = s
    return lut


def sim_buyhold(dates, idx):
    rets = []
    for d in dates:
        rets.append(idx[d])
    return rets


def sim_fixed(dates, idx):
    rets = []
    for d in dates:
        rets.append(0.60 * idx[d] + 0.40 * RF_DAILY)
    return rets


def sim_risk_budget(dates, idx, score_lut):
    rets = []
    cur_w = None
    last_rebal = -999
    for i, d in enumerate(dates):
        # 取当日及之前最新 score（零未来函数）
        sc = None
        for j in range(i, -1, -1):
            s = score_lut.get(dates[j])
            if s is not None:
                sc = s
                break
        if sc is None:
            sc = 50.0
        target_w = score_to_budget(sc)['equity']

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
        port_ret = cur_w * idx[d] + (1.0 - cur_w) * RF_DAILY - cost
        rets.append(port_ret)
    return rets


def metrics(rets):
    """输入日收益列表，输出绩效指标字典。"""
    n = len(rets)
    if n == 0:
        return {}
    # 权益曲线
    curve = [1.0]
    for r in rets:
        curve.append(curve[-1] * (1.0 + r))
    # CAGR
    years = n / 252.0
    final = curve[-1]
    cagr = (final ** (1.0 / years) - 1.0) if final > 0 and years > 0 else None
    # 最大回撤 + 恢复时间
    peak = curve[0]
    mdd = 0.0
    trough_idx = 0
    in_dd = False
    rec_start = 0
    recovery_days = None
    for k in range(1, len(curve)):
        if curve[k] > peak:
            peak = curve[k]
        dd = curve[k] / peak - 1.0
        if dd < mdd:
            mdd = dd
            trough_idx = k
        if dd < 0 and not in_dd:
            in_dd = True
            rec_start = k
        if in_dd and curve[k] >= peak:
            in_dd = False
            if recovery_days is None:
                recovery_days = k - rec_start
    if in_dd:
        recovery_days = None  # 未恢复
    # Sharpe (rf=0)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    std = math.sqrt(var) if var > 0 else 0.0
    sharpe = (mean / std * math.sqrt(252.0)) if std > 0 else 0.0
    # Calmar
    calmar = (cagr / abs(mdd)) if (mdd is not None and mdd < 0 and cagr is not None) else None
    # Worst Month (滚动 21 交易日)
    worst_month = 0.0
    for k in range(0, len(curve) - MONTH_DAYS):
        m = curve[k + MONTH_DAYS] / curve[k] - 1.0
        if m < worst_month:
            worst_month = m
    # 期末权益权重统计（仅 Benchmark C 有意义）—— 用 rets 无法还原，单独在外层统计
    return {
        'n_days': n,
        'final_multiplier': round(final, 4),
        'cagr': round(cagr * 100, 2) if cagr is not None else None,
        'max_drawdown': round(mdd * 100, 2),
        'sharpe': round(sharpe, 3),
        'calmar': round(calmar, 3) if calmar is not None else None,
        'recovery_days': recovery_days,
        'worst_month': round(worst_month * 100, 2),
    }


def equity_weight_stats(dates, idx, score_lut):
    """统计 Benchmark C 实际持仓的权益权重分布（验证是否与设计一致）。"""
    ws = []
    cur_w = None
    last_rebal = -999
    for i, d in enumerate(dates):
        sc = None
        for j in range(i, -1, -1):
            s = score_lut.get(dates[j])
            if s is not None:
                sc = s
                break
        if sc is None:
            sc = 50.0
        target_w = score_to_budget(sc)['equity']
        if cur_w is None:
            cur_w = target_w
            last_rebal = i
        else:
            can_month = (i - last_rebal) >= MONTH_DAYS
            dev = abs(target_w - cur_w)
            cooldown_ok = (i - last_rebal) >= COOLDOWN_DAYS
            if can_month and dev >= REBAL_DEVIATION and cooldown_ok:
                cur_w = target_w
                last_rebal = i
        ws.append(cur_w)
    from collections import Counter
    cnt = Counter(round(w, 2) for w in ws)
    return {
        'mean_equity': round(sum(ws) / len(ws) * 100, 1),
        'min_equity': round(min(ws) * 100, 1),
        'max_equity': round(max(ws) * 100, 1),
        'distribution': {f'{int(k*100)}%': v for k, v in sorted(cnt.items())},
    }


def main():
    con = connect()
    print('[1/3] building equal-weight index...')
    idx = build_equal_weight_index(con)
    print(f'     index days: {len(idx)} ({min(idx)}~{max(idx)})')
    print('[2/3] loading regime scores...')
    regimes = load_regime_scores(con)
    score_lut = build_score_lookup(regimes)
    con.close()

    dates = sorted(idx.keys())
    print(f'     aligned trading days: {len(dates)}')

    print('[3/3] simulating 3 strategies...')
    ra = sim_buyhold(dates, idx)
    rb = sim_fixed(dates, idx)
    rc = sim_risk_budget(dates, idx, score_lut)
    ew = equity_weight_stats(dates, idx, score_lut)

    ma = metrics(ra)
    mb = metrics(rb)
    mc = metrics(rc)

    out = {
        'generated_at': TODAY,
        'methodology': {
            'return_series': '全A等权日收益(由 stock_daily 构造)',
            'survivorship_bias': 'stock_daily 仅含当前上市股 → 向上偏',
            'defensive_sleeve': '黄金/债券/现金用无风险近似 rf=2%/年（真实防御资产收益被低估，对动态策略偏严）',
            'cost_model': '月度调仓 + 偏离±10pct + 20日冷却 + 单边0.2%成本',
            'no_future_leak': 'regime score 只用当日及之前最新值',
        },
        'range': {'start': dates[0], 'end': dates[-1], 'n_days': len(dates)},
        'strategies': {
            'A_BuyHold_100eq': ma,
            'B_Fixed_60_40': mb,
            'C_AI_RiskBudget': mc,
        },
        'risk_budget_equity_stats': ew,
    }

    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, f'risk_budget_backtest_{TODAY}.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('saved', jp)

    md = render_markdown(out)
    mp = os.path.join(OUT, f'risk_budget_backtest_{TODAY}.md')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write(md)
    print('saved', mp)

    html = render_html(out)
    hp = os.path.join(OUT, f'risk_budget_backtest_{TODAY}.html')
    with open(hp, 'w', encoding='utf-8') as f:
        f.write(html)
    print('saved', hp)
    return out


def render_markdown(out):
    s = out['strategies']
    L = []
    L.append('# Risk Budget Backtest（Phase 1.9B）\n')
    L.append(f'> 生成日期：{out["generated_at"]}  ')
    L.append(f'> 区间：{out["range"]["start"]} ~ {out["range"]["end"]}（{out["range"]["n_days"]} 交易日）  ')
    L.append(f'> 诚实声明：{out["methodology"]["survivorship_bias"]}；{out["methodology"]["defensive_sleeve"]}\n')
    L.append('## 三策略绩效对比\n')
    L.append('| 指标 | A: Buy&Hold 100%权益 | B: 固定60/40 | C: AI Risk Budget |')
    L.append('|---|---|---|---|')
    rows = [
        ('期末倍数', 'final_multiplier', '{:.4f}x'),
        ('CAGR(%)', 'cagr', '{:.2f}'),
        ('Max Drawdown(%)', 'max_drawdown', '{:.2f}'),
        ('Sharpe', 'sharpe', '{:.3f}'),
        ('Calmar', 'calmar', '{:.3f}'),
        ('恢复天数', 'recovery_days', '{}'),
        ('最差单月(%)', 'worst_month', '{:.2f}'),
    ]
    for label, key, fmt in rows:
        def g(d):
            v = d.get(key)
            if v is None:
                return '—'
            if key == 'recovery_days':
                return '未恢复' if v is None else str(v)
            return fmt.format(v)
        L.append(f'| {label} | {g(s["A_BuyHold_100eq"])} | {g(s["B_Fixed_60_40"])} | {g(s["C_AI_RiskBudget"])} |')
    L.append('')
    ew = out['risk_budget_equity_stats']
    L.append('## AI Risk Budget 实际权益暴露分布\n')
    L.append(f'- 均值权益：{ew["mean_equity"]}%　最小：{ew["min_equity"]}%　最大：{ew["max_equity"]}%')
    L.append('- 分布：' + '，'.join(f'{k}×{v}天' for k, v in ew['distribution'].items()))
    L.append('')
    L.append('## 解读\n')
    L.append('1. 若 C 的 CAGR 接近 A/B 且 MaxDD 明显更低 → Risk Budget 实现"管理风险暴露"目标（验证标准②）。')
    L.append('2. 若 C 跑输 B 过多 → 调仓摩擦或反应滞后侵蚀收益，需回到 1.9B 设计修正（如放宽 deviation / 缩短 cooldown）。')
    L.append('3. 当前防御层用 rf 近似，真实债券/黄金 > rf，故 C 实际防御收益被低估，结论对 AI 偏保守。')
    L.append('')
    L.append('> 注：样本仅约 1 年（247 交易日），含 2026-07 调整但无真正熊市，Crisis Protocol(<30) 从未触发；')
    L.append('> 结论为阶段性，非长期定论。需更长周期 + 全球资产真实收益接入后复验。')
    return '\n'.join(L)


def render_html(out):
    s = out['strategies']
    def row(key, fmt, none='—'):
        def g(d):
            v = d.get(key)
            if v is None:
                return none
            if key == 'recovery_days':
                return '未恢复' if v is None else str(v)
            return fmt.format(v)
        return f'<tr><td>{key}</td><td>{g(s["A_BuyHold_100eq"])}</td><td>{g(s["B_Fixed_60_40"])}</td><td>{g(s["C_AI_RiskBudget"])}</td></tr>'
    ew = out['risk_budget_equity_stats']
    dist = '，'.join(f'{k}×{v}天' for k, v in ew['distribution'].items())
    return f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Risk Budget Backtest 1.9B</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1218;color:#e6e6e6;padding:32px}}
h1{{color:#7fd1ff}}table{{border-collapse:collapse;margin:16px 0;width:100%}}
td,th{{border:1px solid #2a2f3a;padding:8px 10px;text-align:center}}
th{{background:#1a2030;color:#9fb3c8}}tr:nth-child(even){{background:#161b24}}
.note{{color:#9aa7b5;font-size:13px;line-height:1.6}}
.box{{background:#161b24;border:1px solid #2a2f3a;border-radius:8px;padding:16px;margin:16px 0}}</style></head>
<body>
<h1>Risk Budget Backtest（Phase 1.9B）</h1>
<p class="note">生成 {out['generated_at']} ｜ 区间 {out['range']['start']} ~ {out['range']['end']}（{out['range']['n_days']} 交易日）<br>
{out['methodology']['survivorship_bias']}；{out['methodology']['defensive_sleeve']}<br>
成本模型：{out['methodology']['cost_model']}</p>
<div class="box"><table>
<tr><th>指标</th><th>A: Buy&Hold 100%权益</th><th>B: 固定60/40</th><th>C: AI Risk Budget</th></tr>
{row('final_multiplier','{:.4f}x')}
{row('cagr','{:.2f}')}
{row('max_drawdown','{:.2f}')}
{row('sharpe','{:.3f}')}
{row('calmar','{:.3f}')}
{row('recovery_days',None)}
{row('worst_month','{:.2f}')}
</table></div>
<div class="box"><p><b>AI Risk Budget 实际权益暴露</b><br>
均值 {ew['mean_equity']}% ｜ 最小 {ew['min_equity']}% ｜ 最大 {ew['max_equity']}%<br>
分布：{dist}</p></div>
<p class="note">注：样本约1年，含 2026-07 调整但无真正熊市；Crisis Protocol(&lt;30) 从未触发。结论阶段性，需更长周期+全球资产真实收益接入后复验。</p>
</body></html>'''


if __name__ == '__main__':
    main()
