"""每日决策看板。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

BEIJING = timezone(timedelta(hours=8))

SCORING_DIR = Path(__file__).parent / "strategy" / "output"


def load_json(filename: str) -> dict | list:
    path = SCORING_DIR / filename
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_dashboard():
    now = datetime.now(BEIJING)
    date_str = now.strftime("%Y-%m-%d")
    
    market = load_json("market_score.json")
    sectors = load_json("sector_score.json")
    leaders = load_json("leader_score.json")
    
    print("=" * 60)
    print(f"  Dashboard - {date_str}")
    print("=" * 60)
    
    # ============================================================
    # Part 1: Market
    # ============================================================
    print("\n+-------------------+")
    print("| 1. Market         |")
    print("+-------------------+\n")
    
    score = market.get("score", 0)
    stage = market.get("stage", "Unknown")
    factors = market.get("factors", {})
    
    if score >= 70:
        position = "70-90%"
        decision = "PARTICIPATE (watch for exit signals)"
    elif score >= 55:
        position = "60-80%"
        decision = "PARTICIPATE"
    elif score >= 40:
        position = "40-60%"
        decision = "LIGHT POSITION"
    elif score >= 25:
        position = "20-40%"
        decision = "WAIT"
    else:
        position = "0-20%"
        decision = "REST"
    
    print(f"  Score:    {score:.2f}")
    print(f"  Stage:    {stage}")
    print(f"  Position: {position}")
    print(f"\n  >>> TODAY: {decision} <<<\n")
    
    details = market.get("details", {})
    if details:
        amt = details.get("total_amount", 0)
        ad = details.get("ad_ratio", 0)
        zt = details.get("zt_real", 0)
        dt = details.get("dt_real", 0)
        br = details.get("break_rate", 0)
        print(f"  Key Metrics:")
        print(f"    Amount: {amt:.0f}B | A/D Ratio: {ad:.2f}")
        print(f"    Limit Up: {zt} | Limit Down: {dt} | Break Rate: {br:.0%}")
    
    # ============================================================
    # Part 2: Sectors TOP3
    # ============================================================
    print("\n+-------------------+")
    print("| 2. Sectors TOP3   |")
    print("(Turnover + Persistence, NOT returns)")
    print("+-------------------+\n")
    
    if sectors:
        for i, s in enumerate(sectors[:3], 1):
            name = s.get("name", "")
            sc = s.get("score", 0)
            tier = s.get("tier", "")
            f = s.get("factors", {})
            
            conc = f.get("amount_concentration", 0)
            mom = f.get("amount_momentum", 0)
            dur = f.get("duration", 0)
            
            print(f"  TOP{i}: {name}")
            print(f"    Score: {sc:.1f} ({tier})")
            print(f"    Turnover%: {conc:.0f} | Momentum: {mom:.0f} | Duration: {dur:.0f}")
            print()
    else:
        print("  No sector data\n")
    
    # ============================================================
    # Part 3: Leaders TOP10
    # ============================================================
    print("+-------------------+")
    print("| 3. Leaders TOP10  |")
    print("+-------------------+\n")
    
    if leaders:
        print(f"  {'#':<4} {'Code':<8} {'Name':<10} {'Sector':<10} {'Score':<6} {'Type':<8}")
        print(f"  {'-'*4} {'-'*8} {'-'*10} {'-'*10} {'-'*6} {'-'*8}")
        for i, l in enumerate(leaders[:10], 1):
            code = l.get("code", "")
            name = l.get("name", "")
            sector = l.get("sector", "")
            sc = l.get("score", 0)
            cat = l.get("category", "")
            print(f"  {i:<4} {code:<8} {name:<10} {sector:<10} {sc:<6.1f} {cat:<8}")
    else:
        print("  No leader data")
        print("  (Filters: Amount>10B + Sector Score>70 + Top 3 in sector)")
    
    print(f"\n{'=' * 60}")
    print(f"  Source: Scoring Engine")
    print(f"  Disclaimer: For reference only")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    print_dashboard()
