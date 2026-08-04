# -*- coding: utf-8 -*-
"""
research_decision_log —— 研究决策日志 v0.1（Trading OS · Research Memory 种子）

定位（呼应 Evolution Protocol v1.0 / 用户 2026-08-01 复盘）：
  - 系统核心不是「帮人交易更多」，而是「帮人形成更好的判断」。
  - 大量真实交易出现前，先记录 DECISION（含 NO TRADE），而非 TRADE。
  - Lifecycle：Observation → Decision Memory → Validation → Trading Record。
  - 每条决策 = 当时「知道什么 / 为什么这样判断 / 哪些证据支持 / 哪里会错」，
    后续回填 Outcome / Error Type，成为 AI 私人研究资产。

字段（对齐用户建议结构）：
  decision_id       D{YYYYMMDD}{nn}
  date              交易日
  market_regime     观察：risk_state + a_share_stage + a_share_emotion
  market_score      risk_score（市场状态评分，来自 regime_history）
  market_evidence   JSON：breadth / money_flow / note（客观，自动抽取）
  sector_view       JSON：bullish[{sector,reason}] / avoid[{sector,reason}]
  candidate         JSON：[{code,name,reason}]
  action            BUY / SELL / WAIT / NO TRADE
  hypothesis        如果A发生，则B
  invalidation      如果C发生，则判断错误
  outcome           待验证 / validated / invalid / insufficient
  error_type        待归因 / ...
  source            auto_draft / human
  created_at / updated_at

命令：
  python build_decision_log.py init
  python build_decision_log.py draft [--date YYYY-MM-DD] [--force]
  python build_decision_log.py update --id D... --json '{...}'
  python build_decision_log.py show [--id D... | --date YYYY-MM-DD]
  python build_decision_log.py export
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

DB = str(Path(__file__).parent / "database" / "vibe_research.db")
OUT = Path(__file__).parent / "output"
FLOW_REAL_START = "2026-07-20"  # 个股真实逐日资金流起点
ALLOWED_ACTION = {"BUY", "SELL", "WAIT", "NO TRADE"}


def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def table_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def init(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS research_decision_log (
        decision_id    TEXT PRIMARY KEY,
        date           TEXT,
        market_regime  TEXT,
        market_score   REAL,
        market_evidence TEXT,
        sector_view    TEXT,
        candidate      TEXT,
        action         TEXT,
        hypothesis     TEXT,
        invalidation   TEXT,
        outcome        TEXT,
        error_type     TEXT,
        source         TEXT,
        created_at     TEXT,
        updated_at     TEXT
    )""")


def next_id(cur, d: str) -> str:
    cur.execute("SELECT COUNT(*) FROM research_decision_log WHERE date=?", (d,))
    n = cur.fetchone()[0] + 1
    return f"D{d.replace('-', '')}{n:02d}"


def pull_evidence(cur, d: str):
    """自动抽取客观证据：市场宽度 + 资金流 + regime 观察。"""
    ev = {"breadth": {}, "money_flow": {}, "note": ""}
    cur.execute(
        "SELECT up_count,down_count,flat_count,limit_up_count,limit_down_count "
        "FROM market_daily WHERE date=?", (d,))
    r = cur.fetchone()
    if r and any(v is not None for v in r):
        ev["breadth"] = {"up": r[0], "down": r[1], "flat": r[2],
                         "limit_up": r[3], "limit_down": r[4]}
    else:
        ev["breadth"] = {"note": "market_daily 无该日记录"}

    cur.execute("SELECT SUM(main_net_buy) FROM stock_flow_daily WHERE date=?", (d,))
    s = cur.fetchone()[0]
    if d >= FLOW_REAL_START and s is not None:
        ev["money_flow"] = {"total_main_net_buy": round(float(s), 2), "available": True}
    else:
        ev["money_flow"] = {
            "total_main_net_buy": None, "available": False,
            "note": f"个股资金流真实覆盖自 {FLOW_REAL_START}；该日无可信逐日资金流",
        }

    cur.execute(
        "SELECT risk_state,a_share_stage,a_share_emotion,risk_score FROM regime_history WHERE date=?", (d,))
    rg = cur.fetchone()
    if rg:
        regime = f"risk={rg[0]} | stage={rg[1]} | emotion={rg[2]}"
        score = rg[3]
    else:
        regime = "无 regime_history 记录"
        score = None
    return ev, regime, score


def pull_sector_suggestions(cur, d: str, top: int = 3):
    """草稿预填：TOP 资金净流入板块（看好候选）+ 其龙头（股票候选）。"""
    cur.execute(
        """SELECT sector_name, net_amount, change_pct, leader_code, leader_name
           FROM sector_daily WHERE date=? AND net_amount IS NOT NULL
           ORDER BY net_amount DESC LIMIT ?""", (d, top))
    rows = cur.fetchall()
    bullish, candidates = [], []
    seen = set()
    for i, (sname, na, chg, lcode, lname) in enumerate(rows, 1):
        # net_amount 单位=亿元（与 stock_flow_daily.main_net_buy 一致）
        na_s = f"{na:,.1f}亿" if na is not None else "?"
        bullish.append({"sector": sname,
                        "reason": f"资金净流入TOP{i}（{na_s}）涨幅{chg if chg is not None else '?'}%"})
        if lcode and lcode not in seen:
            seen.add(lcode)
            candidates.append({"code": lcode, "name": lname, "reason": f"{sname}龙头"})
    return bullish, candidates


def draft(cur, d: str, force: bool):
    existing = cur.execute(
        "SELECT decision_id FROM research_decision_log WHERE date=?", (d,)).fetchall()
    if existing and not force:
        print(f"⚠ {d} 已有 {len(existing)} 条决策（"
              + ", ".join(r[0] for r in existing) + "），跳过。用 --force 覆盖重抽。")
        return
    if existing and force:
        cur.execute("DELETE FROM research_decision_log WHERE date=?", (d,))
        print(f"⚠ --force：已删除 {d} 的 {len(existing)} 条旧草稿，重新抽取。")

    ev, regime, score = pull_evidence(cur, d)
    bullish, candidates = pull_sector_suggestions(cur, d)
    did = next_id(cur, d)
    now = datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """INSERT INTO research_decision_log
           (decision_id,date,market_regime,market_score,market_evidence,sector_view,
            candidate,action,hypothesis,invalidation,outcome,error_type,source,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (did, d, regime, score, json.dumps(ev, ensure_ascii=False),
         json.dumps({"bullish": bullish, "avoid": []}, ensure_ascii=False),
         json.dumps(candidates, ensure_ascii=False),
         "WAIT", "", "", "待验证", "待归因", "auto_draft", now, now))
    print(f"✓ 草稿已建 {did}（{d}）")
    print(f"  regime: {regime}")
    print(f"  breadth: {ev['breadth']}")
    print(f"  money_flow: {ev['money_flow']}")
    print(f"  看好候选(预填): {[b['sector'] for b in bullish]}")
    print(f"  股票候选(预填): {[c['code'] for c in candidates]}")
    print(f"  action 默认 WAIT；请用 update 回填 sector_view/hypothesis/invalidation/action。")


def update(cur, did: str, js: str):
    row = cur.execute("SELECT * FROM research_decision_log WHERE decision_id=?", (did,)).fetchone()
    if not row:
        print(f"✗ 无此 decision_id: {did}")
        return
    patch = json.loads(js)
    if "action" in patch and patch["action"] not in ALLOWED_ACTION:
        print(f"✗ 非法 action: {patch['action']}（允许 {ALLOWED_ACTION}）")
        return
    # 仅更新提供的字段
    cols = ["market_regime", "market_score", "market_evidence", "sector_view",
            "candidate", "action", "hypothesis", "invalidation", "outcome", "error_type", "source"]
    for col in cols:
        if col in patch:
            cur.execute(f"UPDATE research_decision_log SET {col}=? WHERE decision_id=?",
                        (json.dumps(patch[col], ensure_ascii=False) if isinstance(patch[col], (dict, list)) else patch[col], did))
    cur.execute("UPDATE research_decision_log SET updated_at=? WHERE decision_id=?",
                (datetime.now().isoformat(timespec="seconds"), did))
    print(f"✓ {did} 已更新字段：{', '.join(patch.keys())}")


def show(cur, did: str | None, d: str | None):
    if did:
        sql = "SELECT * FROM research_decision_log WHERE decision_id=?"
        rows = [cur.execute(sql, (did,)).fetchone()]
    elif d:
        sql = "SELECT * FROM research_decision_log WHERE date=? ORDER BY decision_id"
        rows = cur.execute(sql, (d,)).fetchall()
    else:
        sql = "SELECT * FROM research_decision_log ORDER BY date DESC, decision_id DESC LIMIT 20"
        rows = cur.execute(sql).fetchall()
    cols = [d[0] for d in cur.description]
    for r in rows:
        if not r:
            continue
        rec = dict(zip(cols, r))
        print("=" * 60)
        print(f"[{rec['decision_id']}] {rec['date']}  action={rec['action']}  outcome={rec['outcome']}")
        print(f"  Market Regime : {rec['market_regime']}  (score={rec['market_score']})")
        print(f"  Evidence      : {rec['market_evidence']}")
        print(f"  Sector View   : {rec['sector_view']}")
        print(f"  Candidate     : {rec['candidate']}")
        print(f"  Hypothesis    : {rec['hypothesis']}")
        print(f"  Invalidation  : {rec['invalidation']}")
        print(f"  Error Type    : {rec['error_type']}  source={rec['source']}")


def export(cur):
    rows = cur.execute(
        "SELECT * FROM research_decision_log ORDER BY date, decision_id").fetchall()
    cols = [d[0] for d in cur.description]
    OUT.mkdir(exist_ok=True)
    p = OUT / "research_decision_log.md"
    lines = ["# Research Decision Log（Research Memory 种子）", "",
             "> Lifecycle: Observation → Decision Memory → Validation → Trading Record", ""]
    for r in rows:
        rec = dict(zip(cols, r))
        lines.append(f"## {rec['decision_id']} · {rec['date']} · `{rec['action']}`")
        lines.append(f"- **Market Regime**: {rec['market_regime']} (score={rec['market_score']})")
        lines.append(f"- **Evidence**: {rec['market_evidence']}")
        lines.append(f"- **Sector View**: {rec['sector_view']}")
        lines.append(f"- **Candidate**: {rec['candidate']}")
        lines.append(f"- **Hypothesis**: {rec['hypothesis'] or '(空)'}")
        lines.append(f"- **Invalidation**: {rec['invalidation'] or '(空)'}")
        lines.append(f"- **Outcome**: {rec['outcome']} · **Error Type**: {rec['error_type']} · source={rec['source']}")
        lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ 已导出 {p}（{len(rows)} 条）")


def main():
    ap = argparse.ArgumentParser(description="研究决策日志 v0.1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    pd = sub.add_parser("draft")
    pd.add_argument("--date", help="交易日（默认取 stock_daily 最新日）")
    pd.add_argument("--force", action="store_true", help="已有则重抽覆盖")
    pu = sub.add_parser("update")
    pu.add_argument("--id", required=True)
    pu.add_argument("--json", required=True, help="合并字段的 JSON 对象")
    ps = sub.add_parser("show")
    ps.add_argument("--id")
    ps.add_argument("--date")
    sub.add_parser("export")
    args = ap.parse_args()

    con = connect()
    cur = con.cursor()
    if args.cmd == "init":
        init(cur); con.commit()
        print("✓ research_decision_log 表已就绪")
        return

    init(cur)  # 确保表存在
    if args.cmd == "draft":
        d = args.date
        if not d:
            cur.execute("SELECT MAX(date) FROM stock_daily")
            d = cur.fetchone()[0] or date.today().isoformat()
        draft(cur, d, args.force)
    elif args.cmd == "update":
        update(cur, args.id, args.json)
    elif args.cmd == "show":
        show(cur, args.id, args.date)
    elif args.cmd == "export":
        export(cur)
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
