# -*- coding: utf-8 -*-
"""
cro_agent.py —— CRO（首席研究官 / Chief Research Officer）总裁定词

用户六大引擎（Narrative / Flow / Relationship / Catalyst / Observation / CRO）
的总指挥层。CRO 不自己算数据，而是【编排】各引擎产出，每日只问三个问题：

  Q1 今天交易什么（What to trade）      —— 资金主线 + 强相关板块聚类
  Q2 最大边际变化（Biggest change）      —— 关系断裂/增强 + 资金突变 + 跨资产信号
  Q3 市场教会我们什么（Lesson）          —— 规律库里的"反直觉"发现（Alpha 来源）

设计原则（与系统方法论一致）：
  - 系统只"圈定/合成"，最终买卖由人看图决定；
  - 全部为可审计的确定性规则合成，不调用 LLM，保证可复现；
  - 输入缺失时安全降级，绝不抛异常中断流水线。

输入：output/{sector_mainline,flow_report,gold_report,relationship_report}.json
输出：output/cro_report.json  +  CROMemo 结构（供 CIO memo / 推送渲染读取）
"""
from __future__ import annotations
import os
import json
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
CRO_FILE = os.path.join(OUT, "cro_report.json")


def _load(name, default=None):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _fmt(x, nd=2, pct=False):
    if x is None:
        return "—"
    if pct:
        return f"{x:+.{nd}f}%"
    return f"{x:.{nd}f}"


# ═════════════════════════════════════════════════════
#  Q1 今天交易什么
# ═════════════════════════════════════════════════════

def _build_q1(sector, flow, rel):
    """资金主线：近1日净流入 + 成交额放大 + 近5日累计净流入 三重确认。"""
    rows = []
    if sector:
        for s in (sector.get("top10_net_inflow") or [])[:3]:
            rows.append({
                "name": s.get("sector"),
                "net": s.get("net_now"),
                "chg": s.get("chg_pct"),
                "leader": s.get("leader"),
            })
    # 近5日累计净流入前排（持续性信号）
    c5 = []
    if sector:
        for s in (sector.get("top5_5d_net_inflow") or [])[:3]:
            c5.append({"name": s.get("sector"), "net5d": s.get("net_5d")})

    if rows:
        top = rows[0]
        headline = (f"主攻方向：{top['name']}（今日净流入 {_fmt(top['net'],0)} 亿、"
                    f"{_fmt(top['chg'],2,True)}，龙头 {top.get('leader') or '—'}）")
    elif c5:
        headline = f"主攻方向：{c5[0]['name']}（近5日累计净流入 {_fmt(c5[0]['net5d'],0)} 亿）"
    else:
        headline = "暂无明确资金主线（数据缺失或资金分散）"

    # 行业 ETF 资金在买什么（来自 Flow 情报）
    etf_buy = ""
    intel = (flow or {}).get("intelligence") or {}
    q2c = intel.get("q2_china", "")
    if q2c:
        etf_buy = "行业ETF口径：" + q2c.split("\n")[0][:60]

    note = ("板块>龙头>资金>图形：以上为系统圈定的候选主线，最终买点请人工看图确认。"
            + ((" " + etf_buy) if etf_buy else ""))
    return {"headline": headline, "sectors": rows, "sectors_5d": c5, "note": note}


# ═════════════════════════════════════════════════════
#  Q2 最大边际变化
# ═════════════════════════════════════════════════════

def _build_q2(flow, gold, rel):
    bullets = []

    # 1) 关系规律突变（增强/减弱/脱钩）—— 最值钱的边际信息
    disc = (rel or {}).get("discoveries") or []
    for d in disc:
        if d.get("type") == "auto" and d.get("regime") in ("减弱", "脱钩", "增强"):
            bullets.append(f"【规律】{d['label']} {d['regime']}：{d['note']}")

    # 2) 跨市场验证数字（KOSPI↔科创50）
    cross = (rel or {}).get("cross_detail") or []
    for c in cross:
        if c.get("corr_overall") is not None:
            bullets.append(
                f"【跨市场】{c['label']} 实测日线相关 {_fmt(c['corr_overall'],2,True)}"
                f"（{c['sample']} 个对齐交易日，状态 {c['regime']}）")

    # 3) 南北向资金突变
    inst = (flow or {}).get("institution") or {}
    hsgt = inst.get("hsgt") or {}
    sn = hsgt.get("south_net")
    nn = hsgt.get("north_net")
    if sn is not None and abs(sn) >= 30:
        bullets.append(f"【港股通】南向净流入 {_fmt(sn,1)} 亿"
                       + ("（大额扫货，边际偏强）" if sn > 0 else "（大额流出）"))
    if nn is not None and abs(nn) >= 30:
        bullets.append(f"【港股通】北向净流入 {_fmt(nn,1)} 亿")

    # 4) 商品 / 黄金信号
    if gold:
        gp = gold.get("gold_change_pct")
        gd = (gold.get("drive_score") or {}).get("direction")
        if gp is not None:
            bullets.append(f"【黄金】${_fmt(gold.get('gold_price'),0)}（{_fmt(gp,2,True)}），"
                           f"驱动评分方向 {gd or '—'}")
    comm = (flow or {}).get("commodity") or {}
    up = []
    for cat in ("energy", "precious", "industrial", "agri", "shipping"):
        for it in (comm.get(cat) or []):
            cp = it.get("change_pct")
            if cp is not None and abs(cp) >= 1.5:
                up.append(f"{it.get('name_cn')}{_fmt(cp,2,True)}")
    if up:
        bullets.append("【商品】异动：" + "、".join(up[:6]))

    # 核心子弹（规律/跨市场/资金/商品）限制条数，给盘前纪要信号留位
    core = bullets[:4]

    # 5) 盘前纪要情绪信号（连板高度 / 热榜 / 地雷）—— Phase 1 灌入模块
    #    始终保留（不随核心子弹过多被截断），这是盘前叙事层的关键输入。
    pq_bullets = []
    pq = _load("panqian_feed.json")
    if pq and pq.get("has_data"):
        cf_ = pq.get("cro_feed") or {}
        max_days = cf_.get("limit_up_max_days") or 0
        if max_days:
            pq_bullets.append(f"【盘前纪要】连板最高 {max_days} 板"
                              + ("（情绪高亢，注意分歧风险）" if max_days >= 5 else ""))
        hl = cf_.get("hot_list_top") or []
        names = []
        for it in hl[:3]:
            st = it.get("stock") or []
            if st:
                names.append(st[0])
        if names:
            pq_bullets.append(f"【盘前纪要】人气热榜Top：{'、'.join(names)}")
        land = pq.get("risk_landmines") or []
        if land:
            pq_bullets.append(f"【盘前纪要】地雷阵 {len(land)} 条："
                              + "、".join(f"{r.get('stock','')}({r.get('type','')})" for r in land[:4]))

    final = core + pq_bullets
    headline = final[0] if final else "今日边际变化温和，无显著突变信号"
    return {"headline": headline, "bullets": final}


# ═════════════════════════════════════════════════════
#  Q3 市场教会我们什么（规律 / 反直觉）
# ═════════════════════════════════════════════════════

def _build_q3(rel):
    """从规律库提炼"反直觉"的元认知——这是 Observation 引擎的 Alpha 来源。"""
    bullets = []
    auto = (rel or {}).get("auto_detail") or []
    by_label = {a["label"]: a for a in auto}

    kc_semi = by_label.get("科创50 ↔ 半导体")
    kc_sh = by_label.get("科创50 ↔ 上证指数")
    if kc_semi and kc_sh:
        bullets.append(
            f"科创50 已不再是'半导体β'：与半导体相关从 {_fmt(kc_semi.get('corr_prior40'),2)} "
            f"降到 {_fmt(kc_semi.get('corr_overall'),2)}（{kc_semi.get('regime')}），"
            f"却与上证指数锁到 {_fmt(kc_sh.get('corr_overall'),2)}（{kc_sh.get('regime')}）。"
            f"→ 交易科创50 看上证与全市场风险偏好，而非看半导体。")

    cross = (rel or {}).get("cross_detail") or []
    for c in cross:
        if c.get("corr_overall") is not None:
            weak = abs(c["corr_overall"]) < 0.4
            bullets.append(
                f"{c['label']} 日线相关仅 {_fmt(c['corr_overall'],2)}"
                + ("：所谓'跟屁虫'在日线层面不成立，盘中共振属事件性而非结构。"
                   if weak else "：跨市场结构同步得到验证。"))

    # 其他显著状态变化的板块关系
    for a in auto:
        if a["label"].startswith("科创50"):
            continue
        if a.get("regime") in ("减弱", "脱钩") and (abs(a.get("corr_overall") or 0) >= 0.5
                                                    or abs(a.get("corr_prior40") or 0) >= 0.5):
            bullets.append(f"{a['label']} {a['regime']}（相关 {_fmt(a.get('corr_overall'),2)}），"
                           f"旧有的联动逻辑可能失效，注意切换。")

    headline = bullets[0] if bullets else "暂未提炼出新的反直觉规律"
    return {"headline": headline, "bullets": bullets[:5]}


# ═════════════════════════════════════════════════════
#  总裁定性（verdict）
# ═════════════════════════════════════════════════════

def _verdict(flow, gold, rel):
    """把各引擎方向信号合成一个总裁定性 + 置信度。"""
    score = 50.0
    n = 0
    # Flow 全局流动性 M1
    fs = (flow or {}).get("flow_score") or {}
    m1 = fs.get("m1_global") or {}
    if m1.get("score") is not None:
        score += (m1["score"] - 50) * 0.3
        n += 1
    # Gold 方向
    gd = (gold or {}).get("drive_score") or {}
    direction = gd.get("direction") or ""
    if "bullish" in direction:
        score += 8; n += 1
    elif "bearish" in direction:
        score -= 8; n += 1
    # Relationship：若出现"脱钩"则提示结构风险（降风险偏好）
    disc = (rel or {}).get("discoveries") or []
    if any(d.get("regime") == "脱钩" for d in disc):
        score -= 5

    score = max(0, min(100, score))
    if score >= 60:
        verdict = "偏进攻"
    elif score <= 40:
        verdict = "偏防守"
    else:
        verdict = "结构市 / 观望"

    # 置信度：取各引擎样本/方向可用度的简单均值
    conf = round(0.5 + 0.5 * (n / 3.0), 2) if n else 0.5
    return {"verdict": verdict, "score": round(score, 1), "confidence": conf}


# ═════════════════════════════════════════════════════
#  主入口
# ═════════════════════════════════════════════════════

def produce() -> dict:
    sector = _load("sector_mainline.json", {}) or {}
    flow = _load("flow_report.json", {}) or {}
    gold = _load("gold_report.json", {}) or {}
    rel = _load("relationship_report.json", {}) or {}

    q1 = _build_q1(sector, flow, rel)
    q2 = _build_q2(flow, gold, rel)
    q3 = _build_q3(rel)
    vd = _verdict(flow, gold, rel)

    memo = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "verdict": vd["verdict"],
        "score": vd["score"],
        "confidence": vd["confidence"],
        "q1": q1,
        "q2": q2,
        "q3": q3,
    }
    os.makedirs(OUT, exist_ok=True)
    with open(CRO_FILE, "w", encoding="utf-8") as f:
        json.dump(memo, f, ensure_ascii=False, indent=2)
    return memo


if __name__ == "__main__":
    m = produce()
    print(json.dumps(m, ensure_ascii=False, indent=2))
