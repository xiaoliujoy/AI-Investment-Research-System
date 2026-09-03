# -*- coding: utf-8 -*-
"""派生行情表统一增量补齐：sector_daily / market_daily / limit_up_daily。

背景（2026-08-07 ~ 08-10 连续两次事故）
---------------------------------------------------------------
这三张表全部由 stock_daily 本地聚合而来，但**没有任何一步挂在 run_daily.py 流水线里**
（sector_daily 仅被 tdx_refresh.py 调用，market_daily / limit_up_daily 更是纯手动）。
结果：stock_daily / stock_flow_daily 每天正常落库，三张派生表却停在上一次手工执行的日期，
Decision Log 交叉验证连续报 no_baseline，日报据空表空算。

本脚本把「补齐」这件事收敛成一条幂等命令，并固化两条踩过坑的顺序约束。

顺序约束（不可调换，均为实测踩坑）
---------------------------------------------------------------
1) 必须在 tech_fill.py **之后**执行：
   sector_daily.cm20_count = COUNT(close >= ma20)。ma20 为 NULL 时 `close >= NULL` 恒为 NULL，
   该列会静默变成全 0（不是报错，是假数据）。2026-08-10 实测：全表 6446 个交易日中
   5646 天（87.6%）的 cm20_count 因此失真。
2) market_daily 必须在 limit_up_daily **之前**执行：
   build_limit_up_daily 结束时会回写 market_daily.highest_board / lianban_count / limit_up_count。
   若 market_daily 当日行尚不存在，这次 UPDATE 静默命中 0 行，三个字段留 NULL。

用法
---------------------------------------------------------------
  python build_derived_tables.py                 # 自动检测并补齐所有缺口（默认回看 30 天）
  python build_derived_tables.py --lookback 90   # 扩大回看窗口
  python build_derived_tables.py --date 2026-08-10   # 只补指定交易日
  python build_derived_tables.py --dry-run       # 只报缺口不写库

安全边界
---------------------------------------------------------------
- 默认只回看最近 30 个交易日，不做全量重算。
- sector_daily.net_amount 源自 stock_flow_daily，真实数据起于 2026-07-20；本脚本拒绝
  重建早于该日的 sector_daily，避免把占位值写进历史（见 build_sector_daily.py 文件头警告）。
- 全程幂等：底层三个 build_* 脚本均为「先 DELETE 目标区间再 INSERT」。
- 2026-08-27 修复：ma20 未就绪时**不再整体 return 2 中断**。原设计会因当日 ma20 缺失而把整轮
  增量补齐全部跳过（三表同时缺当天）。现改为仅延后 sector_daily 的 stale 日期，
  market_daily/limit_up_daily 照常补齐（二者不依赖 ma20）。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "database", "vibe_research.db")
PY = sys.executable

# sector_daily.net_amount 的真实资金流起始日，早于此日不重建（否则历史被占位值污染）
FLOW_REAL_START = "2026-07-20"

# (表名, 脚本名, 是否受 FLOW_REAL_START 约束)；顺序即执行顺序，不可调换
TABLES = [
    ("sector_daily", "build_sector_daily.py", True),
    ("market_daily", "build_market_daily.py", False),
    ("limit_up_daily", "build_limit_up_daily.py", False),
]


def connect():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def trading_days(conn, lookback):
    rows = conn.execute(
        "SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT ?", (lookback,)
    ).fetchall()
    return sorted(r[0] for r in rows)


def missing_dates(conn, table, days):
    """返回 days 中该表尚无任何记录的日期。"""
    if not days:
        return []
    ph = ",".join("?" * len(days))
    have = {
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT date FROM {table} WHERE date IN ({ph})", days
        ).fetchall()
    }
    return [d for d in days if d not in have]


def check_ma20_ready(conn, days):
    """tech_fill 前置检查：目标日 ma20 未回填时，cm20_count 会静默变全 0。"""
    if not days:
        return []
    ph = ",".join("?" * len(days))
    rows = conn.execute(
        f"SELECT date, SUM(CASE WHEN ma20 IS NOT NULL THEN 1 ELSE 0 END) FROM stock_daily "
        f"WHERE date IN ({ph}) GROUP BY date",
        days,
    ).fetchall()
    return [d for d, n in rows if not n]


def run_build(script, start, end):
    path = os.path.join(ROOT, script)
    cmd = [PY, path, "--start", start, "--end", end]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    tail = (proc.stdout + "\n" + proc.stderr).strip().splitlines()
    return proc.returncode == 0, (tail[-1] if tail else "")


def main():
    ap = argparse.ArgumentParser(description="派生行情表统一增量补齐")
    ap.add_argument("--lookback", type=int, default=30, help="回看最近 N 个交易日（默认 30）")
    ap.add_argument("--date", help="只补指定交易日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只报缺口不写库")
    args = ap.parse_args()

    conn = connect()
    days = [args.date] if args.date else trading_days(conn, args.lookback)
    if not days:
        print("stock_daily 无数据，退出。")
        return 1
    print(f"检查窗口：{days[0]} ~ {days[-1]}（{len(days)} 个交易日）")

    stale = check_ma20_ready(conn, days)
    if stale:
        # 2026-08-27 修复：ma20 未就绪不再整体 return 2 中断——否则仅当日 ma20 缺失就会
        # 把整轮 30 天增量补齐（含 market_daily/limit_up_daily）全部跳过，造成三表永久缺当天。
        # 改为：market_daily/limit_up_daily 不依赖 ma20，照常补齐；仅 sector_daily 延后 stale
        # 日期（cm20_count 依赖 ma20，写全0 是假数据），待 ma20 就绪后下一轮自动补齐。
        print(f"⚠ 以下日期 ma20 未回填（仅影响 sector_daily.cm20_count）：{stale}")
        print("  → sector_daily 将延后到 ma20 就绪后补齐；market_daily/limit_up_daily 不受影响。")
        print("  → 如需立即补齐 sector_daily，请先执行  python tech_fill.py  再重跑本脚本。")

    total = 0
    failed = []          # P0-A1：构建脚本返回非零的表
    deferred_map = {}    # table -> 被合法延后的日期集合
    for table, script, flow_bound in TABLES:
        miss = missing_dates(conn, table, days)
        deferred = []
        if flow_bound:
            blocked = [d for d in miss if d < FLOW_REAL_START]
            if blocked:
                print(f"  [{table}] 跳过 {len(blocked)} 天（早于资金流真实起点 {FLOW_REAL_START}）")
            miss = [d for d in miss if d >= FLOW_REAL_START]
            # sector_daily.cm20_count = COUNT(close>=ma20)，ma20 为 NULL 时该列静默变全0（假数据）。
            # 故 ma20 未就绪的日期延后补齐，绝不写全0。
            if stale:
                deferred = [d for d in miss if d in set(stale)]
                if deferred:
                    print(f"  [{table}] 延后 {len(deferred)} 天（ma20 未就绪，避免 cm20_count 静默全0）：{deferred[0]} ~ {deferred[-1]}")
                    miss = [d for d in miss if d not in set(stale)]
        if not miss:
            if deferred:
                print(f"  [{table}] 已延后至 ma20 就绪（不写全0 假数据），下一轮自动补齐")
            else:
                print(f"✅ {table:<16} 无缺口")
            continue
        print(f"🔧 {table:<16} 缺 {len(miss)} 天：{miss[0]} ~ {miss[-1]}")
        deferred_map[table] = set(deferred)
        if args.dry_run:
            continue
        ok, tail = run_build(script, miss[0], miss[-1])
        print(f"   {'OK ' if ok else 'FAIL'} {tail[:160]}")
        if ok:
            total += len(miss)
        else:
            failed.append(table)

    # ── 后置校验（P0-A1）：脚本 rc=0 不等于数据落地 ────────────────────────
    # 旧逻辑无论成败都 return 0 → run_daily 标 OK → market_daily 停更无人知晓
    # （2026-09-03 盘点发现 8717 行里 8678 行是空壳，正是这类静默失败的产物）。
    # 这里强制验证「窗口内最新交易日必须真的存在于每张派生表」，否则视为失败。
    verify_failed = []
    if not args.dry_run:
        latest = days[-1]
        cur = conn.cursor()
        for table, script, flow_bound in TABLES:
            if flow_bound and latest < FLOW_REAL_START:
                continue                                  # 早于资金流起点，合法跳过
            if latest in deferred_map.get(table, set()):
                continue                                  # ma20 未就绪，合法延后
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE date=?", (latest,))
            n = cur.fetchone()[0]
            if n == 0:
                verify_failed.append(table)
                print(f"   ❌ 后置校验失败：{table} 在最新交易日 {latest} 仍无数据")
            else:
                print(f"   ✅ 后置校验：{table} {latest} 有 {n} 行")

    conn.close()
    if args.dry_run:
        print("\n[dry-run] 未写库。")
    else:
        print(f"\n完成：补齐 {total} 个表-日。")

    if failed or verify_failed:
        print("=" * 68)
        print(f"build_derived_tables FAIL —— 阻断下游，防止派生表旧数据被当新数据使用")
        if failed:
            print(f"  构建脚本失败: {', '.join(failed)}")
        if verify_failed:
            print(f"  后置校验失败: {', '.join(verify_failed)}")
        print("=" * 68)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
