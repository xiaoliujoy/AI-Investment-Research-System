"""OMI 命令行入口（Observation Only）。

用法：
  python run_omi.py                 # 采集今天
  python run_omi.py --date 2026-08-13
  python run_omi.py --list          # 仅打印观察标的

设计：只把数据写入 OMI 表（option_chain_raw / option_omi_daily），不参与任何 IC/CIO 评分。
不修改现有评分系统。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    # 作为模块运行：python -m omi.run_omi
    from .collect import collect_day
    from .storage import get_enabled_watchlist
except ImportError:
    # 直接作为脚本运行：python omi/run_omi.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from omi.collect import collect_day
    from omi.storage import get_enabled_watchlist


def main():
    parser = argparse.ArgumentParser(description="OMI 期权观察层采集 (v0.1, Observation Only)")
    parser.add_argument("--date", type=str, default=None, help="交易日 YYYY-MM-DD，默认今天")
    parser.add_argument("--list", action="store_true", help="仅列出观察标的")
    args = parser.parse_args()

    if args.list:
        for r in get_enabled_watchlist():
            print(f"  {r['omi_id']:8s} {r['name']:8s} [{r['exchange']:5s}] adapter={r['adapter']}")
        return

    print(f"[OMI] 开始采集 date={args.date or '今天'}")
    results = collect_day(args.date)
    print(f"[OMI] 完成 {len(results)} 个标的：")
    for r in results:
        line = f"  - {r['omi_id']:8s} {r['name']:8s} status={r['status']:12s} contracts={r['contracts']}"
        if r.get("atm_iv") is not None:
            line += f" atm_iv={r['atm_iv']*100:.1f}%"
        if r.get("iv_skew") is not None:
            line += f" skew={r['iv_skew']*100:.1f}pp"
        if r.get("note"):
            line += f"  # {r['note']}"
        print(line)

    # 汇总行（便于流水线/日报一眼扫过：今天几个 ok / 几个 stale / 几个 error）
    _cnt = {}
    for r in results:
        _cnt[r["status"]] = _cnt.get(r["status"], 0) + 1
    _ok = _cnt.get("ok", 0)
    _stale = _cnt.get("stale_data", 0)
    _other = len(results) - _ok - _stale
    print(f"[OMI] 汇总 ok={_ok} stale={_stale} other={_other} total={len(results)}")
    print("[OMI] 数据已写入 option_chain_raw / option_omi_daily（Observation Only，未进入评分）。")


if __name__ == "__main__":
    main()
