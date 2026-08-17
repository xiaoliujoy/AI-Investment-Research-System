# -*- coding: utf-8 -*-
"""
四层一致性审计 (2026-08-01 ~ 2026-08-17) —— 离线只读，绝不修改任何生产代码。

层级:
  L1 市场事实   : stock_daily / sector_daily / market_daily (本地库, 至 2026-08-17)
  L2 Brain/IC   : backend/output/archive/brain_report_2026-08-*.json
  L3 CIO/Composite: memo_*_wechat.html 综合评分 + brain_report L7/资金维度
  L4 用户驾驶舱 : memo_*_wechat.html 今日裁决

输出:
  backend/audit/audit_aug.json        结构化结果
  backend/audit/audit_aug_report.md   人类可读报告
"""
import json, glob, os, re, sqlite3
from collections import defaultdict, OrderedDict

ROOT = "C:/Users/JOY/WorkBuddy/个人AI研投系统"
DB   = os.path.join(ROOT, "backend/database/vibe_research.db")
OUT  = os.path.join(ROOT, "backend/audit")
os.makedirs(OUT, exist_ok=True)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ---------------------------------------------------------------------------
# L1 市场事实
# ---------------------------------------------------------------------------
def market_facts():
    # 全A等权日收益 (市场代理) + 上涨占比
    cur.execute("""
        SELECT date, AVG(change_pct) ew,
               SUM(CASE WHEN change_pct>0 THEN 1 ELSE 0 END)*1.0/COUNT(*) up_pct,
               SUM(CASE WHEN change_pct>=9.8 THEN 1 ELSE 0 END) lim_up,
               SUM(CASE WHEN change_pct<=-9.8 THEN 1 ELSE 0 END) lim_dn
        FROM stock_daily
        WHERE date BETWEEN '2026-08-01' AND '2026-08-17'
        GROUP BY date ORDER BY date
    """)
    m = {}
    for r in cur.fetchall():
        m[r['date']] = dict(ew=round(r['ew'],3), up_pct=round(r['up_pct']*100,1),
                            lim_up=r['lim_up'], lim_dn=r['lim_dn'])
    # 行业强弱: sector_daily (至 2026-08-14)
    cur.execute("""
        SELECT date, sector_name, change_pct, net_amount, tier, leader_name, consecutive_days, days_in_top5
        FROM sector_daily
        WHERE date BETWEEN '2026-08-01' AND '2026-08-14'
    """)
    sec = defaultdict(dict)
    for r in cur.fetchall():
        sec[r['date']][r['sector_name']] = dict(chg=round(r['change_pct'],3),
                                                net=round(r['net_amount'] or 0,1),
                                                tier=r['tier'], leader=r['leader_name'],
                                                cons=r['consecutive_days'], top5=r['days_in_top5'])
    return m, sec

# ---------------------------------------------------------------------------
# L2/L3 决策层: brain_report
# ---------------------------------------------------------------------------
def load_brain():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT,"backend/output/archive/brain_report_2026-08-*.json"))):
        d = json.load(open(f, encoding='utf-8'))
        td = d.get('trade_date')
        dec = d.get('decision', {}) or {}
        res = d.get('results', {}) or {}
        l7 = (res.get('L7',{}) or {}).get('raw',{}) or {}
        cio = d.get('cio_memo', {}) or {}
        ca  = cio.get('cross_asset', {}) or {}
        mig = cio.get('migration', {}) or {}
        # 候选
        cands = []
        tp = cio.get('trading_plan', {}) or {}
        for o in (tp.get('opportunities', []) or []):
            cands.append(dict(tier=o.get('tier'), name=o.get('name'), sector=o.get('sector')))
        for m in (cio.get('main_lines', []) or []):
            pass
        out[td] = dict(
            ic=dec.get('can_buy'),
            direction=dec.get('direction'),
            position=dec.get('position_pct'),
            bull=dec.get('bull'), bear=dec.get('bear'),
            l7=l7.get('composite'),
            cap_flow=ca.get('flow_score_overall'),
            mig_rating=mig.get('rating'),
            theme=(d.get('L0',{}) or {}).get('theme'),
            confirmed=(d.get('L0',{}) or {}).get('confirmed_industries') or [],
            cands=cands,
        )
    return out

# ---------------------------------------------------------------------------
# L3/L4: memo 综合评分 + 今日裁决
# ---------------------------------------------------------------------------
def load_memo():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT,"backend/output/memo_2026-08-*_wechat.html"))):
        html = open(f, encoding='utf-8', errors='ignore').read()
        m = re.search(r'今日裁决</div><div[^>]*>([^<]*)', html)
        verdict = m.group(1).strip() if m else None
        m = re.search(r'font-size:34px[^>]*>(\d+)</div>\s*<div[^>]*>综合评分/100', html)
        score = int(m.group(1)) if m else None
        td = os.path.basename(f).replace('memo_','').replace('_wechat.html','')
        out[td] = dict(verdict=verdict, score=score)
    return out

# ---------------------------------------------------------------------------
# 实际资金流 (Layer1 交叉验证)
# ---------------------------------------------------------------------------
def real_capital():
    # 行业净流入 (sector_daily.net_amount) 与 个股主力净流入 (stock_flow_daily) 的日度均值
    cur.execute("""
        SELECT date, AVG(net_amount) avg_net, SUM(net_amount) sum_net
        FROM sector_daily
        WHERE date BETWEEN '2026-08-01' AND '2026-08-14'
        GROUP BY date ORDER BY date
    """)
    sec_net = {r['date']: round(r['avg_net'] or 0,1) for r in cur.fetchall()}
    cur.execute("""
        SELECT date, AVG(main_net_buy) avg_main
        FROM stock_flow_daily
        WHERE date BETWEEN '2026-08-01' AND '2026-08-17'
        GROUP BY date ORDER BY date
    """)
    stk_flow = {r['date']: round(r['avg_main'] or 0,1) for r in cur.fetchall()}
    return sec_net, stk_flow

# ---------------------------------------------------------------------------
# 工具: 下一交易日收益
# ---------------------------------------------------------------------------
def next_ret(market, date, k):
    dates = sorted(market.keys())
    if date not in dates: return None
    i = dates.index(date)
    j = i + k
    if j >= len(dates): return None
    nd = dates[j]
    return round(market[nd]['ew'] - market[date]['ew'], 3)  # 累计? 用当日收益更直观

def day_ret(market, date, k):
    dates = sorted(market.keys())
    if date not in dates: return None
    i = dates.index(date)
    j = i + k
    if j >= len(dates): return None
    return market[dates[j]]['ew']

# ===========================================================================
def main():
    market, sec = market_facts()
    brain = load_brain()
    memo  = load_memo()
    sec_net, stk_flow = real_capital()

    all_dates = sorted(set(market.keys()) | set(memo.keys()))
    rows = []
    for td in all_dates:
        b = brain.get(td, {})
        mo = memo.get(td, {})
        ic = b.get('ic'); comp = mo.get('score'); verdict = mo.get('verdict')
        # veto_reason
        veto = None
        if ic == 'YES' and verdict == '不交易':
            if comp is not None and comp < 65:
                veto = 'COMPOSITE_SCORE'
            elif (b.get('l7') or 0) >= 70:
                veto = 'RISK_VETO'
            elif b.get('cap_flow') is None or b.get('mig_rating') is None:
                veto = 'DATA_STALE'
            else:
                veto = 'OTHER'
        elif ic == 'YES' and verdict == '谨慎参与':
            veto = 'DOWNGRADED_TO_CAUTION'  # 被压成谨慎, 非完全否决
        elif ic == 'NO' and verdict == '不交易':
            veto = 'CONSISTENT_NO'
        # 数据健康
        data_health = 'OK'
        if b.get('cap_flow') is None or b.get('mig_rating') is None:
            data_health = 'DEGRADED'
        rows.append(dict(
            date=td, ic=ic, composite=comp, verdict=verdict,
            l7=b.get('l7'), cap_flow=b.get('cap_flow'), mig=b.get('mig_rating'),
            position=b.get('position'), bull=b.get('bull'), bear=b.get('bear'),
            real_sec_net=sec_net.get(td), real_stk_flow=stk_flow.get(td),
            data_health=data_health, veto_reason=veto,
            market_ew=market.get(td,{}).get('ew'), up_pct=market.get(td,{}).get('up_pct'),
            lim_up=market.get(td,{}).get('lim_up'), lim_dn=market.get(td,{}).get('lim_dn'),
            theme=b.get('theme'), cands=b.get('cands'),
        ))

    # ---- 数字1: IC YES 胜率 (next-1/3/5 日市场收益>0) ----
    yes_days = [r for r in rows if r['ic']=='YES' and r['date'] in market]
    def win_rate(days, k):
        vals=[day_ret(market,d['date'],k) for d in days]
        vals=[v for v in vals if v is not None]
        if not vals: return None
        return dict(n=len(vals), win=sum(1 for v in vals if v>0),
                    win_pct=round(sum(1 for v in vals if v>0)/len(vals)*100,1),
                    avg=round(sum(vals)/len(vals),3))
    num1 = {f'next_{k}': win_rate(yes_days,k) for k in (1,3,5)}

    # ---- 数字2/3: Composite 桶 后续收益 ----
    def bucket_ret(lo,hi,k):
        ds=[r for r in rows if r['composite'] is not None and lo<=r['composite']<=hi and r['date'] in market]
        vals=[day_ret(market,r['date'],k) for r in ds]
        vals=[v for v in vals if v is not None]
        return dict(n=len(ds), avg=round(sum(vals)/len(vals),3) if vals else None,
                    dates=[r['date'] for r in ds])
    num2 = {f'next_{k}': bucket_ret(60,64,k) for k in (1,3,5)}
    num3 = {f'next_{k}': bucket_ret(65,79,k) for k in (1,3,5)}

    # ---- 数字4: A/B 候选相对市场超额收益 ----
    # 候选板块在 signal 日及次日的 sector_daily 收益, 减去市场 ew
    excess = []
    for r in rows:
        if r['ic']!='YES' or not r['cands']: continue
        td=r['date']
        ab=[c['name'] for c in r['cands'] if c['tier'] in ('A','B')]
        if not ab: continue
        for name in ab:
            sd = sec.get(td,{}).get(name)
            if not sd: continue
            # 次日行业收益
            dates=sorted(sec.keys())
            if td in dates:
                i=dates.index(td)
                nxt = sec[dates[i+1]][name]['chg'] if i+1<len(dates) and name in sec.get(dates[i+1],{}) else None
            else:
                nxt=None
            mkt_nxt = day_ret(market, td, 1)
            ex = round(nxt - mkt_nxt,3) if (nxt is not None and mkt_nxt is not None) else None
            excess.append(dict(date=td, sector=name, tier=[c['tier'] for c in r['cands'] if c['name']==name][0],
                               sig_chg=sd['chg'], next_chg=nxt, mkt_nxt=mkt_nxt, excess=ex))
    ex_vals=[e['excess'] for e in excess if e['excess'] is not None]
    num4 = dict(n=len(ex_vals), avg_excess=round(sum(ex_vals)/len(ex_vals),3) if ex_vals else None,
                detail=excess)

    # ---- 数字5: 被 veto 的 YES 中, 多少"正确"(次日市场上涨) ----
    vetoed = [r for r in rows if r['veto_reason']=='COMPOSITE_SCORE']
    v_correct = [r for r in vetoed if (day_ret(market,r['date'],1) or 0) > 0]
    num5 = dict(vetoed_n=len(vetoed), correct_n=len(v_correct),
                correct_pct=round(len(v_correct)/len(vetoed)*100,1) if vetoed else None,
                vetoed_days=[r['date'] for r in vetoed],
                correct_days=[r['date'] for r in v_correct])

    # ---- Counterfactual: 8/5-8/14 若裁决器改为"显示分歧" ----
    cf = []
    for r in rows:
        if r['date'] < '2026-08-05' or r['date'] > '2026-08-14': continue
        action = '参与' if r['ic']=='YES' else '不参与'
        n1 = day_ret(market, r['date'], 1)
        cf.append(dict(date=r['date'], ic=r['ic'], composite=r['composite'], verdict=r['verdict'],
                       cf_action=action, mkt_next1=n1,
                       cands=[c['name'] for c in (r['cands'] or []) if c['tier'] in ('A','B')]))

    result = dict(
        generated="2026-08-17", scope="2026-08-01~2026-08-17",
        rows=rows, num1_ic_yes_win=num1, num2_comp_60_64=num2,
        num3_comp_65_79=num3, num4_ab_excess=num4, num5_veto_correct=num5,
        counterfactual=cf,
    )
    json.dump(result, open(os.path.join(OUT,"audit_aug.json"),'w',encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print("WROTE audit_aug.json")
    # 控制台摘要
    print("\n=== 逐日四层 ===")
    for r in rows:
        print(f"{r['date']} IC={str(r['ic']):<4} C={str(r['composite']):<4} verdict={str(r['verdict']):<5} "
              f"L7={str(r['l7']):<4} cap={str(r['cap_flow']):<4} mig={str(r['mig']):<3} "
              f"DH={r['data_health']:<8} veto={r['veto_reason']} mktEW={r['market_ew']} up%={r['up_pct']}")
    print("\n[1] IC YES 胜率:", num1)
    print("[2] Comp60-64 next:", num2)
    print("[3] Comp65-79 next:", num3)
    print("[4] A/B excess avg:", num4.get('avg_excess'), "n=", num4.get('n'))
    print("[5] Vetoed YES correct:", num5)
    print("\nCounterfactual 8/5-8/14:")
    for c in cf:
        print(f"  {c['date']} IC={c['ic']:<4} -> {c['cf_action']} (mkt+1={c['mkt_next1']}) cands={c['cands']}")

if __name__ == '__main__':
    main()
