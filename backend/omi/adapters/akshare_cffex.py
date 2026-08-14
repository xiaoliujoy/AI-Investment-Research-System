"""中金所指数期权适配器（沪深300 / 中证1000）。

数据源（akshare）：
- option_cffex_{product_key}_spot_sina()   整条链：行权价 + 看涨/看跌最新价 + 持仓量 + 涨跌（两侧齐全）
- option_cffex_{product_key}_list_sina()   活跃月份合约码（如 io2608），用于解析到期月
- 标的价格/涨跌：stock_zh_index_spot_sina() 按指数代码（沪深300=sh000300, 中证1000=sh000852）

注意：
- spot_sina 的"标识"列可能显示旧标签（如 io2204），但价格/持仓为当前值；本适配器忽略标识列，
  到期日从 list_sina 的活跃月份码解析（取最近月份，按中金所规则取当月第4个周三）。
- 逐行容错；取不到的字段留 None。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import akshare as ak

from ..chain_model import RawOptionChain, RawOptionContract
from ..watchlist import OmiUnderlying
from .base import OptionChainProvider

_INDEX_CODE = {"hs300": "sh000300", "zz1000": "sh000852"}


class AkShareCFFEXProvider(OptionChainProvider):
    def fetch(self, underlying: OmiUnderlying, trade_date: str) -> RawOptionChain:
        chain = RawOptionChain(
            omi_id=underlying.omi_id, trade_date=trade_date, source="akshare_cffex"
        )
        pk = underlying.product_key
        func_spot = getattr(ak, f"option_cffex_{pk}_spot_sina", None)
        func_list = getattr(ak, f"option_cffex_{pk}_list_sina", None)
        if func_spot is None:
            chain.source = f"akshare_cffex:ERR_no_func:{pk}"
            return chain

        # 标的价格/涨跌
        chain.underlying_price, chain.underlying_change_pct = self._index_spot(pk)

        # 到期月（取最近活跃月份解析为日期）
        expiry = self._nearest_expiry(func_list) if func_list else None

        try:
            df = func_spot()
        except Exception as e:
            chain.source = f"akshare_cffex:ERR_spot:{e}"
            return chain
        if df is None or df.empty:
            chain.source = "akshare_cffex:EMPTY_spot"
            return chain

        # 陈旧数据守卫：spot_sina 在本环境可能冻结在旧月份（如 io2204=2022），
        # 而 list_sina 返回的是当前活跃月份（如 io2608=2026）。若两者月份不交，
        # 说明 spot 数据是陈旧的，绝不能把旧 IV 当成今日观测写入。
        if self._is_stale(df, func_list):
            chain.source = "akshare_cffex:STALE_DATA"
            return chain

        for _, row in df.iterrows():
            strike = self._to_float(row.get("行权价"))
            if strike is None:
                continue
            exp = expiry or (str(row.get("到期日")) if row.get("到期日") else None)
            # Call
            chain.add(
                RawOptionContract(
                    omi_id=underlying.omi_id,
                    trade_date=trade_date,
                    contract_code=str(row.get("看涨合约-标识", "")),
                    option_type="CALL",
                    strike=strike,
                    expiry=exp,
                    last_price=self._to_float(row.get("看涨合约-最新价")),
                    volume=self._to_float(row.get("看涨合约-买量")),  # 买量近似成交活跃度
                    open_interest=self._to_float(row.get("看涨合约-持仓量")),
                    underlying_price=chain.underlying_price,
                    source="akshare_cffex",
                )
            )
            # Put
            chain.add(
                RawOptionContract(
                    omi_id=underlying.omi_id,
                    trade_date=trade_date,
                    contract_code=str(row.get("看跌合约-标识", "")),
                    option_type="PUT",
                    strike=strike,
                    expiry=exp,
                    last_price=self._to_float(row.get("看跌合约-最新价")),
                    volume=self._to_float(row.get("看跌合约-买量")),
                    open_interest=self._to_float(row.get("看跌合约-持仓量")),
                    underlying_price=chain.underlying_price,
                    source="akshare_cffex",
                )
            )
        return chain

    def _index_spot(self, pk: str):
        code = _INDEX_CODE.get(pk)
        if not code:
            return None, None
        try:
            df = ak.stock_zh_index_spot_sina()
            if df is not None and not df.empty:
                r = df[df["代码"].astype(str) == code]
                if not r.empty:
                    rr = r.iloc[0]
                    return self._to_float(rr.get("最新价")), self._to_float(rr.get("涨跌幅"))
        except Exception:
            pass
        return None, None

    @staticmethod
    def _is_stale(df, func_list) -> bool:
        """spot_sina 返回月份与 list_sina 当前活跃月份不交 -> 陈旧数据。"""
        try:
            months = func_list()
            if isinstance(months, dict):
                for v in months.values():
                    months = v
                    break
            live = set()
            for m in months:
                mm = re.search(r"(\d{2})(\d{2})", str(m))
                if mm:
                    live.add(mm.group(1) + mm.group(2))
            spot_months = set()
            for c in list(df["看涨合约-标识"]) + list(df["看跌合约-标识"]):
                mm = re.search(r"(\d{2})(\d{2})[CP]", str(c))
                if mm:
                    spot_months.add(mm.group(1) + mm.group(2))
            if not spot_months or not live:
                return False
            return spot_months.isdisjoint(live)
        except Exception:
            return False

    @staticmethod
    def _nearest_expiry(func_list) -> Optional[str]:
        try:
            months = func_list()
            if isinstance(months, dict):
                # 形如 {'沪深300指数': ['io2608', ...]}
                for v in months.values():
                    months = v
                    break
            if not months:
                return None
            # 取第一个（最近月份），解析 YYMM
            code = str(months[0])
            digits = "".join(ch for ch in code if ch.isdigit())
            if len(digits) < 4:
                return None
            yy = int(digits[:2]) + 2000
            mm = int(digits[2:4])
            return AkShareCFFEXProvider._fourth_wednesday(yy, mm)
        except Exception:
            return None

    @staticmethod
    def _fourth_wednesday(yy: int, mm: int) -> str:
        # 中金所期权到期：到期月第4个周三
        d = datetime(yy, mm, 1)
        wednesdays = []
        while d.month == mm:
            if d.weekday() == 2:  # Wednesday
                wednesdays.append(d)
            d += timedelta(days=1)
        if len(wednesdays) >= 4:
            return wednesdays[3].strftime("%Y-%m-%d")
        return wednesdays[-1].strftime("%Y-%m-%d") if wednesdays else f"{yy:04d}-{mm:02d}-28"
