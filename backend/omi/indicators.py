"""OMI 指标计算层（v0.1）。

输入：标准化原始期权链 RawOptionChain + 历史日度记录（用于 iv_rank / iv_percentile / iv_change）。
输出：19 个 OMI 字段（含 option_market_summary）。

原则：
- IV/Rank/Skew 全部基于原始字段自己算（见 iv_calc），不依赖数据源 IV。
- 计算与原始分离：本层只读 RawOptionChain，写 option_omi_daily。
- 观测期：缺失数据如实留 null，不编造。OI 优先用标的层面聚合值（如 SSE daily_stats），
  逐合约 OI 可得时再补 max OI strike 集中度。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

import math

from .chain_model import RawOptionChain
from .iv_calc import RISK_FREE_RATE, implied_vol


def _years_to_expiry(expiry: str, trade_date: str) -> float:
    if not expiry or not trade_date:
        return 0.0
    e = t = None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            e = datetime.strptime(expiry, fmt)
            break
        except Exception:
            continue
    try:
        t = datetime.strptime(trade_date, "%Y-%m-%d")
    except Exception:
        t = None
    if e is None or t is None:
        return 0.0
    return max((e - t).days, 0) / 365.0


def compute_contract_ivs(chain: RawOptionChain) -> list[dict]:
    """为链中每个合约用 BS 自算 IV。返回带 iv/T 的合约字典列表。"""
    out: list[dict] = []
    S = chain.underlying_price
    if not S or S <= 0:
        return out
    for c in chain.contracts:
        T = _years_to_expiry(c.expiry, chain.trade_date)
        iv = implied_vol(S, c.strike, T, RISK_FREE_RATE, c.last_price, c.option_type)
        out.append(
            {
                "contract_code": c.contract_code,
                "option_type": c.option_type,
                "strike": c.strike,
                "expiry": c.expiry,
                "T": T,
                "volume": c.volume,
                "open_interest": c.open_interest,
                "iv": iv,
            }
        )
    return out


def _nearest_iv(rows: list[dict], S: float, otype: str) -> Optional[float]:
    cand = [r for r in rows if r["option_type"] == otype and r["iv"] is not None]
    if not cand:
        return None
    cand.sort(key=lambda r: abs(r["strike"] - S))
    return cand[0]["iv"]


def _atm_iv_for_expiry(rows: list[dict], S: float) -> Optional[float]:
    """该到期月的 ATM IV：取最接近标价的 Call/Put IV 平均。"""
    c_iv = _nearest_iv(rows, S, "CALL")
    p_iv = _nearest_iv(rows, S, "PUT")
    vals = [v for v in (c_iv, p_iv) if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _iv_at_moneyness(rows: list[dict], S: float, otype: str, target_m: float) -> Optional[float]:
    """取某类型中行权价最接近 target_m*S 的合约 IV（用于 skew 的 OTM 端）。"""
    cand = [r for r in rows if r["option_type"] == otype and r["iv"] is not None]
    if not cand:
        return None
    target = target_m * S
    cand.sort(key=lambda r: abs(r["strike"] - target))
    return cand[0]["iv"]


def _safe_div(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def _derive_underlying_price(chain: RawOptionChain) -> Optional[float]:
    """用看涨-看跌平价从期权链反推标的价：S = K·e^(-rT) + (C - P)。

    仅依赖链内数据，不依赖外部行情接口（本沙箱东财/部分新浪接口失效时的兜底，
    也是"原始+计算分离"的稳健做法）。两遍加权：先粗估 S，再取接近 ATM 的行权价精炼。
    """
    groups: dict = defaultdict(dict)
    for c in chain.contracts:
        if c.last_price is None or c.expiry is None:
            continue
        groups[(c.expiry, c.strike)][c.option_type] = c

    ests: list[tuple[float, float]] = []
    for (expiry, strike), d in groups.items():
        if "CALL" in d and "PUT" in d:
            T = _years_to_expiry(expiry, chain.trade_date)
            c_p = d["CALL"].last_price - d["PUT"].last_price
            s_i = strike * math.exp(-RISK_FREE_RATE * T) + c_p
            if s_i > 0:
                ests.append((strike, s_i))
    if not ests:
        return None

    rough = sum(s for _, s in ests) / len(ests)
    near = [(k, s) for k, s in ests if abs(k - rough) / rough < 0.05]
    if not near:
        return rough
    return sum(s for _, s in near) / len(near)


def compute_omi_daily(chain: RawOptionChain, history: list[dict]) -> dict:
    """计算单标的单日 OMI 日度记录。

    history: 该标的已存的历史 option_omi_daily 行（dict），至少含 atm_iv 与 trade_date，
             用于 iv_rank / iv_percentile / iv_change_pct。
    """
    # 标的价格：优先用适配器取到的外部报价；取不到则用期权链本身按
    # 看涨-看跌平价关系反推（S = K·e^(-rT) + (C-P)），避免依赖易失效的行情接口。
    S = chain.underlying_price
    if not S or S <= 0:
        S = _derive_underlying_price(chain)
        if S:
            chain.underlying_price = S

    rows = compute_contract_ivs(chain)

    # ---- 按到期月分组算 ATM IV ----
    by_exp: dict[str, list[dict]] = {}
    for r in rows:
        if r["iv"] is None:
            continue
        by_exp.setdefault(r["expiry"], []).append(r)

    exp_atm: list[tuple[str, float]] = []
    for exp, rs in by_exp.items():
        atm = _atm_iv_for_expiry(rs, S)
        if atm is not None:
            exp_atm.append((exp, atm))
    exp_atm.sort(key=lambda x: x[0])  # 按到期日升序

    atm_iv = exp_atm[0][1] if exp_atm else None
    front_month_iv = exp_atm[0][1] if exp_atm else None
    back_month_iv = exp_atm[-1][1] if exp_atm else None
    iv_term_structure = (
        (front_month_iv - back_month_iv) if (front_month_iv is not None and back_month_iv is not None) else None
    )

    # ---- IV Skew（25-delta 近似）：OTM Put IV - OTM Call IV ----
    iv_skew = None
    if exp_atm and S:
        front_rows = by_exp[exp_atm[0][0]]
        put_iv = _iv_at_moneyness(front_rows, S, "PUT", 0.95)
        call_iv = _iv_at_moneyness(front_rows, S, "CALL", 1.05)
        if put_iv is not None and call_iv is not None:
            iv_skew = put_iv - call_iv

    # ---- Volume / OI 层 ----
    call_volume = sum(r["volume"] for r in rows if r["option_type"] == "CALL" and r["volume"])
    put_volume = sum(r["volume"] for r in rows if r["option_type"] == "PUT" and r["volume"])
    put_call_volume_ratio = _safe_div(put_volume, call_volume)

    # OI：优先标的层面聚合（SSE daily_stats 等），否则逐合约求和
    call_oi = put_oi = put_call_oi_ratio = None
    if chain.underlying_call_oi is not None or chain.underlying_put_oi is not None:
        call_oi = chain.underlying_call_oi
        put_oi = chain.underlying_put_oi
        put_call_oi_ratio = chain.underlying_put_call_oi_ratio
    else:
        sum_call_oi = sum(r["open_interest"] for r in rows if r["option_type"] == "CALL" and r["open_interest"])
        sum_put_oi = sum(r["open_interest"] for r in rows if r["option_type"] == "PUT" and r["open_interest"])
        if sum_call_oi or sum_put_oi:
            call_oi = sum_call_oi or None
            put_oi = sum_put_oi or None
            put_call_oi_ratio = _safe_div(sum_put_oi, sum_call_oi)

    # max OI strike：需逐合约 OI
    max_call_oi_strike = max_put_oi_strike = None
    per_contract_oi = any(r["open_interest"] for r in rows)
    if per_contract_oi:
        calls = [r for r in rows if r["option_type"] == "CALL" and r["open_interest"]]
        puts = [r for r in rows if r["option_type"] == "PUT" and r["open_interest"]]
        if calls:
            max_call_oi_strike = max(calls, key=lambda r: r["open_interest"])["strike"]
        if puts:
            max_put_oi_strike = max(puts, key=lambda r: r["open_interest"])["strike"]

    # ---- 历史类：iv_rank / iv_percentile / iv_change_pct ----
    iv_rank = iv_percentile = iv_change_pct = None
    if atm_iv is not None and history:
        series = [h["atm_iv"] for h in history if h.get("atm_iv") is not None]
        series.append(atm_iv)
        series = [v for v in series if v is not None]
        if len(series) >= 2:
            lo, hi = min(series), max(series)
            if hi > lo:
                iv_rank = (atm_iv - lo) / (hi - lo)
            below = sum(1 for v in series if v <= atm_iv)
            iv_percentile = below / len(series)
            prev = history[-1].get("atm_iv")
            if prev:
                iv_change_pct = (atm_iv - prev) / prev

    summary = _build_summary(
        chain, atm_iv, iv_rank, iv_percentile, front_month_iv, back_month_iv,
        iv_term_structure, iv_skew, put_call_oi_ratio, max_call_oi_strike, max_put_oi_strike,
    )

    return {
        "omi_id": chain.omi_id,
        "trade_date": chain.trade_date,
        "underlying_price": chain.underlying_price,
        "underlying_change_pct": chain.underlying_change_pct,
        "atm_iv": atm_iv,
        "iv_rank": iv_rank,
        "iv_percentile": iv_percentile,
        "front_month_iv": front_month_iv,
        "back_month_iv": back_month_iv,
        "iv_term_structure": iv_term_structure,
        "iv_change_pct": iv_change_pct,
        "iv_skew": iv_skew,
        "call_volume": call_volume or None,
        "put_volume": put_volume or None,
        "put_call_volume_ratio": put_call_volume_ratio,
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "put_call_oi_ratio": put_call_oi_ratio,
        "max_call_oi_strike": max_call_oi_strike,
        "max_put_oi_strike": max_put_oi_strike,
        "option_market_summary": summary,
    }


def _level_word(v: Optional[float]) -> str:
    if v is None:
        return "暂无历史数据"
    if v < 0.2:
        return "历史低位"
    if v < 0.4:
        return "历史偏低"
    if v < 0.6:
        return "历史中位"
    if v < 0.8:
        return "历史偏高位"
    return "历史高位"


def _build_summary(chain, atm_iv, iv_rank, iv_percentile, front, back, term, skew,
                   pc_oi_ratio, max_call_k, max_put_k) -> str:
    name = chain.omi_id
    parts = []
    if atm_iv is not None:
        parts.append(f"{name}当前ATM隐含波动率约{atm_iv*100:.1f}%")
    parts.append(f"，处于{_level_word(iv_rank)}")
    if front is not None and back is not None:
        if front < back - 0.005:
            parts.append("，近月IV低于远月IV（期限结构正常/贴水）")
        elif front > back + 0.005:
            parts.append("，近月IV高于远月IV（短期风险定价升温）")
        else:
            parts.append("，近远月IV基本持平")
    if skew is not None:
        if skew > 0.03:
            parts.append(f"，Put/Call Skew走阔至{skew*100:.1f}pp（下行保护需求偏高）")
        else:
            parts.append("，Put/Call Skew处于常态")
    if pc_oi_ratio is not None:
        parts.append(f"，Put/Call持仓比{pc_oi_ratio:.2f}")
    if max_call_k is not None:
        parts.append(f"，Call OI集中于{max_call_k:.2f}附近")
    if max_put_k is not None:
        parts.append(f"，Put OI集中于{max_put_k:.2f}附近")
    tail = "。当前期权市场未显示明显的尾部风险定价。" if (skew is None or skew <= 0.03) else "。期权市场已对下行尾部风险定价，需关注。"
    return "".join(parts) + tail
