"""OMI 数据适配器基类。

每个适配器把某个数据源/某类标的的原始接口归一化为 RawOptionChain。
核心约束：适配器只负责"取原始数据"，不做 IV/Rank 等计算（计算在 indicators 层）。
这样换数据源只需新增/修改适配器，下游指标与存储完全不动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..chain_model import RawOptionChain
from ..watchlist import OmiUnderlying


class OptionChainProvider(ABC):
    @abstractmethod
    def fetch(self, underlying: OmiUnderlying, trade_date: str) -> RawOptionChain:
        """抓取指定标的在 trade_date 的原始期权链。

        实现应逐合约/逐接口容错：单个合约或接口失败不应中断整条链。
        取不到的字段留 None，绝不编造。
        """
        raise NotImplementedError

    @staticmethod
    def _to_float(v) -> Optional[float]:
        try:
            if v is None or v == "" or (isinstance(v, str) and v.strip() in ("-", "--", "None")):
                return None
            return float(str(v).replace(",", "").replace("%", ""))
        except Exception:
            return None
