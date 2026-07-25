import sqlite3, os, json

DB = "database/vibe_research.db"
con = sqlite3.connect(DB)

def maxdate(t, c="date"):
    try:
        return con.execute("SELECT MAX(%s) FROM %s" % (c, t)).fetchone()[0]
    except Exception as e:
        return "ERR:%s" % e

def cnt(t, where=""):
    try:
        sql = "SELECT COUNT(*) FROM %s %s" % (t, where)
        return con.execute(sql).fetchone()[0]
    except Exception as e:
        return "ERR:%s" % e

TODAY = "2026-07-20"
w_today = "WHERE date='%s'" % TODAY

print("=== 一、核心行情与资金 ===")
print("  stock_daily        最新交易日 :", maxdate('stock_daily'), " | %s行数:" % TODAY, cnt('stock_daily', w_today), " | 总:", cnt('stock_daily'))
print("  stock_flow_daily    最新日期   :", maxdate('stock_flow_daily'), " | %s行数:" % TODAY, cnt('stock_flow_daily', w_today), " | 总:", cnt('stock_flow_daily'))

print("\n=== 二、全球/跨资产数据 ===")
print("  global_history      最新日期   :", maxdate('global_history'), " | %s行数:" % TODAY, cnt('global_history', w_today), " | 总:", cnt('global_history'))

print("\n=== 三、基础字典 ===")
print("  stock_info          总行数     :", cnt('stock_info'), " | 带空格/全角A残留:", cnt('stock_info', "WHERE name LIKE '% %' OR name LIKE '%A%'"))
print("  industry_map        总行数     :", cnt('industry_map'))
print("  sector_crosswalk    总行数     :", cnt('sector_crosswalk'))

print("\n=== 四、资金评分表(Phase1) ===")
print("  stock_capital_score 最新日期   :", maxdate('stock_capital_score'), " | %s行数:" % TODAY, cnt('stock_capital_score', w_today), " | 总:", cnt('stock_capital_score'))

print("\n=== 五、日志/学习表 ===")
print("  trade_journal       总行数     :", cnt('trade_journal'))
print("  trade_journal(signal):", cnt('trade_journal', "WHERE rec_type='signal'"))

print("\n=== 六、JSON 产物日期 ===")
def jdate(p, keys=("date","trade_date","article_date","as_of")):
    if not os.path.exists(p):
        return "文件缺失"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return "解析失败:%s" % e
    for k in keys:
        if k in d and d[k]:
            return "%s=%s" % (k, d[k])
    return "无显式日期字段"

for f in ["output/sector_mainline.json","output/panqian_feed.json","output/brain_report.json","output/decision_tree.json","output/collect.log.json","output/run_daily.log.json"]:
    print("  %s: %s" % (f, jdate(f)))

print("\n=== 七、collect.log 各步时间 ===")
if os.path.exists("output/collect.log.json"):
    log = json.load(open("output/collect.log.json", encoding="utf-8"))
    print("  finished_at:", log.get("finished_at"), "| overall_ok:", log.get("overall_ok"))
    for s in log.get("steps", []):
        print("    [%s] %s rc=%s %ss" % ('OK' if s.get('ok') else 'FAIL', s.get('step'), s.get('returncode'), s.get('secs')))

con.close()
