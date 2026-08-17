# -*- coding: utf-8 -*-
"""
学习复盘中心 (Learning & Review Center)  —— Slice 5
====================================================
回答买方每天的第九个真问题——「系统在成长吗 / 我该信它几分」：

    * 每日预测日志：把当天 IC 裁决 + 情景基准分支 + 赢家/输家 持久化；
    * 结果回放：T+1 用真实板块净流（sector_flow_history）回看判断是否应验；
    * 模式成败率：统计 IC 方向命中率、各情景分支命中率、按裁决类型的成败，
      并提炼可执行的「模式规律」（如「IC=NO 且资金净流出时，实际下跌 X%」）；
    * 反哺闭环：prediction_feedback() 把预测命中率转成置信度/仓位调整信号，
      供 learning_feedback 合并进 orchestrator → IC 越跑越准。

与既有 learning_feedback.py（交易级胜率反哺）是**互补的两层学习**：
    - learning_feedback 基于「真实成交」胜率（需成交样本，沙箱暂无）；
    - 本中心基于「每日预测」回放（无需成交，每天都有，立即可用）。
    两层都汇入 orchestrator 的 learning_feedback()，缺一样不偏废。

输入（只读）：
    output/learning_log.jsonl              (本中心维护的预测日志，自动创建)
    output/sector_flow_history.json        (capital_migration 落盘的板块日净流时序)
    output/archive/brain_report_*.json     (首次运行时播种历史裁决，作为初始样本)

输出：
    build() -> dict  (memo 学习块：n_predictions / n_replayed / 命中率 / 近期复盘 / 模式规律 / 自省)
    prediction_feedback() -> dict  (供 learning_feedback 合并的反哺信号)
"""
import os
import json
import glob
from datetime import datetime, date

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
PRED_PATH = os.path.join(OUT, "learning_log.jsonl")
HIST_PATH = os.path.join(OUT, "sector_flow_history.json")
ARCHIVE_DIR = os.path.join(OUT, "archive")

# 启用反哺的最小回放样本（预测级，比交易级低，因为每天都有）
MIN_REPLAY = 3
CAP = 12            # 预测级置信度净调整上限（与 learning_feedback 一致）

# ── Adaptive Feedback Freeze（Phase 1E / Research Freeze）──
# 自适应反哺（prediction_feedback 的 pos_scale/conf_delta、suggested_weights 的动态权重）
# 会把「市场结果」反向写入生产决策/参数，违反 Research Freeze（禁止 Outcome→Parameter Change）。
# 默认关闭：学习信号继续计算并写入 learning_log（record-only），但绝不改变生产决策。
# 重新启用需人工置 ADAPTIVE_FEEDBACK_ENABLED=1 并经 Release Gate 审查。
ADAPTIVE_FEEDBACK_ENABLED = os.getenv("ADAPTIVE_FEEDBACK_ENABLED", "0") == "1"

# ── Learning 核心（Slice 8 升级）：维度命中率 → 动态权重 ──
# 决策分组（与 IC 加权评分一致）：资金/产业/宏观/技术/风险/估值
_GROUP_OF_LAYER = {
    "L1": "宏观", "L2": "宏观",
    "L3": "产业", "L3_5": "产业",
    "L4": "资金", "FLOW": "资金",
    "L5": "技术", "sentiment": "技术",
    "L7": "风险",
    "fundamental": "估值",
    "L6": "其他", "L8": "其他",
}
# IC 决策基准权重（资金40 / 产业25 / 宏观15 / 技术10 / 风险10；估值作参考 0）
_BASE_DECISION_WEIGHTS = {"资金": 40, "产业": 25, "宏观": 15, "技术": 10, "风险": 10, "估值": 0}
# 启用动态权重校准所需的最小「带分层方向的回放」样本数（三档门槛，防过拟合）
#   < MIN_WEIGHT_SAMPLES          → 只记录，不调整权重
#   MIN_WEIGHT_SAMPLES ~ MED      → 小幅调整，单组相对基准 ±5 个百分点
#   >= MED_WEIGHT_SAMPLES         → 正常调整（按命中率相对 50% 缩放，封顶 2.0x）
MIN_WEIGHT_SAMPLES = 30
MED_WEIGHT_SAMPLES = 100


def _layer_vote(d):
    """方向 → 对'现在做多'的投票（与 investment_committee 一致）。"""
    if d in ("bullish", "neutral_bullish"):
        return "support"
    if d in ("bearish", "bearish_weak"):
        return "oppose"
    return "neutral"


def _capture_layer_dirs(src):
    """从 IC 评分板（实时 scoreboard）或 archive 的 results 提取每层方向。

    实时 memo.committee.scoreboard：[{layer, direction, ...}]
    历史 archive brain_report.results：{层名: {direction, ...}}
    两种格式都支持，确保历史播种也能拿到分层方向（否则维度命中率恒为 0）。
    """
    if not isinstance(src, dict):
        return {}
    out = {}
    # 1) 实时格式：scoreboard
    sb = src.get("scoreboard") or []
    if sb:
        for r in sb:
            if isinstance(r, dict) and r.get("layer"):
                out[r["layer"]] = r.get("direction")
        if out:
            return out
    # 2) archive 格式：results（键即层名）
    res = src.get("results") or {}
    for k, v in res.items():
        if isinstance(v, dict) and v.get("layer"):
            d = v.get("direction")
            if d:
                out[k] = d
    return out


# ── 日志读写 ───────────────────────────────────────────────
def _load_preds():
    if not os.path.exists(PRED_PATH):
        return []
    out = []
    try:
        with open(PRED_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def _save_preds(preds):
    os.makedirs(OUT, exist_ok=True)
    with open(PRED_PATH, "w", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def _history_dates():
    if not os.path.exists(HIST_PATH):
        return [], {}
    try:
        d = json.load(open(HIST_PATH, "r", encoding="utf-8"))
        h = d.get("history", {})
        # 快照为 {板块: net_now(float)} 扁平字典；也可能被其它实现包成 {sectors:[...]}
        clean = {}
        for k, v in h.items():
            if isinstance(v, dict) and "sectors" in v:
                for s in v["sectors"]:
                    if isinstance(s, dict) and "sector" in s:
                        clean[k] = {s["sector"]: float(s.get("net_now") or 0) for s in v["sectors"]}
            elif isinstance(v, dict):
                clean[k] = {sk: float(sv) for sk, sv in v.items() if isinstance(sv, (int, float))}
        return sorted(clean.keys()), clean
    except Exception:
        return [], {}


def _aggregate_net(snapshot):
    vals = [v for v in snapshot.values() if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else 0.0


def _seed_from_archives(preds):
    """首次运行（日志为空）时，从 archive 的 brain_report 播种历史 IC 裁决作为初始样本。"""
    if preds:
        return preds
    if not os.path.isdir(ARCHIVE_DIR):
        return preds
    have = {p.get("date") for p in preds}
    seeded = []
    for fp in sorted(glob.glob(os.path.join(ARCHIVE_DIR, "brain_report_*.json"))):
        try:
            b = json.load(open(fp, "r", encoding="utf-8"))
        except Exception:
            continue
        td = b.get("trade_date") or ""
        if not td or td in have:
            continue
        com = b.get("committee") or b.get("decision") or {}
        cb = com.get("can_buy")
        if not cb:
            continue
        have.add(td)
        seeded.append({
            "date": td,
            "source": "archive",
            "full": False,
            "ic_can_buy": cb,
            "ic_direction": com.get("direction", ""),
            "ic_position": com.get("position_pct", ""),
            "debate_verdict": "",
            "scenario": [],
            "migration_focus": "",
            "layer_dirs": _capture_layer_dirs(b),
            "replayed": False,
        })
    if seeded:
        _save_preds(seeded)
    return seeded


# ── 记录当日预测 ───────────────────────────────────────────
def log_prediction(memo):
    """把当日完整预测追加进日志（幂等：同日 produce 来源不重复）。"""
    try:
        td = memo.trade_date
        if not td:
            return False
        preds = _load_preds()
        # 幂等：若已有同日 source=produce 记录则跳过
        for p in preds:
            if p.get("date") == td and p.get("source") == "produce":
                return False
        # 同日的 archive 种子记录由 produce 完整记录覆盖（按日期去重，避免重复计数）
        preds = [p for p in preds if p.get("date") != td]
        # 情景基准分支（权重最高）
        scenario = []
        sc = getattr(memo, "scenario", None) or {}
        for v in sc.get("variables", []) or []:
            branches = v.get("branches", []) or []
            if not branches:
                continue
            base = max(branches, key=lambda b: b.get("weight", 0))
            scenario.append({
                "var": v.get("title", ""),
                "base_branch": base.get("name", ""),
                "winners": base.get("winners", []) or [],
                "losers": base.get("losers", []) or [],
            })
        debate = getattr(memo, "debate", None) or {}
        mig = getattr(memo, "migration", None) or {}
        rec = {
            "date": td,
            "source": "produce",
            "full": True,
            "ic_can_buy": memo.can_buy,
            "ic_direction": debate.get("direction", ""),
            "ic_position": debate.get("position_pct", "") or memo.position_pct,
            "debate_verdict": debate.get("verdict", ""),
            "scenario": scenario,
            "migration_focus": mig.get("focus", "") or (mig.get("rotation", {}) or {}).get("in_top", [None])[0] or "",
            "layer_dirs": _capture_layer_dirs(getattr(memo, "committee", None)),
            "replayed": False,
        }
        preds.append(rec)
        _save_preds(preds)
        return True
    except Exception:
        return False


# ── 回放（T+1 实际流向）─────────────────────────────────────
def replay(preds=None):
    """对未回放的预测，找下一交易日快照回看命中情况（幂等）。"""
    if preds is None:
        preds = _load_preds()
    dates, hist = _history_dates()
    if not dates:
        return preds
    changed = False
    for p in preds:
        if p.get("replayed"):
            continue
        d = p.get("date", "")
        # 下一交易日快照
        nxt = None
        for hd in dates:
            if hd > d:
                nxt = hd
                break
        if not nxt:
            continue
        snap = hist.get(nxt, {})
        if not snap:
            continue
        # IC 方向命中
        pred_up = p.get("ic_can_buy") in ("YES", "CAUTION")
        agg = _aggregate_net(snap)
        actual_up = agg > 0
        p["replayed"] = True
        p["outcome_date"] = nxt
        p["market_agg"] = round(agg, 2)
        p["ic_hit"] = (pred_up == actual_up)

        # 情景分支命中
        sc_hits = []
        for var in p.get("scenario", []) or []:
            w = [snap.get(x) for x in var.get("winners", []) if isinstance(snap.get(x), (int, float))]
            l = [snap.get(x) for x in var.get("losers", []) if isinstance(snap.get(x), (int, float))]
            w_avg = sum(w) / len(w) if w else None
            l_avg = sum(l) / len(l) if l else None
            if w_avg is None:
                hit = None
            elif l_avg is None:
                hit = w_avg > 0
            else:
                hit = w_avg > l_avg
            var["hit"] = hit
            if hit is not None:
                sc_hits.append(hit)
        if p.get("full") and sc_hits:
            p["scenario_hit"] = (sum(sc_hits) >= (len(sc_hits) + 1) // 2)
        else:
            p["scenario_hit"] = None
        changed = True
    if changed:
        _save_preds(preds)
    return preds


# ── 统计：命中率 + 模式规律 ────────────────────────────────
def _stats(preds):
    replayed = [p for p in preds if p.get("replayed")]
    ic_n = len(replayed)
    ic_hits = sum(1 for p in replayed if p.get("ic_hit"))
    ic_acc = round(ic_hits / ic_n * 100) if ic_n else None

    full_re = [p for p in replayed if p.get("full")]
    sc_n = len([p for p in full_re if p.get("scenario_hit") is not None])
    sc_hits = sum(1 for p in full_re if p.get("scenario_hit"))
    sc_acc = round(sc_hits / sc_n * 100) if sc_n else None

    # 按裁决类型的成败
    by_verdict = {}
    for p in replayed:
        cb = p.get("ic_can_buy")
        by_verdict.setdefault(cb, {"n": 0, "hit": 0})
        by_verdict[cb]["n"] += 1
        if p.get("ic_hit"):
            by_verdict[cb]["hit"] += 1
    patterns = []
    for cb, v in by_verdict.items():
        if v["n"] >= 1:
            rate = round(v["hit"] / v["n"] * 100)
            label = {"YES": "看多买入", "CAUTION": "谨慎参与", "NO": "看空回避"}.get(cb, cb)
            patterns.append({
                "label": f"当 IC={cb}（{label}）",
                "n": v["n"], "hit": v["hit"], "rate": rate,
                "note": f"{v['hit']}/{v['n']} 次方向正确；"
                        + ("该信号可信，可加权重。" if rate >= 60 else
                           ("该信号偏谨慎，按护栏下限执行。" if rate <= 40 else "样本有限，中性看待。")),
            })

    recent = []
    for p in preds[-6:]:
        if p.get("replayed"):
            recent.append({
                "date": p["date"],
                "ic": p.get("ic_can_buy"),
                "outcome": p.get("outcome_date"),
                "market_agg": p.get("market_agg"),
                "ic_hit": ("✅命中" if p.get("ic_hit") else "❌失手"),
                "scenario_hit": (("情景" + ("✅" if p.get("scenario_hit") else "❌"))
                                if p.get("scenario_hit") is not None else "—"),
            })
        else:
            recent.append({
                "date": p["date"], "ic": p.get("ic_can_buy"),
                "outcome": "待T+1回填", "market_agg": None,
                "ic_hit": "…", "scenario_hit": "…",
            })

    return {
        "ic_n": ic_n, "ic_hits": ic_hits, "ic_acc": ic_acc,
        "sc_n": sc_n, "sc_hits": sc_hits, "sc_acc": sc_acc,
        "patterns": patterns, "recent": recent,
        "n_total": len(preds),
    }


def _regularities(preds=None):
    """从回放预测中提炼『条件 → 结果』规律，产出可一句话消费的规律列表。

    设计原则（诚实护栏）：
      - 每条规律都带样本数 n；分组 n<2 时不强行下结论，只在总体规律里标注样本少；
      - 只从已有字段提炼（ic_can_buy / market_agg / scenario_hit / layer_dirs），
        绝不凭空编造成败率；
      - 最失准层直接复用 dimension_accuracy，给出"看该层时打折"的可操作建议。
    """
    if preds is None:
        preds = _load_preds()
    if not preds:
        preds = _seed_from_archives(preds)
    preds = replay(preds)
    replayed = [p for p in preds if p.get("replayed")]
    n = len(replayed)
    out = []
    if n < 2:
        return out

    def _summ(grp):
        if not grp:
            return None
        d = len(grp)
        dn = sum(1 for p in grp if (p.get("market_agg") or 0) < 0)
        avg = round(sum(p.get("market_agg") or 0 for p in grp) / d, 2)
        return d, dn, avg

    # 规律1：IC 看空(NO) 的次日实际表现
    bear = [p for p in replayed if p.get("ic_can_buy") == "NO"]
    if bear:
        d, dn, avg = _summ(bear)
        down_rate = round(dn / d * 100)
        out.append({
            "cond": "IC=NO（看空回避）",
            "result": f"次日市场 {down_rate}% 实际下跌，平均净流 {avg:+.1f}亿",
            "n": d, "hit_rate": down_rate,
            "action": ("看空信号可信，严格按护栏下限执行" if dn == d
                       else "看空信号近期有失手，谨慎"),
        })
    # 规律2：IC 看多(YES/CAUTION) 的次日实际表现
    bull = [p for p in replayed if p.get("ic_can_buy") in ("YES", "CAUTION")]
    if bull:
        d, dn, avg = _summ(bull)
        up_rate = round((d - dn) / d * 100)
        out.append({
            "cond": "IC=YES/CAUTION（看多/谨慎）",
            "result": f"次日市场 {up_rate}% 实际上涨，平均净流 {avg:+.1f}亿",
            "n": d, "hit_rate": up_rate,
            "action": ("看多信号可信，可据此配仓" if (d - dn) == d
                       else "看多信号近期有失手，控仓"),
        })
    # 规律3：情景推演（赢家/输家板块）有效性
    sc_full = [p for p in replayed if p.get("full") and p.get("scenario_hit") is not None]
    if sc_full:
        hits = sum(1 for p in sc_full if p.get("scenario_hit"))
        out.append({
            "cond": "情景推演（赢家/输家板块）",
            "result": f"{hits}/{len(sc_full)} 次赢家板块次日跑赢输家",
            "n": len(sc_full), "hit_rate": round(hits / len(sc_full) * 100),
            "action": ("板块分化有效，可据此配板块" if hits >= len(sc_full) / 2
                       else "板块分化近期偏弱，降低对情景的依赖"),
        })
    # 规律4：最不可信的研究层（复用逐层命中率）
    da = dimension_accuracy(preds)
    if da:
        worst = min(da.items(), key=lambda kv: kv[1]["acc"])
        if worst[1]["acc"] < 60:
            out.append({
                "cond": f"最不可信信号：{worst[0]} 层",
                "result": f"方向命中率仅 {worst[1]['acc']}%（{worst[1]['hit']}/{worst[1]['n']}）",
                "n": worst[1]["n"], "hit_rate": worst[1]["acc"],
                "action": f"看 {worst[0]} 层信号时打折——动态权重已自动下调其占比",
            })
    return out


def dimension_accuracy(preds=None):
    """统计每个研究层（L1~L8）的方向命中率：预测做多/做空 vs T+1 实际市场涨跌。

    仅用 replayed 且带 layer_dirs 的预测。返回 {layer: {n, hit, acc}}。
    """
    if preds is None:
        preds = _load_preds()
    if not preds:
        preds = _seed_from_archives(preds)
    preds = replay(preds)
    stats = {}
    for p in preds:
        if not p.get("replayed"):
            continue
        dirs = p.get("layer_dirs") or {}
        if not dirs:
            continue
        actual_up = (p.get("market_agg") or 0) > 0
        for L, d in dirs.items():
            v = _layer_vote(d)
            if v == "neutral":
                continue
            s = stats.setdefault(L, {"n": 0, "hit": 0})
            s["n"] += 1
            if (v == "support" and actual_up) or (v == "oppose" and not actual_up):
                s["hit"] += 1
    out = {}
    for L, s in stats.items():
        if s["n"] > 0:
            out[L] = {"n": s["n"], "hit": s["hit"], "acc": round(s["hit"] / s["n"] * 100)}
    return out


def suggested_weights(preds=None):
    """把逐层命中率滚动到决策分组（资金/产业/宏观/技术/风险/估值），
    按命中率相对 50% 调整各组权重并归一化，输出基准 vs 校准后权重。

    样本不足（< MIN_WEIGHT_SAMPLES 条带分层方向的回放）时 applied=False，沿用基准。
    """
    if preds is None:
        preds = _load_preds()
    if not preds:
        preds = _seed_from_archives(preds)
    preds = replay(preds)
    da = dimension_accuracy(preds)

    # 分组命中率（按层样本量加权）
    group_acc = {}
    for L, st in da.items():
        g = _GROUP_OF_LAYER.get(L)
        if not g or g == "其他":
            continue
        bucket = group_acc.setdefault(g, {"n": 0, "hit": 0})
        bucket["n"] += st["n"]
        bucket["hit"] += st["acc"] * st["n"] / 100.0
    group_acc_pct = {g: round(b["hit"] / b["n"] * 100) for g, b in group_acc.items() if b["n"] > 0}

    # ── Adaptive Feedback Freeze（Phase 1E / Research Freeze）──
    # 冻结时：不据命中率调整任何权重，suggested 退化为基准权重；applied=False 使
    # os2_report 继续用 DEFAULT_WEIGHTS，Composite 决策不被学习信号污染。
    if not ADAPTIVE_FEEDBACK_ENABLED:
        group_acc_pct = {}

    base = dict(_BASE_DECISION_WEIGHTS)
    suggested = {}
    total_samples = sum(st["n"] for st in da.values())
    # 三档校准闸门（防过拟合式权重漂移）
    if total_samples < MIN_WEIGHT_SAMPLES:
        applied = False
        cap_pct = 0          # 只记录，不调整
    elif total_samples < MED_WEIGHT_SAMPLES:
        applied = True
        cap_pct = 5          # 小幅调整带：单组相对基准 ±5 个百分点
    else:
        applied = True
        cap_pct = None       # 正常调整（按命中率缩放，封顶 2.0x）

    if not ADAPTIVE_FEEDBACK_ENABLED:
        applied = False

    for g, w in base.items():
        if g in group_acc_pct and group_acc_pct[g] > 0:
            factor = max(0.4, min(2.0, group_acc_pct[g] / 50.0))  # 命中率越高权重越大
            raw = round(w * factor, 1)
        else:
            raw = w
        if cap_pct is not None and applied:
            # 小幅调整带：限制单组相对基准 ±cap_pct 个百分点，避免样本偏少时剧烈漂移
            lo, hi = w - cap_pct, w + cap_pct
            suggested[g] = round(min(hi, max(lo, raw)), 1)
        else:
            suggested[g] = raw
    # 归一化（估值 0 权重不参与归一）
    tot = sum(v for g, v in suggested.items() if g != "估值")
    if tot > 0:
        suggested = {g: round(v / tot * 100, 1) for g, v in suggested.items()}

    if not applied:
        note = (f"样本不足（需 ≥{MIN_WEIGHT_SAMPLES} 条带分层方向的回放，当前 {total_samples}），"
                f"只记录不调整，暂用基准权重；系统每日回放后自动校准。")
    elif cap_pct is not None:
        note = (f"试点小幅校准：基于 {total_samples} 条分层回放（{MIN_WEIGHT_SAMPLES}~{MED_WEIGHT_SAMPLES} 档），"
                f"单组权重相对基准限制 ±{cap_pct}%，防过拟合。")
    else:
        note = (f"已基于 {total_samples} 条带分层方向的回放（≥{MED_WEIGHT_SAMPLES}）自动校准权重")
    if not ADAPTIVE_FEEDBACK_ENABLED:
        note = ("[Record-Only] 自适应权重校准已冻结（Research Freeze）："
                f"基于 {total_samples} 条分层回放本可校准，但按治理要求不回写生产权重，"
                f"Composite 继续用基准权重。")

    return {
        "applied": applied,
        "samples": total_samples,
        "base": base,
        "suggested": suggested,
        "group_acc": group_acc_pct,
        "note": note,
    }


def build():
    """构建学习复盘块。返回 dict（供 memo 渲染）。"""
    preds = _load_preds()
    if not preds:
        preds = _seed_from_archives(preds)
    preds = replay(preds)
    st = _stats(preds)

    low = st["ic_n"] < MIN_REPLAY
    if low:
        self_note = (f"预测复盘样本 {st['ic_n']} 条（目标 ≥{MIN_REPLAY}）。"
                     f"系统每日自动回放，样本积累后可输出稳定成败率与模式规律。")
    else:
        fb_status = ("规律已反哺 IC 置信度调整"
                     if ADAPTIVE_FEEDBACK_ENABLED
                     else "规律仅记录（自适应反哺冻结中，不回写生产参数）")
        self_note = (f"已回放 {st['ic_n']} 次预测：IC 方向命中率 "
                     f"{st['ic_acc']}%，情景分支命中率 "
                     f"{st['sc_acc'] if st['sc_acc'] is not None else '—'}%。"
                     f"{fb_status}。")

    # ── Slice 8：维度命中率 + 动态权重 ──
    da = dimension_accuracy(preds)
    sw = suggested_weights(preds)
    # 在说明中补充「基于几个交易日 / 三档门槛」，样本偏少时诚实标注
    samples = sw.get("samples", 0)
    if not sw.get("applied"):
        sw["note"] = (f"仅记录未调整（分层样本 {samples}/{MIN_WEIGHT_SAMPLES}）；"
                      f"已回放 {st['ic_n']} 个交易日，达标后自动接管基准权重")
    elif samples < MED_WEIGHT_SAMPLES:
        sw["note"] = (f"试点小幅校准（分层样本 {samples}，{MIN_WEIGHT_SAMPLES}~{MED_WEIGHT_SAMPLES} 档，"
                      f"单组 ±5%）：基于 {st['ic_n']} 个交易日")
    else:
        sw["note"] = (f"已生效：基于 {st['ic_n']} 个交易日、{samples} 条分层回放自动校准"
                      f"（权重随每日回放持续修正）")

    return {
        "trade_date": date.today().isoformat(),
        "n_predictions": st["n_total"],
        "n_replayed": st["ic_n"],
        "ic_accuracy": st["ic_acc"],
        "scenario_accuracy": st["sc_acc"],
        "patterns": st["patterns"],
        "regularities": _regularities(preds),
        "recent": st["recent"],
        "self_note": self_note,
        "low_sample": low,
        "min_replay": MIN_REPLAY,
        # ── Learning 核心：逐层命中率 + 动态权重建议 ──
        "dimension_accuracy": da,
        "suggested_weights": sw,
    }


# ── 反哺信号（供 learning_feedback 合并）────────────────────
def prediction_feedback():
    """把预测回放结果转成置信度/仓位调整信号，供 learning_feedback 合并。

    Record-Only 约束（Phase 1E / Research Freeze）：当 ADAPTIVE_FEEDBACK_ENABLED 关闭时，
    信号继续计算并暴露 accuracy/n（供 provenance 记录），但 applied=False、conf_delta=0、
    pos_scale=1.0，绝不回写生产决策/参数（禁止 Outcome→Parameter Change）。
    """
    preds = _load_preds()
    if not preds:
        preds = _seed_from_archives(preds)
    preds = replay(preds)
    st = _stats(preds)
    n = st["ic_n"]
    acc = st["ic_acc"]
    if n < MIN_REPLAY:
        return {"applied": False, "source": "prediction", "count": n,
                "conf_delta": 0, "pos_scale": 1.0,
                "notes": [f"预测回放样本 {n} 条（≥{MIN_REPLAY} 启用），持续积累中。"],
                "accuracy": acc}
    if not ADAPTIVE_FEEDBACK_ENABLED:
        return {"applied": False, "source": "prediction", "count": n,
                "conf_delta": 0, "pos_scale": 1.0,
                "notes": [f"[Record-Only] 预测回放 {n} 次，IC 方向命中率 {acc}%；"
                          f"自适应反哺已冻结（Research Freeze），不回写 pos_scale/conf_delta。"],
                "accuracy": acc}
    conf_delta = max(-CAP, min(CAP, round((acc - 50) / 10 * 3, 1)))
    pos_scale = 1.0
    if acc < 40:
        pos_scale = 0.7
    elif acc < 50:
        pos_scale = 0.85
    notes = [f"预测回放：{n} 次复盘，IC 方向命中率 {acc}%，"
             f"置信度净调整 {conf_delta:+.1f}、仓位护栏"
             f"{'收紧至70%' if pos_scale==0.7 else ('收紧至85%' if pos_scale==0.85 else '维持')}。"]
    return {"applied": True, "source": "prediction", "count": n,
            "accuracy": acc, "conf_delta": conf_delta, "pos_scale": pos_scale,
            "notes": notes}


if __name__ == "__main__":
    b = build()
    print(f"交易日: {b['trade_date']}  预测总数: {b['n_predictions']}  已回放: {b['n_replayed']}")
    print(f"IC 方向命中率: {b['ic_accuracy']}%（样本不足则 None）")
    print(f"情景分支命中率: {b['scenario_accuracy']}")
    print(f"\n自省: {b['self_note']}")
    if b["patterns"]:
        print("\n【模式规律】")
        for p in b["patterns"]:
            print(f"  ▸ {p['label']}：{p['note']}")
    print("\n【近期复盘】")
    for r in b["recent"]:
        print(f"  {r['date']} IC={r['ic']} → {r['outcome']} 市场广度={r['market_agg']} "
              f"{r['ic_hit']} {r['scenario_hit']}")
