"""Institutional Daily Report Generator (Upgraded)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

BEIJING = timezone(timedelta(hours=8))

REPORTS_DIR = Path(__file__).parent / "reports"
SCORING_DIR = Path(__file__).parent / "strategy" / "output"
GLOBAL_DIR = Path(__file__).parent / "global_market" / "output"


def load_scoring_results() -> dict:
    results = {}
    for name in ["market_score", "sector_score", "leader_score"]:
        path = SCORING_DIR / f"{name}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                results[name.replace("_score", "")] = json.load(f)
    return results


def load_global_results() -> dict:
    results = {}
    for name in ["global_score", "global_rps", "theme_mapping", "divergence"]:
        path = GLOBAL_DIR / f"{name}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                results[name] = json.load(f)
    return results


def generate_report(data: dict, global_data: dict, output_path: Optional[Path] = None) -> str:
    now = datetime.now(BEIJING)
    date_str = now.strftime("%Y-%m-%d")
    
    sections = []
    sections.append(f"# Institutional Daily Report - {date_str}\\n")
    sections.append("> Source: Vibe-Research + Global Market Analysis\\n")
    sections.append("---\\n")
    sections.append(_gen_global_environment(global_data))
    sections.append(_gen_market_overview(data))
    sections.append(_gen_global_trends(global_data))
    sections.append(_gen_divergence_analysis(global_data))
    sections.append(_gen_capital_analysis(data, global_data))
    sections.append(_gen_leader_analysis(data))
    sections.append(_gen_limit_up_ladder(data))
    sections.append(_gen_profit_effect(data))
    sections.append(_gen_trading_plan(data, global_data))
    sections.append("\\n---\\n**Disclaimer**: For reference only.\\n")
    
    report = "\\n".join(sections)
    
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
    
    return report


def _gen_global_environment(global_data: dict) -> str:
    score = global_data.get("global_score", {})
    lines = []
    lines.append("## 1. Global Market Environment\\n")
    
    if not score:
        lines.append("No global data\\n")
        return "\\n".join(lines)
    
    total = score.get("total_score", 0)
    stage = score.get("stage", "unknown")
    risk = score.get("risk_appetite", 0)
    tech = score.get("tech_cycle", 0)
    liquidity = score.get("liquidity", 0)
    china = score.get("china_relative", 0)
    analysis = score.get("analysis", "")
    
    lines.append(f"### Global Risk Score: {total:.0f}/100 ({stage})\\n")
    lines.append("**Breakdown:**\\n")
    lines.append(f"- Risk Appetite: {risk:.0f}/100 (30%)")
    lines.append(f"- Tech Cycle: {tech:.0f}/100 (30%)")
    lines.append(f"- Liquidity: {liquidity:.0f}/100 (20%)")
    lines.append(f"- China Relative: {china:.0f}/100 (20%)")
    lines.append("")
    
    if analysis:
        lines.append(f"**Analysis:** {analysis}\\n")
    
    return "\\n".join(lines)


def _gen_global_trends(global_data: dict) -> str:
    themes = global_data.get("theme_mapping", {})
    lines = []
    lines.append("## 2. Global Industry Trends\\n")
    
    if not themes or not themes.get("themes"):
        lines.append("No theme data\\n")
        return "\\n".join(lines)
    
    for t in themes.get("themes", [])[:5]:
        name = t.get("name", "")
        heat = t.get("heat_score", 0)
        status = t.get("status", "")
        lines.append(f"### {name} (Heat: {heat:.0f}, Status: {status})\\n")
        
        drivers = t.get("global_drivers", [])
        if drivers:
            lines.append("**Global Drivers:**\\n")
            for d in drivers:
                sym = d.get("symbol", "")
                r = d.get("return_20d")
                r_str = f"{ret:+.1f}%" if r else "N/A"
                lines.append(f"- {sym}: {r_str}")
            lines.append("")
        
        mappings = t.get("china_mapping", [])
        if mappings:
            lines.append("**China Mapping:**\\n")
            for m in mappings:
                mname = m.get("name", "")
                stocks = m.get("stocks", [])
                names = [s.get("name", "") for s in stocks[:3]]
                joined = ", ".join(names)
                lines.append(f"- {mname}: {joined}")
            lines.append("")
    
    return "\\n".join(lines)


def _gen_divergence_analysis(global_data: dict) -> str:
    divergence = global_data.get("divergence", {})
    lines = []
    lines.append("## 3. A-Share Divergence Analysis\\n")
    
    if not divergence or not divergence.get("divergences"):
        lines.append("No significant divergence\\n")
        return "\\n".join(lines)
    
    for d in divergence.get("divergences", []):
        china = d.get("china_name", "")
        g = d.get("global_name", "")
        excess = d.get("excess_return", 0)
        level = d.get("level", "")
        lines.append(f"- {china} vs {g}: excess {excess:+.1f}% ({level})")
    lines.append("")
    
    return "\\n".join(lines)


def _gen_market_overview(data: dict) -> str:
    market = data.get("market", {})
    lines = []
    lines.append("## 4. A-Share Market Overview\\n")
    
    if not market:
        lines.append("No data\\n")
        return "\\n".join(lines)
    
    score = market.get("score", 0)
    stage = market.get("stage", "unknown")
    lines.append(f"Score: {score:.2f} ({stage})\\n")
    
    return "\\n".join(lines)


def _gen_capital_analysis(data: dict, global_data: dict) -> str:
    sectors = data.get("sectors", [])
    lines = []
    lines.append("## 5. Capital Flow Analysis\\n")
    
    if not sectors:
        lines.append("No data\\n")
        return "\\n".join(lines)
    
    for i, s in enumerate(sectors[:5], 1):
        name = s.get("name", "")
        score = s.get("score", 0)
        tier = s.get("tier", "")
        lines.append(f"TOP{i}: {name} ({score:.1f}, {tier})")
    lines.append("")
    
    return "\\n".join(lines)


def _gen_leader_analysis(data: dict) -> str:
    leaders = data.get("leaders", [])
    lines = []
    lines.append("## 6. Leader Analysis\\n")
    
    if leaders:
        for i, l in enumerate(leaders[:5], 1):
            name = l.get("name", "")
            code = l.get("code", "")
            score = l.get("score", 0)
            lines.append(f"TOP{i}: {name}({code}) - {score:.1f}")
    else:
        lines.append("No confirmed leaders")
    lines.append("")
    
    return "\\n".join(lines)


def _gen_limit_up_ladder(data: dict) -> str:
    market = data.get("market", {})
    details = market.get("details", {})
    
    lines = []
    lines.append("## 7. Limit Up Ladder\\n")
    max_b = details.get("max_boards", 0)
    lines.append(f"- Max Board: {max_b}")
    lines.append("")
    
    return "\\n".join(lines)


def _gen_profit_effect(data: dict) -> str:
    market = data.get("market", {})
    details = market.get("details", {})
    
    lines = []
    lines.append("## 8. Profit Effect\\n")
    ad = details.get("ad_ratio", 0)
    lines.append(f"- A/D Ratio: {ad:.2f}")
    seal = details.get("seal_rate", 0)
    lines.append(f"- Seal Rate: {seal:.0%}")
    
    return "\\n".join(lines)


def _gen_trading_plan(data: dict, global_data: dict) -> str:
    market = data.get("market", {})
    stage = market.get("stage", "")
    
    lines = []
    lines.append("## 9. Trading Plan\\n")
    
    lines.append("### Observation\\n")
    if stage in ["Startup", "Fermentation"]:
        lines.append("- Watch main sector persistence")
    elif stage in ["Acceleration", "Climax"]:
        lines.append("- Watch leader breakdown")
    lines.append("")
    
    lines.append("### Triggers\\n")
    lines.append("- Market score > 55 in Acceleration/Fermentation")
    lines.append("- Main sector score > 70")
    lines.append("")
    
    lines.append("### Invalidation\\n")
    lines.append("- Market score < 40 or Recession")
    lines.append("- Break rate > 40%")
    lines.append("")
    
    return "\\n".join(lines)


def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str)
    parser.add_argument("--output", type=str)
    
    args = parser.parse_args()
    
    data = load_scoring_results()
    global_data = load_global_results()
    
    if not data:
        print("Error: No scoring results")
        sys.exit(1)
    
    date_str = args.date or datetime.now(BEIJING).strftime("%Y-%m-%d")
    output_path = Path(args.output) if args.output else REPORTS_DIR / f"{date_str}.md"
    
    report = generate_report(data, global_data, output_path)
    print(f"Report: {output_path}")
    print(f"Length: {len(report)} chars")


if __name__ == "__main__":
    main()





