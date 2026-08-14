"""商品期权适配器（黄金 SHFE / 铜 SHFE / 原油 INE）。

数据源（akshare）：
- option_comm_symbol()                    产品码映射（黄金期权->au_o ...）
- option_comm_info(symbol='黄金期权')     当日全部合约：合约码(含行权价)、类型、现价、成交量
- 标的价：futures_main_sina('<sym>0')     商品期货主力（黄金 au0 / 铜 cu0 / 原油 sc0）

说明（v0.1 已知近似，需后续打磨）：
- 行权价从合约码解析（au2609C1000 -> 1000），现价即每克权利金，与标的(元/克)同单位，可直接 BS 算 IV。
- 到期日：从合约码 YYMM 取，近似为该月首个交易日（SHFE 期权到期规则近似）。后续可接精确到期表。
- 持仓量(OI)：comm_info 不含 OI，v0.1 商品 OI 留 null，Volume 层可用；OI 集中度暂不可得。
- 逐合约/接口容错，失败时留 null 不编造。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import akshare as ak

from ..chain_model import RawOptionChain, RawOptionContract
from ..watchlist import OmiUnderlying
from .base import OptionChainProvider

_PRODUCT_NAME = {"au": "黄金期权", "cu": "铜期权", "sc": "原油期权"}
_FUTURES_MAIN = {"au": "au0", "cu": "cu0", "sc": "sc0"}


class AkShareCommodityProvider(OptionChainProvider):
    def fetch(self, underlying: OmiUnderlying, trade_date: str) -> RawOptionChain:
        chain = RawOptionChain(
            omi_id=underlying.omi_id, trade_date=trade_date, source="akshare_commodity"
        )
        name = _PRODUCT_NAME.get(underlying.underlying_symbol)
        if not name:
            chain.source = f"akshare_commodity:ERR_no_product:{underlying.underlying_symbol}"
            return chain

        chain.underlying_price = self._futures_spot(underlying.underlying_symbol)

        try:
            df = ak.option_comm_info(symbol=name)
        except Exception as e:
            chain.source = f"akshare_commodity:ERR_info:{e}"
            return chain
        if df is None or df.empty:
            chain.source = "akshare_commodity:EMPTY_info"
            return chain

        for _, row in df.iterrows():
            code = self._parse_code(str(row.get("期权品种", "")))
            if not code:
                continue
            otype = "CALL" if str(row.get("类型")) == "看涨" else "PUT"
            strike = self._parse_strike(code)
            expiry = self._approx_expiry(code, trade_date)
            last = self._to_float(row.get("现价"))
            vol = self._to_float(row.get("成交量"))
            chain.add(
                RawOptionContract(
                    omi_id=underlying.omi_id,
                    trade_date=trade_date,
                    contract_code=code,
                    option_type=otype,
                    strike=strike,
                    expiry=expiry,
                    last_price=last,
                    volume=vol,
                    underlying_price=chain.underlying_price,
                    source="akshare_commodity",
                )
            )
        return chain

    @staticmethod
    def _parse_code(label: str) -> Optional[str]:
        m = re.search(r"\(([^)]+)\)", label)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _parse_strike(code: str) -> Optional[float]:
        # au2609C1000 -> 1000 ; au2609P560 -> 560
        m = re.search(r"[CP](\d+(?:\.\d+)?)", code)
        if m:
            return float(m.group(1))
        return None

    @staticmethod
    def _approx_expiry(code: str, trade_date: str) -> Optional[str]:
        # 取 YYMM，近似到期 = 该月首个交易日
        m = re.search(r"(\d{2})(\d{2})[CP]", code)
        if not m:
            return None
        yy = int(m.group(1)) + 2000
        mm = int(m.group(2))
        d = datetime(yy, mm, 1)
        while d.weekday() >= 5:  # 跳过周末，取首个交易日
            d += timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    def _futures_spot(self, sym: str) -> Optional[float]:
        try:
            df = ak.futures_main_sina(symbol=_FUTURES_MAIN.get(sym, f"{sym}0"))
            if df is not None and not df.empty:
                # 常见列：'现价' / 'last_price' / 'close'
                for col in ("现价", "last_price", "close", "最新价"):
                    if col in df.columns:
                        return self._to_float(df[col].iloc[0])
        except Exception:
            pass
        return None
