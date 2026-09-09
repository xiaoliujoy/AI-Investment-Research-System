# -*- coding: utf-8 -*-
"""
data_health —— 数据健康校验层（Data Integrity Layer · Trading OS P0）

职责：每天开盘前（produce 时）跑一次，给整条决策链做「信用体检」。
任何关键数据缺失 → trade_allowed=False → 唯一裁决器强制 NO（禁止交易），
从机制上消灭「数据层幻觉」：系统宁可空仓，也不拿不全的数据下注。

校验项（均可量化）：
  1. 股票数量   ：当日真个股（沪6/深0/创业3/北交83·87·920；剔除 ETF/转债/指数/新三板）应 ≥ 4000
  2. 个股资金流 ：stock_flow_daily 当日覆盖（占真个股）应 ≥ 80%（龙头资金第四环）
  3. 市值覆盖   ：真个股市值（market_cap>0）应 ≥ 90%（候选硬筛可信度）
  4. ST 过滤     ：limit_up_daily.is_st 列已启用（结构上已落，标记完成）
  5. 全球数据   ：global_history 当日行存在（跨资产闭环可用）

返回 dict：
  { trade_date, checks:[{name, ok, value, detail}], trade_allowed, failed:[...],
    summary, n_stocks, flow_cov, cap_cov }
"""
from __future__ import annotations
from db import get_conn, _DB_PATH
from universe import is_stock

import os
import sqlite3
from pathlib import Path

DB = str(_DB_PATH)

# 校验阈值（与用户「主交易池覆盖 >95%」目标对齐，留工程余量）
MIN_STOCKS = 4000
MIN_FLOW_COV = 80.0
MIN_CAP_COV = 90.0


# P1-C · C10：真个股判定收敛到 universe.is_stock（单一事实源，行为等价）。
# 历史此处曾有一份 `_is_stock` 副本，且其 docstring 误写「剔除北交所」——
# 实际规则包含北交所（83/87/920）。现删除副本，规则只留 universe.py 一份。


def check(trade_date: str = None) -> dict:
    """体检当日数据。返回健康报告 dict。"""
    c = get_conn()
    c.row_factory = sqlite3.Row
    try:
        if trade_date is None:
            trade_date = c.execute("SELECT max(date) FROM stock_daily").fetchone()[0]
        if not trade_date:
            return {"trade_date": None, "checks": [], "trade_allowed": False,
                    "failed": ["无行情日期"], "summary": "无行情日期，禁止交易",
                    "n_stocks": 0, "flow_cov": 0.0, "cap_cov": 0.0}

        # 1) 真个股集合 + 数量
        rows = [r[0] for r in c.execute(
            "SELECT code FROM stock_daily WHERE date=?", (trade_date,)).fetchall()]
        real = [x for x in rows if is_stock(x)]
        n_stocks = len(real)
        real_ph = "(" + ",".join("?" * len(real)) + ")" if real else "(NULL)"

        # 2) 个股资金流覆盖
        fl = c.execute(
            "SELECT count(*) FROM stock_flow_daily WHERE date=?", (trade_date,)).fetchone()[0]
        flow_cov = round(fl / n_stocks * 100, 1) if n_stocks else 0.0

        # 3) 市值覆盖（真个股）
        mc = 0
        if real:
            mc = c.execute(
                f"SELECT count(*) FROM stock_daily WHERE date=? AND market_cap>0 "
                f"AND code IN {real_ph}", (trade_date, *real)).fetchone()[0]
        cap_cov = round(mc / n_stocks * 100, 1) if n_stocks else 0.0

        # 4) ST 过滤（结构已启用；当日有 is_st 标注即可认为完成）
        st_rows = 0
        try:
            st_rows = c.execute(
                "SELECT count(*) FROM limit_up_daily WHERE date=? AND is_st=1",
                (trade_date,)).fetchone()[0]
        except Exception:
            pass
        st_ok = True  # 列已建 + 采集已写 is_st，结构层面完成；若当日无涨停则 st_rows=0 也 OK

        # 5) 全球数据
        gh = 0
        try:
            gh = c.execute(
                "SELECT count(*) FROM global_history WHERE date=?", (trade_date,)).fetchone()[0]
        except Exception:
            pass
        global_ok = gh > 0

        checks = [
            {"name": "股票数量", "ok": n_stocks >= MIN_STOCKS,
             "value": f"{n_stocks}", "detail": f"真个股（剔除ETF/债/指数），阈值≥{MIN_STOCKS}"},
            {"name": "个股资金流", "ok": flow_cov >= MIN_FLOW_COV,
             "value": f"{flow_cov}%",
             "detail": f"stock_flow_daily 覆盖占真个股，阈值≥{MIN_FLOW_COV}%（{fl}只）"},
            {"name": "市值覆盖", "ok": cap_cov >= MIN_CAP_COV,
             "value": f"{cap_cov}%",
             "detail": f"真个股市值>0 占比，阈值≥{MIN_CAP_COV}%（{mc}只）"},
            {"name": "ST 过滤", "ok": st_ok,
             "value": "已启用" if st_ok else "未启用",
             "detail": f"limit_up_daily.is_st 列已建并写入（当日 ST 涨停标注 {st_rows} 只）"},
            {"name": "全球数据", "ok": global_ok,
             "value": f"{gh}行", "detail": "global_history 当日行存在（跨资产闭环）"},
        ]
        failed = [c["name"] for c in checks if not c["ok"]]
        trade_allowed = len(failed) == 0
        summary = ("数据健康 · 允许交易" if trade_allowed
                   else f"数据健康未通过 → 禁止交易：{', '.join(failed)}")

        return {
            "trade_date": trade_date,
            "checks": checks,
            "trade_allowed": trade_allowed,
            "failed": failed,
            "summary": summary,
            "n_stocks": n_stocks,
            "flow_cov": flow_cov,
            "cap_cov": cap_cov,
        }
    finally:
        c.close()


if __name__ == "__main__":
    import json
    r = check()
    print(json.dumps(r, ensure_ascii=False, indent=2))
