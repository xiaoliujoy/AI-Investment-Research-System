#!/usr/bin/env python3
"""L6: Gold Risk Radar.

Weekly catalyst calendar with importance weights.
Scans upcoming events that could impact gold:
  FOMC meetings, CPI, NFP, Treasury auctions, geopolitical events.

Events are scored by star rating (★1-5) based on historical gold volatility impact.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List


@dataclass
class RiskEvent:
    """A single risk/catalyst event."""
    name: str
    date: str
    stars: int             # ★1-5
    impact_direction: str  # "双向" / "看涨风险" / "看跌风险"
    note: str = ""


@dataclass
class RiskRadar:
    """Weekly risk radar for gold."""
    timestamp: str
    current_week_events: List[RiskEvent] = field(default_factory=list)
    next_week_events: List[RiskEvent] = field(default_factory=list)
    highest_risk: str = ""     # most important event this week
    summary: str = ""


# Known catalyst calendar for gold
# In production, this should be fetched from economic calendar API
def _get_gold_catalyst_calendar(today: datetime) -> tuple[List[RiskEvent], List[RiskEvent]]:
    """Build gold-specific catalyst calendar.
    
    Uses known schedule for regular events + date rules for others.
    """
    current_week = []
    next_week = []
    
    # Determine which days this week
    weekday = today.weekday()  # 0=Mon
    week_start = today - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)
    next_week_start = week_end + timedelta(days=1)
    next_week_end = next_week_start + timedelta(days=6)
    
    # Define recurring events with approximate dates
    # These should be updated with actual dates in production
    all_events = [
        # FOMC meetings (roughly every 6 weeks)
        RiskEvent("FOMC利率决议", "2026-07-29", 5, "双向", "影响美元/实际利率预期"),
        RiskEvent("FOMC会议纪要", "2026-08-19", 4, "双向", "揭示美联储内部分歧"),
        
        # Inflation data
        RiskEvent("美国CPI", "2026-08-12", 5, "双向", "通胀超预期→压制黄金，低于预期→利好"),
        RiskEvent("美国PCE物价指数", "2026-08-28", 5, "双向", "美联储首选通胀指标"),
        
        # Employment
        RiskEvent("美国非农就业", "2026-08-07", 4, "双向", "就业强劲→加息预期→利空黄金"),
        
        # GDP
        RiskEvent("美国GDP", "2026-07-30", 3, "双向", "影响增长预期"),
        
        # Treasury data
        RiskEvent("美债拍卖(10Y)", "2026-08-12", 3, "双向", "拍卖收益率影响市场利率定价"),
        RiskEvent("美债拍卖(30Y)", "2026-08-13", 3, "双向"),
        
        # Dollar related
        RiskEvent("美元指数周度持仓报告", "每周五", 2, "双向", "CFTC持仓反映投机情绪"),
        
        # Geopolitical (approximate)
        RiskEvent("中东局势跟踪", "持续", 4, "看涨风险", "伊朗-以色列冲突可能升级"),
        
        # Central bank buying
        RiskEvent("WGC季度央行购金报告", "2026-08-01", 4, "看涨风险", "揭示央行购金趋势"),
        
        # Gold specific
        RiskEvent("COMEX黄金期权到期", "每月第三个周五", 2, "双向", "期权到期可能带来短期波动"),
    ]
    
    for event in all_events:
        event_date_str = event.date
        
        # Parse date
        if "每周" in event_date_str or "每月" in event_date_str:
            # Recurring events - always add to current week
            current_week.append(event)
            continue
        if event_date_str == "持续":
            current_week.append(event)
            continue
        
        try:
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d")
        except ValueError:
            continue
        
        if week_start <= event_date <= week_end:
            current_week.append(event)
        elif next_week_start <= event_date <= next_week_end:
            next_week.append(event)
    
    # Sort by stars descending
    current_week.sort(key=lambda e: e.stars, reverse=True)
    next_week.sort(key=lambda e: e.stars, reverse=True)
    
    return current_week, next_week


def scan_risks(timestamp: str = None) -> RiskRadar:
    """Scan upcoming gold risk events for this week and next."""
    if timestamp:
        try:
            today = datetime.strptime(timestamp[:10], "%Y-%m-%d")
        except ValueError:
            today = datetime.now()
    else:
        today = datetime.now()
    
    current_week, next_week = _get_gold_catalyst_calendar(today)
    
    # Determine highest risk
    if current_week:
        highest = current_week[0]
        if highest.stars >= 5:
            highest_risk = f"★★★★★ {highest.name}: {highest.note}"
        elif highest.stars >= 4:
            highest_risk = f"★★★★☆ {highest.name}: {highest.note}"
        else:
            highest_risk = f"本周无重大风险事件，关注{highest.name}"
    else:
        highest_risk = "本周无重大催化剂，市场可能以技术面驱动为主"
    
    # Summary
    high_risk_events = [e for e in current_week if e.stars >= 4]
    if high_risk_events:
        names = ", ".join(e.name for e in high_risk_events[:3])
        summary = f"本周重点关注: {names}"
    else:
        summary = "本周无高风险事件，关注技术面信号"
    
    return RiskRadar(
        timestamp=today.strftime("%Y-%m-%d"),
        current_week_events=current_week,
        next_week_events=next_week,
        highest_risk=highest_risk,
        summary=summary,
    )
