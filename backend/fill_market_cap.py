# -*- coding: utf-8 -*-
"""
fill_market_cap —— 市值数据源（Data OS）。

背景：stock_daily 表已有 market_cap / float_cap 字段但全为 NULL。
      本模块用腾讯 gtimg 批量接口回填【总市值 / 流通市值】（单位：亿元），
      让候选表可标注"市值区间"，辅助用户人工做市值过滤（守边界：仅提示不硬筛）。

数据源：qt.gtimg.cn（本沙箱实测可达）。字段：
    f[44] = 流通市值(亿)   f[45] = 总市值(亿)

注意：gtimg 返回的是【当前/最新】市值快照（非历史某日精确值）。市值日间变化很小，
      用作"市值区间"人工过滤提示完全够用；写入最新交易日的行。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

DB = str(Path(__file__).parent / "database" / "vibe_research.db")
BATCH = 60
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}


def _clear_proxy():
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(k, None)


def _prefix(code: str) -> str:
    """A股代码 → gtimg 市场前缀。"""
    if code.startswith("6") or code[:2] in ("11", "50", "51", "56", "58"):
        return "sh"
    if code[0] in ("0", "3") or code[:2] in ("12", "15", "16", "18"):
        return "sz"
    if code[0] in ("4", "8") or code.startswith("920"):
        return "bj"
    return "sh"


def _fetch_batch(codes):
    """查一批代码 → {code: (total_mv, float_mv)}（亿元）。"""
    q = ",".join(_prefix(c) + c for c in codes)
    url = "https://qt.gtimg.cn/q=" + q
    req = urllib.request.Request(url, headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "ignore")
    out = {}
    for line in raw.strip().split("\n"):
        if "=" not in line:
            continue
        body = line.split("=", 1)[1].strip().strip(";").strip('"')
        f = body.split("~")
        if len(f) < 46:
            continue
        code = f[2]
        try:
            float_mv = float(f[44]) if f[44] else None
        except ValueError:
            float_mv = None
        try:
            total_mv = float(f[45]) if f[45] else None
        except ValueError:
            total_mv = None
        if total_mv or float_mv:
            out[code] = (total_mv, float_mv)
    return out


def fill(date=None, verbose=True):
    """回填指定交易日（默认最新）的市值。返回 {date, total, updated, failed}。"""
    _clear_proxy()
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")  # 等待锁而非直接报错
    if date is None:
        # 选最近的"完整交易日"（行数>1000），避开 step1 实时接口插入的极少量最新日
        row = c.execute("""SELECT date FROM stock_daily GROUP BY date
                           HAVING count(*) > 1000 ORDER BY date DESC LIMIT 1""").fetchone()
        date = row[0] if row else c.execute("SELECT max(date) FROM stock_daily").fetchone()[0]
    codes = [r[0] for r in c.execute(
        "SELECT code FROM stock_daily WHERE date=? ORDER BY code", (date,)).fetchall()]
    # 只回填 A 股个股主体：沪(6)/深(0)/创业(3)/北交(83/87/920)。
    # 排除 88x/880x（通达信板块指数伪代码）、11/12(可转债)、5/15/16(ETF/基金) 等非个股。
    def _is_stock(x):
        if x.startswith(("11", "12", "13", "15", "16", "18", "88", "5")):
            return False
        return x[0] in ("6", "0", "3") or x.startswith(("83", "87", "920"))
    stock_codes = [x for x in codes if _is_stock(x)]
    if verbose:
        print(f"[market_cap] 交易日={date} 待回填个股={len(stock_codes)}（总行={len(codes)}）")

    updated = 0
    failed_batches = 0
    for i in range(0, len(stock_codes), BATCH):
        chunk = stock_codes[i:i + BATCH]
        for attempt in range(3):
            try:
                mp = _fetch_batch(chunk)
                break
            except Exception as e:
                if attempt == 2:
                    failed_batches += 1
                    mp = {}
                    if verbose:
                        print(f"  批次 {i}-{i+len(chunk)} 失败：{type(e).__name__}")
                else:
                    time.sleep(1.2)
        for code, (tmv, fmv) in mp.items():
            c.execute("UPDATE stock_daily SET market_cap=?, float_cap=? "
                      "WHERE date=? AND code=?", (tmv, fmv, date, code))
            updated += 1
        c.commit()
        if verbose and (i // BATCH) % 10 == 0:
            print(f"  进度 {min(i+BATCH, len(stock_codes))}/{len(stock_codes)}  已更新 {updated}")
        time.sleep(0.15)  # 温柔限频

    # 校验
    ok = c.execute("SELECT count(*) FROM stock_daily WHERE date=? AND market_cap>0",
                   (date,)).fetchone()[0]
    c.close()
    if verbose:
        print(f"[market_cap] 完成：更新 {updated} 只，当日 market_cap>0 = {ok}，失败批次 {failed_batches}")
    return {"date": date, "total": len(stock_codes),
            "updated": updated, "ok": ok, "failed_batches": failed_batches}


def cap_bucket(total_mv):
    """总市值(亿) → 市值区间标签（供候选表人工过滤提示）。"""
    if total_mv is None:
        return "—"
    if total_mv < 50:
        return "微盘(<50亿)"
    if total_mv < 100:
        return "小盘(50-100亿)"
    if total_mv < 300:
        return "中小盘(100-300亿)"
    if total_mv < 1000:
        return "中大盘(300-1000亿)"
    return "大盘(>1000亿)"


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else None
    fill(d)
