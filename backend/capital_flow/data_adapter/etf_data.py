# -*- coding: utf-8 -*-
"""ETF fund flow data adapter - ETF资金流监测.

5-layer ETF monitoring:
  1. Broad-based: 300/500/1000/创业板/科创50
  2. Industry: 半导体/芯片/军工/医药/券商/银行/消费
  3. Theme: AI/算力/机器人/创新药/低空/国产替代
  4. Gold: 518880/518800
  5. Overseas: QQQ/SPY/SOXX (via thsdk) + Chinese-listed overseas ETFs

Core metric: shares change (net purchase/redemption) - 比东财资金流更可靠
Data source: akshare fund_etf_spot_em() + daily shares snapshot persistence
"""
from __future__ import annotations

import os
import json
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

for _k in list(os.environ.keys()):
    if "proxy" in _k.lower():
        del os.environ[_k]
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

_CACHE = {"data": None, "ts": 0}
_CACHE_TTL = 300

BACK = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BACK / "output" / ".flow_cache"

# ---- ETF Categorization Rules ----
# Keyword -> category mapping (checked in order, first match wins)
CATEGORY_RULES = [
    # Gold
    ("gold", ["黄金", "gold", "GLD", "IAU"]),
    # Overseas (Chinese-listed ETFs tracking foreign indices)
    ("overseas", ["标普", "纳斯达克", "纳指", "道琼斯", "日经", "德国", "法国",
                   "恒生", "恒生科技", "恒生互联网", "越南", "印度", "亚太",
                   "中概互联", "中美", "海外"]),
    # Broad-based
    ("broad", ["沪深300", "300ETF", "中证500", "500ETF", "中证1000", "1000ETF",
               "创业板", "科创50", "科创100", "上证50", "50ETF",
               "中证A500", "中证A50", "A500ETF", "深证100", "中证800",
               "双创50", "双创ETF", "MSCI"]),
    # Industry
    ("industry", ["半导体", "芯片", "集成电路", "军工", "国防", "航空航天",
                  "医药", "医疗", "生物", "创新药", "券商", "证券", "银行",
                  "金融", "消费", "食品饮料", "白酒", "新能源", "光伏",
                  "锂电", "碳中和", "房地产", "地产", "煤炭", "钢铁",
                  "有色", "稀土", "基建", "建材", "化工", "电力",
                  "交通", "汽车", "传媒", "游戏", "旅游", "农业",
                  "通信", "5G", "电子", "计算机", "软件", "信息技术",
                  "机械", "环保", "水务", "燃气", "家电", "轻工",
                  "纺服", "商贸", "交运", "钢铁", "石油"]),
    # Theme
    ("theme", ["人工智能", "AI", "算力", "机器人", "低空", "国产替代",
               "云计算", "大数据", "物联网", "元宇宙", "区块链",
               "氢能", "储能", "风电", "核电", "氢燃料",
               "ESG", "央企", "国企", "红利", "质量",
               "数字经济", "信创", "web3", "AIGC", "数据要素",
               "脑机", "合成生物", "固态电池"]),
]


def _categorize_etf(name: str, code: str) -> str:
    """Categorize ETF by name keywords."""
    name_lower = name.lower()
    for category, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw.lower() in name_lower:
                return category
    return "other"


# Key ETF codes to always track (user's specific list)
KEY_ETF_CODES = {
    # Broad
    "510300": "沪深300ETF华泰柏瑞", "510500": "中证500ETF南方",
    "512100": "中证1000ETF南方", "159915": "创业板ETF易方达",
    "588000": "科创50ETF华夏", "510050": "上证50ETF华夏",
    # Industry
    "512480": "半导体ETF国联安", "512760": "芯片ETF国泰",
    "512660": "军工ETF鹏华", "512010": "医药ETF易方达",
    "512000": "券商ETF华宝", "512800": "银行ETF华宝",
    "510150": "消费ETF招商", "515030": "新能源车ETF华夏",
    # Theme
    "515980": "人工智能ETF", "159819": "人工智能50ETF",
    "561980": "算力ETF", "159770": "机器人ETF",
    "515120": "创新药沪深港ETF", "159509": "纳指科技ETF",
    # Gold
    "518880": "黄金ETF华安", "518800": "黄金ETF国泰",
    # Overseas (Chinese-listed)
    "513100": "标普500ETF博时", "513400": "道琼斯ETF鹏华",
    "513130": "恒生科技指数ETF", "159920": "恒生科技ETF华泰柏瑞",
}


@dataclass
class ETFItem:
    """Single ETF data point."""
    code: str = ""
    name: str = ""
    category: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    volume: float = 0.0        # 成交量
    amount: float = 0.0        # 成交额
    shares: float = 0.0        # 最新份额
    shares_change: float = 0.0 # 份额变化(今日-昨日)
    shares_change_pct: float = 0.0
    main_inflow: float = 0.0   # 主力净流入(元)
    total_value: float = 0.0   # 总市值
    is_key: bool = False       # 是否为重点关注ETF


@dataclass
class ETFFlowSnapshot:
    """Complete ETF fund flow snapshot."""
    timestamp: str = ""
    trade_date: str = ""
    broad: List[ETFItem] = field(default_factory=list)
    industry: List[ETFItem] = field(default_factory=list)
    theme: List[ETFItem] = field(default_factory=list)
    gold: List[ETFItem] = field(default_factory=list)
    overseas: List[ETFItem] = field(default_factory=list)
    other: List[ETFItem] = field(default_factory=list)
    # Rankings
    top_inflow: List[ETFItem] = field(default_factory=list)   # 净申购TOP10
    top_outflow: List[ETFItem] = field(default_factory=list)  # 净赎回TOP10
    # Summary
    total_main_inflow: float = 0.0
    broad_flow_summary: str = ""
    gaps: list = field(default_factory=list)


def _save_shares_snapshot(snap: ETFFlowSnapshot):
    """Save today's ETF shares for tomorrow's comparison."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = snap.trade_date or datetime.now().strftime("%Y%m%d")
    filepath = CACHE_DIR / f"etf_shares_{today}.json"
    shares_data = {}
    all_etfs = snap.broad + snap.industry + snap.theme + snap.gold + snap.overseas + snap.other
    for etf in all_etfs:
        if etf.shares > 0:
            shares_data[etf.code] = {
                "name": etf.name,
                "shares": etf.shares,
                "price": etf.price,
            }
    filepath.write_text(json.dumps(shares_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved ETF shares snapshot: %d ETFs -> %s", len(shares_data), filepath.name)


def _load_prev_shares() -> Dict[str, float]:
    """Load the most recent previous day's ETF shares."""
    if not CACHE_DIR.exists():
        return {}
    files = sorted([f for f in CACHE_DIR.glob("etf_shares_*.json")], reverse=True)
    today = datetime.now().strftime("%Y%m%d")
    for f in files:
        date_str = f.stem.replace("etf_shares_", "")
        if date_str < today:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                return {code: v["shares"] for code, v in data.items()}
            except Exception:
                pass
    return {}


def get_etf_flow() -> ETFFlowSnapshot:
    """Fetch ETF fund flow data with caching."""
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["data"]

    snap = ETFFlowSnapshot(
        timestamp=datetime.now().isoformat(),
        trade_date=datetime.now().strftime("%Y%m%d"),
    )
    gaps = []

    try:
        import akshare as ak
        df = ak.fund_etf_spot_em()
        if df is None or len(df) == 0:
            gaps.append("etf_spot_empty")
            snap.gaps = gaps
            return snap

        # Load previous day's shares
        prev_shares = _load_prev_shares()
        if not prev_shares:
            gaps.append("no_prev_shares")

        all_items = []
        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            name = str(row.get("名称", ""))
            if not code or len(code) < 5:
                continue

            category = _categorize_etf(name, code)
            price = float(row.get("最新价", 0) or 0)
            change_pct = float(row.get("涨跌幅", 0) or 0)
            volume = float(row.get("成交量", 0) or 0)
            amount = float(row.get("成交额", 0) or 0)
            shares = float(row.get("最新份额", 0) or 0)
            _mi_raw = row.get("主力净流入-净额", 0)
            try:
                main_inflow = float(_mi_raw) if _mi_raw == _mi_raw else 0.0  # NaN guard
            except (TypeError, ValueError):
                main_inflow = 0.0
            total_value = float(row.get("总市值", 0) or 0)

            # Compute shares change
            shares_change = 0.0
            shares_change_pct = 0.0
            if code in prev_shares and shares > 0:
                prev = prev_shares[code]
                shares_change = shares - prev
                if prev > 0:
                    shares_change_pct = (shares_change / prev) * 100

            item = ETFItem(
                code=code,
                name=name,
                category=category,
                price=price,
                change_pct=round(change_pct, 2),
                volume=volume,
                amount=amount,
                shares=shares,
                shares_change=round(shares_change, 0),
                shares_change_pct=round(shares_change_pct, 2),
                main_inflow=main_inflow,
                total_value=total_value,
                is_key=code in KEY_ETF_CODES,
            )
            all_items.append(item)

            if category == "broad":
                snap.broad.append(item)
            elif category == "industry":
                snap.industry.append(item)
            elif category == "theme":
                snap.theme.append(item)
            elif category == "gold":
                snap.gold.append(item)
            elif category == "overseas":
                snap.overseas.append(item)
            else:
                snap.other.append(item)

        # Rankings: 优先用份额变化(净申购/净赎回)，首日无历史份额时回退到主力净流入
        has_share_history = bool(prev_shares)
        rank_key = (lambda x: x.shares_change) if has_share_history else (lambda x: x.main_inflow)
        liquid = [i for i in all_items if i.amount > 1e8]
        snap.top_inflow = sorted(liquid, key=rank_key, reverse=True)[:10]
        snap.top_outflow = sorted(liquid, key=rank_key)[:10]
        if not has_share_history:
            snap.gaps = list(set(snap.gaps + ["rank_by_main_inflow"]))

        # Summary
        snap.total_main_inflow = sum(i.main_inflow for i in all_items if i.main_inflow == i.main_inflow and i.main_inflow != 0)
        broad_flows = {i.name[:8]: i.shares_change for i in snap.broad if i.is_key and i.shares_change != 0}
        if broad_flows:
            parts = [f"{k}{'+' if v > 0 else ''}{v/1e8:.1f}亿份" for k, v in broad_flows.items()]
            snap.broad_flow_summary = " | ".join(parts)

        # Save today's snapshot
        _save_shares_snapshot(snap)

    except Exception as e:
        logger.error("ETF flow collection failed: %s", e)
        gaps.append(f"etf_error: {str(e)[:60]}")

    snap.gaps = gaps
    _CACHE["data"] = snap
    _CACHE["ts"] = now
    return snap
