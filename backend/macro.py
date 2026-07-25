"""全球宏观资产数据（黄金、原油、比特币、美元指数）—— 数据全部来自 akshare 公开接口。
只读、无状态、按用户传入代码返回客观行情数据。不预设标的、不推荐、不预测。"""

from __future__ import annotations

import time as _time

import akshare as ak

# 支持的商品/加密货币资产
_COMMODITIES = {
    "gold": {"symbol": "GC", "name": "COMEX黄金", "cat": "commodity"},
    "oil":  {"symbol": "CL", "name": "NYMEX原油", "cat": "commodity"},
    "copper": {"symbol": "HG", "name": "COMEX铜", "cat": "commodity"},
    "btc":  {"symbol": "BTC", "name": "CME比特币", "cat": "crypto"},
}

# 缓存
_cache: dict = {}
CACHE_TTL = 300  # 5 分钟


def _cached_fetch(key: str, fetch_fn):
    """带缓存的数据获取。"""
    now = _time.time()
    if key in _cache:
        cached = _cache[key]
        if now - cached["ts"] < CACHE_TTL:
            return cached["data"]
    data = fetch_fn()
    _cache[key] = {"ts": now, "data": data}
    return data


def _commodity_realtime(symbol: str) -> dict | None:
    """获取国外商品期货实时行情。失败返回 None。"""
    try:
        df = ak.futures_foreign_commodity_realtime(symbol)
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        price = row.get("最新价")
        chg = row.get("涨跌幅")
        return {
            "price": round(float(price), 4) if price is not None else None,
            "change_pct": round(float(chg), 4) if chg is not None else None,
            "time": str(row.get("行情时间", "")),
        }
    except Exception:
        return None


# BOC 汇率列名 → ISO 货币代码
_BOC_RATE_MAP = {
    "美元": "USD", "欧元": "EUR", "英镑": "GBP", "日元": "JPY",
    "加元": "CAD", "瑞士法郎": "CHF", "瑞典克朗": "SEK", "丹麦克朗": "DKK",
}

# DXY 权重
_DXY_WEIGHTS = {
    "EUR": -0.576,  # EUR/USD
    "JPY":  0.136,  # USD/JPY
    "GBP": -0.119,  # GBP/USD
    "CAD":  0.091,  # USD/CAD
    "SEK":  0.042,  # USD/SEK
    "CHF":  0.036,  # USD/CHF
}
_DXY_BASE = 50.14348112


def _calc_dxy_from_boc() -> dict:
    """利用中国银行公布的人民币汇率中间价计算美元指数 DXY。

    原理：BOC 公布的是 100 单位外币兑人民币，可推算交叉汇率：
      EUR/USD = (CNY/EUR) / (CNY/USD)
      USD/JPY = (CNY/USD) / (CNY/JPY)
    再用 ICE 官方权重加权得到 DXY。
    """
    try:
        df = ak.currency_boc_safe()
        if df is None or df.empty:
            return {"key": "dxy", "name": "美元指数", "cat": "forex", "price": None, "change_pct": None, "time": ""}

        row = df.iloc[-1]
        date_str = str(row.get("日期", ""))

        # 构建 CNY 价（每 1 单位外币兑 CNY）
        cny_per_unit: dict[str, float] = {}
        for col, iso in _BOC_RATE_MAP.items():
            v = row.get(col)
            if v is None or (isinstance(v, float) and (v != v)):  # NaN check
                continue
            v = float(v)
            if v <= 0:
                continue
            # BOC 公布的是 100 单位外币兑人民币
            cny_per_unit[iso] = v / 100.0

        # 检查是否有所需的所有汇率
        needed = {"USD", "EUR", "JPY", "GBP", "CAD", "SEK", "CHF"}
        if not needed.issubset(cny_per_unit):
            return {"key": "dxy", "name": "美元指数", "cat": "forex", "price": None, "change_pct": None, "time": date_str}

        # 计算交叉汇率
        eur_usd = cny_per_unit["EUR"] / cny_per_unit["USD"]
        usd_jpy = cny_per_unit["USD"] / cny_per_unit["JPY"]
        gbp_usd = cny_per_unit["GBP"] / cny_per_unit["USD"]
        usd_cad = cny_per_unit["USD"] / cny_per_unit["CAD"]
        usd_sek = cny_per_unit["USD"] / cny_per_unit["SEK"]
        usd_chf = cny_per_unit["USD"] / cny_per_unit["CHF"]

        # 计算 DXY
        dxy = _DXY_BASE
        dxy *= eur_usd ** _DXY_WEIGHTS["EUR"]
        dxy *= usd_jpy ** _DXY_WEIGHTS["JPY"]
        dxy *= gbp_usd ** _DXY_WEIGHTS["GBP"]
        dxy *= usd_cad ** _DXY_WEIGHTS["CAD"]
        dxy *= usd_sek ** _DXY_WEIGHTS["SEK"]
        dxy *= usd_chf ** _DXY_WEIGHTS["CHF"]

        return {"key": "dxy", "name": "美元指数", "cat": "forex", "price": round(dxy, 4), "change_pct": None, "time": date_str}
    except Exception:
        return {"key": "dxy", "name": "美元指数", "cat": "forex", "price": None, "change_pct": None, "time": ""}


def _fetch_all() -> dict:
    """实际抓取数据的函数（无缓存）。"""
    assets = []
    for key, asset in _COMMODITIES.items():
        data = _commodity_realtime(asset["symbol"])
        assets.append({
            "key": key,
            "name": asset["name"],
            "cat": asset["cat"],
            "price": data["price"] if data else None,
            "change_pct": data["change_pct"] if data else None,
            "time": data["time"] if data else "",
        })
    # 添加 DXY 美元指数
    assets.append(_calc_dxy_from_boc())
    return {"commodities": assets}


def get_all() -> dict:
    """获取全部宏观数据（商品 + DXY），供 /api/macro 一次性返回。带 5 分钟缓存。"""
    return _cached_fetch("macro_all", _fetch_all)
