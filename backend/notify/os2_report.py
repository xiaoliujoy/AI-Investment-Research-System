# -*- coding: utf-8 -*-
"""Trading OS —— 唯一裁决 · 驾驶舱首屏 · 信息压缩版日报生成器
====================================================

设计原则（用户 2026-07-18 评审结论：3.0 不新增任何分析能力，只做 4 件事）：
  不新增任何分析 Agent / 模块；只消费 cio_agent.produce() 已构建的
  InvestmentDecisionMemo（复用全部既有引擎）：

  1. 唯一裁决（P0，最大 bug）：resolve_decision() = 评分阶梯 → IC 闸门 →
     系统安检闸门（0 通过=一票否决 NO）→ 取最保守 → Learning 自校准修正 = Final。
     全报告只认这一个结论；市场状态从 Final 反推（NO 永不显示「偏强」）；
     仓位只留单一终值，推导链进折叠附录。评分固定映射：≥80 YES/65-79 CAUTION/<65 NO。
  2. 信息压缩（≤2 屏）：驾驶舱首屏 8 项一屏读完；候选瘦身为名称+级别+一理由一风险；
     正文只留 SOXX/黄金/原油关键数字，原始数据全部折叠进附录。
  3. 行动导向：盯盘清单每行「满足→动作 / 不满足→动作」；驾驶舱直给回避/观察点/风险。
  4. 强化学习：IC 方向命中率首屏即见；命中率<40% 自动降级并在裁决链标注。

报告结构（3.0，带 P0~P3 优先级标记）：
  驾驶舱 Cockpit               (首屏 8 项 + 学习一行)
  执行摘要 Executive Summary   (P0，slim)
  系统安检 Pre-flight          (P0，闸门前置：0 通过→NO 并置灰)
  最终裁决 Decision            (P0，唯一裁决器)
  盯盘清单 Watch List          (P0，动作化)
  候选主线 Candidate           (P0，瘦身)
  为什么   Why                (P1，含关键数字)
  失效条件 Risk                (P1)
  系统学习 Learning            (P2)
  今日 Alpha                   (P2)
  附录     Appendix            (P3，折叠：裁决推导链 + 原始数据)

入口：
  from notify.os2_report import write
  write(memo, "output/memo_2026-07-17.html")
  CLI: python notify/os2_report.py            # produce() + 写 memo_{trade_date}.html
      python notify/os2_report.py --dry-run    # 只打印，不写盘
"""
import os
import sys
import html
import datetime
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 龙头资金层：Capital Score 100 分模型（OS 4.0 Phase 1）
import capital_score as cs
from capital_score import W_FUND, W_SECTOR, W_LEADER, W_ACTIVE

# IC 决策基准权重（与 learning_center._BASE_DECISION_WEIGHTS 一致）
DEFAULT_WEIGHTS = {"资金": 40, "产业": 25, "宏观": 15, "技术": 10, "风险": 10, "估值": 0}


# ═══════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════
def _esc(s):
    return html.escape("" if s is None else str(s))


def _stars(n):
    n = max(0, min(5, int(round(n or 0))))
    return "★" * n + "☆" * (5 - n)


def _dim_score(direction):
    """方向 → 0/50/100 分。"""
    if direction in ("bullish", "neutral_bullish"):
        return 100
    if direction in ("bearish", "bearish_weak"):
        return 0
    return 50


def _sb_dir(memo, layer):
    sb = (memo.committee or {}).get("scoreboard") or []
    for r in sb:
        if isinstance(r, dict) and r.get("layer") == layer:
            return r.get("direction")
    return None


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _map_can_buy(cb):
    return {"YES": "YES", "CAUTION": "CAUTION", "NO": "NO"}.get(cb, "NO")


def _key_numbers(memo):
    """正文只保留少量跨资产关键数字（SOXX / 黄金 / 原油），其余进折叠附录。"""
    gx = memo.global_market
    if not gx or not getattr(gx, "board", None):
        return ""
    want = [("半导体", "SOXX"), ("SOXX", "SOXX"), ("黄金", "黄金"),
            ("GOLD", "黄金"), ("原油", "原油"), ("油", "原油")]
    out, seen = [], set()
    for b in gx.board:
        nm = b.get("name", "") or ""
        chg = b.get("change_pct")
        if chg is None:
            continue
        for kw, label in want:
            if kw in nm and label not in seen:
                sign = "+" if chg >= 0 else ""
                out.append(f"{label} {sign}{chg:.1f}%")
                seen.add(label)
                break
    return " · ".join(out)


# ═══════════════════════════════════════════════════════
#  加权 IC 综合评分（透明、可解释）
# ═══════════════════════════════════════════════════════
def compute_weighted_score(memo):
    """从 memo 派生 6 维子分 → 按（可动态校准的）权重合成复合分。"""
    # 权重：优先用 Learning 核心校准后的权重，否则用基准
    sw = (memo.learning or {}).get("suggested_weights") or {}
    weights = (sw.get("suggested") if sw.get("applied") else None) or dict(DEFAULT_WEIGHTS)
    weight_src = "learning" if (sw.get("applied")) else "base"

    # —— 资金（40）——
    mig_r = (memo.migration or {}).get("rating") or 0          # 0-5
    flow = getattr(memo.cross_asset, "flow_score_overall", 0) or 0  # 0-100
    sb_L4 = _dim_score(_sb_dir(memo, "L4"))
    capital = 0.4 * (mig_r / 5.0 * 100) + 0.3 * flow + 0.3 * sb_L4

    # —— 产业（25）——
    sb_L3 = _dim_score(_sb_dir(memo, "L3"))
    sb_L3_5 = _dim_score(_sb_dir(memo, "L3_5"))
    industry = (sb_L3 + sb_L3_5) / 2.0

    # —— 宏观（15）——
    sb_L1 = _dim_score(_sb_dir(memo, "L1"))
    sb_L2 = _dim_score(_sb_dir(memo, "L2"))
    macro = (sb_L1 + sb_L2) / 2.0

    # —— 技术（10）——
    mls = memo.main_lines or []
    avg_star = (sum(m.star_rating for m in mls[:5]) / len(mls[:5]) * 20.0) if mls[:5] else 50.0
    sb_L5 = _dim_score(_sb_dir(memo, "L5"))
    sent = _dim_score(_sb_dir(memo, "sentiment"))
    tech = 0.5 * avg_star + 0.3 * sb_L5 + 0.2 * (sent if sent is not None else 50.0)

    # —— 估值（参考，权重 0）——
    sb_fund = _dim_score(_sb_dir(memo, "fundamental"))
    valuation = sb_fund if sb_fund is not None else 50.0

    # —— 风险（10）：can_buy + 证伪条件数 反向 ——
    cb = memo.can_buy
    base = 100 if cb == "YES" else 60 if cb == "CAUTION" else 30
    n_fals = len((memo.risk or None) and (memo.risk.falsification or []))
    risk = max(5, min(95, base - n_fals * 6))

    dims = {
        "资金": max(0, min(100, round(capital))),
        "产业": max(0, min(100, round(industry))),
        "宏观": max(0, min(100, round(macro))),
        "技术": max(0, min(100, round(tech))),
        "估值": max(0, min(100, round(valuation))),
        "风险": max(0, min(100, round(risk))),
    }

    # 复合分（仅用有权重的 5 维，估值作参考不参与）
    wsum = sum(weights[g] for g in ("资金", "产业", "宏观", "技术", "风险"))
    composite = sum(dims[g] * weights[g] for g in ("资金", "产业", "宏观", "技术", "风险"))
    composite = round(composite / wsum) if wsum else 0

    # 评分阶梯（用户固定映射：≥80 YES / 65-79 CAUTION / <65 NO）
    # 注意：这里只产出「评分阶梯」的初判，最终裁决由 resolve_decision() 综合三闸门取最保守。
    if composite >= 80:
        verdict, dec = "可以买", "YES"
    elif composite >= 65:
        verdict, dec = "谨慎参与", "CAUTION"
    else:
        verdict, dec = "不交易", "NO"
    ic_agree = (dec == _map_can_buy(cb))

    return {
        "dims": dims,
        "weights": weights,
        "weight_src": weight_src,
        "composite": composite,
        "verdict": verdict,
        "decision": dec,
        "ic_agree": ic_agree,
        "ic_can_buy": cb,
    }


# ═══════════════════════════════════════════════════════
#  唯一裁决器 resolve_decision（Trading OS 核心 · P0）
#  解决「四把嗓子打架」：评分阶梯 / IC 投票 / 系统安检 三闸门，
#  经 Learning 自校准修正后，取最保守 = Final。全报告只认这一个结论。
# ═══════════════════════════════════════════════════════
_LEVEL = {"NO": 0, "CAUTION": 1, "YES": 2}
_LEVEL_INV = {0: "NO", 1: "CAUTION", 2: "YES"}
_VERDICT_LABEL = {"YES": "可以买", "CAUTION": "谨慎参与", "NO": "不交易"}


def _score_level(composite):
    """用户固定映射：≥80 YES / 65-79 CAUTION / <65 NO。"""
    if composite >= 80:
        return "YES"
    if composite >= 65:
        return "CAUTION"
    return "NO"


def _derive_market_state(final, comp):
    """市场状态从最终裁决反推——NO 永不显示「偏强」，杜绝口径打架。"""
    if final == "NO":
        return "退潮 · 空仓" if comp < 42 else "偏弱 · 防守"
    if final == "CAUTION":
        return "结构牛 · 分化" if comp >= 68 else "震荡 · 精选"
    return "强结构牛" if comp >= 80 else "结构牛"


def _resolve_position(memo, final):
    """单一终值仓位：NO 强制空仓，其余用 IC+Learning 反哺后的护栏值。"""
    if final == "NO":
        return "0%（空仓）"
    pos = (memo.position_pct or "").strip()
    return pos or "—"


def resolve_decision(memo, score):
    """唯一裁决器：评分阶梯 → IC 闸门 → 系统安检闸门 → 取最保守 → Learning 修正 = Final。

    返回全报告唯一权威结论；市场状态 / 仓位 / 派生链均由此产出。
    """
    chain = []
    comp = score["composite"]

    # ① 评分阶梯
    score_lv = _score_level(comp)
    chain.append(f"评分阶梯：综合 {comp} → {score_lv}（≥80 YES／65-79 CAUTION／<65 NO）")

    # ② IC 加权投票闸门
    ic_lv = _map_can_buy(memo.can_buy)
    chain.append(f"IC 加权投票：{_esc(memo.can_buy)} → {ic_lv}")

    # ③ 系统安检闸门（0 通过 = 一票否决 NO；否则用安检「基线」结论，避免与 Learning 重复降级）
    levels = [score_lv, ic_lv]
    pf = memo.preflight or {}
    pf_level = None
    pc = pf.get("passed_count", 0)
    tc = pf.get("total_count", 0)
    pf_hard_no = False
    if pf and not pf.get("error"):
        cal = pf.get("calibration") or {}
        base_v = cal.get("base_verdict") or pf.get("verdict")
        if pc == 0:
            pf_level, pf_hard_no = "NO", True
            chain.append(f"系统安检：通过 0/{tc} → NO（一票否决）")
        elif base_v in _LEVEL:
            pf_level = base_v
            chain.append(f"系统安检：通过 {pc}/{tc} → {pf_level}")
        if pf_level:
            levels.append(pf_level)

    # 取三闸门最保守
    final_lv = min(_LEVEL[x] for x in levels)
    final = _LEVEL_INV[final_lv]
    chain.append(f"取三闸门最保守 → {final}")

    # ③-b 数据健康闸门（Data Integrity Layer：失败 = 禁止交易，绝对否决，优先级最高）
    dh = getattr(memo, "data_health", None) or {}
    health_failed = bool(dh.get("failed"))
    if health_failed:
        final = "NO"
        chain.append(f"数据健康：{dh.get('summary', '未通过')} → NO（禁止交易）")

    # ④ Learning 自校准修正（IC 方向命中率 <40% 且样本≥2 → 再降一级）
    lr = memo.learning or {}
    acc = lr.get("ic_accuracy")
    n_rep = lr.get("n_replayed", 0) or 0
    learning_downgrade = False
    if acc is not None and n_rep >= 2 and acc < 40 and final != "NO":
        final = _LEVEL_INV[max(0, _LEVEL[final] - 1)]
        learning_downgrade = True
        chain.append(f"Learning 自校准：IC 命中率 {acc}%（{n_rep}日回放）<40% → 再降一级 → {final}")

    market_state = _derive_market_state(final, comp)
    if health_failed:
        market_state = "数据异常 · 禁止交易"
    position = _resolve_position(memo, final)

    return {
        "final": final,
        "verdict_label": _VERDICT_LABEL[final],
        "composite": comp,
        "score_level": score_lv,
        "ic_level": ic_lv,
        "ic_can_buy": memo.can_buy,
        "pf_level": pf_level,
        "pf_passed": pc,
        "pf_total": tc,
        "pf_hard_no": pf_hard_no,
        "health_failed": health_failed,
        "health": dh,
        "learning_downgrade": learning_downgrade,
        "ic_accuracy": acc,
        "n_replayed": n_rep,
        "market_state": market_state,
        "position": position,
        "chain": chain,
        "ic_agree": (ic_lv == score_lv),
    }


# ═══════════════════════════════════════════════════════
#  驾驶舱 Cockpit（首屏 8 项 · 3 秒看懂今天怎么办）
# ═══════════════════════════════════════════════════════
def compute_cockpit(memo, score, decision, es, alpha):
    """飞机驾驶舱式首屏：🎯裁决 📊评分 💰仓位 🔥主线 ❌回避 ⏰观察点 ⚠风险 🌟Alpha + 学习一行。"""
    # 🔥 主线（第一候选）
    main = "—"
    mls = memo.main_lines or []
    if mls:
        m = mls[0]
        main = f"{m.sector} {_stars(m.star_rating)}"

    # ❌ 回避（第一条）
    avoid = es["avoid"][0] if es["avoid"] else "—"

    # ⏰ 第一观察点
    first_obs = ""
    for a in (memo.action_list or []):
        if isinstance(a, dict) and a.get("time"):
            first_obs = f'{a.get("time")} {a.get("action")}'
            break
    if not first_obs:
        first_obs = es["most_important"]

    # ⚠ 最大风险
    biggest = (memo.risk.biggest_risk if memo.risk and getattr(memo.risk, "biggest_risk", "") else "") or "—"

    # 📚 学习一行（首屏即见）
    acc = decision.get("ic_accuracy")
    n_rep = decision.get("n_replayed", 0)
    if acc is not None and n_rep >= 1:
        learn_line = f"IC 方向命中率 {acc}%（{n_rep}日回放）"
        if decision.get("learning_downgrade"):
            learn_line += " · 已触发自动降级"
    else:
        learn_line = "学习样本积累中（回放≥2次启用自校准）"

    alpha_txt = (alpha or "").replace("🌟", "").strip()

    return {
        "final": decision["final"],
        "verdict": decision["verdict_label"],
        "composite": score["composite"],
        "position": decision["position"],
        "market_state": decision["market_state"],
        "main": main,
        "avoid": avoid,
        "first_obs": first_obs,
        "biggest_risk": biggest,
        "alpha": alpha_txt,
        "learn_line": learn_line,
    }


# ═══════════════════════════════════════════════════════
#  执行摘要 Executive Summary（首页，1 分钟读完）
# ═══════════════════════════════════════════════════════
def compute_executive_summary(memo, score, decision):
    market_state = decision["market_state"]
    comp = score["composite"]
    stars = max(0, min(5, round(comp / 20.0)))

    # 一句话结论（结论口径统一取自 decision.final）
    thesis = (memo.migration or {}).get("thesis") or (memo.thesis.headline if memo.thesis else "")
    thesis = thesis.strip()
    final = decision["final"]
    if final == "NO":
        act = "今日不交易，等待条件满足。"
    elif final == "CAUTION":
        act = "只看龙头，不追板块。"
    else:
        act = "可择优买入，严格看图确认买点。"
    one_liner = (thesis + " " + act).strip()
    if len(one_liner) > 90:
        one_liner = one_liner[:88] + "…"

    # 可以做（资金实际流入方向优先，其次主线候选）
    can_do = []
    rot_in = ((memo.migration or {}).get("rotation", {}) or {}).get("in_top", []) or []
    can_do += rot_in[:3]
    for op in (memo.trading_plan.opportunities or []):
        name = op.get("name") if isinstance(op, dict) else getattr(op, "name", "")
        can_do.append(name)
    can_do = _dedupe([c for c in can_do if c])[:4]
    if not can_do:
        can_do = ["（暂无明确机会，观望为主）"]

    # 不要做
    avoid = []
    av = (memo.migration or {}).get("avoid")
    if av:
        avoid += av if isinstance(av, list) else [av]
    hard = (memo.debate or {}).get("hard_no") or []
    avoid += hard
    if memo.trading_plan.no_opportunity:
        avoid.append("主线未确认，不强行交易")
    avoid = _dedupe([a for a in avoid if a])
    if not avoid:
        avoid = ["（暂无明确风险，按主线纪律执行）"]

    # 今天最重要的一件事
    most = ""
    al = memo.action_list or []
    for a in al:
        if isinstance(a, dict) and a.get("time") == "10:00":
            most = f"{a.get('time')} {a.get('action')}"
            break
    if not most and len(al) >= 2:
        a = al[1]
        most = f"{a.get('time')} {a.get('action')}" if isinstance(a, dict) else str(a)
    if not most:
        most = (memo.migration or {}).get("what_to_do") or (memo.migration or {}).get("focus") or "盯住资金主线，确认放量"

    return {
        "market_state": market_state,
        "stars": stars,
        "one_liner": one_liner,
        "can_do": can_do,
        "avoid": avoid,
        "position": decision["position"],
        "most_important": most,
        # 口吻与最终裁决对齐：NO 时不写「可以做」，改「观察方向 / 禁止」，消除首页口径冲突
        "do_label": ("🔍 观察方向" if final == "NO" else "✅ 可以做"),
        "avoid_label": ("🚫 禁止" if final == "NO" else "❌ 不要做"),
        "trade_status": f"交易状态：{_VERDICT_LABEL[final]}",
    }


# ═══════════════════════════════════════════════════════
#  今日 Alpha（一句话可沉淀认知资产）
# ═══════════════════════════════════════════════════════
def compute_alpha(memo):
    # 1) 跨资产背离：ETF 净申购但美股半导体跌 → 主导是国内资金
    cf = memo.capital_flow
    gx = memo.global_market or None
    etf_buy = (getattr(cf, "etf_total_net_yi", 0) or 0) > 0
    soxx = None
    if gx is not None:
        for b in (gx.board or []):
            if isinstance(b, dict) and b.get("name") == "SOXX半导体ETF":
                soxx = b
    soxx_down = soxx and soxx.get("change_pct") is not None and soxx["change_pct"] < 0
    if etf_buy and soxx_down:
        return ("🌟 ETF 继续净申购、SOXX 虽跌但 A 股资金未跟跌 —— "
                "今日真正主导市场的是国内资金，应看 ETF 而非美股。")

    # 2) 跨资产合成句（资金迁移引擎产出）
    ca = (memo.migration or {}).get("cross_asset") or {}
    sentence = ca.get("sentence", "")
    if sentence:
        return "🌟 " + sentence

    # 3) 今日新发现（关系/规律引擎）
    if getattr(memo.observation, "has_data", False) and getattr(memo.observation, "headline", ""):
        return "🌟 " + memo.observation.headline

    # 4) 诚实兜底：资金驱动但原因未知
    unk = (memo.causal or {}).get("unknown_list") or []
    if unk:
        return "🌟 今日 " + "、".join(unk[:2]) + " 原因未知，属资金驱动，继续观察。"

    # 5) 最后兜底
    return "🌟 " + ((memo.migration or {}).get("thesis") or "市场信号中性，今日以观察为主。")


# ═══════════════════════════════════════════════════════
#  HTML 渲染（Trading OS 2.0）
# ═══════════════════════════════════════════════════════
CSS = """
* { box-sizing: border-box; }
body { margin:0; background:#eef1f5; font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; color:#1c2733; }
.wrap { max-width:840px; margin:0 auto; padding:18px 16px 60px; }
.topbar { background:linear-gradient(135deg,#0b1f33,#14304d); color:#fff; border-radius:14px; padding:20px 22px; margin-bottom:16px; }
.topbar h1 { margin:0 0 4px; font-size:22px; letter-spacing:1px; }
.topbar .meta { font-size:13px; opacity:.8; }
.topbar .comp { float:right; text-align:center; }
.topbar .comp .num { font-size:34px; font-weight:800; line-height:1; }
.topbar .comp .lbl { font-size:11px; opacity:.8; }
.sec { background:#fff; border-radius:12px; padding:16px 18px; margin-bottom:14px; box-shadow:0 1px 3px rgba(20,40,70,.08); }
.sech { display:flex; align-items:center; justify-content:space-between; margin:0 0 12px; }
.sech .t { font-size:16px; font-weight:700; }
.sech .t small { font-weight:400; opacity:.5; font-size:12px; margin-left:6px; }
.pchip { font-size:11px; font-weight:700; padding:2px 8px; border-radius:20px; color:#fff; }
.p0 { background:#e0532a; } .p1 { background:#c79a16; } .p2 { background:#2f7dac; } .p3 { background:#7a8694; }
.stars { font-size:26px; color:#f5a623; letter-spacing:2px; }
.oneline { font-size:15px; line-height:1.5; margin:6px 0 12px; }
.trading-status { font-size:13px; font-weight:700; color:#14304d; background:#eef3f8; border-radius:8px; padding:5px 10px; margin:0 0 10px; display:inline-block; }
.duo { display:flex; gap:14px; flex-wrap:wrap; }
.duo > div { flex:1; min-width:240px; }
.do h4, .dont h4 { margin:0 0 6px; font-size:13px; }
.do h4 { color:#1a8a4f; } .dont h4 { color:#cf3b2f; }
.li { font-size:14px; line-height:1.7; padding-left:18px; position:relative; }
.li.ok::before { content:"✅"; position:absolute; left:0; }
.li.no::before { content:"❌"; position:absolute; left:0; }
.pos { font-size:15px; font-weight:700; color:#0b1f33; background:#f0f4f8; display:inline-block; padding:4px 14px; border-radius:8px; }
.mi { margin-top:10px; font-size:14px; background:#fff7e6; border-left:4px solid #f5a623; padding:8px 12px; border-radius:6px; }
.scoregrid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.dcard { border:1px solid #e4e9ef; border-radius:10px; padding:10px 12px; }
.dcard .dn { font-size:12px; color:#5a6b7b; display:flex; justify-content:space-between; }
.dcard .dv { font-size:24px; font-weight:800; }
.dcard .dw { font-size:11px; color:#8a96a3; }
.verdict { font-size:20px; font-weight:800; margin:10px 0; }
.verdict.yes { color:#1a8a4f; } .verdict.caution { color:#c79a16; } .verdict.no { color:#cf3b2f; }
.agree { font-size:12px; color:#5a6b7b; }
.watch { border-left:3px solid #2f7dac; padding-left:12px; }
.wrow { display:flex; gap:10px; padding:6px 0; border-bottom:1px dashed #eef1f5; font-size:14px; }
.wrow:last-child { border-bottom:none; }
.wrow .wt { font-weight:700; color:#14304d; min-width:54px; }
.cand { border:1px solid #e4e9ef; border-radius:10px; padding:10px 12px; margin-bottom:10px; }
.cand .ch { display:flex; align-items:center; gap:10px; }
.cand .ctier { font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; color:#fff; }
.tA { background:#cf3b2f; } .tB { background:#c79a16; } .tC { background:#7a8694; }
.cand .cbul { font-size:13px; line-height:1.6; margin:6px 0 0; padding-left:16px; }
.cand .cbul li { margin:1px 0; }
.why .wrow .wt { min-width:64px; color:#2f7dac; }
.risk .rrow { font-size:13px; line-height:1.6; padding:6px 0; border-bottom:1px dashed #f1d6d3; }
.risk .rrow:last-child { border-bottom:none; }
.bigr { background:#fdecea; border-left:4px solid #cf3b2f; padding:8px 12px; border-radius:6px; font-size:13px; margin-top:8px; }
.learn .lgrid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.learn .lbox { border:1px solid #e4e9ef; border-radius:10px; padding:10px 12px; font-size:13px; }
/* 龙头资金层（OS 4.0 Phase 1） */
.leader .lhdr { font-size:15px; font-weight:700; color:#14304d; margin:14px 0 6px; }
.leader .lhdr:first-child { margin-top:0; }
.leader .lrow { border-top:1px solid #eef1f4; padding:8px 0; }
.leader .lname { font-weight:700; color:#14304d; }
.leader .lscore { color:#c0392b; font-weight:800; margin-left:6px; }
.leader .lfactors { font-size:12px; color:#555; margin-top:2px; }
.leader .riskhi { color:#cf3b2f; font-weight:700; }
.leader .risklo { color:#1ba784; }
.learn table { width:100%; border-collapse:collapse; font-size:12px; margin-top:6px; }
.learn th, .learn td { text-align:left; padding:3px 6px; border-bottom:1px solid #eef1f5; }
.alpha { background:linear-gradient(135deg,#1d3b2a,#2c5a3f); color:#eafaf0; border-radius:12px; padding:14px 18px; margin-bottom:14px; font-size:15px; line-height:1.55; }
.appendix { background:#f7f9fb; border:1px solid #e4e9ef; border-radius:12px; padding:14px 18px; font-size:13px; }
.appendix h3 { margin:0 0 8px; font-size:14px; color:#5a6b7b; }
.appendix .arow { margin:5px 0; line-height:1.55; }
.appendix .muted { color:#8a96a3; }
.foot { text-align:center; color:#8a96a3; font-size:11px; margin-top:18px; }
/* ── 驾驶舱 Cockpit（首屏 8 项）── */
.cockpit { border-radius:14px; padding:18px 18px 14px; margin-bottom:16px; color:#fff; }
.cockpit.yes { background:linear-gradient(135deg,#8a1f1f,#c0392b); }
.cockpit.caution { background:linear-gradient(135deg,#7a5c0a,#c79a16); }
.cockpit.no { background:linear-gradient(135deg,#0f3d34,#1ba784); }
.cockpit .cktitle { font-size:12px; letter-spacing:2px; opacity:.85; margin-bottom:10px; }
.ckgrid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.ckcell { background:rgba(255,255,255,.12); border-radius:10px; padding:10px 12px; min-height:74px; }
.ckcell .ckk { font-size:11px; opacity:.85; margin-bottom:4px; }
.ckcell .ckv { font-size:16px; font-weight:800; line-height:1.3; word-break:break-all; }
.ckcell .ckv.big { font-size:26px; }
.ckcell.span2 { grid-column:span 2; }
.cklearn { margin-top:10px; font-size:12px; opacity:.9; background:rgba(0,0,0,.18); border-radius:8px; padding:6px 12px; }
/* ── 系统安检闸门置灰 ── */
.sec.gated { opacity:.55; filter:grayscale(.4); }
.gatebanner { background:#fdecea; border:1px solid #cf3b2f; color:#cf3b2f; border-radius:8px; padding:8px 12px; font-size:13px; font-weight:700; margin-bottom:10px; }
/* ── 数据健康块 ── */
.sec.health { border-left:4px solid #2e9e5b; }
.sec.health.gated { border-left-color:#cf3b2f; }
.hbadge { font-size:14px; font-weight:700; padding:6px 10px; border-radius:8px; background:#eafaf0; color:#2e9e5b; margin:4px 0 8px; }
.hbadge.bad { background:#fdecea; color:#cf3b2f; }
.hchecks { font-size:12.5px; line-height:1.85; }
.hchecks .li.ok { color:#2e9e5b; }
.hchecks .li.no { color:#cf3b2f; font-weight:600; }
/* ── 折叠附录 ── */
details.fold { background:#f7f9fb; border:1px solid #e4e9ef; border-radius:12px; padding:0; margin-bottom:14px; }
details.fold > summary { cursor:pointer; list-style:none; padding:14px 18px; font-size:14px; font-weight:700; color:#5a6b7b; }
details.fold > summary::-webkit-details-marker { display:none; }
details.fold[open] > summary { border-bottom:1px solid #e4e9ef; }
details.fold .foldbody { padding:12px 18px 16px; font-size:13px; }
.keynums { font-size:13px; color:#5a6b7b; line-height:1.7; }
.chainbox { font-size:12px; color:#5a6b7b; line-height:1.8; background:#fff; border:1px solid #e4e9ef; border-radius:8px; padding:8px 12px; margin-bottom:10px; }
.chainbox b { color:#14304d; }
"""


def _sec(title, sub, prio, inner, cls=""):
    return (f'<div class="sec {cls}"><div class="sech"><div class="t">{_esc(title)}'
            f'<small>{_esc(sub)}</small></div>'
            f'<span class="pchip {prio.lower()}">{prio}</span></div>{inner}</div>')


def _leader_layer_inner(memo, wechat=False):
    """龙头资金层（OS 4.0 Phase 1）：对每个候选主线板块，列出 Capital Score 最高的核心股。

    数据来自 capital_score（真实 stock_flow_daily 按板块聚合 + 跨截面百分位）。
    两渲染器共用本助手，wechat=True 时改用内联样式。
    """
    date = getattr(memo, "trade_date", None)
    mains = getattr(memo, "main_lines", None) or []
    if not date or not mains:
        return '<div class="muted">今日无候选主线，龙头资金层为空。</div>'
    blocks = []
    for m in mains:
        sector = getattr(m, "sector", "")
        recs = cs.sector_top_stocks(date, sector, topn=5)
        if not recs:
            continue
        tier = ("A" if m.star_rating >= 4 and m.stage in ("赚钱效应", "一致性")
                else "B" if m.star_rating >= 3 else "C")
        if wechat:
            hdr = (f'<div style="font-weight:700;color:#14304d;margin:14px 0 6px;font-size:15px;">'
                   f'{_esc(sector)} <span style="font-size:12px;color:#7a8694;">'
                   f'· 龙头资金观察（{tier}级）</span></div>')
        else:
            hdr = (f'<div class="lhdr"><b>{_esc(sector)}</b> '
                   f'<span class="muted">· 龙头资金观察（{tier}级）</span></div>')
        rows = []
        for r in recs:
            sc = r["score"]
            sf = _stars(r["f_fund"] / W_FUND * 5)
            ss = _stars(r["f_sector"] / W_SECTOR * 5)
            sl = _stars(r["f_leader"] / W_LEADER * 5)
            sa = _stars(r["f_active"] / W_ACTIVE * 5)
            risk = "高·ST" if r["is_st"] else "低"
            if wechat:
                rows.append(
                    f'<div style="border-top:1px solid #eee;padding:8px 0;">'
                    f'<span style="font-weight:700;color:#14304d;">{_esc(r["name"])}</span> '
                    f'<span style="color:#c0392b;font-weight:800;margin-left:6px;">资本分 {sc}</span><br>'
                    f'<span style="font-size:12px;color:#555;">资金 {sf} ｜ 板块 {ss} ｜ 龙头 {sl} '
                    f'｜ 活跃 {sa} ｜ 风险 {_esc(risk)}</span>'
                    f'<span style="font-size:12px;color:#999;">（板块内第{r["intra_rank"]}）</span></div>')
            else:
                rows.append(
                    f'<div class="lrow"><div class="lname">{_esc(r["name"])}'
                    f'<span class="lscore">资本分 {sc}</span></div>'
                    f'<div class="lfactors">资金 {sf} ｜ 板块 {ss} ｜ 龙头 {sl} ｜ 活跃 {sa} ｜ '
                    f'风险 <span class="{"riskhi" if r["is_st"] else "risklo"}">{_esc(risk)}</span>'
                    f'<span class="muted">（板块内第{r["intra_rank"]}）</span></div></div>')
        blocks.append(hdr + "".join(rows))
    if not blocks:
        return '<div class="muted">候选板块暂无对应个股资金流（stock_flow_daily 未覆盖）。</div>'
    return "".join(blocks)


def render_html(memo):
    score = compute_weighted_score(memo)
    decision = resolve_decision(memo, score)
    alpha = compute_alpha(memo)
    es = compute_executive_summary(memo, score, decision)
    ck = compute_cockpit(memo, score, decision, es, alpha)
    fcls = decision["final"].lower()   # yes / caution / no

    # ── 顶部栏 ──
    top = (f'<div class="topbar"><div class="comp"><div class="num">{score["composite"]}</div>'
           f'<div class="lbl">综合评分 / 100</div></div>'
           f'<h1>A股 Trading OS</h1>'
           f'<div class="meta">{_esc(memo.trade_date)} &nbsp;·&nbsp; 市场状态 {_esc(decision["market_state"])}'
           f' &nbsp;·&nbsp; 建议仓位 {_esc(decision["position"])}</div></div>')

    # ── ★ 驾驶舱 Cockpit（首屏 8 项）★ ──
    def _cell(k, v, big=False, span=False):
        cls = "ckcell span2" if span else "ckcell"
        vcls = "ckv big" if big else "ckv"
        return (f'<div class="{cls}"><div class="ckk">{_esc(k)}</div>'
                f'<div class="{vcls}">{_esc(v)}</div></div>')
    ck_cells = (
        _cell("🎯 今日裁决", ck["verdict"], big=True)
        + _cell("📊 综合评分", f'{ck["composite"]}/100', big=True)
        + _cell("💰 建议仓位", ck["position"])
        + _cell("🔥 主线", ck["main"])
        + _cell("❌ 回避", ck["avoid"], span=True)
        + _cell("⏰ 第一观察点", ck["first_obs"], span=True)
        + _cell("⚠ 最大风险", ck["biggest_risk"], span=True)
        + _cell("🌟 今日 Alpha", ck["alpha"], span=True)
    )
    cockpit = (f'<div class="cockpit {fcls}">'
               f'<div class="cktitle">▎驾驶舱 COCKPIT · 一屏看懂今天怎么办</div>'
               f'<div class="ckgrid">{ck_cells}</div>'
               f'<div class="cklearn">📚 系统学习：{_esc(ck["learn_line"])}</div></div>')

    # ── 执行摘要（slim：一句话 + 可以做/不要做）──
    do_li = "".join(f'<div class="li ok">{_esc(x)}</div>' for x in es["can_do"])
    dont_li = "".join(f'<div class="li no">{_esc(x)}</div>' for x in es["avoid"])
    status_line = (f'<div class="trading-status">{_esc(es["trade_status"])}</div>'
                   if es.get("trade_status") else "")
    inner = (f'<div class="oneline">{_esc(es["one_liner"])}</div>'
             f'{status_line}'
             f'<div class="duo"><div class="do"><h4>{_esc(es["do_label"])}</h4>{do_li}</div>'
             f'<div class="dont"><h4>{_esc(es["avoid_label"])}</h4>{dont_li}</div></div>')
    exec_sec = _sec("执行摘要", "Executive Summary", "P0", inner)

    # ── 系统安检（闸门前置：0 通过=一票否决 NO，并置灰后续）──
    pf_gated = decision["pf_hard_no"]
    pf_banner = ('<div class="gatebanner">⛔ 系统安检 0 项通过 → 交易资格一票否决，'
                 '今日直接 NO；下方评分/候选仅供研究参考，不构成买入依据。</div>'
                 if pf_gated else "")
    pf_sec = _sec("系统安检", "Pre-flight · 交易资格闸门", "P0",
                  pf_banner + _preflight_inner(memo, wechat=False),
                  cls=("gated" if pf_gated else ""))

    # ── 最终裁决（唯一裁决器）──
    vcls = fcls
    cards = ""
    for g in ("资金", "产业", "宏观", "技术", "估值", "风险"):
        w = score["weights"].get(g, 0)
        cards += (f'<div class="dcard"><div class="dn"><span>{_esc(g)}</span>'
                  f'<span>权重 {w}%</span></div>'
                  f'<div class="dv">{score["dims"][g]}</div>'
                  f'<div class="dw">{_stars(score["dims"][g]/20.0)}</div></div>')
    ic_note = ("IC 投票一致" if decision["ic_agree"]
               else f'IC 投票 {_esc(decision["ic_can_buy"])}，取最保守')
    dg_note = " ｜ Learning 已降级" if decision["learning_downgrade"] else ""
    inner = (f'<div class="verdict {vcls}">最终裁决：{_esc(decision["verdict_label"])}'
             f'（{"可买" if decision["final"]=="YES" else "谨慎" if decision["final"]=="CAUTION" else "不买"}）</div>'
             f'<div class="agree">评分 {score["composite"]}（{decision["score_level"]}）'
             f' ｜ {ic_note} ｜ 安检 {decision["pf_passed"]}/{decision["pf_total"]}'
             f' ｜ 权重来源：{"Learning 校准" if score["weight_src"]=="learning" else "基准"}'
             f'{dg_note} ｜ 完整推导见附录</div>'
             f'<div class="scoregrid" style="margin-top:12px">{cards}</div>')
    dec_sec = _sec("最终裁决", "Decision · 唯一裁决器", "P0", inner)

    # ── 盯盘清单（动作化：满足→动作 / 不满足→动作）──
    wrows = ""
    for a in (memo.action_list or []):
        if not isinstance(a, dict):
            continue
        t, act, cond = a.get("time", ""), a.get("action", ""), a.get("condition", "")
        no_act = a.get("else_action") or "不满足则放弃该点、维持观望"
        wrows += (f'<div class="wrow"><span class="wt">{_esc(t)}</span>'
                  f'<span style="flex:1"><b>{_esc(act)}</b>'
                  f'<div class="li ok" style="margin-top:3px">满足「{_esc(cond)}」→ 按上执行</div>'
                  f'<div class="li no">不满足 → {_esc(no_act)}</div></span></div>')
    if not wrows:
        wrows = '<div class="muted">今日无固定盯盘点，按主线纪律相机而动。</div>'
    watch_sec = _sec("盯盘清单", "Watch List · 动作化", "P0", f'<div class="watch">{wrows}</div>')

    # ── 候选主线（瘦身：名称+级别+一条理由+一条风险）──
    cands = ""
    for m in (memo.main_lines or []):
        tier = "A" if m.star_rating >= 4 and m.stage in ("赚钱效应", "一致性") else \
               "B" if m.star_rating >= 3 else "C"
        why1 = (m.why_bullets or [""])[0] if (m.why_bullets) else ""
        risk1 = (m.risk_bullets or [""])[0] if (m.risk_bullets) else ""
        cands += (f'<div class="cand"><div class="ch"><span class="ctier t{tier}">{tier}</span>'
                  f'<b>{_esc(m.sector)}</b> <span class="stars" style="font-size:16px">{_stars(m.star_rating)}</span>'
                  f'<span class="muted">· {_esc(m.stage)}</span></div>'
                  f'<div style="font-size:13px;line-height:1.6;margin-top:4px">✅ {_esc(why1)}</div>'
                  + (f'<div style="font-size:13px;line-height:1.6;color:#cf3b2f">⚠ {_esc(risk1)}</div>' if risk1 else "")
                  + '</div>')
    if not cands:
        cands = '<div class="muted">暂无达标候选主线，今日以观察为主。</div>'
    cand_sec = _sec("候选主线", "Candidate · 名称+级别+一理由一风险", "P0", cands)

    # ── 龙头资金层（OS 4.0 Phase 1：候选板块 → 核心股 Capital Score）──
    leader_sec = _sec("龙头资金层", "Leader Capital · 钱集中到谁", "P1",
                      _leader_layer_inner(memo, False), cls="leader")

    # ── ⑤ 为什么 ──
    cap = (getattr(memo.capital_flow, "one_liner", None)
           or (memo.migration or {}).get("thesis") or "—")
    ind = (memo.industry_chain.narrative if getattr(memo, "industry_chain", None) and memo.industry_chain.has_data else "")
    if not ind:
        ind = (memo.committee or {}).get("main_logic") or "—"
    ind = ind[:80] if ind else "—"
    news = (f'接入 {memo.narrative.news_count} 条实时新闻' if getattr(memo.narrative, "has_news", False)
            else "实时新闻未接入（仅资金/产业链）")
    macro = (memo.committee or {}).get("main_logic") or "—"
    macro = macro[:80] if macro else "—"
    gx = memo.global_market.one_liner if getattr(memo, "global_market", None) else ""
    keynums = _key_numbers(memo)
    gx_cell = (f'{_esc(gx)} <span class="keynums" style="font-weight:700;color:#14304d;">{_esc(keynums)}</span>'
               if keynums else _esc(gx))
    why_rows = (
        f'<div class="wrow"><span class="wt">资金</span><span>{_esc(cap)}</span></div>'
        f'<div class="wrow"><span class="wt">产业</span><span>{_esc(ind)}</span></div>'
        f'<div class="wrow"><span class="wt">新闻</span><span>{_esc(news)}</span></div>'
        f'<div class="wrow"><span class="wt">宏观</span><span>{_esc(macro)}</span></div>'
        f'<div class="wrow"><span class="wt">全球</span><span>{gx_cell}</span></div>'
    )
    why_sec = _sec("为什么", "Why", "P1", f'<div class="watch why">{why_rows}</div>')

    # ── ⑥ 失效条件 ──
    rrows = ""
    for f in ((memo.risk.falsification if memo.risk else []) or [])[:4]:
        if isinstance(f, dict):
            rrows += (f'<div class="rrow">⚠ 若「{_esc(f.get("if_condition",""))}」'
                      f'→ {_esc(f.get("then_conclusion",""))}</div>')
    bigr = (f'<div class="bigr">最大风险：{_esc(memo.risk.biggest_risk)}</div>'
            if memo.risk and memo.risk.biggest_risk else "")
    risk_sec = _sec("失效条件", "Risk · 证伪", "P1", rrows + bigr)

    # ── ⑦ 系统学习 ──
    lr = memo.learning or {}
    da = lr.get("dimension_accuracy") or {}
    sw = lr.get("suggested_weights") or {}
    # 维度命中率表
    da_rows = ""
    if da:
        for L, st in da.items():
            da_rows += f"<tr><td>{_esc(L)}</td><td>{st['n']}</td><td>{st['acc']}%</td></tr>"
    else:
        da_rows = '<tr><td colspan="3" class="muted">维度命中率积累中（需带分层方向的回放样本）</td></tr>'
    # 权重表
    base = sw.get("base") or DEFAULT_WEIGHTS
    sugg = sw.get("suggested") or DEFAULT_WEIGHTS
    w_rows = ""
    for g in ("资金", "产业", "宏观", "技术", "风险", "估值"):
        mark = "→" if abs((sugg.get(g, 0) or 0) - (base.get(g, 0) or 0)) >= 0.5 else ""
        w_rows += (f"<tr><td>{_esc(g)}</td><td>{base.get(g,0)}%</td>"
                   f"<td>{sugg.get(g,0)}% {mark}</td></tr>")
    recent = lr.get("recent") or []
    rec_txt = "；".join(f'{r.get("date")}:{r.get("ic")}→{r.get("ic_hit")}' for r in recent[-3:]) or "—"
    learn_status = ("✅ 动态权重已生效（按维度命中率自动校准）" if sw.get("applied")
                    else "⏳ 动态权重试点中（样本积累中，暂用基准权重）")
    # ── 本周规律（从回放提炼的可消费洞察）──
    regs = lr.get("regularities") or []
    if regs:
        reg_items = "".join(
            f'<div style="border-left:3px solid #2f7dac;padding:4px 0 4px 10px;margin:6px 0;">'
            f'<b>{_esc(r["cond"])}</b>：{_esc(r["result"])}'
            f'<br><span class="muted">{_esc(r["action"])}（基于 {r["n"]} 次回放）</span></div>'
            for r in regs
        )
        reg_html = (f'<div class="lbox" style="grid-column:1/3;background:#f0f7fb;">'
                    f'<b>📌 本周规律（从回放自动提炼）</b>{reg_items}</div>')
    else:
        reg_html = (f'<div class="lbox" style="grid-column:1/3;">'
                    f'<b>📌 本周规律</b><br>'
                    f'<span class="muted">回放样本不足（≥2 次启用），规律自动提炼中……</span></div>')
    inner = (f'<div class="agree" style="margin-bottom:8px;">{_esc(learn_status)}</div>'
             f'{reg_html}'
             f'<div class="lgrid">'
             f'<div class="lbox"><b>IC 方向命中率</b><br>{lr.get("ic_accuracy") if lr.get("ic_accuracy") is not None else "—"}%'
             f'（已回放 {lr.get("n_replayed",0)} 次）<br><span class="muted">近期：{_esc(rec_txt)}</span></div>'
             f'<div class="lbox"><b>逐层命中率</b><table><tr><th>层</th><th>样本</th><th>命中</th></tr>{da_rows}</table></div>'
             f'<div class="lbox" style="grid-column:1/3"><b>IC 权重（Learning 动态校准）</b>'
             f'<span class="muted"> · {_esc(sw.get("note","基准权重"))}</span>'
             f'<table><tr><th>维度</th><th>基准</th><th>校准后</th></tr>{w_rows}</table></div>'
             f'</div>')
    learn_sec = _sec("系统学习", "Learning · 动态权重", "P2", inner)

    # ── ⑧ 今日 Alpha ──
    alpha_sec = f'<div class="alpha">每日 Alpha · {_esc(alpha)}</div>'

    # ── 数据健康（Data Integrity Layer 闸门）──
    dh = decision.get("health") or {}
    if dh:
        ok_badge = ("✅ 数据健康 · 允许交易" if dh.get("trade_allowed")
                    else "⛔ 数据健康未通过 · 禁止交易")
        rows = "".join(
            f'<div class="li {"ok" if c["ok"] else "no"}">{_esc(c["name"])}：'
            f'{_esc(c["value"])}（{_esc(c["detail"])}）</div>'
            for c in dh.get("checks", []))
        hcls = "" if dh.get("trade_allowed") else " gated"
        health_sec = (f'<div class="sec health{hcls}"><div class="sech">🩺 数据健康'
                      f'<span class="badge">{"P0" if not dh.get("trade_allowed") else "OK"}</span></div>'
                      f'<div class="hbadge{" bad" if not dh.get("trade_allowed") else ""}">'
                      f'{ok_badge}</div><div class="hchecks">{rows}</div></div>')
    else:
        health_sec = ""

    # ── ⑨ 附录（折叠：裁决推导链 + 原始数据）──
    chain_html = ('<div class="chainbox"><b>裁决推导链：</b>'
                  + " ".join("→ " + _esc(c) if i else _esc(c)
                             for i, c in enumerate(decision["chain"]))
                  + f'<br><b>仓位推导：</b>{_esc(decision["position"])}'
                  f'（最终裁决={_esc(decision["final"])}；NO 强制空仓，'
                  f'其余取 IC+Learning 反哺后的护栏值）</div>')
    app_body = chain_html + _render_appendix(memo)
    app_sec = (f'<details class="fold"><summary>📎 附录 Appendix · 裁决推导 + 原始数据（点击展开）</summary>'
               f'<div class="foldbody">{app_body}</div></details>')

    # 结构顺序：驾驶舱 → 执行摘要 → 系统安检(闸门前置) → 最终裁决 → 盯盘 → 候选
    #          → 为什么 → 失效 → 学习 → Alpha → 附录(折叠)
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>A股 Trading OS · {_esc(memo.trade_date)}</title><style>{CSS}</style></head>'
            f'<body><div class="wrap">{top}{cockpit}{exec_sec}{health_sec}{pf_sec}{dec_sec}{watch_sec}{cand_sec}{leader_sec}'
            f'{why_sec}{risk_sec}{learn_sec}{alpha_sec}{app_sec}'
            f'<div class="foot">Trading OS · 唯一裁决 · 驾驶舱首屏 · 由个人AI研投系统生成 · 仅供参考，买卖决策以人工看图为准</div>'
            f'</div></body></html>')


# ═══════════════════════════════════════════════════════
#  微信公众号专用渲染（内联样式 · 红涨绿跌 · 无 <style>/class）
#  与 render_html 同一份数据与决策逻辑，仅样式适配公众号白名单标签。
#  公众号草稿接口会剥离 <style>/class，故必须全部内联。
# ═══════════════════════════════════════════════════════
WX_UP = "#e23c3c"       # 涨 / 净流入 / 可以买（红）
WX_DOWN = "#1ba784"     # 跌 / 净流出 / 不买（绿）
WX_CAUTION = "#c79a16"
WX_INK = "#1f2937"
WX_MUTED = "#8a93a6"
WX_PRIO = {"P0": "#e0532a", "P1": "#c79a16", "P2": "#2f7dac", "P3": "#7a8694"}


def _wx_sec(title, sub, prio, inner):
    chip = (f'<span style="font-size:11px;font-weight:700;color:#fff;'
            f'background:{WX_PRIO.get(prio, "#7a8694")};padding:2px 8px;'
            f'border-radius:20px;margin-left:6px;">{_esc(prio)}</span>')
    head = (f'<div style="font-size:16px;font-weight:700;color:{WX_INK};margin:0 0 10px;'
            f'padding-left:8px;border-left:4px solid #2b6cb0;">{_esc(title)} '
            f'<span style="font-weight:400;color:#aaa;font-size:12px;">{_esc(sub)}</span>{chip}</div>')
    return (f'<section style="background:#ffffff;border:1px solid #e5e7eb;'
            f'border-radius:10px;padding:16px 18px;margin:16px 0;">{head}{inner}</section>')


def render_wechat_html(memo):
    """生成公众号可直接发布的「内联样式」HTML（与本地 HTML 同一份决策，红涨绿跌）。"""
    score = compute_weighted_score(memo)
    decision = resolve_decision(memo, score)
    alpha = compute_alpha(memo)
    es = compute_executive_summary(memo, score, decision)
    ck = compute_cockpit(memo, score, decision, es, alpha)
    ck_bg = ({"YES": "#c0392b", "CAUTION": "#c79a16", "NO": "#1ba784"}[decision["final"]])

    # ── 顶部栏（表格，公众号安全）──
    top = (f'<table style="width:100%;background:#14304d;color:#fff;border-radius:12px;'
           f'margin:0 0 16px;"><tr>'
           f'<td style="padding:20px 22px;vertical-align:middle;">'
           f'<div style="font-size:22px;font-weight:800;letter-spacing:1px;">A股 Trading OS</div>'
           f'<div style="font-size:13px;opacity:.85;margin-top:4px;">{_esc(memo.trade_date)} · '
           f'市场状态 {_esc(decision["market_state"])} · 建议仓位 {_esc(decision["position"])}</div></td>'
           f'<td style="padding:20px 22px;text-align:center;vertical-align:middle;width:120px;">'
           f'<div style="font-size:34px;font-weight:800;line-height:1;">{score["composite"]}</div>'
           f'<div style="font-size:11px;opacity:.8;">综合评分/100</div></td></tr></table>')

    # ── ★ 驾驶舱 Cockpit（首屏 8 项）★ ──
    def _wcell(k, v, big=False, colspan=1):
        vsize = "26px" if big else "16px"
        return (f'<td colspan="{colspan}" style="background:rgba(255,255,255,.14);border-radius:8px;'
                f'padding:10px 12px;vertical-align:top;width:25%;">'
                f'<div style="font-size:11px;opacity:.85;margin-bottom:4px;">{_esc(k)}</div>'
                f'<div style="font-size:{vsize};font-weight:800;line-height:1.3;">{_esc(v)}</div></td>')
    ck_rows = (
        f'<tr>{_wcell("🎯 今日裁决", ck["verdict"], big=True)}{_wcell("📊 综合评分", str(ck["composite"])+"/100", big=True)}'
        f'{_wcell("💰 建议仓位", ck["position"])}{_wcell("🔥 主线", ck["main"])}</tr>'
        f'<tr><td style="height:8px" colspan="4"></td></tr>'
        f'<tr>{_wcell("❌ 回避", ck["avoid"], colspan=2)}{_wcell("⏰ 第一观察点", ck["first_obs"], colspan=2)}</tr>'
        f'<tr><td style="height:8px" colspan="4"></td></tr>'
        f'<tr>{_wcell("⚠ 最大风险", ck["biggest_risk"], colspan=2)}{_wcell("🌟 今日 Alpha", ck["alpha"], colspan=2)}</tr>'
    )
    cockpit = (f'<table style="width:100%;border-collapse:separate;border-spacing:6px;'
               f'background:{ck_bg};color:#fff;border-radius:14px;margin:0 0 16px;">'
               f'<tr><td colspan="4" style="padding:10px 8px 2px;font-size:12px;letter-spacing:2px;opacity:.85;">'
               f'▎驾驶舱 COCKPIT · 一屏看懂今天怎么办</td></tr>{ck_rows}'
               f'<tr><td colspan="4" style="padding:4px 10px 12px;font-size:12px;opacity:.92;">'
               f'📚 系统学习：{_esc(ck["learn_line"])}</td></tr></table>')

    # ── 执行摘要（slim）──
    do_li = "".join(f'<div style="font-size:14px;line-height:1.7;margin:4px 0;">✅ {_esc(x)}</div>' for x in es["can_do"])
    dont_li = "".join(f'<div style="font-size:14px;line-height:1.7;margin:4px 0;">❌ {_esc(x)}</div>' for x in es["avoid"])
    inner = (f'<div style="font-size:15px;line-height:1.5;margin:0 0 12px;">{_esc(es["one_liner"])}</div>'
             f'<div style="font-size:13px;font-weight:700;color:#14304d;margin-bottom:8px;">{_esc(es["trade_status"])}</div>'
             f'<table style="width:100%;border-collapse:collapse;"><tr>'
             f'<td style="width:50%;vertical-align:top;padding-right:8px;"><div style="font-size:13px;font-weight:700;color:#1a8a4f;margin-bottom:4px;">{_esc(es["do_label"])}</div>{do_li}</td>'
             f'<td style="width:50%;vertical-align:top;padding-left:8px;border-left:1px solid #eef1f5;"><div style="font-size:13px;font-weight:700;color:#cf3b2f;margin-bottom:4px;">{_esc(es["avoid_label"])}</div>{dont_li}</td>'
             f'</tr></table>')
    exec_sec = _wx_sec("执行摘要", "Executive Summary", "P0", inner)

    # ── 数据健康（Data Integrity Layer 闸门）──
    dh = decision.get("health") or {}
    if dh:
        ok_badge = ("✅ 数据健康 · 允许交易" if dh.get("trade_allowed")
                    else "⛔ 数据健康未通过 · 禁止交易")
        rows = "".join(
            f'<div style="font-size:12px;line-height:1.7;">{"✅" if c["ok"] else "⛔"} '
            f'{_esc(c["name"])}：{_esc(c["value"])}（{_esc(c["detail"])}）</div>'
            for c in dh.get("checks", []))
        hbox = (f'<div style="background:{"#eafaf0" if dh.get("trade_allowed") else "#fdecea"};'
                f'border:1px solid {"#2e9e5b" if dh.get("trade_allowed") else "#cf3b2f"};'
                f'border-radius:8px;padding:8px 12px;margin-bottom:8px;'
                f'color:{"#2e9e5b" if dh.get("trade_allowed") else "#cf3b2f"};'
                f'font-size:14px;font-weight:700;">{ok_badge}</div>{rows}')
        health_sec = _wx_sec("数据健康", "Data Integrity Layer · 闸门",
                              "P0" if not dh.get("trade_allowed") else "OK", hbox)
    else:
        health_sec = ""

    # ── 系统安检（闸门前置：0 通过=一票否决 NO）──
    pf_banner = ('<div style="background:#fdecea;border:1px solid #cf3b2f;color:#cf3b2f;'
                 'border-radius:8px;padding:8px 12px;font-size:13px;font-weight:700;margin-bottom:10px;">'
                 '⛔ 系统安检 0 项通过 → 交易资格一票否决，今日直接 NO；下方仅供研究参考。</div>'
                 if decision["pf_hard_no"] else "")
    pf_sec = _wx_sec("系统安检", "Pre-flight · 交易资格闸门", "P0",
                     pf_banner + _preflight_inner(memo, wechat=True))

    # ── 最终裁决（唯一裁决器）──
    vcls = WX_UP if decision["final"] == "YES" else WX_DOWN if decision["final"] == "NO" else WX_CAUTION
    head_cells = "".join(f'<td style="padding:4px 2px;font-size:13px;color:#5a6b7b;">{_esc(g)}</td>' for g in ("资金","产业","宏观","技术","估值","风险"))
    val_cells = "".join(f'<td style="padding:4px 2px;font-size:18px;font-weight:800;color:{WX_INK};">{score["dims"][g]}</td>' for g in ("资金","产业","宏观","技术","估值","风险"))
    w_cells = "".join(f'<td style="padding:2px;font-size:11px;color:#8a96a3;">权重{score["weights"].get(g,0)}%</td>' for g in ("资金","产业","宏观","技术","估值","风险"))
    ic_note = ("IC 投票一致" if decision["ic_agree"]
               else f'IC 投票 {_esc(decision["ic_can_buy"])}，取最保守')
    dg_note = " ｜ Learning 已降级" if decision["learning_downgrade"] else ""
    inner = (f'<div style="font-size:20px;font-weight:800;margin:6px 0;color:{vcls};">最终裁决：{_esc(decision["verdict_label"])}'
             f'（{"可买" if decision["final"]=="YES" else "谨慎" if decision["final"]=="CAUTION" else "不买"}）</div>'
             f'<div style="font-size:12px;color:#5a6b7b;margin-bottom:8px;">评分 {score["composite"]}（{decision["score_level"]}）'
             f' ｜ {ic_note} ｜ 安检 {decision["pf_passed"]}/{decision["pf_total"]}'
             f' ｜ 权重来源：{"Learning 校准" if score["weight_src"]=="learning" else "基准"}{dg_note} ｜ 完整推导见附录</div>'
             f'<table style="width:100%;border-collapse:collapse;text-align:center;">'
             f'<tr>{head_cells}</tr><tr>{val_cells}</tr><tr>{w_cells}</tr></table>')
    dec_sec = _wx_sec("最终裁决", "Decision · 唯一裁决器", "P0", inner)

    # ── 盯盘清单（动作化：满足→动作 / 不满足→动作）──
    wrows = ""
    for a in (memo.action_list or []):
        if not isinstance(a, dict):
            continue
        t, act, cond = a.get("time", ""), a.get("action", ""), a.get("condition", "")
        no_act = a.get("else_action") or "不满足则放弃该点、维持观望"
        wrows += (f'<div style="padding:8px 0;border-bottom:1px dashed #eef1f5;font-size:14px;">'
                  f'<span style="font-weight:700;color:#14304d;display:inline-block;min-width:54px;">{_esc(t)}</span>'
                  f'<b>{_esc(act)}</b>'
                  f'<div style="font-size:13px;margin-top:3px;">✅ 满足「{_esc(cond)}」→ 按上执行</div>'
                  f'<div style="font-size:13px;color:#cf3b2f;">❌ 不满足 → {_esc(no_act)}</div></div>')
    if not wrows:
        wrows = '<div style="color:#8a96a3;">今日无固定盯盘点，按主线纪律相机而动。</div>'
    watch_sec = _wx_sec("盯盘清单", "Watch List · 动作化", "P0",
                        f'<div style="border-left:3px solid #2f7dac;padding-left:12px;">{wrows}</div>')

    # ── 候选主线（瘦身：名称+级别+一理由一风险）──
    cands = ""
    for m in (memo.main_lines or []):
        tier = "A" if m.star_rating >= 4 and m.stage in ("赚钱效应", "一致性") else "B" if m.star_rating >= 3 else "C"
        tcol = {"A": "#cf3b2f", "B": "#c79a16", "C": "#7a8694"}[tier]
        why1 = (m.why_bullets or [""])[0] if (m.why_bullets) else ""
        risk1 = (m.risk_bullets or [""])[0] if (m.risk_bullets) else ""
        cands += (f'<div style="border:1px solid #e4e9ef;border-radius:10px;padding:10px 12px;margin-bottom:10px;">'
                  f'<span style="font-size:11px;font-weight:700;color:#fff;background:{tcol};padding:2px 8px;border-radius:6px;">{tier}</span> '
                  f'<b style="font-size:15px;">{_esc(m.sector)}</b> '
                  f'<span style="color:#f5a623;font-size:16px;">{_stars(m.star_rating)}</span> '
                  f'<span style="color:#8a96a3;font-size:13px;">· {_esc(m.stage)}</span>'
                  f'<div style="font-size:13px;line-height:1.6;margin-top:4px;">✅ {_esc(why1)}</div>'
                  + (f'<div style="font-size:13px;line-height:1.6;color:#cf3b2f;">⚠ {_esc(risk1)}</div>' if risk1 else "")
                  + '</div>')
    if not cands:
        cands = '<div style="color:#8a96a3;">暂无达标候选主线，今日以观察为主。</div>'
    cand_sec = _wx_sec("候选主线", "Candidate · 名称+级别+一理由一风险", "P0", cands)

    # ── 龙头资金层（OS 4.0 Phase 1：候选板块 → 核心股 Capital Score）──
    leader_sec = _wx_sec("龙头资金层", "Leader Capital · 钱集中到谁", "P1",
                         _leader_layer_inner(memo, True))

    # ── 为什么 ──
    cap = (getattr(memo.capital_flow, "one_liner", None)
           or (memo.migration or {}).get("thesis") or "—")
    ind = (memo.industry_chain.narrative if getattr(memo, "industry_chain", None) and memo.industry_chain.has_data else "")
    if not ind:
        ind = (memo.committee or {}).get("main_logic") or "—"
    ind = ind[:80] if ind else "—"
    news = (f'接入 {getattr(memo.narrative, "news_count", 0)} 条实时新闻'
            if getattr(memo.narrative, "has_news", False) else "实时新闻未接入（仅资金/产业链）")
    macro = (memo.committee or {}).get("main_logic") or "—"
    macro = macro[:80] if macro else "—"
    gx = memo.global_market.one_liner if getattr(memo, "global_market", None) else ""
    keynums = _key_numbers(memo)
    gx_val = (f'{gx}  {keynums}' if keynums else gx)
    def _wrow(k, v):
        return (f'<div style="padding:5px 0;border-bottom:1px dashed #eef1f5;font-size:14px;">'
                f'<span style="display:inline-block;min-width:64px;font-weight:700;color:#2f7dac;">{_esc(k)}</span>'
                f'<span>{_esc(v)}</span></div>')
    why_rows = (_wrow("资金", cap) + _wrow("产业", ind) + _wrow("新闻", news)
                + _wrow("宏观", macro) + _wrow("全球", gx_val))
    why_sec = _wx_sec("为什么", "Why", "P1",
                      f'<div style="border-left:3px solid #2f7dac;padding-left:12px;">{why_rows}</div>')

    # ── 失效条件 ──
    rf = (memo.risk.falsification if memo.risk else []) or []
    rrows = ""
    for f in rf[:4]:
        if isinstance(f, dict):
            rrows += (f'<div style="font-size:13px;line-height:1.6;padding:6px 0;border-bottom:1px dashed #f1d6d3;">'
                      f'⚠ 若「{_esc(f.get("if_condition",""))}」→ {_esc(f.get("then_conclusion",""))}</div>')
    bigr = (f'<div style="background:#fdecea;border-left:4px solid #cf3b2f;padding:8px 12px;border-radius:6px;font-size:13px;margin-top:8px;">最大风险：{_esc(memo.risk.biggest_risk)}</div>'
            if memo.risk and memo.risk.biggest_risk else "")
    risk_sec = _wx_sec("失效条件", "Risk · 证伪", "P1", rrows + bigr)

    # ── 系统学习 ──
    lr = memo.learning or {}
    da = lr.get("dimension_accuracy") or {}
    sw = lr.get("suggested_weights") or {}
    da_rows = ""
    if da:
        for L, st in da.items():
            da_rows += (f'<tr><td style="padding:3px 6px;border-bottom:1px solid #eef1f5;">{_esc(L)}</td>'
                        f'<td style="padding:3px 6px;">{st["n"]}</td>'
                        f'<td style="padding:3px 6px;">{st["acc"]}%</td></tr>')
    else:
        da_rows = '<tr><td colspan="3" style="padding:3px 6px;color:#8a96a3;">维度命中率积累中（需带分层方向的回放样本）</td></tr>'
    base = sw.get("base") or DEFAULT_WEIGHTS
    sugg = sw.get("suggested") or DEFAULT_WEIGHTS
    w_rows = ""
    for g in ("资金", "产业", "宏观", "技术", "风险", "估值"):
        mark = "→" if abs((sugg.get(g, 0) or 0) - (base.get(g, 0) or 0)) >= 0.5 else ""
        w_rows += (f'<tr><td style="padding:3px 6px;">{_esc(g)}</td>'
                   f'<td style="padding:3px 6px;">{base.get(g, 0)}%</td>'
                   f'<td style="padding:3px 6px;">{sugg.get(g, 0)}% {mark}</td></tr>')
    recent = lr.get("recent") or []
    rec_txt = "；".join(f'{r.get("date")}:{r.get("ic")}→{r.get("ic_hit")}' for r in recent[-3:]) or "—"
    learn_status = ("✅ 动态权重已生效（按维度命中率自动校准）" if sw.get("applied")
                    else "⏳ 动态权重试点中（样本积累中，暂用基准权重）")
    # ── 本周规律（公众号内联版）──
    regs = lr.get("regularities") or []
    if regs:
        reg_items = "".join(
            f'<div style="border-left:3px solid #2f7dac;padding:4px 0 4px 10px;margin:6px 0;font-size:13px;line-height:1.5;">'
            f'<b>{_esc(r["cond"])}</b>：{_esc(r["result"])}'
            f'<br><span style="color:#8a96a3;font-size:12px;">{_esc(r["action"])}（基于 {r["n"]} 次回放）</span></div>'
            for r in regs
        )
        reg_html = (f'<div style="background:#f0f7fb;border:1px solid #dbeafe;border-radius:8px;'
                    f'padding:10px 12px;margin-bottom:10px;">'
                    f'<div style="font-weight:700;margin-bottom:4px;font-size:13px;">'
                    f'📌 本周规律（从回放自动提炼）</div>{reg_items}</div>')
    else:
        reg_html = (f'<div style="background:#f7f9fb;border:1px solid #e4e9ef;border-radius:8px;'
                    f'padding:10px 12px;margin-bottom:10px;font-size:13px;">'
                    f'<div style="font-weight:700;margin-bottom:4px;">📌 本周规律</div>'
                    f'<span style="color:#8a96a3;">回放样本不足（≥2 次启用），规律自动提炼中……</span></div>')
    inner = (f'{reg_html}'
             f'<div style="font-size:12px;font-weight:700;color:{"#1a8a4f" if sw.get("applied") else "#c79a16"};'
             f'margin-bottom:8px;">{_esc(learn_status)}</div>'
             f'<table style="width:100%;border-collapse:collapse;font-size:13px;"><tr>'
             f'<td style="width:50%;vertical-align:top;padding-right:8px;">'
             f'<div style="font-weight:700;margin-bottom:4px;">IC 方向命中率</div>'
             f'<div style="font-size:18px;font-weight:800;color:{WX_INK};">{lr.get("ic_accuracy") if lr.get("ic_accuracy") is not None else "—"}%</div>'
             f'<div style="font-size:12px;color:#8a96a3;">已回放 {lr.get("n_replayed", 0)} 次 · 近期：{_esc(rec_txt)}</div></td>'
             f'<td style="width:50%;vertical-align:top;padding-left:8px;border-left:1px solid #eef1f5;">'
             f'<div style="font-weight:700;margin-bottom:4px;">逐层命中率</div>'
             f'<table style="width:100%;border-collapse:collapse;font-size:12px;">'
             f'<tr><th style="text-align:left;">层</th><th>样本</th><th>命中</th></tr>{da_rows}</table></td></tr></table>'
             f'<div style="margin-top:10px;font-weight:700;margin-bottom:4px;">IC 权重（Learning 动态校准）</div>'
             f'<div style="font-size:12px;color:#8a96a3;margin-bottom:4px;">{_esc(sw.get("note", "基准权重"))}</div>'
             f'<table style="width:100%;border-collapse:collapse;font-size:12px;">'
             f'<tr><th style="text-align:left;">维度</th><th>基准</th><th>校准后</th></tr>{w_rows}</table>')
    learn_sec = _wx_sec("系统学习", "Learning · 动态权重", "P2", inner)

    # ── 今日 Alpha ──
    alpha_sec = (f'<section style="background:#1f4d33;color:#eafaf0;border-radius:12px;padding:14px 18px;'
                 f'margin:16px 0;font-size:15px;line-height:1.55;">每日 Alpha · {_esc(alpha)}</section>')

    # ── 附录（裁决推导链 + 原始数据；公众号编辑器不支持折叠，故置末尾并压缩）──
    chain_html = ('<div style="font-size:12px;color:#5a6b7b;line-height:1.8;background:#fff;'
                  'border:1px solid #e4e9ef;border-radius:8px;padding:8px 12px;margin-bottom:10px;">'
                  '<b style="color:#14304d;">裁决推导链：</b>'
                  + " ".join(("→ " + _esc(c)) if i else _esc(c)
                             for i, c in enumerate(decision["chain"]))
                  + f'<br><b style="color:#14304d;">仓位推导：</b>{_esc(decision["position"])}'
                  f'（最终裁决={_esc(decision["final"])}；NO 强制空仓，其余取 IC+Learning 反哺护栏值）</div>')
    app = _render_appendix(memo, inline=True)
    app_sec = _wx_sec("附录", "Appendix · 裁决推导 + 原始数据", "P3",
                      chain_html + f'<div style="font-size:13px;color:#5a6b7b;">{app}</div>')

    intro = ('<section style="max-width:680px;margin:0 auto;padding:6px 2px;'
             'font-family:-apple-system,\'Segoe UI\',\'Microsoft YaHei\',sans-serif;">'
             '<p style="font-size:14px;color:#6b7280;line-height:1.8;margin:0 0 4px;">'
             '以下为系统每日生成的 Trading OS 压缩版决策备忘录：首屏「驾驶舱」一屏看懂今天怎么办，'
             '全报告只认一个「最终裁决」。红涨绿跌，颜色仅作区分，不构成任何投资建议。</p>')
    footer = ('<section style="background:#faf7ff;border:2px solid #6b46c1;border-radius:10px;'
              'padding:14px 18px;margin:18px 0;font-size:13px;color:#6b7280;line-height:1.8;">'
              '<strong style="color:#6b46c1;">免责声明：</strong>'
              '本文由个人 AI 研投系统自动生成，所有数据可能存在延迟或误差，'
              '所载内容仅供研究学习与信息参考，<strong style="color:#6b46c1;">不构成任何投资建议或买卖邀约</strong>。'
              '市场有风险，投资需谨慎，请独立判断并自担风险。</section>'
              '</section>')

    # 结构顺序：驾驶舱 → 执行摘要 → 系统安检(闸门前置) → 最终裁决 → 盯盘 → 候选
    #          → 为什么 → 失效 → 学习 → Alpha → 附录
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<title>A股 Trading OS · {_esc(memo.trade_date)}</title></head><body>'
            f'{intro}{top}{cockpit}{exec_sec}{health_sec}{pf_sec}{dec_sec}{watch_sec}{cand_sec}{leader_sec}'
            f'{why_sec}{risk_sec}{learn_sec}{alpha_sec}{app_sec}{footer}'
            f'</body></html>')


def _preflight_inner(memo, wechat=False):
    """系统安检（Pre-flight）+ 系统自校准（IC 命中率反哺）的紧凑显示内容。

    memo.preflight 来自 cio_agent._build_preflight（含第7项「系统自校准」检查与 calibration）。
    命中率<40% 时展示降级与仓位收紧；命中率≥50% 展示正常放行。
    """
    pf = memo.preflight or {}
    if not pf or pf.get("error"):
        return ""
    verdict = pf.get("verdict", "")
    pc = pf.get("passed_count", 0)
    tc = pf.get("total_count", 0)
    cal = pf.get("calibration") or {}

    if wechat:
        vcol = WX_UP if verdict == "YES" else WX_DOWN if verdict == "NO" else WX_CAUTION
        ink = WX_INK
        muted = WX_MUTED
    else:
        vcol = "#1ba784" if verdict == "YES" else "#e23c3c" if verdict == "NO" else "#c79a16"
        ink = "#1f2937"
        muted = "#8a93a6"

    # 校准行
    cal_line = ""
    acc = cal.get("accuracy")
    n = cal.get("n", 0)
    pos_scale = cal.get("pos_scale", 1.0)
    if cal.get("available") and acc is not None:
        pct = int(round(pos_scale * 100))
        if cal.get("downgraded"):
            cal_line = (f'<b style="color:{vcol}">⚠️ 系统自校准：</b>IC 方向命中率仅 '
                        f'<b>{acc}%</b>（{n}日回放），显著低于随机 → 仓位护栏自动收紧至 '
                        f'<b>{pct}%</b>、安检由 {_esc(cal.get("base_verdict"))} 降级为 '
                        f'<b>{_esc(verdict)}</b>')
        elif acc < 50:
            cal_line = (f'系统自校准：IC 命中率 <b>{acc}%</b>（{n}日）→ 仓位护栏收紧至 {pct}%，仅可小仓试探')
        else:
            cal_line = f'系统自校准：IC 命中率 <b>{acc}%</b>（{n}日回放）→ 方向判断可信，正常放行'

    # 失败项（精简，最多 3 条）
    fails = pf.get("failed_summary") or []
    fail_html = ""
    if fails:
        items = ""
        for f in fails[:3]:
            items += (f'<li style="margin:2px 0;">❌ {_esc(f.get("condition",""))}：'
                      f'{_esc((f.get("reason") or "")[:46])}</li>')
        fail_html = (f'<div style="margin-top:8px;font-size:13px;color:{muted};">'
                     f'<div style="font-weight:700;color:{ink};margin-bottom:2px;">未通过项</div>'
                     f'<ul style="margin:0;padding-left:18px;">{items}</ul></div>')

    head = (f'<span style="font-size:15px;font-weight:800;color:{vcol};">安检 {_esc(verdict)}</span>'
            f' <span style="font-size:12px;color:{muted};">通过 {pc}/{tc}</span>')
    cal_block = (f'<div style="margin-top:6px;font-size:13px;line-height:1.6;color:{ink};">{cal_line}</div>'
                 if cal_line else "")
    return f'<div>{head}{cal_block}{fail_html}</div>'


def write_wechat(memo, path):
    """写出公众号内联版 HTML（可手动粘贴到公众号编辑器的兜底文件）。"""
    html_text = render_wechat_html(memo)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return len(html_text)


def _render_appendix(memo, inline=False):
    """原始数据归集（P3 附录）。inline=True 时全部用内联样式（公众号兼容，无 class）。"""
    if inline:
        A_OPEN = '<div style="margin:5px 0;line-height:1.55;font-size:13px;color:#5a6b7b;"'
        M_OPEN = '<div style="margin:5px 0;line-height:1.55;font-size:13px;color:#8a96a3;"'
    else:
        A_OPEN = '<div class="arow"'
        M_OPEN = '<div class="arow muted"'
    parts = []
    # 全球看板
    gx = memo.global_market
    if gx is not None and getattr(gx, "board", None):
        rows = ""
        for b in gx.board:
            chg = b.get("change_pct")
            arrow = "" if chg is None else ("▲" if chg > 0 else "▼")
            rows += f'{_esc(b.get("name",""))} {arrow}{abs(chg):.1f}% ' if chg is not None else f'{_esc(b.get("name",""))} 未接入 '
        parts.append(f'{A_OPEN}><b>全球：</b>{_esc(rows)}</div>')
    # 商品 / ETF
    cf = memo.capital_flow
    etf_in = getattr(cf, "etf_top_inflow", None) or []
    if etf_in:
        etf = "、".join(f'{i.get("name")}(+{i.get("shares_change_pct")}%)' for i in etf_in[:3])
        parts.append(f'{A_OPEN}><b>ETF净申购：</b>{_esc(etf)}'
                     f' ｜ 整体 {getattr(cf, "etf_total_net_yi", 0)}亿 ｜ 南向 {getattr(cf, "south_net_yi", 0)}亿</div>')
    # 盘前纪要
    pq = memo.panqian
    if pq is not None and getattr(pq, "has_data", False):
        parts.append(f'{A_OPEN}><b>盘前纪要：</b>{_esc(pq.headline)}</div>')
        if pq.risk_flags:
            flags = []
            for x in pq.risk_flags[:4]:
                if isinstance(x, dict):
                    flags.append(x.get("text") or x.get("desc") or x.get("name") or str(x))
                else:
                    flags.append(str(x))
            parts.append(f'{M_OPEN}>地雷阵：{_esc("；".join(flags))}</div>')
    # 产业链
    ic = memo.industry_chain
    if ic is not None and getattr(ic, "has_data", False):
        bn = len(ic.bottlenecks or [])
        dg = len(ic.downgraded or [])
        parts.append(f'{A_OPEN}><b>产业链瓶颈：</b>{bn} 个环节 · 降级 {dg} 个题材</div>')
    # 因果未知
    unk = (memo.causal or {}).get("unknown_list") or []
    if unk:
        parts.append(f'{M_OPEN}><b>因果未知（诚实标注）：</b>{_esc("、".join(unk[:3]))}</div>')
    # 数据新鲜度
    fr = memo.freshness or {}
    if fr.get("summary"):
        parts.append(f'{M_OPEN}><b>数据新鲜度：</b>{_esc(fr["summary"])}</div>')
    parts.append(f'{M_OPEN}>完整引擎输出见 output/ 下各 report.json；本报告为正文压缩版，原始数据全部归集于此。</div>')
    return "".join(parts)


# ═══════════════════════════════════════════════════════
#  推送文本（压缩版，供企微/飞书/Server酱）
# ═══════════════════════════════════════════════════════
def render_push(memo):
    score = compute_weighted_score(memo)
    decision = resolve_decision(memo, score)
    es = compute_executive_summary(memo, score, decision)
    vcls = "✅可买" if decision["final"] == "YES" else "⛔不买" if decision["final"] == "NO" else "⚠️谨慎"
    lines = [
        f"【A股 Trading OS · {memo.trade_date}】",
        f"综合 {score['composite']}/100 · {decision['market_state']} · 仓位 {decision['position']}",
        f"裁决：{vcls}（{es['one_liner']}）",
        "",
        f"{es['do_label']}：{' / '.join(es['can_do'][:3])}",
        f"{es['avoid_label']}：{' / '.join(es['avoid'][:3])}",
        f"🔑 今天最重要：{es['most_important']}",
        "",
        "候选：" + " | ".join(
            f"{('A' if m.star_rating>=4 else 'B' if m.star_rating>=3 else 'C')}{m.sector}{_stars(m.star_rating)}"
            for m in (memo.main_lines or [])[:4]),
        "",
        compute_alpha(memo),
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
#  写出
# ═══════════════════════════════════════════════════════
def write(memo, path):
    html_text = render_html(memo)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return len(html_text)


def _produce_and_write(dry_run=False):
    from brain.cio_agent import produce
    memo = produce()
    out = os.path.join(ROOT, "output", f"memo_{memo.trade_date}.html")
    if dry_run:
        print(render_push(memo))
        print(f"\n[dry-run] 将写入：{out}（{len(render_html(memo))} 字节）")
    else:
        n = write(memo, out)
        print(f"✅ 已生成 Trading OS 日报：{out}（{n} 字节）")
    return memo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    _produce_and_write(dry_run=args.dry_run)
