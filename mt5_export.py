#!/usr/bin/env python3
"""MT5 交易记录导出器 (研投君定制版)

前置条件:
  - Windows + 已安装并登录的 MT5 终端【正在运行】
  - Python 3.11 或 3.12 (MetaTrader5 不支持 3.13)
  - pip install MetaTrader5 pandas

用法:
  python mt5_export.py --from 2024-01-01 --to 2026-08-04 --out mt5_history
  python mt5_export.py --group            # 额外输出按持仓聚合的逐笔交易

输出文件(UTF-8 BOM, Excel 可直接开):
  {out}_deals.csv      成交明细(每笔 execution: 开/平/手续费/库存费/盈亏)
  {out}_orders.csv     订单历史(挂单/成交/撤单)
  {out}_trades.csv     逐笔交易(按 position_id 聚合, --group 时)
  {out}_summary.json   基础统计(胜率/期望值/盈亏比/净盈亏)

注意: summary 的胜率基于"成交笔数"粗算(开仓成交 profit=0 会略微拉低胜率);
做严谨的逐笔统计请以 --group 产出的 trades.csv 为准, 我导入后会重新计算。
"""
import argparse
import csv
import json
from datetime import datetime

try:
    import MetaTrader5 as mt5
except ImportError:
    raise SystemExit("未安装 MetaTrader5, 请先: pip install MetaTrader5")

ENTRY_IN = getattr(mt5, "DEAL_ENTRY_IN", 0)
ENTRY_OUT = getattr(mt5, "DEAL_ENTRY_OUT", 1)
ENTRY_INOUT = getattr(mt5, "DEAL_ENTRY_INOUT", 2)


def dt_str(v):
    return v.isoformat() if isinstance(v, datetime) else v


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", default="2020-01-01")
    ap.add_argument("--to", dest="to_date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default="mt5_history")
    ap.add_argument("--group", action="store_true", help="额外输出逐笔交易(按持仓聚合)")
    args = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit(
            f"MT5 初始化失败: {mt5.last_error()}\n"
            "请确认 MT5 终端已打开并登录(脚本读取的是正在运行的终端实例)。"
        )

    info = mt5.account_info()
    print(f"已连接账户: login={info.login} server={info.server} currency={info.currency}")

    f = datetime.strptime(args.from_date, "%Y-%m-%d")
    t = datetime.strptime(args.to_date, "%Y-%m-%d")

    deals = mt5.history_deals_get(f, t)
    orders = mt5.history_orders_get(f, t)

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
    if args.group and deals:
        trades = {}
        for d in drows:
            pid = d.get("position_id")
            if pid is None:
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
            tr["result"] = "WIN" if tr["net_profit"] > 0 else "LOSS"
        write_csv(f"{args.out}_trades.csv", trows)
        print(f"逐笔交易: {len(trows)} 笔 -> {args.out}_trades.csv")

    # 基础统计(基于成交盈亏, 粗算)
    if deals:
        profits = [d.get("profit", 0) or 0 for d in drows]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        gross_w = sum(wins)
        gross_l = sum(losses)
        summary = {
            "account": info.login,
            "server": info.server,
            "range": [args.from_date, args.to_date],
            "deal_count": len(drows),
            "gross_profit": round(gross_w, 2),
            "gross_loss": round(gross_l, 2),
            "net_profit": round(gross_w + gross_l, 2),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": round(len(wins) / len(drows) * 100, 2) if drows else 0,
            "profit_factor": round(gross_w / abs(gross_l), 2) if gross_l else None,
            "avg_win": round(gross_w / len(wins), 2) if wins else 0,
            "avg_loss": round(gross_l / len(losses), 2) if losses else 0,
            "expectancy": round((gross_w + gross_l) / len(drows), 2) if drows else 0,
        }
        with open(f"{args.out}_summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print("摘要 ->", f"{args.out}_summary.json")

    mt5.shutdown()
    print("完成。把生成的 *_deals.csv / *_trades.csv 丢进项目, 我直接做全维度分析。")


if __name__ == "__main__":
    main()
