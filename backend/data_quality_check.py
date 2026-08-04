# -*- coding: utf-8 -*-
"""
data_quality_check —— 每日数据质量自检（Research OS 基础设施，只读诊断）

目的（呼应 Trading OS Evolution Protocol v1.0）：
  未来系统失败时，第一时间区分「判断错」还是「输入错」。
  本脚本每天记录各感知器模块的数据就绪状态，不产出任何评分/信号。

检查模块：
  market_daily     市场宽度/情绪（客观字段）
  sector_daily     板块序列 + 真实资金流(net_amount)覆盖
  limit_up_daily   涨停生态
  stock_flow_daily 个股真实资金流（识别复制快照/占位值）
  global_history   全球/商品（如存在）
  stock_daily      个股价格（基础层）

输出：
  1) 控制台打印 OK/缺/异常 状态表
  2) JSON 落盘 backend/output/data_quality_<refdate>.json
  3) upsert 进 data_quality_daily 表（每日留痕，可追溯）

用法：
  python data_quality_check.py            # 检查最新交易日
  python data_quality_check.py --date 2026-07-31
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

DB = str(Path(__file__).parent / "database" / "vibe_research.db")
OUT = Path(__file__).parent / "output"
FLOW_REAL_START = "2026-07-20"  # stock_flow_daily 真实逐日资金流起点（早于该日为复制快照，已诚实置 NULL）


def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def table_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def check_stock_flow(cur):
    """个股真实资金流：真实覆盖天数 + 早期伪数据是否已清除。"""
    if not table_exists(cur, "stock_flow_daily"):
        return "缺", "表不存在"
    cur.execute("SELECT MAX(date) FROM stock_flow_daily")
    latest = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT date) FROM stock_flow_daily WHERE main_net_buy IS NOT NULL")
    real_days = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM stock_flow_daily WHERE date < ? AND main_net_buy IS NOT NULL", (FLOW_REAL_START,))
    leak = cur.fetchone()[0]
    if leak and leak > 0:
        return "异常", f"最新={latest} 真实天数={real_days} 但早期仍有{leak}行伪数据未清"
    if real_days == 0:
        return "缺", f"最新={latest} 无任何真实资金流"
    return "OK", f"最新={latest} 真实逐日覆盖={real_days}天(≥{FLOW_REAL_START}) 早期伪数据已清0"


def check_sector(cur):
    """板块序列 + 真实资金流覆盖。"""
    if not table_exists(cur, "sector_daily"):
        return "缺", "表不存在"
    cur.execute("SELECT MAX(date) FROM sector_daily")
    latest = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT date) FROM sector_daily")
    days = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT date) FROM sector_daily WHERE net_amount IS NOT NULL")
    real_flow_days = cur.fetchone()[0]
    if days == 0:
        return "缺", "无任何板块序列"
    flag = "" if real_flow_days > 0 else " ⚠无真实资金流"
    return "OK", f"最新={latest} 序列天数={days} 真实资金流天数={real_flow_days}{flag}"


def check_simple(cur, table, label):
    if not table_exists(cur, table):
        return "缺", "表不存在"
    cur.execute(f"SELECT MAX(date), COUNT(DISTINCT date) FROM {table}")
    latest, days = cur.fetchone()
    if days == 0:
        return "缺", "无数据"
    return "OK", f"最新={latest} 覆盖天数={days}"


def check_global(cur):
    """全球/商品：优先 commodity_history，其次任何 global* 表。"""
    candidates = ["commodity_history", "global_history", "global_asset_history"]
    found = [t for t in candidates if table_exists(cur, t)]
    if not found:
        # 探测是否有任何含 global/commodity 的表
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%global%' OR name LIKE '%commodity%')")
        found = [r[0] for r in cur.fetchall()]
    if not found:
        return "N/A", "无全球/商品表（非必需）"
    t = found[0]
    cur.execute(f"SELECT MAX(date), COUNT(DISTINCT date) FROM {t}")
    latest, days = cur.fetchone()
    return "OK", f"表={t} 最新={latest} 天数={days}"


def main():
    ap = argparse.ArgumentParser(description="每日数据质量自检")
    ap.add_argument("--date", help="参考交易日（默认取 stock_daily 最新日）")
    args = ap.parse_args()

    con = connect()
    cur = con.cursor()
    # 参考交易日
    if args.date:
        ref = args.date
    else:
        cur.execute("SELECT MAX(date) FROM stock_daily")
        ref = cur.fetchone()[0] or date.today().isoformat()

    modules = [
        ("stock_daily", "个股价格(基础层)", lambda: check_simple(cur, "stock_daily", "个股价格")),
        ("market_daily", "市场宽度/情绪", lambda: check_simple(cur, "market_daily", "市场")),
        ("sector_daily", "板块序列/资金流", lambda: check_sector(cur)),
        ("limit_up_daily", "涨停生态", lambda: check_simple(cur, "limit_up_daily", "涨停")),
        ("stock_flow_daily", "个股真实资金流", lambda: check_stock_flow(cur)),
        ("global/commodity", "全球/商品", lambda: check_global(cur)),
    ]

    report = {"ref_date": ref, "checked_at": datetime.now().isoformat(timespec="seconds"), "modules": []}
    ICON = {"OK": "✅", "缺": "⚠️", "异常": "❌", "N/A": "➖"}
    print(f"\n{'=' * 64}")
    print(f"  Trading OS Health Monitor   Date: {ref}")
    print(f"{'=' * 64}")
    for key, label, fn in modules:
        status, detail = fn()
        print(f"  {ICON.get(status, '·')} {label:<14} {status:<4} {detail}")
        report["modules"].append({"module": key, "label": label, "status": status, "detail": detail})

    # 落盘 JSON
    OUT.mkdir(exist_ok=True)
    jp = OUT / f"data_quality_{ref}.json"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # upsert 进 data_quality_daily（每日留痕）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS data_quality_daily (
        ref_date TEXT, module TEXT, status TEXT, detail TEXT, checked_at TEXT,
        PRIMARY KEY (ref_date, module)
    )""")
    for m in report["modules"]:
        cur.execute(
            "INSERT OR REPLACE INTO data_quality_daily (ref_date, module, status, detail, checked_at) VALUES (?,?,?,?,?)",
            (ref, m["module"], m["status"], m["detail"], report["checked_at"]),
        )
    con.commit()
    con.close()
    print(f"\n→ JSON: {jp}")
    print(f"→ 已留痕 data_quality_daily ({len(report['modules'])} 模块, ref={ref})")
    # 汇总
    bad = [m for m in report["modules"] if m["status"] in ("缺", "异常")]
    print("汇总:", "全部 OK" if not bad else f"{len(bad)} 个模块需关注: " + ",".join(m['label'] for m in bad))
    print("-" * 64)
    print("用途：未来判断失败时，先回答「判断错？还是输入数据错？」")
    print("      数据健康 → 查本表；异常 → 先修数据，再判研究。")


if __name__ == "__main__":
    main()
