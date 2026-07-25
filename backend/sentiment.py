# -*- coding: utf-8 -*-
"""
情绪验证模块（市场情绪温度计 / Market Sentiment Gauge）
=========================================================
职责：把「资金+情绪验证」里的"情绪"这一半做成可量化、可验证的信号。
零外部依赖 —— 全部来自本地库：
  - stock_daily（市场宽度 / 涨跌家数 / 涨停跌停 / 量能比）
  - limit_up_daily（连板高度 / 涨停主题家数）

设计要点（用户边界，2026-07-11）：
  - 不接触 个股成交额、不接触 ma20/ma60。情绪只用「计数 / 比值 / 连板」信号。
  - 排除通达信指数代码（880xxx/999xxx/399xxx），这些被误导入 stock_daily，
    其成交额=全市场总量会污染聚合（已实测确认）。
  - 情绪状态：冰点 / 低迷 / 回暖 / 活跃 / 高潮（另含 退潮迹象检测）。
  - 只引用「比值 / 计数」类信号（宽度、涨停跌停、连板、量能比），不暴露绝对成交额。
    stock_daily.amount 存在约 10x 膨胀，绝对值不可信；量能比=今日/近20日均，
    膨胀均匀可相互抵消，作为比值保留。
  - 输出一句验证 verdict，供 playbook 的「资金+情绪验证」段与推送继承。
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "vibe_research.db")
EXCLUDE_IDX = "(code LIKE '880%' OR code LIKE '999%' OR code LIKE '399%')"


def _conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def _prev_date(cur, date):
    r = cur.execute("SELECT MAX(date) FROM stock_daily WHERE date < ?", (date,)).fetchone()
    return r[0] if r else None


def market_sentiment(date):
    """返回当日市场情绪温度计 dict（仅计数/比值，无绝对成交额）。"""
    c = _conn()
    cur = c.cursor()
    try:
        # —— 市场宽度 + 涨停跌停（排除指数代码）——
        row = cur.execute(f"""
            SELECT COUNT(*) total,
                   SUM(CASE WHEN change_pct > 0 THEN 1 ELSE 0 END) up,
                   SUM(CASE WHEN change_pct < 0 THEN 1 ELSE 0 END) dn,
                   SUM(CASE WHEN change_pct >= 9.5 THEN 1 ELSE 0 END) zt,
                   SUM(CASE WHEN change_pct <= -9.5 THEN 1 ELSE 0 END) dt,
                   SUM(amount) amt
            FROM stock_daily WHERE date=? AND NOT {EXCLUDE_IDX}
        """, (date,)).fetchone()
        total = row["total"] or 0
        up = row["up"] or 0
        dn = row["dn"] or 0
        zt = row["zt"] or 0
        dt = row["dt"] or 0
        amt = row["amt"] or 0.0           # 仅供算量能比，绝不对外暴露绝对值
        up_ratio = round(up / (up + dn), 4) if (up + dn) else 0.5

        # —— ST 连板拆分（双轨）：情绪只信「正常股」，ST 单独报数不污染 ——
        # 正常股涨停/连板（排除 ST/*/退市，避免重组连板虚高情绪）
        lu = cur.execute(
            "SELECT COUNT(*) n, MAX(board_height) bh FROM limit_up_daily "
            "WHERE date=? AND (is_st IS NULL OR is_st=0)", (date,)).fetchone()
        board_n = lu["n"] or 0            # = 正常股涨停数（limit_up_real）
        board_h = lu["bh"] or 0           # = 正常股最高连板（height_real）
        # ST 涨停/连板（单独口径）
        lu_st = cur.execute(
            "SELECT COUNT(*) n, MAX(board_height) bh FROM limit_up_daily "
            "WHERE date=? AND is_st=1", (date,)).fetchone()
        zt_st = lu_st["n"] or 0           # ST 涨停数（limit_up_daily 覆盖的 ST 连板）
        height_st = lu_st["bh"] or 0      # ST 最高连板
        # 全市场涨停 zt 含 ST，正常涨停 ≈ 总数 − ST 涨停（用于情绪打分，避免 ST 虚高）
        zt_real = max(0, zt - zt_st)

        # —— 量能比：今日 / 前20交易日均（比值，膨胀均匀可抵消）——
        prev = _prev_date(cur, date)
        avg20 = cur.execute(f"""
            SELECT AVG(d) FROM (
                SELECT SUM(amount) d FROM stock_daily
                WHERE date < ? AND NOT {EXCLUDE_IDX} GROUP BY date ORDER BY date DESC LIMIT 20
            )
        """, (date,)).fetchone()[0]
        vol_ratio = round(amt / avg20, 3) if avg20 else None

        # —— 退潮检测：今日涨停 vs 前一日涨停 ——
        zt_prev = 0
        if prev:
            zt_prev = cur.execute(
                f"SELECT SUM(CASE WHEN change_pct>=9.5 THEN 1 ELSE 0 END) FROM stock_daily "
                f"WHERE date=? AND NOT {EXCLUDE_IDX}", (prev,)
            ).fetchone()[0] or 0
        drawdown = (zt_prev - zt) / zt_prev if zt_prev else 0.0
        cooling = (drawdown >= 0.35)  # 涨停家数较前日骤降≥35% → 退潮迹象

        # —— 打分（只用计数/比值）——
        score = 0
        score += 2 if up_ratio >= 0.65 else (1 if up_ratio >= 0.55 else
                 (-1 if up_ratio <= 0.45 else (-2 if up_ratio <= 0.35 else 0)))
        score += 2 if zt_real >= 150 else (1 if zt_real >= 100 else (-1 if zt_real <= 60 else (-2 if zt_real < 30 else 0)))
        score += 2 if board_h >= 5 else (1 if board_h >= 3 else (0 if board_h == 2 else -1))
        if vol_ratio is not None:
            score += 1 if vol_ratio >= 1.2 else (-1 if vol_ratio < 0.9 else 0)

        # —— 状态映射 ——
        if cooling and score <= 1:
            state, state_en = "退潮", "cooling"
        elif score >= 4:
            state, state_en = "高潮", "euphoria"
        elif score >= 2:
            state, state_en = "活跃", "active"
        elif score >= 0:
            state, state_en = "回暖", "recovering"
        elif score >= -2:
            state, state_en = "低迷", "sluggish"
        else:
            state, state_en = "冰点", "freezing"

        # —— 验证 verdict（只用量/计数，不提绝对成交额）——
        vol_txt = (f"量能比{vol_ratio}（" +
                   ("放量" if vol_ratio and vol_ratio >= 1.2 else
                    ("缩量" if vol_ratio and vol_ratio < 0.9 else "持平")) + "）")
        parts = [f"上涨{up}/下跌{dn}（占比{up_ratio*100:.0f}%）｜"
                 f"涨停{zt}（正常{zt_real}/ST{zt_st}）／跌停{dt}｜"
                 f"连板高度 正常{board_h}板／ST{height_st}板｜{vol_txt}"]
        if state in ("高潮", "活跃"):
            parts.append("市场情绪高涨、风险偏好强，利于主线板块发酵与连板梯队延续；"
                         "但高潮区需防一致后赶顶，只可低吸不追高。")
        elif state in ("回暖", "低迷"):
            parts.append("情绪中性偏弱，资金仍在试错，宜聚焦已验证的主线、等放量确认再加码。")
        elif state == "冰点":
            parts.append("情绪冰点，亏钱效应扩散，防御为主、控仓等待反转信号。")
        elif state == "退潮":
            parts.append(f"涨停家数较前日({zt_prev})骤降{drawdown*100:.0f}%，情绪退潮，"
                         "高位股与连板梯队风险骤增，回避追高。")
        verdict = " ".join(parts)

        return {
            "status": "已接入",
            "date": date,
            "state": state,
            "state_en": state_en,
            "score": score,
            "up": up, "down": dn, "total": total, "up_ratio": up_ratio,
            "zt": zt, "zt_real": zt_real, "zt_st": zt_st,
            "dt": dt, "board_height": board_h,
            "limit_up_real": board_n, "limit_up_st": zt_st,
            "height_real": board_h, "height_st": height_st,
            "vol_ratio": vol_ratio,
            "cooling": cooling, "zt_prev": zt_prev,
            "verdict": verdict,
            "read": f"【情绪验证：{state}】{verdict}",
            "gaps": [] if total else ["当日行情数据缺失"],
        }
    finally:
        c.close()


if __name__ == "__main__":
    import json
    d = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "output", "decision_tree.json"), encoding="utf-8"))["trade_date"]
    r = market_sentiment(d)
    print("DATE:", r["date"])
    print("STATE:", r["state"], "(score", r["score"], ")")
    print("up/down:", r["up"], "/", r["down"], "ratio", r["up_ratio"])
    print("zt/dt/board:", r["zt"], "/", r["dt"], "/", r["board_height"])
    print("vol_ratio:", r["vol_ratio"])
    print("READ:", r["read"])
