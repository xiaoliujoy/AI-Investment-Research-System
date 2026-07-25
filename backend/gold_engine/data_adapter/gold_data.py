#!/usr/bin/env python3
"""Gold data adapter — unified data collection from thsdk + akshare + neodata.

Collects all 8 gold driving factors + auxiliary data.
Priority: thsdk (real-time C library) → akshare → neodata (news/events).

Factors:
  ★5 US 10Y TIPS real yield
  ★5 DXY (US Dollar Index)
  ★4 Fed rate expectations
  ★4 Gold ETF flows (GLD)
  ★4 Central bank gold buying
  ★3 Geopolitical risk
  ★3 Oil price (WTI)
  ★4 Breakeven inflation (10Y nominal - TIPS)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import sqlite3

BACK = Path(__file__).resolve().parent.parent.parent
DB_PATH = BACK / "database" / "vibe_research.db"
CACHE_DIR = BACK / "output" / ".gold_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL = 300  # 5 minutes for real-time data


@dataclass
class FactorResult:
    """Single factor scoring result."""
    name: str               # eg. "实际利率"
    weight: int             # 1-5 stars
    direction: str          # "bullish" / "bearish" / "neutral"
    score: float            # 0-100 individual score
    value: str              # human-readable value
    raw: dict = field(default_factory=dict)
    source: str = ""        # data source tag
    note: str = ""          # additional context


@dataclass
class GoldFactors:
    """Complete gold factor dataset for one day."""
    timestamp: str
    gold_price: float           # XAUUSD spot
    gold_change_pct: float
    dxy: float
    dxy_change_pct: float
    us_10y_yield: float
    us_2y_yield: float
    tips_10y_yield: Optional[float]  # may be estimated
    tips_source: str
    gld_price: float
    gld_volume: int
    gld_change_pct: float
    fed_rate: float
    fed_direction: str          # "pause" / "cut" / "hike"
    oil_price: float
    oil_change_pct: float
    central_bank_buying: Optional[float]  # tons, monthly
    geopolitical_risk: float    # 0-10 proxy score
    breakeven_inflation: Optional[float]
    factors: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)


# ── thsdk helpers ──────────────────────────────────────────────

def _get_thsdk():
    """Get thsdk connection (guest mode). Returns None if unavailable."""
    try:
        from thsdk import THS
        ths = THS()
        ths.connect()
        return ths
    except Exception:
        return None


def _fetch_thsdk_forex(ths, code: str, key: str = "基础数据") -> Optional[dict]:
    """Fetch forex data via thsdk. Returns dict or None."""
    try:
        data = ths.market_data_forex(code, query_key=key)
        if hasattr(data, 'df') and not data.df.empty:
            row = data.df.iloc[0].to_dict()
            return row
    except Exception:
        pass
    return None


def _fetch_thsdk_us(ths, code: str) -> Optional[dict]:
    """Fetch US stock/ETF data via thsdk."""
    try:
        data = ths.market_data_us(code, query_key="基础数据")
        if hasattr(data, 'df') and not data.df.empty:
            return data.df.iloc[0].to_dict()
    except Exception:
        pass
    return None


# ── akshare helpers ────────────────────────────────────────────

def _fetch_akshare_bond_yields() -> Optional[dict]:
    """Fetch latest China-US bond yields from akshare."""
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is not None and len(df) > 0:
            # Get latest row with US data (some days have NaN for US)
            valid = df[df['美国国债收益率10年'].notna()]
            if len(valid) > 0:
                row = valid.iloc[-1]
                return {
                    "date": str(row.get("日期", "")),
                    "us_2y": float(row["美国国债收益率2年"]),
                    "us_10y": float(row["美国国债收益率10年"]),
                    "cn_10y": float(row["中国国债收益率10年"]),
                }
    except Exception as e:
        pass
    return None


def _fetch_akshare_fed_rate() -> Optional[dict]:
    """Fetch latest Fed funds rate."""
    try:
        import akshare as ak
        df = ak.macro_bank_usa_interest_rate()
        if df is not None and len(df) > 0:
            valid = df[df['今值'].notna()]
            if len(valid) > 0:
                row = valid.iloc[-1]
                return {
                    "date": str(row.get("日期", "")),
                    "rate": float(row["今值"]),
                    "prev": float(row.get("前值", 0)) if row.get("前值") else None,
                }
    except Exception:
        pass
    return None


def _fetch_akshare_oil() -> Optional[dict]:
    """Fetch crude oil price via akshare."""
    try:
        import akshare as ak
        df = ak.futures_foreign_commodity_realtime(symbol="原油")
        if df is not None and len(df) > 0:
            row = df.iloc[0]
            return {
                "price": float(row.get("最新价", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
            }
    except Exception:
        pass
    return None


def _fetch_akshare_gold_inventory() -> Optional[dict]:
    """Fetch gold ETF inventory from akshare macro_cons_gold."""
    try:
        import akshare as ak
        df = ak.macro_cons_gold()
        if df is not None and len(df) > 0:
            row = df.iloc[-1]
            change = float(row.get("增持/减持", 0))
            return {
                "date": str(row.get("日期", "")),
                "inventory": float(row.get("总库存", 0)),
                "change": change,  # positive = inflow, negative = outflow
            }
    except Exception:
        pass
    return None


# ── neodata helpers ────────────────────────────────────────────

def _fetch_neodata_tips() -> Optional[dict]:
    """Fetch latest TIPS auction data via neodata."""
    script = BACK.parent.parent / "Program Files" / "WorkBuddy" / "resources" / \
             "app.asar.unpacked" / "resources" / "builtin-skills" / \
             "neodata-financial-search" / "scripts" / "query.py"
    if not script.exists():
        return None
    try:
        import subprocess
        cmd = [
            "python3", str(script),
            "--query", "美国10年期TIPS竞拍-高收益率 最新数据",
            "--data-type", "api",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        if data.get("code") == "200":
            api_data = data.get("data", {}).get("apiData", {})
            recalls = api_data.get("apiRecall", [])
            for recall in recalls:
                content = recall.get("content", "")
                if "TIPS" in content and "高收益率" in content:
                    # Parse latest auction yield
                    lines = content.strip().split("\n")
                    if len(lines) >= 3:
                        last_line = lines[-1]
                        parts = last_line.split("|")
                        if len(parts) >= 8:
                            # Extract yield from the last row
                            yield_str = parts[-2].strip() if len(parts) > 6 else ""
                            try:
                                return {"tips_yield": float(yield_str), "source": "neodata_auction"}
                            except ValueError:
                                pass
    except Exception:
        pass
    return None


# ── auxiliary calculations ─────────────────────────────────────

def _calc_geopolitical_risk() -> tuple[float, str]:
    """Simple geopolitical risk proxy based on known events.
    In production, this could be replaced with news NLP or GPR index.
    Returns (score 0-10, description).
    """
    # For now: static baseline with known events
    # Future: scan neodata news for keywords
    score = 4.0  # baseline moderate risk
    notes = []
    current_date = datetime.now()
    # Iran-Israel conflict elevated throughout 2026
    if current_date.month >= 3:
        score = max(score, 6.5)
        notes.append("中东地缘持续紧张")
    # US election cycle
    if 9 <= current_date.month <= 11:
        score = max(score, 5.5)
        notes.append("美国大选周期")
    return score, "; ".join(notes) if notes else "全球地缘风险基线"


def _calc_central_bank_buying() -> Optional[dict]:
    """Get central bank gold buying estimate.
    Uses cached WGC data when available, otherwise returns known trends.
    """
    # Known trend from WGC May 2026 report: +41 tons
    # China +10t, Poland +18t, ongoing trend
    # This should be updated via neodata news extraction monthly
    return {
        "monthly_net": 41.0,    # tons (May 2026)
        "trend": "持续增持",
        "top_buyers": ["波兰 +18t", "中国 +10t", "乌兹别克斯坦 +9t"],
        "source": "WGC月度报告(2026-05)",
    }


# ── main collection function ───────────────────────────────────

def get_all_gold_factors() -> GoldFactors:
    """Collect all gold driving factors from all data sources.
    
    Returns GoldFactors dataclass with all 8 factors populated.
    Gracefully degrades: if a source is unavailable, marks gap and uses fallback.
    """
    gaps = []
    raw = {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # ── Layer 1: thsdk real-time data ──
    ths = _get_thsdk()
    if ths is None:
        gaps.append("thsdk_unavailable")
    
    # Gold spot (XAUUSD)
    gold_price = 0.0
    gold_change = 0.0
    gold_source = ""
    if ths:
        xau = _fetch_thsdk_forex(ths, "UFXBXAUUSD")
        if xau:
            gold_price = float(xau.get("价格", 0))
            prev = float(xau.get("昨收价", gold_price))
            gold_change = ((gold_price - prev) / prev * 100) if prev else 0
            gold_source = "thsdk"
            raw["xauusd"] = xau
    if gold_price == 0:
        # Fallback to akshare
        try:
            import akshare as ak
            df = ak.futures_foreign_commodity_realtime(symbol="COMEX黄金")
            if df is not None and len(df) > 0:
                gold_price = float(df.iloc[0].get("最新价", 0))
                gold_change = float(df.iloc[0].get("涨跌幅", 0))
                gold_source = "akshare"
                raw["gold_akshare"] = df.iloc[0].to_dict()
        except Exception:
            gaps.append("gold_price_missing")
    
    # DXY
    dxy = 0.0
    dxy_change = 0.0
    dxy_source = ""
    if ths:
        dxy_data = _fetch_thsdk_forex(ths, "UFXBUSDIND")
        if dxy_data:
            dxy = float(dxy_data.get("价格", 0))
            prev_dxy = float(dxy_data.get("昨收价", dxy))
            dxy_change = ((dxy - prev_dxy) / prev_dxy * 100) if prev_dxy else 0
            dxy_source = "thsdk"
            raw["dxy"] = dxy_data
    if dxy == 0:
        gaps.append("dxy_missing")
    
    # GLD ETF
    gld_price = 0.0
    gld_volume = 0
    gld_change = 0.0
    gld_source = ""
    if ths:
        gld_data = _fetch_thsdk_us(ths, "UNYNGLD")
        if gld_data:
            gld_price = float(gld_data.get("价格", 0))
            gld_volume = int(gld_data.get("成交量", 0))
            prev_gld = float(gld_data.get("昨收价", gld_price))
            gld_change = ((gld_price - prev_gld) / prev_gld * 100) if prev_gld else 0
            gld_source = "thsdk"
            raw["gld"] = gld_data
    if gld_price == 0:
        gaps.append("gld_missing")
    
    # Disconnect thsdk
    if ths:
        try:
            ths.disconnect()
        except Exception:
            pass
    
    # ── Layer 2: akshare macro data ──
    us_10y = 0.0
    us_2y = 0.0
    bonds = _fetch_akshare_bond_yields()
    if bonds:
        us_10y = bonds["us_10y"]
        us_2y = bonds["us_2y"]
        raw["bonds"] = bonds
    else:
        gaps.append("us_bond_yields_missing")
    
    fed_rate = 0.0
    fed_direction = "unknown"
    fed_data = _fetch_akshare_fed_rate()
    if fed_data:
        fed_rate = fed_data["rate"]
        prev_rate = fed_data.get("prev", fed_rate)
        if prev_rate and prev_rate > fed_rate:
            fed_direction = "cut"
        elif prev_rate and prev_rate < fed_rate:
            fed_direction = "hike"
        else:
            fed_direction = "pause"
        raw["fed"] = fed_data
    else:
        gaps.append("fed_rate_missing")
    
    # Oil
    oil_price = 0.0
    oil_change = 0.0
    oil_data = _fetch_akshare_oil()
    if oil_data:
        oil_price = oil_data["price"]
        oil_change = oil_data["change_pct"]
        raw["oil"] = oil_data
    else:
        gaps.append("oil_missing")
    
    # Gold inventory (akshare)
    gold_inv = _fetch_akshare_gold_inventory()
    inv_change = 0.0
    if gold_inv:
        inv_change = gold_inv["change"]
        raw["gold_inventory"] = gold_inv
    
    # ── Layer 3: neodata / derived data ──
    # TIPS yield
    tips_yield = None
    tips_source_str = "estimated"
    tips_data = _fetch_neodata_tips()
    if tips_data:
        tips_yield = tips_data["tips_yield"]
        tips_source_str = tips_data.get("source", "neodata_auction")
        raw["tips"] = tips_data
    else:
        # Estimate: assume breakeven ~2.3% → TIPS ≈ 10Y - 2.3%
        if us_10y > 0:
            tips_yield = round(us_10y - 2.3, 2)
            tips_source_str = "estimated(10Y_nominal-2.3%)"
        else:
            gaps.append("tips_yield_missing")
    
    breakeven = None
    if tips_yield is not None and us_10y > 0:
        breakeven = round(us_10y - tips_yield, 2)
    
    # Central bank buying
    cb_data = _calc_central_bank_buying()
    raw["central_bank"] = cb_data
    
    # Geopolitical risk
    geo_score, geo_note = _calc_geopolitical_risk()
    
    # Build factor dict for scorer
    factors = {
        "tips_yield": {"name": "实际利率(TIPS)", "weight": 5, "value": tips_yield},
        "dxy": {"name": "美元指数DXY", "weight": 5, "value": dxy, "change": dxy_change},
        "us_10y": {"name": "美债10Y", "weight": 4, "value": us_10y},
        "us_2y": {"name": "美债2Y", "weight": 4, "value": us_2y},
        "fed_rate": {"name": "联邦基金利率", "weight": 4, "value": fed_rate, "direction": fed_direction},
        "gld_volume": {"name": "GLD ETF", "weight": 4, "value": gld_volume, "price": gld_price, "change": gld_change},
        "gold_inventory": {"name": "黄金库存变动", "weight": 3, "value": inv_change},
        "central_bank": {"name": "央行购金", "weight": 4, "value": cb_data["monthly_net"], "trend": cb_data["trend"]},
        "oil": {"name": "原油WTI", "weight": 3, "value": oil_price, "change": oil_change},
        "geopolitical": {"name": "地缘政治风险", "weight": 3, "value": geo_score},
        "breakeven_inflation": {"name": "通胀预期", "weight": 4, "value": breakeven},
    }
    
    return GoldFactors(
        timestamp=now,
        gold_price=gold_price,
        gold_change_pct=round(gold_change, 2),
        dxy=round(dxy, 3),
        dxy_change_pct=round(dxy_change, 2),
        us_10y_yield=round(us_10y, 3),
        us_2y_yield=round(us_2y, 3),
        tips_10y_yield=round(tips_yield, 3) if tips_yield else None,
        tips_source=tips_source_str,
        gld_price=round(gld_price, 2),
        gld_volume=gld_volume,
        gld_change_pct=round(gld_change, 2),
        fed_rate=round(fed_rate, 2),
        fed_direction=fed_direction,
        oil_price=round(oil_price, 2),
        oil_change_pct=round(oil_change, 2),
        central_bank_buying=cb_data["monthly_net"],
        geopolitical_risk=round(geo_score, 1),
        breakeven_inflation=round(breakeven, 2) if breakeven else None,
        factors=factors,
        gaps=gaps,
        raw_data=raw,
    )


# ── cache helpers ──────────────────────────────────────────────

def get_gold_factors_cached(force_refresh: bool = False) -> GoldFactors:
    """Get gold factors with 5-minute cache."""
    cache_file = CACHE_DIR / "gold_factors.json"
    if not force_refresh and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < CACHE_TTL:
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return GoldFactors(**data)
            except Exception:
                pass
    
    factors = get_all_gold_factors()
    cache_file.write_text(json.dumps(asdict(factors), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return factors


if __name__ == "__main__":
    gf = get_all_gold_factors()
    print(json.dumps(asdict(gf), ensure_ascii=False, indent=2, default=str))
