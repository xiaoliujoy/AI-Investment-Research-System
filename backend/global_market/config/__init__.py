"""配置加载器。"""

from __future__ import annotations

import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent


def load_symbols() -> dict:
    """加载标的配置。"""
    path = CONFIG_DIR / "symbols.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_scoring_config() -> dict:
    """加载评分配置。"""
    path = CONFIG_DIR / "scoring_config.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_theme_mapping() -> dict:
    """加载产业链映射配置。"""
    path = CONFIG_DIR / "theme_mapping.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
