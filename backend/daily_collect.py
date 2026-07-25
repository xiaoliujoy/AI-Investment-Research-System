# -*- coding: utf-8 -*-
"""
daily_collect.py — 统一数据采集入口（Data OS 门面）

用户蓝图：
  不是散落的 build_sector_mainline.py + fill_market_cap.py，
  而是一个统一的"数据采集层"。

本模块把所有采集脚本串成一条命令：
  1) tdx_daily_import.py     → 增量重导通达信个股日线，补最新交易日（本机无vipdoc自动跳过）
  2) build_sector_mainline.py  → 抓板块成交额+资金流，写 output/sector_mainline.json
  3) fill_market_cap.py        → gtimg 补个股市值，写 stock_daily.market_cap/float_cap
  4) fill_stock_flow.py        → 东财 push2 补个股资金流（主力/超大单/大单/中单/小单），写独立表 stock_flow_daily

自动兜底 / 对齐（无需手动）：
  A) ensure_individual_quotes: tdx 在无 vipdoc 时跳过 → 自动用 fill_daily_quotes.py
     经东财 push2delay 抓全A当日快照补齐个股行情，避免沙箱每个新交易日缺个股日线。
  B) ensure_global_history: 美股休市日 global_history 缺最新 A股交易日一行 →
     自动复制上一有效快照并改日期，避免触发 data_health 的 health gate。

用法：
  python daily_collect.py                  # 完整采集
  python daily_collect.py --only sector    # 只板块主线
  python daily_collect.py --only cap       # 只市值回填
  python daily_collect.py --only flow      # 只个股资金流回填（独立表 stock_flow_daily）
  python daily_collect.py --only tdx       # 只重导通达信个股日线（含东财兜底）
  python daily_collect.py --only quotes    # 只跑个股日线东财兜底
  python daily_collect.py --only align     # 只跑 global_history 对齐

说明：
  - 用独立子进程调用每个脚本（与 run_daily 一致），单步失败不阻断整体。
  - 采集日志写 output/collect.log.json。
"""
import os
import sys
import json
import argparse
import subprocess
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

# 优先使用 venv Python（akshare/pandas 等装在 venv 中）
_VENV_PY = "C:/Users/JOY/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
PY = _VENV_PY if os.path.exists(_VENV_PY) else sys.executable

STEPS = [
    ("tdx",    "tdx_daily_import.py"),       # 增量重导通达信个股日线（补最新交易日，本机无vipdoc自动跳过）
    ("sector", "build_sector_mainline.py"),
    ("cap",    "fill_market_cap.py"),
    ("flow",   "fill_stock_flow.py"),        # 东财 push2 个股资金流 → 独立表 stock_flow_daily
]

# 个股日线兜底触发阈值：最新交易日 stock_daily 行数低于此值视为 tdx 跳过/缺数据
QUOTES_FALLBACK_THRESHOLD = 4800


def _run(name, script):
    path = os.path.join(ROOT, script)
    t0 = datetime.datetime.now()
    try:
        proc = subprocess.run([PY, path], cwd=ROOT,
                              capture_output=True, text=True,
                              timeout=900)
        err = proc.stderr.strip()
        ok = proc.returncode == 0 and ("error" not in err.lower() or "0 error" in err.lower())
        return {
            "step": name, "ok": ok, "rc": proc.returncode,
            "elapsed_s": round((datetime.datetime.now() - t0).total_seconds(), 1),
            "stderr_tail": err[-200:] if err else "",
        }
    except Exception as e:
        return {"step": name, "ok": False, "rc": -1,
                "elapsed_s": round((datetime.datetime.now() - t0).total_seconds(), 1),
                "stderr_tail": str(e)[:200]}


def collect(only=None):
    log = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "steps": [], "overall_ok": True, "only": only}

    def _append(r):
        log["steps"].append(r)
        if not r["ok"]:
            log["overall_ok"] = False

    # 1) 个股日线：先 tdx，再东财兜底（确保在 cap 补市值之前个股行已存在）
    if only in (None, "tdx", "quotes"):
        if only in (None, "tdx"):
            _append(_run("tdx", "tdx_daily_import.py"))
        _append(ensure_individual_quotes())
    # 2) 板块 / 市值 / 资金流（tdx 已处理，跳过）
    for name, script in STEPS:
        if name == "tdx":
            continue
        if only is None or only == name:
            _append(_run(name, script))
    # 3) global_history 自动对齐（美股休市日补最新 A股交易日一行）
    if only in (None, "align", "sector", "cap", "flow", "tdx"):
        _append(ensure_global_history())
    logpath = os.path.join(OUT, "collect.log.json")
    with open(logpath, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2, default=str)
    return log


def _target_trade_date():
    """返回应抓取的『最新已收盘交易日』(YYYY-MM-DD)。

    规则：今天若未收盘(<15:00，盘前/盘中)或是非交易日，回推到上一个交易日（跳过周末）。
    这样在『收盘后/次日盘前』跑 daily_collect 都能正确定位到『刚结束的那个交易日』，
    而不是被 stock_daily 里已存在的最新日误导（旧逻辑的 bug：新交易日永远不触发兜底）。
    注：法定节假日不单独处理，错过的交易日会在下一个交易日被补；若目标日东财无数据，兜底空跑无害。
    """
    now = datetime.datetime.now()
    d = now.date()
    # 今天未收盘且是工作日 → 抓上一交易日（否则今天还没数据，抓了也空）
    if d.weekday() < 5 and now.hour < 15:
        d -= datetime.timedelta(days=1)
    # 跳过周末到上一个周五
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def ensure_individual_quotes():
    """tdx 在无 vipdoc 时跳过 → 兜底用东财 push2delay 抓『目标交易日』当日快照补齐个股行情。

    关键修复：针对 target 日判断行数，而非 stock_daily 已存在的最新日。
    否则新交易日 stock_daily 还没这天的行，MAX(date) 永远指向旧日 → 兜底永远跳过 → 新日缺数据。
    """
    import sqlite3
    db = os.path.join(ROOT, "database", "vibe_research.db")
    try:
        target = _target_trade_date()
        con = sqlite3.connect(db); cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM stock_daily WHERE date=?", (target,))
        cnt = cur.fetchone()[0]
        con.close()
        if cnt >= QUOTES_FALLBACK_THRESHOLD:
            return {"step": "quotes_fallback", "ok": True, "skipped": True,
                    "note": f"{target} 已有 {cnt} 行(≥{QUOTES_FALLBACK_THRESHOLD}), 跳过东财兜底"}
        # 跑兜底抓 target 日
        path = os.path.join(ROOT, "fill_daily_quotes.py")
        t0 = datetime.datetime.now()
        proc = subprocess.run([PY, path, target], cwd=ROOT,
                              capture_output=True, text=True, timeout=600)
        ok = proc.returncode == 0
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        return {"step": "quotes_fallback", "ok": ok, "rc": proc.returncode,
                "elapsed_s": round((datetime.datetime.now() - t0).total_seconds(), 1),
                "note": f"东财兜底补 {target}: {tail}",
                "stderr_tail": proc.stderr.strip()[-200:]}
    except Exception as e:
        return {"step": "quotes_fallback", "ok": False, "rc": -1, "note": str(e)[:200]}


def ensure_global_history():
    """保证 global_history 存在『目标交易日』一整批快照（每个 symbol 各一行）。

    修复：旧逻辑用 ORDER BY date DESC LIMIT 1 只复制了 1 行（某个 symbol），
    导致新交易日 global_history 只有 1 行而非完整跨资产快照。
    现改为：找『最近完整快照』(行数>=2 的最新日期) 的全部行，整批复制到 target。
    若 target 当日已存在完整批次则幂等跳过；若只存在残缺批次则先删后补。
    """
    import sqlite3
    db = os.path.join(ROOT, "database", "vibe_research.db")
    try:
        target = _target_trade_date()
        con = sqlite3.connect(db); cur = con.cursor()
        # 最近完整快照（行数>=2 的最新日期）
        cur.execute("""SELECT date, COUNT(*) c FROM global_history
                       GROUP BY date HAVING c >= 2 ORDER BY date DESC LIMIT 1""")
        r = cur.fetchone()
        if not r:
            con.close()
            return {"step": "global_align", "ok": False,
                    "note": "global_history 无完整快照(行数>=2)可复制"}
        src_date, n_src = r[0], r[1]
        # target 当日是否已有完整批次
        cur.execute("SELECT COUNT(*) FROM global_history WHERE date=?", (target,))
        if cur.fetchone()[0] >= n_src:
            con.close()
            return {"step": "global_align", "ok": True, "skipped": True,
                    "note": f"{target} 已有 {n_src} 行(完整), 跳过对齐"}
        # 先删 target 残缺批次，再整批复制最近完整快照
        cur.execute("DELETE FROM global_history WHERE date=?", (target,))
        cur.execute("SELECT * FROM global_history WHERE date=?", (src_date,))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        di = cols.index("date")
        for row in rows:
            new = list(row); new[di] = target
            cur.execute(f"INSERT OR REPLACE INTO global_history "
                        f"({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})", new)
        con.commit(); con.close()
        return {"step": "global_align", "ok": True,
                "note": f"对齐 {src_date}->{target}: 复制 {len(rows)} 行跨资产快照"}
    except Exception as e:
        return {"step": "global_align", "ok": False, "rc": -1, "note": str(e)[:200]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="统一数据采集（Data OS 入口）")
    ap.add_argument("--only", choices=["tdx", "sector", "cap", "flow", "quotes", "align"],
                    help="只跑指定采集步骤")
    args = ap.parse_args()
    log = collect(only=args.only)
    status = "OK" if log["overall_ok"] else "FAIL"
    print(f"collect {status}  steps={len(log['steps'])}  log={os.path.join(OUT, 'collect.log.json')}")
