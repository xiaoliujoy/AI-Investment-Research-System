# -*- coding: utf-8 -*-
"""
回测引擎 (Backtest Engine)
===========================================================
目标：验证 brain 决策逻辑的历史有效性。

两种模式：
  1. 历史模拟 (historical)：用 DB 中的 market_daily / sector_daily / stock_daily
     数据，对每个交易日计算简化版决策信号（市场宽度 + 板块资金 + 情绪），
     对比下一交易日实际市场涨跌，统计命中率。
  2. 实盘追踪 (track-record)：读取 output/archive/brain_report_YYYY-MM-DD.json
     保存的历史 brain 报告，对比实际市场表现。每日 run_daily 可自动归档。

用法：
  python backtest_engine.py                  # 历史模拟（默认60个交易日）
  python backtest_engine.py --days 120       # 指定天数
  python backtest_engine.py --track-record   # 实盘追踪模式
  python backtest_engine.py --save-snapshot  # 归档今日 brain 报告

输出：
  - 终端打印回测摘要（命中率 / 分决策统计 / 月度统计）
  - output/backtest_report.json（完整结果）
  - output/backtest_report.html（可视化 HTML）
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import datetime
import argparse
from collections import defaultdict
from typing import Any

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "output")
ARCHIVE_DIR = os.path.join(OUT, "archive")

# 上证指数代码（用于计算市场日收益率）
SH_INDEX_CODE = "000001"
SZ_INDEX_CODE = "399001"


def _get_db():
    from database.models import get_db
    return get_db()


def _get_trading_dates(days: int) -> list[str]:
    """从 market_daily 取最近 N 个交易日（降序）。"""
    conn = _get_db()
    rows = conn.execute(
        "SELECT date FROM market_daily ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    conn.close()
    return [r["date"] for r in rows]


def _get_market_breadth(date: str) -> dict | None:
    """市场宽度：上涨/下跌/涨停/跌停/情绪。"""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM market_daily WHERE date = ?", (date,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    up = row["up_count"] or 0
    down = row["down_count"] or 0
    total = up + down + (row["flat_count"] or 0)
    breadth = up / total if total > 0 else 0.5
    return {
        "date": date,
        "breadth": round(breadth, 4),
        "up": up,
        "down": down,
        "limit_up": row["limit_up_count"] or 0,
        "limit_down": row["limit_down_count"] or 0,
        "seal_rate": row["seal_rate"],
        "break_rate": row["break_rate"],
        "emotion_score": row["emotion_score"],
        "stage": row["stage"] or "",
        "total_amount": row["total_amount"],
        "avg_5d": row["avg_5d_amount"],
        "avg_20d": row["avg_20d_amount"],
    }


def _get_sector_signals(date: str) -> dict | None:
    """板块资金信号：前5净流入 + 前5净流出。"""
    conn = _get_db()
    rows = conn.execute(
        """SELECT sector_name, net_amount, change_pct, sector_score, tier
           FROM sector_daily WHERE date = ?
           ORDER BY net_amount DESC""", (date,)
    ).fetchall()
    conn.close()
    if not rows:
        return None
    top5 = rows[:5]
    bottom5 = rows[-5:] if len(rows) >= 10 else rows[-5:]
    top_net = sum(r["net_amount"] or 0 for r in top5)
    bottom_net = sum(r["net_amount"] or 0 for r in bottom5)
    return {
        "top5_names": [r["sector_name"] for r in top5],
        "top5_net": round(top_net, 2),
        "bottom5_net": round(bottom_net, 2),
        "total_sectors": len(rows),
        "positive_count": sum(1 for r in rows if (r["net_amount"] or 0) > 0),
        "negative_count": sum(1 for r in rows if (r["net_amount"] or 0) < 0),
    }


def _get_next_day_return(date: str) -> float | None:
    """下一交易日的市场平均涨跌幅（用全市场等权涨跌中位数）。
    若 market_daily 有下一日数据则用 up/down 算宽度变化作为代理。"""
    conn = _get_db()
    # 方案1：从 stock_daily 算等权平均
    row = conn.execute(
        """SELECT AVG(change_pct) as avg_ret, COUNT(*) as n
           FROM stock_daily WHERE date = ?
           AND change_pct IS NOT NULL""", (date,)
    ).fetchone()
    conn.close()
    if row and row["n"] and row["n"] > 100:
        return round(row["avg_ret"], 4)
    return None


def _simplified_decision(breadth: dict, sectors: dict) -> dict:
    """简化版决策逻辑（模拟 brain 投票）。

    信号：
      - 市场宽度 > 55% → bull +1
      - 市场宽度 < 45% → bear +1
      - 板块净流入sector > 流出sector → bull +1
      - 板块净流入sector < 流出sector → bear +1
      - 情绪 stage 含"活跃/亢奋/强" → bull +1
      - 情绪 stage 含"冰点/退潮/弱" → bear +1
      - 涨停 > 跌停 × 2 → bull +1
      - 跌停 > 涨停 × 2 → bear +1
      - 成交额 > 5日均量 → bull +1（量能放大）
      - 成交额 < 5日均量 × 0.8 → bear +1（缩量）
    """
    bull = 0
    bear = 0
    reasons = []

    # 市场宽度
    b = breadth["breadth"]
    if b > 0.55:
        bull += 1
        reasons.append(f"市场宽度{b:.0%}偏强")
    elif b < 0.45:
        bear += 1
        reasons.append(f"市场宽度{b:.0%}偏弱")

    # 板块资金
    if sectors:
        pos = sectors["positive_count"]
        neg = sectors["negative_count"]
        if pos > neg * 1.2:
            bull += 1
            reasons.append(f"板块净流入{pos}个>流出{neg}个")
        elif neg > pos * 1.2:
            bear += 1
            reasons.append(f"板块净流出{neg}个>流入{pos}个")

    # 情绪
    stage = breadth.get("stage", "")
    if any(k in stage for k in ["活跃", "亢奋", "强", "普涨"]):
        bull += 1
        reasons.append(f"情绪{stage}")
    elif any(k in stage for k in ["冰点", "退潮", "弱", "恐慌"]):
        bear += 1
        reasons.append(f"情绪{stage}")

    # 涨跌停
    lu = breadth.get("limit_up", 0)
    ld = breadth.get("limit_down", 0)
    if lu > 0 and ld > 0:
        if lu > ld * 2:
            bull += 1
            reasons.append(f"涨停{lu}>>跌停{ld}")
        elif ld > lu * 2:
            bear += 1
            reasons.append(f"跌停{ld}>>涨停{lu}")

    # 量能
    ta = breadth.get("total_amount")
    avg5 = breadth.get("avg_5d")
    if ta and avg5 and avg5 > 0:
        if ta > avg5:
            bull += 1
            reasons.append("成交额放量")
        elif ta < avg5 * 0.8:
            bear += 1
            reasons.append("成交额缩量")

    # 决策
    if bear >= 3 and bear > bull:
        can_buy = "NO"
    elif bull >= 3 and bull > bear:
        can_buy = "YES"
    else:
        can_buy = "CAUTION"

    return {
        "can_buy": can_buy,
        "bull": bull,
        "bear": bear,
        "reasons": reasons,
    }


def run_historical_backtest(days: int = 60) -> dict:
    """历史模拟回测。"""
    dates = _get_trading_dates(days + 5)  # 多取几天，防止末尾没有 next-day
    if len(dates) < 5:
        return {"error": "历史数据不足"}

    results = []
    for i in range(len(dates) - 1):
        date = dates[i]
        next_date = dates[i + 1] if i + 1 < len(dates) else None

        breadth = _get_market_breadth(date)
        if not breadth:
            continue
        sectors = _get_sector_signals(date)
        if not sectors:
            continue

        decision = _simplified_decision(breadth, sectors)

        # 下一日市场表现
        next_ret = _get_next_day_return(next_date) if next_date else None

        results.append({
            "date": date,
            "next_date": next_date,
            "breadth": breadth["breadth"],
            "stage": breadth["stage"],
            "top5_net": sectors["top5_net"],
            "decision": decision["can_buy"],
            "bull": decision["bull"],
            "bear": decision["bear"],
            "reasons": decision["reasons"],
            "next_ret": next_ret,
        })

    # 统计
    stats = _compute_stats(results)
    return {"results": results, "stats": stats, "mode": "historical", "days": days}


def _compute_stats(results: list[dict]) -> dict:
    """计算回测统计。"""
    valid = [r for r in results if r["next_ret"] is not None]
    if not valid:
        return {"error": "无有效下一日收益数据"}

    # 总体命中率：YES/CAUTION 时市场上涨算对，NO 时市场下跌算对
    hits = 0
    for r in valid:
        if r["decision"] in ("YES", "CAUTION") and r["next_ret"] > 0:
            hits += 1
        elif r["decision"] == "NO" and r["next_ret"] < 0:
            hits += 1

    hit_rate = hits / len(valid) if valid else 0

    # 分决策统计
    by_decision = defaultdict(list)
    for r in valid:
        by_decision[r["decision"]].append(r["next_ret"])

    decision_stats = {}
    for dec, rets in by_decision.items():
        wins = sum(1 for r in rets if r > 0)
        decision_stats[dec] = {
            "count": len(rets),
            "win_count": wins,
            "win_rate": round(wins / len(rets), 4) if rets else 0,
            "avg_return": round(sum(rets) / len(rets), 4) if rets else 0,
            "max_return": round(max(rets), 4) if rets else 0,
            "min_return": round(min(rets), 4) if rets else 0,
        }

    # 月度统计
    by_month = defaultdict(list)
    for r in valid:
        month = r["date"][:7]
        by_month[month].append(r["next_ret"])

    monthly_stats = {}
    for month, rets in sorted(by_month.items()):
        monthly_stats[month] = {
            "trading_days": len(rets),
            "avg_return": round(sum(rets) / len(rets), 4),
            "total_return": round(sum(rets), 4),
        }

    return {
        "total_days": len(valid),
        "hit_rate": round(hit_rate, 4),
        "decision_breakdown": decision_stats,
        "monthly": monthly_stats,
    }


def run_track_record() -> dict:
    """实盘追踪模式：读取归档的 brain 报告。"""
    if not os.path.exists(ARCHIVE_DIR):
        return {"error": "归档目录不存在，请先运行 --save-snapshot 归档今日报告"}

    snapshots = sorted([f for f in os.listdir(ARCHIVE_DIR) if f.startswith("brain_report_")])
    if not snapshots:
        return {"error": "无归档报告"}

    results = []
    for fname in snapshots:
        path = os.path.join(ARCHIVE_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            report = json.load(f)

        date = report.get("trade_date", fname.replace("brain_report_", "").replace(".json", ""))
        can_buy = report.get("decision", {}).get("can_buy", "UNKNOWN")
        confidence = report.get("confidence", {}).get("overall", 0)

        # 下一日市场表现
        dates = _get_trading_dates(5)
        next_date = None
        for d in dates:
            if d > date:
                next_date = d
                break
        next_ret = _get_next_day_return(next_date) if next_date else None

        results.append({
            "date": date,
            "can_buy": can_buy,
            "confidence": confidence,
            "next_date": next_date,
            "next_ret": next_ret,
        })

    stats = _compute_stats_track(results)
    return {"results": results, "stats": stats, "mode": "track-record", "snapshots": len(snapshots)}


def _compute_stats_track(results: list[dict]) -> dict:
    valid = [r for r in results if r["next_ret"] is not None]
    if not valid:
        return {"error": "无有效下一日收益数据", "total_snapshots": len(results)}

    hits = 0
    for r in valid:
        if r["can_buy"] in ("YES", "CAUTION") and r["next_ret"] > 0:
            hits += 1
        elif r["can_buy"] == "NO" and r["next_ret"] < 0:
            hits += 1

    return {
        "total_snapshots": len(results),
        "valid_days": len(valid),
        "hit_rate": round(hits / len(valid), 4) if valid else 0,
    }


def save_snapshot():
    """归档今日 brain 报告（带日期戳）。"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    src = os.path.join(OUT, "brain_report.json")
    if not os.path.exists(src):
        print("brain_report.json 不存在，请先运行 run_daily.py")
        return False

    with open(src, "r", encoding="utf-8") as f:
        report = json.load(f)
    trade_date = report.get("trade_date", datetime.date.today().isoformat())

    dst = os.path.join(ARCHIVE_DIR, f"brain_report_{trade_date}.json")
    if os.path.exists(dst):
        print(f"已存在 {dst}，跳过")
        return True

    shutil.copy2(src, dst)
    print(f"已归档 -> {dst}")
    return True


def render_html(data: dict) -> str:
    """生成回测报告 HTML。"""
    stats = data.get("stats", {})
    results = data.get("results", [])
    mode = data.get("mode", "historical")

    rows_html = ""
    for r in results[-30:]:  # 最近30天
        ret = r.get("next_ret")
        ret_str = f"{ret:+.2f}%" if ret is not None else "—"
        ret_color = "color:#E24B4A" if ret and ret > 0 else "color:#1D9E75" if ret and ret < 0 else "color:#888"
        dec = r.get("decision") or r.get("can_buy", "?")
        dec_color = {"YES": "#1D9E75", "NO": "#E24B4A", "CAUTION": "#BA7517"}.get(dec, "#888")
        rows_html += f"""
        <tr>
          <td style="padding:6px 12px;border-bottom:1px solid #eee">{r['date']}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee;color:{dec_color};font-weight:600">{dec}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee">{r.get('bull','—')}/{r.get('bear','—')}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee">{r.get('breadth','—')}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee">{r.get('stage','—')}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee;{ret_color}">{ret_str}</td>
        </tr>"""

    decision_html = ""
    for dec, s in stats.get("decision_breakdown", {}).items():
        dec_color = {"YES": "#1D9E75", "NO": "#E24B4A", "CAUTION": "#BA7517"}.get(dec, "#888")
        decision_html += f"""
        <div style="display:inline-block;margin-right:16px;padding:12px;border-radius:8px;background:#f8f8f8">
          <div style="font-size:18px;font-weight:700;color:{dec_color}">{dec}</div>
          <div style="font-size:12px;color:#888">{s['count']}天 · 胜率{s['win_rate']:.0%} · 均收{s['avg_return']:+.2f}%</div>
        </div>"""

    hit_rate = stats.get("hit_rate", 0)
    hit_color = "#1D9E75" if hit_rate > 0.55 else "#BA7517" if hit_rate > 0.45 else "#E24B4A"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>回测报告 - {data.get('days','')}天</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:900px;margin:20px auto;padding:20px;color:#333}}
h1{{font-size:20px}}h2{{font-size:16px;margin-top:24px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 12px;border-bottom:2px solid #ddd;color:#666;font-weight:600}}
</style></head><body>
<h1>回测报告 ({mode})</h1>
<div style="margin:16px 0">
  <span style="font-size:28px;font-weight:700;color:{hit_color}">{hit_rate:.0%}</span>
  <span style="font-size:14px;color:#888;margin-left:8px">总体命中率 ({stats.get('total_days',0)}天)</span>
</div>
<div style="margin:16px 0">{decision_html}</div>
<h2>逐日明细（最近30天）</h2>
<table>
  <thead><tr>
    <th>日期</th><th>决策</th><th>多/空</th><th>宽度</th><th>情绪</th><th>次日收益</th>
  </tr></thead>
  <tbody>{rows_html}
  </tbody>
</table>
<p style="margin-top:16px;font-size:11px;color:#999">
  简化版决策逻辑，非完整 brain 推理链。仅用于验证方向性判断的有效性。
  买卖/图形由你人工定。
</p>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="回测引擎")
    ap.add_argument("--days", type=int, default=60, help="历史模拟天数（默认60）")
    ap.add_argument("--track-record", action="store_true", help="实盘追踪模式")
    ap.add_argument("--save-snapshot", action="store_true", help="归档今日 brain 报告")
    args = ap.parse_args()

    if args.save_snapshot:
        save_snapshot()
        return

    if args.track_record:
        print("=== 实盘追踪模式 ===")
        data = run_track_record()
    else:
        print(f"=== 历史模拟回测 ({args.days} 天) ===")
        data = run_historical_backtest(args.days)

    if "error" in data:
        print(f"错误: {data['error']}")
        return

    stats = data.get("stats", {})
    if "error" in stats:
        print(f"统计错误: {stats['error']}")
    else:
        print(f"\n总体命中率: {stats.get('hit_rate', 0):.1%} ({stats.get('total_days', 0)} 天)")
        if "decision_breakdown" in stats:
            print("\n分决策统计:")
            for dec, s in stats["decision_breakdown"].items():
                print(f"  {dec}: {s['count']}天 · 胜率{s['win_rate']:.1%} · 均收{s['avg_return']:+.2f}% · 范围[{s['min_return']:+.2f}%, {s['max_return']:+.2f}%]")
        if "monthly" in stats:
            print("\n月度统计:")
            for month, s in stats["monthly"].items():
                print(f"  {month}: {s['trading_days']}天 · 均收{s['avg_return']:+.2f}% · 总收{s['total_return']:+.2f}%")

    # 保存结果
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "backtest_report.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    html = render_html(data)
    with open(os.path.join(OUT, "backtest_report.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n报告已保存: {os.path.join(OUT, 'backtest_report.json')}")
    print(f"HTML报告: {os.path.join(OUT, 'backtest_report.html')}")


if __name__ == "__main__":
    main()
