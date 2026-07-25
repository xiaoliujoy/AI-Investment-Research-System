# -*- coding: utf-8 -*-
"""
第五层 · 四龙头体系 + 板块净额本地聚合
===========================================================
依赖：
  - sector_crosswalk 表：同花顺行业名 -> 东财板块(industry_code/em_name)
  - industry_map 表(fetch_industry_map.py 产出)：stock_code -> 东财 industry_code/name
  - stock_info 表：code -> name（新浪补齐，stock_daily.name 为空）
  - stock_daily 表（TDX）：amount/change_pct/volume_ratio/ma20/ma60/is_new_high_20d
  - 新浪个股资金流 stock_fund_flow_individual()：逐只 主力净流入

产出：
  - 每个主线板块的 产业/资金/技术/情绪 四龙头
  - 板块资金净流入（本地聚合 = Σ 成分股主力净流入），与 step1 在线口径交叉验证
"""
import os
import re
import json
import sqlite3
import datetime

for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)
import akshare as ak

DB = "C:/Users/JOY/WorkBuddy/个人AI研投系统/backend/database/vibe_research.db"
OUT = "C:/Users/JOY/WorkBuddy/个人AI研投系统/backend/output"


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


_MONEY_RE = re.compile(r"(-?[\d.]+)\s*(亿|万)?")


def _parse_money(s):
    """新浪金额字符串(如 '4779.03万' / '0.48亿' / '-6.12亿') -> 亿元 float。"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        pass
    m = _MONEY_RE.match(s)
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2)
    if unit == "万":
        v /= 1e4
    return v  # 亿 or 无单位 -> 视为亿元


def resolve_em_code(c, thx_sector):
    """同花顺行业名 -> 东财板块代码（sector_crosswalk）。"""
    r = c.execute("SELECT em_code, em_name, em_type FROM sector_crosswalk WHERE thx_name=?",
                  (thx_sector,)).fetchone()
    return r


def industry_members(c, em_code):
    """东财板块代码 -> [(stock_code, stock_name)]，排除北交所/转债。"""
    rows = c.execute(
        """SELECT im.stock_code, COALESCE(si.name, '') 
           FROM industry_map im LEFT JOIN stock_info si ON im.stock_code = si.code
           WHERE im.industry_code = ?
             AND im.stock_code NOT LIKE '88%' AND im.stock_code NOT LIKE '11%'
             AND im.stock_code NOT LIKE '12%' AND im.stock_code NOT LIKE '5%'""",
        (em_code,)).fetchall()
    return [(r[0], r[1]) for r in rows]


def load_net_flow(force=False):
    """新浪个股资金流（全市场），缓存到 output/stock_net_flow.json。返回 {code: 净额(亿)}。"""
    cache = os.path.join(OUT, "stock_net_flow.json")
    today = str(datetime.date.today())
    if not force and os.path.exists(cache):
        d = json.load(open(cache, encoding="utf-8"))
        if d.get("date") == today:
            return d["map"], today
    df = ak.stock_fund_flow_individual()
    code_col = next((x for x in df.columns if "代码" in x), None)
    net_col = next((x for x in df.columns if "净额" in x or "主力" in x), None)
    if code_col is None or net_col is None:
        raise RuntimeError(f"个股资金流列异常: {list(df.columns)}")
    cols = list(df.columns)
    ci, ni = cols.index(code_col), cols.index(net_col)
    mp = {str(r[ci]).zfill(6): _parse_money(r[ni]) for r in df.itertuples(index=False)}
    json.dump({"date": today, "map": mp}, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return mp, today


def compute_leaders(date, main_sectors, net_flow=None):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    if net_flow is None:
        net_flow, _ = load_net_flow()
    result = {}
    for sec in main_sectors:
        x = resolve_em_code(c, sec)
        if not x:
            result[sec] = {"error": "未匹配到东财板块(跨表缺失)", "member_count": 0}
            continue
        em_code, em_name, em_type = x
        members = industry_members(c, em_code)
        if not members:
            result[sec] = {"em_name": em_name, "error": "无成分股", "member_count": 0}
            continue
        codes = [m[0] for m in members]
        name_map = {m[0]: (m[1] or "").replace(" ", "") for m in members}
        placeholders = ",".join("?" * len(codes))
        rows = c.execute(f"""
            SELECT code, close, high_20d, low_20d, ma20, ma60,
                   volume_ratio, amount, change_pct, turnover_rate, is_new_high_20d
            FROM stock_daily
            WHERE date=? AND code IN ({placeholders})
        """, [date] + codes).fetchall()
        recs = []
        for r in rows:
            d = dict(r)
            d["name"] = name_map.get(d["code"], "")
            d["net_main"] = net_flow.get(d["code"])   # 主力净流入（新浪，当日，亿元）
            recs.append(d)
        if not recs:
            result[sec] = {"em_name": em_name, "error": "当日无行情", "member_count": 0}
            continue

        def topn(key, rev=True, n=1, filt=None):
            pool = [x for x in recs if (filt is None or filt(x))]
            pool.sort(key=lambda x: (x.get(key) is not None, x.get(key) if x.get(key) is not None else 0),
                      reverse=rev)
            return pool[:n]

        ind_leader = topn("amount", rev=True, n=1)[0]
        fund_pool = [x for x in recs if x["net_main"] is not None]
        fund_leader = sorted(fund_pool, key=lambda x: x["net_main"], reverse=True)[0] if fund_pool else None
        tech_leader = topn("change_pct", rev=True, n=1,
                           filt=lambda x: x["is_new_high_20d"] == 1)[0] if any(
            x["is_new_high_20d"] == 1 for x in recs) else topn("change_pct", rev=True, n=1)[0]
        sent_leader = topn("change_pct", rev=True, n=1)[0]

        sector_net = round(sum(x["net_main"] for x in recs if x["net_main"] is not None), 1)
        result[sec] = {
            "em_name": em_name,
            "member_count": len(recs),
            "sector_net_main": sector_net,
            "产业龙头": _lead(ind_leader),
            "资金龙头": _lead(fund_leader),
            "技术龙头": _lead(tech_leader),
            "情绪龙头": _lead(sent_leader),
        }
    c.close()
    return result


def _lead(r):
    if not r:
        return None
    return {
        "code": r["code"], "name": r["name"],
        "amount_yi": round(r["amount"], 1) if r["amount"] else None,
        "change_pct": r["change_pct"],
        "volume_ratio": r["volume_ratio"],
        "net_main": round(r["net_main"], 1) if r.get("net_main") is not None else None,
        "is_new_high": r["is_new_high_20d"],
    }


if __name__ == "__main__":
    date = "2026-07-09"
    sectors = ["医疗服务", "化学制药", "计算机设备", "白酒", "半导体"]
    net, ndate = load_net_flow()
    print(f"个股资金流日期={ndate}  覆盖 {len(net)} 只")
    res = compute_leaders(date, sectors, net)
    for sec, v in res.items():
        if "error" in v:
            print(f"\n### {sec}: {v['error']}")
            continue
        print(f"\n### {sec} -> {v['em_name']}（{v['member_count']}只成分，本地聚合净额={v['sector_net_main']}亿）")
        for k in ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"]:
            l = v[k]
            if l:
                print(f"  {k}: {l['name']}({l['code']}) 成交额{l['amount_yi']}亿 涨{l['change_pct']}% "
                      f"量比{l['volume_ratio']} 主力净额{l['net_main']}亿 新高{l['is_new_high']}")
