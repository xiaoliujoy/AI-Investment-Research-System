#!/usr/bin/env python3
"""L3: Gold Cycle State Machine.

Detects which phase of the gold cycle we're in:
  Accumulation → Fermentation → Main Rise → Euphoria → Correction → Bear

Uses multi-factor conditions to determine state transitions.
States persist across days (must meet transition conditions to change).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
from datetime import datetime

from ..scoring.drive_scorer import DriveScore
from ..data_adapter.gold_data import GoldFactors


@dataclass
class GoldCycle:
    """Gold cycle state machine result."""
    timestamp: str
    current_phase: str          # accumulation/fermentation/main_rise/euphoria/correction/bear
    phase_name_cn: str          # Chinese display name
    suggested_action: str       # "开始配置" / "加仓" / "持有" / "减仓" / "等待" / "回避"
    confidence: float
    signals: list = field(default_factory=list)
    note: str = ""


# Phase definitions with conditions
PHASES = {
    "accumulation": {
        "name": "建仓期",
        "action": "开始配置",
        "conditions": "实际利率见顶 + ETF开始流入 + 价格低位盘整",
        "next": "fermentation",
    },
    "fermentation": {
        "name": "发酵期",
        "action": "加仓",
        "conditions": "降息预期升温 + 黄金突破平台 + ETF持续流入",
        "next": "main_rise",
    },
    "main_rise": {
        "name": "主升期",
        "action": "持有",
        "conditions": "ETF持续流入 + 趋势确立 + 主流媒体开始关注",
        "next": "euphoria",
    },
    "euphoria": {
        "name": "狂热期",
        "action": "减仓",
        "conditions": "黄金新闻刷屏 + 散户大量买入 + 价格加速上涨",
        "next": "correction",
    },
    "correction": {
        "name": "调整期",
        "action": "等待",
        "conditions": "短期超买回落 + 实际利率回升 + ETF流出",
        "next": "bear",
    },
    "bear": {
        "name": "熊市",
        "action": "回避",
        "conditions": "美元强 + 实际利率高 + ETF持续流出 + 趋势下行",
        "next": "accumulation",
    },
}

# Cache file for state persistence
STATE_FILE = Path(__file__).resolve().parent.parent.parent / "output" / ".gold_cache" / "gold_cycle_state.json"


def _load_previous_state() -> str:
    """Load previous cycle state from cache."""
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data.get("phase", "fermentation")  # default to fermentation
    except Exception:
        pass
    return "fermentation"


def _save_state(phase: str):
    """Save current cycle state to cache."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "phase": phase,
        "updated": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2))


def _determine_phase(ds: DriveScore, gf: GoldFactors, prev_phase: str) -> tuple[str, list[str], float]:
    """Determine current cycle phase based on factor signals.
    
    Returns (phase_id, [signal_descriptions], confidence).
    """
    composite = ds.composite_score
    signals = []
    
    # Extract key signals
    tips_f = next((f for f in ds.factors if "TIPS" in f.name), None)
    dxy_f = next((f for f in ds.factors if "DXY" in f.name), None)
    gld_f = next((f for f in ds.factors if "GLD" in f.name), None)
    fed_f = next((f for f in ds.factors if "美联储" in f.name), None)
    cb_f = next((f for f in ds.factors if "央行" in f.name), None)
    
    # Determine candidate phase from pure signal strength
    if composite >= 75:
        candidate = "main_rise"
        signals.append(f"综合评分{composite:.0f}，多头力量强劲")
    elif composite >= 65:
        candidate = "fermentation"
        signals.append(f"综合评分{composite:.0f}，偏多但未到主升")
    elif composite >= 55:
        candidate = "fermentation"
        signals.append(f"综合评分{composite:.0f}，温和看涨")
    elif composite >= 45:
        candidate = "correction"
        signals.append(f"综合评分{composite:.0f}，中性震荡")
    elif composite >= 35:
        candidate = "corrected"
        signals.append(f"综合评分{composite:.0f}，偏弱")
    else:
        candidate = "bear"
        signals.append(f"综合评分{composite:.0f}，空头主导")
    
    # ETF flow signal
    if gld_f and "bull" in gld_f.direction:
        signals.append(f"GLD ETF放量流入(${gf.gld_price:.0f}, {gf.gld_change_pct:+.1f}%)")
    elif gld_f and "bear" in gld_f.direction:
        signals.append(f"GLD ETF流出(${gf.gld_price:.0f}, {gf.gld_change_pct:+.1f}%)")
    
    # DXY signal
    if dxy_f and "bull" in dxy_f.direction:
        signals.append(f"DXY={gf.dxy:.2f}，美元走弱利好黄金")
    elif dxy_f and "bear" in dxy_f.direction:
        signals.append(f"DXY={gf.dxy:.2f}，美元走强压制黄金")
    
    # TIPS signal
    if tips_f and gf.tips_10y_yield:
        signals.append(f"实际利率={gf.tips_10y_yield:.2f}%")
    
    # CB buying
    if gf.central_bank_buying and gf.central_bank_buying > 30:
        signals.append(f"央行持续大量购金({gf.central_bank_buying:.0f}t/月)")
    
    # State transition: only move forward one step at a time
    # unless there's a clear reversal signal
    phase_order = ["accumulation", "fermentation", "main_rise", "euphoria", "correction", "bear"]
    try:
        prev_idx = phase_order.index(prev_phase)
    except ValueError:
        prev_idx = phase_order.index("fermentation")
    
    cand_idx = phase_order.index(candidate) if candidate in phase_order else prev_idx
    
    # Rules for transition
    if cand_idx == prev_idx:
        final = prev_phase
    elif cand_idx > prev_idx:
        # Forward: max 1 step unless euphoria signal
        if composite >= 80 and gld_f and "bull" in gld_f.direction:
            final = phase_order[min(cand_idx, prev_idx + 1)]
            if final != prev_phase:
                signals.append(f"相位前进：{PHASES[prev_phase]['name']} → {PHASES[final]['name']}")
        else:
            # Need strong signal to advance, otherwise stay
            if composite - 50 > 10 * (cand_idx - prev_idx):
                final = phase_order[min(cand_idx, prev_idx + 1)]
            else:
                final = prev_phase
    else:
        # Backward: require reversal signals
        if "bear" in ds.direction and composite < 40:
            final = phase_order[max(cand_idx, prev_idx - 1)]
            if final != prev_phase:
                signals.append(f"相位回退：{PHASES[prev_phase]['name']} → {PHASES[final]['name']}")
        else:
            final = prev_phase
    
    confidence = min(ds.confidence, 85)
    
    return final, signals, confidence


def detect_cycle(ds: DriveScore, gf: GoldFactors) -> GoldCycle:
    """Detect current gold cycle phase.
    
    Loads previous state, evaluates current conditions,
    applies transition rules, saves new state.
    """
    prev_phase = _load_previous_state()
    phase, signals, confidence = _determine_phase(ds, gf, prev_phase)
    
    _save_state(phase)
    
    phase_info = PHASES[phase]
    
    return GoldCycle(
        timestamp=ds.timestamp,
        current_phase=phase,
        phase_name_cn=phase_info["name"],
        suggested_action=phase_info["action"],
        confidence=round(confidence, 1),
        signals=signals,
        note=phase_info["conditions"],
    )
