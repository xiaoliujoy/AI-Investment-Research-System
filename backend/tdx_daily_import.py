# -*- coding: utf-8 -*-
"""增量重导通达信个股日线（日常流水线 step1 用）。

为什么需要：
  daily_collect.py 原 STEPS 只有 sector(板块API) + cap(市值)，
  从未重导通达信本地个股日线，导致 stock_daily 最新交易日长期落后
  真实交易日 1~2 天（如板块已到 07-16，个股日线还停在 07-15）。

做法：
  只拉 stock_daily 最新日及之后的记录（INSERT OR REPLACE 幂等），
  补齐遗漏的交易日。本机无 vipdoc（沙箱/无通达信环境）时自动跳过。

用法：
  python tdx_daily_import.py            # 增量重导（默认）
  python tdx_daily_import.py --full    # 无视最新日，从 2000 起全量重导
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_tdx

DB = str(Path(__file__).parent / "database" / "vibe_research.db")


def _latest() -> str | None:
    try:
        c = sqlite3.connect(DB)
        d = c.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
        c.close()
        return d
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="增量重导通达信个股日线")
    ap.add_argument("--full", action="store_true", help="从 2000 起全量重导（忽略最新日）")
    args = ap.parse_args()

    # 本机无 vipdoc → 跳过（沙箱/无通达信环境安全降级）
    if not import_tdx.TDX_PATH.exists():
        print("本机无 vipdoc，跳过 TDX 日线重导")
        return

    start = "2000-01-01" if args.full else (_latest() or "2000-01-01")
    print(f"TDX 增量重导 start_date={start}")
    total = 0
    for m in ["sh", "sz", "bj"]:
        r = import_tdx.import_market_data(m, start, dry_run=False)
        total += r["records"]
        print(f"  {m}: {r['files']} 文件 / {r['records']} 记录")
    print(f"TDX 增量重导完成，新增/更新 {total} 行")


if __name__ == "__main__":
    main()
