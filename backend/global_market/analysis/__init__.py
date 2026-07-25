"""分析模块。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

BEIJING = timezone(timedelta(hours=8))


def generate_global_analysis() -> dict:
    """生成全球市场分析。"""
    now = datetime.now(BEIJING)
    date_str = now.strftime("%Y-%m-%d")
    
    output_dir = Path(__file__).parent.parent / "output"
    
    global_score = _load_json(output_dir / "global_score.json")
    rps = _load_json(output_dir / "global_rps.json")
    themes = _load_json(output_dir / "theme_mapping.json")
    divergence = _load_json(output_dir / "divergence.json")
    
    summary = _generate_summary(global_score, rps, themes, divergence)
    
    return {
        "date": date_str,
        "global_score": global_score,
        "rps": rps.get("rps", []) if rps else [],
        "themes": themes.get("themes", []) if themes else [],
        "divergence": divergence.get("divergences", []) if divergence else [],
        "summary": summary,
    }


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _generate_summary(score: dict, rps: dict, themes: dict, divergence: dict) -> str:
    parts = []
    
    if score:
        total = score.get("total_score", 0)
        stage = score.get("stage", "")
        parts.append(f"Global score {total:.0f} ({stage})")
    
    if rps and rps.get("rps"):
        top_rps = [r for r in rps["rps"] if r.get("global_rank", 999) <= 3]
        if top_rps:
            symbols = [r["symbol"] for r in top_rps]
            parts.append(f"Leaders: {', '.join(symbols)}")
    
    if themes and themes.get("themes"):
        hot_themes = [t for t in themes["themes"] if t.get("heat_score", 0) >= 60]
        if hot_themes:
            theme_names = [t["name"] for t in hot_themes[:3]]
            parts.append(f"Hot themes: {', '.join(theme_names)}")
    
    return "; ".join(parts) if parts else "No data"


def save_analysis(data: dict, output_path: Path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
