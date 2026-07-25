# -*- coding: utf-8 -*-
"""
step2 · 板块→成分股 映射构建（同花顺数据域 d/q.10jqka.com.cn）
===========================================================
1) stock_info 表：全 A code→name（akshare stock_info_a_code_name，新浪源，已验证可达）
2) industry_map 表：股票→同花顺行业（爬 90 行业详情页，解析 stockpage.10jqka.com.cn/{code} 链接）

用法：python build_industry_mapping.py
注意：沙箱仅 dead 代理，调用前必须清 http_proxy/https_proxy。
"""
import os, re, time, sqlite3, json
for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)
import akshare as ak
import requests
from py_mini_racer import MiniRacer
import akshare.stock_feature.stock_board_industry_ths as ths_mod

DB = "C:/Users/JOY/WorkBuddy/个人AI研投系统/backend/database/vibe_research.db"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"


def get_v():
    js = MiniRacer()
    js.eval(ths_mod._get_file_content_ths("ths.js"))
    return js.call("v")


def conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS stock_info(
        code TEXT PRIMARY KEY, name TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS industry_map(
        stock_code TEXT, industry_code TEXT, industry_name TEXT, stock_name TEXT,
        PRIMARY KEY(stock_code, industry_code))""")
    return c


def build_stock_info(c):
    print("== 拉取全 A code→name ==")
    df = ak.stock_info_a_code_name()
    df = df.rename(columns={"code": "code", "name": "name"})
    c.executemany("INSERT OR REPLACE INTO stock_info(code,name) VALUES(?,?)",
                  [(str(r.code), str(r.name)) for r in df.itertuples()])
    c.commit()
    print(f"   stock_info 写入 {len(df)} 条")


LINK_RE = re.compile(r'stockpage\.10jqka\.com\.cn/(\d{6})/?"[^>]*>([^<]*)</a>')
COUNT_RE = re.compile(r'成分股[（(]?\s*(\d+)\s*[)）]?')


def fetch_industry_members(code, v):
    """爬单个行业详情页（含翻页），返回 [(stock_code, stock_name), ...]"""
    members = {}
    page = 1
    while True:
        url = f"http://q.10jqka.com.cn/thshy/detail/code/{code}/" + (f"?page={page}" if page > 1 else "")
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Cookie": f"v={v}",
                                            "Referer": "http://q.10jqka.com.cn"}, timeout=30)
        except Exception:
            return list(members.values())
        if r.status_code != 200:
            if page == 1:
                v = get_v()  # 重新生成 cookie 重试
                continue
            break
        found = LINK_RE.findall(r.text)
        new = 0
        for sc, sn in found:
            sn = sn.strip()
            if sc not in members:
                members[sc] = (sc, sn)
                new += 1
        if new == 0 or page >= 20:
            break
        page += 1
        time.sleep(0.15)
    return list(members.values())


def main():
    c = conn()
    build_stock_info(c)

    print("== 拉取同花顺 90 行业成分 ==")
    bd = ak.stock_board_industry_name_ths()  # columns: name, code
    v = get_v()
    total_pairs = 0
    for _, r in bd.iterrows():
        iname, icode = str(r["name"]), str(r["code"])
        mem = fetch_industry_members(icode, v)
        if not mem:
            print(f"  [空] {iname}({icode})")
            continue
        c.executemany(
            "INSERT OR REPLACE INTO industry_map(stock_code,industry_code,industry_name,stock_name) VALUES(?,?,?,?)",
            [(sc, icode, iname, sn) for sc, sn in mem])
        total_pairs += len(mem)
        if len(mem) < 30:
            print(f"  {iname}: {len(mem)} 只")
        time.sleep(0.1)
    c.commit()

    # 统计
    nc = c.execute("SELECT COUNT(DISTINCT stock_code) FROM industry_map").fetchone()[0]
    ni = c.execute("SELECT COUNT(DISTINCT industry_code) FROM industry_map").fetchone()[0]
    print(f"\n完成：industry_map 共 {total_pairs} 对映射，覆盖 {nc} 只股票 / {ni} 个行业")
    # 重点行业抽查
    for tname in ["半导体", "医疗服务", "计算机设备"]:
        n = c.execute("SELECT COUNT(*) FROM industry_map WHERE industry_name=?", (tname,)).fetchone()[0]
        print(f"   {tname}: {n} 只成分")
    c.close()


if __name__ == "__main__":
    main()
