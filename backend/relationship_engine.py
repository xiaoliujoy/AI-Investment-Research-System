# -*- coding: utf-8 -*-
"""
relationship_engine.py —— 关系/规律引擎（Relationship & Observation Engine）

项目新阶段的核心模块之一。回答的不是"今天发生了什么"，
而是"今天市场教会了我们什么新规律 / 哪些跨资产关系正在增强或失效"。

这是用户要求的六大引擎之一（Narrative / Flow / Relationship / Catalyst /
Observation / CRO）里最值得先落地的：它直接产出"新的 Alpha 来源"。

两种输入：
  (1) AUTO —— 系统用本地已有的日线收益率序列，自动计算两资产滚动相关 +
      状态机（增强/稳定/减弱/断裂），发现关系变化。
  (2) HUMAN —— 用户目测到的疑似规律（如"韩股领先科创50"），系统记录为
      待验证假设；一旦两端历史数据齐备（如回填 KOSPI 日线），自动计算并
      更新置信度。这实现了用户"Observation #137"的构想，且尊重
      "系统圈定/记录，人确认"的分工原则。

数据：
  - A 股内部关系：stock_daily(指数如 000688/399006/000001) + sector_daily，
    本地全量历史，可直接 AUTO 计算。
  - 跨市场关系（KOSPI / 纳指 / 黄金 / 铜 / 美元）：global_market_daily 目前
    仅快照（20 行），无历史 → 跨市场对走 HUMAN 假设 + DATA_NEEDED 状态，
    待回填 global_history 表后自动升级为 AUTO。

输出：
  - output/relationship_report.json  （本引擎结构化产出，供 CIO memo 读取）
  - output/observations.json         （假设/规律库，跨日持久化，只追加不覆盖）
"""
from __future__ import annotations
import os
import json
import sqlite3
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "database", "vibe_research.db")
OUT = os.path.join(BASE, "output")
REL_FILE = os.path.join(OUT, "relationship_report.json")
OBS_FILE = os.path.join(OUT, "observations.json")

# ── 用户目测到的"待验证假设"种子（Observation 构想）──
# 一旦 KOSPI 日线历史回填，引擎会自动计算滚动相关并升级状态。
HYPOTHESIS_SEEDS = [
    {
        "id": "OBS-KOSPI-KC50",
        "type": "human",
        "title": "韩国 KOSPI 科技股 领先/同步 科创50",
        "pair": {"a": "KOSPI(KS11)", "b": "科创50(000688)"},
        "hypothesis": ("亚洲 AI 资金跨市场交易：KOSPI 盘中走势领先/同步科创50约30分钟。"
                       "7/14 两者均从 -5%/-4.9% 拉升到 +0.5%，高度一致。"),
        "source": "用户 7/14 盘后观察",
        "data_needed": "KOSPI 日线历史（global_history 表，需 akshare/网络回填）",
        "seed_confidence": 0.78,
    },
    {
        "id": "OBS-NASDAQ-KC50",
        "type": "human",
        "title": "纳斯达克 领先/同步 科创50",
        "pair": {"a": "纳斯达克(NDX)", "b": "科创50(000688)"},
        "hypothesis": ("AI 产业链中美映射：纳指（半导体/AI 权重高）隔夜/盘中走势影响科创50风险偏好。"),
        "source": "用户 7/14 跨市场观察",
        "data_needed": "纳斯达克日线历史（global_history 表，需 yfinance/EM 回填）",
        "seed_confidence": 0.6,
    },
    {
        "id": "OBS-GOLD-BTC",
        "type": "human",
        "title": "黄金 与 BTC 同步下跌（实际利率驱动）",
        "pair": {"a": "黄金(XAU)", "b": "BTC"},
        "hypothesis": "当实际利率上行时，黄金与 BTC 作为零息/高风险资产同步承压。",
        "source": "用户方法论假设",
        "data_needed": "BTC 日线历史 + 实际利率序列",
        "seed_confidence": 0.55,
    },
]


# ═══════════════════════════════════════════════════════
#  数据读取
# ═══════════════════════════════════════════════════════

def _con():
    return sqlite3.connect(DB)


def _stock_pct(code: str, n: int = 60):
    """取指数/个股最近 n 个交易日的日涨跌幅（%）。"""
    con = _con()
    cur = con.cursor()
    rows = cur.execute(
        "SELECT change_pct FROM stock_daily WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, n)).fetchall()
    con.close()
    return [float(r[0]) for r in reversed(rows) if r[0] is not None]


def _sector_pct(name: str, n: int = 60):
    """取某板块最近 n 个交易日的日涨跌幅（%）。"""
    con = _con()
    cur = con.cursor()
    rows = cur.execute(
        "SELECT change_pct FROM sector_daily WHERE sector_name=? ORDER BY date DESC LIMIT ?",
        (name, n)).fetchall()
    con.close()
    return [float(r[0]) for r in reversed(rows) if r[0] is not None]


def _resolve_sector(keyword: str):
    """按关键词匹配一个存在的板块名（取最近一日有数据的）。"""
    con = _con()
    cur = con.cursor()
    rows = cur.execute(
        "SELECT DISTINCT sector_name FROM sector_daily WHERE sector_name LIKE ?",
        (f"%{keyword}%",)).fetchall()
    con.close()
    return [r[0] for r in rows]


# ═══════════════════════════════════════════════════════
#  相关性 / 状态机
# ═══════════════════════════════════════════════════════

def _stock_dated(code: str, n: int = 300):
    """返回 [(date, change_pct), ...] 升序，最近 n 个交易日（带日期以便对齐）。"""
    con = _con()
    cur = con.cursor()
    rows = cur.execute(
        "SELECT date, change_pct FROM stock_daily WHERE code=? AND change_pct IS NOT NULL "
        "ORDER BY date DESC LIMIT ?", (code, n)).fetchall()
    con.close()
    return [(str(r[0]), float(r[1])) for r in reversed(rows)]


def _global_dated(symbol: str, n: int = 300):
    """返回 global_history 中某境外指数/商品的 [(date, change_pct), ...] 升序。"""
    con = _con()
    cur = con.cursor()
    rows = cur.execute(
        "SELECT date, change_pct FROM global_history WHERE symbol=? AND change_pct IS NOT NULL "
        "ORDER BY date DESC LIMIT ?", (symbol, n)).fetchall()
    con.close()
    return [(str(r[0]), float(r[1])) for r in reversed(rows)]


def _align(a_dated, b_dated):
    """按交集交易日对齐两序列，返回 [(a_pct, b_pct), ...] 升序；样本<20 返回 None。"""
    if not a_dated or not b_dated:
        return None
    da = {d: p for d, p in a_dated}
    db = {d: p for d, p in b_dated}
    common = sorted(set(da) & set(db))
    if len(common) < 20:
        return None
    return [(da[d], db[d]) for d in common]


def _analyze_cross():
    """跨市场关系对：KOSPI / 纳指 / 标普 ↔ A股指数（需 global_history 已回填对应符号）。

    数据缺失的对自动跳过（优雅降级），回填后下次运行自动出现并参与验证。
    """
    CROSS_PAIRS = [
        ("KS11", "000688", "KOSPI ↔ 科创50", "韩国KOSPI(KS11)", "科创50(000688)"),
        ("NDX", "000688", "纳指 ↔ 科创50", "纳斯达克(NDX)", "科创50(000688)"),
        ("NDX", "399006", "纳指 ↔ 创业板指", "纳斯达克(NDX)", "创业板指(399006)"),
        ("SPX", "000688", "标普500 ↔ 科创50", "标普500(SPX)", "科创50(000688)"),
    ]
    out = []
    for gsym, code, label, pa, pb in CROSS_PAIRS:
        g = _global_dated(gsym, 300)
        s = _stock_dated(code, 300)
        aligned = _align(g, s)
        if not aligned:
            continue
        a = [x[0] for x in aligned]
        b = [x[1] for x in aligned]
        overall = _corr(a, b)
        recent = _corr(a[-20:], b[-20:]) if len(a) >= 20 else None
        prior = _corr(a[-60:-20], b[-60:-20]) if len(a) >= 40 else None
        rg = _regime(recent, prior)
        conf = _confidence(overall, len(a))
        out.append({
            "type": "cross",
            "label": label,
            "pair_a": pa,
            "pair_b": pb,
            "corr_overall": round(overall, 3) if overall is not None else None,
            "corr_recent20": round(recent, 3) if recent is not None else None,
            "corr_prior40": round(prior, 3) if prior is not None else None,
            "regime": rg,
            "confidence": conf,
            "sample": len(a),
        })
    return out


def _corr(a, b):
    n = min(len(a), len(b))
    if n < 5:
        return None
    a, b = a[-n:], b[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return cov / (va ** 0.5 * vb ** 0.5)


def _regime(recent: float, prior: float):
    """比较两个窗口的相关，判定关系状态。"""
    if recent is None or prior is None:
        return "未知"
    delta = recent - prior
    if delta >= 0.15:
        return "增强"
    if delta <= -0.15:
        return "减弱"
    if abs(recent) < 0.3:
        return "脱钩"
    return "稳定"


def _confidence(corr: float, n: int):
    """样本越多、相关越强，置信越高。"""
    if corr is None:
        return 0.0
    base = min(1.0, n / 60.0)
    return round(base * (0.5 + 0.5 * abs(corr)), 2)


def _fmt_corr(x):
    """相关系数安全格式化：None 显示破折号，避免 NoneType 格式化崩溃。

    背景：跨市场对齐样本在 20~39 个交易日时，corr_prior40 为 None，
    直接 {x:+.2f} 会抛 TypeError，导致整条流水线 FAIL。
    """
    return f"{x:+.2f}" if isinstance(x, (int, float)) else "—"


# ═══════════════════════════════════════════════════════
#  AUTO 关系对（A 股内部，本地有历史）
# ═══════════════════════════════════════════════════════

def _auto_pairs():
    """构造可自动计算的 A 股内部关系对。"""
    pairs = []
    kc50 = _stock_pct("000688", 60)
    cyb = _stock_pct("399006", 60)
    sh = _stock_pct("000001", 60)
    if kc50 and cyb:
        pairs.append(("科创50 ↔ 创业板指", kc50, cyb, "科创50(000688)", "创业板指(399006)"))
    if kc50 and sh:
        pairs.append(("科创50 ↔ 上证指数", kc50, sh, "科创50(000688)", "上证指数(000001)"))
    # 科创50 vs 科技板块
    for kw in ("半导体", "芯片", "人工智能", "算力", "光模块", "CPO"):
        names = _resolve_sector(kw)
        if names:
            s = _sector_pct(names[0], 60)
            if kc50 and s:
                pairs.append((f"科创50 ↔ {names[0]}", kc50, s, "科创50(000688)", names[0]))
    # 上证 vs 创业板（风格相关）
    if sh and cyb:
        pairs.append(("上证指数 ↔ 创业板指", sh, cyb, "上证指数(000001)", "创业板指(399006)"))
    return pairs


def _analyze_auto():
    out = []
    for label, a, b, na, nb in _auto_pairs():
        if len(a) < 25 or len(b) < 25:
            continue
        overall = _corr(a, b)
        recent = _corr(a[-20:], b[-20:])
        prior = _corr(a[-60:-20], b[-60:-20]) if len(a) >= 40 else None
        rg = _regime(recent, prior)
        conf = _confidence(overall, min(len(a), len(b)))
        out.append({
            "type": "auto",
            "label": label,
            "pair_a": na,
            "pair_b": nb,
            "corr_overall": round(overall, 2) if overall is not None else None,
            "corr_recent20": round(recent, 2) if recent is not None else None,
            "corr_prior40": round(prior, 2) if prior is not None else None,
            "regime": rg,
            "confidence": conf,
            "sample": min(len(a), len(b)),
        })
    return out


# ═══════════════════════════════════════════════════════
#  假设 / 规律库（跨日持久化）
# ═══════════════════════════════════════════════════════

def _load_obs():
    if os.path.exists(OBS_FILE):
        try:
            return json.load(open(OBS_FILE, encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_obs(lst):
    with open(OBS_FILE, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)


def _merge_hypotheses(auto_results, cross_results=None):
    """将种子假设并入规律库；已存在的保留验证进度，不存在的新增。
    cross_results：跨市场对齐相关结果，用于把 KOSPI↔科创50 等假设升级为验证数字。
    """
    obs = _load_obs()
    existing = {o.get("id") for o in obs}
    today = datetime.date.today().isoformat()

    # 先把 AUTO 结果里"强相关且状态变化"的也登记为 auto 规律
    for r in auto_results:
        if r["corr_overall"] is not None and abs(r["corr_overall"]) >= 0.6:
            oid = f"AUTO-{r['pair_a']}__{r['pair_b']}"
            rec = {
                "id": oid,
                "type": "auto",
                "title": r["label"],
                "pair": {"a": r["pair_a"], "b": r["pair_b"]},
                "hypothesis": f"近60日相关系数 {r['corr_overall']:+.2f}，状态：{r['regime']}。",
                "status": "VALIDATED" if abs(r["corr_overall"]) >= 0.7 else "TRACKING",
                "auto_corr": r["corr_overall"],
                "regime": r["regime"],
                "confidence": r["confidence"],
                "updated": today,
            }
            # 去重更新
            for i, o in enumerate(obs):
                if o.get("id") == oid:
                    obs[i].update({k: v for k, v in rec.items() if k != "id"})
                    break
            else:
                rec["created"] = today
                rec["evidence"] = [f"本地 {r['sample']} 交易日收益率序列自动计算"]
                obs.append(rec)

    # 合并 HUMAN 种子
    for seed in HYPOTHESIS_SEEDS:
        if seed["id"] in existing:
            continue
        rec = dict(seed)
        rec["status"] = "TRACKING"
        rec["auto_corr"] = None
        rec["regime"] = None
        rec["confidence"] = seed.get("seed_confidence", 0.5)
        rec["created"] = today
        rec["updated"] = today
        rec["days_observed"] = 1
        rec["evidence"] = ["用户目测：7/14 两者盘中走势高度一致"]
        obs.append(rec)

    # 跨市场验证：用真实对齐相关升级对应假设（TRACKING→VALIDATED）
    # 跨市场标签 → 假设 id 映射
    CROSS_TO_HYP = {
        "KOSPI ↔ 科创50": "OBS-KOSPI-KC50",
        "纳指 ↔ 科创50": "OBS-NASDAQ-KC50",
    }
    if cross_results:
        for cr in cross_results:
            hid = CROSS_TO_HYP.get(cr["label"])
            if not hid or cr["corr_overall"] is None:
                continue
            for o in obs:
                if o.get("id") == hid:
                    o["status"] = "VALIDATED"
                    o["auto_corr"] = cr["corr_overall"]
                    o["regime"] = cr["regime"]
                    o["confidence"] = cr["confidence"]
                    o["validated_on"] = today
                    o["sample"] = cr["sample"]
                    o["updated"] = today
                    o.setdefault("evidence", []).append(
                        f"实测：{cr['sample']} 个对齐交易日，近60日相关 "
                        f"{cr['corr_overall']:+.2f}（近20日 {_fmt_corr(cr['corr_recent20'])}，"
                        f"前40日 {_fmt_corr(cr['corr_prior40'])}），状态{cr['regime']}")
                    break

    _save_obs(obs)
    return obs


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def run() -> dict:
    """计算关系 + 维护规律库，写 relationship_report.json。"""
    auto = _analyze_auto()
    cross = _analyze_cross()
    obs = _merge_hypotheses(auto, cross)

    # 选取"今日新发现"头条：状态变化最强的 auto + 用户重点 human 假设
    # 关键：不仅看"当前相关高"，更要捕捉"关系断裂/减弱"——从强相关跌到弱相关
    # 往往是更有价值的 Alpha（如科创50近期与自身半导体板块脱钩）。
    discoveries = []
    for r in auto:
        if r["regime"] in ("增强", "减弱", "脱钩") and r["corr_overall"] is not None:
            prior = r["corr_prior40"]
            strong = (abs(r["corr_overall"]) >= 0.5
                      or (prior is not None and abs(prior) >= 0.5))
            if not strong:
                continue
            discoveries.append({
                "type": "auto",
                "label": r["label"],
                "regime": r["regime"],
                "corr": r["corr_overall"],
                "confidence": r["confidence"],
                "note": (f"近60日相关 {r['corr_overall']:+.2f}，近20日"
                         f"{_fmt_corr(r['corr_recent20'])}（前40日 {_fmt_corr(r['corr_prior40'])}），"
                         f"关系{r['regime']}。"),
            })
    # 其他跨市场关系（如纳指↔科创50）作为补充发现（KOSPI 由下方 OBS 置顶处理）
    for c in cross:
        if c["label"] == "KOSPI ↔ 科创50":
            continue
        if c["corr_overall"] is None:
            continue
        discoveries.append({
            "type": "cross",
            "label": c["label"],
            "regime": c["regime"],
            "corr": c["corr_overall"],
            "confidence": c["confidence"],
                "note": (f"近60日相关 {c['corr_overall']:+.2f}（近20日"
                         f"{_fmt_corr(c['corr_recent20'])}，前40日 {_fmt_corr(c['corr_prior40'])}），"
                         f"状态{c['regime']}。样本 {c['sample']} 个对齐交易日。"),
        })

    # 用户重点假设（KOSPI↔科创50）：已回填 KOSPI 则展示验证数字，否则仍置顶提醒待验证
    for o in obs:
        if o.get("id") == "OBS-KOSPI-KC50":
            if o.get("status") == "VALIDATED" and o.get("auto_corr") is not None:
                c = o["auto_corr"]
                weak = abs(c) < 0.4
                # 关键纠偏：日线相关弱 ≠ "关系不存在"。用户观察到的是分钟级事件性共振，
                # 日线相关无法证伪它，必须用分钟级数据单独验证。
                if weak:
                    verdict = (f"日线收盘相关仅 {c:+.2f}（减弱）：说明'收盘层面的稳定同步'并不存在；"
                               f"但你 7/14 观察到的 KOSPI 盘中领先科创50 约30分钟，属分钟级事件性共振，"
                               f"日线相关不能证伪它——'韩股跟屁虫'在日线层不成立，但分钟级是否领先【待验证】")
                else:
                    verdict = f"实测日线相关性较强（{c:+.2f}），假设获支撑"
                discoveries.insert(0, {
                    "type": "human",
                    "label": o["title"] + ("（分钟级待验证）" if weak else ""),
                    "regime": o.get("regime", "已验证"),
                    "corr": c,
                    "confidence": o.get("confidence", 0.78),
                    "note": (f"已验证数字：{o.get('sample')} 个对齐交易日，近60日相关 "
                             f"{c:+.2f}（状态：{o.get('regime')}）。{verdict}。"
                             f"注：日线收盘相关衡量的是同日收尾联动；盘中30分钟领先需分钟级数据另测，"
                             f"系统已将此标记为【分钟数据待验证】，而非'关系不存在'。"),
                })
            else:
                discoveries.insert(0, {
                    "type": "human",
                    "label": o["title"],
                    "regime": "待验证",
                    "corr": None,
                    "confidence": o.get("confidence", 0.78),
                    "note": f"用户假设：{o['hypothesis']}（需回填KOSPI历史后自动计算）",
                })

    report = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "auto_pairs_count": len(auto),
        "cross_pairs_count": len(cross),
        "observations_count": len(obs),
        "auto_detail": auto,
        "cross_detail": cross,
        "discoveries": discoveries[:6],
        "headline": discoveries[0]["label"] if discoveries else "今日未发现显著新关系",
    }
    os.makedirs(OUT, exist_ok=True)
    with open(REL_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


if __name__ == "__main__":
    rep = run()
    print("关系引擎产出：")
    print(json.dumps(rep, ensure_ascii=False, indent=2)[:2500])
