# -*- coding: utf-8 -*-
"""
CIO Historical Baseline (Phase 1E · OBSERVATION + PROVENANCE MODE)
===============================================================
只读 / 离线 / 零生产改动。
目的：在不修改任何冻结参数的前提下，回答"这套系统目前到底有没有信息增量？"

七层 + Counterfactual + 10 核心数字 + CIO Health Dashboard。
统计纪律：样本 N<30 只做描述性现象观察，绝不做显著性/推断性结论。
Signal Loss Incident (2026-08-04 ~ 2026-08-14) 保留在样本内，单独标记。

性能注意：stock_daily 有 2342 万行，禁止全表聚合；市场代理只 IN 查询所需日期。

输出：
  backend/audit/cio_baseline.json
"""
import sqlite3, json, glob, re, os
from collections import defaultdict

ROOT = "C:/Users/JOY/WorkBuddy/个人AI研投系统"
DB = os.path.join(ROOT, "backend/database/vibe_research.db")
ARCHIVE = os.path.join(ROOT, "backend/output/archive/brain_report_2026-*.json")
MEMO_DIR = os.path.join(ROOT, "backend/output")
OUT_JSON = os.path.join(ROOT, "backend/audit/cio_baseline.json")

INCIDENT_FROM, INCIDENT_TO = "2026-08-04", "2026-08-14"

# ---------- Layer 2/3: IC 与 Composite 加载（不依赖 DB 大表） ----------
def load_ic():
    recs = {}
    for f in sorted(glob.glob(ARCHIVE)):
        try:
            d = json.load(open(f, encoding="utf-8"))
            td = d.get("trade_date")
            if not td:
                continue
            decision = d.get("decision", {}) or {}
            can = str(decision.get("can_buy", "")).upper()
            pos = decision.get("position_pct")
            if isinstance(pos, str):
                nums = re.findall(r"\d+\.?\d*", pos)
                if len(nums) >= 2:
                    pos = (float(nums[0]) + float(nums[1])) / 2.0
                elif nums:
                    pos = float(nums[0])
                else:
                    pos = None
            res = d.get("results", {})
            l7 = (res.get("L7", {}).get("raw", {}) or {}).get("composite")
            cio = d.get("cio_memo", {}) or {}
            tp = cio.get("trading_plan", {}) or {}
            opps = tp.get("opportunities", []) or []
            cands = []
            for o in opps:
                tier = str(o.get("tier", "")).upper()
                cands.append({"tier": tier, "name": o.get("name", ""),
                              "sector": (o.get("sector") or o.get("cat") or o.get("name") or "")})
            for m in (cio.get("main_lines", []) or []):
                nm = m.get("name") or m.get("sector")
                if nm:
                    cands.append({"tier": "LINE", "name": nm, "sector": nm})
            recs[td] = {"date": td, "can_buy": can, "position_pct": pos, "l7": l7,
                        "candidates": cands, "n_cand": len([c for c in cands if c["tier"] in ("A", "B", "C")])}
        except Exception as e:
            print(f"  [warn] IC load fail {os.path.basename(f)}: {e}", flush=True)
    return recs

def load_memo():
    recs = {}
    files = sorted(glob.glob(os.path.join(MEMO_DIR, "memo_2026-*.html")))
    bydate = {}
    for f in files:
        m = re.search(r"memo_(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        if not m:
            continue
        td = m.group(1)
        is_wx = "_wechat" in os.path.basename(f)
        if td in bydate:
            if is_wx and "_wechat" not in bydate[td]:
                bydate[td] = f
        else:
            bydate[td] = f
    for td, f in bydate.items():
        try:
            html = open(f, encoding="utf-8", errors="ignore").read()
            mv = re.search(r"今日裁决</div><div[^>]*>([^<]*)", html)
            verdict = mv.group(1).strip() if mv else ""
            sm = re.search(r"font-size:34px[^>]*>(\d+)</div>\s*<div[^>]*>综合评分/100", html)
            score = int(sm.group(1)) if sm else None
            if score is None:
                continue
            if "可以买" in verdict:
                w = 1.0
            elif "谨慎参与" in verdict:
                w = 0.5
            elif "不交易" in verdict:
                w = 0.0
            else:
                w = None
            recs[td] = {"date": td, "composite": score, "verdict": verdict, "final_w": w}
        except Exception as e:
            print(f"  [warn] memo parse fail {os.path.basename(f)}: {e}", flush=True)
    return recs

ic = load_ic()
memo = load_memo()
print("[p] ic", len(ic), "memo", len(memo), flush=True)

# ---------- 基础数据（避免 stock_daily 全表扫描） ----------
con = sqlite3.connect(DB); cur = con.cursor()
# 交易日历从 sector_daily（小表）取
cur.execute("SELECT DISTINCT date FROM sector_daily ORDER BY date")
tdates = [r[0] for r in cur.fetchall()]
tidx = {d: i for i, d in enumerate(tdates)}
print("[p] tdates", len(tdates), flush=True)

# 只查需要的日期：决策日 + 其后 10 个交易日
all_dates = sorted(set(ic.keys()) | set(memo.keys()))
needed = set(all_dates)
for d in all_dates:
    i = tidx.get(d)
    if i is not None:
        for k in range(1, 11):
            if i + k < len(tdates):
                needed.add(tdates[i + k])
ph = ",".join("?" * len(needed))
cur.execute(f"SELECT date, AVG(change_pct) FROM stock_daily WHERE date IN ({ph}) GROUP BY date", list(needed))
mkt = {d: r for d, r in cur.fetchall()}
cur.execute(f"SELECT date, COUNT(*), SUM(CASE WHEN change_pct>0 THEN 1 ELSE 0 END) FROM stock_daily WHERE date IN ({ph}) GROUP BY date", list(needed))
breadth = {d: (up, tot) for d, tot, up in cur.fetchall()}
print("[p] mkt", len(mkt), "breadth", len(breadth), flush=True)

# 板块收益（125k 行，可接受）
cur.execute("SELECT date, sector_name, change_pct FROM sector_daily WHERE change_pct IS NOT NULL")
sec = {}
for d, s, c in cur.fetchall():
    sec[(d, s.strip())] = c
known_sectors = set(s.strip() for (_, s) in sec.keys())
print("[p] sec", len(sec), "known_sectors", len(known_sectors), flush=True)

cur.execute("SELECT date, COUNT(*) FROM limit_up_daily GROUP BY date")
lim_up = {d: n for d, n in cur.fetchall()}
con.close()
print("[p] db closed", flush=True)

def fwd(date, h, ret_map):
    i = tidx.get(date)
    if i is None or i + h >= len(tdates):
        return None
    prod = 1.0
    for k in range(1, h + 1):
        dk = tdates[i + k]
        r = ret_map.get(dk)
        if r is None:
            return None
        prod *= (1 + r / 100.0)
    return (prod - 1) * 100.0

def fwd_sector(date, h, sector):
    i = tidx.get(date)
    if i is None or i + h >= len(tdates):
        return None
    prod = 1.0
    for k in range(1, h + 1):
        dk = tdates[i + k]
        r = sec.get((dk, sector.strip()))
        if r is None:
            return None
        prod *= (1 + r / 100.0)
    return (prod - 1) * 100.0

# ---------- 合并逐日记录 ----------
dates = sorted(set(ic.keys()) | set(memo.keys()))
records = []
for td in dates:
    r = {"date": td, "incident": INCIDENT_FROM <= td <= INCIDENT_TO}
    if td in ic:
        r.update(ic[td])
    if td in memo:
        r.update({k: v for k, v in memo[td].items() if k != "date"})
    r["fwd1"] = fwd(td, 1, mkt)
    r["fwd3"] = fwd(td, 3, mkt)
    r["fwd5"] = fwd(td, 5, mkt)
    r["fwd10"] = fwd(td, 10, mkt)
    b = breadth.get(td)
    r["breadth"] = (b[0] / b[1]) if b and b[1] else None
    r["lim_up"] = lim_up.get(td)
    records.append(r)
print("[p] records", len(records), flush=True)

def avg(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs), len(xs)) if xs else (None, 0)

def hit(xs):
    xs = [x for x in xs if x is not None]
    return (sum(1 for x in xs if x > 0) / len(xs), len(xs)) if xs else (None, 0)

# ================= LAYER 1: 市场环境 =================
def env(subset):
    mr, n1 = avg([mkt.get(r["date"]) for r in subset if r["date"] in mkt])
    br, n2 = avg([r["breadth"] for r in subset if r.get("breadth") is not None])
    lu, n3 = avg([r["lim_up"] for r in subset if r.get("lim_up") is not None])
    return {"avg_mkt_ret": round(mr, 3) if mr is not None else None, "n_mkt": n1,
            "avg_breadth": round(br, 4) if br is not None else None, "n_br": n2,
            "avg_limit_up": round(lu, 2) if lu is not None else None, "n_lu": n3}

L1_all = env(records)
L1_inc = env([r for r in records if r["incident"]])

# ================= LAYER 2: IC =================
ic_recs = [r for r in records if r.get("can_buy")]
ic_yes = [r for r in ic_recs if r["can_buy"] == "YES"]
ic_no = [r for r in ic_recs if r["can_buy"] == "NO"]

def ic_stats(group):
    f1, n1 = avg([r["fwd1"] for r in group])
    f3, n3 = avg([r["fwd3"] for r in group])
    f5, n5 = avg([r["fwd5"] for r in group])
    f10, n10 = avg([r["fwd10"] for r in group])
    h1, _ = hit([r["fwd1"] for r in group])
    h3, _ = hit([r["fwd3"] for r in group])
    pos = avg([r.get("position_pct") for r in group if r.get("position_pct") is not None])
    return {"n": len(group),
            "fwd1": round(f1, 3) if f1 is not None else None, "n1": n1,
            "fwd3": round(f3, 3) if f3 is not None else None, "n3": n3,
            "fwd5": round(f5, 3) if f5 is not None else None, "n5": n5,
            "fwd10": round(f10, 3) if f10 is not None else None, "n10": n10,
            "hit1": round(h1, 3) if h1 is not None else None,
            "hit3": round(h3, 3) if h3 is not None else None,
            "avg_position": round(pos[0], 1) if pos[0] is not None else None}

L2 = {"n_total": len(ic_recs), "n_yes": len(ic_yes), "n_no": len(ic_no),
      "yes": ic_stats(ic_yes), "no": ic_stats(ic_no)}

def risk_bucket(v):
    if v is None: return "NA"
    if v >= 70: return ">=70"
    if v >= 50: return "50-69"
    return "<50"
rb = defaultdict(list)
for r in ic_yes:
    rb[risk_bucket(r.get("l7"))].append(r)
L2["yes_by_risk"] = {k: ic_stats(v) for k, v in rb.items() if v}

# ================= LAYER 3: Composite 分段 =================
def comp_bin(s):
    if s < 60: return "<60"
    if s < 65: return "60-64"
    if s < 70: return "65-69"
    if s < 80: return "70-79"
    return ">=80"
comp_recs = [r for r in records if r.get("composite") is not None]
buckets = defaultdict(list)
for r in comp_recs:
    buckets[comp_bin(r["composite"])].append(r)
L3 = {}
for b, grp in sorted(buckets.items()):
    f1, n1 = avg([r["fwd1"] for r in grp])
    f3, n3 = avg([r["fwd3"] for r in grp])
    f5, n5 = avg([r["fwd5"] for r in grp])
    f10, n10 = avg([r["fwd10"] for r in grp])
    L3[b] = {"n": len(grp),
             "fwd1": round(f1, 3) if f1 is not None else None, "n1": n1,
             "fwd3": round(f3, 3) if f3 is not None else None, "n3": n3,
             "fwd5": round(f5, 3) if f5 is not None else None, "n5": n5,
             "fwd10": round(f10, 3) if f10 is not None else None, "n10": n10}

# ================= LAYER 4: IC × Composite 矩阵 =================
both = [r for r in records if r.get("can_buy") and r.get("composite") is not None]
def cell(icv, comp_hi):
    grp = [r for r in both if r["can_buy"] == icv and (r["composite"] >= 65) == comp_hi]
    f5, n5 = avg([r["fwd5"] for r in grp])
    f1, n1 = avg([r["fwd1"] for r in grp])
    veto_final_no = sum(1 for r in grp if r.get("final_w") == 0.0)
    return {"n": len(grp), "fwd1": round(f1, 3) if f1 is not None else None, "n1": n1,
            "fwd5": round(f5, 3) if f5 is not None else None, "n5": n5, "final_no": veto_final_no}
L4 = {"YES_x_hiComp": cell("YES", True), "YES_x_loComp": cell("YES", False),
      "NO_x_hiComp": cell("NO", True), "NO_x_loComp": cell("NO", False)}

# ================= LAYER 5: Veto 归因 =================
vetoes = []
for r in both:
    if r["can_buy"] == "YES" and r.get("final_w") == 0.0:
        if r["composite"] < 65:
            reason = "COMPOSITE_SCORE"
        elif (r.get("l7") or 0) >= 70:
            reason = "RISK_VETO"
        else:
            reason = "OTHER"
        vetoes.append({**r, "veto_reason": reason})
veto_rate = len(vetoes) / len(ic_yes) if ic_yes else None
veto_down = sum(1 for r in vetoes if r.get("fwd1") is not None and r["fwd1"] <= 0)
veto_up = sum(1 for r in vetoes if r.get("fwd1") is not None and r["fwd1"] > 0)
veto_n = sum(1 for r in vetoes if r.get("fwd1") is not None)
L5 = {"veto_rate": round(veto_rate, 3) if veto_rate is not None else None, "n_veto": len(vetoes),
      "n_veto_with_fwd": veto_n,
      "veto_accuracy": round(veto_down / veto_n, 3) if veto_n else None,
      "false_veto_rate": round(veto_up / veto_n, 3) if veto_n else None,
      "by_reason": {rs: sum(1 for r in vetoes if r["veto_reason"] == rs) for rs in ("COMPOSITE_SCORE", "RISK_VETO", "OTHER")},
      "detail": [{"date": r["date"], "composite": r["composite"], "l7": r.get("l7"), "fwd1": r.get("fwd1"), "reason": r["veto_reason"]} for r in vetoes]}
print("[p] L1-L5 done", flush=True)

# ================= LAYER 6: 候选方向超额 =================
def match_sector(cand_sector):
    cs = (cand_sector or "").strip()
    if not cs:
        return None
    if cs in known_sectors:
        return cs
    for s in known_sectors:
        if cs in s or s in cs:
            return s
    return None

cand_rows = []
for r in ic_recs:
    for c in r.get("candidates", []):
        if c["tier"] not in ("A", "B", "C"):
            continue
        s = match_sector(c["sector"])
        if not s:
            continue
        for h in (1, 3, 5):
            sf = fwd_sector(r["date"], h, s)
            mf = fwd(r["date"], h, mkt)
            if sf is not None and mf is not None:
                cand_rows.append({"date": r["date"], "tier": c["tier"], "sector": s,
                                  "h": h, "sec_fwd": sf, "mkt_fwd": mf, "excess": sf - mf})
L6 = {}
for tier in ("A", "B", "C"):
    rows = [x for x in cand_rows if x["tier"] == tier]
    by_h = {}
    for h in (1, 3, 5):
        ex = [x["excess"] for x in rows if x["h"] == h]
        by_h[h] = {"avg_excess": round(sum(ex) / len(ex), 3) if ex else None, "n": len(ex)}
    L6[tier] = by_h
L6["n_matched"] = len(cand_rows)
L6["n_unmatched_cands"] = sum(1 for r in ic_recs for c in r.get("candidates", []) if c["tier"] in ("A", "B", "C") and not match_sector(c["sector"]))
print("[p] L6 done matched=", L6["n_matched"], flush=True)

# ================= LAYER 7: Counterfactual =================
def scenario(name, weight_fn, ret_fn):
    eq = []
    for r in ic_recs:
        w = weight_fn(r)
        if w is None or w == 0:
            continue
        ret = ret_fn(r)
        if ret is None:
            continue
        eq.append((r["date"], w, ret))
    if not eq:
        return {"name": name, "invested": 0}
    rets = [w * rt for _, w, rt in eq]
    expo = sum(w for _, w, _ in eq) / len(ic_recs)
    eq_curve = 1.0
    for x in rets:
        eq_curve *= (1 + x / 100.0)
    mean = sum(rets) / len(rets)
    sd = (sum((x - mean) ** 2 for x in rets) / len(rets)) ** 0.5
    ir = mean / sd if sd > 0 else None
    hitr = sum(1 for _, _, rt in eq if rt > 0) / len(eq)
    return {"name": name, "invested": len(eq), "exposure": round(expo, 3),
            "avg_ret_invested": round(mean, 3), "hit_rate": round(hitr, 3),
            "equity_growth_pct": round((eq_curve - 1) * 100, 2),
            "ir_proxy_annualized": round(ir * (252 ** 0.5), 2) if ir is not None else None}

def w_final(r): return r.get("final_w")
def w_ic(r): return 1.0 if r.get("can_buy") == "YES" else 0.0
def w_ic_cand(r):
    if r.get("can_buy") != "YES": return 0.0
    secs = [match_sector(c["sector"]) for c in r.get("candidates", []) if c["tier"] in ("A", "B")]
    secs = [s for s in secs if s]
    return 1.0 if secs else 0.0
def ret_mkt(r): return r.get("fwd1")
def ret_cand(r):
    secs = [match_sector(c["sector"]) for c in r.get("candidates", []) if c["tier"] in ("A", "B")]
    secs = [s for s in secs if s]
    rs = [fwd_sector(r["date"], 1, s) for s in secs]
    rs = [x for x in rs if x is not None]
    return sum(rs) / len(rs) if rs else None

L7 = {"A_current_final": scenario("A_current_final", w_final, ret_mkt),
      "B_ic_only": scenario("B_ic_only", w_ic, ret_mkt),
      "C_ic_noveto": scenario("C_ic_noveto", w_ic, ret_mkt),
      "D_ic_candidate": scenario("D_ic_candidate", w_ic_cand, ret_cand)}
print("[p] L7 done", flush=True)

# ================= 10 核心数字 =================
ten = {"1_ic_yes_hit1": L2["yes"]["hit1"],
       "2_ic_yes_fwd5": L2["yes"]["fwd5"], "2_n": L2["yes"]["n5"],
       "3_ic_no_fwd5": L2["no"]["fwd5"], "3_n": L2["no"]["n5"],
       "4_veto_rate": L5["veto_rate"],
       "5_false_veto_rate": L5["false_veto_rate"],
       "6_composite_segments": L3,
       "7_ic_x_compound_matrix": L4,
       "8_ab_excess": {"A": L6.get("A"), "B": L6.get("B")},
       "9_signal_preservation_rate": None,
       "10_current_data_health": {"note": "来自 flow_snapshot_2026-08-17.json（Provenance 基线）",
                                  "capital_effective_weight_in_composite": 0.168,
                                  "capital_nominal_weight": 0.40,
                                  "effective_weight_fraction_of_flow": 0.40,
                                  "ashare_signal_in_composite": False, "rating": "LOW"}}
yes_with_final = [r for r in ic_yes if r.get("final_w") is not None]
preserved = sum(1 for r in yes_with_final if (r.get("final_w") or 0) > 0)
ten["9_signal_preservation_rate"] = round(preserved / len(yes_with_final), 3) if yes_with_final else None
ten["9_n_ic_yes_with_final"] = len(yes_with_final)

def z(v): return "—" if v is None else v
dashboard = {"STATUS": "OBSERVATION",
             "SAMPLE_NOTE": "N<30，仅描述性现象；推断性结论需 30~60+ 干净样本",
             "Signal_Preservation": z(ten["9_signal_preservation_rate"]),
             "IC_HitRate_1D": z(L2["yes"]["hit1"]),
             "IC_Information_Ratio_proxy": "见 L7",
             "Composite_Incremental": "见 L4/L5（待积累）",
             "Veto_FalsePositive": z(ten["5_false_veto_rate"]),
             "AB_Excess_1D": z(L6.get("A", {}).get(1, {}).get("avg_excess")),
             "Data_Health": ten["10_current_data_health"]["rating"],
             "Decision_Delivery": "GAP（Signal Loss Incident 2026-08 已记录）",
             "n_decision_days": len(ic_recs), "incident_window": f"{INCIDENT_FROM}~{INCIDENT_TO}"}

result = {"meta": {"generated": "2026-08-17", "mode": "Phase 1E · FROZEN / OBSERVATION + PROVENANCE MODE",
                   "discipline": "只读/离线/零生产改动；N<30 仅描述性", "market_proxy": "stock_daily 等权均价日收益（IN 查询所需日期）",
                   "incident_in_sample": True},
          "layer1_env": {"all": L1_all, "incident_window": L1_inc},
          "layer2_ic": L2, "layer3_composite": L3, "layer4_ic_x_comp": L4, "layer5_veto": L5,
          "layer6_candidates": L6, "layer7_counterfactual": L7, "ten_numbers": ten, "dashboard": dashboard,
          "records": records}
json.dump(result, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"决策日(IC层) N={len(ic_recs)} | Composite层 N={len(comp_recs)} | 合并 N={len(records)}", flush=True)
print(f"IC YES={len(ic_yes)} NO={len(ic_no)}", flush=True)
print(f"IC YES hit1={L2['yes']['hit1']} fwd5={L2['yes']['fwd5']}(n{L2['yes']['n5']}) | NO fwd5={L2['no']['fwd5']}(n{L2['no']['n5']})", flush=True)
print(f"Veto rate={L5['veto_rate']} false_veto={L5['false_veto_rate']} by_reason={L5['by_reason']}", flush=True)
print(f"Signal Preservation={ten['9_signal_preservation_rate']} (n={ten['9_n_ic_yes_with_final']})", flush=True)
print(f"A/B excess 1D: A={L6.get('A',{}).get(1)} B={L6.get('B',{}).get(1)}", flush=True)
print(f"Counterfactual 1D: A={L7['A_current_final'].get('equity_growth_pct','?')}% B={L7['B_ic_only'].get('equity_growth_pct','?')}% D={L7['D_ic_candidate'].get('equity_growth_pct','?')}%", flush=True)
print(f"→ 写出 {OUT_JSON}", flush=True)
