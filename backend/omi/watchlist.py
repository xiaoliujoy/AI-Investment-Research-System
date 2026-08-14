"""OMI 观察标的配置（Watchlist）。

第一版只做中国：
  - 指数期权(CFFEX): 沪深300, 中证1000
  - ETF期权(SSE):    中证500 (510500)
  - 商品期权:        黄金(SHFE au) / 原油(INE sc) / 铜(SHFE cu)

adapter 字段决定用哪个数据适配器：
  cffex     -> akshare_cffex   (CFFEX 指数期权)
  sse       -> akshare_sse     (上交所 ETF 期权)
  commodity -> akshare_commodity (商品期权)

第二阶段再扩展 SPX / NDX / VIX。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class OmiUnderlying:
    omi_id: str                 # 稳定内部 id，如 'hs300'
    name: str                   # 中文名，如 '沪深300'
    asset_class: str            # index_option | etf_option | commodity_option
    region: str                 # 'CN'
    exchange: str               # CFFEX | SSE | SHFE | INE
    adapter: str                # cffex | sse | commodity
    underlying_symbol: Optional[str] = None   # akshare 用的标的/合约代码关键词
    product_key: Optional[str] = None         # akshare 函数中间键，如 'hs300'/'zz1000'
    contract_root: Optional[str] = None       # CFFEX 合约前缀，如 'io' (沪深300) / 'mo' (中证1000)
    notes: str = ""


OMI_WATCHLIST: list[OmiUnderlying] = [
    OmiUnderlying(
        omi_id="hs300", name="沪深300", asset_class="index_option",
        region="CN", exchange="CFFEX", adapter="cffex",
        product_key="hs300", contract_root="io", notes="中金所沪深300指数期权",
    ),
    OmiUnderlying(
        omi_id="zz1000", name="中证1000", asset_class="index_option",
        region="CN", exchange="CFFEX", adapter="cffex",
        product_key="zz1000", contract_root="mo", notes="中金所中证1000指数期权(合约前缀 mo)",
    ),
    OmiUnderlying(
        omi_id="zz500", name="中证500", asset_class="etf_option",
        region="CN", exchange="SSE", adapter="sse",
        underlying_symbol="510500", notes="上交所中证500ETF期权(标的 510500)",
    ),
    OmiUnderlying(
        omi_id="au", name="黄金", asset_class="commodity_option",
        region="CN", exchange="SHFE", adapter="commodity",
        underlying_symbol="au", notes="上期所黄金期权",
    ),
    OmiUnderlying(
        omi_id="sc", name="原油", asset_class="commodity_option",
        region="CN", exchange="INE", adapter="commodity",
        underlying_symbol="sc", notes="上海国际能源交易中心原油期权",
    ),
    OmiUnderlying(
        omi_id="cu", name="铜", asset_class="commodity_option",
        region="CN", exchange="SHFE", adapter="commodity",
        underlying_symbol="cu", notes="上期所铜期权",
    ),
]


def get_underlying(omi_id: str) -> Optional[OmiUnderlying]:
    for u in OMI_WATCHLIST:
        if u.omi_id == omi_id:
            return u
    return None
