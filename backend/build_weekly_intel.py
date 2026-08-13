# -*- coding: utf-8 -*-
"""
build_weekly_intel.py — Joy Research · 周度认知更新 Weekly Intelligence Update v0.1
（ colloquial: 周报 / Weekly Report ；内部规范名：周度认知更新 / Weekly Intelligence Update ）

定位（重要，冻结安全）：
    周度认知更新是 Research OS 的「周期复盘层 / 认知复利层 / 时间维度压缩器」，属于 Evolution Protocol 的
    Layer2（能力迭代 / 合成呈现层），不新建任何评分模型：
      * 市场状态 / 评分  → 复用 regime_history.risk_state / risk_score（Layer1 冻结稳定层）
      * 量化部分        → 仅聚合现有 DB（market_daily / sector_daily / limit_up_daily /
                          stock_flow_daily / research_decision_log），不引入新权重
      * 认知 / 战略部分  → key_changes / leader_add / leader_remove / next_week_plan
                          全部留空待人工回填（update 子命令）

模块（固定 7 + 决策复盘）：
    1. 市场状态评分（复用 regime_history，非新模型）
    2. 本周关键变化（人工）
    3. 资金流向（A股周净流入 + 板块资金地图）
    4. 板块趋势排名（Top10，逻辑列人工）
    5. 龙头变化（人工增删 + 本周板块龙头建议）
    6. 风险检查（自动推导）
    7. 下周计划（人工）
    + 本周决策复盘（来自 research_decision_log，纯读取）

用法：
    python build_weekly_report.py init
    python build_weekly_report.py draft [--week-end YYYY-MM-DD] [--force]
    python build_weekly_report.py update --week-end YYYY-MM-DD --json '{...}'
    python build_weekly_report.py show [--week-end YYYY-MM-DD]
    python build_weekly_report.py export
"""
import sqlite3, json, os, argparse
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(__file__), "database", "vibe_research.db")
OUT = os.path.join(os.path.dirname(__file__), "output", "research_weekly_intel.md")
FLOW_AVAIL_FROM = "2026-07-20"  # stock_flow_daily 真实数据起点（审计确认）


def conn():
    return sqlite3.connect(DB)


def most_recent_friday(d=None):
    d = d or datetime.now().date()
    while d.weekday() != 4:  # 4 = Friday
        d -= timedelta(days=1)
    return d


def week_range(week_end):
    we = (datetime.strptime(week_end, "%Y-%m-%d").date()
          if isinstance(week_end, str) else week_end)
    ws = we - timedelta(days=4)  # Monday
    return ws.isoformat(), we.isoformat()


# ---------------- init ----------------
def init():
    c = conn(); cur = c.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS research_weekly_intel (
        week_end        TEXT PRIMARY KEY,
        week_start      TEXT,
        regime_state    TEXT,
        regime_score    REAL,
        a_share_week_ret REAL,
        breadth_avg_up  REAL,
        breadth_avg_down REAL,
        amount_last     REAL,
        amount_avg20    REAL,
        amount_trend_pct REAL,
        limit_up_avg    REAL,
        max_board_height INTEGER,
        a_share_net_inflow REAL,
        top_sectors     TEXT,   -- json list
        weak_sectors    TEXT,   -- json list
        decision_summary TEXT,  -- json
        risk_check      TEXT,
        key_changes     TEXT,
        leader_add      TEXT,
        leader_remove   TEXT,
        next_week_plan  TEXT,
        source          TEXT,
        created_at      TEXT,
        updated_at      TEXT
    )""")
    c.commit(); c.close()
    print("✅ research_weekly_intel 表已就绪")


# ---------------- draft ----------------
def draft(week_end=None, force=False):
    we = most_recent_friday(
        datetime.strptime(week_end, "%Y-%m-%d").date() if week_end else None)
    ws, we_s = week_range(we)
    c = conn(); cur = c.cursor()

    existing = cur.execute(
        "SELECT week_end FROM research_weekly_intel WHERE week_end=?",
        (we_s,)).fetchall()
    if existing and not force:
        print(f"⚠ {we_s} 周度认知更新已存在，跳过。用 --force 覆盖重抽。")
        c.close(); return
    if existing and force:
        cur.execute("DELETE FROM research_weekly_intel WHERE week_end=?", (we_s,))

    rec = {"week_end": we_s, "week_start": ws, "source": "auto",
           "created_at": datetime.now().isoformat(timespec="seconds")}

    # 1) 市场状态（复用 regime_history，冻结层）
    r = cur.execute(
        "SELECT risk_state,risk_score,a_share_ret,commodity_states,risk_drivers "
        "FROM regime_history WHERE date BETWEEN ? AND ? ORDER BY date DESC LIMIT 1",
        (ws, we_s)).fetchone()
    if r:
        rec["regime_state"] = r[0]
        rec["regime_score"] = r[1]
        rows = cur.execute(
            "SELECT a_share_ret FROM regime_history WHERE date BETWEEN ? AND ? "
            "AND a_share_ret IS NOT NULL", (ws, we_s)).fetchall()
        rec["a_share_week_ret"] = round(sum(x[0] for x in rows), 2) if rows else None
    else:
        rec["regime_state"] = rec["regime_score"] = rec["a_share_week_ret"] = None

    # 2) 市场宽度 / 流动性 / 涨停（market_daily）
    md = cur.execute(
        "SELECT date,up_count,down_count,total_amount,limit_up_count,avg_20d_amount "
        "FROM market_daily WHERE date BETWEEN ? AND ? ORDER BY date",
        (ws, we_s)).fetchall()
    if md:
        ups = [x[1] for x in md]; downs = [x[2] for x in md]
        rec["breadth_avg_up"] = round(sum(ups)/len(ups), 0)
        rec["breadth_avg_down"] = round(sum(downs)/len(downs), 0)
        rec["amount_last"] = md[-1][3]
        rec["amount_avg20"] = md[-1][5]
        rec["amount_trend_pct"] = round((md[-1][3]-md[-1][5])/md[-1][5]*100, 1) if md[-1][5] else None
        rec["limit_up_avg"] = round(sum(x[4] for x in md)/len(md), 0)
    else:
        rec.update(dict.fromkeys(
            ["breadth_avg_up","breadth_avg_down","amount_last","amount_avg20",
             "amount_trend_pct","limit_up_avg"], None))

    # 3) 涨停投机强度（limit_up_daily）
    bh = cur.execute(
        "SELECT MAX(board_height) FROM limit_up_daily WHERE date BETWEEN ? AND ?",
        (ws, we_s)).fetchone()
    rec["max_board_height"] = bh[0] if bh else None

    # 4) A股周净流入（stock_flow_daily，真实起点 FLOW_AVAIL_FROM）
    if ws >= FLOW_AVAIL_FROM:
        nf = cur.execute(
            "SELECT SUM(main_net_buy) FROM stock_flow_daily WHERE date BETWEEN ? AND ?",
            (ws, we_s)).fetchone()
        rec["a_share_net_inflow"] = round(nf[0], 1) if nf and nf[0] is not None else None
    else:
        rec["a_share_net_inflow"] = None

    # 5) 板块资金地图（sector_daily 周聚合）
    sec = cur.execute(
        "SELECT sector_name AS sector, SUM(net_amount), AVG(change_pct) "
        "FROM sector_daily WHERE date BETWEEN ? AND ? GROUP BY sector_name",
        (ws, we_s)).fetchall()
    lim = cur.execute(
        "SELECT sector, COUNT(*) FROM limit_up_daily WHERE date BETWEEN ? AND ? "
        "GROUP BY sector", (ws, we_s)).fetchall()
    lim_map = {s: n for s, n in lim}
    sec_sorted = sorted([s for s in sec if s[1] is not None],
                        key=lambda x: x[1], reverse=True)
    top = [{"sector": s, "net": round(v, 1), "chg": round(c, 2) if c else None,
            "lim": lim_map.get(s, 0)} for s, v, c in sec_sorted[:10]]
    weak = [{"sector": s, "net": round(v, 1), "chg": round(c, 2) if c else None,
             "lim": lim_map.get(s, 0)} for s, v, c in sec_sorted[-10:][::-1]]
    rec["top_sectors"] = json.dumps(top, ensure_ascii=False)
    rec["weak_sectors"] = json.dumps(weak, ensure_ascii=False)

    # 6) 决策复盘（research_decision_log，纯读取）
    ds = cur.execute(
        "SELECT action, COUNT(*) FROM research_decision_log WHERE date BETWEEN ? AND ? "
        "GROUP BY action", (ws, we_s)).fetchall()
    rec["decision_summary"] = json.dumps({a: n for a, n in ds}, ensure_ascii=False)

    # 7) 风险检查（自动推导，透明规则，非评分模型）
    rec["risk_check"] = build_risk_check(rec)

    # 认知字段留空
    for k in ("key_changes", "leader_add", "leader_remove", "next_week_plan"):
        rec[k] = ""

    cols = ",".join(rec.keys())
    ph = ",".join("?" * len(rec))
    cur.execute(f"INSERT INTO research_weekly_intel ({cols}) VALUES ({ph})",
                list(rec.values()))
    c.commit(); c.close()
    print(f"✅ 周度认知更新草稿已生成：{ws} ~ {we_s}（量化部分就绪，认知字段待 update 回填）")


def build_risk_check(rec):
    lines = []
    up = rec.get("breadth_avg_up"); dn = rec.get("breadth_avg_down")
    if up is not None and dn is not None and (up + dn) > 0:
        ratio = up / (up + dn)
        if ratio < 0.45:
            lines.append(f"⚠ 宽度偏弱：上涨家数占比 {ratio*100:.0f}%（均涨{up:.0f}/均跌{dn:.0f}），市场分歧大")
        else:
            lines.append(f"✅ 宽度中性偏强：上涨家数占比 {ratio*100:.0f}%（均涨{up:.0f}/均跌{dn:.0f}）")
    tp = rec.get("amount_trend_pct")
    if tp is not None:
        if tp < -10:
            lines.append(f"⚠ 流动性收缩：成交额较20日均值 {tp:.1f}%")
        elif tp > 10:
            lines.append(f"✅ 放量：成交额较20日均值 +{tp:.1f}%")
        else:
            lines.append(f"· 成交额较20日均值 {tp:+.1f}%（平稳）")
    la = rec.get("limit_up_avg")
    if la is not None:
        if la < 60:
            lines.append(f"⚠ 投机情绪降温：周均涨停 {la:.0f} 家")
        else:
            lines.append(f"✅ 投机活跃：周均涨停 {la:.0f} 家")
    if not lines:
        lines.append("· 本周数据不足，风险检查待累积")
    return "\n".join(lines)


# ---------------- update ----------------
def update(week_end, payload):
    c = conn(); cur = c.cursor()
    if not cur.execute("SELECT week_end FROM research_weekly_intel WHERE week_end=?",
                       (week_end,)).fetchone():
        print(f"⚠ {week_end} 周度认知更新不存在，请先 draft。"); c.close(); return
    allowed = {"key_changes", "leader_add", "leader_remove", "next_week_plan",
               "regime_state", "regime_score"}
    sets = []
    for k, v in payload.items():
        if k not in allowed:
            print(f"· 忽略非允许字段 {k}"); continue
        sets.append((k, v))
    if not sets:
        print("无可更新字段"); c.close(); return
    sets.append(("updated_at", datetime.now().isoformat(timespec="seconds")))
    cur.execute(f"UPDATE research_weekly_intel SET " +
                ", ".join(f"{k}=?" for k, _ in sets) +
                " WHERE week_end=?", [v for _, v in sets] + [week_end])
    c.commit(); c.close()
    print(f"✅ {week_end} 周度认知更新已更新：{', '.join(k for k,_ in sets)}")


# ---------------- show ----------------
def show(week_end=None):
    c = conn(); cur = c.cursor()
    if week_end:
        row = cur.execute("SELECT * FROM research_weekly_intel WHERE week_end=?",
                          (week_end,)).fetchone()
        rows = [row] if row else []
    else:
        rows = cur.execute("SELECT * FROM research_weekly_intel ORDER BY week_end DESC").fetchall()
    cols = [d[0] for d in cur.description]
    c.close()
    if not rows:
        print("暂无周度认知更新"); return
    for r in rows:
        d = dict(zip(cols, r))
        print("=" * 64)
        print(f"📅 周度认知更新 {d['week_start']} ~ {d['week_end']}  (source={d['source']})")
        print("-" * 64)
        print(f"市场状态: {d['regime_state']}  评分(复用regime_history): {d['regime_score']}")
        print(f"本周A股收益(汇总): {d['a_share_week_ret']}")
        print(f"宽度: 均涨{d['breadth_avg_up']}/均跌{d['breadth_avg_down']}  成交额趋势: {d['amount_trend_pct']}%")
        print(f"涨停: 周均{d['limit_up_avg']}家  最高连板{d['max_board_height']}板  A股周净流入: {d['a_share_net_inflow']}亿")
        print(f"决策: {d['decision_summary']}")
        print(f"\n[风险检查]\n{d['risk_check']}")
        print(f"\n[关键变化] {d['key_changes'] or '— 待填 —'}")
        print(f"[龙头增] {d['leader_add'] or '— 待填 —'}")
        print(f"[龙头减] {d['leader_remove'] or '— 待填 —'}")
        print(f"[下周计划] {d['next_week_plan'] or '— 待填 —'}")


# ---------------- export ----------------
def export():
    c = conn(); cur = c.cursor()
    rows = cur.execute("SELECT * FROM research_weekly_intel ORDER BY week_end DESC").fetchall()
    cols = [d[0] for d in cur.description]
    c.close()
    if not rows:
        print("暂无周度认知更新可导出"); return
    L = ["# Joy Research · Weekly Intelligence Report\n"]
    for r in rows:
        d = dict(zip(cols, r))
        top = json.loads(d["top_sectors"] or "[]")
        weak = json.loads(d["weak_sectors"] or "[]")
        dec = json.loads(d["decision_summary"] or "{}")
        L.append(f"\n---\n## 周度认知更新 {d['week_start']} ~ {d['week_end']}\n")
        L.append("### 1. 市场状态评分（复用 regime_history，非新模型）\n")
        L.append(f"- 状态：**{d['regime_state']}**　评分：**{d['regime_score']}**（Layer1 冻结稳定层）")
        L.append(f"- 本周A股收益（日收益汇总）：{d['a_share_week_ret']}")
        L.append(f"- 宽度：均涨 {d['breadth_avg_up']} / 均跌 {d['breadth_avg_down']}")
        L.append(f"- 成交额：最新 {d['amount_last']} 亿，较20日均值 {d['amount_trend_pct']}%")
        L.append(f"- 涨停生态：周均 {d['limit_up_avg']} 家，最高连板 {d['max_board_height']} 板")
        L.append("\n### 2. 本周关键变化（人工）\n")
        L.append(d["key_changes"] or "> 待填：仅记录改变投资判断的信息（非新闻罗列）")
        L.append("\n### 3. 资金流向（资金地图）\n")
        if d['a_share_net_inflow'] is not None:
            L.append(f"- A股周主力净流入：**{d['a_share_net_inflow']} 亿**（数据自 {FLOW_AVAIL_FROM} 起真实）")
        else:
            L.append(f"- A股周主力净流入：数据自 {FLOW_AVAIL_FROM} 起可用（本周早于起点）")
        if top:
            L.append("- 资金增强板块 Top：")
            for s in top[:5]:
                L.append(f"  - {s['sector']}：净流入 {s['net']} 亿，周均 {s['chg']}%，涨停参与 {s['lim']} 次")
        if weak:
            L.append("- 资金减弱板块：")
            for s in weak[:5]:
                L.append(f"  - {s['sector']}：净流入 {s['net']} 亿，周均 {s['chg']}%")
        L.append("\n### 4. 板块趋势排名（Top10）\n")
        L.append("| 排名 | 板块 | 周净流入(亿) | 周均涨跌幅 | 涨停参与 | 逻辑 |")
        L.append("| -- | -- | -- | -- | -- | -- |")
        for i, s in enumerate(top, 1):
            L.append(f"| {i} | {s['sector']} | {s['net']} | {s['chg']} | {s['lim']} | 待填 |")
        L.append("\n### 5. 龙头变化（Leader Watchlist，人工）\n")
        L.append(f"- 新增：{d['leader_add'] or '待填'}")
        L.append(f"- 删除：{d['leader_remove'] or '待填'}")
        L.append("\n### 6. 风险检查（自动推导）\n")
        L.append(d["risk_check"])
        L.append("\n### 7. 下周计划（人工）\n")
        L.append(d["next_week_plan"] or "> 待填：市场判断 / 建议仓位 / 重点方向 / 避免 / 触发降仓条件")
        L.append("\n### + 本周决策复盘（来自 Decision Log）\n")
        if dec:
            L.append("本周系统判断：" + "，".join(f"{k} {v}次" for k, v in dec.items()))
        else:
            L.append("本周无 Decision Log 记录（系统尚未积累判断样本）。")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"✅ 已导出：{OUT}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init")
    p = sub.add_parser("draft")
    p.add_argument("--week-end", default=None)
    p.add_argument("--force", action="store_true")
    u = sub.add_parser("update")
    u.add_argument("--week-end", required=True)
    u.add_argument("--json", required=True)
    s = sub.add_parser("show")
    s.add_argument("--week-end", default=None)
    sub.add_parser("export")
    args = ap.parse_args()
    if args.cmd == "init":
        init()
    elif args.cmd == "draft":
        draft(args.week_end, args.force)
    elif args.cmd == "update":
        update(args.week_end, json.loads(args.json))
    elif args.cmd == "show":
        show(args.week_end)
    elif args.cmd == "export":
        export()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
