"""P1-C Round 2 · 北交所 327→0 反事实探针（READONLY, mode=ro）。

只查不改：统计 stock_info / stock_daily 中北交所代码（83/87/920 前缀）实际在场数量，
并扫描是否存在 exchange/board/market 列或 universe 表。
"""
import sqlite3, os

CANON = r"C:\Users\JOY\WorkBuddy\个人AI研投系统\backend\database\vibe_research.db"
uri = "file:" + CANON.replace("\\", "/") + "?mode=ro"
c = sqlite3.connect(uri, uri=True)
cur = c.cursor()


def q(sql, args=()):
    try:
        return cur.execute(sql, args).fetchall()
    except Exception as e:
        return f"ERR:{e}"


print("="*60)
print("stock_info 结构")
print(q("PRAGMA table_info(stock_info)"))
print("-"*60)
print("北交所代码在 stock_info（83/87/920 前缀，DISTINCT）")
for pre in ("83", "87", "920"):
    n = q(f"SELECT COUNT(DISTINCT code) FROM stock_info WHERE code LIKE '{pre}%'")
    print(f"  {pre}% : {n}")
tot_info = q("SELECT COUNT(DISTINCT code) FROM stock_info")
print(f"  stock_info DISTINCT code 总计: {tot_info}")
print("-"*60)
print("北交所代码在 stock_daily（DISTINCT，近全量）")
for pre in ("83", "87", "920"):
    n = q(f"SELECT COUNT(DISTINCT code) FROM stock_daily WHERE code LIKE '{pre}%'")
    print(f"  {pre}% : {n}")
tot_daily = q("SELECT COUNT(DISTINCT code) FROM stock_daily")
print(f"  stock_daily DISTINCT code 总计: {tot_daily}")
print("-"*60)
# 8 开头（含北交及其他）整体
n8 = q("SELECT COUNT(DISTINCT code) FROM stock_daily WHERE code LIKE '8%'")
print(f"  stock_daily '8%' DISTINCT: {n8}")
print("-"*60)
print("是否存在 exchange/board/market 列 或 universe 表")
tabs = [r[0] for r in q("SELECT name FROM sqlite_master WHERE type='table'") ]
print("  含 'universe' 的表:", [t for t in tabs if 'universe' in t.lower()])
for t in ("stock_info", "stock_daily"):
    cols = [d[1] for d in cur.execute(f"PRAGMA table_info('{t}')").fetchall()]
    hits = [x for x in cols if x.lower() in ("exchange", "board", "market", "sec_type", "security_type", "type")]
    print(f"  {t} 相关列: {hits}")
c.close()
