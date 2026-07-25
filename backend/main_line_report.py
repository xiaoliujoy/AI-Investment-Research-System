"""Phase A-4/5: 主线板块排名 + 板块内候选个股（每日报告）。

输出 reports/main_line_YYYY-MM-DD.md：
  Step1 主线板块（净流入 + 成交额 两个维度并重）:
    ① 当日板块资金净流入 Top10
    ② 近5日累计净流入 Top5
    ③ 成交额持续放大 + 赚钱效应 综合主线评分（供你选 1~3 个）
  Step2 主线板块内候选个股（系统只圈候选+给数据/图形支撑，硬过滤由你做）:
    - 列出板块内个股，附 ma20/ma60/量比/涨跌幅/突破信号/市值/主力净流入
    - 量比从大到小排序；标注「突破20日新高 / 20MA>60MA / 量比放大」

用法:
  python main_line_report.py                 # 用最新完整交易日
  python main_line_report.py --enrich        # 额外用 akshare 补市值/主力净流入
  python main_line_report.py --date 2026-07-09
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import date as dmod
from pathlib import Path

DB = Path(__file__).parent / "database" / "vibe_research.db"
REPORT_DIR = Path(__file__).parent.parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)


def get_db():
    return sqlite3.connect(str(DB))


def latest_full_day(c):
    return c.execute(
        "SELECT date FROM stock_daily GROUP BY date ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]


def recent_days(c, day, n=5):
    return [r[0] for r in c.execute(
        "SELECT DISTINCT date FROM stock_daily WHERE date<=? ORDER BY date DESC LIMIT ?",
        (day, n),
    )]


def ranking_today_net(c, day, top=10):
    return c.execute(
        "SELECT sector_name, net_amount, amount, change_pct, up_count, down_count "
        "FROM sector_daily WHERE date=? ORDER BY net_amount DESC LIMIT ?",
        (day, top),
    ).fetchall()


def ranking_5d_net(c, days, top=5):
    return c.execute(
        "SELECT sector_name, SUM(net_amount) AS s, SUM(amount) AS a "
        "FROM sector_daily WHERE date IN (%s) GROUP BY sector_name "
        "ORDER BY s DESC LIMIT ?" % ",".join("?" * len(days)),
        (*days, top),
    ).fetchall()


def ranking_main_line(c, days):
    """综合主线评分: 近5日累计净流入 + 成交额趋势 + 赚钱效应。"""
    # 当日 & 5日前成交额对比（放大）
    day = days[0]
    prev = days[1:] if len(days) > 1 else days
    rows = c.execute(
        "SELECT sector_name, net_amount, amount, change_pct, up_count, down_count "
        "FROM sector_daily WHERE date=?", (day,)
    ).fetchall()
    # 5日累计净流入
    cum = dict((r[0], r[1]) for r in c.execute(
        "SELECT sector_name, SUM(net_amount) FROM sector_daily WHERE date IN (%s) GROUP BY sector_name"
        % ",".join("?" * len(days)), days))
    # 成交额趋势: 当日 vs 前几日均
    prev_amt = {}
    if prev:
        for r in c.execute(
            "SELECT sector_name, AVG(amount) FROM sector_daily WHERE date IN (%s) GROUP BY sector_name"
            % ",".join("?" * len(prev)), prev):
            prev_amt[r[0]] = r[1]
    out = []
    for sec, net, amt, chg, up, dwn in rows:
        cum_net = cum.get(sec, 0) or 0
        pa = prev_amt.get(sec, 0) or 0
        amt_growth = (amt / pa - 1) if pa > 0 else 0
        profit = (up - dwn) if (up is not None and dwn is not None) else 0
        # 综合分（归一化前用原始量级，仅排序用）: 5日净流入(亿) + 成交额放大% + 赚钱效应
        score = cum_net / 1e8 + amt_growth * 50 + profit
        out.append((sec, net, amt, chg, up, dwn, cum_net, amt_growth, profit, score))
    out.sort(key=lambda x: x[-1], reverse=True)
    return out


def candidates_in_sector(c, day, sector, enrich=None):
    rows = c.execute(
        """SELECT s.code, s.name, s.close, s.change_pct, s.ma20, s.ma60,
                  s.volume_ratio, s.high_20d, s.low_20d, s.is_new_high_20d,
                  s.market_cap, s.main_net_buy
           FROM stock_daily s
           JOIN sector_membership m ON s.code = m.code
           WHERE s.date=? AND m.sector_name=?
           ORDER BY s.volume_ratio DESC NULLS LAST""",
        (day, sector),
    ).fetchall()
    return rows


def fmt(v, kind="num"):
    if v is None:
        return "-"
    if kind == "pct":
        return f"{v:+.2f}%"
    if kind == "yi":
        return f"{v/1e8:.2f}亿"
    if kind == "wan":
        return f"{v/1e4:.1f}万"
    if kind == "float2":
        return f"{v:.2f}"
    return str(v)


def enrich_market(day):
    """用 akshare 东财实时快照补 市值/主力净流入（仅内存 dict）。"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        # 列含 代码, 总市值, 主力净流入-净额
        code_col = "代码"
        cap_col = next((x for x in df.columns if "总市值" in x), None)
        net_col = next((x for x in df.columns if "主力净流入" in x and "净额" in x), None)
        d = {}
        for _, r in df.iterrows():
            d[str(r[code_col]).strip()] = (r[cap_col] if cap_col else None,
                                           r[net_col] if net_col else None)
        return d
    except Exception as e:
        print(f"[enrich] 失败: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--enrich", action="store_true")
    args = ap.parse_args()

    c = get_db()
    day = args.date or latest_full_day(c)
    days = recent_days(c, day, 5)
    print(f"报告日: {day}  近5交易日: {days}")

    r1 = ranking_today_net(c, day, 10)
    r5 = ranking_5d_net(c, days, 5)
    rm = ranking_main_line(c, days)

    enrich = enrich_market(day) if args.enrich else None

    lines = []
    lines.append(f"# 主线板块与候选个股 · {day}\n")
    lines.append("> 维度说明：**资金净流入** 与 **成交额** 并重（均为东财/TDX真实数据）。\n")
    lines.append("> Step2 个股仅圈候选+给数据支撑，**硬过滤(20MA>60MA/市值/量比)由你人工看图完成**。\n")

    lines.append("## ① 当日板块资金净流入 Top10\n")
    lines.append("| 排名 | 板块 | 资金净流入 | 成交额 | 涨跌幅 | 涨/跌家数 |")
    lines.append("|---|---|---|---|---|---|")
    for i, (sec, net, amt, chg, up, dwn) in enumerate(r1, 1):
        lines.append(f"| {i} | {sec} | {fmt(net,'yi')} | {fmt(amt,'yi')} | {fmt(chg,'pct')} | {up}/{dwn} |")

    lines.append("\n## ② 近5日累计资金净流入 Top5\n")
    lines.append("| 排名 | 板块 | 5日累计净流入 | 5日累计成交额 |")
    lines.append("|---|---|---|---|")
    for i, (sec, s, a) in enumerate(r5, 1):
        lines.append(f"| {i} | {sec} | {fmt(s,'yi')} | {fmt(a,'yi')} |")

    lines.append("\n## ③ 综合主线评分（选 1~3 个板块的依据）\n")
    lines.append("评分 = 5日累计净流入 + 成交额放大%×50 + 赚钱效应(涨-跌家数)\n")
    lines.append("| 排名 | 板块 | 当日净流入 | 5日累计净流入 | 成交额较前期 | 赚钱效应 | 综合分 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, (sec, net, amt, chg, up, dwn, cum, gr, prof, score) in enumerate(rm[:15], 1):
        lines.append(f"| {i} | {sec} | {fmt(net,'yi')} | {fmt(cum,'yi')} | {gr*100:+.1f}% | {prof} | {score:.1f} |")

    # 选主线板块（top 8 供用户挑 1~3）
    main_sectors = [x[0] for x in rm[:8]]
    lines.append(f"\n## ④ 主线板块内候选个股（系统圈选，量比从大到小）\n")
    lines.append(f"> 候选主线板块（综合前8，你最终挑 1~3）：{', '.join(main_sectors)}\n")

    for sec in main_sectors:
        rows = candidates_in_sector(c, day, sec, enrich)
        if not rows:
            continue
        lines.append(f"\n### {sec}（{len(rows)} 只）\n")
        lines.append("| 代码 | 名称 | 收盘 | 涨跌幅 | 量比 | 20MA | 60MA | 20MA>60MA | 突破20日高 | 市值 | 主力净流入 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for code, name, close, chg, ma20, ma60, vr, h20, l20, inh, cap, mn in rows:
            ma_ok = "✅" if (ma20 and ma60 and ma20 > ma60) else ""
            brk = "🚀" if inh == 1 else ""
            capv = enrich.get(code, (cap, mn))[0] if enrich else cap
            mnv = enrich.get(code, (cap, mn))[1] if enrich else mn
            lines.append(
                f"| {code} | {name} | {fmt(close,'float2')} | {fmt(chg,'pct')} | {fmt(vr,'float2')} | "
                f"{fmt(ma20,'float2')} | {fmt(ma60,'float2')} | {ma_ok} | {brk} | {fmt(capv,'yi')} | {fmt(mnv,'yi')} |"
            )

    out = "\n".join(lines) + "\n"
    fn = REPORT_DIR / f"main_line_{day}.md"
    fn.write_text(out, encoding="utf-8")
    print(f"报告已生成: {fn}")
    # 终端摘要
    print("\n=== 当日净流入 Top5 ===")
    for sec, net, *_ in r1[:5]:
        print(f"  {sec}: {net/1e8:.2f}亿")
    print("=== 综合主线前5 ===")
    for sec, *_rest in rm[:5]:
        print(f"  {sec}")
    c.close()


if __name__ == "__main__":
    main()
