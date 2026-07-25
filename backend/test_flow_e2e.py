# -*- coding: utf-8 -*-
"""End-to-end test of Capital Flow Engine.
Tests: commodity_data -> etf_data -> institution_data -> flow_scorer -> five_questions -> flow_agent
"""
import os
import sys
import json
import time
from pathlib import Path

# Clear proxy
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(k, None)

BACK = Path(__file__).resolve().parent
sys.path.insert(0, str(BACK))

print("=" * 60)
print("Capital Flow Engine E2E Test")
print("=" * 60)

# ---- 1. Commodity Data ----
print("\n[1/6] Testing commodity_data...")
try:
    from capital_flow.data_adapter.commodity_data import get_commodity_snapshot
    t0 = time.time()
    comm = get_commodity_snapshot()
    t1 = time.time()
    print(f"  OK ({t1-t0:.1f}s)")
    print(f"  Energy: {len(comm.energy)} items")
    print(f"  Precious: {len(comm.precious)} items")
    print(f"  Industrial: {len(comm.industrial)} items")
    print(f"  Agriculture: {len(comm.agriculture)} items")
    print(f"  Risk appetite: {comm.risk_appetite}")
    print(f"  Gaps: {comm.gaps}")
    for item in comm.all_items[:5]:
        print(f"    {item.category:12s} {item.name_cn:10s} {item.change_pct:+.2f}%  price={item.price}")
except Exception as e:
    import traceback
    print(f"  FAIL: {e}")
    traceback.print_exc()

# ---- 2. ETF Data ----
print("\n[2/6] Testing etf_data...")
try:
    from capital_flow.data_adapter.etf_data import get_etf_flow
    t0 = time.time()
    etf = get_etf_flow()
    t1 = time.time()
    print(f"  OK ({t1-t0:.1f}s)")
    print(f"  Broad: {len(etf.broad)} | Industry: {len(etf.industry)} | Theme: {len(etf.theme)}")
    print(f"  Gold: {len(etf.gold)} | Overseas: {len(etf.overseas)} | Other: {len(etf.other)}")
    print(f"  Top inflow: {len(etf.top_inflow)} | Top outflow: {len(etf.top_outflow)}")
    print(f"  Total main inflow: {etf.total_main_inflow / 1e8:.1f} Yi" if etf.total_main_inflow else "  Total main inflow: 0")
    print(f"  Gaps: {etf.gaps}")
    for e in etf.top_inflow[:3]:
        chg = f"{e.shares_change/1e4:.0f}W" if e.shares_change else "N/A"
        print(f"    INFLOW {e.code} {e.name[:16]:16s} shares={chg} amt={e.amount/1e8:.1f}Yi")
    for e in etf.top_outflow[:3]:
        chg = f"{e.shares_change/1e4:.0f}W" if e.shares_change else "N/A"
        print(f"    OUTFLOW {e.code} {e.name[:16]:16s} shares={chg} amt={e.amount/1e8:.1f}Yi")
except Exception as e:
    import traceback
    print(f"  FAIL: {e}")
    traceback.print_exc()

# ---- 3. Institution Data ----
print("\n[3/6] Testing institution_data...")
try:
    from capital_flow.data_adapter.institution_data import get_institution_flow
    t0 = time.time()
    inst = get_institution_flow(etf_snap=etf)
    t1 = time.time()
    print(f"  OK ({t1-t0:.1f}s)")
    print(f"  HSGT north_net: {inst.hsgt.north_net:.1f} Yi")
    print(f"  HSGT south_net: {inst.hsgt.south_net:.1f} Yi")
    print(f"  HSGT south_status: {inst.hsgt.south_status}")
    print(f"  National team: {len(inst.national_team)} ETFs tracked")
    for nt in inst.national_team:
        print(f"    {nt.etf_code} {nt.etf_name[:10]:10s} {nt.action} {nt.shares_change/1e4:.0f}W")
    print(f"  Gaps: {inst.gaps}")
except Exception as e:
    import traceback
    print(f"  FAIL: {e}")
    traceback.print_exc()

# ---- 4. Flow Score ----
print("\n[4/6] Testing flow_scorer...")
try:
    from capital_flow.scoring.flow_scorer import calc_flow_score
    gold_data = {"dxy": 101.06, "us_10y_yield": 4.62, "tips_10y_yield": 2.32, "gold_price": 4030}
    score = calc_flow_score(
        commodity_snap=comm,
        etf_snap=etf,
        institution_flow=inst,
        gold_data=gold_data,
    )
    print(f"  OK")
    print(f"  Overall: {score.overall}/100 ({score.overall_stars} stars)")
    for layer in [score.m1_global, score.m2_cross_asset, score.m3_etf, score.m4_sector, score.m5_individual]:
        print(f"    {layer.name:12s} {layer.name_cn:10s} score={layer.score:3d} stars={layer.stars} dir={layer.direction}")
    print(f"  One-liner: {score.one_liner}")
except Exception as e:
    import traceback
    print(f"  FAIL: {e}")
    traceback.print_exc()

# ---- 5. Five Questions ----
print("\n[5/6] Testing five_questions...")
try:
    from capital_flow.intelligence.five_questions import answer_five_questions
    intel = answer_five_questions(
        commodity_snap=comm,
        etf_snap=etf,
        institution_flow=inst,
        gold_data=gold_data,
    )
    print(f"  OK")
    print(f"  One-liner: {intel.one_liner}")
    print(f"  Q1 Global: {intel.q1_global[:120]}...")
    print(f"  Q2 China:  {intel.q2_china[:120]}...")
    print(f"  Q3 ETF:    {intel.q3_etf[:120]}...")
    print(f"  Q4 Comm:   {intel.q4_commodity[:120]}...")
    print(f"  Q5 AShare: {intel.q5_a_share[:120]}...")
except Exception as e:
    import traceback
    print(f"  FAIL: {e}")
    traceback.print_exc()

# ---- 6. Flow Agent (full pipeline) ----
print("\n[6/6] Testing flow_agent (full pipeline)...")
try:
    from capital_flow.agents.flow_agent import run as run_flow
    from brain.context import ReasoningContext

    ctx = ReasoningContext()
    t0 = time.time()
    result = run_flow(ctx)
    t1 = time.time()
    print(f"  OK ({t1-t0:.1f}s)")
    print(f"  Stage: {result.stage}")
    print(f"  Confidence: {result.confidence}")
    print(f"  Gaps: {result.gaps}")
    flow_data = ctx.get("FLOW") or {}
    raw = flow_data.get("raw", {})
    if raw.get("flow_score"):
        print(f"  Flow Score: {raw['flow_score']['overall']}/100")
    if raw.get("intelligence"):
        print(f"  Intelligence one_liner: {raw['intelligence']['one_liner']}")

    # Check reports
    json_path = BACK / "output" / "flow_report.json"
    html_path = BACK / "output" / "flow_report.html"
    print(f"  JSON report: {'OK' if json_path.exists() else 'MISSING'} ({json_path.stat().st_size/1024:.1f}KB)" if json_path.exists() else f"  JSON report: MISSING")
    print(f"  HTML report: {'OK' if html_path.exists() else 'MISSING'} ({html_path.stat().st_size/1024:.1f}KB)" if html_path.exists() else f"  HTML report: MISSING")
except Exception as e:
    import traceback
    print(f"  FAIL: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("E2E Test Complete")
print("=" * 60)
