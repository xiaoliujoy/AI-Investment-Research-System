# -*- coding: utf-8 -*-
"""
trade_review.py —— 交易复盘纪律引擎（Personal AI Research System）
==================================================================

移植自开源项目 AI-Portfolio-Compass（MIT License,
https://github.com/Elian-dan/AI-Portfolio-Compass-public）的
`backend/app/services/trade_review.py` 的 **规则化复盘纪律**。

「取其精华去其糟粕」适配说明：
  - 精华：classify_trade_result() 用「成交价 vs 成交后 1日/5日 K线收盘价」
    按规则生成 *事实标签*（追高 / 卖飞 / 止损拖延 / 计划内）。
    原项目核心原则——"事实标签由成交价和成交后 K 线收盘价按规则生成；
    AI 只解释，不改写事实"——我们完全保留并强化，因为它正好对应
    用户方法论里的「复盘=事实，不甩锅给 AI」。
  - 去糟粕：原项目依赖 FutuReadOnlyAdapter 拉成交与 K 线。我们去掉券商耦合，
    改用：
      (a) 用户手工记账 output/trades.jsonl（每行一笔成交）；
      (b) TDX 本地 stock_daily 库查成交后 1/5 日收盘价（零网络、确定性强）。
  - 数据源：我们自己的 TDX 本地数据 + 用户手工 trades.jsonl，不依赖任何商业源。

事实标签（与原项目一致，阈值 REVIEW_MOVE_THRESHOLD=0.03）：
  BUY 后 1 日跌 > 3%  -> 买到短线高位
  BUY 后 5 日跌 > 3%  -> 买后承压
  BUY 后深套 > 10%    -> 止损拖延（附加标记）
  SELL 后 1 日涨 > 3% -> 卖飞
  SELL 后 5 日涨 > 3% -> 卖后上涨
  其余                 -> 计划内买入 / 计划内卖出

输入：
  output/trades.jsonl   用户维护的成交台账（缺失则优雅降级）
  backend/database/vibe_research.db -> stock_daily（TDX 本地，查成交后收盘价）

输出：build() 返回 dict，供 CIO memo + research_memo 渲染。
"""
from __future__ import annotations

import os
import json
import sqlite3
import datetime
from dataclasses import dataclass
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
TRADES_PATH = os.path.join(OUT, "trades.jsonl")
DB_PATH = os.path.join(ROOT, "database", "vibe_research.db")

REVIEW_MOVE_THRESHOLD = 0.03   # 3% 阈值（与原项目一致）
STOP_DELAY_RATIO = -0.10       # 浮亏 > 10% 且仍持有 -> 止损拖延标记


@dataclass
class TradeFacts:
    code: str
    name: str
    side: str               # BUY / SELL
    deal_price: float
    deal_time: str          # YYYY-MM-DD
    ref_1d: Optional[float] = None
    ref_5d: Optional[float] = None
    ref_latest: Optional[float] = None


def _trade_return(side: str, deal_price: float, ref_price: float) -> Optional[float]:
    """成交收益率（与原项目一致）：SELL 取负。"""
    if not deal_price or ref_price is None:
        return None
    r = ref_price / deal_price - 1.0
    return -r if side == "SELL" else r


def classify_trade_result(side: str, one_day: Optional[float],
                          five_day: Optional[float], latest: Optional[float]):
    """纯规则事实标签（移植自 AI-Portfolio-Compass trade_review.py，MIT）。

    返回 (label, note)。label 是事实（不夹带 AI 推断）。
    """
    if side == "BUY":
        if one_day is not None and one_day <= -REVIEW_MOVE_THRESHOLD:
            return ("买到短线高位",
                    f"买入后1日即跌{one_day*100:+.1f}%，大概率追在短线高点")
        if five_day is not None and five_day <= -REVIEW_MOVE_THRESHOLD:
            return ("买后承压", f"买入后5日跌{five_day*100:+.1f}%，暂未被市场验证")
        return ("计划内买入", "买入后走势平稳，属计划内建仓")
    elif side == "SELL":
        if one_day is not None and one_day <= -REVIEW_MOVE_THRESHOLD:
            return ("卖飞", f"卖出后1日继续涨{-one_day*100:+.1f}%，少赚/踏空")
        if five_day is not None and five_day <= -REVIEW_MOVE_THRESHOLD:
            return ("卖后上涨", f"卖出后5日涨{-five_day*100:+.1f}%，离场偏早")
        return ("计划内卖出", "卖出后走势平稳，属计划内了结")
    return ("未知", "方向未知")


# ═══════════════════════════════════════════════════════
#  数据加载 / TDX 适配器
# ═══════════════════════════════════════════════════════

def load_deals() -> list:
    """读取用户维护的成交台账 output/trades.jsonl。缺失/损坏 -> 空列表。"""
    if not os.path.exists(TRADES_PATH):
        return []
    out = []
    try:
        with open(TRADES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not d.get("code") or not d.get("side"):
                    continue
                out.append(d)
    except Exception:
        return []
    return out


def _normalize_code(code: str) -> str:
    """TDX stock_daily 的 code 是纯 6 位（如 600519）。
    兼容用户填写 sh600519 / 600519.SH 等写法。"""
    c = str(code).strip().lower()
    for p in ("sh", "sz", "bj"):
        if c.startswith(p):
            c = c[2:]
    if c.endswith(".sh") or c.endswith(".sz") or c.endswith(".bj"):
        c = c[:-3]
    return c[:6]


def _post_deal_closes(code: str, deal_date: str):
    """从 TDX stock_daily 取成交后 1日/5日/最新 收盘价。无数据返回 (None,)*3。"""
    nc = _normalize_code(code)
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT date, close FROM stock_daily WHERE code=? AND date > ? "
            "ORDER BY date ASC", (nc, deal_date[:10])).fetchall()
        con.close()
    except Exception:
        return None, None, None
    if not rows:
        return None, None, None
    closes = [r[1] for r in rows]
    c1 = closes[0] if len(closes) >= 1 else None
    c5 = closes[4] if len(closes) >= 5 else closes[-1]
    cl = closes[-1]
    return c1, c5, cl


# ═══════════════════════════════════════════════════════
#  主构建
# ═══════════════════════════════════════════════════════

def build() -> dict:
    """交易复盘主构建。无 trades.jsonl -> has_data=False 优雅降级。"""
    deals = load_deals()
    if not deals:
        return {
            "has_data": False,
            "n_trades": 0,
            "reviews": [],
            "stats": {},
            "summary": "暂无成交台账（output/trades.jsonl）。"
                      "逐笔记录买卖后，本模块会自动复盘每笔交易的事实标签。",
        }

    reviews = []
    stats = {"买到短线高位": 0, "买后承压": 0, "计划内买入": 0,
             "卖飞": 0, "卖后上涨": 0, "计划内卖出": 0, "止损拖延": 0}
    stop_delay_examples = []

    for d in deals:
        side = str(d.get("side", "")).upper()
        if side not in ("BUY", "SELL"):
            continue
        code = str(d.get("code", ""))
        deal_price = float(d.get("price") or 0)
        deal_time = str(d.get("deal_time") or d.get("date") or "")
        if not deal_price or not deal_time:
            continue
        c1, c5, cl = _post_deal_closes(code, deal_time)
        r1 = _trade_return(side, deal_price, c1) if c1 is not None else None
        r5 = _trade_return(side, deal_price, c5) if c5 is not None else None
        rl = _trade_return(side, deal_price, cl) if cl is not None else None
        label, note = classify_trade_result(side, r1, r5, rl)

        # 止损拖延：买入后深套且仍持有（无对应卖出）
        stop_delay = False
        if side == "BUY" and rl is not None and rl <= STOP_DELAY_RATIO:
            stop_delay = True
            stats["止损拖延"] += 1
            stop_delay_examples.append({
                "code": code, "name": d.get("name", ""),
                "deal_time": deal_time[:10], "ret_latest": round(rl * 100, 1),
            })

        stats[label] = stats.get(label, 0) + 1
        reviews.append({
            "code": code,
            "name": d.get("name", ""),
            "side": side,
            "deal_time": deal_time[:10],
            "deal_price": round(deal_price, 2),
            "ret_1d": round(r1 * 100, 2) if r1 is not None else None,
            "ret_5d": round(r5 * 100, 2) if r5 is not None else None,
            "ret_latest": round(rl * 100, 2) if rl is not None else None,
            "label": label,
            "note": note,
            "stop_delay": stop_delay,
        })

    # 排序：复盘价值高的（卖飞/买到短线高位/止损拖延）置顶
    rank = {"卖飞": 0, "买到短线高位": 1, "止损拖延": 1, "买后承压": 2,
            "卖后上涨": 2, "计划内卖出": 3, "计划内买入": 3}
    reviews.sort(key=lambda x: (rank.get(x["label"], 9),
                                x["ret_latest"] if x["ret_latest"] is not None else 0))

    n = len(reviews)
    buy_n = sum(1 for r in reviews if r["side"] == "BUY")
    sell_n = n - buy_n
    discipline_rate = 0.0
    planned = stats.get("计划内买入", 0) + stats.get("计划内卖出", 0)
    if n:
        discipline_rate = round(planned / n * 100, 1)

    summary = (f"共复盘{n}笔（买{buy_n}/卖{sell_n}）：计划内{planned}笔"
               f"（纪律率{discipline_rate}%）。")
    if stats["卖飞"]:
        summary += f" ⚠ 卖飞{stats['卖飞']}笔，需反思止盈节奏。"
    if stats["买到短线高位"]:
        summary += f" ⚠ 买到短线高位{stats['买到短线高位']}笔，追高需克制。"
    if stats["止损拖延"]:
        summary += f" ⚠ 止损拖延{stats['止损拖延']}笔，深套未处理。"

    return {
        "has_data": True,
        "n_trades": n,
        "reviews": reviews,
        "stats": stats,
        "discipline_rate": discipline_rate,
        "stop_delay_examples": stop_delay_examples,
        "summary": summary,
    }


if __name__ == "__main__":
    import pprint
    pprint.pprint(build())
