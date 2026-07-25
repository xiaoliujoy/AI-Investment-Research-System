#!/usr/bin/env python3
"""L2: Market Narrative Detection.

Determines what narrative the market is trading gold on today.
Five possible themes: inflation, risk-off, rate-cut expectations,
dollar credibility, geopolitics.

Logic: Reads L1 factor scores → maps factor directions to narrative themes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List

from ..scoring.drive_scorer import DriveScore, FactorResult


@dataclass
class GoldNarrative:
    """Market narrative detection result."""
    timestamp: str
    primary_theme: str          # main narrative: "通胀" / "避险" / "降息预期" / "美元信用" / "地缘"
    themes: dict = field(default_factory=dict)  # {theme_name: strength_0_to_100}
    narrative_text: str = ""
    confidence: float = 0.0


# Narrative theme definitions
THEMES = {
    "通胀对冲": {
        "keywords": ["通胀预期(BE)", "原油WTI", "实际利率(TIPS)"],
        "description": "市场在交易通胀风险，黄金作为通胀对冲资产受追捧",
        "bull_condition": "实际利率下降 + 通胀预期上升 + 油价上涨",
        "bear_condition": "实际利率上升 + 通胀预期下降",
    },
    "避险需求": {
        "keywords": ["地缘政治风险", "GLD ETF"],
        "description": "风险事件驱动避险资金流入黄金",
        "bull_condition": "地缘风险升高 + GLD ETF放量流入",
        "bear_condition": "地缘风险回落 + 风险偏好回升",
    },
    "降息预期": {
        "keywords": ["美联储利率", "实际利率(TIPS)"],
        "description": "市场定价美联储降息，持有黄金的机会成本降低",
        "bull_condition": "美联储暂停/降息 + 实际利率下降",
        "bear_condition": "美联储加息预期升温",
    },
    "美元信用": {
        "keywords": ["美元指数DXY", "央行购金"],
        "description": "美元信用体系弱化，央行持续增持黄金替代美元储备",
        "bull_condition": "美元走弱 + 央行持续大量购金",
        "bear_condition": "美元强势 + 央行购金放缓",
    },
    "地缘冲突": {
        "keywords": ["地缘政治风险", "原油WTI"],
        "description": "地缘冲突推升避险+通胀双重逻辑",
        "bull_condition": "地缘风险极高(≥7) + 油价联动上涨",
        "bear_condition": "地缘局势缓和",
    },
}


def _calc_theme_strength(theme_name: str, theme_def: dict, factors: list[FactorResult]) -> float:
    """Calculate how strongly a theme is present based on factor scores.
    
    Returns 0-100 strength score.
    """
    keyword_scores = []
    for kw in theme_def["keywords"]:
        for f in factors:
            if f.name == kw:
                # Map factor direction to theme contribution
                if "bull" in f.direction:
                    keyword_scores.append(f.score)
                elif "bear" in f.direction:
                    keyword_scores.append(100 - f.score)
                else:
                    keyword_scores.append(50)
                break
    
    if not keyword_scores:
        return 50
    
    return sum(keyword_scores) / len(keyword_scores)


def detect_narrative(ds: DriveScore) -> GoldNarrative:
    """Detect dominant market narrative from factor scores.
    
    Maps L1 factor scores to 5 possible themes,
    picks the strongest as primary, and writes a narrative paragraph.
    """
    theme_strengths = {}
    for name, definition in THEMES.items():
        strength = _calc_theme_strength(name, definition, ds.factors)
        theme_strengths[name] = round(strength, 1)
    
    # Sort by strength
    sorted_themes = sorted(theme_strengths.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_themes[0][0]
    primary_strength = sorted_themes[0][1]
    
    # If top 2 are close (<10 apart), it's a multi-theme day
    if len(sorted_themes) >= 2:
        second_strength = sorted_themes[1][1]
        if primary_strength - second_strength < 10:
            primary = f"{primary} + {sorted_themes[1][0]}"
    
    # Build narrative text
    lines = [
        f"今日黄金交易主题：{primary}",
        "",
        f"综合驱动评分：{ds.composite_score:.0f}/100 ({ds.direction})",
    ]
    
    # Explain dominant theme
    if "通胀" in primary:
        lines.append(f"市场定价通胀风险。{THEMES['通胀对冲']['description']}")
    elif "避险" in primary and "地缘" not in primary:
        lines.append(f"风险情绪主导。{THEMES['避险需求']['description']}")
    elif "降息" in primary:
        lines.append(f"利率预期驱动。{THEMES['降息预期']['description']}")
    elif "美元信用" in primary:
        lines.append(f"美元体系重构。{THEMES['美元信用']['description']}")
    elif "地缘" in primary:
        lines.append(f"地缘冲击双重逻辑。{THEMES['地缘冲突']['description']}")
    
    # Theme checklist
    lines.append("")
    lines.append("主题强度：")
    for theme, strength in sorted_themes:
        marker = "☑" if strength >= 60 else ("☐" if strength < 45 else "◐")
        lines.append(f"  {marker} {theme}: {strength:.0f}/100")
    
    # History note
    if primary_strength < 50:
        lines.append("")
        lines.append("⚠️ 当前主题信号较弱，市场可能在等待新的催化剂。各因子方向不一致，建议观望。")
    
    # Confidence
    confidence = min(primary_strength, ds.confidence) if ds.confidence > 0 else primary_strength
    
    return GoldNarrative(
        timestamp=ds.timestamp,
        primary_theme=primary,
        themes=theme_strengths,
        narrative_text="\n".join(lines),
        confidence=round(confidence, 1),
    )
