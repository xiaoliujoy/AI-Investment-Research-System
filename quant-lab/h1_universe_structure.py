"""
H1 验证：高股息篮子是否具备「程序化波段」可交易结构
研投君 · 2026-08-21

不假设任何策略有效，只回答一个问题：
  高股息股票（默认 中证红利低波动 930955 成分）的历史日线，
  是否存在技术波段可利用的统计结构？
    - 波动率是否足够低（低波=可交易 swing，噪声小）
    - 收益是否自相关（动量 / 反转特征）
    - 经典均线穿越（MA20/MA60）多头胜率与回撤
    - 最大回撤分布（风险刻度）

数据源：AKShare（项目 requirements.txt 已含）。需联网拉取。
依赖：pandas, numpy, akshare
运行：在 Python 3.11 venv 中  ->  python quant-lab/h1_universe_structure.py
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import akshare as ak

# ----------------------------- 配置 -----------------------------
UNIVERSE_INDEX = "930955"   # 中证红利低波动；更宽可换 "000922"(中证红利)
START = "20150101"
END = "20260821"
QFQ = "qfq"                 # 前复权，波段回测必须用复权价
MA_FAST, MA_SLOW = 20, 60


# --------------------------- 数据拉取 ---------------------------
def get_universe(symbol: str) -> list[tuple[str, str]]:
    """返回 [(code, name), ...]。优先 CSI 接口，回退通用接口。"""
    try:
        df = ak.index_stock_cons_csindex(symbol=symbol)
    except Exception:
        df = ak.index_stock_cons(symbol=symbol)
    code_col = "品种代码" if "品种代码" in df.columns else "symbol"
    name_col = "品种名称" if "品种名称" in df.columns else "name"
    return list(zip(df[code_col].astype(str), df[name_col].astype(str)))


def get_daily(code: str) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=START, end_date=END, adjust=QFQ,
        )
        if df is None or df.empty:
            return None
        df = df.rename(columns={"日期": "date", "收盘": "close"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()[["close"]]
        return df
    except Exception as e:  # noqa: BLE001
        print(f"  [skip] {code}: {e}")
        return None


# --------------------------- 结构分析 ---------------------------
def analyse(close: pd.Series) -> dict:
    """高股息单标的的结构统计。"""
    ret = close.pct_change().dropna()
    if len(ret) < 250:
        return {}
    vol = ret.std() * np.sqrt(242)
    ac1 = ret.autocorr(lag=1)
    ma_f = close.rolling(MA_FAST).mean()
    ma_s = close.rolling(MA_SLOW).mean()
    pos = (ma_f > ma_s).astype(int)
    strat_ret = (ret * pos.shift(1).fillna(0)).dropna()
    win_rate = (strat_ret > 0).mean() if len(strat_ret) else float("nan")
    equity = (1 + strat_ret).cumprod()
    strat_mdd = (equity / equity.cummax() - 1).min()
    price_mdd = (close / close.cummax() - 1).min()
    return {
        "vol_ann": vol,
        "autocorr_1": ac1,
        "ma_cross_win": win_rate,
        "ma_cross_mdd": strat_mdd,
        "price_mdd": price_mdd,
        "pct_long": pos.mean(),
        "n_days": len(ret),
    }


# ----------------------------- 主流程 ---------------------------
def main() -> int:
    print(f"[1/3] 拉取 universe={UNIVERSE_INDEX} 成分...")
    universe = get_universe(UNIVERSE_INDEX)
    print(f"      共 {len(universe)} 只")

    rows = []
    for i, (code, name) in enumerate(universe, 1):
        df = get_daily(code)
        if df is None:
            continue
        stat = analyse(df["close"])
        if stat:
            stat["code"], stat["name"] = code, name
            rows.append(stat)
        print(f"      ({i}/{len(universe)}) {code} {name} done", flush=True)

    if not rows:
        print("无有效数据，退出")
        return 1

    res = pd.DataFrame(rows)
    cols = ["vol_ann", "autocorr_1", "ma_cross_win", "ma_cross_mdd", "price_mdd", "pct_long"]
    agg = res[cols].median()

    print("\n[2/3] 全篮子中位数（H1 结构画像）")
    print(agg.to_string())
    print(f"\n[3/3] 样本 {len(res)} 只 / 区间 {START}~{END}")
    print("解读：")
    print(f"  - 年化波动中位数 {agg['vol_ann']:.1%}（<25% 视为低波、适合波段）")
    print(f"  - 收益一阶自相关 {agg['autocorr_1']:.3f}（>0 偏动量 / <0 偏反转）")
    print(f"  - MA{MA_FAST}/{MA_SLOW} 多头胜率 {agg['ma_cross_win']:.1%}（>50% 才有关注价值）")
    print(f"  - 价格最大回撤中位数 {agg['price_mdd']:.1%}（风险刻度）")

    out = "quant-lab/h1_result.csv"
    res.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n明细已存 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
