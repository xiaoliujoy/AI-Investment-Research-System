"""评分引擎 — 市场/板块/龙头评分。

所有权重和阈值从 scoring_config.yaml 读取，代码中不硬编码。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent.parent / "strategy" / "scoring_config.yaml"
OUTPUT_DIR = Path(__file__).parent / "strategy" / "output"


def load_config() -> dict:
    """加载评分配置。"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()


# ---------------------------------------------------------------------------
# 通用评分工具
# ---------------------------------------------------------------------------

def score_from_thresholds(value: Optional[float], thresholds: list[dict]) -> float:
    """根据阈值列表计算分数。
    
    thresholds 格式: [{threshold: x, score: y}, ...]
    按 threshold 降序排列，返回第一个 value >= threshold 的 score。
    """
    if value is None:
        return 0
    
    for item in thresholds:
        if value >= item["threshold"]:
            return item["score"]
    
    return 0


def score_from_range(value: Optional[float], min_val: float, max_val: float, 
                    min_score: float = 0, max_score: float = 100) -> float:
    """线性插值计算分数。"""
    if value is None:
        return 0
    
    if value <= min_val:
        return min_score
    if value >= max_val:
        return max_score
    
    ratio = (value - min_val) / (max_val - min_val)
    return min_score + ratio * (max_score - min_score)


def weighted_score(factors: dict[str, float], weights: dict[str, float]) -> float:
    """加权求和。"""
    total = 0
    for key, weight in weights.items():
        total += factors.get(key, 0) * weight
    return round(total, 2)


# ---------------------------------------------------------------------------
# 市场情绪评分
# ---------------------------------------------------------------------------

def calc_market_score(market_data: dict) -> dict:
    """计算市场情绪评分。
    
    Args:
        market_data: 市场数据，包含:
            - total_amount: 两市成交额（亿元）
            - amount_change_rate: 成交额变化率
            - up_count: 上涨家数
            - down_count: 下跌家数
            - zt_count: 涨停数
            - dt_count: 跌停数
            - seal_rate: 封板率
            - break_rate: 炸板率
            - max_boards: 最高连板
            - lianban_count: 连板数量
            - promotion_rate: 晋级率
            - active_ratio: 活跃度
            - yesterday_zt_avg_pct: 昨日涨停股平均涨幅
            - yesterday_zt_win_rate: 昨日涨停股上涨比例
    
    Returns:
        {
            "score": 总分,
            "stage": 阶段,
            "factors": {各因子得分},
            "details": {各指标原始值}
        }
    """
    cfg = CONFIG["market_score"]
    weights = cfg["weights"]
    
    # 提取数据
    total_amount = market_data.get("total_amount", 0)
    change_rate = market_data.get("amount_change_rate")
    up = market_data.get("up_count", 0)
    down = market_data.get("down_count", 0)
    zt = market_data.get("zt_count", 0)
    dt = market_data.get("dt_count", 0)
    seal_rate = market_data.get("seal_rate", 0)
    break_rate = market_data.get("break_rate", 0)
    max_boards = market_data.get("max_boards", 0)
    lianban_count = market_data.get("lianban_count", 0)
    promotion_rate = market_data.get("promotion_rate", 0)
    active_ratio = market_data.get("active_ratio", 0)
    yzt_avg_pct = market_data.get("yesterday_zt_avg_pct", 0)
    yzt_win_rate = market_data.get("yesterday_zt_win_rate", 0)
    
    # 计算各因子
    # 1. 成交额因子
    amount_score = 0
    if total_amount:
        for item in cfg["amount"]["total_amount"]:
            if total_amount >= item["threshold"]:
                amount_score = item["score"]
                break
    
    amount_chg_score = 0
    if change_rate is not None:
        for item in cfg["amount"]["change_rate"]:
            if change_rate >= item["threshold"]:
                amount_chg_score = item["score"]
                break
    
    amount_factor = amount_score + amount_chg_score
    
    # 2. 赚钱效应因子
    ad_ratio = up / max(down, 1)
    ad_score = score_from_thresholds(ad_ratio, cfg["profit"]["ad_ratio"])
    
    zt_dt_ratio = zt / max(dt, 1)
    zt_dt_score = score_from_thresholds(zt_dt_ratio, cfg["profit"]["zt_dt_ratio"])
    
    seal_score = seal_rate * cfg["profit"]["seal_rate_max"]
    
    profit_factor = ad_score + zt_dt_score + seal_score
    
    # 3. 连板高度因子
    height_score = score_from_thresholds(max_boards, cfg["height"]["max_boards"])
    lianban_score = score_from_thresholds(lianban_count, cfg["height"]["lianban_count"])
    promotion_score = (promotion_rate or 0) * cfg["height"]["promotion_rate_max"]
    
    height_factor = height_score + lianban_score + promotion_score
    
    # 4. 资金活跃度因子
    activity_score = score_from_thresholds(active_ratio, cfg["activity"]["active_ratio"])
    # 资金集中度（从成交额前20占比估算）
    concentration = market_data.get("concentration", 0.15)
    conc_score = score_from_thresholds(concentration, cfg["activity"]["concentration"])
    
    activity_factor = activity_score + conc_score
    
    # 5. 昨日涨停表现因子
    avg_pct_score = score_from_thresholds(yzt_avg_pct, cfg["continuation"]["avg_pct"])
    win_rate_score = score_from_thresholds(yzt_win_rate, cfg["continuation"]["win_rate"])
    
    continuation_factor = avg_pct_score + win_rate_score
    
    # 加权总分
    factors = {
        "amount_factor": amount_factor,
        "profit_factor": profit_factor,
        "height_factor": height_factor,
        "activity_factor": activity_factor,
        "continuation_factor": continuation_factor,
    }
    
    total_score = weighted_score(factors, weights)
    
    # 判定阶段
    stage = _determine_stage(total_score, market_data, cfg["stage"])
    
    return {
        "score": total_score,
        "stage": stage,
        "factors": factors,
        "details": {
            "total_amount": total_amount,
            "amount_change_rate": change_rate,
            "ad_ratio": round(ad_ratio, 3),
            "zt_dt_ratio": round(zt_dt_ratio, 3),
            "seal_rate": seal_rate,
            "max_boards": max_boards,
            "lianban_count": lianban_count,
            "active_ratio": active_ratio,
        }
    }


def _determine_stage(score: float, data: dict, stage_cfg: dict) -> str:
    """判定市场阶段。"""
    # 基于分数 + 辅助条件
    if score >= 70:
        return "高潮期"
    elif score >= 50:
        # 检查是否在分歧（炸板率高）
        if data.get("break_rate", 0) > 0.4:
            return "分歧期"
        return "加速期"
    elif score >= 35:
        # 检查是否在修复
        if data.get("amount_change_rate", 0) < 0:
            return "修复期"
        return "发酵期"
    elif score >= 20:
        return "启动期"
    else:
        return "退潮期"


# ---------------------------------------------------------------------------
# 板块热度评分
# ---------------------------------------------------------------------------

def calc_sector_score(sector_data: dict, context: dict = None) -> dict:
    """计算板块热度评分。
    
    Args:
        sector_data: 板块数据，包含:
            - name: 板块名称
            - amount: 成交额（亿元）
            - amount_ratio: 占全市场比例
            - amount_change_rate: 成交额变化率
            - change_pct: 涨跌幅
            - up_count: 上涨数量
            - down_count: 下跌数量
            - zt_count: 涨停数量
            - total_firms: 公司总数
            - leader_pct: 龙头涨幅
            - leader_turnover: 龙头成交额
            - leader_board: 龙头连板高度
            - leader_rps: 龙头RPS
            - days_in_top10: 近5日前10次数
            - consecutive_days: 连续上榜天数
    
    Returns:
        {
            "name": 板块名,
            "score": 总分,
            "tier": 梯队,
            "factors": {各因子得分}
        }
    """
    cfg = CONFIG["sector_score"]
    weights = cfg["weights"]
    
    # 提取数据
    amount_ratio = sector_data.get("amount_ratio", 0) or 0
    amount_change_rate = sector_data.get("amount_change_rate")
    change_pct = sector_data.get("change_pct", 0) or 0
    zt_count = sector_data.get("zt_count", 0) or 0
    total_firms = sector_data.get("total_firms", 1) or 1
    leader_pct = sector_data.get("leader_pct", 0) or 0
    leader_turnover = sector_data.get("leader_turnover", 0) or 0
    leader_board = sector_data.get("leader_board", 0) or 0
    leader_rps = sector_data.get("leader_rps", 0) or 0
    days_in_top10 = sector_data.get("days_in_top10", 0) or 0
    consecutive_days = sector_data.get("consecutive_days", 0) or 0
    
    # 1. 成交额占比因子
    conc_score = score_from_thresholds(amount_ratio, cfg["amount_concentration"])
    
    # 2. 成交额增速因子
    mom_score = score_from_thresholds(amount_change_rate, cfg["amount_momentum"]) if amount_change_rate is not None else 30
    
    # 3. 涨停数量因子
    zt_score = score_from_thresholds(zt_count, cfg["limitup"]["zt_count"])
    zt_firms_ratio = zt_count / max(total_firms, 1)
    zt_firms_score = score_from_thresholds(zt_firms_ratio, cfg["limitup"]["zt_firms_ratio"])
    cm20_count = sector_data.get("cm20_count", 0) or 0
    cm20_score = score_from_thresholds(cm20_count, cfg["limitup"]["cm20_count"])
    
    limitup_factor = zt_score + zt_firms_score + cm20_score
    
    # 4. 涨幅因子
    gain_score = score_from_thresholds(change_pct, cfg["gain"]["sector_pct"])
    weighted_pct = sector_data.get("weighted_pct", change_pct)
    weighted_pct_score = score_from_thresholds(weighted_pct, cfg["gain"]["weighted_pct"])
    
    gain_factor = gain_score + weighted_pct_score
    
    # 5. 持续性因子
    freq_score = score_from_thresholds(days_in_top10, cfg["duration"]["days_in_top10"])
    con_score = score_from_thresholds(consecutive_days, cfg["duration"]["consecutive_days"])
    
    duration_factor = freq_score + con_score
    
    # 6. 龙头强度因子
    leader_pct_score = score_from_thresholds(leader_pct, cfg["leader_strength"]["leader_pct"])
    leader_turnover_score = score_from_thresholds(leader_turnover / 1e8, cfg["leader_strength"]["leader_turnover"])
    leader_board_score = score_from_thresholds(leader_board, cfg["leader_strength"]["leader_board"])
    leader_rps_score = score_from_thresholds(leader_rps, cfg["leader_strength"]["leader_rps"])
    
    leader_factor = leader_pct_score + leader_turnover_score + leader_board_score + leader_rps_score
    
    # 加权总分
    factors = {
        "amount_concentration": conc_score,
        "amount_momentum": mom_score,
        "limitup": limitup_factor,
        "gain": gain_factor,
        "duration": duration_factor,
        "leader_strength": leader_factor,
    }
    
    total_score = weighted_score(factors, weights)
    
    # 梯队
    tier = _determine_tier(total_score, cfg["tier"])
    
    return {
        "name": sector_data.get("name", ""),
        "score": total_score,
        "tier": tier,
        "factors": factors,
    }


def _determine_tier(score: float, tier_cfg: dict) -> str:
    """判定板块梯队。"""
    if score >= tier_cfg["T0"]["min"]:
        return "T0"
    elif score >= tier_cfg["T1"]["min"]:
        return "T1"
    elif score >= tier_cfg["T2"]["min"]:
        return "T2"
    elif score >= tier_cfg["T3"]["min"]:
        return "T3"
    else:
        return "T4"


# ---------------------------------------------------------------------------
# 龙头评分
# ---------------------------------------------------------------------------

def calc_leader_score(stock_data: dict, sector_score: float = 0) -> Optional[dict]:
    """计算龙头评分。
    
    Args:
        stock_data: 个股数据，包含:
            - code: 股票代码
            - name: 股票名称
            - sector: 所属板块
            - amount: 成交额（亿元）
            - turnover_rate: 换手率
            - change_pct: 涨跌幅
            - board_height: 连板高度
            - mcap: 总市值（亿元）
            - amount_rank: 全市场成交额排名
            - sector_rank: 板块内排名
            - rps_20: 20日RPS
            - rps_60: 60日RPS
            - is_first_board: 是否首板
            - is_open_height: 是否打开高度
            - percentile: 板块内涨幅百分位
            - relative_strength: 相对板块强度
            - seal_quality: 封板质量
            - trend_structure: 趋势结构
            - lhm_net_buy: 龙虎榜净买入
            - follower_count: 跟随者数量
    
    Returns:
        None 如果未通过过滤，否则返回评分 dict
    """
    cfg = CONFIG["leader_score"]
    filters = cfg["filters"]
    weights = cfg["weights"]
    
    # 基础过滤
    if stock_data.get("amount", 0) < filters["min_amount"]:
        return None
    if (stock_data.get("turnover_rate", 0) or 0) < filters["min_turnover_rate"]:
        return None
    if sector_score < filters["min_sector_score"]:
        return None
    if stock_data.get("sector_rank", 99) > filters["max_rank_in_sector"]:
        return None
    
    # 提取数据
    amount = stock_data.get("amount", 0)
    sector_amount = stock_data.get("sector_amount", 1)
    amount_ratio = amount / max(sector_amount, 1)
    amount_rank = stock_data.get("amount_rank", 99)
    board_height = stock_data.get("board_height", 0)
    change_pct = stock_data.get("change_pct", 0) or 0
    turnover_rate = stock_data.get("turnover_rate", 0) or 0
    rps_20 = stock_data.get("rps_20", 0) or 0
    rps_60 = stock_data.get("rps_60", 0) or 0
    percentile = stock_data.get("percentile", 0) or 0
    is_first_board = stock_data.get("is_first_board", False)
    is_open_height = stock_data.get("is_open_height", False)
    lhm_net_buy = stock_data.get("lhm_net_buy", 0) or 0
    follower_count = stock_data.get("follower_count", 0) or 0
    
    # 1. 资金因子
    amount_ratio_score = score_from_thresholds(amount_ratio, cfg["capital"]["amount_ratio"])
    amount_rank_score = score_from_thresholds(amount_rank, cfg["capital"]["amount_rank"])
    
    capital_factor = amount_ratio_score + amount_rank_score
    
    # 2. 空间因子
    board_score = score_from_thresholds(board_height, cfg["space"]["board_height"])
    first_board_score = cfg["space"]["first_board_bonus"] if is_first_board else 0
    open_height_score = cfg["space"]["open_height_bonus"] if is_open_height else cfg["space"]["no_open_height_bonus"]
    
    space_factor = board_score + first_board_score + open_height_score
    
    # 3. 强度因子
    pct_score = score_from_thresholds(change_pct, cfg["strength"]["pct"])
    percentile_score = score_from_thresholds(percentile, cfg["strength"]["percentile"])
    
    strength_factor = pct_score + percentile_score
    
    # 4. 质量因子
    quality_cfg = cfg["quality"]["turnover"]
    if turnover_rate >= quality_cfg["healthy_min"] and turnover_rate < quality_cfg["healthy_max"]:
        quality_factor = quality_cfg["healthy_score"]
    elif turnover_rate >= quality_cfg["caution_min"] and turnover_rate < quality_cfg["caution_max"]:
        quality_factor = quality_cfg["caution_score"]
    elif turnover_rate >= quality_cfg["high_min"] and turnover_rate < quality_cfg["high_max"]:
        quality_factor = quality_cfg["high_score"]
    elif turnover_rate >= quality_cfg["danger_threshold"]:
        quality_factor = quality_cfg["danger_score"]
    elif turnover_rate < quality_cfg["inactive_threshold"]:
        quality_factor = quality_cfg["inactive_score"]
    else:
        quality_factor = quality_cfg["caution_score"]
    
    # 5. RPS因子
    rps_20_score = score_from_thresholds(rps_20, cfg["rps"]["rps_20"])
    rps_60_score = score_from_thresholds(rps_60, cfg["rps"]["rps_60"])
    
    rps_factor = rps_20_score + rps_60_score
    
    # 6. 共识因子
    lhm_score = score_from_thresholds(lhm_net_buy, cfg["consensus"]["lhm_net_buy"])
    follower_score = score_from_thresholds(follower_count, cfg["consensus"]["follower_count"])
    
    consensus_factor = lhm_score + follower_score
    
    # 加权总分
    factors = {
        "capital": capital_factor,
        "space": space_factor,
        "strength": strength_factor,
        "quality": quality_factor,
        "rps": rps_factor,
        "consensus": consensus_factor,
    }
    
    total_score = weighted_score(factors, weights)
    
    # 龙头类型
    category = _determine_category(total_score, stock_data, cfg["category"])
    
    return {
        "code": stock_data.get("code", ""),
        "name": stock_data.get("name", ""),
        "sector": stock_data.get("sector", ""),
        "score": total_score,
        "category": category,
        "factors": factors,
        "passed_filter": True,
    }


def _determine_category(score: float, data: dict, cat_cfg: dict) -> str:
    """判定龙头类型。"""
    if score >= cat_cfg["绝对龙头"]["min"] and data.get("board_height", 0) >= 4:
        return "绝对龙头"
    elif score >= cat_cfg["趋势龙头"]["min"] and data.get("rps_20", 0) > 80 and data.get("board_height", 0) == 0:
        return "趋势龙头"
    elif score >= cat_cfg["核心龙头"]["min"] and data.get("board_height", 0) >= 2:
        return "核心龙头"
    elif score >= cat_cfg["次龙"]["min"]:
        return "次龙"
    else:
        return "跟风"


# ---------------------------------------------------------------------------
# 批量评分 + JSON 输出
# ---------------------------------------------------------------------------

def score_all(market_data: dict, sectors_data: list[dict], 
              leaders_data: list[dict]) -> dict:
    """执行全量评分并输出 JSON。
    
    Returns:
        {
            "market_score": {...},
            "sector_scores": [...],
            "leader_scores": [...],
            "timestamp": "..."
        }
    """
    now = datetime.now(timezone(timedelta(hours=8)))
    
    # 1. 市场评分
    market_result = calc_market_score(market_data)
    
    # 2. 板块评分
    sector_results = []
    for sector in sectors_data:
        result = calc_sector_score(sector)
        sector_results.append(result)
    
    # 排序并添加排名
    sector_results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(sector_results, 1):
        r["rank"] = i
    
    # 3. 龙头评分
    leader_results = []
    for stock in leaders_data:
        # 获取该股票所属板块的评分
        sector_score = 0
        for sr in sector_results:
            if sr["name"] == stock.get("sector", ""):
                sector_score = sr["score"]
                break
        
        result = calc_leader_score(stock, sector_score)
        if result:
            leader_results.append(result)
    
    # 排序并添加排名
    leader_results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(leader_results, 1):
        r["rank"] = i
    
    output = {
        "market_score": market_result,
        "sector_scores": sector_results,
        "leader_scores": leader_results,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    return output


def save_scores(output: dict, output_dir: Path = OUTPUT_DIR) -> dict:
    """保存评分结果到 JSON 文件。
    
    Returns:
        {"market_score": path, "sector_scores": path, "leader_scores": path}
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    paths = {}
    
    # 市场评分
    market_path = output_dir / "market_score.json"
    with open(market_path, "w", encoding="utf-8") as f:
        json.dump(output["market_score"], f, ensure_ascii=False, indent=2)
    paths["market_score"] = str(market_path)
    
    # 板块评分
    sector_path = output_dir / "sector_score.json"
    with open(sector_path, "w", encoding="utf-8") as f:
        json.dump(output["sector_scores"], f, ensure_ascii=False, indent=2)
    paths["sector_scores"] = str(sector_path)
    
    # 龙头评分
    leader_path = output_dir / "leader_score.json"
    with open(leader_path, "w", encoding="utf-8") as f:
        json.dump(output["leader_scores"], f, ensure_ascii=False, indent=2)
    paths["leader_scores"] = str(leader_path)
    
    return paths


