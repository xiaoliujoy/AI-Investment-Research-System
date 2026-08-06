#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trader OS · Layer 3 路径层 —— 反事实规则回放 (Counterfactual Replay v0.1)

上位: docs/trader_os_behavior_engine_v0.1.md
依赖: backend/trade_path_reconstruction.py (共用 bar / deals 载入与持仓重建)

目的:
    用已重建的价格路径, 前向回放"如果当时执行了某条规则"的结果,
    在不等待前瞻实验的前提下, 先给出规则的量级估计。

------------------------------------------------------------------
【反后视偏差声明 · 本模块存在的理由】
    第一版模拟曾用「MFE 早于 MAE」作为规则触发条件, 这是错的:
    MFE/MAE 的先后顺序是平仓之后才知道的信息, 用它决定"当时是否移止损"
    等于偷看答案, 会系统性高估规则收益。

    本模块改为【逐 bar 前向重放】: 在时间轴上一根一根走, 任一时点只用
    该时点之前已发生的信息决策, 与真实交易的信息集一致。
------------------------------------------------------------------

【bar 内顺序不可知问题】
    一根 bar 只有 OHLC, 无法知道 high 与 low 谁先发生。对同时可能触发
    "保本止损被打掉" 与 "浮盈继续扩大" 的 bar, 两种假设结果不同。
    本模块同时输出两种口径:
        pessimistic  假设不利方向先到 (先打止损)   -> 结果下界
        optimistic   假设有利方向先到 (先扩浮盈)   -> 结果上界
    只报单一数字是不诚实的, 真实值落在区间内。

【本模块不做什么】
    不产生交易建议, 不写回任何决策表。输出仅供 Behavior Engine 观测层
    评估"规则的潜在量级", 是否采用由人决定 (Independence Rule)。

用法:
    python backend/trade_path_counterfactual.py
    python backend/trade_path_counterfactual.py --rule breakeven --thresholds 5,10,15,20
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "mt5_raw")

sys.path.insert(0, HERE)
from trade_path_reconstruction import (  # noqa: E402
    load_bars, load_deals, build_positions, slice_bars, CONTRACT_SIZE,
    DEFAULT_CONTRACT,
)


def pick_source(p, sources):
    for tf_name, tf_sec, bars, t0, t1 in sources:
        if t0 <= p["in_time"] and p["out_time"] <= t1:
            return tf_name, tf_sec, bars
    return None


def replay_breakeven(p, bars, tf_sec, trigger_usd, cost_per_lot, order):
    """逐 bar 前向重放: 浮盈达到 trigger_usd 后把止损移到入场价(保本)。

    order: 'pess' 不利先到 / 'opt' 有利先到
    返回 (new_pnl, triggered, stopped_at_breakeven)
    """
    ep = p["entry_price"]
    is_buy = p["direction"] == "BUY"
    vol = p["volume"]
    cs = CONTRACT_SIZE.get(p["symbol"], DEFAULT_CONTRACT)
    mult = vol * cs

    seg = slice_bars(bars, p["in_time"], p["out_time"], tf_sec)
    if not seg:
        return None

    armed = False
    for (_bt, h, l) in seg:
        fav = (h - ep) if is_buy else (ep - l)      # 该 bar 内最大有利位移
        adv = (ep - l) if is_buy else (h - ep)      # 该 bar 内最大不利位移

        if order == "pess":
            # 先看不利: 若已武装且价格回到入场价 -> 保本出局
            if armed and adv >= 0:
                return -cost_per_lot * mult / cs, True, True
            if fav * mult >= trigger_usd:
                armed = True
        else:
            # 先看有利: 本 bar 内先扩浮盈再回落
            if fav * mult >= trigger_usd:
                armed = True
            if armed and adv >= 0:
                return -cost_per_lot * mult / cs, True, True

    # 未被保本止损打掉 -> 保持真实结果
    return p["pnl"], armed, False


def run(rule, thresholds, cost, symbol, bars_dir, deals_path):
    sources = []
    for tf_name, tf_sec in (("M1", 60), ("M5", 300), ("M15", 900)):
        path = os.path.join(bars_dir, f"{symbol}_{tf_name}.csv")
        if os.path.exists(path):
            b = load_bars(path)
            if b:
                sources.append((tf_name, tf_sec, b, b[0][0], b[-1][0]))
    if not sources:
        print("缺少 K 线, 先跑: python mt5_export.py --bars", symbol)
        sys.exit(2)

    positions = build_positions(load_deals(deals_path), symbol)
    usable = []
    for p in positions:
        s = pick_source(p, sources)
        if s:
            usable.append((p, s))
    base = sum(p["pnl"] for p, _ in usable)

    print(f"样本: {len(usable)} 笔  实际净盈亏基线: {base:.2f}")
    print(f"规则: {rule}   成本假设: {cost} USD/手往返\n")
    header = ("阈值USD", "触发笔数", "保本出局", "悲观净额", "悲观差异",
              "乐观净额", "乐观差异")
    print("%-8s %-9s %-9s %-11s %-11s %-11s %-11s" % header)

    out = {"base_pnl": round(base, 2), "n": len(usable), "rule": rule,
           "cost_per_lot": cost, "results": []}

    for thr in thresholds:
        res = {}
        for order in ("pess", "opt"):
            tot = 0.0
            trig = 0
            stopped = 0
            improved = 0
            worsened = 0
            for p, (tf_name, tf_sec, bars) in usable:
                r = replay_breakeven(p, bars, tf_sec, thr, cost, order)
                if r is None:
                    tot += p["pnl"]
                    continue
                new_pnl, t, st = r
                trig += 1 if t else 0
                stopped += 1 if st else 0
                if st:
                    if new_pnl > p["pnl"]:
                        improved += 1
                    elif new_pnl < p["pnl"]:
                        worsened += 1
                tot += new_pnl
            res[order] = {
                "net": round(tot, 2), "delta": round(tot - base, 2),
                "triggered": trig, "stopped_at_be": stopped,
                "improved": improved, "worsened": worsened,
            }
        print("%-8d %-9d %-9d %-11.2f %+-11.2f %-11.2f %+-11.2f" % (
            thr, res["pess"]["triggered"], res["pess"]["stopped_at_be"],
            res["pess"]["net"], res["pess"]["delta"],
            res["opt"]["net"], res["opt"]["delta"]))
        out["results"].append({"threshold_usd": thr, **res})

    print("\n改善/恶化明细(悲观口径):")
    for r in out["results"]:
        p = r["pess"]
        print("  阈值%-3d 保本出局%-3d 笔  其中改善%-3d 恶化%-3d" % (
            r["threshold_usd"], p["stopped_at_be"], p["improved"], p["worsened"]))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default="breakeven", choices=["breakeven"])
    ap.add_argument("--thresholds", default="5,10,15,20,30")
    ap.add_argument("--cost", type=float, default=0.34,
                    help="每手往返成本 USD(XAUUSD 0.01 手实测约 0.34)")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars-dir", dest="bars_dir", default=RAW)
    ap.add_argument("--deals", default=os.path.join(RAW, "mt5_history_deals.csv"))
    ap.add_argument("--out", default=os.path.join(RAW, "counterfactual_breakeven.json"))
    args = ap.parse_args()

    thresholds = [int(x) for x in args.thresholds.split(",") if x.strip()]
    out = run(args.rule, thresholds, args.cost, args.symbol,
              args.bars_dir, args.deals)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n->", args.out)
    print("\n注意: 悲观/乐观区间来自 bar 内顺序不可知; 真实值落在区间内。")
    print("      本结果为历史重放, 不构成前瞻验证, 不得直接当作规则收益。")


if __name__ == "__main__":
    main()
