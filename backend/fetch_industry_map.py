"""
fetch_industry_map.py
Step2 成分映射：从东财 datacenter (RPT_BOARD_CONSTITUENT, 沙箱内可达) 拉取
「股票 -> 行业/概念板块」映射，落地到 industry_map / board_list / stock_info 表。

背景：
- 沙箱网络：同花顺 q.10jqka.com.cn 被 WAF 403；东财 push2.eastmoney.com 被代理封；
  但 东财 datacenter-web.eastmoney.com 可达，RPT_BOARD_CONSTITUENT 报表可用。
- RPT_BOARD_CONSTITUENT 含全部板块(行业/概念/地域/通)的成分股，BOARD_TYPE_NEW 区分：
    2 = 行业板块(东财~90 coarse + 申万多级)，3 = 概念/主题，1 = 地域，4 = 沪深港通
- 个股名称从新浪 stock_info_a_code_name 一次性补齐（沙箱内可达）。

用法：
  python fetch_industry_map.py          # 全量拉取并写库
  python fetch_industry_map.py --check  # 仅统计覆盖率，不写库
"""
import argparse
import sqlite3
import time
import sys
import requests
import akshare as ak
import pandas as pd

DB = "C:/Users/JOY/WorkBuddy/个人AI研投系统/backend/database/vibe_research.db"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get?"

# 同花顺 90 行业名（来自 step1 缓存 sector_mainline.json，用于交叉匹配覆盖率评估）
import json, os
_THX_NAMES = []
_ml = os.path.join(os.path.dirname(__file__), "output", "sector_mainline.json")
if os.path.exists(_ml):
    try:
        _d = json.load(open(_ml, encoding="utf-8"))
        _THX_NAMES = [s.get("name") for s in _d.get("sectors", []) if s.get("name")]
    except Exception:
        pass


def _get(url, timeout=25):
    h = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://data.eastmoney.com/",
    }
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_constituents(board_type, page_size=5000, max_pages=20):
    """分页拉取某 BOARD_TYPE_NEW 下的全部成分股。返回 [(stock_code, industry_code, industry_name, board_type)]"""
    filt = "(BOARD_TYPE_NEW%%3D%%22%d%%22)" % board_type
    cols = "BOARD_TYPE_NEW,BOARD_CODE,BOARD_NAME,SECURITY_CODE,SECUCODE"
    rows = []
    for pg in range(1, max_pages + 1):
        u = (BASE + "reportName=RPT_BOARD_CONSTITUENT&columns=%s&filter=%s"
             "&pageSize=%d&pageNumber=%d&source=WEB&client=WEB") % (cols, filt, page_size, pg)
        try:
            j = _get(u)
        except Exception as e:
            print("  [warn] page %d fetch fail: %s" % (pg, e))
            break
        res = (j.get("result") or {}).get("data") or []
        if not res:
            break
        for r in res:
            bc = str(r.get("BOARD_CODE") or "").strip()
            bn = (r.get("BOARD_NAME") or "").strip()
            sc = (r.get("SECURITY_CODE") or "").strip()
            if not bc or not sc:
                continue
            rows.append((sc, bc, bn, board_type))
        if len(res) < page_size:
            break
        time.sleep(0.3)
    return rows


def fetch_stock_info():
    """新浪 code->name，返回 {code: name}"""
    print("  fetching stock_info (新浪) ...")
    df = ak.stock_info_a_code_name()
    out = {}
    for _, row in df.iterrows():
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        if code:
            out[code] = name
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="仅统计覆盖率")
    args = ap.parse_args()

    print("==> fetching 东财 industry/concept constituents (datacenter) ...")
    rows2 = fetch_constituents(2)
    rows3 = fetch_constituents(3)
    all_rows = rows2 + rows3
    print("  type2 rows=%d  type3 rows=%d  total=%d" % (len(rows2), len(rows3), len(all_rows)))

    # board_list + 覆盖率
    boards = {}  # code -> (name, type, count)
    for sc, bc, bn, bt in all_rows:
        if bc not in boards:
            boards[bc] = [bn, bt, 0]
        boards[bc][2] += 1
    board_names_type2 = {bn for bc, (bn, bt, _) in boards.items() if bt == 2}

    print("  distinct boards: %d (type2=%d, type3=%d)" % (
        len(boards),
        sum(1 for v in boards.values() if v[1] == 2),
        sum(1 for v in boards.values() if v[1] == 3),
    ))

    # 同花顺名 -> 东财名 匹配评估
    if _THX_NAMES:
        exact = sum(1 for n in _THX_NAMES if n in board_names_type2)
        print("  同花顺90行业 精确命中 type2 名称: %d/%d" % (exact, len(_THX_NAMES)))
        miss = [n for n in _THX_NAMES if n not in board_names_type2]
        if miss:
            print("  未命中(待概念/模糊匹配):", miss)

    if args.check:
        return

    # 写库
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS industry_map")
    con.execute("""CREATE TABLE industry_map (
        stock_code TEXT, industry_code TEXT, industry_name TEXT, board_type INTEGER,
        PRIMARY KEY (stock_code, industry_code))""")
    con.execute("DROP TABLE IF EXISTS board_list")
    con.execute("""CREATE TABLE board_list (
        industry_code TEXT PRIMARY KEY, industry_name TEXT, board_type INTEGER, member_count INTEGER)""")
    con.executemany("INSERT OR REPLACE INTO industry_map VALUES (?,?,?,?)", all_rows)
    con.executemany("INSERT OR REPLACE INTO board_list VALUES (?,?,?,?)",
                    [(bc, v[0], v[1], v[2]) for bc, v in boards.items()])

    # stock_info
    si = fetch_stock_info()
    con.execute("DROP TABLE IF EXISTS stock_info")
    con.execute("CREATE TABLE stock_info (code TEXT PRIMARY KEY, name TEXT)")
    con.executemany("INSERT OR REPLACE INTO stock_info VALUES (?,?)", list(si.items()))
    con.commit()

    n_im = con.execute("SELECT COUNT(*) FROM industry_map").fetchone()[0]
    n_bl = con.execute("SELECT COUNT(*) FROM board_list").fetchone()[0]
    n_si = con.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
    print("  WROTE industry_map=%d  board_list=%d  stock_info=%d" % (n_im, n_bl, n_si))
    con.close()
    print("==> done.")


if __name__ == "__main__":
    main()
