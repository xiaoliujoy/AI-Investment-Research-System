# -*- coding: utf-8 -*-
"""
L7 个股风险维度（本地，从 stock_daily 计算，零外部依赖）
=========================================================
为 L6 突破候选逐只计算风险画像：波动率 / 近20日回撤 / 量比异常 / 技术位
（追高，价处20日高位）/ 在主线中的位置（龙头 vs 补涨）。输出每只风险分(0-100,越高越险)
与警示标签；并给出板块整体个股风险分（取候选中最险一只 + 均值）。

设计：不改变既有「市场风险 + 行业风险」的仓位预算逻辑，仅新增「个股风险」第三维，
      供 L7 综合分加权，并在看板逐只标注，辅助用户人工下单前的最后一道风控。
"""
import os
import math
import sqlite3
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "database", "vibe_research.db")


def _q(sql, args=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def compute_stock_risk(date, candidates, leader_codes=None):
    """candidates: list[dict] 含 'code'。leader_codes: set 已识别龙头代码。
    返回 {code: risk_record}。"""
    leader_codes = leader_codes or set()
    out = {}
    for cand in candidates:
        code = cand.get("code")
        if not code:
            continue
        ser = _q("""SELECT close, change_pct, high_20d, low_20d, volume_ratio
                    FROM stock_daily WHERE code=? AND date<=?
                    ORDER BY date DESC LIMIT 21""", (code, date))
        if len(ser) < 5:
            continue
        ser = list(reversed(ser))  # 升序
        closes = [r["close"] for r in ser]
        chgs = [r["change_pct"] for r in ser if r["change_pct"] is not None]
        last = ser[-1]
        vr = last["volume_ratio"]
        h20 = last["high_20d"]

        # 年化波动率（日收益 std × √252，单位 %）
        ann_vol = (statistics.pstdev(chgs) * math.sqrt(252)) if len(chgs) > 1 else 0.0
        # 近20日最大回撤
        peak = closes[0]; mdd = 0.0
        for p in closes:
            peak = max(peak, p)
            mdd = min(mdd, p / peak - 1)
        mdd = abs(mdd)
        # 技术位
        near_high = (closes[-1] / h20) if h20 else None
        chase = (near_high is not None and near_high >= 0.98)     # 追高（价处20日高位）

        score = 0.0
        score += min(ann_vol / 60.0, 1.0) * 30      # 波动 ≤30
        score += min(mdd / 0.20, 1.0) * 25          # 回撤 ≤25
        if vr and vr > 5:
            score += 20
        elif vr and vr > 3:
            score += 15
        elif vr and vr < 0.4:
            score += 8                              # 地量流动性风险
        if chase:
            score += 15
        if code in leader_codes:
            score -= 12                             # 已为主流认可的龙头，相对安全

        flags = []
        if ann_vol >= 45:
            flags.append("高波动")
        if mdd >= 0.12:
            flags.append("深回撤")
        if vr and vr > 3:
            flags.append("异常放量")
        if chase:
            flags.append("追高")
        if code not in leader_codes:
            flags.append("补涨(非龙头)")

        out[code] = {
            "code": code,
            "ann_vol": round(ann_vol, 1),
            "max_drawdown_20d": round(mdd * 100, 1),
            "volume_ratio": round(vr, 2) if vr else None,
            "near_high": round(near_high, 3) if near_high else None,
            "chase": chase,
            "is_leader": code in leader_codes,
            "score": round(max(0.0, min(score, 100.0)), 1),
            "flags": flags,
        }
    return out


def aggregate(risk_map):
    """候选个股风险的整体刻画。"""
    if not risk_map:
        return {"risk_stock": None, "max_score": None, "avg_score": None,
                "worst": None, "count": 0}
    scores = [v["score"] for v in risk_map.values()]
    worst = max(risk_map.values(), key=lambda v: v["score"])
    return {
        "risk_stock": round(max(scores), 1),
        "max_score": round(max(scores), 1),
        "avg_score": round(sum(scores) / len(scores), 1),
        "worst": worst,
        "count": len(scores),
    }


if __name__ == "__main__":
    date = "2026-07-09"
    cands = _q("""SELECT code FROM stock_daily WHERE date=? AND high_20d IS NOT NULL
                  ORDER BY volume_ratio DESC LIMIT 10""", (date,))
    rm = compute_stock_risk(date, cands)
    for code, v in rm.items():
        print(f"{code} 风险分={v['score']} 波动={v['ann_vol']}% 回撤={v['max_drawdown_20d']}% "
              f"量比={v['volume_ratio']} 追高={v['chase']} 标签={v['flags']}")
    print("\n聚合:", aggregate(rm))
