# -*- coding: utf-8 -*-
"""Institution flow data adapter - 机构资金监测.

Tracks:
  1. HSGT (沪深港通) - southbound capital flow
  2. National Team ETFs - track 510300/510310/510500 shares change
  3. Summary for Flow Intelligence

Data source: akshare stock_hsgt_fund_flow_summary_em()
"""
from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)

for _k in list(os.environ.keys()):
    if "proxy" in _k.lower():
        del os.environ[_k]
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

_CACHE = {"data": None, "ts": 0}
_CACHE_TTL = 300

# National team ETF codes (中央汇金/中国诚通/中国国新 主要持仓)
NATIONAL_TEAM_ETF = {
    "510300": "沪深300ETF华泰柏瑞",
    "510310": "沪深300ETF易方达",
    "510500": "中证500ETF南方",
    "510050": "上证50ETF华夏",
    "159919": "沪深300ETF嘉实",
    "510330": "沪深300ETF行业",
}


@dataclass
class HSGTFlow:
    """HSGT (沪深港通) capital flow."""
    north_net: float = 0.0      # 北向净流入(亿元)
    south_net: float = 0.0      # 南向净流入(亿元)
    north_status: str = ""      # 交易状态
    south_status: str = ""
    detail: list = field(default_factory=list)


@dataclass
class NationalTeamFlow:
    """National team ETF shares change."""
    etf_code: str = ""
    etf_name: str = ""
    shares_change: float = 0.0  # 份额变化
    action: str = ""            # 增持/减持/持平


@dataclass
class InstitutionFlow:
    """Complete institution flow snapshot."""
    timestamp: str = ""
    hsgt: HSGTFlow = field(default_factory=HSGTFlow)
    national_team: List[NationalTeamFlow] = field(default_factory=list)
    south_direction: str = ""   # southbound flow direction summary
    gaps: list = field(default_factory=list)


def get_institution_flow(etf_snap=None) -> InstitutionFlow:
    """Fetch institution capital flow data.
    
    Args:
        etf_snap: ETFFlowSnapshot from etf_data (for national team ETF tracking)
    """
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["data"]

    flow = InstitutionFlow(timestamp=datetime.now().isoformat())
    gaps = []

    # 1. HSGT fund flow summary
    try:
        import akshare as ak
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is not None and len(df) > 0:
            hsgt = HSGTFlow()
            for _, row in df.iterrows():
                direction = str(row.get("资金方向", ""))
                net = float(row.get("成交净买额", 0) or 0)
                status = str(row.get("交易状态", ""))
                detail_item = {
                    "type": str(row.get("类型", "")),
                    "board": str(row.get("板块", "")),
                    "direction": direction,
                    "net": net,
                    "status": status,
                }
                hsgt.detail.append(detail_item)
                if "北向" in direction:
                    hsgt.north_net += net
                    hsgt.north_status = status
                elif "南向" in direction:
                    hsgt.south_net += net
                    hsgt.south_status = status
            flow.hsgt = hsgt
            # South direction summary
            if hsgt.south_net > 50:
                flow.south_direction = "南向资金大幅净流入(%.0f亿)" % hsgt.south_net
            elif hsgt.south_net > 10:
                flow.south_direction = "南向资金小幅净流入(%.0f亿)" % hsgt.south_net
            elif hsgt.south_net < -10:
                flow.south_direction = "南向资金净流出(%.0f亿)" % hsgt.south_net
            else:
                flow.south_direction = "南向资金中性(%.0f亿)" % hsgt.south_net
        else:
            gaps.append("hsgt_empty")
    except Exception as e:
        logger.warning("HSGT fund flow failed: %s", e)
        gaps.append("hsgt_error")

    # 2. National team ETF tracking (from ETF snapshot)
    if etf_snap:
        all_etfs = (etf_snap.broad + etf_snap.industry + etf_snap.theme +
                    etf_snap.gold + etf_snap.overseas + etf_snap.other)
        for code, name in NATIONAL_TEAM_ETF.items():
            etf = next((e for e in all_etfs if e.code == code), None)
            if etf and etf.shares_change != 0:
                action = "增持" if etf.shares_change > 0 else "减持"
                flow.national_team.append(NationalTeamFlow(
                    etf_code=code,
                    etf_name=name,
                    shares_change=etf.shares_change,
                    action=action,
                ))

    flow.gaps = gaps
    _CACHE["data"] = flow
    _CACHE["ts"] = now
    return flow
