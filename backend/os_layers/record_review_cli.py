#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对话入口：保存一笔盘后复盘（含平仓归因）。

用法：
  python record_review_cli.py --tid 123 --close D --dq 4 --eq 2 --em 1 --judge y --exec n
  python record_review_cli.py --tid 123 --close B --dq 5 --eq 5 --em 4 --fear "浮亏时怕" --improve "按失效位持仓"

平仓归因 close: A逻辑错误 / B目标达成 / C风险调整 / D情绪退出
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trading_discipline_engine as ENG  # noqa


def main():
    p = argparse.ArgumentParser(description="保存盘后复盘（含平仓归因）")
    p.add_argument("--tid", type=int, required=True, help="关联计划 ID")
    p.add_argument("--dq", type=int, default=0, help="决策质量 ★ 1-5")
    p.add_argument("--eq", type=int, default=0, help="执行质量 ★ 1-5")
    p.add_argument("--em", type=int, default=0, help="情绪管理 ★ 1-5")
    p.add_argument("--judge", choices=["y", "n"], default="y", help="判断正确?")
    p.add_argument("--exec", choices=["y", "n"], default="y", help="执行正确?")
    p.add_argument("--close", choices=["A", "B", "C", "D"], default="",
                   help="平仓归因 A逻辑错误/B目标达成/C风险调整/D情绪退出")
    p.add_argument("--fear", default="", help="恐惧何时产生")
    p.add_argument("--improve", default="", help="下次怎么改进")
    p.add_argument("--dev", choices=["execution", "information", "none"], default="none",
                   help="偏差原因")
    a = p.parse_args()

    ENG.record_review(a.tid, a.dq, a.eq, a.em, a.judge, a.exec,
                      fear_trigger=a.fear, improvement=a.improve,
                      deviation_reason=a.dev, close_reason=a.close)
    # 即时回显 TAR，让训练反馈闭环
    tar = ENG.thesis_abandonment_rate()
    if tar.get("total"):
        t = tar["total"]
        flag = " ⚠️ D超10%·训练失败" if t["tar"] > 0.1 else " ✅ 达标"
        print("📉 全账户 TAR(D/方向正确) = %.1f%%%s" % (t["tar"] * 100, flag))


if __name__ == "__main__":
    main()
