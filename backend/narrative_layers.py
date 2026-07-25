# -*- coding: utf-8 -*-
"""
narrative_layers —— 八层决策树的【叙事/宏观层数据函数】。

★ 重建说明（2026-07-16）★
    原实现位于 narrative_engine.py，于 2026-07-15 被「为什么引擎」整体覆盖而丢失，
    导致 L1 全球宏观 / L2 中国宏观 / L3 产业趋势 / L8 学习进化 四层静默失效
    （ImportError 被 orchestrator._safe 吞掉）。原始代码已不可恢复（非 git 仓库、
    无备份、pyc 已刷新、历史对话无留存），故按现有可用数据源【重建】。
    重建逻辑均为规则化、可复现、透明标注；缺数据一律优雅降级到 gaps，绝不编造。

    为根除「一个文件承担两种职责→被覆盖」的隐患，本模块与 narrative_engine.py
    （为什么引擎）彻底分家：
        narrative_layers.py  ←── 决策树宏观/叙事层数据（本文件）
        narrative_engine.py  ←── 「为什么」板块因果链引擎（run()）

契约（被 brain/agents 与 decision_tree / learning_feedback 消费）：
    layer1_global()          → {"data": {...}, "gaps": [...]}         L1 全球宏观
    layer2_china()           → {"data": {regime}, "read", "gaps"}     L2 中国宏观
    layer3_industry(l4raw)   → {"top_industries": [...], "gaps": [...]} L3 产业趋势
    layer8_learning()        → {"count", "read", "gaps"}              L8 学习(薄封装)
    monthly_pattern()        → {"count","win_rate","by_month","by_sector","insights","read"}
    add_journal(...) / interactive_add()                             交易日志录入
    DB                       → SQLite 路径常量（trade_log_cli 复用）
"""
from __future__ import annotations

import os
import sys
import sqlite3
import json
import datetime
from collections import defaultdict

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

DB = os.path.join(_BASE, "database", "vibe_research.db")
_OUTPUT = os.path.join(_BASE, "output")


def _clear_proxy():
    """清空死代理，保证 akshare/requests 直连（沙箱 7890 代理已 dead）。"""
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)


def _load_json(fname):
    p = os.path.join(_OUTPUT, fname)
    try:
        import json
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _num(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════
#  L1 全球宏观 —— 美股/VIX/美元/商品/BTC/美债/北向 → 风险偏好 regime
# ════════════════════════════════════════════════════════════════════

def layer1_global() -> dict:
    """
    全球宏观风险偏好判定。

    数据源（复用已有、避免重复脆弱网络请求）：
      · macro.get_all()          → 黄金/原油/铜/BTC/美元指数（实时/缓存）
      · output/flow_report.json  → 北向/南向净额、商品 risk_appetite（FLOW 引擎已算）
      · 美股指数/VIX/美债/离岸人民币/恒生：本沙箱外网受限，多缺失→记 gaps

    regime ∈ {风险偏好回升, 中性震荡, 避险偏强, 避险主导}
    """
    gaps = []
    data = {}

    # 1) 商品 + 美元（macro 模块）
    try:
        _clear_proxy()
        import macro
        mall = macro.get_all()
        for c in mall.get("commodities", []) or []:
            key = c.get("key")
            if key in ("gold", "oil", "copper", "btc", "dxy"):
                data[key] = {"change_pct": _num(c.get("change_pct")),
                             "price": _num(c.get("price"))}
        if "dxy" in data:
            data["usd"] = data["dxy"]
    except Exception as e:
        gaps.append(f"商品/美元取数失败：{type(e).__name__}")

    # 2) 北向/南向 + 商品风险偏好（复用 FLOW 引擎产出）
    flow = _load_json("flow_report.json")
    inst = (flow.get("institution") or {})
    hsgt = (inst.get("hsgt") or {})
    north = _num(hsgt.get("north_net"))
    south = _num(hsgt.get("south_net"))
    if north is not None:
        data["north"] = north
    if south is not None:
        data["south"] = south
    risk_appetite = ((flow.get("commodity") or {}).get("risk_appetite"))
    if risk_appetite:
        data["risk_appetite"] = risk_appetite

    # 3) 外网受限项——诚实记 gaps（不编造）
    for k, label in [("us_indices", "美股指数"), ("vix", "VIX"),
                     ("ust10y", "美债10Y"), ("cnh", "离岸人民币"), ("hsi", "恒生")]:
        if k not in data:
            gaps.append(f"{label}未接入（沙箱外网受限）")

    # 4) 规则化 regime 打分（正=risk-on）
    score = 0.0
    reasons = []
    dxy = (data.get("dxy") or {}).get("change_pct")
    if dxy is not None:
        if dxy < -0.1:
            score += 1; reasons.append(f"美元走弱({dxy:+.2f}%)")
        elif dxy > 0.1:
            score -= 1; reasons.append(f"美元走强({dxy:+.2f}%)")
    if north is not None:
        if north > 5:
            score += 1; reasons.append(f"北向净流入{north:.0f}亿")
        elif north < -5:
            score -= 1; reasons.append(f"北向净流出{abs(north):.0f}亿")
    copper = (data.get("copper") or {}).get("change_pct")
    if copper is not None:
        if copper > 0.3:
            score += 0.5; reasons.append("铜价上行(工业需求)")
        elif copper < -0.3:
            score -= 0.5; reasons.append("铜价走弱")
    btc = (data.get("btc") or {}).get("change_pct")
    if btc is not None:
        if btc > 1:
            score += 0.5; reasons.append("BTC上行(风险偏好)")
        elif btc < -1:
            score -= 0.5; reasons.append("BTC下行(避险)")
    gold = (data.get("gold") or {}).get("change_pct")
    if gold is not None and gold > 0.8:
        score -= 0.5; reasons.append("黄金明显上行(避险买盘)")
    if risk_appetite == "进攻" or risk_appetite == "risk_on":
        score += 0.5
    elif risk_appetite == "防御" or risk_appetite == "risk_off":
        score -= 0.5

    if score >= 2:
        regime = "风险偏好回升"
    elif score <= -2:
        regime = "避险主导"
    elif score <= -1:
        regime = "避险偏强"
    else:
        regime = "中性震荡"

    note = "、".join(reasons[:4]) if reasons else "外围信号平淡，无明显方向"
    if len(gaps) >= 4:
        note += "（注：美股/VIX/美债等外围核心项沙箱受限，判定以商品+汇率+北向为主，权重有限）"
    data["regime"] = regime
    data["regime_note"] = note
    data["score"] = round(score, 1)

    # 顶层 read/status：供 decision_tree.render_narrative（legacy HTML）直接渲染
    read = f"【外围：{regime}】{note}"
    status = "部分接入" if gaps else "已接入"
    return {"data": data, "read": read, "status": status, "gaps": gaps}


# ════════════════════════════════════════════════════════════════════
#  L2 中国宏观 —— PMI/M2/社融/LPR/CPI → 货币信用 2×2 格局
# ════════════════════════════════════════════════════════════════════

def _date_key(s):
    """把 '2026年06月份' / '2026-06' / '20260601' 等归一为可比整数 YYYYMM(DD)。"""
    import re
    digits = re.sub(r"\D", "", str(s))
    return int(digits) if digits else -1


def _latest_two(df, val_col):
    """
    取某列「最近两个」非空数值 (latest, prev)。

    akshare 宏观 df 排序方向不一（多为降序：最新在首行），故不依赖原始顺序——
    找日期列(月份/日期/date/TRADE_DATE)按时间升序对齐后取末两个；无日期列则退回原序。
    """
    try:
        date_col = None
        for c in df.columns:
            cl = str(c)
            if cl in ("月份", "日期", "date", "TRADE_DATE") or "日期" in cl or "月份" in cl:
                date_col = c
                break
        sub = df[[val_col]].copy()
        if date_col is not None:
            sub["_dk"] = df[date_col].map(_date_key)
            sub = sub.sort_values("_dk")  # 升序：最新在末尾
        sub = sub[sub[val_col].notna()]
        vals = [_num(x) for x in sub[val_col].tolist() if _num(x) is not None]
        if len(vals) >= 2:
            return vals[-1], vals[-2]
        if len(vals) == 1:
            return vals[-1], None
    except Exception:
        pass
    return None, None


def layer2_china() -> dict:
    """
    货币信用格局判定（2×2）。
      货币松紧：看 LPR 方向 + M1 同比趋势（利率下行/M1回升 = 宽货币）
      信用松紧：看社融增量趋势 + M2 同比趋势（社融/M2 回升 = 宽信用）
    regime ∈ {宽货币+宽信用, 宽货币+紧信用, 紧货币+宽信用, 紧货币+紧信用, 数据待补}
    """
    gaps = []
    reads = []
    money_loose = None   # True=宽 False=紧
    credit_loose = None

    _clear_proxy()
    try:
        import akshare as ak
    except Exception as e:
        return {"data": {"regime": "数据待补"},
                "read": f"akshare 不可用：{type(e).__name__}",
                "gaps": [f"akshare import 失败：{type(e).__name__}"]}

    # ── 货币面：LPR ──
    try:
        lpr = ak.macro_china_lpr()
        col = None
        for c in lpr.columns:
            if "1Y" in str(c) or "1年" in str(c) or "LPR1Y" in str(c):
                col = c; break
        if col is None:
            # 常见列名 TRADE_DATE / LPR1Y
            cand = [c for c in lpr.columns if "LPR" in str(c).upper()]
            col = cand[0] if cand else None
        if col is not None:
            cur, prev = _latest_two(lpr, col)
            if cur is not None and prev is not None:
                if cur < prev:
                    money_loose = True; reads.append(f"1年期LPR下调至{cur}%（宽货币）")
                elif cur > prev:
                    money_loose = False; reads.append(f"1年期LPR上调至{cur}%（紧货币）")
                else:
                    reads.append(f"1年期LPR维持{cur}%")
    except Exception:
        gaps.append("LPR 取数失败")

    # ── 货币面补充：M1 同比 ──
    try:
        m2 = ak.macro_china_money_supply()
        m1col = None
        for c in m2.columns:
            if "M1" in str(c) and "同比" in str(c):
                m1col = c; break
        if m1col:
            cur, prev = _latest_two(m2, m1col)
            if cur is not None and prev is not None:
                reads.append(f"M1同比{cur}%（前值{prev}%）")
                if money_loose is None:
                    money_loose = cur >= prev
        # ── 信用面：M2 同比 ──
        m2col = None
        for c in m2.columns:
            if "M2" in str(c) and "同比" in str(c):
                m2col = c; break
        if m2col:
            cur, prev = _latest_two(m2, m2col)
            if cur is not None and prev is not None:
                reads.append(f"M2同比{cur}%（前值{prev}%）")
                credit_loose = cur >= prev
    except Exception:
        gaps.append("M1/M2 取数失败")

    # ── 信用面补充：社融增量 ──
    try:
        shrz = ak.macro_china_shrzgm()
        col = None
        for c in shrz.columns:
            if "增量" in str(c):
                col = c; break
        if col:
            cur, prev = _latest_two(shrz, col)
            if cur is not None and prev is not None:
                reads.append(f"社融增量{cur}亿（前值{prev}亿）")
                if credit_loose is None:
                    credit_loose = cur >= prev
    except Exception:
        gaps.append("社融 取数失败")

    # ── 景气面：PMI（辅助读，不进 regime 主判） ──
    try:
        pmi = ak.macro_china_pmi_yearly()
        cur, prev = _latest_two(pmi, "今值")
        if cur is not None:
            state = "扩张" if cur >= 50 else "收缩"
            reads.append(f"制造业PMI {cur}（{state}区间）")
    except Exception:
        gaps.append("PMI 取数失败")

    # ── 合成 regime ──
    if money_loose is None and credit_loose is None:
        regime = "数据待补"
    else:
        m = "宽货币" if money_loose else ("紧货币" if money_loose is False else "货币中性")
        c = "宽信用" if credit_loose else ("紧信用" if credit_loose is False else "信用中性")
        if money_loose is None:
            regime = c
        elif credit_loose is None:
            regime = m
        else:
            regime = f"{m}+{c}"

    read = "；".join(reads) if reads else "中国宏观数据暂缺"
    status = "已接入" if regime != "数据待补" else "数据缺口"
    return {"data": {"regime": regime}, "read": read, "status": status, "gaps": gaps}


# ════════════════════════════════════════════════════════════════════
#  L3 产业趋势 —— 从 L4 资金共识派生「未来6月最值得研究产业」
# ════════════════════════════════════════════════════════════════════

# L4 阶段 → 产业投资相位（产业≠板块：6个月视角看资金对产业方向的确认）
_STAGE_PHASE = {
    "赚钱效应": "加速",
    "资金流入": "加速",
    "一致性": "加速",
    "高潮": "兑现",
    "退潮": "退潮",
    "讨论": "潜伏",
}


def layer3_industry(l4raw) -> dict:
    """
    产业趋势判定（从 L4 主线派生，confirmed = 已被资金验证）。

    l4raw : L4 agent 的 raw（含 main_lines）。传 None 时回退读 sector_mainline.json。
    """
    gaps = []
    l4raw = l4raw or {}
    main_lines = l4raw.get("main_lines")
    if not main_lines:
        sm = _load_json("sector_mainline.json")
        main_lines = sm.get("top10_net_inflow") or sm.get("main_lines") or []
        if not main_lines:
            gaps.append("L4 主线数据缺失，产业趋势无法派生")
            return {"top_industries": [], "all_ranked": [],
                    "read": "L4 主线缺失，产业趋势暂无法派生。",
                    "status": "数据缺口", "gaps": gaps}

    # 过滤退潮，按 consensus_strength / stage_score 排序取头部作为「值得研究产业」
    ranked = []
    for m in main_lines:
        stage = m.get("stage", "")
        if stage == "退潮":
            continue
        strength = _num(m.get("consensus_strength")) or _num(m.get("stage_score")) or 0
        ranked.append((strength, m))
    ranked.sort(key=lambda x: x[0], reverse=True)

    # phase → 风险话术（产业相位视角）
    _PHASE_RISK = {
        "加速": "跟随主线，注意板块内轮动与放量真伪。",
        "兑现": "高潮/兑现区，谨防资金退潮与获利了结。",
        "潜伏": "尚未被资金验证，右侧确认前仅观察。",
        "退潮": "资金撤离，规避为主。",
    }

    def _mk(m):
        stage = m.get("stage", "")
        phase = _STAGE_PHASE.get(stage, "潜伏")
        # confirmed：进入 L4 主线即已获资金验证（加速/兑现相位为已确认）
        confirmed = phase in ("加速", "兑现")
        return {
            "name": m.get("sector", ""),
            "confirmed": confirmed,
            "phase": phase,
            "stage": stage,
            "consensus": _num(m.get("consensus_strength")),
            "net_5d": _num(m.get("net_5d")),
            # —— 以下字段供 decision_tree.render_l3（legacy HTML）渲染 ——
            # 本模块从 L4 资金共识派生，非独立产业模型，故 driver 统一标「资金驱动」
            "driver": "资金驱动",
            "catalyst": f"L4 资金共识（阶段：{stage or '—'}）",
            "verify": ("已被资金验证（进入 L4 主线）" if confirmed
                       else "尚未被资金验证（潜伏/待右侧）"),
            "risk": _PHASE_RISK.get(phase, "跟随主线，注意轮动。"),
            "matched_boards": [],  # 本派生路径不做板块级映射
        }

    all_ranked = [_mk(m) for _, m in ranked]
    top_industries = all_ranked[:6]

    if not top_industries:
        gaps.append("主线全部处退潮/讨论期，无加速产业")

    conf_names = [t["name"] for t in top_industries if t["confirmed"]]
    read = ("整体研判：" + (
        f"{'、'.join(conf_names[:3])} 已获资金验证，为未来6月重点研究产业。"
        if conf_names else "主线多处潜伏/讨论期，暂无资金强验证产业，以观察为主。"))
    status = "AI主导"
    return {"top_industries": top_industries, "all_ranked": all_ranked,
            "read": read, "status": status, "gaps": gaps}


# ════════════════════════════════════════════════════════════════════
#  L8 学习进化 —— trade_journal 交易日志统计 + 月度模式
# ════════════════════════════════════════════════════════════════════

# ── ⑧ trade_journal 列迁移（Phase 2：判断侧/执行侧分离）──
# 旧表只有「执行录入」字段；Phase 2 增加：
#   rec_type           : 'signal'(系统判断) | 'trade'(用户执行)  默认 'trade' 向后兼容
#   signal_id          : trade 行关联回源 signal 行的 id
#   ic_score           : 信号时刻加权 IC 评分/置信度（判断背景）
#   candidate_sectors  : JSON 字符串，当日候选主线板块列表
#   judge_result       : 判断回放 'right'|'wrong'|'na'（信号方向 vs 次日收益）
#   exec_result        : 执行回放 'executed'|'missed'|'pending'（用户是否跟单）
_JOURNAL_NEW_COLS = [
    ("rec_type", "TEXT NOT NULL DEFAULT 'trade'"),
    ("signal_id", "INTEGER"),
    ("ic_score", "REAL"),
    ("candidate_sectors", "TEXT"),
    ("judge_result", "TEXT NOT NULL DEFAULT ''"),
    ("exec_result", "TEXT NOT NULL DEFAULT ''"),
]


def _migrate_journal_table(conn):
    """幂等补列（SQLite 不支持 ADD COLUMN IF NOT EXISTS）。"""
    try:
        existing = {r[1] for r in conn.execute(
            "PRAGMA table_info(trade_journal)").fetchall()}
    except Exception:
        return
    for col, ddl in _JOURNAL_NEW_COLS:
        if col not in existing:
            try:
                conn.execute(
                    f"ALTER TABLE trade_journal ADD COLUMN {col} {ddl}")
            except Exception:
                pass


def _ensure_journal_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT, code TEXT, name TEXT, sector TEXT,
            action TEXT, reason TEXT, plan_stop TEXT,
            result TEXT, pnl REAL, note TEXT,
            created_at TEXT
        )
    """)
    _migrate_journal_table(conn)


def add_journal(trade_date, code, action, sector="", name="", reason="",
                plan_stop="", result="", pnl=None, note="",
                rec_type="trade", signal_id=None, ic_score=None,
                candidate_sectors="", judge_result="", exec_result=""):
    """录入一笔交易日志到 trade_journal 表。

    rec_type='trade'（默认，用户执行录入，向后兼容）或 'signal'（系统判断自动通电）。
    """
    conn = sqlite3.connect(DB)
    try:
        _ensure_journal_table(conn)
        conn.execute(
            "INSERT INTO trade_journal (trade_date, code, name, sector, action, "
            "reason, plan_stop, result, pnl, note, created_at, "
            "rec_type, signal_id, ic_score, candidate_sectors, "
            "judge_result, exec_result) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (trade_date, code, name, sector, action, reason, plan_stop,
             result, _num(pnl), note,
             datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             rec_type, signal_id, _num(ic_score), candidate_sectors,
             judge_result, exec_result))
        conn.commit()
    finally:
        conn.close()


def interactive_add():
    """交互式录入一笔（CLI）。"""
    print("== 录入一笔交易（⑧ 学习进化闭环）==")
    trade_date = input("交易日 YYYY-MM-DD: ").strip()
    code = input("代码: ").strip()
    name = input("名称: ").strip()
    sector = input("板块: ").strip()
    action = input("买/卖/观察 [买]: ").strip() or "买"
    reason = input("买入逻辑: ").strip()
    plan_stop = input("计划止损: ").strip()
    result = input("胜/负/持有: ").strip()
    pnl_s = input("盈亏%(可空): ").strip()
    note = input("备注: ").strip()
    add_journal(trade_date, code, action, sector=sector, name=name,
                reason=reason, plan_stop=plan_stop, result=result,
                pnl=_num(pnl_s) if pnl_s else None, note=note)
    print(f"✅ 已记录 {trade_date} {code} {name} ({action})")


# ═══════════════════════════════════════════════════════════════════
#  Phase 2 —— 交易日志「通电」：系统判断自动落库 + 判断/执行分离回放
# ═══════════════════════════════════════════════════════════════════

def log_daily_signals(memo, top_n_sectors=3, top_n_stocks=5) -> int:
    """在 produce() 末尾调用：把当日系统决策（候选主线板块 → 板块内 Capital Score
    Top 个股）自动写入 trade_journal 作为 rec_type='signal' 记录（判断侧）。

    仅在 IC 给出可操作方向（YES/CAUTION）时记录，避免把「观察」污染执行统计。
    幂等：同日同代码 signal 不重复写入。返回写入条数。
    """
    trade_date = getattr(memo, "trade_date", "") or ""
    if not trade_date:
        return 0
    can_buy = str(getattr(memo, "can_buy", "") or "").upper()
    if can_buy not in ("YES", "CAUTION"):
        return 0  # 不可操作 → 不落信号

    try:
        from capital_score import sector_top_stocks
    except Exception:
        return 0

    committee = getattr(memo, "committee", {}) or {}
    ic_score = getattr(memo, "confidence_overall", 0) or 0
    position_pct = committee.get("position_pct", "")
    mains = getattr(memo, "main_lines", []) or []
    sectors = [getattr(m, "sector", "") for m in mains[:top_n_sectors]
               if getattr(m, "sector", "")]
    if not sectors:
        return 0

    # 板块 → 星级 映射（reason 用）
    star_of = {getattr(m, "sector", ""): getattr(m, "star_rating", "")
               for m in mains if getattr(m, "sector", "")}

    conn = sqlite3.connect(DB)
    try:
        _ensure_journal_table(conn)
        seen = {r[0] for r in conn.execute(
            "SELECT code FROM trade_journal "
            "WHERE trade_date=? AND rec_type='signal'", (trade_date,)).fetchall()}
        cand_json = json.dumps(sectors, ensure_ascii=False)
        n = 0
        for sec in sectors:
            try:
                recs = sector_top_stocks(trade_date, sec, top_n_stocks) or []
            except Exception:
                recs = []
            for r in recs:
                code = str(r.get("code", "")).strip()
                if not code or code in seen:
                    continue
                name = r.get("name", "")
                star = star_of.get(sec, "")
                reason = (f"IC={can_buy} 仓位{position_pct} | 板块「{sec}」星级{star} "
                          f"| CapitalScore={float(r.get('score', 0) or 0):.1f}")
                add_journal(trade_date, code, "买", sector=sec, name=name,
                            reason=reason, ic_score=ic_score,
                            candidate_sectors=cand_json, rec_type="signal")
                seen.add(code)
                n += 1
        return n
    finally:
        conn.close()


def reconcile_journal(as_of=None) -> dict:
    """回放 trade_journal，区分「判断」与「执行」两类错误：

    · 判断侧 judge_result：对 rec_type='signal' 且 action='买' 的行，用
      「信号日收盘 → 下一交易日收盘」收益率判定 right/wrong；无方向押注(观察)标 na。
    · 执行侧 exec_result：用 rec_type='trade' 的录入（按 code 命中，或显式 signal_id）
      判定该信号是否被跟单 executed；信号日后超 5 交易日仍无跟单标 missed；否则 pending。

    回写 judge_result/exec_result 到表，并返回聚合指标：
      judgment.rate        = 判断命中率（right/(right+wrong)）
      execution.capture_rate = 判断对但用户跟单的比例（执行纪律）
      execution.discipline_error = 判断对没跟(错过利润) + 判断错还跟(逆向) 的次数
    """
    if as_of is None:
        as_of = datetime.date.today().isoformat()
    try:
        conn = sqlite3.connect(DB)
        _ensure_journal_table(conn)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM trade_journal").fetchall()]
        cal = [d[0] for d in conn.execute(
            "SELECT DISTINCT date FROM stock_daily ORDER BY date").fetchall()]
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e),
                "judgment": {}, "execution": {}}

    cal_set = set(cal)

    def _ntd(d):
        if d in cal_set:
            i = cal.index(d)
            return cal[i + 1] if i + 1 < len(cal) else None
        for c in cal:
            if c >= d:
                return c
        return None

    def _close(d, code):
        row = conn.execute(
            "SELECT close FROM stock_daily WHERE date=? AND code=?",
            (d, code)).fetchone()
        return row[0] if row else None

    signals = [r for r in rows if r.get("rec_type") == "signal"]
    trades = [r for r in rows if r.get("rec_type") == "trade"]

    judge_map, exec_map = {}, {}
    for s in signals:
        sid = s["id"]
        td = s.get("trade_date", "")
        code = str(s.get("code", ""))
        if s.get("judge_result") in ("right", "wrong", "na"):
            judge_map[sid] = s["judge_result"]
            continue
        if s.get("action") != "买":
            judge_map[sid] = "na"
            continue
        nx = _ntd(td)
        if not nx:
            judge_map[sid] = "pending"
            continue
        c0, c1 = _close(td, code), _close(nx, code)
        if c0 in (None, 0) or c1 is None:
            judge_map[sid] = "pending"
            continue
        judge_map[sid] = "right" if (c1 - c0) / c0 * 100 > 0 else "wrong"

    for s in signals:
        sid = s["id"]
        code = str(s.get("code", ""))
        td = s.get("trade_date", "")
        linked = [t for t in trades
                  if str(t.get("code", "")) == code
                  and (t.get("signal_id") == sid or t.get("trade_date", "") >= td)]
        if linked:
            exec_map[sid] = "executed"
        elif td < as_of and td in cal_set and cal.index(td) + 5 < len(cal):
            exec_map[sid] = "missed"
        else:
            exec_map[sid] = "pending"

    # 回写（仅已确定的）
    for sid, jr in judge_map.items():
        if jr in ("right", "wrong", "na"):
            conn.execute("UPDATE trade_journal SET judge_result=? WHERE id=?",
                         (jr, sid))
    for sid, er in exec_map.items():
        if er in ("executed", "missed"):
            conn.execute("UPDATE trade_journal SET exec_result=? WHERE id=?",
                         (er, sid))
    conn.commit()
    conn.close()

    j_right = sum(1 for v in judge_map.values() if v == "right")
    j_wrong = sum(1 for v in judge_map.values() if v == "wrong")
    j_na = sum(1 for v in judge_map.values() if v == "na")
    j_pending = sum(1 for v in judge_map.values() if v == "pending")
    j_n = j_right + j_wrong
    j_rate = round(j_right / j_n * 100, 1) if j_n else None

    right_ids = [sid for sid, v in judge_map.items() if v == "right"]
    wrong_ids = [sid for sid, v in judge_map.items() if v == "wrong"]
    executed_right = sum(1 for sid in right_ids if exec_map.get(sid) == "executed")
    missed_right = sum(1 for sid in right_ids if exec_map.get(sid) == "missed")
    acted_on_wrong = sum(1 for sid in wrong_ids if exec_map.get(sid) == "executed")
    capture_rate = round(executed_right / len(right_ids) * 100, 1) if right_ids else None

    return {
        "ok": True,
        "judgment": {"right": j_right, "wrong": j_wrong, "na": j_na,
                     "pending": j_pending, "n": j_n, "rate": j_rate},
        "execution": {"executed": executed_right, "missed_profit": missed_right,
                      "acted_on_wrong": acted_on_wrong,
                      "n_directional": len(right_ids) + len(wrong_ids),
                      "capture_rate": capture_rate,
                      "discipline_error": missed_right + acted_on_wrong},
    }


def _win_rate(rows):
    """rows: [{result, pnl}]。胜率 = 胜/(胜+负)，持有不计入。"""
    wins = sum(1 for r in rows if str(r.get("result")) == "胜")
    losses = sum(1 for r in rows if str(r.get("result")) == "负")
    denom = wins + losses
    if denom == 0:
        return None
    return round(wins / denom * 100, 1)


def _pnl_stats(rows):
    pnls = [_num(r.get("pnl")) for r in rows if _num(r.get("pnl")) is not None]
    if not pnls:
        return None, None
    return round(sum(pnls), 2), round(sum(pnls) / len(pnls), 2)


def monthly_pattern() -> dict:
    """
    交易日志的月度 / 板块胜率统计，供 learning_feedback 反哺 + CLI stats。

    无记录时优雅返回 count=0（不报错），由 learning_feedback 判为「样本积累中」。
    """
    try:
        conn = sqlite3.connect(DB)
        _ensure_journal_table(conn)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM trade_journal ORDER BY trade_date").fetchall()]
        conn.close()
    except Exception as e:
        return {"count": 0, "win_rate": None, "by_month": {}, "by_sector": {},
                "insights": [], "read": f"交易日志读取失败：{type(e).__name__}",
                "gaps": [f"trade_journal 读取失败：{type(e).__name__}"]}

    n_signal = sum(1 for r in rows if r.get("rec_type") == "signal")
    n_trade = sum(1 for r in rows if r.get("rec_type") == "trade")
    count = n_trade  # 兼容性：learning_agent 置信度 / 下游以「执行录入」为准

    # 仅执行录入参与月度/板块胜率与盈亏（signal 无 result/pnl）
    trade_rows = [r for r in rows if r.get("rec_type") == "trade"]

    if n_signal == 0 and n_trade == 0:
        return {"count": 0, "win_rate": None, "by_month": {}, "by_sector": {},
                "insights": [],
                "read": "交易日志暂无记录。produce() 会自动把系统判断写入；录入实际交易后启动执行纪律统计。",
                "n_signal": 0, "n_trade": 0, "judgment": {}, "execution": {}, "gaps": []}

    # 按月（执行录入）
    by_month = {}
    m_group = defaultdict(list)
    for r in trade_rows:
        mkey = str(r.get("trade_date", ""))[:7]
        m_group[mkey].append(r)
    for m, rs in m_group.items():
        psum, pavg = _pnl_stats(rs)
        by_month[m] = {"n": len(rs), "win_rate": _win_rate(rs),
                       "pnl_sum": psum, "pnl_avg": pavg}

    # 按板块（执行录入）
    by_sector = {}
    s_group = defaultdict(list)
    for r in trade_rows:
        skey = r.get("sector") or "未分类"
        s_group[skey].append(r)
    for s, rs in s_group.items():
        _, pavg = _pnl_stats(rs)
        by_sector[s] = {"n": len(rs), "win_rate": _win_rate(rs), "pnl_avg": pavg}

    overall_wr = _win_rate(trade_rows)
    total_pnl, avg_pnl = _pnl_stats(trade_rows)

    # 自动迭代建议
    insights = []
    ranked = sorted([(s, v) for s, v in by_sector.items() if v["win_rate"] is not None],
                    key=lambda kv: kv[1]["win_rate"], reverse=True)
    if ranked:
        best = ranked[0]
        insights.append(f"胜率最高板块：{best[0]}（{best[1]['win_rate']}%/{best[1]['n']}笔）→ 后续可加权关注")
        if len(ranked) > 1:
            worst = ranked[-1]
            if worst[1]["win_rate"] is not None and worst[1]["win_rate"] < 40:
                insights.append(f"胜率偏低板块：{worst[0]}（{worst[1]['win_rate']}%）→ 收紧或规避")

    # 判断/执行分离回放
    try:
        rec = reconcile_journal()
    except Exception:
        rec = None
    judgment = rec.get("judgment", {}) if rec else {}
    execution = rec.get("execution", {}) if rec else {}

    # 合成 read（区分信号 / 执行 / 判断）
    parts = []
    if n_signal > 0:
        jr = judgment.get("rate")
        parts.append(f"系统信号 {n_signal} 条" + (f"，判断命中率 {jr}%"
                     if jr is not None else "（判断回放积累中）"))
    if n_trade > 0:
        parts.append(f"执行录入 {n_trade} 笔，总胜率 {overall_wr}%")
    else:
        parts.append("尚未录入实际交易（执行纪律待积累）")
    read = "；".join(parts) + "。"

    return {"count": count, "win_rate": overall_wr,
            "avg_pnl": avg_pnl, "total_pnl": total_pnl,
            "by_month": by_month, "by_sector": by_sector,
            "insights": insights, "read": read,
            "status": "已通电" if n_signal else "未接入",
            "n_signal": n_signal, "n_trade": n_trade,
            "judgment": judgment, "execution": execution, "gaps": []}


def layer8_learning() -> dict:
    """
    L8 层封装：返回 monthly_pattern 的完整统计（超集），并合成 read。

    两类消费方：
      · brain/agents/learning_agent 只读 {count, read, gaps}；
      · decision_tree.render_learning 需 {count, by_month, by_sector, insights,
        win_rate, avg_pnl, total_pnl, status}。
    返回超集同时满足两者（agent 忽略多余字段无害）。
    """
    stat = monthly_pattern()
    count = stat.get("count", 0)
    if count == 0:
        read = "⑧ 学习进化：交易日志暂无记录，录入首笔后启动历史胜率反哺（板块偏置+仓位缩放）。"
    else:
        read = stat.get("read", "")
        if stat.get("insights"):
            read += " " + "；".join(stat["insights"][:2])
    out = dict(stat)
    out["count"] = count
    out["read"] = read
    return out


if __name__ == "__main__":
    import json
    print("=== layer1_global ===")
    print(json.dumps(layer1_global(), ensure_ascii=False, indent=1, default=str)[:800])
    print("=== layer2_china ===")
    print(json.dumps(layer2_china(), ensure_ascii=False, indent=1, default=str)[:800])
    print("=== layer3_industry ===")
    print(json.dumps(layer3_industry(None), ensure_ascii=False, indent=1, default=str)[:800])
    print("=== layer8_learning ===")
    print(json.dumps(layer8_learning(), ensure_ascii=False, indent=1, default=str)[:400])
