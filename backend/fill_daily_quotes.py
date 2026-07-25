# -*- coding: utf-8 -*-
"""
fill_daily_quotes.py — 个股日线东财兜底抓取（Data OS）

背景：
  stock_daily 个股日线历史上由 tdx_daily_import.py 从通达信 vipdoc 导入。
  沙箱/无通达信环境无 vipdoc，tdx_daily_import 直接跳过 → 新交易日个股行情进不来。
  本脚本用东财 push2delay 批量快照接口兜底，把指定交易日全 A 股 OHLCV+市值+换手
  抓回并 upsert 进 stock_daily，使日报/决策层在沙箱也能跑通。

数据源：push2delay.eastmoney.com/api/qt/clist/get
  字段：f12=代码 f14=名称 f2=最新价(收盘) f3=涨跌幅% f15=最高 f16=最低 f17=今开
        f5=成交量(手) f6=成交额(元) f20=总市值(元) f21=流通市值(元) f8=换手率(%)
  注：①主域 push2 被沙箱代理拦截，改用 push2delay 可直连；
      ②用 urllib 显式无代理 opener 强制不走系统死代理（同 fill_stock_flow）。

用法：
  python fill_daily_quotes.py                 # 抓今天
  python fill_daily_quotes.py 2026-07-21     # 抓指定交易日

说明：
  - 分页步长固定 100（push2delay 强制上限）。
  - amount 单位统一为亿元（÷1e8），volume 单位股（手×100），与既有 stock_daily 一致。
  - UPSERT（ON CONFLICT DO UPDATE）只更新价格/市值列，保留 high_20d 等技术列（tech_fill 回填）。
  - 北交所(8xx/92x) push2 不覆盖，保持缺省（流动性低，可接受）。
"""
from __future__ import annotations

import os
import sys
import time
import json
import sqlite3
import urllib.request
import urllib.parse
import datetime
from pathlib import Path

DB = str(Path(__file__).parent / "database" / "vibe_research.db")
PZ = 100
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
SOURCE = "eastmoney_push2"

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _clear_proxy():
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "no_proxy", "NO_PROXY"):
        os.environ.pop(k, None)


def _fetch_page(pn: int):
    """拉一页当日快照 → list[dict(f12,f14,f2,f3,f15,f16,f17,f5,f6,f20,f21,f8)]。"""
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"  # 沪A/深A/科创/创业
    fields = "f12,f14,f2,f3,f15,f16,f17,f5,f6,f20,f21,f8"
    url = (f"https://push2delay.eastmoney.com/api/qt/clist/get"
           f"?pn={pn}&pz={PZ}&po=1&np=1&fltt=2&invt=2&fid=f3"
           f"&fs={urllib.parse.quote(fs)}&fields={fields}")
    req = urllib.request.Request(url, headers=HEADERS)
    raw = _NO_PROXY_OPENER.open(req, timeout=TIMEOUT).read().decode("utf-8", "ignore")
    j = json.loads(raw)
    diff = (j.get("data") or {}).get("diff") or []
    out = []
    for it in diff:
        code = (it.get("f12") or "").strip()
        if not code:
            continue
        out.append({
            "code": code,
            "name": (it.get("f14") or "").strip(),
            "close": _f(it.get("f2")),
            "pct": _f(it.get("f3")),
            "high": _f(it.get("f15")),
            "low": _f(it.get("f16")),
            "open": _f(it.get("f17")),
            "vol_hand": _f(it.get("f5")),     # 手
            "amount_yuan": _f(it.get("f6")),  # 元
            "mcap_yuan": _f(it.get("f20")),   # 元
            "fcap_yuan": _f(it.get("f21")),   # 元
            "turnover": _f(it.get("f8")),     # %
        })
    return out


def _f(v):
    try:
        if v is None or v == "-":
            return None
        return float(v)
    except Exception:
        return None


def main():
    _clear_proxy()
    target = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    print(f"[fill_daily_quotes] target_date={target}")

    all_rows = []
    pn = 1
    while True:
        page = _fetch_page(pn)
        if not page:
            break
        all_rows.extend(page)
        if len(page) < PZ:
            break
        pn += 1
        time.sleep(0.08)
    print(f"[fill_daily_quotes] 抓到 {len(all_rows)} 只")

    con = sqlite3.connect(DB)
    cur = con.cursor()
    cnt = 0
    skipped = 0
    for it in all_rows:
        if it["close"] is None:
            skipped += 1
            continue
        vol = it["vol_hand"] * 100 if it["vol_hand"] is not None else None
        amount = it["amount_yuan"] / 1e8 if it["amount_yuan"] is not None else None
        mcap = it["mcap_yuan"] / 1e8 if it["mcap_yuan"] is not None else None
        fcap = it["fcap_yuan"] / 1e8 if it["fcap_yuan"] is not None else None
        # UPSERT：保留 high_20d 等技术列（由 tech_fill 回填），冲突时只更新价格/市值
        cur.execute(
            """INSERT INTO stock_daily
               (date,code,name,open,high,low,close,volume,amount,change_pct,
                turnover_rate,market_cap,float_cap,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(date,code) DO UPDATE SET
                 name=excluded.name, open=excluded.open, high=excluded.high,
                 low=excluded.low, close=excluded.close, volume=excluded.volume,
                 amount=excluded.amount, change_pct=excluded.change_pct,
                 turnover_rate=excluded.turnover_rate,
                 market_cap=excluded.market_cap, float_cap=excluded.float_cap""",
            (target, it["code"], it["name"], it["open"], it["high"], it["low"],
             it["close"], vol, amount, it["pct"], it["turnover"], mcap, fcap,
             time.time()),
        )
        cnt += 1
    con.commit()
    con.close()
    print(f"[fill_daily_quotes] upserted {cnt} 行 (跳过 {skipped} 只无收盘价)")
    return cnt


if __name__ == "__main__":
    main()
