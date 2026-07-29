# -*- coding: utf-8 -*-
"""
commodity_engine/scoring.py —— Commodity Engine v1 评分（Phase 1）

三品种（内盘为交易核心，外盘为宏观锚）：
  AU0 沪金  + 外盘 XAU(GC)    → 代表 流动性/避险
  CU0 沪铜  + 外盘 HG         → 代表 全球制造周期
  SC0 原油  + 外盘 CL         → 代表 通胀/供给冲击

v1 权重（供需数据尚空，不伪造）：
  宏观 40% / 资金 25% / 技术 25% / 风险 10%
  cycle_score(供需) 留空 NULL，待 Phase 2 库存/仓单接口补齐后升级为：
  宏观30 / 供需25 / 资金20 / 技术15 / 风险10

宏观源：复用 Gold Engine 评分逻辑（DB 源，不依赖 thsdk 实时）
  - 全局宏观环境分 global_macro_score = composite(DXY, TIPS, Fed, Oil, BE, Geo)
  - 黄金 macro = global_macro_score
  - 铜   macro = 0.6*global + 0.4*growth(全球制造周期)
  - 原油 macro = 0.6*global + 0.4*supply(供给冲击)

输出：commodity_factor_daily（每品种每日一行：
  macro/fund/tech/risk/total + stage(阶段) + analysis(JSON 解释型文本)）

用法：
  python commodity_engine/scoring.py            # 评分 + 回填 + 打印最新
  python commodity_engine/scoring.py --symbol AU0
"""
from __future__ import annotations

import os
import sys
import json
import math
import sqlite3
import datetime
import argparse

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from database.models import get_db  # noqa: E402

# 复用 Gold Engine 的评分逻辑（DB 源宏观，不直接调其实时采集）
try:
    from gold_engine.scoring.drive_scorer import (
        _score_dxy, _score_tips, _score_fed, _score_oil,
        _score_breakeven, _score_geopolitical,
    )
    _GOLD_OK = True
except Exception:
    _GOLD_OK = False

# 三品种：内盘交易核心 + 外盘宏观锚
PAIRS = {
    "AU0": {"name": "沪金", "anchor": "GC", "outer_symbol": "XAU", "category": "贵金属"},
    "CU0": {"name": "沪铜", "anchor": "HG", "outer_symbol": "HG", "category": "有色"},
    "SC0": {"name": "原油", "anchor": "CL", "outer_symbol": "CL", "category": "能源"},
}
BACKFILL_DAYS = 250


# =============================================================================
# 数据加载
# =============================================================================
def _load_series(symbol: str) -> list[dict]:
    conn = get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT date,close,change_pct,volume,open_interest FROM commodity_daily "
        "WHERE symbol=? ORDER BY date ASC", (symbol,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _load_macro(date: str) -> dict | None:
    """从 global_history 取宏观快照（DB 源，稳定）。DXY/US10Y 为主，TIPS 估算。"""
    conn = get_db()
    conn.row_factory = sqlite3.Row

    def near(symbol):
        r = conn.execute(
            "SELECT date,close,change_pct FROM global_history "
            "WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
            (symbol, date)).fetchone()
        return dict(r) if r else None

    dxy = near("DXY")
    us10y = near("US10Y")
    us2y = near("US2Y")
    cl = near("CL")
    conn.close()
    if not dxy or not us10y:
        return None
    us10y_v = float(us10y["close"])
    tips = round(us10y_v - 2.3, 2)            # 与 gold_engine 估算口径一致
    breakeven = round(us10y_v - tips, 2)
    return {
        "date": date,
        "dxy": float(dxy["close"]),
        "dxy_chg": float(dxy["change_pct"] or 0.0),
        "us10y": us10y_v,
        "us2y": float(us2y["close"]) if us2y else us10y_v,
        "tips": tips,
        "breakeven": breakeven,
        "fed_rate": float(us2y["close"]) if us2y else us10y_v,
        "oil_price": float(cl["close"]) if cl else 0.0,
        "oil_chg": float(cl["change_pct"]) if cl else 0.0,
    }


def _geo_baseline() -> float:
    """地缘风险基线（与 gold_engine 近似，0-10）。"""
    m = datetime.date.today().month
    s = 4.0
    if m >= 3:
        s = max(s, 6.5)
    if 9 <= m <= 11:
        s = max(s, 5.5)
    return s


# =============================================================================
# 宏观分（复用 Gold Engine）
# =============================================================================
def _global_macro_score(snap: dict | None):
    """全局宏观环境分（0-100）。复用 Gold Engine 的 _score_* 逻辑。"""
    if snap is None or not _GOLD_OK:
        return 50.0, []
    factors = [
        _score_dxy(snap["dxy"], snap["dxy_chg"]),
        _score_tips(snap["tips"], snap["us10y"]),
        _score_fed(snap["fed_rate"], "pause"),
        _score_oil(snap["oil_price"], snap["oil_chg"]),
        _score_breakeven(snap["breakeven"]),
        _score_geopolitical(_geo_baseline()),
    ]
    w = sum(f.weight for f in factors) or 1
    s = sum(f.score * f.weight for f in factors) / w
    return s, factors


def _growth_signal(snap: dict | None) -> float:
    """全球制造周期信号（铜用）。US10Y 水平映射：温和=偏多，过高/过低=偏空。"""
    us10y = snap["us10y"] if snap else 4.0
    if 3.5 <= us10y <= 4.5:
        return 65.0
    if us10y < 3.0:
        return 40.0     # 衰退担忧
    if us10y > 5.0:
        return 35.0     # 紧信用
    if us10y < 3.5:
        return 55.0
    return 45.0


def _supply_signal(snap: dict | None) -> float:
    """供给冲击信号（原油用）。地缘上升 + 油价上行 = 供给约束偏多。"""
    geo = _geo_baseline()
    oil_chg = snap["oil_chg"] if snap else 0.0
    base = 50.0
    if geo >= 6:
        base += 15
    elif geo >= 5:
        base += 8
    if oil_chg > 2:
        base += 10
    elif oil_chg > 0:
        base += 4
    elif oil_chg < -2:
        base -= 8
    return max(20.0, min(90.0, base))


# =============================================================================
# 资金 / 技术 / 风险
# =============================================================================
def _fund_score(series: list, idx: int):
    """资金分（0-100）：内盘持仓(OI)趋势 + 成交量趋势。外盘 OI 恒0，退化为量比。"""
    r = series[idx]
    oi = r["open_interest"]
    w = series[max(0, idx - 19): idx + 1]
    if len(w) < 6:
        return 50.0, "样本不足(<%d日)" % 6
    oi_prev = w[0]["open_interest"]
    oi_score = 50.0
    oi_chg = 0.0
    if oi is not None and oi_prev not in (None, 0):
        oi_chg = (oi / oi_prev - 1) * 100
        oi_score = 50.0 + max(-40.0, min(40.0, oi_chg * 2))
    rec = w[-10:]
    prev = w[:-10] if len(w) > 10 else w[: max(1, len(w) // 2)]
    avg_rec = sum(x["volume"] or 0 for x in rec) / max(1, len(rec))
    avg_prev = sum(x["volume"] or 0 for x in prev) / max(1, len(prev))
    vol_score = 50.0
    ratio = 1.0
    if avg_prev > 0:
        ratio = avg_rec / avg_prev
        vol_score = 50.0 + max(-25.0, min(25.0, (ratio - 1) * 40))
    fund = 0.6 * oi_score + 0.4 * vol_score
    note = f"20日持仓变化{oi_chg:+.1f}% 量比{ratio:.2f}"
    return fund, note


def _ma(series: list, idx: int, n: int):
    w = series[max(0, idx - n + 1): idx + 1]
    if len(w) < n:
        return None
    return sum(x["close"] for x in w) / n


def _rsi(series: list, idx: int, n: int = 14) -> float:
    w = series[max(0, idx - n): idx + 1]
    if len(w) < 2:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(w)):
        d = w[i]["close"] - w[i - 1]["close"]
        if d > 0:
            gains.append(d)
        elif d < 0:
            losses.append(-d)
    ag = sum(gains) / max(1, len(w) - 1)
    al = sum(losses) / max(1, len(w) - 1)
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def _tech_score(series: list, idx: int):
    r = series[idx]
    close = r["close"]
    ma20 = _ma(series, idx, 20)
    ma60 = _ma(series, idx, 60)
    if ma20 and ma60:
        if close > ma20 > ma60:
            ma_score = 80.0
        elif close > ma20 and ma20 <= ma60:
            ma_score = 62.0
        elif close < ma20 and ma20 >= ma60:
            ma_score = 40.0
        else:
            ma_score = 22.0
    else:
        ma_score = 50.0
    if ma20:
        mom = (close / ma20 - 1) * 100
        mom_score = 50.0 + max(-40.0, min(40.0, mom * 4))
    else:
        mom_score = 50.0
    rsi = _rsi(series, idx)
    tech = 0.4 * ma_score + 0.3 * mom_score + 0.3 * rsi
    note = f"价{close:.2f} MA20={ma20:.2f} MA60={ma60:.2f} RSI={rsi:.0f}"
    return tech, note, {"ma20": ma20, "ma60": ma60, "rsi": rsi, "close": close}


def _realized_vol(series: list, idx: int, n: int = 20) -> float:
    w = series[max(0, idx - n + 1): idx + 1]
    if len(w) < 3:
        return 0.15
    rets = []
    for i in range(1, len(w)):
        p0 = w[i - 1]["close"]
        if p0:
            rets.append(w[i]["close"] / p0 - 1)
    if not rets:
        return 0.15
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / len(rets)
    return math.sqrt(var) * math.sqrt(252)


def _risk_score(series: list, idx: int, snap: dict | None):
    """风险分（0-100，越高越安全/低波动）。= 100 - 波动罚分 - 宏观罚分。"""
    vol = _realized_vol(series, idx)
    penalty = max(0.0, min(60.0, (vol - 0.10) * 200))   # 波动10%→0, 40%→60封顶
    macro_pen = 0.0
    if snap and abs(snap["dxy_chg"]) > 1.0:
        macro_pen = min(10.0, abs(snap["dxy_chg"]) * 3)
    risk = max(20.0, 100.0 - penalty - macro_pen)
    note = f"年化波动{vol*100:.1f}% 波动罚{penalty:.0f} 宏观罚{macro_pen:.0f}"
    return risk, note


# =============================================================================
# 阶段 + 解释型分析
# =============================================================================
def _stage(total: float, tech_info: dict) -> str:
    close, ma20, ma60 = tech_info["close"], tech_info["ma20"], tech_info["ma60"]
    if total >= 60 and close and ma20 and ma60 and close > ma20 > ma60:
        return "上涨趋势"
    if total <= 42 or (ma20 and ma60 and close < ma20 < ma60):
        return "下跌趋势"
    return "震荡整理"


def _build_analysis(symbol, name, total, stage, macro, fund, tech, risk, snap, notes):
    drivers, risks = [], []
    for label, val in (("宏观", macro), ("资金", fund), ("技术", tech)):
        if val >= 65:
            drivers.append(f"{label}强({val:.0f})")
        elif val <= 40:
            risks.append(f"{label}弱({val:.0f})")
    if risk < 45:
        risks.append(f"风险分{risk:.0f}偏低(波动/宏观不确定性高)")
    elif risk >= 70:
        drivers.append(f"风险分{risk:.0f}高(环境平稳)")
    if not drivers:
        drivers.append("各维度均衡，无显著单边驱动")

    if stage == "上涨趋势" and total >= 60:
        strat = "持有/顺势，等待回踩均线加仓；不追高"
    elif stage == "下跌趋势" or total <= 42:
        strat = "回避/减仓，等待企稳信号(跌破MA60或波动率回落)"
    else:
        strat = "观望为主，区间操作；突破MA20且放量再跟进"

    macro_env = ""
    if snap:
        macro_env = (f"DXY={snap['dxy']:.1f} US10Y={snap['us10y']:.2f}% "
                     f"TIPS≈{snap['tips']:.2f}% 原油={snap['oil_price']:.0f}")

    return {
        "综合评分": round(total, 1),
        "阶段": stage,
        "维度": {"宏观": round(macro, 1), "资金": round(fund, 1),
                 "技术": round(tech, 1), "风险": round(risk, 1)},
        "主要驱动": drivers,
        "风险提示": risks,
        "策略建议": strat,
        "宏观环境": macro_env.strip(),
        "细节": notes,
    }


# =============================================================================
# 单品种评分
# =============================================================================
def score_one(symbol: str, series: list, idx: int) -> dict:
    snap = _load_macro(series[idx]["date"])
    gmacro, _ = _global_macro_score(snap)
    if symbol == "AU0":
        macro = gmacro
        macro_note = "黄金宏观=全球环境分(美元/实际利率/地缘)"
    elif symbol == "CU0":
        macro = 0.6 * gmacro + 0.4 * _growth_signal(snap)
        macro_note = "铜宏观=0.6全球环境+0.4全球制造周期"
    else:  # SC0
        macro = 0.6 * gmacro + 0.4 * _supply_signal(snap)
        macro_note = "原油宏观=0.6全球环境+0.4供给冲击"

    fund, fund_note = _fund_score(series, idx)
    tech, tech_note, tech_info = _tech_score(series, idx)
    risk, risk_note = _risk_score(series, idx, snap)
    total = 0.40 * macro + 0.25 * fund + 0.25 * tech + 0.10 * risk
    stage = _stage(total, tech_info)
    analysis = _build_analysis(
        symbol, PAIRS[symbol]["name"], total, stage, macro, fund, tech, risk, snap,
        {"宏观": macro_note, "资金": fund_note, "技术": tech_note, "风险": risk_note})

    return {
        "date": series[idx]["date"],
        "symbol": symbol,
        "name": PAIRS[symbol]["name"],
        "category": PAIRS[symbol]["category"],
        "macro_score": round(macro, 1),
        "cycle_score": None,
        "fund_score": round(fund, 1),
        "technical_score": round(tech, 1),
        "risk_score": round(risk, 1),
        "total_score": round(total, 1),
        "stage": stage,
        "analysis": json.dumps(analysis, ensure_ascii=False),
    }


# =============================================================================
# 对外入口
# =============================================================================
def ensure_commodity_factor(backfill_days: int = BACKFILL_DAYS,
                            symbol_filter: list | None = None) -> dict:
    """评分并落 commodity_factor_daily。增量：只算比已存最大日期更新的行；
    首次/空表则回填最近 backfill_days 日。"""
    from commodity_engine import collector as commodity_collector
    commodity_collector.ensure_schema()

    conn = get_db()
    results = {}
    for symbol in PAIRS:
        if symbol_filter and symbol not in symbol_filter:
            continue
        series = _load_series(symbol)
        if not series:
            results[symbol] = {"ok": False, "note": "no series"}
            continue
        stored_max = conn.execute(
            "SELECT MAX(date) FROM commodity_factor_daily WHERE symbol=?",
            (symbol,)).fetchone()[0]
        if stored_max is None:
            window = series[-backfill_days:]
        else:
            window = [r for r in series if r["date"] > stored_max]
        rows = [score_one(symbol, series, series.index(r)) for r in window]
        cols = ["date", "symbol", "name", "category", "macro_score", "cycle_score",
                "fund_score", "technical_score", "risk_score", "total_score",
                "stage", "analysis"]
        conn.executemany(
            f"INSERT OR REPLACE INTO commodity_factor_daily ({','.join(cols)}) "
            f"VALUES ({','.join(['?'] * len(cols))})",
            [[r[c] for c in cols] for r in rows])
        results[symbol] = {
            "ok": True, "scored": len(rows),
            "latest": rows[-1]["date"] if rows else None,
            "total": rows[-1]["total_score"] if rows else None,
            "stage": rows[-1]["stage"] if rows else None,
        }
    conn.commit()
    conn.close()
    return results


def get_factor_latest() -> list[dict]:
    conn = get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT f.* FROM commodity_factor_daily f "
        "JOIN (SELECT symbol, MAX(date) md FROM commodity_factor_daily GROUP BY symbol) t "
        "ON f.symbol=t.symbol AND f.date=t.md ORDER BY f.symbol").fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Commodity Engine v1 评分（Phase 1）")
    ap.add_argument("--symbol", help="只评单个品种 AU0/CU0/SC0")
    args = ap.parse_args()
    filt = [args.symbol] if args.symbol else None
    res = ensure_commodity_factor(symbol_filter=filt)
    print(f"\n=== Commodity Engine v1 评分 ({datetime.datetime.now().isoformat(timespec='seconds')}) ===")
    for sym, info in res.items():
        if info.get("ok"):
            print(f"  {sym:4s} ✅ 评分{info['scored']}行 最新{info['latest']} "
                  f"总分{info['total']} 阶段{info['stage']}")
        else:
            print(f"  {sym:4s} ❌ {info.get('note','')}")

    print("\n--- 最新评分快照（含解释）---")
    for r in get_factor_latest():
        if filt and r["symbol"] not in filt:
            continue
        try:
            a = json.loads(r["analysis"])
        except Exception:
            a = {}
        print(f"\n[{r['symbol']}] {r['name']}（{r['date']}）  综合 {r['total_score']}  {r['stage']}")
        print(f"  维度: 宏观{r['macro_score']} 资金{r['fund_score']} "
              f"技术{r['technical_score']} 风险{r['risk_score']}")
        print(f"  宏观环境: {a.get('宏观环境','')}")
        print(f"  主要驱动: {'；'.join(a.get('主要驱动', []))}")
        print(f"  风险提示: {'；'.join(a.get('风险提示', []))}")
        print(f"  策略建议: {a.get('策略建议','')}")
