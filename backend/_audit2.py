import sqlite3, re, os, json

DB = "database/vibe_research.db"
con = sqlite3.connect(DB)

print("=== A. stock_info 脏名残留 27 个 ===")
rows = con.execute("SELECT code,name FROM stock_info WHERE name LIKE '% %' OR name LIKE '%A%'").fetchall()
for code, name in rows:
    print("   ", code, repr(name))
print("   共", len(rows), "个")

print("\n=== B. brain_report.json / decision_tree.json 是否影响 live memo ===")
# 看 produce() 是否读取这些文件；grep memo 生成链路
print("   brain_report.json trade_date:", json.load(open("output/brain_report.json", encoding="utf-8")).get("trade_date"))
print("   decision_tree.json trade_date:", json.load(open("output/decision_tree.json", encoding="utf-8")).get("trade_date"))
# memo 是否引用它们
import subprocess
# 简单判断 os2_report 是否 import 这两个 json
p = open("notify/os2_report.py", encoding="utf-8").read()
print("   os2_report 引用 brain_report.json:", "brain_report.json" in p)
print("   os2_report 引用 decision_tree.json:", "decision_tree.json" in p)

print("\n=== C. trade_journal 5 条 signal 来源 ===")
for r in con.execute("SELECT id,trade_date,code,name,sector,action,rec_type,ic_score,candidate_sectors,created_at FROM trade_journal ORDER BY id"):
    print("   ", r)

con.close()
PYEOF = None
