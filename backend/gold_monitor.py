#!/usr/bin/env python3
"""Gold Monitor — Intraday gold signal detection and alerting.

Runs gold_engine pipeline, compares with previous run, detects significant
changes, and writes signals to output/gold_signal_{timestamp}.json.

Signal triggers:
  1. Score crosses 65 (bullish threshold) from below
  2. Score crosses 45 (bearish threshold) from above
  3. Direction changes (e.g., neutral → bullish)
  4. Signal level changes (e.g., C级 → A级)
  5. Cycle phase changes

Usage:
  python backend/gold_monitor.py [--time HHMM]
"""

from __future__ import annotations

import sys
import json
import os
from pathlib import Path
from datetime import datetime

BACK = Path(__file__).resolve().parent
sys.path.insert(0, str(BACK))

ROOT = BACK.parent
OUTPUT_DIR = ROOT / "output"
STATE_FILE = OUTPUT_DIR / "gold_monitor_state.json"
SIGNAL_DIR = OUTPUT_DIR / "gold_signals"


def run_gold_engine() -> dict:
    """Run gold_engine pipeline and return the report dict."""
    from gold_engine.data_adapter.gold_data import get_all_gold_factors
    from gold_engine.scoring.drive_scorer import score_drive_factors
    from gold_engine.narrative.detector import detect_narrative
    from gold_engine.cycle.state_machine import detect_cycle
    from gold_engine.plan.trading_plan import generate_plan
    from gold_engine.risk.radar import scan_risks
    from dataclasses import asdict

    gf = get_all_gold_factors()
    ds = score_drive_factors(gf)
    narrative = detect_narrative(ds)
    cycle = detect_cycle(ds, gf)
    plan = generate_plan(ds, narrative, cycle)
    radar = scan_risks()

    report = {
        "generated_at": gf.timestamp,
        "gold_price": gf.gold_price,
        "gold_change_pct": gf.gold_change_pct,
        "drive_score": asdict(ds),
        "narrative": asdict(narrative),
        "cycle": asdict(cycle),
        "plan": asdict(plan),
        "radar": asdict(radar),
        "factors": asdict(gf),
    }

    # Save gold_report.json (both locations for compatibility)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "gold_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (BACK / "output" / "gold_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    return report


def load_previous_state() -> dict:
    """Load previous run state for comparison."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict):
    """Save current state for next run comparison."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def detect_signals(current: dict, previous: dict) -> list[dict]:
    """Detect significant changes between current and previous runs."""
    signals = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ds = current.get("drive_score", {})
    plan = current.get("plan", {})
    cycle = current.get("cycle", {})

    score = ds.get("composite_score", 0)
    direction = ds.get("direction", "neutral")
    signal_level = plan.get("signal_level", "")
    phase = cycle.get("current_phase", "")
    gold_price = current.get("gold_price", 0)

    if not previous:
        # First run — no comparison, just record state
        signals.append({
            "time": now,
            "type": "initial",
            "message": f"黄金监控启动。当前评分 {score:.0f}/100，方向 {direction}，"
                       f"金价 ${gold_price:,.0f}，周期 {cycle.get('phase_name_cn', '未知')}。",
            "score": score,
            "direction": direction,
            "signal_level": signal_level,
            "gold_price": gold_price,
        })
        return signals

    prev_ds = previous.get("drive_score", {})
    prev_plan = previous.get("plan", {})
    prev_cycle = previous.get("cycle", {})

    prev_score = prev_ds.get("composite_score", 0)
    prev_direction = prev_ds.get("direction", "neutral")
    prev_signal_level = prev_plan.get("signal_level", "")
    prev_phase = prev_cycle.get("current_phase", "")

    # 1. Score crosses 65 (bullish threshold) from below
    if prev_score < 65 and score >= 65:
        signals.append({
            "time": now,
            "type": "bullish_breakout",
            "message": f"黄金评分突破65看涨阈值！{prev_score:.0f} → {score:.0f}，"
                       f"方向 {direction}，信号等级 {signal_level}。"
                       f"金价 ${gold_price:,.0f}。建议关注加仓机会。",
            "score": score,
            "direction": direction,
            "signal_level": signal_level,
            "gold_price": gold_price,
        })

    # 2. Score crosses 45 (bearish threshold) from above
    if prev_score >= 45 and score < 45:
        signals.append({
            "time": now,
            "type": "bearish_breakdown",
            "message": f"黄金评分跌破45看跌阈值！{prev_score:.0f} → {score:.0f}，"
                       f"方向 {direction}。建议减仓防守。",
            "score": score,
            "direction": direction,
            "signal_level": signal_level,
            "gold_price": gold_price,
        })

    # 3. Direction changes
    if prev_direction != direction:
        signals.append({
            "time": now,
            "type": "direction_change",
            "message": f"黄金方向变化：{prev_direction} → {direction}。"
                       f"评分 {score:.0f}/100，金价 ${gold_price:,.0f}。",
            "score": score,
            "direction": direction,
            "signal_level": signal_level,
            "gold_price": gold_price,
        })

    # 4. Signal level changes
    if prev_signal_level != signal_level and signal_level:
        signals.append({
            "time": now,
            "type": "signal_level_change",
            "message": f"黄金信号等级变化：{prev_signal_level} → {signal_level}。"
                       f"评分 {score:.0f}/100。",
            "score": score,
            "direction": direction,
            "signal_level": signal_level,
            "gold_price": gold_price,
        })

    # 5. Cycle phase changes
    if prev_phase and prev_phase != phase:
        signals.append({
            "time": now,
            "type": "cycle_change",
            "message": f"黄金周期变化：{prev_phase} → {phase}。"
                       f"评分 {score:.0f}/100。",
            "score": score,
            "direction": direction,
            "signal_level": signal_level,
            "gold_price": gold_price,
        })

    # 6. Score significant move (>10 points)
    if abs(score - prev_score) >= 10:
        direction_text = "上升" if score > prev_score else "下降"
        signals.append({
            "time": now,
            "type": "score_jump",
            "message": f"黄金评分显著{direction_text}：{prev_score:.0f} → {score:.0f}"
                       f"（变化{score - prev_score:+.1f}）。金价 ${gold_price:,.0f}。",
            "score": score,
            "direction": direction,
            "signal_level": signal_level,
            "gold_price": gold_price,
        })

    return signals


def write_signals(signals: list[dict]):
    """Write signals to individual JSON files in gold_signals/ directory."""
    if not signals:
        return

    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    for sig in signals:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sig_type = sig.get("type", "unknown")
        filename = SIGNAL_DIR / f"gold_signal_{ts}_{sig_type}.json"
        filename.write_text(
            json.dumps(sig, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Gold Monitor")
    parser.add_argument("--time", type=str, default=None,
                        help="Time slot HHMM (for logging)")
    args = parser.parse_args()

    time_label = args.time or datetime.now().strftime("%H%M")
    print(f"[Gold Monitor {time_label}] Starting at {datetime.now().isoformat()}")

    # Step 1: Run gold engine
    print("[Gold Monitor] Running gold_engine pipeline...")
    try:
        report = run_gold_engine()
    except Exception as e:
        print(f"[Gold Monitor] ERROR: gold_engine failed: {e}")
        return 1

    ds = report.get("drive_score", {})
    score = ds.get("composite_score", 0)
    direction = ds.get("direction", "neutral")
    gold_price = report.get("gold_price", 0)

    print(f"[Gold Monitor] Score: {score:.1f}, Direction: {direction}, Gold: ${gold_price:,.0f}")

    # Step 2: Compare with previous state
    previous = load_previous_state()
    signals = detect_signals(report, previous)

    # Step 3: Write signals
    if signals:
        print(f"[Gold Monitor] {len(signals)} signal(s) detected:")
        for sig in signals:
            print(f"  [{sig['type']}] {sig['message']}")
        write_signals(signals)
    else:
        print("[Gold Monitor] No significant changes detected.")

    # Step 4: Save current state
    save_state(report)
    print(f"[Gold Monitor] State saved. Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
