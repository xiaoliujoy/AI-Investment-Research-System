# -*- coding: utf-8 -*-
"""
commodity_engine/collector.py —— 商品期货日线采集器（Commodity OS Phase 0）

职责（与 A股流水线解耦，独立模块）：
  1. ensure_schema()          建 4 张表（commodity_daily / commodity_factor_daily /
                              commodity_symbol_map / commodity_supply_daily）
  2. init_symbol_map()        初始化 commodity_symbol_map 元数据
  3. fetch_inner_history(sym) 新浪内盘主力连续全历史（含 OI/结算）
  4. fetch_foreign_history(sym) akshare 外盘历史（GC/CL/HG）
  5. ensure_commodity_daily() 增量追加：每个 symbol 只写「比已存最大日期更新的行」；
                              首次运行或行数明显不足时全量回填（自愈）。
  6. 外盘同步回写 global_history 的 XAU/CL/HG（补全跨资产看板缺口）

数据源（沙箱实测 2026-07-29 可用）：
  - 内盘：ak.futures_zh_daily_sina(symbol="AU0"...) → date/open/high/low/close/volume/hold/settle
  - 外盘：ak.futures_foreign_hist(symbol="GC"...)   → date/open/high/low/close/volume/position/s/settlement
  不用东财（沙箱封）。外盘 volume/position 历史恒为 0（akshare 限制），按原样落库。

幂等：所有写入均为 INSERT OR REPLACE，主键 (date, symbol)。

用法：
  python commodity_engine/collector.py            # 全量/增量采集全部品种
  python commodity_engine/collector.py --symbol AU0   # 只采单个品种
"""
from __future__ import annotations

import os
import sys
import json
import time
import datetime
import argparse

# 保证 backend 在 sys.path，便于 from database.models import get_db
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from database.models import get_db  # noqa: E402
try:
    from commodity_engine import symbol_map  # 作为包被导入时（daily_collect）
except Exception:
    import symbol_map  # 作为脚本直接运行时（cwd=backend/commodity_engine）

# 行数低于此阈值视为「历史残缺」，触发该 symbol 全量重填（内盘/外盘均 >2000 行）
_MIN_ROWS_FOR_INCREMENTAL = 500


# =============================================================================
# Schema
# =============================================================================
def ensure_schema():
    """建 Commodity OS 全部表（幂等）。"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commodity_daily (
            date            TEXT,
            symbol          TEXT,
            name            TEXT,
            market          TEXT,
            category        TEXT,
            close           REAL,
            change_pct      REAL,
            volume          REAL,
            open_interest   REAL,
            settlement      REAL,
            main_contract   TEXT,
            source          TEXT,
            PRIMARY KEY (date, symbol)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commodity_factor_daily (
            date             TEXT,
            symbol           TEXT,
            name             TEXT,
            category         TEXT,
            macro_score      REAL,
            cycle_score      REAL,
            fund_score       REAL,
            technical_score  REAL,
            risk_score       REAL,
            total_score      REAL,
            stage            TEXT,
            analysis         TEXT,
            PRIMARY KEY (date, symbol)
        )""")
    # 兼容已存在（本会话早先建过无 risk_score）的表
    try:
        conn.execute("ALTER TABLE commodity_factor_daily ADD COLUMN risk_score REAL")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commodity_symbol_map (
            symbol         TEXT PRIMARY KEY,
            name           TEXT,
            market         TEXT,
            category       TEXT,
            em_link        TEXT,
            inner_symbol   TEXT,
            foreign_symbol TEXT,
            global_symbol  TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commodity_supply_daily (
            date        TEXT,
            symbol      TEXT,
            inventory   REAL,
            production  REAL,
            consumption REAL,
            source      TEXT,
            PRIMARY KEY (date, symbol)
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_commodity_daily_symbol ON commodity_daily(symbol, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_commodity_daily_date ON commodity_daily(date)")
    conn.commit()
    conn.close()


def init_symbol_map():
    """写入 commodity_symbol_map 元数据（幂等）。"""
    conn = get_db()
    for m in symbol_map.all_symbols():
        conn.execute("""
            INSERT OR REPLACE INTO commodity_symbol_map
                (symbol, name, market, category, em_link, inner_symbol, foreign_symbol, global_symbol)
            VALUES (?,?,?,?,?,?,?,?)
        """, (m["symbol"], m["name"], m["market"], m["category"], m["em_link"],
              m["inner_symbol"], m["foreign_symbol"], m["global_symbol"]))
    conn.commit()
    conn.close()


# =============================================================================
# 工具
# =============================================================================
def _change_pct_from_closes(pairs):
    """pairs: list of (date, close) 已按日期升序。返回 {date: change_pct}。"""
    out = {}
    prev = None
    for d, c in pairs:
        if prev is None or not prev:
            out[d] = None
        else:
            out[d] = round((c / prev - 1) * 100, 4) if prev else None
        prev = c
    return out


def _stored_max_date(symbol: str):
    conn = get_db()
    r = conn.execute("SELECT MAX(date) FROM commodity_daily WHERE symbol=?", (symbol,)).fetchone()
    conn.close()
    return r[0] if r else None


def _stored_count(symbol: str):
    conn = get_db()
    r = conn.execute("SELECT COUNT(*) FROM commodity_daily WHERE symbol=?", (symbol,)).fetchone()
    conn.close()
    return r[0] if r else 0


# =============================================================================
# 采集（akshare）
# =============================================================================
def fetch_inner_history(symbol: str) -> list[dict]:
    """新浪内盘主力连续全历史。symbol 如 'AU0'。返回 commodity_daily 行（去 change_pct）。"""
    import akshare as ak
    df = ak.futures_zh_daily_sina(symbol=symbol)
    if df is None or len(df) == 0:
        return []
    pairs = []
    for _, row in df.iterrows():
        d = str(row["date"])[:10]
        try:
            c = float(row["close"])
        except Exception:
            continue
        pairs.append((d, c))
    pairs.sort(key=lambda x: x[0])
    cps = _change_pct_from_closes(pairs)
    meta = symbol_map.INNER[symbol]
    rows = []
    for _, row in df.iterrows():
        d = str(row["date"])[:10]
        try:
            close = float(row["close"])
        except Exception:
            continue
        rows.append({
            "date": d,
            "symbol": symbol,
            "name": meta["name"],
            "market": "内盘",
            "category": meta["category"],
            "close": close,
            "change_pct": cps.get(d),
            "volume": _f(row.get("volume")),
            "open_interest": _f(row.get("hold")),
            "settlement": _f(row.get("settle")),
            "main_contract": symbol,
            "source": "futures_zh_daily_sina",
        })
    return rows


def fetch_foreign_history(symbol: str) -> list[dict]:
    """akshare 外盘历史。symbol 如 'GC'/'CL'/'HG'。返回 commodity_daily 行。"""
    import akshare as ak
    df = ak.futures_foreign_hist(symbol=symbol)
    if df is None or len(df) == 0:
        return []
    pairs = []
    for _, row in df.iterrows():
        d = str(row["date"])[:10]
        try:
            c = float(row["close"])
        except Exception:
            continue
        pairs.append((d, c))
    pairs.sort(key=lambda x: x[0])
    cps = _change_pct_from_closes(pairs)
    meta = symbol_map.FOREIGN[symbol]
    rows = []
    for _, row in df.iterrows():
        d = str(row["date"])[:10]
        try:
            close = float(row["close"])
        except Exception:
            continue
        rows.append({
            "date": d,
            "symbol": symbol,
            "name": meta["name"],
            "market": "外盘",
            "category": meta["category"],
            "close": close,
            "change_pct": cps.get(d),
            "volume": _f(row.get("volume")),
            "open_interest": _f(row.get("position")),  # 外盘持仓量(position)
            "settlement": _f(row.get("settlement")),
            "main_contract": symbol,
            "source": "futures_foreign_hist",
        })
    return rows


def _f(v):
    try:
        if v is None or v == "" or v == "None":
            return None
        return float(v)
    except Exception:
        return None


# =============================================================================
# 写入
# =============================================================================
def save_commodity_rows(rows: list[dict]):
    if not rows:
        return 0
    cols = ["date", "symbol", "name", "market", "category", "close", "change_pct",
            "volume", "open_interest", "settlement", "main_contract", "source"]
    conn = get_db()
    conn.executemany(
        f"INSERT OR REPLACE INTO commodity_daily ({','.join(cols)}) "
        f"VALUES ({','.join(['?']*len(cols))})",
        [[r.get(c) for c in cols] for r in rows])
    conn.commit()
    conn.close()
    return len(rows)


def backfill_global_history(foreign_rows: list[dict]):
    """把外盘行回写 global_history（XAU/CL/HG）。幂等 INSERT OR REPLACE。"""
    if not foreign_rows:
        return 0
    # 按 symbol 分组
    by_sym = {}
    for r in foreign_rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    conn = get_db()
    n = 0
    for sym, rows in by_sym.items():
        gsym = symbol_map.FOREIGN_TO_GLOBAL.get(sym)
        if not gsym:
            continue
        gname = symbol_map.GLOBAL_NAME.get(gsym, sym)
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO global_history (date, symbol, name, close, change_pct) "
                "VALUES (?,?,?,?,?)",
                (r["date"], gsym, gname, r["close"], r["change_pct"]))
            n += 1
    conn.commit()
    conn.close()
    return n


# =============================================================================
# 对外入口
# =============================================================================
def ensure_commodity_daily(symbol_filter: list[str] | None = None) -> dict:
    """增量追加商品日线（自愈：首次/残缺则全量）。

    返回每个品种的结果摘要。
    """
    ensure_schema()
    init_symbol_map()

    symbols = symbol_map.all_symbols()
    if symbol_filter:
        fs = set(symbol_filter)
        symbols = [s for s in symbols if s["symbol"] in fs]

    summary = {}
    for m in symbols:
        sym = m["symbol"]
        market = m["market"]
        try:
            if market == "内盘":
                hist = fetch_inner_history(sym)
            else:
                hist = fetch_foreign_history(sym)
        except Exception as e:
            summary[sym] = {"ok": False, "note": f"fetch error: {type(e).__name__}: {str(e)[:120]}"}
            continue
        if not hist:
            summary[sym] = {"ok": False, "note": "empty history"}
            continue

        stored_max = _stored_max_date(sym)
        stored_cnt = _stored_count(sym)
        if stored_max is None or stored_cnt < _MIN_ROWS_FOR_INCREMENTAL:
            new_rows = hist  # 全量回填（首次或残缺）
            mode = "full"
        else:
            new_rows = [r for r in hist if r["date"] > stored_max]
            mode = "incremental"
        saved = save_commodity_rows(new_rows)
        # 外盘回写 global_history
        gh_n = 0
        if market == "外盘":
            gh_n = backfill_global_history(new_rows)
        summary[sym] = {
            "ok": True, "mode": mode,
            "fetched": len(hist), "saved": saved,
            "stored_total": stored_cnt + saved,
            "latest": hist[-1]["date"] if hist else None,
            "global_history_written": gh_n,
        }
    return summary


def collect_and_save(symbol_filter: list[str] | None = None) -> dict:
    """对外总入口：建表 + 采集 + 回写。"""
    return ensure_commodity_daily(symbol_filter=symbol_filter)


def get_commodity_latest() -> list[dict]:
    """读取每个 symbol 最新一行（供 CIO / 日报消费）。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT c.* FROM commodity_daily c
        JOIN (SELECT symbol, MAX(date) md FROM commodity_daily GROUP BY symbol) t
        ON c.symbol = t.symbol AND c.date = t.md
        ORDER BY market, category, symbol
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="商品期货日线采集（Commodity Engine Phase 0）")
    ap.add_argument("--symbol", help="只采集单个品种，如 AU0 / GC")
    args = ap.parse_args()
    t0 = datetime.datetime.now()
    filt = [args.symbol] if args.symbol else None
    summ = collect_and_save(symbol_filter=filt)
    # 打印摘要
    print(f"\n=== Commodity Engine 采集摘要 ({datetime.datetime.now().isoformat(timespec='seconds')}) ===")
    for sym, info in summ.items():
        if info.get("ok"):
            print(f"  {sym:4s} ✅ {info['mode']:12s} 存{info['stored_total']:>5d}行 "
                  f"本次+{info['saved']:<5d} 最新{info['latest']} "
                  f"global_history+{info.get('global_history_written',0)}")
        else:
            print(f"  {sym:4s} ❌ {info.get('note','')}")
    # 最新快照
    print("\n--- 最新日线快照 ---")
    for r in get_commodity_latest():
        cp = r["change_pct"]
        cp_s = f"{cp:+.2f}%" if cp is not None else "  n/a"
        print(f"  [{r['market']}] {r['symbol']:4s} {r['name']:8s} 收{r['close']:>10.2f} "
              f"{cp_s:>8s} OI={r['open_interest']} 结算={r['settlement']} ({r['date']})")
    elapsed = round((datetime.datetime.now() - t0).total_seconds(), 1)
    print(f"\n耗时 {elapsed}s")
