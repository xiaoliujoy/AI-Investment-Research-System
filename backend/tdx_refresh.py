"""一键刷新数据地基（P0）：

  Step1  从通达信本地目录 C:\\new_tdx64\\vipdoc 重导 stock_daily（补齐次新/ST/遗漏）
  Step2  基于 industry_map × stock_daily 回填 sector_daily（板块级历史序列）

需在装有通达信的本机运行。沙箱无 vipdoc 时 Step1 自动跳过，仅做 Step2
（用现有 stock_daily 回填，同样可产出完整 sector_daily）。

用法：
  python tdx_refresh.py                 # 全量刷新
  python tdx_refresh.py --recent 250   # 只刷最近 250 个交易日（快速）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_tdx
import build_sector_daily as bsd


def refresh(recent=None):
    t0 = time.time()
    print("=" * 56)
    print("P0 数据地基一键刷新")
    print("=" * 56)

    print("\n[Step1] 重导 stock_daily（通达信本地 vipdoc）")
    for m in ["sh", "sz", "bj"]:
        r = import_tdx.import_market_data(m, None, dry_run=False)
        print(f"  {m}: 文件 {r['files']} / 记录 {r['records']}")
    if not any(import_tdx.import_market_data(m, None, dry_run=True)["files"]
               for m in ["sh", "sz", "bj"]):
        print("  （本机无 vipdoc，Step1 跳过；用现有 stock_daily 继续）")

    print("\n[Step2] 回填 sector_daily（industry_map × stock_daily，SQLite 端聚合）")
    dates = bsd.get_dates(recent=recent)
    w, sec = bsd.build(dates, dry_run=False)
    print(f"  写入 sector_daily 共 {w} 行，耗时 {sec}s")

    print(f"\n✅ 完成，总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="P0 数据地基一键刷新")
    ap.add_argument("--recent", type=int, help="仅最近 N 个交易日（默认全量）")
    args = ap.parse_args()
    refresh(recent=args.recent)
