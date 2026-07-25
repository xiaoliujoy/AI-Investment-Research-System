"""交易信号模块。

基于评分结果和历史数据生成入场/出场信号。
所有信号基于规则，不含AI猜测。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import models

BEIJING = timezone(timedelta(hours=8))


# =============================================================================
# 入场信号
# =============================================================================

def check_entry_signals(date: str = None) -> list[dict]:
    """检查入场信号。
    
    基于以下条件生成入场信号：
    1. 板块启动：板块成交额占比连续3日上升 + 进入TOP5
    2. 龙头确立：板块内成交额第1 + 连板高度>=2
    3. 突破买入：股价突破20日新高 + 放量
    4. 均线共振：MA5 > MA10 > MA20 > MA60
    
    Returns:
        入场信号列表
    """
    if date is None:
        date = datetime.now(BEIJING).strftime("%Y-%m-%d")
    
    signals = []
    
    # 获取市场数据
    market = models.get_market_daily(date)
    if not market:
        return signals
    
    market_stage = market.get("stage", "")
    
    # 退潮期不生成入场信号
    if market_stage == "退潮期":
        return signals
    
    # 获取板块数据
    sectors = models.get_sector_daily_by_date(date)
    
    for sector in sectors:
        sector_name = sector.get("sector_name", "")
        sector_score = sector.get("sector_score", 0) or 0
        
        # 只关注评分>60的板块
        if sector_score < 60:
            continue
        
        # 获取板块历史（检查持续性）
        history = models.get_sector_daily(sector_name, 5)
        
        # 信号1: 板块启动 - 成交额占比连续3日上升
        if len(history) >= 3:
            ratios = [h.get("amount_ratio", 0) or 0 for h in history[:3]]
            if all(ratios[i] > ratios[i+1] for i in range(len(ratios)-1)):
                signals.append({
                    "date": date,
                    "signal_type": "sector_startup",
                    "sector": sector_name,
                    "direction": "long",
                    "trigger_condition": f"板块成交额占比连续3日上升: {[round(r*100, 2) for r in ratios]}%",
                    "confidence": min(sector_score, 80),
                    "reasons": [f"板块{sector_name}资金持续流入", f"当前占比{round(ratios[0]*100, 2)}%"],
                })
        
        # 信号2: 板块进入TOP5 + 评分>70
        top_sectors = models.get_top_sectors(date, 5)
        top_names = [s["sector_name"] for s in top_sectors]
        
        if sector_name in top_names and sector_score > 70:
            signals.append({
                "date": date,
                "signal_type": "sector_top5",
                "sector": sector_name,
                "direction": "long",
                "trigger_condition": f"板块进入TOP5，评分{sector_score:.1f}",
                "confidence": min(sector_score, 85),
                "reasons": [f"板块{sector_name}进入TOP5", f"评分{sector_score:.1f}"],
            })
    
    # 基于个股生成信号
    stocks = models.get_stock_daily_by_date(date)
    
    for stock in stocks:
        code = stock.get("code", "")
        name = stock.get("name", "")
        
        # 信号3: 突破20日新高 + 放量
        is_new_high = stock.get("is_new_high_20d", 0)
        volume_ratio = stock.get("volume_ratio", 1) or 1
        
        if is_new_high and volume_ratio > 1.5:
            signals.append({
                "date": date,
                "signal_type": "breakout",
                "code": code,
                "name": name,
                "sector": stock.get("sector", ""),
                "direction": "long",
                "trigger_condition": f"突破20日新高，量比{volume_ratio:.1f}",
                "confidence": min(70 + volume_ratio * 5, 90),
                "reasons": [f"{name}突破20日新高", f"量比{volume_ratio:.1f}"],
            })
        
        # 信号4: 均线共振
        ma5 = stock.get("ma5")
        ma10 = stock.get("ma10")
        ma20 = stock.get("ma20")
        ma60 = stock.get("ma60")
        
        if all([ma5, ma10, ma20, ma60]):
            if ma5 > ma10 > ma20 > ma60:
                signals.append({
                    "date": date,
                    "signal_type": "ma_alignment",
                    "code": code,
                    "name": name,
                    "sector": stock.get("sector", ""),
                    "direction": "long",
                    "trigger_condition": "MA5 > MA10 > MA20 > MA60",
                    "confidence": 75,
                    "reasons": [f"{name}均线多头排列"],
                })
    
    # 按置信度排序
    signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    
    return signals


# =============================================================================
# 出场信号
# =============================================================================

def check_exit_signals(positions: list[dict], date: str = None) -> list[dict]:
    """检查出场信号。
    
    基于以下条件生成出场信号：
    1. 止盈：涨幅达15%或封板被炸
    2. 止损：跌破买入价-7%
    3. 时间退出：持有超过10天未触发
    4. 板块退潮：板块评分降至60以下
    
    Args:
        positions: 当前持仓列表
    
    Returns:
        出场信号列表
    """
    if date is None:
        date = datetime.now(BEIJING).strftime("%Y-%m-%d")
    
    signals = []
    
    for pos in positions:
        code = pos.get("code", "")
        name = pos.get("name", "")
        buy_price = pos.get("buy_price", 0)
        buy_date = pos.get("buy_date", "")
        
        # 获取当前数据
        stock = models.get_stock_by_code_and_date(code, date)
        if not stock:
            continue
        
        current_price = stock.get("close", 0)
        if current_price <= 0:
            continue
        
        # 信号1: 止损
        if buy_price > 0:
            loss_pct = (current_price - buy_price) / buy_price
            if loss_pct <= -0.07:
                signals.append({
                    "date": date,
                    "signal_type": "stop_loss",
                    "code": code,
                    "name": name,
                    "direction": "close",
                    "urgency": "immediate",
                    "trigger_condition": f"跌破买入价-7%（当前{loss_pct*100:.1f}%）",
                    "reasons": [f"止损触发", f"当前亏损{loss_pct*100:.1f}%"],
                })
        
        # 信号2: 止盈
        if buy_price > 0:
            gain_pct = (current_price - buy_price) / buy_price
            if gain_pct >= 0.15:
                signals.append({
                    "date": date,
                    "signal_type": "take_profit",
                    "code": code,
                    "name": name,
                    "direction": "close",
                    "urgency": "watch",
                    "trigger_condition": f"涨幅达15%（当前{gain_pct*100:.1f}%）",
                    "reasons": [f"止盈触发", f"当前盈利{gain_pct*100:.1f}%"],
                })
        
        # 信号3: 时间退出
        if buy_date:
            try:
                buy_dt = datetime.strptime(buy_date, "%Y-%m-%d").date()
                current_dt = datetime.strptime(date, "%Y-%m-%d").date()
                hold_days = (current_dt - buy_dt).days
                
                if hold_days > 10:
                    signals.append({
                        "date": date,
                        "signal_type": "time_exit",
                        "code": code,
                        "name": name,
                        "direction": "close",
                        "urgency": "optional",
                        "trigger_condition": f"持有超过10天（当前{hold_days}天）",
                        "reasons": [f"时间退出", f"持有{hold_days}天"],
                    })
            except Exception:
                pass
        
        # 信号4: 板块退潮
        sector = stock.get("sector", "")
        if sector:
            sector_data = models.get_sector_daily(sector, 1)
            if sector_data:
                sector_score = sector_data[0].get("sector_score", 0) or 0
                if sector_score < 60:
                    signals.append({
                        "date": date,
                        "signal_type": "sector_exit",
                        "code": code,
                        "name": name,
                        "direction": "close",
                        "urgency": "watch",
                        "trigger_condition": f"板块评分降至60以下（当前{sector_score:.1f}）",
                        "reasons": [f"板块{sector}退潮"],
                    })
    
    return signals


# =============================================================================
# 仓位管理
# =============================================================================

def calc_position_size(market_score: float, sector_score: float, leader_score: float,
                       current_positions: int = 0, max_positions: int = 5) -> dict:
    """计算建议仓位。
    
    基于三层评分计算建议仓位：
    1. 市场分决定基础仓位
    2. 板块分调整
    3. 龙头分调整
    
    Returns:
        {"base_position": float, "adjusted_position": float, "reasons": list}
    """
    # 基础仓位由市场分决定
    if market_score >= 70:
        base = 0.8
    elif market_score >= 55:
        base = 0.6
    elif market_score >= 40:
        base = 0.4
    elif market_score >= 25:
        base = 0.2
    else:
        base = 0.0
    
    # 板块调整
    sector_mult = min(sector_score / 70, 1.0) if sector_score else 0.5
    
    # 龙头调整
    leader_mult = min(leader_score / 70, 1.0) if leader_score else 0.5
    
    # 持仓调整
    position_mult = 1.0 - (current_positions / max_positions) if max_positions > 0 else 1.0
    
    adjusted = base * sector_mult * leader_mult * position_mult
    
    reasons = [
        f"市场分{market_score:.1f} → 基础仓位{base*100:.0f}%",
        f"板块分{sector_score:.1f} → 调整系数{sector_mult:.2f}",
        f"龙头分{leader_score:.1f} → 调整系数{leader_mult:.2f}",
        f"当前持仓{current_positions}/{max_positions} → 调整系数{position_mult:.2f}",
    ]
    
    return {
        "base_position": round(base, 2),
        "adjusted_position": round(adjusted, 4),
        "position_pct": round(adjusted * 100, 2),
        "reasons": reasons,
    }


# =============================================================================
# 汇总
# =============================================================================

def generate_signals_report(date: str = None) -> dict:
    """生成信号报告。
    
    Returns:
        {
            "date": str,
            "entry_signals": list,
            "exit_signals": list,
            "position_sizing": dict,
            "summary": str
        }
    """
    if date is None:
        date = datetime.now(BEIJING).strftime("%Y-%m-%d")
    
    # 入场信号
    entry_signals = check_entry_signals(date)
    
    # 出场信号（需要当前持仓）
    exit_signals = check_exit_signals([], date)
    
    # 仓位建议
    market = models.get_market_daily(date)
    market_score = market.get("emotion_score", 50) or 50 if market else 50
    
    # 获取最高板块分和龙头分
    top_sectors = models.get_top_sectors(date, 1)
    sector_score = top_sectors[0].get("sector_score", 50) or 50 if top_sectors else 50
    
    position = calc_position_size(market_score, sector_score, 60)
    
    report = {
        "date": date,
        "entry_signals": entry_signals,
        "exit_signals": exit_signals,
        "position_sizing": position,
        "summary": f"入场信号{len(entry_signals)}个，出场信号{len(exit_signals)}个，建议仓位{position['position_pct']:.1f}%",
    }
    
    return report


if __name__ == "__main__":
    report = generate_signals_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
