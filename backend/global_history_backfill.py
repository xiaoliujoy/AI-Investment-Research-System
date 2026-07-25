# -*- coding: utf-8 -*-
"""
global_history_backfill.py —— 跨市场历史回填（打通韩股/纳指/商品）

为什么需要：relationship_engine 要算 KOSPI↔科创50 这类跨市场相关性，
但本地只有 A 股历史；global_market_daily 仅是 20 行快照，无历史序列。
本模块把境外指数/商品日线回填进新表 `global_history`，使跨市场 AUTO
关系可得以计算，用户假设（OBS-KOSPI-KC50）从 TRACKING 升级为已验证数字。

数据来源（多源顺序兜底，第一个成功即止）：
  - akshare（可达）：美债2Y/10Y（bond_zh_us_rate），沙箱与本机均可用，无限制
  - Binance（可达）：BTC 现货 K 线，免费无 rate limit，极可靠
  - Yahoo chart REST（主源）：NDX/SOXX/HSTECH/DXY/TIPS 等；直接打 chart 接口
        （单请求+间隔+crumb，比 yfinance 库抗 429）；候选 ticker 依次尝试
  - Stooq（兜底）：曾为免费主源，现对程序化 CSV 请求返回 HTML 拦截页，退为最后兜底
  - Sina（可达）：韩国KOSPI / 台湾加权 / 日经225 等股指期货指数
  - 离线兜底：--csv 直接灌入（date,symbol,close 或 date,symbol,change_pct）

用法：
  python global_history_backfill.py            # 尝试拉取所有已配置符号
  python global_history_backfill.py --csv data/kospi.csv   # 离线灌入
  python global_history_backfill.py --symbol KS11         # 只拉单个

说明：本脚本依赖 akshare，应在装有 akshare 的 venv 下运行
（与 run_daily.py 的 _VENV_PY 一致）。
"""
from __future__ import annotations
import os
import sys
import csv
import json
import sqlite3
import datetime
import argparse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "database", "vibe_research.db")

# 我们的内部代码 -> (akshare 函数, 键, 友好名)
SINA_SYMBOLS = {
    "KS11":  ("首尔综合指数", "韩国KOSPI"),
    "TWII":  ("中国台湾加权指数", "台湾加权"),
    "NKY":   ("日经225指数", "日经225"),
}
# East Money 全球指数（网络可用时使用；本沙箱常被封，见下方 yfinance 兜底）
# 注：EM 全球指数表只含股指+DXY+CRB，不含单品种商品（黄金/原油/铜需另寻期货源）
EM_SYMBOLS = {
    "NDX":   ("纳斯达克", "纳斯达克"),
    "SPX":   ("标普500", "标普500"),
    "DJIA":  ("道琼斯", "道琼斯"),
    "DXY":   ("美元指数", "美元指数"),
    "CRB":   ("路透CRB商品指数", "CRB商品"),
}
# Yahoo chart REST 兜底（Stooq 被 bot 拦截、yfinance 库限流 429 时的主取数路径）
# 键名 = 看板内部代码（与 cio_agent._GLOBAL_BOARD_SPEC 完全一致，回填后自动点亮）
# 值为候选 ticker 列表，依次尝试（兼容不同写法 / 404 自动换下一个）
YF_SYMBOLS = {
    "NDX":    (["^IXIC"], "纳斯达克"),
    "SOXX":   (["SOXX"], "SOXX半导体ETF"),
    "HSTECH": (["^HSTECH", "3033.HK", "HSTECH.HK"], "恒生科技"),
    "DXY":    (["DX-Y.NYB"], "美元指数"),
    "US2Y":   (["ZT=F"], "美债2Y(期货代理)"),
    "US10Y":  (["^TNX"], "美债10Y"),
    "TIPS":   (["TIP"], "TIPS通胀保值债"),
    "BTC":    (["BTC-USD"], "比特币"),
    # 广度（跨市场相关分析备用；看板未直接展示）
    "SPX":    (["^GSPC"], "标普500"),
    "DJIA":   (["^DJI"], "道琼斯"),
    "XAU":    (["GC=F"], "黄金"),
    "CL":     (["CL=F"], "WTI原油"),
    "HG":     (["HG=F"], "COMEX铜"),
}
# akshare 中文源（沙箱与本机均可达）：目前 bond_zh_us_rate 能给美债收益率
# 键名 = 看板内部代码 -> (akshare函数名, 列名, 友好名)
AKSHARE_SYMBOLS = {
    "US2Y":  ("bond_zh_us_rate", "美国国债收益率2年", "美债2年"),
    "US10Y": ("bond_zh_us_rate", "美国国债收益率10年", "美债10年"),
}
# Stooq 主源（yfinance 被 Yahoo 普遍限流 429 时的第一兜底；本机通常可用，无 rate limit）
# 键名 = 看板内部代码 -> stooq 候选 ticker 列表（依次尝试，取到数据即止）
STOOQ_SYMBOLS = {
    "NDX":    ["^ndx", "ndx.us"],
    "SOXX":   ["soxx.us"],
    "HSTECH": ["^hstech", "hstech.hk"],
    "DXY":    ["^dxy", "dxy.us", "dx.us"],
    "US2Y":   ["us2y.us", "^us2y"],
    "US10Y":  ["us10y.us", "^us10y"],
    "TIPS":   ["tip.us", "tips.us"],
    "BTC":    ["btc.us"],
}

# Binance 现货 K 线（免费、无 rate limit、极可靠；本机几乎必通）。目前用于 BTC。
# 键名 = 看板内部代码 -> (Binance 交易对, 友好名)
BINANCE_SYMBOLS = {
    "BTC": ("BTCUSDT", "比特币"),
}


def _con():
    return sqlite3.connect(DB)


def ensure_table():
    con = _con()
    con.execute("""CREATE TABLE IF NOT EXISTS global_history (
        date TEXT, symbol TEXT, name TEXT, close REAL, change_pct REAL,
        PRIMARY KEY (date, symbol))""")
    con.commit()
    con.close()


def _change_pct(series):
    """由 close 序列算日涨跌幅(%)。"""
    out = [None]
    for i in range(1, len(series)):
        prev, cur = series[i - 1], series[i]
        out.append(round((cur / prev - 1) * 100, 4) if prev else None)
    return out


def _upsert(rows):
    """rows: list of (date, symbol, name, close, change_pct)。"""
    con = _con()
    con.executemany(
        "INSERT OR REPLACE INTO global_history(date,symbol,name,close,change_pct) "
        "VALUES(?,?,?,?,?)", rows)
    con.commit()
    con.close()


def fetch_sina(symbol, sina_key, name):
    import akshare as ak
    df = ak.index_global_hist_sina(symbol=sina_key)
    df = df.dropna(subset=["date", "close"])
    closes = [float(x) for x in df["close"].tolist()]
    dates = [str(x)[:10] for x in df["date"].tolist()]
    cps = _change_pct(closes)
    rows = [(d, symbol, name, c, cp) for d, c, cp in zip(dates, closes, cps)]
    _upsert(rows)
    return len(rows)


def fetch_em(symbol, em_key, name):
    import akshare as ak
    df = ak.index_global_hist_em(symbol=em_key)
    df = df.dropna(subset=["date", "close"])
    closes = [float(x) for x in df["close"].tolist()]
    dates = [str(x)[:10] for x in df["date"].tolist()]
    cps = _change_pct(closes)
    rows = [(d, symbol, name, c, cp) for d, c, cp in zip(dates, closes, cps)]
    _upsert(rows)
    return len(rows)


def load_csv(path):
    """离线灌入。CSV 列：date,symbol[,name],close 或 date,symbol,change_pct。"""
    name_map = {**{k: v[1] for k, v in SINA_SYMBOLS.items()},
                **{k: v[1] for k, v in EM_SYMBOLS.items()},
                **{k: v[1] for k, v in YF_SYMBOLS.items()}}
    rows = []
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            sym = row["symbol"].strip().upper()
            d = row["date"].strip()[:10]
            cp = row.get("change_pct")
            if cp not in (None, ""):
                rows.append((d, sym, name_map.get(sym, sym), None, float(cp)))
            else:
                rows.append((d, sym, name_map.get(sym, sym), float(row["close"]), None))
    _upsert(rows)
    return len(rows)


def export_csv(path):
    """导出 global_history 全表为 CSV（跨机器搬运用）。"""
    con = _con()
    cur = con.execute("SELECT date, symbol, name, close, change_pct FROM global_history ORDER BY symbol, date")
    rows = cur.fetchall()
    con.close()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "symbol", "name", "close", "change_pct"])
        w.writerows(rows)
    return len(rows)


def _yf_session():
    """构造带 Yahoo cookie 的 requests 会话，降低 429 概率（Yahoo 现在常要求 cookie/crumb）。"""
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        s.get("https://fc.yahoo.com", timeout=10)  # 触发 A1 cookie
    except Exception:
        pass
    return s


def fetch_yahoo_rest(symbol, yf_tickers, name, max_retries=5):
    """直接打 Yahoo chart REST（绕过 yfinance 库，单请求+间隔+退避，抗 429）。

    相比 yfinance.Ticker.history()（一次调用触发多个子请求、极易触发 429），
    这里每个 ticker 仅发 1 个 chart 请求，并带 cookie + crumb，且请求间留间隔，
    大幅降低被 Yahoo 限流的概率。yf_tickers 为候选列表，依次尝试。"""
    import time
    import json
    import datetime
    import urllib.request
    import urllib.parse
    import urllib.error
    MIN_ROWS = 60  # 不足此行数视为"数据不足"，自动换下一个候选 ticker
    s = _yf_session()
    last_err = None
    thin_err = None  # 所有候选都行数不足时的错误
    for tk in (yf_tickers if isinstance(yf_tickers, list) else [yf_tickers]):
        for attempt in range(1, max_retries + 1):
            try:
                time.sleep(2 if attempt == 1 else min(6 * attempt, 30))
                # 取 crumb（Yahoo 现在常要求，缺失易 429）
                crumb = ""
                try:
                    cr = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb",
                               timeout=10).text
                    if cr and 0 < len(cr) < 40:
                        crumb = cr
                except Exception:
                    pass
                url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
                       + urllib.parse.quote(tk) + "?range=5y&interval=1d")
                if crumb:
                    url += "&crumb=" + urllib.parse.quote(crumb)
                req = urllib.request.Request(url, headers={
                    "User-Agent": s.headers.get("User-Agent", "Mozilla/5.0"),
                    "Accept": "application/json",
                })
                req.add_header("Cookie", "; ".join(
                    f"{c.name}={c.value}" for c in s.cookies))
                raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
                j = json.loads(raw)
                res = j["chart"]["result"][0]
                ts = res["timestamp"]
                closes = res["indicators"]["quote"][0]["close"]
                pair = [(datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), c)
                        for t, c in zip(ts, closes) if c is not None]
                if not pair:
                    raise ValueError("Yahoo chart 无有效 close")
                cps = _change_pct([c for d, c in pair])
                rows = [(d, symbol, name, c, cp) for (d, c), cp in zip(pair, cps)]
                if len(rows) < MIN_ROWS:
                    # 行数过少（如 HSTECH.HK 仅 1 行）→ 视作数据不足，换下一候选
                    thin_err = ValueError(
                        f"{symbol}({tk}) 仅 {len(rows)} 行(<{MIN_ROWS})，换下一候选")
                    print(f"  [yahoo] {symbol}({tk}) ⚠️ 仅 {len(rows)} 行，换候选")
                    break  # 跳出 attempt 循环，进入下一个 tk
                _upsert(rows)
                print(f"  [yahoo] {symbol}({tk}) ✅ {len(rows)} 行")
                return len(rows)
            except Exception as e:
                # 404 = 符号不存在（确定性问题），无需重试，立即换下一候选
                if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                    last_err = e
                    print(f"  [yahoo] {symbol}({tk}) 404 不存在，换下一候选")
                    break  # 跳出 attempt 循环，进入下一个 tk
                last_err = e
                wait = min(8 * (2 ** (attempt - 1)), 60)
                print(f"  [yahoo] {symbol}({tk}) 重试{attempt}/{max_retries}: "
                      f"{type(e).__name__}: {str(e)[:60]} -> {wait}s")
                if attempt < max_retries:
                    time.sleep(wait)
    raise thin_err or last_err


def fetch_akshare(symbol, ak_func_name, col, name):
    """通过 akshare 中文源拉取（沙箱与本机均可达，如 bond_zh_us_rate 给美债收益率）。"""
    import akshare as ak
    import pandas as pd
    fn = getattr(ak, ak_func_name)
    df = fn()
    if df is None or len(df) == 0 or col not in df.columns:
        raise ValueError(f"akshare {ak_func_name} 无列 {col}")
    sub = df[["日期", col]].copy()
    sub = sub[sub[col] != "-"].dropna()
    dates = [str(pd.to_datetime(d).date()) for d in sub["日期"].tolist()]
    vals = [float(x) for x in sub[col].tolist()]
    cps = _change_pct(vals)
    rows = [(d, symbol, name, v, cp) for d, v, cp in zip(dates, vals, cps)]
    _upsert(rows)
    return len(rows)


def fetch_stooq(symbol, stooq_tickers, name, verbose=True):
    """通过 Stooq 免费 CSV 拉取（yfinance 限流时的主源；本机通常可用，无 rate limit）。

    stooq_tickers: 候选 ticker 列表，依次尝试直到取到有效数据（兼容不同后缀写法）。
    关键修复：ticker 中的 '^' 等字符必须 URL 编码，否则 Stooq 返回非 CSV 而静默失败。"""
    import urllib.request
    import urllib.parse
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY", "ftp_proxy", "FTP_PROXY"):
        os.environ.pop(k, None)
    hosts = ("https://stooq.com", "https://stooq.pl")
    last_err = None
    for tk in (stooq_tickers if isinstance(stooq_tickers, list) else [stooq_tickers]):
        encoded = urllib.parse.quote(tk)  # 关键：编码 ^ 等字符
        for host in hosts:
            try:
                url = f"{host}/q/d/l/?s={encoded}&i=d"
                req = urllib.request.Request(url, headers={
                    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/124.0 Safari/537.36"),
                    "Accept": "text/csv,*/*",
                })
                data = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
                # 诊断：若返回 HTML（含 <）说明不是 CSV
                if "<" in data[:200]:
                    raise ValueError(f"返回非CSV(疑似HTML拦截): {data[:100]!r}")
                lines = [l for l in data.strip().splitlines() if l]
                if len(lines) < 2:
                    raise ValueError(f"返回空(仅 {len(lines)} 行): {data[:100]!r}")
                closes, dates = [], []
                for l in lines[1:]:  # 跳过表头 Date,Open,...
                    p = l.split(",")
                    if len(p) < 5:
                        continue
                    try:
                        closes.append(float(p[4]))
                        dates.append(p[0][:10])
                    except Exception:
                        pass
                if not closes:
                    raise ValueError(f"无有效行(共 {len(lines)} 行)")
                cps = _change_pct(closes)
                rows = [(d, symbol, name, c, cp) for d, c, cp in zip(dates, closes, cps)]
                _upsert(rows)
                if verbose:
                    print(f"  [stooq] {symbol}({tk}) ✅ {len(rows)} 行")
                return len(rows)
            except Exception as e:
                last_err = e
                if verbose:
                    host_tag = host.split("//")[1]
                    print(f"  [stooq] {symbol}({tk}@{host_tag}): "
                          f"{type(e).__name__}: {str(e)[:80]}")
                continue
    raise last_err


def fetch_binance(symbol, pair, name, verbose=True):
    """通过 Binance 现货 K 线拉取（免费、无 rate limit、极可靠；用于 BTC 等加密货币）。
    返回 JSON 数组：每行 [openTime(ms), open, high, low, close, volume, ...]，close 在索引 4。"""
    import urllib.request
    import json
    import datetime
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY", "ftp_proxy", "FTP_PROXY"):
        os.environ.pop(k, None)
    url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=1d&limit=2000"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    if not data:
        raise ValueError("Binance 返回空")
    closes, dates = [], []
    for row in data:
        dt = datetime.datetime.utcfromtimestamp(row[0] / 1000)
        dates.append(dt.strftime("%Y-%m-%d"))
        closes.append(float(row[4]))
    if not closes:
        raise ValueError("Binance 无有效行")
    cps = _change_pct(closes)
    rows = [(d, symbol, name, c, cp) for d, c, cp in zip(dates, closes, cps)]
    _upsert(rows)
    if verbose:
        print(f"  [binance] {symbol}({pair}) ✅ {len(rows)} 行")
    return len(rows)


def run(symbols=None, local_only=False):
    """多源顺序回填。优先级：akshare(无限制) → binance(加密) → yahoo(chart REST,抗429)
    → stooq(兼容兜底) → sina/em。
    local_only=True 时跳过会被限流的 yahoo/stooq/em，保留 akshare+binance（本机可达）。"""
    ensure_table()
    if symbols:
        syms = list(symbols)
    else:
        syms = list(SINA_SYMBOLS) + list(EM_SYMBOLS) + list(YF_SYMBOLS)
        seen, uniq = set(), []
        for s in syms:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        syms = uniq
    summary = {}
    for sym in syms:
        # 优先级：akshare(无限制) → binance(加密,极稳) → yahoo(chart REST,抗429主源)
        #         → stooq(兼容兜底) → sina/em。local_only 跳过 yahoo/stooq/em，保留 akshare+binance。
        sources = []
        if sym in AKSHARE_SYMBOLS:
            sources.append(("ak",) + AKSHARE_SYMBOLS[sym])
        if sym in BINANCE_SYMBOLS:
            sources.append(("binance",) + BINANCE_SYMBOLS[sym])
        if not local_only:
            if sym in YF_SYMBOLS:
                sources.append(("yf",) + YF_SYMBOLS[sym])
            if sym in STOOQ_SYMBOLS:
                sources.append(("stooq", STOOQ_SYMBOLS[sym], sym))
            if sym in EM_SYMBOLS:
                sources.append(("em",) + EM_SYMBOLS[sym])
        # Sina 仅覆盖 KS11/TWII/NKY，且与上面不重叠，作最后兼容
        if sym in SINA_SYMBOLS:
            sources.append(("sina",) + SINA_SYMBOLS[sym])
        last_err = None
        done = False
        for src in sources:
            kind = src[0]
            try:
                if kind == "ak":
                    n = fetch_akshare(sym, src[1], src[2], src[3])
                elif kind == "sina":
                    n = fetch_sina(sym, src[1], src[2])
                elif kind == "em":
                    n = fetch_em(sym, src[1], src[2])
                elif kind == "yf":
                    n = fetch_yahoo_rest(sym, src[1], src[2])
                elif kind == "stooq":
                    n = fetch_stooq(sym, src[1], src[2])
                elif kind == "binance":
                    n = fetch_binance(sym, src[1], src[2])
                summary[sym] = f"OK {n} rows ({kind})"
                done = True
                break
            except Exception as e:
                last_err = e
                continue
        if not done:
            tag = type(last_err).__name__ if last_err else "no-source"
            summary[sym] = f"FAIL unreachable({tag})"
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="离线灌入 CSV")
    ap.add_argument("--export", help="导出 global_history 全表为 CSV（跨机器搬运）")
    ap.add_argument("--symbol", help="只拉单个符号，如 NDX")
    ap.add_argument("--local-only", action="store_true",
                    help="受限网络：只用 akshare/Sina 可达源，不撞 Yahoo/Stooq")
    args = ap.parse_args()
    ensure_table()
    if args.export:
        n = export_csv(args.export)
        print(f"导出完成：{n} 行 -> {args.export}")
    elif args.csv:
        n = load_csv(args.csv)
        print(f"CSV 灌入完成：{n} 行")
    else:
        syms = [args.symbol] if args.symbol else None
        summ = run(syms, local_only=args.local_only)
        print("回填结果：")
        for k, v in summ.items():
            print(f"  {k}: {v}")
