"""观察清单模块。

管理重点观察股票，自动生成观察名单，检查触发/失效条件。
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
# 观察清单管理
# =============================================================================

def add_to_watchlist(code: str, name: str, sector: str, reason: str,
                     trigger: str, invalidation: str, target: float = 0,
                     stop_loss: float = 0, notes: str = "") -> int:
    """添加股票到观察清单。
    
    Returns:
        记录ID
    """
    conn = models.get_db()
    now = datetime.now(BEIJING).strftime("%Y-%m-%d")
    
    cursor = conn.execute("""
        INSERT INTO watchlist (code, name, sector, added_date, watch_reason,
                               trigger_condition, invalidation_condition,
                               target_price, stop_loss, status, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "watching", ?, ?, ?)
    """, (code, name, sector, now, reason, trigger, invalidation,
          target, stop_loss, notes, time.time(), time.time()))
    
    conn.commit()
    record_id = cursor.lastrowid
    conn.close()
    
    return record_id


def remove_from_watchlist(code: str) -> bool:
    """从观察清单移除。"""
    conn = models.get_db()
    conn.execute("DELETE FROM watchlist WHERE code = ? AND status = 'watching'", (code,))
    conn.commit()
    conn.close()
    return True


def update_watchlist_status(code: str, status: str, notes: str = ""):
    """更新观察清单状态。"""
    conn = models.get_db()
    conn.execute("""
        UPDATE watchlist SET status = ?, notes = ?, updated_at = ?
        WHERE code = ? AND status = 'watching'
    """, (status, notes, time.time(), code))
    conn.commit()
    conn.close()


def get_watchlist(status: str = "watching") -> list[dict]:
    """获取观察清单。"""
    conn = models.get_db()
    
    if status == "all":
        rows = conn.execute("SELECT * FROM watchlist ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
    
    conn.close()
    return [dict(r) for r in rows]


# =============================================================================
# 自动生成观察名单
# =============================================================================

def auto_generate_watchlist(date: str = None) -> list[dict]:
    """基于规则自动生成观察名单。
    
    规则：
    1. 潜在龙头：板块内成交额前3 + 未连板
    2. 板块轮动：板块成交额占比突然上升
    3. 强势整理：上涨后横盘3天 + 缩量
    4. 突破在即：逼近20日高点 + 量能积蓄
    
    Returns:
        新增的观察条目列表
    """
    if date is None:
        date = datetime.now(BEIJING).strftime("%Y-%m-%d")
    
    added = []
    
    # 规则1: 潜在龙头
    potential_leaders = _find_potential_leaders(date)
    for stock in potential_leaders:
        record_id = add_to_watchlist(
            code=stock["code"],
            name=stock["name"],
            sector=stock.get("sector", ""),
            reason="潜在龙头",
            trigger=f"板块内成交额第{stock.get('sector_rank', 1)} + 未连板",
            invalidation="板块退出TOP5或连板高度>5",
            target=stock.get("close", 0) * 1.15,
            stop_loss=stock.get("close", 0) * 0.93,
            notes=f"板块{stock.get('sector', '')}成交额前3",
        )
        added.append({**stock, "id": record_id, "rule": "potential_leader"})
    
    # 规则2: 板块轮动
    sector_rotations = _find_sector_rotation(date)
    for stock in sector_rotations:
        record_id = add_to_watchlist(
            code=stock["code"],
            name=stock["name"],
            sector=stock.get("sector", ""),
            reason="板块轮动",
            trigger=f"板块成交额占比上升至{stock.get('amount_ratio', 0)*100:.2f}%",
            invalidation="板块成交额占比连续2日下降",
            target=stock.get("close", 0) * 1.10,
            stop_loss=stock.get("close", 0) * 0.93,
            notes=f"板块{stock.get('sector', '')}资金流入",
        )
        added.append({**stock, "id": record_id, "rule": "sector_rotation"})
    
    # 规则3: 强势整理
    consolidations = _find_consolidation(date)
    for stock in consolidations:
        record_id = add_to_watchlist(
            code=stock["code"],
            name=stock["name"],
            sector=stock.get("sector", ""),
            reason="强势整理",
            trigger=f"横盘{stock.get('consolidation_days', 3)}天 + 缩量",
            invalidation="跌破整理区间下沿",
            target=stock.get("close", 0) * 1.12,
            stop_loss=stock.get("close", 0) * 0.93,
            notes=f"横盘整理{stock.get('consolidation_days', 3)}天",
        )
        added.append({**stock, "id": record_id, "rule": "consolidation"})
    
    # 规则4: 突破在即
    breakouts = _find_imminent_breakout(date)
    for stock in breakouts:
        record_id = add_to_watchlist(
            code=stock["code"],
            name=stock["name"],
            sector=stock.get("sector", ""),
            reason="突破在即",
            trigger=f"逼近20日高点（距高点{stock.get('distance_to_high', 0)*100:.1f}%）",
            invalidation="跌破20日均线",
            target=stock.get("high_20d", 0) * 1.05,
            stop_loss=stock.get("close", 0) * 0.93,
            notes=f"距20日高点{stock.get('distance_to_high', 0)*100:.1f}%",
        )
        added.append({**stock, "id": record_id, "rule": "imminent_breakout"})
    
    return added


def _find_potential_leaders(date: str) -> list[dict]:
    """寻找潜在龙头：板块内成交额前3 + 未连板。"""
    stocks = models.get_stock_daily_by_date(date)
    leaders = []
    
    # 按板块分组
    sector_stocks: dict[str, list[dict]] = {}
    for stock in stocks:
        sector = stock.get("sector", "")
        if sector not in sector_stocks:
            sector_stocks[sector] = []
        sector_stocks[sector].append(stock)
    
    for sector, stocks_in_sector in sector_stocks.items():
        # 按成交额排序
        sorted_stocks = sorted(stocks_in_sector, key=lambda x: x.get("amount", 0), reverse=True)
        
        # 取前3
        for i, stock in enumerate(sorted_stocks[:3]):
            # 排除已连板的
            if stock.get("change_pct", 0) < 9.5:
                stock["sector_rank"] = i + 1
                leaders.append(stock)
    
    return leaders


def _find_sector_rotation(date: str) -> list[dict]:
    """寻找板块轮动：板块成交额占比突然上升。"""
    # 获取当前板块数据
    sectors = models.get_sector_daily_by_date(date)
    
    # 筛选成交额占比上升的
    rotation_sectors = []
    for sector in sectors:
        history = models.get_sector_daily(sector["sector_name"], 3)
        if len(history) >= 2:
            current_ratio = sector.get("amount_ratio", 0) or 0
            prev_ratio = history[1].get("amount_ratio", 0) or 0 if len(history) > 1 else 0
            
            if current_ratio > prev_ratio * 1.3 and current_ratio > 0.02:
                rotation_sectors.append(sector["sector_name"])
    
    # 获取这些板块的龙头股
    stocks = models.get_stock_daily_by_date(date)
    result = []
    
    for stock in stocks:
        if stock.get("sector", "") in rotation_sectors:
            if stock.get("change_pct", 0) > 2:
                result.append(stock)
    
    return result[:10]  # 限制数量


def _find_consolidation(date: str) -> list[dict]:
    """寻找强势整理：上涨后横盘3天 + 缩量。"""
    stocks = models.get_stock_daily_by_date(date)
    result = []
    
    for stock in stocks:
        code = stock.get("code", "")
        history = models.get_stock_daily(code, 10)
        
        if len(history) < 5:
            continue
        
        # 检查是否横盘（涨跌幅在±3%以内）
        recent = history[:5]
        changes = [h.get("change_pct", 0) or 0 for h in recent]
        
        if all(abs(c) < 3 for c in changes):
            # 检查是否缩量
            volumes = [h.get("volume", 0) or 0 for h in recent]
            if len(volumes) >= 3 and volumes[0] < volumes[-1] * 0.7:
                stock["consolidation_days"] = 5
                result.append(stock)
    
    return result[:10]


def _find_imminent_breakout(date: str) -> list[dict]:
    """寻找突破在即：逼近20日高点 + 量能积蓄。"""
    stocks = models.get_stock_daily_by_date(date)
    result = []
    
    for stock in stocks:
        high_20d = stock.get("high_20d")
        close = stock.get("close", 0)
        
        if high_20d and close > 0:
            distance = (high_20d - close) / close
            
            # 距高点5%以内
            if 0 < distance < 0.05:
                stock["distance_to_high"] = distance
                result.append(stock)
    
    return result[:10]


# =============================================================================
# 触发/失效检查
# =============================================================================

def check_triggers(date: str = None) -> dict:
    """检查观察清单的触发/失效条件。
    
    Returns:
        {"triggered": list, "invalidated": list, "still_watching": list}
    """
    if date is None:
        date = datetime.now(BEIJING).strftime("%Y-%m-%d")
    
    watchlist = get_watchlist("watching")
    
    triggered = []
    invalidated = []
    still_watching = []
    
    for item in watchlist:
        code = item.get("code", "")
        stock = models.get_stock_by_code_and_date(code, date)
        
        if not stock:
            still_watching.append(item)
            continue
        
        close = stock.get("close", 0)
        target = item.get("target_price", 0)
        stop = item.get("stop_loss", 0)
        
        # 检查触发
        if target > 0 and close >= target:
            triggered.append({**item, "trigger_price": close, "reason": f"达到目标价{target}"})
            update_watchlist_status(code, "triggered", f"触发于{date}，价格{close}")
        elif stop > 0 and close <= stop:
            invalidated.append({**item, "trigger_price": close, "reason": f"跌破止损价{stop}"})
            update_watchlist_status(code, "invalidated", f"止损于{date}，价格{close}")
        else:
            still_watching.append(item)
    
    return {
        "triggered": triggered,
        "invalidated": invalidated,
        "still_watching": still_watching,
    }


# =============================================================================
# 汇总报告
# =============================================================================

def generate_watchlist_report(date: str = None) -> dict:
    """生成观察清单报告。
    
    Returns:
        {
            "date": str,
            "watchlist": list,
            "triggered": list,
            "invalidated": list,
            "summary": str
        }
    """
    if date is None:
        date = datetime.now(BEIJING).strftime("%Y-%m-%d")
    
    watchlist = get_watchlist("watching")
    triggers = check_triggers(date)
    
    report = {
        "date": date,
        "watchlist": watchlist,
        "triggered": triggers["triggered"],
        "invalidated": triggers["invalidated"],
        "summary": f"观察中{len(triggers['still_watching'])}只，触发{len(triggers['triggered'])}只，失效{len(triggers['invalidated'])}只",
    }
    
    return report


import time

if __name__ == "__main__":
    report = generate_watchlist_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
