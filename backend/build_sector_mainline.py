# -*- coding: utf-8 -*-
"""
Phase A-2: 主线板块数据底座（step1 多源容错 + 去同花顺硬依赖）
==============================================================
数据来源（按优先级，单源失败自动降级，不阻断流水线）：
  - 板块资金净流入(当日/3/5/10日) : 新浪 stock_fund_flow_industry（主）
                                    → tushare_provider.sector_flow_as_records（第3源，需token+出口，可选）
  - 板块成交额 + 价格序列(25日)    : 同花顺 stock_board_industry_index_ths（主，脆弱，偶发403）
                                    → 本地 industry_map × stock_daily 聚合（兜底，零外部依赖）
重要：沙箱仅 dead 代理，akshare 调用前必须清掉 http_proxy/https_proxy。
产出：output/sector_mainline.json（含 data_sources 溯源字段）。
"""
import os
import time
import json
import sqlite3
import datetime
from pathlib import Path
import pandas as pd

# 清代理 + 给所有 requests（含 akshare）注入默认超时，防止网络挂起（曾导致 step1 卡死）
for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)

import requests
_ORIG_REQUEST = requests.Session.request
def _request_with_timeout(self, method, url, **kwargs):
    kwargs.setdefault("timeout", 20)
    return _ORIG_REQUEST(self, method, url, **kwargs)
requests.Session.request = _request_with_timeout

import akshare as ak

_BASE = Path(__file__).resolve().parent
DB = str(_BASE / "database" / "vibe_research.db")
OUT = str(_BASE / "output")
os.makedirs(OUT, exist_ok=True)

# tushare 第3源（latent）：导入失败不影响主流程
try:
    import tushare_provider as tp
    TP_OK = True
except Exception:
    tp = None
    TP_OK = False


def _q(sql, args=()):
    c = sqlite3.connect(DB, timeout=30)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def latest_full_date():
    rows = _q("SELECT date FROM stock_daily GROUP BY date HAVING COUNT(*)>4000 "
              "ORDER BY date DESC LIMIT 1")
    return rows[0][0] if rows else None


def get_recent_dates(n=25):
    """升序返回最近 n 个完整交易日（用于本地序列）。"""
    rows = _q("SELECT date FROM stock_daily WHERE date<=? GROUP BY date HAVING COUNT(*)>4000 "
              "ORDER BY date DESC LIMIT ?", (latest_full_date(), n))
    return list(reversed([r[0] for r in rows]))


# ---------- 板块资金流：新浪（主） ----------
def _flow_sina():
    now = ak.stock_fund_flow_industry(symbol='即时')
    f5 = ak.stock_fund_flow_industry(symbol='5日排行')
    now = now.rename(columns={'行业': 'sector', '净额': 'net_now',
                              '行业-涨跌幅': 'chg_pct', '公司家数': 'stock_count',
                              '领涨股': 'leader', '领涨股-涨跌幅': 'leader_chg'})
    f5 = f5.rename(columns={'行业': 'sector', '净额': 'net_5d'})
    df = now.merge(f5[['sector', 'net_5d']], on='sector', how='left')
    for sym, col in [('3日排行', 'net_3d'), ('10日排行', 'net_10d')]:
        try:
            fx = ak.stock_fund_flow_industry(symbol=sym).rename(columns={'行业': 'sector', '净额': col})
            df = df.merge(fx[['sector', col]], on='sector', how='left')
        except Exception as e:
            print(f"   [skip {sym}]: {repr(e)[:60]}")
    return df


# ---------- 板块资金流：tushare（第3源，可选） ----------
def _flow_tushare(trade_date):
    if not TP_OK or not tp.is_available():
        raise RuntimeError("tushare 不可用（无 token 或出口不可达）")
    cw = _q("SELECT thx_name, em_code FROM sector_crosswalk")
    recs = tp.sector_flow_as_records(trade_date, cw)
    if not recs:
        return pd.DataFrame(columns=['sector', 'net_now'])
    df = pd.DataFrame(recs)
    # 新浪缺失的维度留空，保证下游 consensus 不崩
    for col in ['net_5d', 'net_3d', 'net_10d', 'chg_pct', 'stock_count', 'leader']:
        if col not in df.columns:
            df[col] = None
    return df


def get_sector_flow():
    """返回 (df, source)。新浪优先；失败则尝试 tushare；再失败返回空壳。"""
    try:
        df = _flow_sina()
        print(f"   新浪行业资金流：行业数={len(df)}")
        return df, "sina"
    except Exception as e:
        print(f"   [新浪失败] {repr(e)[:80]} -> 尝试 tushare")
        try:
            td = latest_full_date()
            df = _flow_tushare(td)
            print(f"   tushare 行业资金流：行业数={len(df)}")
            return df, "tushare"
        except Exception as e2:
            print(f"   [tushare不可用] {repr(e2)[:80]}")
            return pd.DataFrame(columns=['sector', 'net_now', 'net_5d', 'net_3d',
                                         'net_10d', 'chg_pct', 'stock_count', 'leader']), "none"


# ---------- 板块成交额 + 价格序列：同花顺（主，脆弱） ----------
def get_sector_amount_ths():
    """同花顺 90 行业指数：约25交易日 成交额(→亿元)+收盘价 序列。"""
    bd = ak.stock_board_industry_name_ths()
    today_str = datetime.datetime.now().strftime('%Y%m%d')
    rows = []
    for _, r in bd.iterrows():
        name = r['name']
        try:
            d = ak.stock_board_industry_index_ths(symbol=name, start_date='20260601', end_date=today_str)
            if d is None or len(d) == 0:
                continue
            d = d.copy()
            d['成交额'] = d['成交额'].astype(float) / 1e8   # 元→亿元
            d['收盘价'] = d['收盘价'].astype(float)
            n = len(d)
            last = d.iloc[-1]
            prev = d.iloc[-2] if n > 1 else None
            recent5 = d.tail(5)['成交额']
            tail = d.tail(25)
            close_series = tail['收盘价'].tolist()
            amount_series = tail['成交额'].tolist()
            hi25 = max(close_series)
            mom5 = (close_series[-1] / close_series[-6] - 1) if len(close_series) >= 6 else None
            mom10 = (close_series[-1] / close_series[-11] - 1) if len(close_series) >= 11 else None
            rows.append({
                'sector': name,
                'trade_date': str(last['日期']),
                'amount_today': float(last['成交额']),
                'amount_prev': float(prev['成交额']) if prev is not None else None,
                'amount_5sum': float(recent5.sum()),
                'amount_5avg': float(recent5.mean()),
                'amount_ma20': float(tail['成交额'].mean()),
                'amount_series': [round(x, 0) for x in amount_series],
                'close_series': [round(x, 2) for x in close_series],
                'close_vs_high25': round(close_series[-1] / hi25, 4) if hi25 else None,
                'price_mom5': round(mom5, 4) if mom5 is not None else None,
                'price_mom10': round(mom10, 4) if mom10 is not None else None,
            })
        except Exception as e:
            print(f"  [skip] {name}: {repr(e)[:80]}")
        time.sleep(0.04)
    return pd.DataFrame(rows)


# ---------- 板块成交额 + 价格序列：本地聚合（兜底，零外部依赖） ----------
def get_sector_amount_local(dates):
    """同花顺90行业(经 crosswalk→东财板块) 的 板块成交额(Σ成员amount,亿元) + 等权收盘价序列。
    完全本地：industry_map(东财成分) × stock_daily。用于同花顺不可达时的兜底。"""
    cw = {r[0]: r[1] for r in _q("SELECT thx_name, em_code FROM sector_crosswalk")}
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        rows = []
        for thx, em in cw.items():
            members = [r[0] for r in c.execute(
                "SELECT stock_code FROM industry_map WHERE industry_code=? "
                "AND stock_code NOT LIKE '88%' AND stock_code NOT LIKE '11%' "
                "AND stock_code NOT LIKE '12%' AND stock_code NOT LIKE '5%'", (em,)).fetchall()]
            if not members:
                continue
            ph = ",".join("?" * len(members))
            q = (f"SELECT date, SUM(amount) AS amt, AVG(close) AS cl FROM stock_daily "
                 f"WHERE code IN ({ph}) AND date IN ({','.join('?' * len(dates))}) "
                 f"GROUP BY date ORDER BY date")
            res = {r["date"]: (r["amt"], r["cl"]) for r in c.execute(q, list(members) + list(dates))}
            amt_s, close_s = [], []
            for d in dates:
                if d in res:
                    amt_s.append(round(res[d][0], 1)); close_s.append(round(res[d][1], 2))
                else:
                    amt_s.append(None); close_s.append(None)
            valid = [(a, cl) for a, cl in zip(amt_s, close_s) if a is not None and cl is not None]
            if len(valid) < 2:
                continue
            amt_v = [a for a, _ in valid]; close_v = [cl for _, cl in valid]
            today = valid[-1][0]; prev = valid[-2][0]
            recent5 = amt_v[-5:]; tail20 = amt_v[-20:]
            hi25 = max(close_v); last_close = close_v[-1]
            mom5 = (close_v[-1] / close_v[-6] - 1) if len(close_v) >= 6 else None
            mom10 = (close_v[-1] / close_v[-11] - 1) if len(close_v) >= 11 else None
            rows.append({
                'sector': thx,
                'trade_date': dates[-1] if dates[-1] in res else [d for d in dates if d in res][-1],
                'amount_today': round(today, 1),
                'amount_prev': round(prev, 1),
                'amount_5sum': round(sum(recent5), 1),
                'amount_5avg': round(sum(recent5) / len(recent5), 1),
                'amount_ma20': round(sum(tail20) / len(tail20), 1),
                'amount_series': [round(x, 0) for x in amt_v],
                'close_series': [round(x, 2) for x in close_v],
                'close_vs_high25': round(last_close / hi25, 4) if hi25 else None,
                'price_mom5': round(mom5, 4) if mom5 is not None else None,
                'price_mom10': round(mom10, 4) if mom10 is not None else None,
            })
        return pd.DataFrame(rows)
    finally:
        c.close()


def main():
    flow, flow_source = get_sector_flow()
    dates = get_recent_dates(25)

    # 板块成交额：同花顺主；失败/空/旧数据 → 本地兜底
    amount_source = None
    amt = None
    db_latest = latest_full_date()  # 数据库最新完整交易日
    try:
        amt_ths = get_sector_amount_ths()
        if amt_ths is not None and len(amt_ths) > 0:
            ths_latest = str(amt_ths['trade_date'].iloc[0])
            # 新鲜度检查：同花顺日期必须 >= 数据库最新日期，否则降级
            if db_latest and ths_latest < db_latest:
                print(f"   [同花顺数据过期] ths_latest={ths_latest} < db_latest={db_latest} → 降级本地聚合")
            else:
                amt = amt_ths
                amount_source = "ths"
                print(f"   同花顺行业成交额：行业数={len(amt)} 最新日期={ths_latest}")
    except Exception as e:
        print(f"   [同花顺失败] {repr(e)[:80]}")
    if amount_source is None:
        amt = get_sector_amount_local(dates)
        amount_source = "local"
        print(f"   本地聚合行业成交额(兜底)：行业数={len(amt)}")

    df = flow.merge(amt, on='sector', how='left')
    print(f"== 合并后行业数={len(df)} ==")

    # ---- step1 三张排名 ----
    top10_net = df.dropna(subset=['net_now']).nlargest(10, 'net_now')[
        ['sector', 'net_now', 'chg_pct', 'stock_count', 'leader']]
    top5_5d = df.dropna(subset=['net_5d']).nlargest(5, 'net_5d')[
        ['sector', 'net_5d', 'net_now', 'chg_pct']]
    df['amt_amplifying'] = (df['amount_today'].notna() & df['amount_prev'].notna()
                            & (df['amount_today'] > df['amount_prev'])
                            & (df['amount_today'] > df['amount_5avg']))
    amt_up = df[df['amt_amplifying']].nlargest(10, 'amount_today')[
        ['sector', 'amount_today', 'amount_prev', 'amount_5avg']]

    sec_cols = ['sector', 'net_now', 'net_3d', 'net_5d', 'net_10d', 'chg_pct',
                'stock_count', 'leader', 'amount_today', 'amount_prev',
                'amount_5avg', 'amount_ma20', 'amount_series', 'close_series',
                'close_vs_high25', 'price_mom5', 'price_mom10']
    sec_cols = [c for c in sec_cols if c in df.columns]
    sectors = df[sec_cols].to_dict('records')

    out = {
        'trade_date': str(amt['trade_date'].iloc[0]) if (amt is not None and len(amt)) else None,
        'top10_net_inflow': top10_net.to_dict('records'),
        'top5_5d_net_inflow': top5_5d.to_dict('records'),
        'amount_amplifying': amt_up.to_dict('records'),
        'sector_count': int(len(df)),
        'sectors': sectors,
        'data_sources': {
            'flow': flow_source,
            'amount': amount_source,
            'tushare_available': (TP_OK and tp.is_available()) if TP_OK else False,
        },
    }
    with open(os.path.join(OUT, 'sector_mainline.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)

    print("\n========== 【step1】主线板块排名 ==========")
    print(f"交易日: {out['trade_date']}  覆盖行业: {out['sector_count']}  "
          f"数据源[资金流={flow_source}, 成交额={amount_source}, tushare可用={out['data_sources']['tushare_available']}]")
    print("\n① 当日板块资金净流入 Top10（单位：亿元）:")
    for i, r in enumerate(top10_net.itertuples(), 1):
        print(f"  {i:2d}. {r.sector:<6} 净额={r.net_now:>8.2f}  涨跌幅={r.chg_pct:>6.2f}%  家数={r.stock_count}  领涨={r.leader}")
    print("\n② 近5日累计净流入 Top5（单位：亿元）:")
    for i, r in enumerate(top5_5d.itertuples(), 1):
        print(f"  {i}. {r.sector:<6} 5日净额={r.net_5d:>8.2f}  当日净额={r.net_now:>8.2f}")
    print("\n③ 成交额持续放大（今日>昨日 且 >5日均）Top10（单位：亿元）:")
    for i, r in enumerate(amt_up.itertuples(), 1):
        print(f"  {i:2d}. {r.sector:<6} 今日={r.amount_today:>8.1f}亿  昨日={r.amount_prev:>8.1f}亿  5日均={r.amount_5avg:>8.1f}亿")
    print(f"\n已写出: {os.path.join(OUT, 'sector_mainline.json')}")


if __name__ == '__main__':
    main()
