#!/usr/bin/env python3
"""MT5 交易记录导出器 (研投君定制版)

前置条件:
  - Windows + 已安装并登录的 MT5 终端【正在运行】
  - Python 3.11 或 3.12 (MetaTrader5 不支持 3.13)
  - pip install MetaTrader5 pandas

用法:
  python mt5_export.py --from 2024-01-01 --to 2026-08-04 --out mt5_history
  python mt5_export.py --group            # 额外输出按持仓聚合的逐笔交易
  python mt5_export.py --bars XAUUSD --bars-from 2026-03-01 --bars-out mt5_raw
                                          # 仅导 K 线(Trade Path Reconstruction 前置)

输出文件(UTF-8 BOM, Excel 可直接开):
  {out}_deals.csv      成交明细(每笔 execution: 开/平/手续费/库存费/盈亏)
  {out}_orders.csv     订单历史(挂单/成交/撤单)
  {out}_trades.csv     逐笔交易(按 position_id 聚合, --group 时)
  {out}_summary.json   基础统计(胜率/期望值/盈亏比/净盈亏)
  {bars_out}/{SYM}_M1.csv / _M5.csv / _M15.csv   K线(time 为 epoch 秒)

K 线导出说明(2026-08-05 实测约束, 见 docs/trader_os_behavior_engine_v0.1.md §10):
  - MT5 终端对单次 copy_rates_from_pos 有硬上限(本机 XAUUSD M1 实测 80000 根),
    超限直接返回 0 而不是截断, 所以这里一律按【周】分段 copy_rates_range 拉取。
  - 各周期本地缓存深度不同: 本机 M1 仅回溯至 2026-05-14, M5/M15 可回溯至 2025-12。
    因此路径重建必须做混合精度(优先 M1, 回退 M5), 不能假设 M1 全期可用。
  - copy_rates_range 的 datetime 按 UTC 解释, 返回的 time 列是 epoch 秒, 与 deals 一致。

注意: summary 的胜率基于"成交笔数"粗算(开仓成交 profit=0 会略微拉低胜率);
做严谨的逐笔统计请以 --group 产出的 trades.csv 为准, 我导入后会重新计算。
"""
import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    raise SystemExit("未安装 MetaTrader5, 请先: pip install MetaTrader5")

ENTRY_IN = getattr(mt5, "DEAL_ENTRY_IN", 0)
ENTRY_OUT = getattr(mt5, "DEAL_ENTRY_OUT", 1)
ENTRY_INOUT = getattr(mt5, "DEAL_ENTRY_INOUT", 2)


def dt_str(v):
    """时间统一输出为 epoch 秒整数(与 K 线 time 列一致), 避免 ISO/epoch 混排。
    MT5 返回 naive datetime(UTC), 视为 UTC 转 epoch。"""
    if isinstance(v, datetime):
        return int(v.replace(tzinfo=timezone.utc).timestamp())
    return v


def to_rows(objs, time_keys):
    rows = [o._asdict() for o in objs]
    for r in rows:
        for k in time_keys:
            if k in r:
                r[k] = dt_str(r[k])
    return rows


def write_csv(path, rows):
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def fetch_history_segmented(func, f, t, step_days=7):
    """按周分段拉取 history_deals/orders 再按 ticket 合并去重。

    MT5 的 history_deals_get(from, to) 在范围过大、本地历史库较大时会被
    内部截断(实测 2026-03~08 一次性调用只回 447 条止步 7/13, 但按周分段
    能完整拿到 8 月)。改为分段循环调用, 用 ticket 去重合并。
    """
    merged = {}
    cur = f
    while cur < t:
        nxt = min(cur + timedelta(days=step_days), t)
        objs = func(cur, nxt)
        if objs:
            for o in objs:
                merged[int(o.ticket)] = o
        cur = nxt
    return list(merged.values())


def export_bars(symbol, from_date, to_date, out_dir, timeframes=("M1", "M5", "M15")):
    """按周分段导出 K 线, 规避终端单次请求上限。

    返回 {tf: {"rows": n, "earliest": iso, "latest": iso, "path": p}}
    """
    tf_map = {
        "M1": (mt5.TIMEFRAME_M1, 60),
        "M5": (mt5.TIMEFRAME_M5, 300),
        "M15": (mt5.TIMEFRAME_M15, 900),
    }
    if not mt5.symbol_select(symbol, True):
        print(f"⚠ symbol_select({symbol}) 失败: {mt5.last_error()}")
        return {}

    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for tf_name in timeframes:
        tf, _sec = tf_map[tf_name]
        merged = {}
        cur = from_date
        gaps = 0
        while cur < to_date:
            nxt = min(cur + timedelta(days=7), to_date)
            rates = mt5.copy_rates_range(symbol, tf, cur, nxt)
            if rates is None or len(rates) == 0:
                gaps += 1
            else:
                for r in rates:
                    merged[int(r["time"])] = (
                        float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]),
                        int(r["tick_volume"]),
                    )
            cur = nxt

        if not merged:
            print(f"  {tf_name}: 无数据(该周期本地缓存不覆盖此区间)")
            result[tf_name] = {"rows": 0}
            continue

        keys = sorted(merged)
        path = os.path.join(out_dir, f"{symbol}_{tf_name}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "open", "high", "low", "close", "tick_volume"])
            for t in keys:
                o, h, lo, c, v = merged[t]
                w.writerow([t, o, h, lo, c, v])
        earliest = datetime.utcfromtimestamp(keys[0]).isoformat()
        latest = datetime.utcfromtimestamp(keys[-1]).isoformat()
        print(f"  {tf_name}: {len(keys)} 根  {earliest} ~ {latest}  空段周数={gaps}  -> {path}")
        result[tf_name] = {
            "rows": len(keys), "earliest": earliest,
            "latest": latest, "path": path, "empty_weeks": gaps,
        }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", default="2020-01-01")
    ap.add_argument("--to", dest="to_date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default="mt5_history")
    ap.add_argument("--group", action="store_true", help="额外输出逐笔交易(按持仓聚合)")
    ap.add_argument("--bars", default=None,
                    help="导出该品种的 K 线(如 XAUUSD)。指定后只导 K 线, 不重复导成交")
    ap.add_argument("--bars-from", dest="bars_from", default="2026-03-01")
    ap.add_argument("--bars-to", dest="bars_to",
                    default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--bars-out", dest="bars_out", default="mt5_raw")
    ap.add_argument("--timeframes", default="M1,M5,M15")
    args = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit(
            f"MT5 初始化失败: {mt5.last_error()}\n"
            "请确认 MT5 终端已打开并登录(脚本读取的是正在运行的终端实例)。"
        )

    info = mt5.account_info()
    print(f"已连接账户: login={info.login} server={info.server} currency={info.currency}")

    # ---- K 线导出模式(Trade Path Reconstruction 前置) ----
    if args.bars:
        bf = datetime.strptime(args.bars_from, "%Y-%m-%d")
        bt = datetime.strptime(args.bars_to, "%Y-%m-%d") + timedelta(days=1)
        tfs = tuple(x.strip() for x in args.timeframes.split(",") if x.strip())
        print(f"导出 K 线: {args.bars}  {args.bars_from} ~ {args.bars_to}  周期={tfs}")
        meta = export_bars(args.bars, bf, bt, args.bars_out, tfs)
        with open(os.path.join(args.bars_out, f"{args.bars}_bars_meta.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        mt5.shutdown()
        print("K 线导出完成。下一步: python backend/trade_path_reconstruction.py")
        return

    f = datetime.strptime(args.from_date, "%Y-%m-%d")
    t = datetime.strptime(args.to_date, "%Y-%m-%d") + timedelta(days=1)

    # 按周分段拉取再合并: 单次大范围 history_deals_get 在本地历史库较大时
    # 会被内部截断(实测 3月~8月只回 447 条止步 7/13, 按周分段方能拿到 8月)。
    deals = fetch_history_segmented(mt5.history_deals_get, f, t)
    orders = fetch_history_segmented(mt5.history_orders_get, f, t)

    if deals is None:
        print("成交记录为空或读取失败:", mt5.last_error())
    else:
        drows = to_rows(deals, ("time", "time_msc", "open_time", "close_time"))
        write_csv(f"{args.out}_deals.csv", drows)
        print(f"成交明细: {len(drows)} 条 -> {args.out}_deals.csv")

    if orders:
        orows = to_rows(orders, ("time_setup", "time_done", "time_expiration"))
        write_csv(f"{args.out}_orders.csv", orows)
        print(f"订单历史: {len(orows)} 条 -> {args.out}_orders.csv")

    # 逐笔交易(按持仓聚合)
    # 聚合无条件执行(summary 依赖它), CSV 仅在 --group 时写出
    trows = []
    if deals:
        trades = {}
        for d in drows:
            pid = d.get("position_id")
            # pid==0 是 balance/入金/出金等非交易记录, 必须剔除,
            # 否则初始入金会被当成一笔巨额盈利交易污染全部统计
            if pid is None or pid == 0:
                continue
            tr = trades.setdefault(
                pid,
                {
                    "position_id": pid,
                    "symbol": d.get("symbol"),
                    "net_profit": 0.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "volume": 0.0,
                    "entry_time": d.get("time"),
                    "exit_time": d.get("time"),
                    "n_deals": 0,
                    "direction": None,
                },
            )
            tr["net_profit"] += d.get("profit", 0) or 0
            tr["commission"] += d.get("commission", 0) or 0
            tr["swap"] += d.get("swap", 0) or 0
            tr["volume"] += d.get("volume", 0) or 0
            tr["n_deals"] += 1
            et = d.get("time")
            if et < tr["entry_time"]:
                tr["entry_time"] = et
            if et > tr["exit_time"]:
                tr["exit_time"] = et
            if d.get("entry") in (ENTRY_IN, ENTRY_INOUT):
                tr["direction"] = "BUY" if d.get("type") == 0 else "SELL"
        trows = list(trades.values())
        for tr in trows:
            # 口径: 真实盈亏 = 成交盈亏 + 手续费 + 库存费
            tr["pnl"] = round(tr["net_profit"] + tr["commission"] + tr["swap"], 2)
            tr["result"] = (
                "WIN" if tr["pnl"] > 0 else ("LOSS" if tr["pnl"] < 0 else "FLAT")
            )
        if args.group:
            write_csv(f"{args.out}_trades.csv", trows)
            print(f"逐笔交易: {len(trows)} 笔 -> {args.out}_trades.csv")

    # 基础统计
    # 口径声明(改前的版本三处错误, 已修正):
    #   1) 分母必须是「逐笔交易」而非「成交明细」, 后者含开仓腿(profit=0)与入金记录
    #   2) profit==0 不是亏损, 单列 FLAT, 不计入胜率分母外的任何一侧
    #   3) 盈亏须含 commission + swap, 否则高频交易的成本被完全隐藏
    if trows:
        pnls = [t["pnl"] for t in trows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        flats = [p for p in pnls if p == 0]
        gross_w = sum(wins)
        gross_l = sum(losses)
        summary = {
            "account": info.login,
            "server": info.server,
            "range": [args.from_date, args.to_date],
            "basis": "per-trade (position-aggregated), incl. commission+swap",
            "deal_count": len(drows),
            "trade_count": len(trows),
            "gross_profit": round(gross_w, 2),
            "gross_loss": round(gross_l, 2),
            "net_profit": round(gross_w + gross_l, 2),
            "win_count": len(wins),
            "loss_count": len(losses),
            "flat_count": len(flats),
            "win_rate_pct": round(len(wins) / len(trows) * 100, 2),
            "profit_factor": round(gross_w / abs(gross_l), 2) if gross_l else None,
            "avg_win": round(gross_w / len(wins), 2) if wins else 0,
            "avg_loss": round(gross_l / len(losses), 2) if losses else 0,
            "expectancy": round((gross_w + gross_l) / len(trows), 2),
        }
        with open(f"{args.out}_summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print("摘要 ->", f"{args.out}_summary.json")

    mt5.shutdown()
    print("完成。把生成的 *_deals.csv / *_trades.csv 丢进项目, 我直接做全维度分析。")


if __name__ == "__main__":
    main()
