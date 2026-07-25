"""评分引擎 CLI 入口。

用法:
  python -m scoring_engine --run          # 运行评分并输出 JSON
  python -m scoring_engine --test         # 运行单元测试
  python -m scoring_engine --demo         # 使用模拟数据演示
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 确保能导入 backend 模块
sys.path.insert(0, str(Path(__file__).parent))

from scoring_engine import score_all, save_scores, load_config


def run_with_live_data():
    """使用实时数据运行评分。"""
    from market_amount import get_market_amount
    from sector_stat import get_sector_stats
    from leader_candidate import get_leader_candidates
    
    print("正在采集数据...")
    
    # 1. 市场数据
    amount_data = get_market_amount()
    market_data = {
        "total_amount": amount_data["total_amount"],
        "amount_change_rate": amount_data["change_rate"],
        # 以下数据需要从其他接口获取，暂时用估算值
        "up_count": 2000,
        "down_count": 3000,
        "zt_count": 70,
        "dt_count": 15,
        "seal_rate": 0.65,
        "break_rate": 0.35,
        "max_boards": 6,
        "lianban_count": 8,
        "promotion_rate": 0.45,
        "active_ratio": 0.37,
        "yesterday_zt_avg_pct": 2.5,
        "yesterday_zt_win_rate": 0.65,
        "concentration": 0.18,
    }
    
    # 2. 板块数据
    sectors_raw = get_sector_stats()
    sectors_data = []
    for s in sectors_raw:
        sectors_data.append({
            "name": s["name"],
            "amount": s["amount"],
            "amount_ratio": s["amount_ratio"],
            "amount_change_rate": s.get("amount_change_rate"),
            "change_pct": s["change_pct"],
            "up_count": s.get("up_count"),
            "down_count": s.get("down_count"),
            "zt_count": s.get("zt_count"),
            "total_firms": s.get("total_firms"),
            "leader_pct": s["change_pct"],  # 简化：用板块涨幅代替
            "leader_turnover": s["amount"] * 0.3,  # 简化估算
            "leader_board": 2 if s.get("zt_count", 0) > 0 else 0,
            "leader_rps": 60,  # 默认值
            "days_in_top10": 3,  # 默认值
            "consecutive_days": 2,  # 默认值
        })
    
    # 3. 龙头候选数据
    leaders_raw = get_leader_candidates(30)
    leaders_data = []
    for l in leaders_raw:
        leaders_data.append({
            "code": l["code"],
            "name": l["name"],
            "sector": l["sector"],
            "amount": l["amount"] * 1e8,  # 亿元 → 元
            "turnover_rate": (l["turnover_rate"] or 5) / 100,  # % → 小数
            "change_pct": l["change_pct"],
            "board_height": l["board_height"],
            "mcap": l["mcap"],
            "amount_rank": l["amount_rank"],
            "sector_rank": min(l["amount_rank"], 3),  # 简化
            "rps_20": 50,  # 默认值
            "rps_60": 50,
            "is_first_board": l["board_height"] == 1,
            "is_open_height": l["board_height"] >= 5,
            "percentile": 0.85,
            "lhm_net_buy": 0,
            "follower_count": 3,
            "sector_amount": l["amount"] * 1e8 * 3,  # 简化
        })
    
    print("正在评分...")
    result = score_all(market_data, sectors_data, leaders_data)
    
    # 保存
    paths = save_scores(result)
    
    print(f"\n评分完成！")
    print(f"市场评分: {result['market_score']['score']} ({result['market_score']['stage']})")
    print(f"板块数量: {len(result['sector_scores'])}")
    print(f"龙头数量: {len(result['leader_scores'])}")
    print(f"\n输出文件:")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    
    return result


def run_demo():
    """使用模拟数据演示评分。"""
    print("=== 评分引擎演示 ===\n")
    
    # 模拟市场数据
    market_data = {
        "total_amount": 29137,
        "amount_change_rate": 0.10,
        "up_count": 2500,
        "down_count": 2400,
        "zt_count": 75,
        "dt_count": 12,
        "seal_rate": 0.68,
        "break_rate": 0.32,
        "max_boards": 6,
        "lianban_count": 10,
        "promotion_rate": 0.50,
        "active_ratio": 0.40,
        "yesterday_zt_avg_pct": 3.0,
        "yesterday_zt_win_rate": 0.70,
        "concentration": 0.18,
    }
    
    # 模拟板块数据
    sectors_data = [
        {"name": "半导体", "amount": 397, "amount_ratio": 0.06, "amount_change_rate": 0.25,
         "change_pct": 6.5, "up_count": 150, "down_count": 31, "zt_count": 12, "total_firms": 181,
         "leader_pct": 10.0, "leader_turnover": 380, "leader_board": 3, "leader_rps": 85,
         "days_in_top10": 5, "consecutive_days": 4},
        {"name": "通信设备", "amount": 160, "amount_ratio": 0.024, "amount_change_rate": 0.15,
         "change_pct": 2.7, "up_count": 70, "down_count": 21, "zt_count": 5, "total_firms": 91,
         "leader_pct": 5.9, "leader_turnover": 416, "leader_board": 0, "leader_rps": 75,
         "days_in_top10": 4, "consecutive_days": 3},
        {"name": "消费电子", "amount": 71, "amount_ratio": 0.011, "amount_change_rate": 0.10,
         "change_pct": 2.6, "up_count": 60, "down_count": 36, "zt_count": 3, "total_firms": 96,
         "leader_pct": 4.0, "leader_turnover": 100, "leader_board": 0, "leader_rps": 60,
         "days_in_top10": 3, "consecutive_days": 2},
    ]
    
    # 模拟龙头数据
    leaders_data = [
        {"code": "603986", "name": "兆易创新", "sector": "半导体",
         "amount": 380e8, "turnover_rate": 0.088, "change_pct": 10.0,
         "board_height": 3, "mcap": 4656, "amount_rank": 2, "sector_rank": 1,
         "rps_20": 85, "rps_60": 80, "is_first_board": False, "is_open_height": False,
         "percentile": 0.95, "lhm_net_buy": 50000000, "follower_count": 5,
         "sector_amount": 397e8},
        {"code": "300308", "name": "中际旭创", "sector": "通信设备",
         "amount": 416e8, "turnover_rate": 0.032, "change_pct": 5.9,
         "board_height": 0, "mcap": 13262, "amount_rank": 1, "sector_rank": 1,
         "rps_20": 75, "rps_60": 70, "is_first_board": False, "is_open_height": False,
         "percentile": 0.90, "lhm_net_buy": 0, "follower_count": 3,
         "sector_amount": 160e8},
        {"code": "002384", "name": "东山精密", "sector": "元件",
         "amount": 278e8, "turnover_rate": 0.081, "change_pct": 10.0,
         "board_height": 2, "mcap": 4786, "amount_rank": 4, "sector_rank": 1,
         "rps_20": 70, "rps_60": 65, "is_first_board": False, "is_open_height": False,
         "percentile": 0.85, "lhm_net_buy": 0, "follower_count": 2,
         "sector_amount": 69e8},
    ]
    
    result = score_all(market_data, sectors_data, leaders_data)
    
    # 保存
    paths = save_scores(result)
    
    print(f"市场评分: {result['market_score']['score']} ({result['market_score']['stage']})")
    print(f"  因子: {result['market_score']['factors']}")
    print(f"\n板块评分:")
    for s in result['sector_scores']:
        print(f"  #{s['rank']} {s['name']}: {s['score']} ({s['tier']})")
    print(f"\n龙头评分:")
    for l in result['leader_scores']:
        print(f"  #{l['rank']} {l['name']}({l['code']}): {l['score']} ({l['category']})")
    print(f"\n输出文件:")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    
    return result


def main():
    parser = argparse.ArgumentParser(description="评分引擎")
    parser.add_argument("--run", action="store_true", help="使用实时数据运行评分")
    parser.add_argument("--demo", action="store_true", help="使用模拟数据演示")
    parser.add_argument("--test", action="store_true", help="运行单元测试")
    
    args = parser.parse_args()
    
    if args.test:
        import unittest
        from test_scoring import run_tests
        run_tests()
    elif args.run:
        run_with_live_data()
    elif args.demo:
        run_demo()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
