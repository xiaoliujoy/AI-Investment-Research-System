import threading, time, urllib.request, json
import http.server as hs
import app as A

srv = None
def start():
    global srv
    srv = hs.HTTPServer(("127.0.0.1", 8779), A.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.6)

def post(path, body):
    req = urllib.request.Request("http://127.0.0.1:8779"+path,
        data=json.dumps(body).encode(), headers={"Content-Type":"application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req).read())

def get(path):
    return json.loads(urllib.request.urlopen("http://127.0.0.1:8779"+path).read())

start()
date = "2026-08-13"
print("noon:", post("/api/noon", {"date":date,"state":"丰盛","note":"观想圆满"}))
print("trade:", post("/api/trade", {"date":date,"session":{"env":"震荡","dir":"多","has_chance":"是","accept_no":"能","plan":True,"chase":False,"early":False,"loss":False,"note":"按计划入场"}}))
print("evening:", post("/api/evening", {"date":date,
    "evening_data":{"closest":"开盘前冥想","taken":"尾盘追价","error":"无",
      "review":{"plan":True,"entry":True,"stop":True,"early":False,"miss":False},
      "growth":{"learn":"先写计划再开仓","good":"没有冲动交易","next":"明天所有交易先写计划"}},
    "score_inner":4,"score_abundance":5,"score_discipline":4,"score_awareness":4,"score_joy":5,"belief_fulfillment":4}))

t = get("/api/today?date="+date)
print("TODAY ->", {k:t.get(k) for k in ["noon_state","daily_state_score","presence","discipline_idx","joy_idx","belief_fulfillment"]})
tr = get("/api/trend?days=30")
print("TREND len:", len(tr), "| score:", tr[0]["daily_state_score"] if tr else None,
      "| discipline_idx:", tr[0].get("discipline_idx") if tr else None)
srv.shutdown()
print("E2E_OK")
