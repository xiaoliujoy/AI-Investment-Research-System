# -*- coding: utf-8 -*-
"""
capital_score.py — Stock Capital Score（个股资金强度评分）

模型（100 分，按用户 2026-07-19 定义的 OS 4.0 Phase 1 权重）：

    资金强度评分
    = 个股主力净流入(30)        -- 今天有没有钱
    + 3/5日持续性(20)          -- 是不是持续买
    + 板块资金排名(20)         -- 有没有板块背景
    + 龙头位置(15)             -- 是不是核心
    + 成交活跃度(10)          -- 有没有交易关注
    - 异常风险(15)             -- ST/减持/监管

所有子分均来自真实数据，不依赖任何死列：
  - 个股主力净流入：stock_flow_daily.main_net_buy（东财 push2 真实回填）
  - 板块资金排名：把个股资金流按「行业→板块」聚合后跨截面百分位（sector_daily.net_amount 已于 2026-07-31 改为由 stock_flow_daily 聚合回填，真实区间≥07-20；此处仍独立计算、不依赖该列，避免历史 NULL 干扰）
  - 龙头位置：个股在其板块内主力净流入的排名
  - 持续性：近 window(默认5) 个交易日主力净流入累计的跨截面百分位
  - 活跃度：stock_daily.turnover_rate 百分位（缺失则退回 amount 百分位）
  - 风险：名称含 ST/*/退 → 扣 15（减持/监管无数据源，暂留接口）

落库：stock_capital_score（date, code 主键），便于 Data Health 校验、L5 消费、回放。

下游：
  - 日报「龙头资金层」：对每个候选主线板块，列出 Capital Score 最高的核心股。
  - L5 龙头体系（后续）：直接读 stock_capital_score。
"""
from __future__ import annotations
import sqlite3
from database.models import get_db

# ── 权重（与用户定义一致）──
W_FUND = 30.0
W_PERSIST = 20.0
W_SECTOR = 20.0
W_LEADER = 15.0
W_ACTIVE = 10.0
W_RISK = 15.0

# ST / 退市 / 风险命名特征
_RISK_NAME_TOKENS = ("ST", "*ST", "退", "N ")


def _is_stock(code: str) -> bool:
    if not code:
        return False
    return code[0] in ("6", "0", "3") or code.startswith(("83", "87", "920"))


def _is_risk_name(name: str) -> bool:
    if not name:
        return False
    n = name.strip().upper()
    for tok in ("ST", "*ST", "退"):
        if tok in n:
            return True
    return False


def _pct_rank(vals: dict) -> dict:
    """vals: code -> float；返回 code -> 百分位(0~1，值越大越接近1)。None/NaN 视为最低。"""
    items = [(c, (v if (v is not None and isinstance(v, (int, float)) and v == v) else float("-inf")))
             for c, v in vals.items()]
    items.sort(key=lambda x: x[1])
    N = len(items)
    out = {}
    i = 0
    while i < N:
        j = i
        while j < N and items[j][1] == items[i][1]:
            j += 1
        p = (i / (N - 1)) if N > 1 else 0.5
        for k in range(i, j):
            out[items[k][0]] = p
        i = j
    return out


def _leader_points(rank1: int) -> float:
    """板块内主力净流入排名（1-based）→ 龙头位置分。"""
    if rank1 <= 1:
        return W_LEADER
    if rank1 <= 3:
        return 10.0
    if rank1 <= 10:
        return 5.0
    return 0.0


# ── 模块级缓存：避免两个渲染器重复计算 ──
_CACHE: dict = {}


def _ensure(date: str, window: int = 5):
    if date not in _CACHE:
        _CACHE[date] = compute_scores(date, window=window)
    return _CACHE[date]


def compute_scores(date: str, window: int = 5, verbose: bool = False) -> dict:
    """
    计算单日全市场 Capital Score。

    返回 dict:
      scores:            code -> rec(dict)
      sector_constituents: em板块 -> [code,...]
      sector_rank_pct:   em板块 -> 资金排名百分位(0~1)
      em_of:             code -> [em板块,...]
      sorted_by_sector:  em板块 -> 按当日主力净流入降序的 [code,...]
    rec 字段：date,code,name,score,f_fund,f_persist,f_sector,f_leader,
             f_active,f_risk,sector_name,sector_rank_pct,intra_rank,is_st
    """
    c = get_db()

    # 确保表存在（与 models.init_db 中 DDL 一致，自给自足）
    c.execute("""
        CREATE TABLE IF NOT EXISTS stock_capital_score (
            date            TEXT,
            code            TEXT,
            name            TEXT,
            score           REAL,
            f_fund          REAL,
            f_persist       REAL,
            f_sector        REAL,
            f_leader        REAL,
            f_active        REAL,
            f_risk          REAL,
            sector_name     TEXT,
            sector_rank_pct REAL,
            intra_rank      INTEGER,
            is_st           INTEGER DEFAULT 0,
            PRIMARY KEY (date, code)
        )
    """)

    # 1) 近期交易日窗口（含当日）
    flow_dates = [r[0] for r in c.execute(
        "SELECT DISTINCT date FROM stock_flow_daily WHERE date<=? ORDER BY date DESC LIMIT ?",
        (date, window)).fetchall()]
    flow_dates = list(reversed(flow_dates))  # 升序
    if not flow_dates:
        if verbose:
            print(f"[capital_score] {date} 无 stock_flow_daily 数据")
        return {"scores": {}, "sector_constituents": {}, "sector_rank_pct": {},
                "em_of": {}, "sorted_by_sector": {}}
    d0 = flow_dates[-1]  # 实际计算日（最新可用）

    # 2) 当日个股资金流 + 历史窗口累计
    today_flow = {r[0]: r[1] for r in c.execute(
        "SELECT code, main_net_buy FROM stock_flow_daily WHERE date=?", (d0,)).fetchall()}
    hist_flow = {d: {r[0]: r[1] for r in c.execute(
        "SELECT code, main_net_buy FROM stock_flow_daily WHERE date=?", (d,)).fetchall()}
        for d in flow_dates}
    cum5 = {}
    for code in today_flow:
        s = 0.0
        for d in flow_dates:
            v = hist_flow.get(d, {}).get(code)
            if v:
                s += v
        cum5[code] = s

    # 3) 当日成交活跃度（turnover_rate，缺失退 amount）
    act = {}
    for code, name, tr, amt in c.execute(
            "SELECT code, name, turnover_rate, amount FROM stock_daily WHERE date=?", (d0,)).fetchall():
        act[code] = (tr if (tr is not None and tr == tr) else (amt if amt else 0.0), name)

    # 4) 股票 → em 板块映射（industry_map 同花顺行业 → sector_crosswalk 东财板块）
    cross = {}
    for thx, em in c.execute("SELECT thx_name, em_name FROM sector_crosswalk").fetchall():
        cross[thx] = em
    stock_ind = {}
    for code, ind in c.execute("SELECT stock_code, industry_name FROM industry_map").fetchall():
        stock_ind.setdefault(code, []).append(ind)

    em_of = {}
    for code, inds in stock_ind.items():
        ems = []
        for ind in inds:
            if ind in cross:
                ems.append(cross[ind])
        # 去重保序
        seen = set()
        ems = [e for e in ems if not (e in seen or seen.add(e))]
        if not ems:  # 无对照 → 用原始行业名兜底（避免完全无板块背景）
            ems = [inds[0]]
        em_of[code] = ems

    # 5) 板块资金净额（个股资金流按 em 板块聚合）+ 排名
    sector_net = {}
    sector_constituents = {}
    for code, ems in em_of.items():
        v = today_flow.get(code) or 0.0
        for em in ems:
            sector_net[em] = sector_net.get(em, 0.0) + v
            sector_constituents.setdefault(em, []).append(code)
    sector_rank_pct = _pct_rank(sector_net)

    # 6) 板块内龙头排名（按当日主力净流入降序）
    sorted_by_sector = {}
    for em, codes in sector_constituents.items():
        ranked = sorted(codes, key=lambda x: today_flow.get(x) or 0.0, reverse=True)
        sorted_by_sector[em] = ranked

    # 7) 跨截面百分位
    pct_fund = _pct_rank(today_flow)
    pct_persist = _pct_rank(cum5)
    pct_active = _pct_rank({k: v[0] for k, v in act.items()})

    # 8) 逐股打分
    scores = {}
    for code in today_flow:
        if not _is_stock(code):
            continue
        name = act.get(code, (0.0, code))[1]
        ems = em_of.get(code, [])
        # 板块因子：取该股所属板块中排名最高的
        best_sector, best_sp = None, 0.0
        best_rank = None
        best_leader = 0.0
        for em in ems:
            sp = sector_rank_pct.get(em, 0.0)
            if sp >= best_sp:
                best_sp = sp
                best_sector = em
            ranked = sorted_by_sector.get(em, [])
            if code in ranked:
                rk = ranked.index(code) + 1
                lp = _leader_points(rk)
                if lp >= best_leader:
                    best_leader = lp
                    best_rank = rk
        f_fund = pct_fund.get(code, 0.0) * W_FUND
        f_persist = pct_persist.get(code, 0.0) * W_PERSIST
        f_sector = best_sp * W_SECTOR
        f_leader = best_leader
        f_active = pct_active.get(code, 0.0) * W_ACTIVE
        is_st = 1 if _is_risk_name(name) else 0
        f_risk = W_RISK if is_st else 0.0
        score = f_fund + f_persist + f_sector + f_leader + f_active - f_risk
        score = max(0.0, min(100.0, score))
        scores[code] = {
            "date": d0, "code": code, "name": name, "score": round(score, 1),
            "f_fund": round(f_fund, 1), "f_persist": round(f_persist, 1),
            "f_sector": round(f_sector, 1), "f_leader": round(f_leader, 1),
            "f_active": round(f_active, 1), "f_risk": round(f_risk, 1),
            "sector_name": best_sector, "sector_rank_pct": round(best_sp, 3),
            "intra_rank": best_rank, "is_st": is_st,
        }

    # 9) 落库
    c.executemany(
        """INSERT OR REPLACE INTO stock_capital_score
           (date,code,name,score,f_fund,f_persist,f_sector,f_leader,f_active,f_risk,
            sector_name,sector_rank_pct,intra_rank,is_st)
           VALUES (:date,:code,:name,:score,:f_fund,:f_persist,:f_sector,:f_leader,
                   :f_active,:f_risk,:sector_name,:sector_rank_pct,:intra_rank,:is_st)""",
        list(scores.values()))
    c.commit()
    if verbose:
        print(f"[capital_score] {d0}: 计算 {len(scores)} 只 Capital Score，落库完成")
    return {"scores": scores, "sector_constituents": sector_constituents,
            "sector_rank_pct": sector_rank_pct, "em_of": em_of,
            "sorted_by_sector": sorted_by_sector}


# ── 报告消费接口 ──
def _resolve_em(sector_query: str, cache: dict) -> list:
    """把候选板块显示名（可能是同花顺/东财名）解析为 em 板块列表。"""
    q = (sector_query or "").strip()
    if not q:
        return []
    cross_rev = {}  # em_name -> thx set (用于反向)
    c = get_db()
    rows = c.execute("SELECT thx_name, em_name FROM sector_crosswalk").fetchall()
    em_names = set()
    thx_to_em = {}
    for thx, em in rows:
        em_names.add(em)
        thx_to_em[thx] = em
    # 精确
    if q in em_names:
        return [q]
    if q in thx_to_em:
        return [thx_to_em[q]]
    # 部分匹配（包含）
    out = []
    for em in em_names:
        if q in em or em in q:
            out.append(em)
    if out:
        return out[:5]
    for thx, em in thx_to_em.items():
        if q in thx or thx in q:
            out.append(em)
    # 也直接匹配 industry_map 原始行业名
    if not out:
        direct = [r[0] for r in c.execute(
            "SELECT DISTINCT industry_name FROM industry_map WHERE industry_name LIKE ? LIMIT 5",
            (f"%{q}%",)).fetchall()]
        for ind in direct:
            if ind in thx_to_em:
                out.append(thx_to_em[ind])
            else:
                out.append(ind)
    return list(dict.fromkeys(out))[:5]


def sector_top_stocks(date: str, sector_query: str, topn: int = 5, window: int = 5) -> list:
    """返回某候选板块内 Capital Score 最高的 Top 个股（rec 列表）。"""
    cache = _ensure(date, window)
    ems = _resolve_em(sector_query, cache)
    if not ems:
        return []
    codes = set()
    for em in ems:
        codes.update(cache["sector_constituents"].get(em, []))
    scores = cache["scores"]
    recs = [scores[code] for code in codes if code in scores]
    recs.sort(key=lambda r: r["score"], reverse=True)
    return recs[:topn]


def top_universe(date: str, topn: int = 30, window: int = 5) -> list:
    """全市场 Capital Score 最高的 Top 个股。"""
    cache = _ensure(date, window)
    recs = list(cache["scores"].values())
    recs.sort(key=lambda r: r["score"], reverse=True)
    return recs[:topn]


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "2026-07-17"
    res = compute_scores(d, verbose=True)
    print("\n=== 全市场 Capital Score Top 15 ===")
    for r in top_universe(d, 15):
        print(f"  {r['code']} {r['name']:<8} 分={r['score']:>5}  板块={r['sector_name']}"
              f"  资金={r['f_fund']:.0f} 持续={r['f_persist']:.0f} 板块={r['f_sector']:.0f}"
              f" 龙头={r['f_leader']:.0f} 活跃={r['f_active']:.0f} 风险={r['f_risk']:.0f}")
    print("\n=== 白酒 龙头资金层 Top 5 ===")
    for r in sector_top_stocks(d, "白酒", 5):
        print(f"  {r['code']} {r['name']:<8} 分={r['score']:>5} 板块内排名={r['intra_rank']}")
