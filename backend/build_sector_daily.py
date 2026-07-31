"""回填 sector_daily：基于 industry_map(东财成分) × stock_daily 逐日聚合板块级序列。

完全本地、零外部依赖。采用 SQLite 端聚合（一条 SQL + 窗口函数取板块龙头），
6425 个交易日全量回填仅需分钟级（远快于逐天 Python 循环）。

net_amount 数据源说明（重要）：
  - 板块净流入 = Σ(成分股 stock_flow_daily.main_net_buy)。stock_daily.main_net_buy 全表为
    NULL（历史误用该列 → net_amount 恒为 0，即"死列"），故本脚本改为 JOIN stock_flow_daily。
  - stock_flow_daily 真实区间起于 2026-07-20（此前为占位值 -0.3447）。因此：
      * 仅对 >= 2026-07-20 的日期回填才有有效 net_amount；
      * 早于该日的 net_amount 应置 NULL（见下方 --nullify-historical），勿用 --all 重算历史，
        否则历史会被占位值污染。

用法：
  python build_sector_daily.py --recent 250          # 最近 250 个交易日
  python build_sector_daily.py --start 2026-01-01    # 某起始日至今
  python build_sector_daily.py --start 2026-07-20 --end 2026-07-31   # 回填真实资金流窗口
  python build_sector_daily.py --all                 # 全量回填（默认，⚠️历史 net_amount 会失真）
  python build_sector_daily.py --recent 30 --dry-run # 只统计不写库
  python build_sector_daily.py --nullify-historical  # 将 <=2026-07-19 的 net_amount 置 NULL
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

DB = str(Path(__file__).resolve().parent / "database" / "vibe_research.db")


def connect():
    """打开连接并施加容错：WAL 日志 + 长 busy_timeout，避免并发写锁。"""
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass  # 已有其他连接持有非 WAL 模式时忽略
    return conn

# 主聚合 SQL（含板块龙头：按 date+行业 amount 最大的成分股）
SQL = """
INSERT OR REPLACE INTO sector_daily
  (date, sector_name, change_pct, amount, amount_ratio, amount_change_rate, net_amount,
   up_count, down_count, flat_count, limit_up_count, cm20_count,
   leader_code, leader_name, leader_change_pct, leader_amount,
   days_in_top5, consecutive_days, sector_score, tier)
SELECT s.date, im.industry_name,
  ROUND(AVG(s.change_pct), 3),
  ROUND(SUM(s.amount), 2),
  NULL, NULL,
  ROUND(SUM(COALESCE(f.main_net_buy, 0)), 2),
  SUM(CASE WHEN s.change_pct > 0 THEN 1 ELSE 0 END),
  SUM(CASE WHEN s.change_pct < 0 THEN 1 ELSE 0 END),
  SUM(CASE WHEN s.change_pct = 0 THEN 1 ELSE 0 END),
  SUM(CASE WHEN s.change_pct >= 9.5 THEN 1 ELSE 0 END),
  SUM(CASE WHEN s.close >= s.ma20 THEN 1 ELSE 0 END),
  l.leader_code, l.leader_name, l.leader_change_pct, l.leader_amount,
  NULL, NULL, NULL, NULL
FROM stock_daily s
JOIN industry_map im ON s.code = im.stock_code
LEFT JOIN stock_flow_daily f ON f.date = s.date AND f.code = s.code
LEFT JOIN (
  SELECT s2.date, im2.industry_name,
    s2.code AS leader_code, s2.name AS leader_name,
    s2.change_pct AS leader_change_pct, s2.amount AS leader_amount,
    ROW_NUMBER() OVER (PARTITION BY s2.date, im2.industry_name ORDER BY s2.amount DESC) rn
      FROM stock_daily s2 JOIN industry_map im2 ON s2.code = im2.stock_code {lwhere}
  ) l ON l.date = s.date AND l.industry_name = im.industry_name AND l.rn = 1
{where}
GROUP BY s.date, im.industry_name
"""


def get_dates(start=None, end=None, recent=None):
    c = connect()
    q = "SELECT DISTINCT date FROM stock_daily"
    cond = []
    if start:
        cond.append(f"date>='{start}'")
    if end:
        cond.append(f"date<='{end}'")
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY date"
    ds = [r[0] for r in c.execute(q).fetchall()]
    c.close()
    if recent:
        ds = ds[-recent:]
    return ds


def build(dates, dry_run=False):
    if not dates:
        return 0
    conn = connect()
    where = f"WHERE s.date >= '{dates[0]}' AND s.date <= '{dates[-1]}'"
    lwhere = where.replace('s.date', 's2.date')
    if dry_run:
        cnt = conn.execute(
            f"SELECT COUNT(*) FROM (SELECT 1 FROM stock_daily s "
            f"JOIN industry_map im ON s.code=im.stock_code {where} "
            f"GROUP BY s.date, im.industry_name)").fetchone()[0]
        conn.close()
        return cnt
    conn.execute("DELETE FROM sector_daily WHERE date >= ? AND date <= ?",
                 (dates[0], dates[-1]))
    t0 = time.time()
    conn.execute(SQL.format(where=where, lwhere=lwhere))
    conn.commit()
    n = conn.execute("SELECT changes()").fetchone()[0]
    conn.close()
    return n, round(time.time() - t0, 1)


def nullify_historical(cutoff="2026-07-19"):
    """将早于真实资金流区间的 net_amount 置 NULL，避免 0 被误读为'无净流入'。"""
    conn = connect()
    n = conn.execute(
        "UPDATE sector_daily SET net_amount = NULL WHERE date <= ? AND net_amount IS NOT NULL",
        (cutoff,),
    ).rowcount
    conn.commit()
    conn.close()
    print(f"✅ 已将 <= {cutoff} 的 net_amount 置 NULL（共 {n} 行，诚实标记无真实资金流）。")


def main():
    ap = argparse.ArgumentParser(description="回填 sector_daily（板块级历史序列）")
    ap.add_argument("--recent", type=int, help="最近 N 个交易日")
    ap.add_argument("--start", help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", help="截止日 YYYY-MM-DD")
    ap.add_argument("--all", action="store_true", help="全量回填（默认，⚠️历史 net_amount 失真）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    ap.add_argument("--nullify-historical", action="store_true",
                    help="将 <=2026-07-19 的 net_amount 置 NULL（诚实标记无真实资金流）")
    args = ap.parse_args()

    if args.nullify_historical:
        nullify_historical()
        return

    dates = get_dates(args.start, args.end, args.recent)
    if not dates:
        print("无目标日期，退出。")
        return
    print(f"目标交易日：{len(dates)} 个（{dates[0]} ~ {dates[-1]}）"
          f"{' [dry-run]' if args.dry_run else ''}")

    if args.dry_run:
        n = build(dates, dry_run=True)
        print(f"dry-run 完成，预计写入 {n} 行（未落库）。")
        return
    n, sec = build(dates, dry_run=False)
    print(f"✅ 写入 sector_daily 共 {n} 行，耗时 {sec}s。")


if __name__ == "__main__":
    main()
