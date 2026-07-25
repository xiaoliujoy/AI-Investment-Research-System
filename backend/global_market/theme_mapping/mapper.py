"""产业链映射模块。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

BEIJING = timezone(timedelta(hours=8))


def generate_theme_mapping_report() -> dict:
    """生成产业链映射报告。
    
    Returns:
        {
            "date": "2026-07-10",
            "themes": [...]
        }
    """
    from global_market.config import load_theme_mapping
    from global_market.indicators.technology_cycle import analyze_technology_cycle
    
    now = datetime.now(BEIJING)
    
    # 分析科技周期
    cycle_data = analyze_technology_cycle()
    
    return cycle_data


def save_theme_report(data: dict, output_path: Path):
    """保存产业链报告。"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
