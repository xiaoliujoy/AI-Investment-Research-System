"""Phase A-2/3: 板块主线数据底座。

数据分工（按你的要求：TDX 优先，缺的用 akshare/东财）：
  - 资金净流入 net_amount : 东财 行业资金流 (akshare stock_sector_fund_flow_hist)
  - 板块成交额 amount     : TDX 个股 amount 按板块聚合（真实成交额，含趋势）
  - 涨跌家数 / 龙头       : TDX 成分股 (需 板块->个股 映射)

两个维度（净流入 + 成交额）并重，写入 sector_daily。

用法:
  python sector_pipeline.py --inspect      # 仅打印东财接口真实列结构，不写库
  python sector_pipeline.py                # 正式拉取并写入 sector_daily
  python sector_pipeline.py --rebuild-map  # 强制重建 板块->个股 映射
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).parent / "database" / "vibe_research.db"
VENV_PY = Path(r"C:\Users\JOY\.workbuddy\binaries\python\envs\default\Scripts\python.exe")


def get_db():
    return sqlite3.connect(str(DB))


def latest_full_day(c) -> str:
    return c.execute(
        "SELECT date FROM stock_daily GROUP BY date ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]


# ---------- 板块 -> 个股 映射 (akshare 东财行业成分) ----------
def build_membership(c):
    import akshare as ak
    print("[map] 拉取东财行业板块列表 ...")
    boards = ak.stock_board_industry_name_em()
    # 列: 板块名称 / 板块代码 / 板块英文 ...
    name_col = "板块名称" if "板块名称" in boards.columns else boards.columns[0]
    cons_all = []
    for i, sym in enumerate(boards[name_col].tolist()):
        try:
            cons = ak.stock_board_industry_cons_em(symbol=sym)
            code_col = "代码" if "代码" in cons.columns else cons.columns[0]
            for code in cons[code_col].tolist():
                cons_all.append((str(code).strip(), str(sym).strip()))
        except Exception as e:
            print(f"  [map] {sym} 失败: {e}")
        if (i + 1) % 20 == 0:
            print(f"  [map] {i+1}/{len(boards)} 板块")
    c.execute("DROP TABLE IF EXISTS sector_membership")
    c.execute("CREATE TABLE sector_membership (code TEXT, sector_name TEXT, PRIMARY KEY(code, sector_name))")
    c.executemany("INSERT OR IGNORE INTO sector_membership VALUES (?,?)", cons_all)
    c.commit()
    print(f"[map] 完成, 映射 {len(cons_all)} 条")


def get_membership(c):
    return c.execute("SELECT code, sector_name FROM sector_membership").fetchall()


# ---------- 东财行业资金流 ----------
def fetch_fund_flow_hist():
    import akshare as ak
    print("[flow] 拉取东财行业资金流历史 ...")
    df = ak.stock_sector_fund_flow_hist(indicator="今日", sector_type="行业资金流")
    return df


def inspect(df):
    print("=== 东财行业资金流 列 ===")
    print(list(df.columns))
    print(df.head(2).to_string())
    # 启发式定位关键列
    def find(*kw):
        for col in df.columns:
            if all(k in col for k in kw):
                return col
        return None
    print("\n=== 启发式映射 ===")
    print("日期 :", find("日期"))
    print("板块 :", find("名称") or find("板块"))
    print("净流入净额 :", find("主力净流入", "净额") or find("净流入", "净额"))
    print("涨跌幅 :", find("涨跌幅"))


# ---------- TDX 聚合：板块成交额 / 涨跌家数 / 龙头 ----------
def tdx_sector_agg(c, day, mapping):
    # mapping: list of (code, sector)
    by_sector = {}
    for code, sec in mapping:
        by_sector.setdefault(sec, []).append(code)
    # 取当日个股数据
    rows = c.execute(
        "SELECT code, amount, change_pct, volume, close FROM stock_daily WHERE date=?",
        (day,),
    ).fetchall()
    price = {r[0]: r for r in rows}
    result = {}
    for sec, codes in by_sector.items():
        amt = up = dwn = flat = 0.0
        leader_code = leader_name = None
        leader_amt = -1
        for code in codes:
            r = price.get(code)
            if not r:
                continue
            a, chg, vol, close = r[1], r[2], r[3], r[4]
            if a:
                amt += a
            if chg is not None:
                if chg > 0:
                    up += 1
                elif chg < 0:
                    dwn += 1
                else:
                    flat += 1
            if a and a > leader_amt:
                leader_amt = a
                leader_code = code
        result[sec] = dict(amount=amt, up=int(up), down=int(dwn), flat=int(flat),
                            leader_code=leader_code, leader_amount=leader_amt if leader_amt > 0 else None)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--rebuild-map", action="store_true")
    args = ap.parse_args()

    c = get_db()
    day = latest_full_day(c)
    print(f"最新完整交易日: {day}")

    df = fetch_fund_flow_hist()
    if args.inspect:
        inspect(df)
        c.close()
        return

    # 列定位
    cols = list(df.columns)
    date_col = next((x for x in cols if "日期" in x), cols[0])
    name_col = next((x for x in cols if ("名称" in x) or ("板块" in x)), None)
    if name_col is None:
        name_col = cols[1]
    net_col = next((x for x in cols if ("主力净流入" in x and "净额" in x)), None)
    if net_col is None:
        net_col = next((x for x in cols if ("净流入" in x and "净额" in x)), None)
    chg_col = next((x for x in cols if "涨跌幅" in x), None)
    print(f"映射: date={date_col} name={name_col} net={net_col} chg={chg_col}")

    # 资金流按 (日期, 板块) 建索引
    flow = {}
    for _, row in df.iterrows():
        d = str(row[date_col])
        sec = str(row[name_col]).strip()
        net = row[net_col] if net_col else None
        chg = row[chg_col] if chg_col else None
        flow[(d, sec)] = (net, chg)

    # 映射
    if args.rebuild_map or not c.execute("SELECT COUNT(*) FROM sector_membership").fetchone()[0]:
        build_membership(c)
    mapping = get_membership(c)
    print(f"映射条目: {len(mapping)}")

    # 仅处理 flow 里出现、且 <= day 的日期
    flow_dates = sorted({d for (d, _) in flow.keys() if d <= day})
    print(f"资金流覆盖交易日(<= {day}): {len(flow_dates)} 天")

    written = 0
    for d in flow_dates:
        agg = tdx_sector_agg(c, d, mapping)
        for (fd, sec), (net, chg) in flow.items():
            if fd != d:
                continue
            a = agg.get(sec, {})
            amount = a.get("amount", 0) or 0
            c.execute(
                """INSERT OR REPLACE INTO sector_daily
                   (date, sector_name, change_pct, amount, net_amount, up_count, down_count, flat_count,
                    leader_code, leader_amount)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (d, sec, chg, amount, net, a.get("up"), a.get("down"), a.get("flat"),
                 a.get("leader_code"), a.get("leader_amount")),
            )
            written += 1
        c.commit()
        print(f"  {d}: 写入 {sum(1 for k in flow if k[0]==d)} 个板块")
    print(f"完成: 共写入 sector_daily {written} 行")
    c.close()


if __name__ == "__main__":
    main()
