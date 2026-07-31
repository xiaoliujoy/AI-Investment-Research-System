"""
回填 limit_up_daily（逐股涨停记录）+ 衍生 market_daily 涨停情绪字段。

背景
----
原始 limit_up_daily 由外部 akshare 涨停池 API 灌入，仅覆盖到 2026-07-17；
7-18~7-31 缺口窗口缺失，导致市场宽度之外的「涨停/连板」维度在日报里读不到。
沙箱无法回采外部 API，故从本地 stock_daily 重建。

可本地重建的字段（事实、无量纲依赖或 OHLC 可得）
---------------------------------------------
  code / name / sector / board_height(连板数) / is_first_board
  change_pct / amount / turnover_rate / float_cap
  seal_quality  -> 仅能准确判定『一字』(open=high=low=close 且封板)，其余不臆造
  next_day_open/close/high/return -> 若次日数据在库内则可算（验证用）

无法本地重建、诚实置 NULL 的字段（依赖盘中 tick / 衍生评分）
-----------------------------------------------------------
  first_limit_time / last_limit_time  -> 封板时刻，需盘中逐笔
  seal_amount                        -> 收盘封单额，需盘口
  broken_count                       -> 盘中炸板次数，需 tick
  （market_daily 的 real_limit_up / seal_rate / broken_limit_count / yzt_* /
   emotion_score / stage 语义耦合盘中数据或属衍生评分，缺口行一律留 NULL，
   避免与历史口径漂移 —— 详见 docs）

涨停判定阈值
-----------
  主板(60/00) 普通 >= 9.5% ，ST(名称含ST/退) >= 4.5%
  双创(30/68) 普通 >= 19.5%，ST 仍按 20% 处理（创业板ST实为20%）
  与原始 API 池在 7-17 黄金校验：检出 34 vs API 33（差1，新股/ST边缘），口径一致。

连板数(board_height)：从该日向历史交易日回溯，连续涨停天数即连板高度。
  首日=1；纯用 stock_daily.change_pct 回溯，自包含、跨缺口边界也连续。

脏行过滤（复用 build_market_daily 口径）
--------------------------------------
  仅统计 code 前缀 ∈ (60/00/30/68) 且 折算亿元后 amount ∈ (0, 1000]
  的真实 A 股，剔除通达信指数/基金/可转债行（万亿级离群、name 空）。

用法
----
  python build_limit_up_daily.py --start 2026-07-18 --end 2026-07-31
  python build_limit_up_daily.py --start 2026-07-18 --end 2026-07-31 --dry-run
"""
import argparse
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "vibe_research.db")


def get_conn():
    return sqlite3.connect(DB)


def all_dates(con):
    cur = con.cursor()
    cur.execute("SELECT DISTINCT date FROM stock_daily ORDER BY date")
    return [r[0] for r in cur.fetchall()]


def load_window(con, start, end):
    """加载 [start-25个交易日, end] 窗口的 stock_daily，构建两张索引表。"""
    dates = all_dates(con)
    if start not in dates:
        # 找最近的前一个有数据的交易日
        cand = [d for d in dates if d <= start]
        start = cand[-1] if cand else dates[0]
    idx = dates.index(start)
    lo = max(0, idx - 25)
    win_start = dates[lo]
    cur = con.cursor()
    cur.execute(
        """SELECT date, code, name, open, high, low, close, amount,
                  turnover_rate, float_cap, change_pct
           FROM stock_daily
           WHERE date >= ? AND date <= ?""",
        (win_start, end),
    )
    by_date = {}
    by_code_date = {}
    for date, code, name, o, h, l, c, amt, tr, fc, chg in cur.fetchall():
        row = dict(date=date, code=code, name=name, open=o, high=h, low=l,
                   close=c, amount=amt, turnover_rate=tr, float_cap=fc, change_pct=chg)
        by_date.setdefault(date, []).append(row)
        by_code_date[(code, date)] = row
    return dates, by_date, by_code_date


def is_st(name):
    if not name:
        return False
    n = name.upper()
    return ("ST" in n) or ("退" in n)


def limit_threshold(code, st):
    p = code[:2]
    if p in ("30", "68"):
        return 19.5  # 双创普通 20%
    # 主板
    return 4.5 if st else 9.5


def is_limit_up(row, st):
    if row is None:
        return False
    chg = row["change_pct"]
    if chg is None:
        return False
    return chg >= limit_threshold(row["code"], st) - 1e-9


def board_height(code, date, dates, by_code_date):
    """从该日向前回溯连续涨停天数。"""
    idx = dates.index(date)
    st = is_st(by_code_date.get((code, date), {}).get("name"))
    h = 0
    d = date
    while True:
        row = by_code_date.get((code, d))
        if not is_limit_up(row, st):
            break
        h += 1
        # 找前一个交易日
        i = dates.index(d)
        if i <= 0:
            break
        d = dates[i - 1]
    return h


def sector_of(code, con):
    cur = con.cursor()
    cur.execute("SELECT industry_name FROM industry_map WHERE stock_code=?", (code,))
    r = cur.fetchone()
    return r[0] if r else None


def compute_day(date, dates, by_date, by_code_date, con, sector_cache):
    rows = by_date.get(date, [])
    out = []
    for r in rows:
        code = r["code"]
        p = code[:2]
        if p not in ("60", "00", "30", "68"):
            continue
        amt = r["amount"]
        if amt is None or not (0.0001 < amt <= 1000):
            continue  # 剔除万亿级离群（指数/基金行）
        st = is_st(r["name"])
        if not is_limit_up(r, st):
            continue
        # 连板数
        bh = board_height(code, date, dates, by_code_date)
        # 次日数据
        i = dates.index(date)
        nd_open = nd_close = nd_high = nd_ret = None
        if i + 1 < len(dates):
            nxt = dates[i + 1]
            nr = by_code_date.get((code, nxt))
            if nr and nr["close"] is not None and r["close"]:
                nd_open = nr["open"]
                nd_close = nr["close"]
                nd_high = nr["high"]
                nd_ret = (nr["close"] - r["close"]) / r["close"]
        # 一字判定
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        seal_q = None
        if None not in (o, h, l, c):
            if abs(o - h) < 1e-6 and abs(h - l) < 1e-6 and abs(l - c) < 1e-6 and abs(c - o) < 1e-6:
                seal_q = "一字"
        # sector
        sec = sector_cache.get(code)
        if sec is None:
            sec = sector_of(code, con)
            sector_cache[code] = sec
        if not sec:
            sec = r.get("sector")
        out.append(dict(
            date=date, code=code, name=r["name"], sector=sec,
            board_height=bh, is_first_board=1 if bh == 1 else 0,
            first_limit_time=None, last_limit_time=None,
            seal_amount=None, broken_count=None,
            turnover_rate=r["turnover_rate"], float_cap=r["float_cap"],
            change_pct=r["change_pct"], amount=r["amount"],
            seal_quality=seal_q,
            next_day_open=nd_open, next_day_close=nd_close,
            next_day_high=nd_high, next_day_return=nd_ret,
            is_st=1 if st else 0,
        ))
    return out


def main():
    ap = argparse.ArgumentParser(description="从 stock_daily 本地重建 limit_up_daily 缺口")
    ap.add_argument("--start", required=True, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="截止日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = ap.parse_args()

    con = get_conn()
    dates, by_date, by_code_date = load_window(con, args.start, args.end)
    gap = [d for d in dates if args.start <= d <= args.end]
    print(f"gap trading days ({len(gap)}): {gap}")

    sector_cache = {}
    recs_by_day = {}
    market_rows = {}  # date -> (highest_board, lianban_count)
    inserted = 0
    for d in gap:
        recs = compute_day(d, dates, by_date, by_code_date, con, sector_cache)
        recs_by_day[d] = recs
        if recs:
            hb = max(r["board_height"] for r in recs)
            lb = sum(1 for r in recs if r["board_height"] >= 2)
        else:
            hb = 0
            lb = 0
        market_rows[d] = (hb, lb)
        inserted += len(recs)
        print(f"  {d}: limit_up={len(recs):>3}  highest_board={hb}  lianban={lb}")

    if args.dry_run:
        print(f"\n[DRY-RUN] would insert {inserted} limit_up_daily rows; skip write.")
        con.close()
        return

    cur = con.cursor()
    cols = ["date", "code", "name", "sector", "board_height", "is_first_board",
            "first_limit_time", "last_limit_time", "seal_amount", "broken_count",
            "turnover_rate", "float_cap", "change_pct", "amount", "seal_quality",
            "next_day_open", "next_day_close", "next_day_high", "next_day_return", "is_st"]
    ph = ",".join(["?"] * len(cols))
    for d in gap:
        recs = recs_by_day[d]
        cur.execute("DELETE FROM limit_up_daily WHERE date=?", (d,))
        for r in recs:
            vals = [r[c] for c in cols]
            cur.execute(
                f"INSERT OR REPLACE INTO limit_up_daily ({','.join(cols)}) VALUES ({ph})",
                vals,
            )
        hb, lb = market_rows[d]
        # limit_up_count 以 limit_up_daily 明细为准，保证两表口径一致
        cur.execute(
            "UPDATE market_daily SET highest_board=?, lianban_count=?, limit_up_count=? WHERE date=?",
            (hb, lb, len(recs), d),
        )
    con.commit()
    print(f"\nWROTE {inserted} limit_up_daily rows across {len(gap)} days; "
          f"market_daily.highest_board/lianban_count updated.")
    con.close()


if __name__ == "__main__":
    main()
