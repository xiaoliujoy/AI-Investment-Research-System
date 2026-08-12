#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘晓每日系统 v1.0  —— Daily OS
零依赖本地服务：纯 Python 标准库 (http.server + sqlite3)
运行: python app.py  (可选端口: python app.py 8777)
打开: http://127.0.0.1:8777
"""
import os
import sys
import json
import sqlite3
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "daily_os.db")
INDEX_PATH = os.path.join(BASE_DIR, "index.html")
# 交易 OS 主库（只读拉取 + 复盘回写 trader_review），路径以 backend/db.py 为准
TRADING_DB = os.path.normpath(os.path.join(BASE_DIR, "..", "backend", "database", "vibe_research.db"))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777

NOON_STATES = ["平静", "喜悦", "丰盛", "焦虑", "疲惫", "混乱", "其他"]

# ----------------------------------------------------------------------------
# 数据库
# ----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_records (
            date              TEXT PRIMARY KEY,
            noon_state       TEXT,
            noon_note        TEXT,
            trade_data       TEXT,   -- JSON: [ {plan, execution, belief, note} ]
            evening_data     TEXT,   -- JSON: {spiritual, trade_review, growth}
            score_inner      REAL,
            score_abundance  REAL,
            score_discipline REAL,
            score_awareness  REAL,
            score_joy        REAL,
            daily_state_score REAL,
            presence         REAL,
            discipline_idx   REAL,
            joy_idx          REAL,
            belief_fulfillment REAL,  -- 信念兑现率 (0-5)，无交易则为 NULL
            trade_link       TEXT,   -- 预留：对接 trade_journal 的关联键
            updated_at       TEXT
        )
    """)
    conn.commit()
    conn.close()

def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")

def ensure_row(date_str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT date FROM daily_records WHERE date=?", (date_str,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO daily_records (date, trade_data, evening_data, updated_at) VALUES (?,?,?,?)",
                    (date_str, "[]", "{}", datetime.datetime.now().isoformat()))
        conn.commit()
    conn.close()

def compute_scores(rec):
    """计算 Daily State Score 与三项长期指标（提案映射，可改）。"""
    s_inner = rec.get("score_inner")
    s_abun = rec.get("score_abundance")
    s_disc = rec.get("score_discipline")
    s_aware = rec.get("score_awareness")
    s_joy = rec.get("score_joy")
    scores = [s_inner, s_abun, s_disc, s_aware, s_joy]
    valid = [s for s in scores if s is not None]
    dss = round(sum(valid) / len(valid), 2) if valid else None

    presence = None
    if s_aware is not None and s_inner is not None:
        presence = round((s_aware + s_inner) / 2, 2)

    discipline_idx = None
    if s_disc is not None:
        belief = rec.get("belief_fulfillment")
        if belief is not None:
            discipline_idx = round((s_disc + belief) / 2, 2)
        else:
            discipline_idx = float(s_disc)

    joy_idx = None
    if s_joy is not None and s_abun is not None:
        joy_idx = round((s_joy + s_abun) / 2, 2)

    return dss, presence, discipline_idx, joy_idx

def upsert_partial(date_str, **fields):
    ensure_row(date_str)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM daily_records WHERE date=?", (date_str,))
    row = dict(cur.fetchone())
    row.update({k: v for k, v in fields.items() if v is not None})
    dss, presence, discipline_idx, joy_idx = compute_scores(row)
    row["daily_state_score"] = dss
    row["presence"] = presence
    row["discipline_idx"] = discipline_idx
    row["joy_idx"] = joy_idx
    row["updated_at"] = datetime.datetime.now().isoformat()
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    cur.execute(f"INSERT OR REPLACE INTO daily_records ({','.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols])
    conn.commit()
    conn.close()

# ----------------------------------------------------------------------------
# 交易 OS 对接（只读拉取 trade_journal + 复盘回写 trader_review）
# 边界：只读取客观台账、只向 trader_review 插入复盘；绝不修改 trade_journal 事实。
# ----------------------------------------------------------------------------
def import_trades_from_os(date_str):
    """从交易 OS 主库 trade_journal 拉取当日客观交易台账。无库或出错返回 []。"""
    if not os.path.exists(TRADING_DB):
        return []
    try:
        conn = sqlite3.connect(TRADING_DB, timeout=10)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, trade_date, code, name, action, plan_stop, result, pnl, "
            "judge_result, exec_result, note FROM trade_journal WHERE trade_date=? ORDER BY id",
            (date_str,))
        out = []
        for r in cur.fetchall():
            out.append({
                "journal_id": r["id"],
                "code": r["code"], "name": r["name"], "action": r["action"],
                "plan_stop": r["plan_stop"], "result": r["result"], "pnl": r["pnl"],
                "judge_result": r["judge_result"], "exec_result": r["exec_result"],
                "note": r["note"],
                # 以下为 daily-os 侧待用户主观填写的字段，先留空
                "env": None, "dir": r["action"], "has_chance": "是" if r["action"] else None,
                "accept_no": None, "entry": None, "plan": None,
                "chase": None, "early": None, "loss": None,
            })
        conn.close()
        return out
    except Exception:
        return []

def sync_review_to_os(date_str, reviews):
    """把当日晚间交易复盘（定性部分）回写交易 OS 的 trader_review 表。仅插入，不改动既有数据。"""
    if not os.path.exists(TRADING_DB):
        return 0
    try:
        conn = sqlite3.connect(TRADING_DB, timeout=10)
        cur = conn.cursor()
        now = datetime.datetime.now().isoformat()
        inserted = 0
        for rv in reviews:
            tid = rv.get("trade_id")
            if not tid:
                continue
            cur.execute(
                "INSERT INTO trader_review "
                "(trade_id, rdate, decision_quality, execution_quality, emotion_management, "
                "judgment_correct, execution_correct, fear_trigger, improvement, deviation_reason, close_reason, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, date_str,
                 rv.get("belief"), rv.get("belief"), rv.get("emotion"),
                 rv.get("judgment_correct"), rv.get("execution_correct"),
                 rv.get("fear_trigger"), rv.get("improvement"),
                 rv.get("deviation_reason"), rv.get("close_reason"), now))
            inserted += 1
        conn.commit()
        conn.close()
        return inserted
    except Exception:
        return 0

# ----------------------------------------------------------------------------
# API 助手
# ----------------------------------------------------------------------------
def read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}

def send_json(handler, obj, status=200):
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    try:
        d["trade_data"] = json.loads(d["trade_data"]) if d.get("trade_data") else []
    except Exception:
        d["trade_data"] = []
    try:
        d["evening_data"] = json.loads(d["evening_data"]) if d.get("evening_data") else {}
    except Exception:
        d["evening_data"] = {}
    return d

# ----------------------------------------------------------------------------
# HTTP Handler
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默日志，保持清爽

    def _serve_index(self):
        try:
            with open(INDEX_PATH, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"index.html not found")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._serve_index()
            return
        if path == "/api/today":
            date_str = parse_qs(parsed.query).get("date", [today_str()])[0]
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM daily_records WHERE date=?", (date_str,))
            row = cur.fetchone()
            conn.close()
            send_json(self, row_to_dict(row) or {"date": date_str})
            return
        if path == "/api/trend":
            days = int(parse_qs(parsed.query).get("days", [30])[0])
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT date, daily_state_score, presence, discipline_idx, joy_idx, "
                "score_inner, score_abundance, score_discipline, score_awareness, score_joy "
                "FROM daily_records WHERE daily_state_score IS NOT NULL "
                "ORDER BY date DESC LIMIT ?", (days,))
            rows = [dict(r) for r in cur.fetchall()]
            rows.reverse()
            conn.close()
            send_json(self, rows)
            return
        if path == "/api/record":
            date_str = parse_qs(parsed.query).get("date", [today_str()])[0]
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM daily_records WHERE date=?", (date_str,))
            row = cur.fetchone()
            conn.close()
            send_json(self, row_to_dict(row) or {"date": date_str})
            return
        if path == "/api/import_trades":
            date_str = parse_qs(parsed.query).get("date", [today_str()])[0]
            send_json(self, import_trades_from_os(date_str))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = read_body(self)

        if path == "/api/noon":
            date_str = body.get("date", today_str())
            ensure_row(date_str)
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE daily_records SET noon_state=?, noon_note=?, updated_at=? WHERE date=?",
                        (body.get("state"), body.get("note", ""),
                         datetime.datetime.now().isoformat(), date_str))
            conn.commit()
            conn.close()
            send_json(self, {"ok": True})
            return

        if path == "/api/trade":
            date_str = body.get("date", today_str())
            ensure_row(date_str)
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT trade_data FROM daily_records WHERE date=?", (date_str,))
            td = cur.fetchone()["trade_data"] or "[]"
            try:
                trades = json.loads(td)
            except Exception:
                trades = []
            trades.append(body.get("session", {}))
            cur.execute("UPDATE daily_records SET trade_data=?, updated_at=? WHERE date=?",
                        (json.dumps(trades, ensure_ascii=False),
                         datetime.datetime.now().isoformat(), date_str))
            conn.commit()
            conn.close()
            send_json(self, {"ok": True, "count": len(trades)})
            return

        if path == "/api/evening":
            date_str = body.get("date", today_str())
            fields = {}
            for k in ["score_inner", "score_abundance", "score_discipline",
                      "score_awareness", "score_joy", "belief_fulfillment"]:
                if k in body and body[k] is not None:
                    fields[k] = float(body[k])
            fields["evening_data"] = json.dumps(body.get("evening_data", {}), ensure_ascii=False)
            if "trade_link" in body and body["trade_link"] is not None:
                fields["trade_link"] = body["trade_link"]
            upsert_partial(date_str, **fields)
            send_json(self, {"ok": True})
            return

        if path == "/api/link":
            date_str = body.get("date", today_str())
            ensure_row(date_str)
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE daily_records SET trade_link=? WHERE date=?",
                        (body.get("trade_link", ""), date_str))
            conn.commit()
            conn.close()
            send_json(self, {"ok": True})
            return

        if path == "/api/sync_review":
            date_str = body.get("date", today_str())
            n = sync_review_to_os(date_str, body.get("reviews", []))
            send_json(self, {"ok": True, "inserted": n})
            return

        self.send_response(404)
        self.end_headers()

def run():
    init_db()
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"刘晓每日系统 v1.0  已启动")
    print(f"打开: http://127.0.0.1:{PORT}")
    print(f"数据库: {DB_PATH}")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.shutdown()

if __name__ == "__main__":
    run()
