import threading, time, urllib.request, json, sqlite3, os, tempfile
import http.server as hs
import app as A

# 造一个临时"交易OS"库，模拟 trade_journal + trader_review
tmp = tempfile.mkdtemp()
fake_os = os.path.join(tmp, "vibe_research.db")
c = sqlite3.connect(fake_os)
c.execute("""CREATE TABLE trade_journal(id INTEGER PRIMARY KEY, trade_date TEXT, code TEXT, name TEXT,
  action TEXT, plan_stop TEXT, result TEXT, pnl REAL, judge_result TEXT, exec_result TEXT, note TEXT)""")
c.execute("""CREATE TABLE trader_review(id INTEGER PRIMARY KEY, trade_id INTEGER, rdate TEXT,
  decision_quality REAL, execution_quality REAL, emotion_management TEXT, judgment_correct TEXT,
  execution_correct TEXT, fear_trigger TEXT, improvement TEXT, deviation_reason TEXT, close_reason TEXT, created_at TEXT)""")
c.execute("INSERT INTO trade_journal(trade_date,code,name,action,plan_stop,result,pnl,judge_result,exec_result,note) "
          "VALUES('2026-08-13','300005','探路者','买','10.2','',NULL,'right','missed','测试')")
c.commit(); c.close()

A.TRADING_DB = fake_os  # 重定向到临时库，不动真实主库

srv = hs.HTTPServer(("127.0.0.1", 8781), A.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.6)

def post(p, b):
    r = urllib.request.Request("http://127.0.0.1:8781"+p, data=json.dumps(b).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(r).read())
def get(p):
    return json.loads(urllib.request.urlopen("http://127.0.0.1:8781"+p).read())

date = "2026-08-13"

# 1) 导入今日交易
imp = get("/api/import_trades?date="+date)
print("IMPORT ->", [(t["journal_id"], t["name"], t["judge_result"]) for t in imp])
assert len(imp) == 1 and imp[0]["journal_id"] == 1

# 2) 本地记录 trade_link + 晚间复盘
print("LINK ->", post("/api/link", {"date":date, "trade_link":"1"}))
print("EVENING ->", post("/api/evening", {"date":date, "evening_data":{"closest":"x","taken":"恐惧","error":"无",
    "review":{},"growth":{"learn":"a","good":"b","next":"c"}},
    "score_inner":4,"score_abundance":5,"score_discipline":4,"score_awareness":4,"score_joy":5,"belief_fulfillment":4}))
today = get("/api/today?date="+date)
print("TODAY trade_link ->", today.get("trade_link"), "| dss ->", today.get("daily_state_score"))

# 3) 复盘回写 trader_review
syn = post("/api/sync_review", {"date":date, "reviews":[{
    "trade_id":1, "belief":4, "emotion":"恐惧", "improvement":"先写计划",
    "deviation_reason":"无", "judgment_correct":"right", "execution_correct":"missed",
    "fear_trigger":"恐惧", "close_reason":"D"}]})
print("SYNC ->", syn)

# 4) 核对 trader_review 真实写入
oc = sqlite3.connect(fake_os); oc.row_factory=sqlite3.Row
row = oc.execute("SELECT * FROM trader_review").fetchone()
oc.close()
print("trader_review row ->", dict(row) if row else None)

srv.shutdown()
assert row and row["close_reason"]=="D" and row["trade_id"]==1, "回写校验失败"
print("INTEGRATION_OK")
