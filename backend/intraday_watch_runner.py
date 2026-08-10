#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
intraday_watch_runner.py — 盘中 Watch List 信号判定器 v3（通用·动态热点）

v3 相对 v2 的三处改造（v2 三处硬阻塞的修复）：
  1. **不再写死板块**。v2 五个 checker 全部硬编码 软件开发/影视院线；v3 改为
     「阶段条件模板 × 动态板块列表」，同一阶段对 N 个板块逐一判定、逐行写库。
  2. **基准日回退**。sector_daily 是盘后表（tdx 收盘后写入），盘中查当天必为空。
     v3 用 resolve_base_date() 取「<= 目标日的最近一个有数据交易日」作为主线来源，
     盘中即是用 T-1 定的主线去验证今天延不延续 —— 符合「近5日资金流定主线」方法论。
  3. **time_point 自由化**。--time 接受任意 4 位 HHMM，内部映射到 5 个阶段；
     09:30/10:30/11:30 等新时点不再 argparse 崩溃。

阶段映射（HHMM -> stage）：
  09:00-09:59 open      开盘段：主线资金是否延续（净流入>0）
  10:00-10:59 morning   上午段：龙头是否给力（封板 或 涨幅>7%）
  11:00-12:59 midday    半日段：板块涨幅>0 且 净流入>0；另加「全市场」半日成交额>7500亿
  13:00-13:59 afternoon 午后段：涨幅>1% 且 净流入>0
  14:00-15:59 close     尾盘段：净流入是否仍为正

板块来源优先级：
  --sectors "A,B,C"  >  --json.watch_sectors  >  sector_daily 基准日 net_amount TOP N（--top，默认5）

字段取值优先级（每板块，取不到即 None，判定为「未知」，绝不伪造）：
  涨跌幅 chg : json.sector_quote[name|code].change_percent
             -> json.sector_rank[] 匹配 bd_name/bd_code 的 bd_zdf
  净流入 net : json.sector_net[name]                     （单位亿元，automation 直接给，最优）
             -> --fundflow 成分股 MainNetFlow 聚合        （需 industry_map 有该板块成分）
             -> json.plate_ranking.top/bottom 截断符号判定（只能定符号，不能定量）
  龙头 leader: json.sector_leader[name]
             -> json.sector_rank[] 的 nzg_code/nzg_name/nzg_zdf
             -> sector_daily 基准日 leader_code/leader_name（T-1 龙头，note 标注）

数据源说明（westock）：
  - data_sector mode=ranking -> rank.plate/concept 给**实时**板块涨跌幅 bd_zdf + 领涨股 nzg_*（免费，不额外调用）
  - data_sector mode=ranking -> fundflow.plate/concept.top|bottom 各 3 条给精确 zljlr（万元），**只有 12 个板块**
  - 其余板块的精确净流入需成分股 data_fund_flow 聚合，或直接判「未知」
  - 三大指数 amount 累加为半日成交额近似（非全市场口径）

用法：
  python intraday_watch_runner.py --time 0930 --json <j> [--fundflow <f>] [--sectors "A,B"] [--top 5] [--dry-run]

写库：intraday_watch_signal(date, time_point, sector) 唯一，重复运行 UPSERT。
"""
import argparse
import glob
import json
import os
import re
import sqlite3
from datetime import date

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "vibe_research.db")

# ---- 阶段定义 ----------------------------------------------------------------
STAGES = ("open", "morning", "midday", "afternoon", "close")

STAGE_LABEL = {
    "open": "开盘段",
    "morning": "上午段",
    "midday": "半日段",
    "afternoon": "午后段",
    "close": "尾盘段",
}

# 全市场半日成交额阈值（亿元）
MARKET_AMOUNT_THRESHOLD = 7500.0


def stage_of(hhmm: str) -> str:
    """HHMM -> stage。非交易时段按最近的阶段归类，不报错。"""
    h = int(hhmm[:2])
    m = int(hhmm[2:])
    t = h * 60 + m
    if t < 10 * 60:
        return "open"
    if t < 11 * 60:
        return "morning"
    if t < 13 * 60:
        return "midday"
    if t < 14 * 60:
        return "afternoon"
    return "close"


# ---- DB ----------------------------------------------------------------------
def get_conn():
    return sqlite3.connect(DB)


def ensure_table(c):
    c.execute(
        """CREATE TABLE IF NOT EXISTS intraday_watch_signal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time_point TEXT,
            sector TEXT,
            condition_text TEXT,
            met INTEGER,
            actual TEXT,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    try:
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_iws_uniq "
            "ON intraday_watch_signal(date, time_point, sector)"
        )
    except (sqlite3.OperationalError, sqlite3.IntegrityError):
        c.execute(
            "DELETE FROM intraday_watch_signal WHERE id NOT IN ("
            "SELECT MAX(id) FROM intraday_watch_signal GROUP BY date, time_point, sector)"
        )
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_iws_uniq "
            "ON intraday_watch_signal(date, time_point, sector)"
        )
    c.commit()


def resolve_base_date(c, target_date: str):
    """取 <= target_date 的最近一个 sector_daily 有数据的交易日。无则 None。"""
    row = c.execute(
        "SELECT MAX(date) FROM sector_daily WHERE date <= ? AND net_amount IS NOT NULL",
        (target_date,),
    ).fetchone()
    return row[0] if row and row[0] else None


def top_sectors_from_db(c, base_date: str, n: int):
    """基准日 net_amount TOP N。返回 [(name, net_amount, change_pct, leader_code, leader_name)]"""
    return c.execute(
        "SELECT sector_name, net_amount, change_pct, leader_code, leader_name "
        "FROM sector_daily WHERE date=? AND net_amount IS NOT NULL "
        "ORDER BY net_amount DESC LIMIT ?",
        (base_date, n),
    ).fetchall()


def db_leader_map(c, base_date: str, names):
    """基准日各板块的 T-1 龙头，作为兜底。"""
    if not names:
        return {}
    q = ",".join("?" * len(names))
    rows = c.execute(
        f"SELECT sector_name, leader_code, leader_name, leader_change_pct "
        f"FROM sector_daily WHERE date=? AND sector_name IN ({q})",
        (base_date, *names),
    ).fetchall()
    return {r[0]: {"code": r[1], "name": r[2], "change_percent": r[3]} for r in rows}


def sector_members(c, name):
    """板块成分股代码集合（本地 industry_map）。取不到返回空集。"""
    rows = c.execute(
        "SELECT stock_code FROM industry_map WHERE industry_name=?", (name,)
    ).fetchall()
    return {r[0] for r in rows}


def dedup_sectors(c, names, thr=0.5):
    """按成分股重叠度，用并查集聚类把同一主线的板块并成一条。

    sector_daily 混装申万行业与东财概念，TOP5 常是同一产业链的不同口径
    （电子/半导体概念/国产芯片/存储芯片 龙头常同一只）。逐个判定 = 把同一件事
    判 N 遍，还容易被「龙头同只股」误导。

    度量用 overlap coefficient = |A∩B| / min(|A|,|B|)（不用 Jaccard：小概念被大
    行业包含时 Jaccard 偏低，overlap 才能反映「同一主线」）。把 pairwise overlap
    >= thr 的板块用**并查集聚类**连成连通分量；贪心逐对合并会漏掉传递合并
    （A~B 合并后，C~B 成立但 C 不再跟 A 比 → C 漏掉），故用 union-find。

    默认 thr=0.5：实测 2026-08-05 TOP5（电子/半导体概念/国产芯片/物联网/存储芯片）
    在 0.5 下聚成 2 条主线（芯片半导体链 + 物联网），0.7 下只并掉 1 对（仍 4 条），
    偏保守。0.5 是混装口径下的合理拐点。

    输入按净流入降序，每个连通分量保留先出现（净流入最大）的板块作 anchor。
    返回 (kept:[anchor_name], merged:[(被并入板块, anchor板块, overlap)])
    """
    mem = {n: sector_members(c, n) for n in names}
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = mem[names[i]], mem[names[j]]
            if a and b:
                ov = len(a & b) / min(len(a), len(b))
                if ov >= thr:
                    union(names[i], names[j])

    groups = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    kept, merged = [], []
    for members in groups.values():
        anchor = members[0]  # names 顺序 = 净流入降序，首位是 anchor
        kept.append(anchor)
        for m in members[1:]:
            ov = 0.0
            if mem[m] and mem[anchor]:
                ov = len(mem[m] & mem[anchor]) / min(len(mem[m]), len(mem[anchor]))
            merged.append((m, anchor, ov))
    return kept, merged


# ---- JSON 输入 ----------------------------------------------------------------
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_fundflow(path):
    """精简资金流 JSON（单文件或目录 glob 合并多批）。
    格式：{"sector_flow": {板块名: [{code,name,MainNetFlow,...}]}}  MainNetFlow 单位=元"""
    if not path:
        return {}
    files = sorted(glob.glob(os.path.join(path, "*.json"))) if os.path.isdir(path) else [path]
    flow = {}
    for fp in files:
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        for sec, items in (d.get("sector_flow") or {}).items():
            flow.setdefault(sec, []).extend(items or [])
    return flow


# ---- 字段解析（每板块） --------------------------------------------------------
def _norm(s):
    """板块名归一，便于跨源对齐（东财概念 vs 申万行业命名差异）。"""
    if not s:
        return ""
    for rep in ("概念", "Ⅱ", "Ⅲ", "II", "III", "（", "）", "(", ")", " "):
        s = s.replace(rep, "")
    return s.strip()


def get_chg(d, name):
    """板块实时涨跌幅(%)。取不到返回 None。"""
    sq = d.get("sector_quote") or {}
    for k, v in sq.items():
        if not isinstance(v, dict):
            continue
        if k == name or _norm(v.get("name")) == _norm(name) or _norm(k) == _norm(name):
            cp = v.get("change_percent", v.get("bd_zdf"))
            if cp is not None:
                try:
                    return float(cp)
                except (TypeError, ValueError):
                    pass
    for r in d.get("sector_rank") or []:
        if _norm(r.get("bd_name")) == _norm(name) or r.get("bd_code") == name:
            try:
                return float(r.get("bd_zdf"))
            except (TypeError, ValueError):
                return None
    return None


def get_net(d, flow, name):
    """板块实时主力净流入。返回 (值[亿元]或None, 符号[1/-1/None], 来源标签)。
    值为 None 但符号已知时 = 只能定方向不能定量（ranking 截断）。"""
    sn = d.get("sector_net") or {}
    for k, v in sn.items():
        if _norm(k) == _norm(name):
            try:
                fv = float(v)
                return fv, (1 if fv > 0 else -1 if fv < 0 else 0), "板块级实时净流入(直给)"
            except (TypeError, ValueError):
                pass
    for sec, items in flow.items():
        if _norm(sec) == _norm(name) and items:
            s = sum((x.get("MainNetFlow") or 0) for x in items) / 1e8
            return s, (1 if s > 0 else -1 if s < 0 else 0), f"成分股聚合(n={len(items)})"
    pr = d.get("plate_ranking") or {}

    def _pr_name(x):
        if isinstance(x, dict):
            return x.get("name"), x.get("code")
        return x, None

    for x in pr.get("top") or []:
        xn, xc = _pr_name(x)
        if xn is not None and (_norm(xn) == _norm(name) or xc == name):
            return None, 1, "ranking前3截断(仅符号)"
    for x in pr.get("bottom") or []:
        xn, xc = _pr_name(x)
        if xn is not None and (_norm(xn) == _norm(name) or xc == name):
            return None, -1, "ranking后3截断(仅符号)"
    return None, None, ""


def get_leader(d, name, db_leaders):
    """板块龙头实时行情。返回 (dict或None, 是否为T-1兜底)。"""
    sl = d.get("sector_leader") or {}
    for k, v in sl.items():
        if _norm(k) == _norm(name) and isinstance(v, dict):
            return v, False
    for r in d.get("sector_rank") or []:
        if _norm(r.get("bd_name")) == _norm(name) or r.get("bd_code") == name:
            if r.get("nzg_code"):
                try:
                    cp = float(r.get("nzg_zdf"))
                except (TypeError, ValueError):
                    cp = None
                return {"code": r["nzg_code"], "name": r.get("nzg_name"), "change_percent": cp}, False
    if name in db_leaders:
        return db_leaders[name], True
    return None, False


def _net_txt(net, sign):
    if net is not None:
        return f"主力净流入{net:+.2f}亿"
    if sign == 1:
        return "主力净流入为正(仅符号)"
    if sign == -1:
        return "主力净流出(仅符号)"
    return "净流入未知"


# ---- 阶段判定器 ----------------------------------------------------------------
def judge_open(name, chg, net, sign, net_src, leader, leader_stale):
    cond = "开盘主线资金延续: 板块主力净流入>0"
    if sign is None:
        return None, "无板块资金流数据, 无法判定", "需 sector_net 直给 或 成分股 data_fund_flow 聚合"
    met = sign > 0
    chg_txt = f", 板块涨{chg:+.2f}%" if chg is not None else ""
    return met, f"{_net_txt(net, sign)}{chg_txt}", net_src


def judge_morning(name, chg, net, sign, net_src, leader, leader_stale):
    cond = "龙头封板或涨幅>7%"
    if not leader:
        return None, "无龙头股数据, 无法判定", "需 sector_leader 或 sector_rank.nzg_*"
    if leader_stale:
        return None, f"仅有T-1龙头 {leader.get('name')}({leader.get('code')}), 无实时涨幅", "T-1兜底不可当实时判定, 需实时 quote"
    cp = leader.get("change_percent")
    if cp is None:
        return None, f"龙头 {leader.get('name')} 无实时涨幅", ""
    price, ceiling = leader.get("price"), leader.get("ceiling")
    sealed = price is not None and ceiling and ceiling > 0 and price >= ceiling * 0.999
    if sealed or cp > 7:
        return True, f"龙头 {leader.get('name')}({leader.get('code')}) 涨{cp:+.2f}%{' 封板' if sealed else ''}", ""
    return False, f"龙头 {leader.get('name')}({leader.get('code')}) 涨{cp:+.2f}%, 未封板且<=7%", ""


def judge_midday(name, chg, net, sign, net_src, leader, leader_stale):
    cond = "半日板块涨幅>0 且 净流入>0"
    if chg is None and sign is None:
        return None, "无板块行情与资金流数据", "需 sector_quote/sector_rank + sector_net"
    if chg is None:
        return None, f"{_net_txt(net, sign)}, 但无板块涨跌幅", "需 sector_quote 或 sector_rank"
    if sign is None:
        return None, f"板块涨{chg:+.2f}%, 但净流入未知", "需 sector_net 或成分股聚合"
    met = chg > 0 and sign > 0
    return met, f"板块涨{chg:+.2f}%, {_net_txt(net, sign)}", net_src


def judge_afternoon(name, chg, net, sign, net_src, leader, leader_stale):
    cond = "午后涨幅>1% 且 净流入>0"
    if chg is None:
        return None, "无板块行情数据", "需 sector_quote 或 sector_rank"
    if chg <= 1:
        return False, f"板块涨{chg:+.2f}% <= 1%", ""
    if sign is None:
        return None, f"板块涨{chg:+.2f}%>1% 但净流入未知", "需 sector_net 或成分股聚合"
    met = sign > 0
    return met, f"板块涨{chg:+.2f}%>1%, {_net_txt(net, sign)}", net_src


def judge_close(name, chg, net, sign, net_src, leader, leader_stale):
    cond = "尾盘主线净流入仍为正"
    if sign is None:
        return None, "无板块资金流数据, 无法判定", "需 sector_net 或成分股聚合"
    met = sign > 0
    tail = "仍为正" if sign > 0 else "已转负"
    chg_txt = f", 板块涨{chg:+.2f}%" if chg is not None else ""
    return met, f"{_net_txt(net, sign)} {tail}{chg_txt}", net_src


STAGE_COND = {
    "open": "开盘主线资金延续: 板块主力净流入>0",
    "morning": "龙头封板或涨幅>7%",
    "midday": "半日板块涨幅>0 且 净流入>0",
    "afternoon": "午后涨幅>1% 且 净流入>0",
    "close": "尾盘主线净流入仍为正",
}

STAGE_JUDGE = {
    "open": judge_open,
    "morning": judge_morning,
    "midday": judge_midday,
    "afternoon": judge_afternoon,
    "close": judge_close,
}


def judge_market_amount(d):
    """半日段附加：全市场成交额（三大指数近似）。"""
    idx = d.get("index_amount") or {}
    vals = [v for v in idx.values() if isinstance(v, (int, float))]
    cond = f"半日成交额>{MARKET_AMOUNT_THRESHOLD:.0f}亿"
    if not vals:
        return "全市场", cond, None, "无指数成交额数据", "需 index_amount(sh000001/sz399001/sz399006)"
    total_yi = sum(vals) / 1e8
    sh = (idx.get("sh000001") or 0) / 1e8
    sz = (idx.get("sz399001") or 0) / 1e8
    cy = (idx.get("sz399006") or 0) / 1e8
    actual = f"三大指数实时成交额累加≈{total_yi:.0f}亿 (上证{sh:.0f}/深证{sz:.0f}/创业板{cy:.0f})"
    note = "近似口径: 仅上证+深证+创业板三大指数实时 amount 累加, 非全市场; 且创业板与深证有重叠"
    return "全市场", cond, total_yi > MARKET_AMOUNT_THRESHOLD, actual, note


# ---- main ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", required=True, help="4位 HHMM，如 0930/1030/1130/1330/1430")
    ap.add_argument("--json", required=True, help="含 sector_quote/sector_rank/sector_net/sector_leader/index_amount/plate_ranking/watch_sectors")
    ap.add_argument("--fundflow", required=False, help="成分股资金流 JSON（文件或目录，含 sector_flow）")
    ap.add_argument("--sectors", required=False, help="逗号分隔的板块名，覆盖自动取 TOP")
    ap.add_argument("--top", type=int, default=5, help="自动取基准日 net_amount TOP N（默认5）")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--no-dedup", action="store_true", help="关闭板块成分重叠去重")
    ap.add_argument("--dedup-thr", type=float, default=0.5, help="重叠度合并阈值（并查集聚类，默认0.5）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tp = args.time.strip()
    if not re.fullmatch(r"\d{4}", tp):
        raise SystemExit(f"--time 必须是 4 位 HHMM，收到: {tp}")
    stage = stage_of(tp)

    d = load_json(args.json)
    flow = load_fundflow(args.fundflow) or (d.get("sector_flow") or {})

    c = get_conn()
    ensure_table(c)

    base_date = resolve_base_date(c, args.date)
    date_note = ""  # 仅当板块来自 sector_daily(T-1) 时才标注；实时/json 来源不误导

    # 板块来源
    if args.sectors:
        sectors = [s.strip() for s in args.sectors.split(",") if s.strip()]
        src = "--sectors 指定"
    elif d.get("watch_sectors"):
        sectors = list(d["watch_sectors"])
        src = "json.watch_sectors"
    elif base_date:
        rows = top_sectors_from_db(c, base_date, args.top)
        sectors = [r[0] for r in rows]
        src = f"sector_daily {base_date} net_amount TOP{args.top}"
        date_note = f"主线基准日={base_date}(T-1, sector_daily为盘后表)"
    else:
        sectors = []
        src = "无"

    merged = []
    if sectors and not args.no_dedup:
        sectors, merged = dedup_sectors(c, sectors, args.dedup_thr)

    print(f"[{tp}] stage={stage} ({STAGE_LABEL[stage]}) | 条件: {STAGE_COND[stage]}")
    print(f"  板块来源: {src}" + (f" | {date_note}" if date_note else ""))
    # 合并备注只贴到"被合并到"的那个板块行，不污染其他板块
    merge_note_by_sector = {}
    if merged:
        for a, b, ov in merged:
            print(f"  合并: {a} -> {b} (成分重叠 {ov:.0%}, 同一主线)")
            merge_note_by_sector.setdefault(b, []).append(a)
        merge_note_by_sector = {
            b: "已合并同主线: " + ",".join(f"{a}->{b}" for a in srcs)
            for b, srcs in merge_note_by_sector.items()
        }

    if not sectors and stage != "midday":
        print("  !! 无板块可判定，退出（未写库）")
        c.close()
        return

    db_leaders = db_leader_map(c, base_date, sectors) if base_date else {}
    judge = STAGE_JUDGE[stage]
    results = []

    for name in sectors:
        chg = get_chg(d, name)
        net, sign, net_src = get_net(d, flow, name)
        leader, leader_stale = get_leader(d, name, db_leaders)
        met, actual, judge_note = judge(name, chg, net, sign, net_src, leader, leader_stale)
        extra = []
        if leader_stale:
            extra.append("龙头为T-1兜底(无实时行情)")
        if date_note:
            extra.append(date_note)
        if merge_note_by_sector.get(name):
            extra.append(merge_note_by_sector[name])
        note = "; ".join(x for x in (judge_note, *extra) if x)
        results.append((name, STAGE_COND[stage], met, actual, note))

    if stage == "midday":
        results.append(judge_market_amount(d))

    met_str = {True: "满足", False: "不满足", None: "未知"}
    for name, cond, met, actual, note in results:
        print(f"  - {name:<10} [{met_str[met]}] {actual}")
        if note:
            print(f"      note: {note}")

    if args.dry_run:
        print("  (dry-run, 未写库)")
        c.close()
        return

    for name, cond, met, actual, note in results:
        c.execute(
            "INSERT OR REPLACE INTO intraday_watch_signal"
            "(date,time_point,sector,condition_text,met,actual,note) VALUES(?,?,?,?,?,?,?)",
            (args.date, tp, name, cond, met, actual, note),
        )
    c.commit()
    c.close()
    n_met = sum(1 for r in results if r[2] is True)
    n_unk = sum(1 for r in results if r[2] is None)
    print(f"  -> 已写入(UPSERT) {len(results)} 行 | 满足 {n_met} / 未知 {n_unk}")


if __name__ == "__main__":
    main()
