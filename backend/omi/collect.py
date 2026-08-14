"""OMI 采集编排（Observation Only）。

每天流程：
  取原始链(adapter) -> 存原始(option_chain_raw) -> 算指标(含历史用于 rank/change)
  -> 存日度(option_omi_daily) -> 生成摘要。

严格不进 IC/CIO 评分系统：本模块产出只落 OMI 表，不写任何 score / decision 表。
"""

from __future__ import annotations

import json
from datetime import datetime

from .adapters import get_provider
from .indicators import compute_omi_daily
from .storage import (
    get_omi_history,
    get_enabled_watchlist,
    save_chain_raw,
    save_omi_daily,
)
from .watchlist import OmiUnderlying


def collect_one(underlying: OmiUnderlying, trade_date: str) -> dict:
    """采集并计算单个标的，返回结果摘要（含状态）。"""
    result = {
        "omi_id": underlying.omi_id,
        "name": underlying.name,
        "trade_date": trade_date,
        "status": "ok",
        "contracts": 0,
        "note": "",
    }
    try:
        provider = get_provider(underlying)
        chain = provider.fetch(underlying, trade_date)
    except Exception as e:
        result["status"] = "adapter_error"
        result["note"] = f"{type(e).__name__}: {e}"[:300]
        return result

    # 陈旧数据守卫：CFFEX 数据源在本环境可能冻结在旧月份，跳过以免污染观测
    if str(chain.source).startswith("akshare_cffex:STALE"):
        result["status"] = "stale_data"
        result["note"] = "CFFEX 数据源返回非当前月份(陈旧)数据，已跳过，不写入观测"
        return result

    result["contracts"] = len(chain.contracts)
    if chain.underlying_price is None:
        result["note"] = "underlying_price 缺失（IV 无法计算）；已存原始链供后续补全"
    if not chain.contracts:
        result["status"] = "empty"
        return result

    # 存原始链（原始与计算分离）
    try:
        save_chain_raw(chain)
    except Exception as e:
        result["note"] = (result["note"] + f" | raw_save_err:{e}")[:300]

    # 历史（用于 iv_rank / iv_percentile / iv_change_pct）
    history = get_omi_history(underlying.omi_id, trade_date)

    rec = compute_omi_daily(chain, history)
    # 若平价反推成功算出 IV，清除适配器阶段的"underlying_price 缺失"旧提示
    if rec.get("atm_iv") is not None and "underlying_price 缺失" in (result.get("note") or ""):
        result["note"] = ""
    rec["raw_coverage"] = json.dumps(
        {
            "source": chain.source,
            "n_contracts": len(chain.contracts),
            "underlying_price": chain.underlying_price,
            "has_underlying_oi": chain.underlying_call_oi is not None
            or chain.underlying_put_oi is not None,
            "per_contract_oi": any(
                c.open_interest for c in chain.contracts
            ),
        },
        ensure_ascii=False,
    )
    try:
        save_omi_daily(rec)
    except Exception as e:
        result["status"] = "save_error"
        result["note"] = (result["note"] + f" | daily_save_err:{e}")[:300]
        return result

    result["atm_iv"] = rec.get("atm_iv")
    result["iv_skew"] = rec.get("iv_skew")
    return result


def collect_day(trade_date: str = None) -> list[dict]:
    """采集当日全部观察标的。trade_date 缺省取今天(北京时区)。"""
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    out = []
    for row in get_enabled_watchlist():
        u = OmiUnderlying(
            omi_id=row["omi_id"], name=row["name"], asset_class=row["asset_class"],
            region=row["region"], exchange=row["exchange"], adapter=row["adapter"],
            underlying_symbol=row.get("underlying_symbol"),
            product_key=row.get("product_key"), contract_root=row.get("contract_root"),
        )
        out.append(collect_one(u, trade_date))
    return out
