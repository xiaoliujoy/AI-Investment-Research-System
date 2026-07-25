"""
build_crosswalk.py
建立 同花顺行业名(共识L4输出) -> 东财板块(industry_map) 的映射表 sector_crosswalk。
这样 L5/L6 拿到主线板块(同花顺名)后，能解析到东财成分股，把候选从全市场缩到主线板块内。

匹配优先级：MANUAL硬编码 -> 精确 -> 归一化(去Ⅱ/Ⅲ/Ⅳ/Ⅴ/概念/指数后缀) -> 包含 -> 二元文法相似度(>=0.45, 优先行业t2)。

用法：python build_crosswalk.py
"""
import json
import os
import re
import sqlite3

DB = "C:/Users/JOY/WorkBuddy/个人AI研投系统/backend/database/vibe_research.db"
_ML = os.path.join(os.path.dirname(__file__), "output", "sector_mainline.json")

# 同花顺名 -> 东财板块名（针对模糊仍易错的少量手工覆盖）
MANUAL = {
    "军工装备": "国防军工",
    "文化传媒": "传媒",
    "旅游及酒店": "旅游酒店",
    "汽车服务及其他": "汽车服务",
    "饮料制造": "饮料乳品",
    "石油加工贸易": "石油石化",
    "种植业与林业": "种植业",
    "公路铁路运输": "铁路公路",
    "机场航运": "航运港口",
    "港口航运": "航运港口",
    "油气开采及服务": "油气开采Ⅱ",
}

SUFFIX = re.compile(r"(Ⅱ|Ⅲ|Ⅳ|Ⅴ)$")


def norm(name):
    return SUFFIX.sub("", name).strip()


def bigrams(s):
    return set(s[i:i + 2] for i in range(len(s) - 1))


def sim(a, b):
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def main():
    con = sqlite3.connect(DB)
    boards = con.execute(
        "SELECT industry_code, industry_name, board_type FROM board_list").fetchall()
    # 归一化索引：同一归一名可能对应 Ⅱ/Ⅲ 多级，优先选更宽泛的(无高级后缀、名字短、t2)
    def _penalty(name):
        if name.endswith(("Ⅲ", "Ⅳ", "Ⅴ")):
            return 2
        if name.endswith("Ⅱ"):
            return 1
        return 0

    norm_idx = {}
    for c, n, t in boards:
        nn = norm(n)
        cand = (c, n, t)
        if nn not in norm_idx:
            norm_idx[nn] = cand
        else:
            old = norm_idx[nn]
            if (_penalty(n), len(n), t) < (_penalty(old[1]), len(old[1]), old[2]):
                norm_idx[nn] = cand

    d = json.load(open(_ML, encoding="utf-8"))
    thx = [s["sector"] for s in d.get("sectors", []) if s.get("sector")]

    rows = []
    miss = []
    for n in thx:
        em = None
        method = None
        if n in MANUAL:
            tgt = MANUAL[n]
            hit = [(c, bn, bt) for c, bn, bt in boards if bn == tgt]
            if hit:
                c, bn, bt = hit[0]
                em, method = (c, bn, bt, "manual"), "manual"
        if not em:
            # 精确
            hit = [(c, bn, bt) for c, bn, bt in boards if bn == n]
            if hit:
                c, bn, bt = sorted(hit, key=lambda x: x[2])[0]
                em, method = (c, bn, bt), "exact"
        if not em:
            # 归一化
            if norm(n) in norm_idx:
                c, bn, bt = norm_idx[norm(n)]
                em, method = (c, bn, bt), "normalized"
        if not em:
            # 包含
            hit = [(c, bn, bt) for c, bn, bt in boards if bn in n or n in bn]
            if hit:
                c, bn, bt = sorted(hit, key=lambda x: x[2])[0]
                em, method = (c, bn, bt), "contains"
        if not em:
            # 二元文法
            best = max(boards, key=lambda x: sim(n, x[1]))
            if sim(n, best[1]) >= 0.45:
                em, method = best, "bigram"
        if em:
            rows.append((n, em[0], em[1], em[2], method))
        else:
            miss.append(n)

    con.execute("DROP TABLE IF EXISTS sector_crosswalk")
    con.execute("""CREATE TABLE sector_crosswalk (
        thx_name TEXT PRIMARY KEY, em_code TEXT, em_name TEXT, em_type INTEGER, match_method TEXT)""")
    con.executemany("INSERT OR REPLACE INTO sector_crosswalk VALUES (?,?,?,?,?)", rows)
    con.commit()
    print("crosswalk rows=%d  miss=%d" % (len(rows), len(miss)))
    for n, c, bn, bt, m in rows:
        if m != "exact":
            print("  ", n, "->", bn, "(%s t%d)" % (m, bt))
    if miss:
        print("UNMAPPED:", miss)
    con.close()


if __name__ == "__main__":
    main()
