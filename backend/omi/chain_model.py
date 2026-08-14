"""OMI 原始期权链数据模型（标准化、数据源无关）。

这是 OMI 的底层：Option Chain Data Layer。
所有适配器把各家接口归一化到 RawOptionContract / RawOptionChain，
后续指标计算只依赖这套标准化结构，与具体数据源解耦。

关键点（用户要求：原始数据与计算指标分离）：
- 原始字段原样保存：underlying_price / strike / option_type / last_price /
  volume / open_interest / iv_reported(数据源给的IV，仅作参考校验) / delta。
- IV 等衍生指标由 indicators 层基于这些原始字段"自己算"，不信任也不依赖 iv_reported。
- 这样换数据源或发现算法问题，可以基于原始数据重算全部历史。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawOptionContract:
    omi_id: str
    trade_date: str
    contract_code: str
    option_type: str          # 'CALL' | 'PUT'
    strike: float
    expiry: str               # 'YYYY-MM-DD'
    last_price: Optional[float] = None
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    iv_reported: Optional[float] = None      # 数据源直接给的 IV（参考/校验用，非主值）
    delta: Optional[float] = None
    underlying_price: Optional[float] = None
    source: str = ""


@dataclass
class RawOptionChain:
    omi_id: str
    trade_date: str
    source: str
    underlying_price: Optional[float] = None
    underlying_change_pct: Optional[float] = None
    contracts: list[RawOptionContract] = field(default_factory=list)
    # 标的层面的成交量/持仓（部分数据源在链接口之外单独提供，如 SSE daily_stats）。
    # 用于 OI 层：当逐合约 OI 不可得时，退化为标的层面聚合值。
    underlying_call_volume: Optional[float] = None
    underlying_put_volume: Optional[float] = None
    underlying_call_oi: Optional[float] = None
    underlying_put_oi: Optional[float] = None
    underlying_put_call_oi_ratio: Optional[float] = None
    fetched_at: float = field(default_factory=time.time)

    def add(self, c: RawOptionContract) -> None:
        self.contracts.append(c)
