"""全球环境评分器。

计算全球市场综合评分 (0-100)。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from global_market.config import load_scoring_config

BEIJING = timezone(timedelta(hours=8))


def calc_global_score() -> dict:
    """计算全球环境评分。
    
    Returns:
        {
            "date": "2026-07-10",
            "risk_appetite": 75.0,
            "tech_cycle": 82.0,
            "liquidity": 65.0,
            "china_relative": 70.0,
            "total_score": 73.5,
            "stage": "risk_on",
            "analysis": "..."
        }
    """
    config = load_scoring_config()
    weights = config.get("global_score", {}).get("weights", {})
    
    # 计算各维度
    risk_appetite = _calc_risk_appetite(config)
    tech_cycle = _calc_tech_cycle(config)
    liquidity = _calc_liquidity(config)
    china_relative = _calc_china_relative(config)
    
    # 加权总分
    total = (
        risk_appetite * weights.get("risk_appetite", 0.3) +
        tech_cycle * weights.get("tech_cycle", 0.3) +
        liquidity * weights.get("liquidity", 0.2) +
        china_relative * weights.get("china_relative", 0.2)
    )
    
    # 阶段判断
    if total >= 80:
        stage = "strong_risk_on"
    elif total >= 65:
        stage = "risk_on"
    elif total >= 50:
        stage = "neutral"
    elif total >= 35:
        stage = "risk_off"
    else:
        stage = "strong_risk_off"
    
    # 生成分析文本
    analysis = _generate_analysis(risk_appetite, tech_cycle, liquidity, china_relative, stage)
    
    now = datetime.now(BEIJING)
    
    return {
        "date": now.strftime("%Y-%m-%d"),
        "risk_appetite": round(risk_appetite, 1),
        "tech_cycle": round(tech_cycle, 1),
        "liquidity": round(liquidity, 1),
        "china_relative": round(china_relative, 1),
        "total_score": round(total, 1),
        "stage": stage,
        "analysis": analysis,
    }


def _calc_risk_appetite(config: dict) -> float:
    """计算风险偏好得分。"""
    from database import models
    
    # 获取 NASDAQ 20日涨幅
    conn = models.get_db()
    rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = 'NDX' ORDER BY date DESC LIMIT 22
    """).fetchall()
    conn.close()
    
    if len(rows) < 2:
        return 50.0
    
    latest = rows[0]["close"]
    
    # 20日收益率
    if len(rows) >= 21:
        old = rows[20]["close"]
    else:
        old = rows[-1]["close"]
    
    if latest is None or old is None or old == 0:
        return 50.0
    
    return_20d = (latest - old) / old * 100
    
    # 转换为分数: 涨幅越高分数越高
    # 20日涨幅 10% = 80分, 0% = 50分, -10% = 20分
    score = 50 + return_20d * 3
    return max(0, min(100, score))


def _calc_tech_cycle(config: dict) -> float:
    """计算科技周期得分。"""
    from database import models
    
    # 获取 SOX (费城半导体) 20日涨幅
    conn = models.get_db()
    rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = 'SOX' ORDER BY date DESC LIMIT 22
    """).fetchall()
    conn.close()
    
    if len(rows) < 2:
        return 50.0
    
    latest = rows[0]["close"]
    
    if len(rows) >= 21:
        old = rows[20]["close"]
    else:
        old = rows[-1]["close"]
    
    if latest is None or old is None or old == 0:
        return 50.0
    
    return_20d = (latest - old) / old * 100
    
    # 半导体涨幅与科技周期正相关
    score = 50 + return_20d * 4
    return max(0, min(100, score))


def _calc_liquidity(config: dict) -> float:
    """计算流动性得分。"""
    from database import models
    
    # 获取美元指数 (DXY)
    conn = models.get_db()
    rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = 'DXY' ORDER BY date DESC LIMIT 22
    """).fetchall()
    conn.close()
    
    if len(rows) < 2:
        return 50.0
    
    latest = rows[0]["close"]
    
    if len(rows) >= 21:
        old = rows[20]["close"]
    else:
        old = rows[-1]["close"]
    
    if latest is None or old is None or old == 0:
        return 50.0
    
    # DXY 下跌 = 利好风险资产 = 流动性宽松
    dxy_change = (latest - old) / old * 100
    
    # DXY 跌 5% = 80分, 0% = 50分, 涨 5% = 20分
    score = 50 - dxy_change * 6
    return max(0, min(100, score))


def _calc_china_relative(config: dict) -> float:
    """计算中国资产相对强度得分。"""
    from database import models
    
    # 获取科创50 vs 纳斯达克
    conn = models.get_db()
    
    star_rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = 'STAR50' ORDER BY date DESC LIMIT 22
    """).fetchall()
    
    ndx_rows = conn.execute("""
        SELECT date, close FROM global_market_daily 
        WHERE symbol = 'NDX' ORDER BY date DESC LIMIT 22
    """).fetchall()
    
    conn.close()
    
    if len(star_rows) < 2 or len(ndx_rows) < 2:
        return 50.0
    
    # 计算科创50 20日涨幅
    star_latest = star_rows[0]["close"]
    star_old = star_rows[min(20, len(star_rows)-1)]["close"] if len(star_rows) > 1 else None
    
    # 计算纳斯达克 20日涨幅
    ndx_latest = ndx_rows[0]["close"]
    ndx_old = ndx_rows[min(20, len(ndx_rows)-1)]["close"] if len(ndx_rows) > 1 else None
    
    if not all([star_latest, star_old, ndx_latest, ndx_old]):
        return 50.0
    
    star_return = (star_latest - star_old) / star_old * 100
    ndx_return = (ndx_latest - ndx_old) / ndx_old * 100
    
    # 超额收益
    excess = star_return - ndx_return
    
    # 超额 10% = 80分, 0% = 50分, -10% = 20分
    score = 50 + excess * 3
    return max(0, min(100, score))


def _generate_analysis(risk: float, tech: float, liquidity: float, china: float, stage: str) -> str:
    """生成分析文本。"""
    parts = []
    
    if risk >= 70:
        parts.append("全球风险偏好提升，资金流向高风险资产")
    elif risk >= 50:
        parts.append("全球风险偏好中性")
    else:
        parts.append("全球风险偏好下降，资金避险情绪升温")
    
    if tech >= 70:
        parts.append("科技周期上行，半导体等科技板块领涨")
    elif tech >= 50:
        parts.append("科技周期中性")
    else:
        parts.append("科技周期下行")
    
    if liquidity >= 70:
        parts.append("流动性宽松，利好成长股")
    elif liquidity >= 50:
        parts.append("流动性中性")
    else:
        parts.append("流动性收紧，利空高估值资产")
    
    if china >= 70:
        parts.append("中国资产相对全球表现强势")
    elif china >= 50:
        parts.append("中国资产相对表现中性")
    else:
        parts.append("中国资产相对表现弱势")
    
    return "；".join(parts) + "。"


def save_score_to_json(score: dict, output_path: Path):
    """保存评分到JSON。"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(score, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    score = calc_global_score()
    
    output = Path(__file__).parent.parent / "output" / "global_score.json"
    save_score_to_json(score, output)
    
    print("Global Score:")
    print(f"  Total: {score['total_score']}")
    print(f"  Stage: {score['stage']}")
    print(f"  Risk Appetite: {score['risk_appetite']}")
    print(f"  Tech Cycle: {score['tech_cycle']}")
    print(f"  Liquidity: {score['liquidity']}")
    print(f"  China Relative: {score['china_relative']}")
    print(f"  Analysis: {score['analysis']}")
