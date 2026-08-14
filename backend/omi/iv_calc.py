"""Black-Scholes 隐含波动率求解（OMI 自己算 IV，不依赖数据源 IV 字段）。

设计依据（用户要求）：
- 原始数据与计算指标分离。OMI 必须能基于 标的价格/行权价/到期/期权价 自己算 IV，
  这样换数据源或修正算法后可重算全部历史。
- 数据源(akshare)给的 IV 只作为参考列(iv_reported)交叉校验，不计入主值。

说明：
- 无风险利率用 RISK_FREE_RATE 近似（v0.1 固定；后续可接实时国债收益率）。
- 忽略股息率（股票/指数期权近似；商品期权近似）。这是观察期可接受的简化，记录于此。
- 用二分法求解，数值稳定，对深度 ITM/OTM 也健壮。
"""

from __future__ import annotations

import math

RISK_FREE_RATE: float = 0.015


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> float:
    """Black-Scholes 期权理论价格。T 为年化到期时间(年)。"""
    if S <= 0 or K <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "CALL" else max(K - S, 0.0)
        return intrinsic
    if T <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "CALL" else max(K - S, 0.0)
        return intrinsic
    if sigma <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "CALL" else max(K - S, 0.0)
        return intrinsic

    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    if option_type == "CALL":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_vol(
    S: float,
    K: float,
    T: float,
    r: float,
    market_price: float,
    option_type: str,
    lo: float = 1e-6,
    hi: float = 5.0,
    tol: float = 1e-7,
    max_iter: int = 100,
) -> Optional[float]:
    """用二分法从市场期权价反解 IV。无解或非法返回 None。

    边界处理：
    - 价格 <= 0 或 None：返回 None（无交易/无报价）。
    - 价格低于内在价值：数据异常，返回 None。
    - 价格≈内在价值：IV 趋近 0，返回 0.0。
    """
    if market_price is None or market_price <= 0:
        return None
    if S <= 0 or K <= 0 or T <= 0:
        return None

    intrinsic = max(S - K, 0.0) if option_type == "CALL" else max(K - S, 0.0)
    if market_price < intrinsic - 1e-6:
        return None
    if abs(market_price - intrinsic) < 1e-4:
        return 0.0

    f_lo = 0.0
    price_lo = bs_price(S, K, T, r, lo, option_type)
    f_lo = price_lo - market_price
    f_hi = bs_price(S, K, T, r, hi, option_type) - market_price

    # 若两端同号，说明该价格不在 BS 单调区间内（极端价外或数据噪声），返回 None
    if f_lo * f_hi > 0:
        return None

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = bs_price(S, K, T, r, mid, option_type) - market_price
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return 0.5 * (lo + hi)
