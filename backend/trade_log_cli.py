"""交易日志录入 CLI —— ⑧ 学习进化闭环入口（Phase 2：判断/执行分离）。

用法：
  python trade_log_cli.py add -i                       # 交互式录入一笔
  python trade_log_cli.py add --date 2026-07-10 --code 300750 --name 宁德时代 \
      --sector 新能源 --action 买 --reason "主线板块+平台突破" \
      --plan-stop "破20日线" --result 胜 --pnl 5.2 --note "缩量回踩"
  python trade_log_cli.py reconcile                     # 回放：判断命中率 vs 执行纪律
  python trade_log_cli.py stats                         # 月度模式 + 判断/执行统计
  python trade_log_cli.py list -n 20                    # 最近记录

说明：
  · produce() 每日自动把系统判断写入 trade_journal（rec_type='signal'）。
  · 你手动录入的成交为 rec_type='trade'，add 会按 (code, date) 自动关联最近的系统信号。
  · reconcile 用「信号日→次日」收益率判定判断对错，并统计你是否跟单（执行纪律）。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import narrative_layers as ne


def _resolve_signal_id(date, code):
    """按 (code, date) 关联最近的系统信号（rec_type='signal'）。"""
    try:
        c = sqlite3.connect(ne.DB)
        row = c.execute(
            "SELECT id FROM trade_journal WHERE rec_type='signal' AND code=? "
            "AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
            (str(code), date)).fetchone()
        c.close()
        return row[0] if row else None
    except Exception:
        return None


def cmd_add(args):
    if args.interactive or not (args.code or args.date):
        ne.interactive_add()
        return
    signal_id = _resolve_signal_id(args.date, args.code)
    ne.add_journal(args.date, args.code, args.action,
                   sector=args.sector or "", name=args.name or "",
                   reason=args.reason or "", plan_stop=args.plan_stop or "",
                   result=args.result or "", pnl=args.pnl, note=args.note or "",
                   rec_type="trade", signal_id=signal_id)
    suffix = f"（已关联系统信号 #{signal_id}）" if signal_id else "（无关联系统信号）"
    print(f"✅ 已记录 {args.date} {args.code} {args.name} ({args.action}) {suffix}")


def cmd_stats(args):
    r = ne.monthly_pattern()
    print("== ⑧ 学习进化（判断/执行分离）==")
    print(r.get("read"))
    j = r.get("judgment") or {}
    e = r.get("execution") or {}
    if j.get("rate") is not None:
        print(f"\n判断命中率：{j['rate']}%（对{j['right']}/错{j['wrong']}，样本{j['n']}；"
              f"na={j.get('na',0)}，待次日回放{j.get('pending',0)}）")
    else:
        print(f"\n判断回放：系统信号 {r.get('n_signal',0)} 条，样本积累中"
              f"（{j.get('pending',0)} 条待次日数据）")
    if e.get("capture_rate") is not None:
        print(f"执行跟单率：{e['capture_rate']}%（判断对且跟单 {e.get('executed',0)} 条）")
        if e.get("discipline_error"):
            print(f"执行纪律误差：{e['discipline_error']} 次"
                  f"（错过利润 {e.get('missed_profit',0)} / 逆向跟单 {e.get('acted_on_wrong',0)}）")
    else:
        print("执行跟单率：尚未录入实际交易（执行纪律待积累）")
    if r.get("by_month"):
        print("\n月度复盘：")
        for m, v in r["by_month"].items():
            print(f"  {m}: {v['n']}笔 胜率{v['win_rate']}% 累计{v['pnl_sum']}% 均{v['pnl_avg']}%")
    if r.get("by_sector"):
        print("\n板块胜率榜（反哺选股偏好）：")
        for s, v in sorted(r["by_sector"].items(),
                           key=lambda kv: (kv[1]["win_rate"] or 0), reverse=True):
            print(f"  {s}: {v['n']}笔 胜率{v['win_rate']}% 均盈亏{v['pnl_avg']}%")
    if r.get("insights"):
        print("\n系统自动迭代建议：")
        for i in r["insights"]:
            print("  -", i)


def cmd_reconcile(args):
    rec = ne.reconcile_journal()
    if not rec or not rec.get("ok"):
        print("回放失败：", rec.get("error") if rec else "未知")
        return
    j, e = rec["judgment"], rec["execution"]
    print("== ⑧ 回放 trade_journal（判断/执行分离）==")
    if j.get("rate") is not None:
        print(f"判断命中率：{j['rate']}%（对{j['right']}/错{j['wrong']}，样本{j['n']}）")
    else:
        print(f"判断回放：{j.get('pending',0)} 条待次日数据，暂无法判定命中率")
    if e.get("capture_rate") is not None:
        print(f"执行跟单率：{e['capture_rate']}%（判断对且跟单 {e.get('executed',0)} 条）")
        print(f"执行纪律误差：{e['discipline_error']} 次"
              f"（错过利润 {e.get('missed_profit',0)} / 逆向跟单 {e.get('acted_on_wrong',0)}）")
    else:
        print("执行跟单率：暂无（未录入实际交易）")


def cmd_list(args):
    c = sqlite3.connect(ne.DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM trade_journal ORDER BY trade_date DESC LIMIT ?",
                     (args.n,)).fetchall()
    c.close()
    if not rows:
        print("（暂无记录）")
        return
    for r in rows:
        print(f"{r['trade_date']} {r['code']} {r['name']} [{r['action']}] {r['sector']} "
              f"-> {r['result']} {r['pnl']}% | {r['reason']}")


def main():
    p = argparse.ArgumentParser(description="交易日志录入（⑧ 学习进化闭环）")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="录入一笔交易")
    a.add_argument("--date", help="交易日 YYYY-MM-DD")
    a.add_argument("--code", help="股票代码")
    a.add_argument("--name", help="股票名称")
    a.add_argument("--sector", help="所属板块")
    a.add_argument("--action", default="买", help="买/卖/观察")
    a.add_argument("--reason", help="买入逻辑")
    a.add_argument("--plan-stop", dest="plan_stop", help="计划止损")
    a.add_argument("--result", help="胜/负/持有")
    a.add_argument("--pnl", type=float, help="盈亏%(持有可空)")
    a.add_argument("--note", help="备注")
    a.add_argument("-i", "--interactive", action="store_true", help="交互式录入")

    sub.add_parser("stats", help="月度模式 + 判断/执行统计")
    sub.add_parser("reconcile", help="回放：判断命中率 vs 执行纪律")
    l = sub.add_parser("list", help="列出最近记录")
    l.add_argument("-n", type=int, default=20)

    args = p.parse_args()
    if args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "stats":
        cmd_stats(args)
    elif args.cmd == "reconcile":
        cmd_reconcile(args)
    elif args.cmd == "list":
        cmd_list(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
