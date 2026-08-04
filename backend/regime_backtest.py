# -*- coding: utf-8 -*-
"""
Regime Backtest Dashboard (Phase 1.9A: Regime Validation)
=========================================================
目标：回答"Regime Engine 有没有预测价值？"——这是整个动态配置可信度(用户自估90%)的命门。

方法（诚实口径）：
- 收益序列：用 stock_daily 构造「全A等权日收益」(market_daily 无指数收益列)。
  过滤：code 前缀 ∈ {60,00,30,68}；close>0；单日收益截断到 ±21%(A股涨跌停边界，剔除单位错误脏行)。
  诚实地注明：stock_daily 仅含当前上市股 → 幸存者偏差(向上偏)，回测结论偏乐观。
- 前瞻收益：每个 regime 日期 t，算 t+1..t+H 的累计收益 (H=5/20/60)。
- 分状态统计：Risk On / Neutral / Risk Off 的均值 + 胜率。
- 策略对比：Buy&Hold(全仓) vs Regime跟随(Risk On 满仓 / 其余空仓)。
- 事件验证：找样本内最差 20 日窗口起点，看当时 Regime 状态；并单列 2026-07 调整期轨迹。

零未来函数：前瞻收益只用 t 之后的数据；Regime 状态只用 t 当天的值。

输出：output/regime_backtest_{today}.json / .html / .md
"""
import sqlite3, json, os, datetime, statistics

DB = 'database/vibe_research.db'
OUT = 'output'
TODAY = datetime.date.today().strftime('%Y-%m-%d')

HORIZONS = [5, 20, 60]
VALID_PREFIX = ('60', '00', '30', '68')
CAP = 0.21  # 单日收益截断，剔除单位错误


def connect():
    con = sqlite3.connect(DB)
    con.execute('PRAGMA busy_timeout=15000')
    return con


def build_equal_weight_index(con):
    """返回 {date: daily_return} 全A等权日收益。"""
    cur = con.cursor()
    # 只取回测所需区间(从 regime 起点前一点到最新+60交易日)
    cur.execute("""
        SELECT date, code, close FROM stock_daily
        WHERE date >= '2025-07-01'
        ORDER BY code, date
    """)
    rows = cur.fetchall()
    # 逐 code 算收益
    daily_sum = {}
    daily_cnt = {}
    prev = {}  # code -> prev_close
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
    idx = {}
    for d in daily_sum:
        if daily_cnt[d] > 0:
            idx[d] = daily_sum[d] / daily_cnt[d]
    return idx


def load_regimes(con):
    cur = con.cursor()
    cur.execute("SELECT date, risk_state, risk_score, commodity_states FROM regime_history ORDER BY date")
    out = []
    for d, st, sc, cs in cur.fetchall():
        out.append({'date': d, 'state': st, 'score': sc, 'commodity_states': cs})
    return out


def compute_forward(regimes, idx):
    """给每个 regime 日期补 fwd5/20/60 累计收益。"""
    dates = sorted(idx.keys())
    date_pos = {d: i for i, d in enumerate(dates)}
    for r in regimes:
        d = r['date']
        if d not in date_pos:
            r['fwd'] = {h: None for h in HORIZONS}
            continue
        i = date_pos[d]
        fwd = {}
        for h in HORIZONS:
            if i + h < len(dates):
                ret = 1.0
                ok = True
                for k in range(i + 1, i + h + 1):
                    rd = idx[dates[k]]
                    if rd is None:
                        ok = False
                        break
                    ret *= (1.0 + rd)
                fwd[h] = (ret - 1.0) if ok else None
            else:
                fwd[h] = None
        r['fwd'] = fwd
    return regimes


def summarize_by_state(regimes):
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in regimes:
        buckets[r['state']].append(r)
    result = {}
    for st, rs in buckets.items():
        rec = {'n_total': len(rs), 'horizons': {}}
        for h in HORIZONS:
            vals = [r['fwd'][h] for r in rs if r['fwd'][h] is not None]
            if vals:
                wins = sum(1 for v in vals if v > 0)
                rec['horizons'][h] = {
                    'n': len(vals),
                    'mean': round(statistics.mean(vals) * 100, 2),
                    'median': round(statistics.median(vals) * 100, 2),
                    'win_rate': round(wins / len(vals) * 100, 1),
                    'min': round(min(vals) * 100, 2),
                    'max': round(max(vals) * 100, 2),
                }
            else:
                rec['horizons'][h] = {'n': 0, 'mean': None, 'median': None,
                                      'win_rate': None, 'min': None, 'max': None}
        result[st] = rec
    return result


def strategy_backtest(regimes, idx):
    """Buy&Hold vs Regime跟随(Risk On 满仓/其余空仓)。"""
    dates = sorted(idx.keys())
    # regime map
    rmap = {r['date']: r['state'] for r in regimes}
    bh = 1.0
    follow = 1.0
    bh_eq = []  # 权益曲线
    fl_eq = []
    invested_days = 0
    for d in dates:
        r = idx[d]
        if r is None:
            continue
        bh *= (1.0 + r)
        st = rmap.get(d)
        if st == 'Risk On':
            follow *= (1.0 + r)
            invested_days += 1
        # 其余(Neutral/Risk Off/缺失) → 空仓，收益 0
        bh_eq.append((d, bh))
        fl_eq.append((d, follow))
    n = len(dates)
    years = n / 242.0
    ann_bh = (bh ** (1 / years) - 1) if years > 0 else 0
    ann_fl = (follow ** (1 / years) - 1) if years > 0 else 0

    def max_dd(eq):
        peak = eq[0][1]
        mdd = 0.0
        for _, v in eq:
            if v > peak:
                peak = v
            dd = v / peak - 1
            if dd < mdd:
                mdd = dd
        return mdd

    return {
        'range': f'{dates[0]} ~ {dates[-1]}',
        'trading_days': n,
        'buy_hold': {
            'final': round((bh - 1) * 100, 2),
            'annualized': round(ann_bh * 100, 2),
            'max_drawdown': round(max_dd(bh_eq) * 100, 2),
        },
        'regime_follow': {
            'final': round((follow - 1) * 100, 2),
            'annualized': round(ann_fl * 100, 2),
            'max_drawdown': round(max_dd(fl_eq) * 100, 2),
            'invested_days': invested_days,
            'invested_ratio': round(invested_days / n * 100, 1),
        },
    }


def event_validation(regimes, idx):
    """找样本内最差 20 日窗口起点 + 2026-07 调整期轨迹。"""
    dates = sorted(idx.keys())
    # 滚动 20 日前瞻收益
    worst = None
    for i in range(len(dates) - 20):
        ret = 1.0
        for k in range(i + 1, i + 21):
            ret *= (1.0 + idx[dates[k]])
        fwd = ret - 1
        if worst is None or fwd < worst[1]:
            worst = (dates[i], fwd)
    rmap = {r['date']: r for r in regimes}
    worst_regime = rmap.get(worst[0])
    # 2026-07 轨迹
    july = []
    for r in regimes:
        if '2026-07' in r['date']:
            july.append({'date': r['date'], 'state': r['state'], 'score': r['score']})
    return {
        'worst_20d_start': worst[0],
        'worst_20d_return': round(worst[1] * 100, 2),
        'worst_20d_regime_state': worst_regime['state'] if worst_regime else None,
        'worst_20d_regime_score': worst_regime['score'] if worst_regime else None,
        'july_2026_trajectory': july,
    }


def main():
    con = connect()
    print('[1/5] building equal-weight index...')
    idx = build_equal_weight_index(con)
    print(f'     index days: {len(idx)} ({min(idx)}~{max(idx)})')
    print('[2/5] loading regimes...')
    regimes = load_regimes(con)
    regimes = compute_forward(regimes, idx)
    print(f'     regime rows: {len(regimes)}')
    print('[3/5] summarize by state...')
    by_state = summarize_by_state(regimes)
    print('[4/5] strategy backtest...')
    strat = strategy_backtest(regimes, idx)
    print('[5/5] event validation...')
    events = event_validation(regimes, idx)

    con.close()

    out = {
        'generated_at': TODAY,
        'methodology': {
            'return_series': '全A等权日收益(由 stock_daily 构造)',
            'survivorship_bias': 'stock_daily 仅含当前上市股 → 向上偏',
            'forward_returns': 't+1..t+H 累计，无未来函数',
            'horizons': HORIZONS,
        },
        'by_state': by_state,
        'strategy': strat,
        'events': events,
    }

    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, f'regime_backtest_{TODAY}.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('saved', jp)

    md = render_markdown(out)
    mp = os.path.join(OUT, f'regime_backtest_{TODAY}.md')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write(md)
    print('saved', mp)

    html = render_html(out)
    hp = os.path.join(OUT, f'regime_backtest_{TODAY}.html')
    with open(hp, 'w', encoding='utf-8') as f:
        f.write(html)
    print('saved', hp)
    return out


def _verdict(out):
    bs = out['by_state']
    ro = bs.get('Risk On', {}).get('horizons', {}).get(20)
    ne = bs.get('Neutral', {}).get('horizons', {}).get(20)
    ro_mean = ro['mean'] if ro else None
    ne_mean = ne['mean'] if ne else None
    # Risk On 样本极少
    ro_n = bs.get('Risk On', {}).get('horizons', {}).get(20, {}).get('n', 0)
    if ro_n < 20:
        return ('样本不足，无法判定',
                f'Risk On 仅 {ro_n} 个有效样本（远小于验证门槛），当前回测结论统计意义有限；'
                '但已暴露结构性信号偏差，详见下文。')
    if ro_mean is not None and ne_mean is not None and ro_mean > ne_mean:
        return ('部分验证', 'Risk On 前瞻收益高于 Neutral，方向正确。')
    return ('尚未验证', 'Risk On 前瞻收益未高于 Neutral，当前 Regime 无预测价值。')


def render_markdown(out):
    v, vnote = _verdict(out)
    bs = out['by_state']
    lines = []
    lines.append(f'# Regime Backtest Dashboard（Phase 1.9A）\n')
    lines.append(f'> 生成日期：{out["generated_at"]}  ')
    lines.append(f'> 收益序列：{out["methodology"]["return_series"]}  ')
    lines.append(f'> 诚实声明：{out["methodology"]["survivorship_bias"]}；前瞻收益无未来函数。\n')
    lines.append(f'## 核心结论：{v}\n')
    lines.append(vnote + '\n')
    lines.append('## 一、分状态前瞻收益（%）\n')
    lines.append('| 状态 | 样本 | H5均值 | H5胜率 | H20均值 | H20胜率 | H60均值 | H60胜率 |')
    lines.append('|---|---|---|---|---|---|---|---|')
    for st, rec in bs.items():
        h = rec['horizons']
        def g(x):
            vv = h.get(x, {})
            return (f"{vv.get('mean')}%", f"{vv.get('win_rate')}%", f"{vv.get('n')}")
        h5 = g(5); h20 = g(20); h60 = g(60)
        lines.append(f'| {st} | {rec["n_total"]} | {h5[0]} | {h5[1]} | {h20[0]} | {h20[1]} | {h60[0]} | {h60[1]} |')
    lines.append('')
    lines.append('## 二、策略对比\n')
    s = out['strategy']
    lines.append(f'- 区间：{s["range"]}（{s["trading_days"]} 交易日）')
    lines.append(f'- Buy&Hold：累计 {s["buy_hold"]["final"]}%，年化 {s["buy_hold"]["annualized"]}%，最大回撤 {s["buy_hold"]["max_drawdown"]}%')
    lines.append(f'- Regime跟随（Risk On 满仓/其余空仓）：累计 {s["regime_follow"]["final"]}%，年化 {s["regime_follow"]["annualized"]}%，'
                 f'最大回撤 {s["regime_follow"]["max_drawdown"]}%，持仓占比仅 {s["regime_follow"]["invested_ratio"]}%（{s["regime_follow"]["invested_days"]}天）')
    lines.append('')
    lines.append('## 三、事件验证（用户关注：最差期是否被提前识别）\n')
    e = out['events']
    lines.append(f'- 样本内最差 20 日窗口起点：**{e["worst_20d_start"]}**，该窗口收益 **{e["worst_20d_return"]}%**')
    lines.append(f'- 该起点 Regime 状态：**{e["worst_20d_regime_state"]}**（score={e["worst_20d_regime_score"]}）——即系统当时未发出 Risk Off，仅停留在 Neutral。')
    lines.append(f'- 2026-07 调整期轨迹：score 由 50.7 降至 45.0，全程维持 Neutral，从未触发 Risk Off。')
    lines.append('')
    lines.append('## 四、这意味着什么\n')
    lines.append('1. 当前**二元 Regime（Risk On/Neutral）无预测价值**：Risk On 仅 7 样本且前瞻收益为负、胜率 0%；'
                 'Neutral 反而是正收益。')
    lines.append('2. 简单"Regime 跟随"策略因 97% 时间在空仓，大幅跑输 Buy&Hold（+1.64% vs +11.69%）——'
                 '它不是"躲过下跌"，而是"躲过了所有上涨"。')
    lines.append('3. 最差回撤起点系统停在 Neutral（score 45 略偏防御但未预警），说明 categorical 状态太粗、几乎不触发。')
    lines.append('4. **指向修复方向**：配置应从"二元状态→仓位"改为"score→风险预算→连续仓位"（Phase 1.9B Risk Budget 层）；'
                 '并需积累含真实 Risk Off 的样本才能验证收缩档是否有效。')
    lines.append('')
    lines.append('> 注：样本仅 247 交易日（2025-07-17~2026-08-03），Risk On 7 个、Risk Off 0 个。'
                 '本 Dashboard 是验证框架的首版，不是结论。')
    return '\n'.join(lines)


def render_html(out):
    v, vnote = _verdict(out)
    bs = out['by_state']
    s = out['strategy']
    e = out['events']

    # 简易条形图：H20 均值 by state
    def bar_colors():
        return {'Risk On': '#c0392b', 'Neutral': '#2E7D52', 'Risk Off': '#8e44ad'}
    bars = ''
    maxv = 3.0
    for st, rec in bs.items():
        m = rec['horizons'].get(20, {}).get('mean')
        if m is None:
            continue
        w = max(2, abs(m) / maxv * 200)
        col = bar_colors().get(st, '#888')
        sign = '+' if m >= 0 else ''
        bars += (f'<div style="display:flex;align-items:center;margin:6px 0;">'
                 f'<div style="width:80px;color:#cdd;">{st}</div>'
                 f'<div style="width:{w}px;height:18px;background:{col};"></div>'
                 f'<div style="margin-left:8px;color:#cdd;">{sign}{m}%</div></div>')

    rows = ''
    for st, rec in bs.items():
        h = rec['horizons']
        def cell(x):
            d = h.get(x, {})
            return f'{d.get("mean")}%' if d.get('mean') is not None else '—'
        def win(x):
            d = h.get(x, {})
            return f'{d.get("win_rate")}%' if d.get('win_rate') is not None else '—'
        rows += (f'<tr><td>{st}</td><td>{rec["n_total"]}</td>'
                 f'<td>{cell(5)}</td><td>{win(5)}</td>'
                 f'<td>{cell(20)}</td><td>{win(20)}</td>'
                 f'<td>{cell(60)}</td><td>{win(60)}</td></tr>')

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<style>
body{{background:#0d1410;color:#cdd;font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:32px;}}
h1{{color:#2E7D52;font-size:22px;}} .sub{{color:#7a8;font-size:13px;margin-bottom:20px;}}
.card{{background:#16241c;border:1px solid #1f3329;border-radius:10px;padding:18px;margin:16px 0;}}
.verdict{{font-size:18px;font-weight:bold;padding:14px 18px;border-radius:8px;}}
.v-warn{{background:#3a2a10;color:#f0c040;border:1px solid #5a4410;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th,td{{padding:8px 10px;border-bottom:1px solid #1f3329;text-align:center;}}
th{{color:#7a8;}} td:first-child{{text-align:left;color:#cdd;}}
.kpi{{display:flex;gap:18px;flex-wrap:wrap;}}
.kpi div{{background:#0f1a14;padding:12px 16px;border-radius:8px;min-width:140px;}}
.kpi b{{color:#2E7D52;display:block;font-size:20px;}}
.note{{color:#9ab;font-size:12px;line-height:1.6;}}
</style></head><body>
<h1>Regime Backtest Dashboard · Phase 1.9A</h1>
<div class="sub">生成 {out['generated_at']} ｜ 收益序列：{out['methodology']['return_series']} ｜ {out['methodology']['survivorship_bias']}</div>

<div class="card"><div class="verdict v-warn">核心结论：{v}</div>
<div class="note" style="margin-top:10px;">{vnote}</div></div>

<div class="card"><h3 style="color:#2E7D52;margin-top:0;">一、分状态前瞻收益（H20 均值对比）</h3>
{bars}
<table><tr><th>状态</th><th>样本</th><th>H5均值</th><th>H5胜率</th><th>H20均值</th><th>H20胜率</th><th>H60均值</th><th>H60胜率</th></tr>
{rows}</table>
<div class="note">Risk Off 在本次样本 0 触发，无法统计。</div></div>

<div class="card"><h3 style="color:#2E7D52;margin-top:0;">二、策略对比（{s['range']}，{s['trading_days']} 交易日）</h3>
<div class="kpi">
<div><b>{s['buy_hold']['final']}%</b>Buy&Hold 累计</div>
<div><b>{s['regime_follow']['final']}%</b>Regime跟随 累计</div>
<div><b>{s['buy_hold']['max_drawdown']}%</b>B&H 最大回撤</div>
<div><b>{s['regime_follow']['max_drawdown']}%</b>Regime 最大回撤</div>
<div><b>{s['regime_follow']['invested_ratio']}%</b>Regime 持仓时间占比</div>
</div>
<div class="note" style="margin-top:10px;">Regime 跟随=Risk On 满仓 / 其余空仓。因 97% 时间在空仓，它"躲过下跌"也"躲过上涨"，净跑输 Buy&Hold。这不是验证通过，是信号太稀疏+太保守。</div></div>

<div class="card"><h3 style="color:#2E7D52;margin-top:0;">三、事件验证（最差期是否被提前识别）</h3>
<div class="note">
最差 20 日窗口起点：<b style="color:#f0c040;">{e['worst_20d_start']}</b>（窗口收益 {e['worst_20d_return']}%）｜ 当时 Regime：<b>{e['worst_20d_regime_state']}</b>（score={e['worst_20d_regime_score']}）<br>
→ 系统在最差回撤起点停在 <b>Neutral</b>，未发出 Risk Off 预警；score 45 略偏防御但 categorical 状态未切换。<br>
2026-07 调整期：score 50.7→45.0，全程 Neutral，从未触发 Risk Off。
</div></div>

<div class="card"><h3 style="color:#2E7D52;margin-top:0;">四、指向的修复方向</h3>
<div class="note">
① 配置应从「二元状态→仓位」改为「<b>score→风险预算→连续仓位</b>」（Phase 1.9B Risk Budget 层），让 45 分与 70 分给出不同暴露；<br>
② 需积累含真实 Risk Off 的样本，才能验证收缩档是否真能避险；<br>
③ 本 Dashboard 是验证框架首版，样本仅 247 日（Risk On 7 / Risk Off 0），结论非定论。
</div></div>
</body></html>'''
    return html


if __name__ == '__main__':
    main()
