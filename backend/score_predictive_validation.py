# -*- coding: utf-8 -*-
"""
Score Predictive Validation (Phase 1.9C)
========================================
目标：验证「Risk Score 本身」有没有预测能力——这是 Phase 1.9B Risk Budget 成立的
前提。如果 score 与未来收益无关，则"score→风险预算"再精巧也是空中楼阁。

方法（诚实口径，复用 1.9A 的全A等权收益序列）：
- 收益序列：stock_daily 构造全A等权日收益（前缀 60/00/30/68；单日收益截断 ±21%）。
  诚实标注：幸存者偏差（向上偏）。
- 分桶：按 risk_score 分 6 档（用户给定映射分界）：
  80-100 / 65-80 / 50-65 / 35-50 / 20-35 / 0-20
- 每桶前瞻 5/20/60 日：均值、中位数、胜率、样本数、min/max。
- 相关性：risk_score 与 未来20日收益（Pearson + Spearman）；与 未来20日最大回撤。
- Score Drawdown Warning：样本内最差 20 日窗口起点前 5/10/20 个交易日，
  score 是否提前下降（这是用户最关心的"风险事件前能否提前降暴露"）。

零未来函数：前瞻收益只用 t 之后数据；score 只用 t 当天值。

输出：output/score_validation_{today}.json / .md
"""
import sqlite3, json, os, datetime, statistics, math

DB = 'database/vibe_research.db'
OUT = 'output'
TODAY = datetime.date.today().strftime('%Y-%m-%d')
HORIZONS = [5, 20, 60]
VALID_PREFIX = ('60', '00', '30', '68')
CAP = 0.21

BUCKETS = [
    (80, 100, '80-100'),
    (65, 80, '65-80'),
    (50, 65, '50-65'),
    (35, 50, '35-50'),
    (20, 35, '20-35'),
    (0, 20, '0-20'),
]


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


def load_regimes(con):
    cur = con.cursor()
    cur.execute("SELECT date, risk_state, risk_score FROM regime_history ORDER BY date")
    return [{'date': d, 'state': st, 'score': sc} for d, st, sc in cur.fetchall()]


def compute_forward(regimes, idx):
    dates = sorted(idx.keys())
    pos = {d: i for i, d in enumerate(dates)}
    for r in regimes:
        d = r['date']
        if d not in pos:
            r['fwd'] = {h: None for h in HORIZONS}
            continue
        i = pos[d]
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


def bucket_of(score):
    if score is None:
        return None
    for lo, hi, label in BUCKETS:
        if lo <= score <= hi:
            return label
    return None


def summarize_by_score(regimes):
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in regimes:
        b = bucket_of(r['score'])
        if b:
            buckets[b].append(r)
    result = {}
    for lo, hi, label in BUCKETS:
        rs = buckets.get(label, [])
        rec = {'range': f'{lo}-{hi}', 'n_total': len(rs), 'horizons': {}}
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
                rec['horizons'][h] = {'n': 0, 'mean': None, 'median': None, 'win_rate': None, 'min': None, 'max': None}
        result[label] = rec
    return result


def correlation(regimes):
    """score vs 未来20日收益；score vs 未来20日最大回撤。"""
    pairs_ret = [(r['score'], r['fwd'][20]) for r in regimes if r['score'] is not None and r['fwd'][20] is not None]
    # max drawdown over next 20d
    dates = sorted(idx_global.keys())
    pos = {d: i for i, d in enumerate(dates)}
    pairs_dd = []
    for r in regimes:
        if r['score'] is None or r['date'] not in pos:
            continue
        i = pos[r['date']]
        if i + 20 < len(dates):
            peak = 1.0
            mdd = 0.0
            eq = 1.0
            for k in range(i + 1, i + 21):
                eq *= (1.0 + idx_global[dates[k]])
                if eq > peak:
                    peak = eq
                dd = eq / peak - 1
                if dd < mdd:
                    mdd = dd
            pairs_dd.append((r['score'], mdd))
    return [_corr(pairs_ret, 'score vs fwd20_ret'), _corr(pairs_dd, 'score vs fwd20_maxdd')]


def _corr(pairs, name):
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    n = len(xs)
    if n < 10:
        return {'name': name, 'n': n, 'pearson': None, 'spearman': None, 'note': '样本不足'}
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    pear = sxy / (sx * sy) if sx > 0 and sy > 0 else None
    # spearman
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0] * len(v)
        for rank_idx, idx_p in enumerate(order):
            rk[idx_p] = rank_idx + 1
        return rk
    rx, ry = rank(xs), rank(ys)
    mrx, mry = statistics.mean(rx), statistics.mean(ry)
    sxy2 = sum((a - mrx) * (b - mry) for a, b in zip(rx, ry))
    sx2 = math.sqrt(sum((a - mrx) ** 2 for a in rx))
    sy2 = math.sqrt(sum((b - mry) ** 2 for b in ry))
    spear = sxy2 / (sx2 * sy2) if sx2 > 0 and sy2 > 0 else None
    return {
        'name': name, 'n': n,
        'pearson': round(pear, 3) if pear is not None else None,
        'spearman': round(spear, 3) if spear is not None else None,
        'note': '正相关=高分未来更易涨 / 高分未来回撤更小',
    }


def drawdown_warning(regimes, idx):
    """最差 20 日窗口起点前 score 轨迹。"""
    dates = sorted(idx.keys())
    worst = None
    for i in range(len(dates) - 20):
        ret = 1.0
        for k in range(i + 1, i + 21):
            ret *= (1.0 + idx[dates[k]])
        fwd = ret - 1
        if worst is None or fwd < worst[1]:
            worst = (dates[i], fwd)
    rmap = {r['date']: r for r in regimes}
    start = worst[0]
    traj = []
    # 找 start 在 dates 的位置
    if start in {d for d, _ in [(x, 0) for x in []]}:
        pass
    # 用 rmap 直接取前后日期
    all_dates = sorted(rmap.keys())
    if start in rmap:
        si = all_dates.index(start)
        for off in [-20, -10, -5, 0, 5, 10, 20]:
            j = si + off
            if 0 <= j < len(all_dates):
                d = all_dates[j]
                traj.append({'offset': off, 'date': d, 'score': rmap[d]['score'], 'state': rmap[d]['state']})
    # 窗口内最低点
    wi = dates.index(start)
    valley_ret = 1.0
    valley_day = start
    eq = 1.0
    peak = 1.0
    for k in range(wi + 1, wi + 21):
        eq *= (1.0 + idx[dates[k]])
        if eq > peak:
            peak = eq
        if (eq / peak - 1) < (valley_ret / peak - 1) or valley_ret == 1.0:
            valley_ret = eq
            valley_day = dates[k]
    return {
        'worst_20d_start': start,
        'worst_20d_return': round(worst[1] * 100, 2),
        'trajectory_around_start': traj,
        'note': '若 start 前 score 已明显下降 → 系统有提前预警能力；若持平/上升 → 无。',
    }


idx_global = {}


def main():
    global idx_global
    con = connect()
    print('[1/4] building equal-weight index...')
    idx = build_equal_weight_index(con)
    idx_global = idx
    print(f'     index days: {len(idx)} ({min(idx)}~{max(idx)})')
    print('[2/4] loading regimes + forward returns...')
    regimes = load_regimes(con)
    regimes = compute_forward(regimes, idx)
    print(f'     regime rows: {len(regimes)}')
    print('[3/4] score buckets + correlation...')
    by_score = summarize_by_score(regimes)
    corr = correlation(regimes)
    print('[4/4] drawdown warning...')
    dd = drawdown_warning(regimes, idx)
    con.close()

    out = {
        'generated_at': TODAY,
        'methodology': {
            'return_series': '全A等权日收益(由 stock_daily 构造)',
            'survivorship_bias': 'stock_daily 仅含当前上市股 → 向上偏',
            'buckets': [b[2] for b in BUCKETS],
            'forward_returns': 't+1..t+H 累计，无未来函数',
        },
        'by_score': by_score,
        'correlation': corr if isinstance(corr, dict) else corr,
        'drawdown_warning': dd,
    }
    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, f'score_validation_{TODAY}.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('saved', jp)

    md = render_markdown(out)
    mp = os.path.join(OUT, f'score_validation_{TODAY}.md')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write(md)
    print('saved', mp)
    return out


def render_markdown(out):
    bs = out['by_score']
    corr = out['correlation']
    if isinstance(corr, list):
        c_ret, c_dd = corr[0], corr[1]
    else:
        c_ret, c_dd = corr, corr
    dd = out['drawdown_warning']
    lines = []
    lines.append('# Score Predictive Validation（Phase 1.9C）\n')
    lines.append(f'> 生成日期：{out["generated_at"]}  ')
    lines.append(f'> 收益序列：{out["methodology"]["return_series"]}  ')
    lines.append(f'> 诚实声明：{out["methodology"]["survivorship_bias"]}；前瞻收益无未来函数。\n')
    lines.append('## 一、按 Risk Score 分桶的前瞻收益（%）\n')
    lines.append('| 分数段 | 样本 | H5均值 | H5胜率 | H20均值 | H20胜率 | H60均值 | H60胜率 |')
    lines.append('|---|---|---|---|---|---|---|---|')
    for label, rec in bs.items():
        h = rec['horizons']
        def g(x):
            vv = h.get(x, {})
            return (f"{vv.get('mean')}%", f"{vv.get('win_rate')}%", f"{vv.get('n')}")
        h5 = g(5); h20 = g(20); h60 = g(60)
        lines.append(f'| {label} | {rec["n_total"]} | {h5[0]} | {h5[1]} | {h20[0]} | {h20[1]} | {h60[0]} | {h60[1]} |')
    lines.append('')
    lines.append('## 二、Risk Score 与未来表现的统计相关性\n')
    for c in (c_ret, c_dd):
        if c.get('n', 0) < 10:
            lines.append(f'- {c["name"]}：样本不足（n={c.get("n")}），无法计算。')
            continue
        pr = c.get('pearson'); sp = c.get('spearman')
        lines.append(f'- {c["name"]}：Pearson={pr}，Spearman={sp}（n={c["n"]}）')
    lines.append('')
    lines.append(' 解读：若 H20 收益与 score 显著正相关（>0.1 且 p<0.05）→ score 有分层能力；'
                 '若接近 0 → score 当前无预测力，Risk Budget 框架需先重构评分。')
    lines.append('')
    lines.append('## 三、Score Drawdown Warning（最差期前 score 轨迹）\n')
    lines.append(f'- 样本内最差 20 日窗口起点：**{dd["worst_20d_start"]}**，窗口收益 **{dd["worst_20d_return"]}%**')
    lines.append('- 起点前 score 轨迹：')
    for t in dd['trajectory_around_start']:
        sign = '+' if t['offset'] >= 0 else ''
        lines.append(f'  - 起点前 {sign}{abs(t["offset"])} 交易日（{t["date"]}）：score={t["score"]}，state={t["state"]}')
    lines.append('')
    lines.append(f'> {dd["note"]}')
    lines.append('')
    lines.append('## 四、结论（供 1.9B 设计参考）\n')
    lines.append('1. 若分桶 H20 收益随分数单调上升 + 相关性显著 → Risk Budget 框架成立，可进入 1.9B 实现。')
    lines.append('2. 若分数与收益无关 → 必须先重构 risk_score（Phase 1.9C 卡住，不进 1.9B）。')
    lines.append('3. Drawdown Warning 轨迹揭示 score 在真实风险事件前是否下降——这是 AI CIO v0.1 验收标准③的直接依据。')
    lines.append('')
    lines.append('> 注：样本 247 交易日，高风险区间（80-100）样本极少，分桶结论需谨慎；幸存者偏差使收益偏乐观。')
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
