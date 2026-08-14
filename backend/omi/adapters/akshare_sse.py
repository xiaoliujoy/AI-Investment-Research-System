"""上交所 ETF 期权适配器（中证500 等，标的如 510500）。

数据源（akshare）：
- option_current_day_sse()            当日全部 SSE 合约清单（含标的/类型/行权价/到期日）
- option_sse_daily_sina(code)         单合约日线（最新收盘 + 成交量）
- option_sse_greeks_sina(code)        单合约 Greeks（隐含波动率/Delta/最新价，参考校验）
- option_daily_stats_sse(date)        标的层面成交量/持仓（认购/认沽 + 认沽认购比）-> OI 层主来源

说明：
- 逐合约取价+IV 参考，OTI 用标的层面聚合（SSE 不提供逐合约 OI 的稳定接口）。
- underlying 价/涨跌用 fund_etf_spot_em 兜底；失败时留 None。
- 所有接口逐合约 try/except，单点失败不影响整链。
"""

from __future__ import annotations

from typing import Optional

import akshare as ak

from ..chain_model import RawOptionChain, RawOptionContract
from ..watchlist import OmiUnderlying
from .base import OptionChainProvider


class AkShareSSEProvider(OptionChainProvider):
    def fetch(self, underlying: OmiUnderlying, trade_date: str) -> RawOptionChain:
        sym = underlying.underlying_symbol  # e.g. '510500'
        chain = RawOptionChain(
            omi_id=underlying.omi_id, trade_date=trade_date, source="akshare_sse"
        )

        # 标的价/涨跌
        chain.underlying_price, chain.underlying_change_pct = self._underlying_spot(sym)

        # 标的层面 OI / Volume（SSE daily_stats）
        self._fill_underlying_stats(chain, trade_date, sym)

        # 合约清单
        try:
            uni = ak.option_current_day_sse()
        except Exception as e:
            chain.source = f"akshare_sse:ERR_universe:{e}"
            return chain
        mask = uni["标的券名称及代码"].astype(str).str.contains(str(sym))
        sub = uni[mask]
        for _, row in sub.iterrows():
            code = str(row["合约编码"])
            otype = "CALL" if str(row["类型"]) == "认购" else "PUT"
            strike = self._to_float(row["行权价"])
            expiry = str(row["到期日"])
            last, vol, ivr, delta = self._contract_fields(code)
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
                    iv_reported=ivr,
                    delta=delta,
                    underlying_price=chain.underlying_price,
                    source="akshare_sse",
                )
            )
        return chain

    def _contract_fields(self, code: str):
        last = vol = ivr = delta = None
        try:
            d = ak.option_sse_daily_sina(symbol=code)
            if d is not None and not d.empty:
                last = self._to_float(d["收盘"].iloc[-1])
                vol = self._to_float(d["成交量"].iloc[-1])
        except Exception:
            pass
        try:
            g = ak.option_sse_greeks_sina(symbol=code)
            if g is not None and not g.empty and "字段" in g.columns:
                gmap = dict(zip(g["字段"], g["值"]))
                ivr = self._to_float(gmap.get("隐含波动率"))
                delta = self._to_float(gmap.get("Delta"))
        except Exception:
            pass
        return last, vol, ivr, delta

    def _fill_underlying_stats(self, chain: RawOptionChain, trade_date: str, sym: str):
        try:
            stats = ak.option_daily_stats_sse(date=trade_date)
            if stats is None or stats.empty:
                return
            row = stats[stats["合约标的代码"].astype(str) == str(sym)]
            if row.empty:
                return
            r = row.iloc[0]
            chain.underlying_call_volume = self._to_float(r["认购成交量"])
            chain.underlying_put_volume = self._to_float(r["认沽成交量"])
            chain.underlying_call_oi = self._to_float(r["未平仓认购合约数"])
            chain.underlying_put_oi = self._to_float(r["未平仓认沽合约数"])
            chain.underlying_put_call_oi_ratio = self._to_float(r["认沽/认购"])
        except Exception:
            pass

    def _underlying_spot(self, sym: str):
        # 注：本沙箱东财(fund_etf_spot_em)被代理阻断，部分新浪行情接口对近期日期失效。
        # 标的价改由 indicators 层用看涨-看跌平价从期权链反推（更稳健、零外部依赖）。
        # 此处保留扩展位：若未来有稳定行情源可在此补充。
        return None, None
