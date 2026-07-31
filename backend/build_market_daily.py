"""
回填 market_daily 的客观市场宽度/成交额字段（本地、零外部依赖）。

背景：
  market_daily 历史覆盖到 2026-07-14，缺口 2026-07-15~2026-07-31 缺失，
  导致日报「判环境」读不到最近的涨跌家数/成交额。原始采集器 collect_market_daily
  依赖外部 akshare API（沙箱不可用，且无法回填历史），故改为本地聚合。

数据源：stock_daily（amount=成交额；change_pct=涨跌幅）。

口径纪律（关键，避免脏数据污染）：
  1. 只统计真实 A 股（code 前缀 60/00/30/68），并剔除金额离群行：折算成「亿元」后
     amount 必须落在 (0, 1000] 区间（通达信指数/基金汇总行常以 00/60 前缀伪装且金额达
     万亿级、name 为空；真实个股单日成交罕超千亿）。早期批次(7-15~7-20)连真实股票 name
     都为空，故不能用 name 判别，只能用金额区间。
  2. amount 单位自检：缺口窗口经实测已是「亿元」（锚点股 600519 在 15~139 区间）；
     若锚点股 amount>1000 视为「元」需 /1e8，否则直接使用。
  3. 沪市=60/68，深市=00/30；sz_amount = total - sh_amount，保证 sh+sz=total 恒等式。
  4. 涨停阈值：主板(60/00) |涨跌幅|>=9.5%，创业板/科创板(30/68) >=19.5%；跌停对称。
  5. 不填字段（一律 NULL，绝不造假）：
        highest_board / lianban_count / seal_rate / break_rate / promotion_rate /
        broken_limit_count / real_limit_up / real_limit_down /
        yzt_avg_return / yzt_win_rate / emotion_score / stage
     这些涨停细分情绪依赖 limit_up_daily（缺口窗口多数日缺失），或属观察层衍生，
     不在本次「客观补洞」范围。基础涨停家数(limit_up_count/limit_down_count)从
     change_pct 客观算出，明确语义、可填。

用法：
  python build_market_daily.py --start 2026-07-15 --end 2026-07-31
  python build_market_daily.py --start 2026-07-15 --end 2026-07-31 --dry-run
"""
import sqlite3
import os
import argparse

DB = os.path.join(os.path.dirname(__file__), "database", "vibe_research.db")


def get_conn():
    return sqlite3.connect(DB)


def get_dates(start: str, end: str):
    con = get_conn()
    cur = con.cursor()
    cur.execute(
        "SELECT DISTINCT date FROM stock_daily WHERE date>=? AND date<=? ORDER BY date",
        (start, end),
    )
    ds = [r[0] for r in cur.fetchall()]
    con.close()
    return ds


def unit_factor(con, date: str) -> float:
    """锚点股(600519 贵州茅台)判断 amount 单位。>1000 视为「元」需换算为亿；否则已是亿元。"""
    cur = con.cursor()
    cur.execute("SELECT amount FROM stock_daily WHERE date=? AND code='600519'", (date,))
    r = cur.fetchone()
    if r and r[0] is not None and r[0] > 1000:
        return 1e-8  # 元 -> 亿元
    return 1.0       # 已是亿元


def compute_day(con, date: str) -> dict:
    cur = con.cursor()
    uf = unit_factor(con, date)
    # base：真实 A 股前缀(60/00/30/68)，且折算成「亿元」后金额落在 (0, 1000] 区间——
    # 用以剔除通达信指数/基金汇总行（折算后达万亿级、单股不可能），真实个股单日成交罕超千亿。
    # 同时兼容早期批次单位为「元」的情况（锚点股>1000 时 uf=1e-8，此处统一换算后过滤）。
    # 注意：不能用 name 非空判别——早期批次(7-15~7-20)连真实股票 name 都为空。
    cur.execute(
        """
        WITH base AS (
            SELECT code, amount * ? AS amt, change_pct FROM stock_daily
            WHERE date = ?
              AND substr(code,1,2) IN ('60','00','30','68')
              AND amount * ? > 0 AND amount * ? <= 1000
        )
        SELECT
            SUM(amt),
            SUM(CASE WHEN code LIKE '60%' OR code LIKE '68%' THEN amt ELSE 0 END),
            SUM(CASE WHEN change_pct >  0.005 THEN 1 ELSE 0 END),
            SUM(CASE WHEN change_pct < -0.005 THEN 1 ELSE 0 END),
            SUM(CASE WHEN change_pct BETWEEN -0.005 AND 0.005 THEN 1 ELSE 0 END),
            SUM(CASE WHEN (code LIKE '60%' OR code LIKE '00%') AND change_pct >=  9.5 THEN 1 ELSE 0 END)
          + SUM(CASE WHEN (code LIKE '30%' OR code LIKE '68%') AND change_pct >= 19.5 THEN 1 ELSE 0 END),
            SUM(CASE WHEN (code LIKE '60%' OR code LIKE '00%') AND change_pct <= -9.5 THEN 1 ELSE 0 END)
          + SUM(CASE WHEN (code LIKE '30%' OR code LIKE '68%') AND change_pct <= -19.5 THEN 1 ELSE 0 END)
        FROM base
        """,
        (uf, date, uf, uf),
    )
    total, sh, up, down, flat, zt, dt = cur.fetchone()
    total = float(total or 0.0)
    sh = float(sh or 0.0)
    return dict(
        total_amount=round(total, 2),
        sh_amount=round(sh, 2),
        sz_amount=round(total, 2) - round(sh, 2),  # 严格恒等拆分，杜绝浮点舍入差
        up_count=int(up or 0),
        down_count=int(down or 0),
        flat_count=int(flat or 0),
        limit_up_count=int(zt or 0),
        limit_down_count=int(dt or 0),
    )


def rolling(con, date: str, totals: dict):
    """基于已知 total 序列（历史 + 本次窗口内已算日期）算 change_rate/avg_5d/avg_20d。"""
    seq = sorted((d, t) for d, t in totals.items() if d <= date)
    idx = {d: i for i, (d, _) in enumerate(seq)}
    i = idx[date]
    prev = seq[i - 1][1] if i > 0 else None
    change_rate = round((totals[date] - prev) / prev, 4) if (prev and prev > 0) else None
    w5 = [t for _, t in seq[max(0, i - 4): i + 1]]
    w20 = [t for _, t in seq[max(0, i - 19): i + 1]]
    avg5 = round(sum(w5) / len(w5), 2) if len(w5) >= 2 else None
    avg20 = round(sum(w20) / len(w20), 2) if len(w20) >= 2 else None
    return change_rate, avg5, avg20


def main():
    ap = argparse.ArgumentParser(description="本地回填 market_daily 客观字段")
    ap.add_argument("--start", required=True, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="截止日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = ap.parse_args()

    dates = get_dates(args.start, args.end)
    if not dates:
        print("无数据，检查 stock_daily 日期范围。")
        return

    con = get_conn()
    cur = con.cursor()
    # 载入历史已有 total（用于滚动均值）
    cur.execute("SELECT date, total_amount FROM market_daily WHERE total_amount IS NOT NULL")
    totals = {r[0]: r[1] for r in cur.fetchall()}

    rows = []
    UNSOURCED = (  # 缺口窗口缺源、留 NULL 的字段
        "broken_limit_count", "highest_board", "lianban_count", "seal_rate", "break_rate",
        "promotion_rate", "yzt_avg_return", "yzt_win_rate", "emotion_score", "stage",
        "real_limit_up", "real_limit_down",
    )
    for d in dates:
        c = compute_day(con, d)
        totals[d] = c["total_amount"]  # 让窗口内后一天能看到前一天
        cr, avg5, avg20 = rolling(con, d, totals)
        c.update(
            date=d,
            amount_change_rate=cr,
            avg_5d_amount=avg5,
            avg_20d_amount=avg20,
        )
        for k in UNSOURCED:
            c.setdefault(k, None)
        rows.append(c)
    con.close()

    if args.dry_run:
        print(f"DRY-RUN: {len(rows)} 个交易日，单位=亿元")
        print(f"{'date':12}{'total':>10}{'sh':>10}{'sz':>10}{'up':>6}{'down':>6}"
              f"{'flat':>5}{'zt':>4}{'dt':>4}{'chgR':>9}")
        for r in rows:
            print(f"{r['date']:12}{r['total_amount']:>10}{r['sh_amount']:>10}{r['sz_amount']:>10}"
                  f"{r['up_count']:>6}{r['down_count']:>6}{r['flat_count']:>5}"
                  f"{r['limit_up_count']:>4}{r['limit_down_count']:>4}"
                  f"{str(r['amount_change_rate']):>9}")
        return

    con = get_conn()
    cur = con.cursor()
    n = 0
    for r in rows:
        cur.execute(
            """
            INSERT OR REPLACE INTO market_daily
            (date, total_amount, sh_amount, sz_amount, amount_change_rate, avg_5d_amount, avg_20d_amount,
             up_count, down_count, flat_count, limit_up_count, limit_down_count,
             real_limit_up, real_limit_down, broken_limit_count, highest_board, lianban_count,
             seal_rate, break_rate, promotion_rate, yzt_avg_return, yzt_win_rate, emotion_score, stage)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (r["date"], r["total_amount"], r["sh_amount"], r["sz_amount"], r["amount_change_rate"],
             r["avg_5d_amount"], r["avg_20d_amount"], r["up_count"], r["down_count"], r["flat_count"],
             r["limit_up_count"], r["limit_down_count"], r["real_limit_up"], r["real_limit_down"],
             r["broken_limit_count"], r["highest_board"], r["lianban_count"], r["seal_rate"],
             r["break_rate"], r["promotion_rate"], r["yzt_avg_return"], r["yzt_win_rate"],
             r["emotion_score"], r["stage"]),
        )
        n += 1
    con.commit()
    con.close()
    print(f"WROTE {n} 天 ({args.start}..{args.end})")


if __name__ == "__main__":
    main()
