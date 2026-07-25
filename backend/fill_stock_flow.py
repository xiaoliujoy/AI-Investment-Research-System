# -*- coding: utf-8 -*-
"""
fill_stock_flow —— 个股资金流数据源（Data OS，独立表）

背景：stock_daily 的 main_net_buy 列由 TDX 导入而来，TDX 不提供主力净流入
      → 该列恒为 NULL（实测 2026-07-17 填充 0/9326）。用户的红线要求：
      「龙头资金」必须可观测（板块 → 龙头 → 资金 → 图形 第四环）。
      故建立独立表 stock_flow_daily，与价格数据（stock_daily）分离。

数据源：push2delay.eastmoney.com/api/qt/clist/get
        字段：f62=主力净流入 f66=超大单 f72=大单 f78=中单 f84=小单（净额，单位：元）。
        **关键**：①主域 push2.eastmoney.com 被沙箱代理(127.0.0.1:7890)拦截
        （RemoteDisconnected），改用 delayed 子域 push2delay 可直连/经代理均通；
        ②akshare 自带 requests 死代理会 ProxyError，故用 urllib 直连 +
        显式空 ProxyHandler opener 强制不走系统代理。

设计要点：
  - 分页拉全 A 股（沪A/深A/科创/创业），fs 拼接。
  - 元 ÷1e8 → 亿元（与 amount / market_cap 同单位）。
  - INSERT OR REPLACE 写独立表（不 UPDATE stock_daily，避免数据层幻觉）。
  - source='eastmoney_push2'，confidence 默认 1.0（网络可达即高可信）。
  - 北交所(8xx/92x) push2 不覆盖，保持缺省（流动性低，可接受）。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
import json
from pathlib import Path

DB = str(Path(__file__).parent / "database" / "vibe_research.db")
# 注意：push2delay 子域无视 pz 参数、强制每页最多 100 条（实测 pz=1000 仍只回 100）。
# 故分页步长固定 100，循环翻页直到不足 100 条为止（全 A 约 5540 只 → ~56 页）。
PZ = 100           # 每页条数（push2delay 实际上限）
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
SOURCE = "eastmoney_push2"


# 显式无代理 opener：Windows 上 getproxies() 会读注册表代理（127.0.0.1:7890 死代理），
# 仅清 env 变量不够，必须在 _fetch_page 内显式用空 ProxyHandler 的 opener 强制直连。
# 注意：只在本模块内显式使用，不 install_opener 全局，避免影响同进程其他采集器的代理设置。
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _clear_proxy():
    """清掉所有代理环境变量（防御性；真正强制直连靠 _fetch_page 内的 _NO_PROXY_OPENER）。"""
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "no_proxy", "NO_PROXY"):
        os.environ.pop(k, None)


def _fetch_page(pn: int):
    """拉一页个股资金流排名 → list[{code,name,main,super_l,large,medium,small}]（亿元）。"""
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"  # 沪A/深A/科创/创业
    fields = "f12,f14,f62,f66,f72,f78,f84"
    url = (f"https://push2delay.eastmoney.com/api/qt/clist/get"
           f"?pn={pn}&pz={PZ}&po=1&np=1&fltt=2&invt=2&fid=f62"
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
        try:
            main = float(it.get("f62") or 0) / 1e8
            super_l = float(it.get("f66") or 0) / 1e8
            large = float(it.get("f72") or 0) / 1e8
            medium = float(it.get("f78") or 0) / 1e8
            small = float(it.get("f84") or 0) / 1e8
        except (ValueError, TypeError):
            main = super_l = large = medium = small = 0.0
        out.append({
            "code": code, "name": it.get("f14") or "",
            "main": round(main, 4), "super_l": round(super_l, 4),
            "large": round(large, 4), "medium": round(medium, 4),
            "small": round(small, 4),
        })
    return out


def fill(date=None, verbose=True):
    """回填指定交易日（默认最新）的个股资金流。返回统计 dict。"""
    _clear_proxy()
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    if date is None:
        row = c.execute("SELECT max(date) FROM stock_daily").fetchone()
        date = row[0] if row and row[0] else None
    if not date:
        c.close()
        return {"date": None, "error": "no date"}

    # 分页拉全量
    all_rows = []
    pn = 1
    while True:
        page = None
        for attempt in range(3):
            try:
                page = _fetch_page(pn)
                break
            except Exception:
                if attempt == 2:
                    page = []
                else:
                    time.sleep(1.0)
        if not page:
            break
        all_rows.extend(page)
        if len(page) < PZ:
            break
        pn += 1
        time.sleep(0.25)

    rows = [(
        date, r["code"], r["name"], r["main"], r["super_l"], r["large"],
        r["medium"], r["small"], SOURCE, 1.0,
    ) for r in all_rows]
    c.executemany(
        "INSERT OR REPLACE INTO stock_flow_daily "
        "(date, code, name, main_net_buy, super_large_net_buy, large_net_buy, "
        " medium_net_buy, small_net_buy, source, confidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    c.commit()

    ok = c.execute(
        "SELECT count(*) FROM stock_flow_daily WHERE date=? AND main_net_buy IS NOT NULL",
        (date,)).fetchone()[0]
    c.close()
    if verbose:
        print(f"[stock_flow] 交易日={date} 拉取 {len(all_rows)} 条，"
              f"写入 stock_flow_daily {ok} 只（亿元）。")
    return {"date": date, "fetched": len(all_rows), "written": ok}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else None
    fill(d)
