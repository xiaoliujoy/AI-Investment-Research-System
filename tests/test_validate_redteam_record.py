# -*- coding: utf-8 -*-
"""
Red-Team 审查记录结构断言器单元测试
===================================
验证 parse_and_validate_markdown 对 VALID / 结构缺失 两类样本的判定。

运行：python -m unittest tests.test_validate_redteam_record -v
"""
import os
import sys
import unittest

_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from os_layers.validate_redteam_record import parse_and_validate_markdown  # noqa: E402


class TestRedteamRecordStructure(unittest.TestCase):

    def test_valid_record_structure(self):
        sample_md = """
# Red-Team 观察层审查记录
- 日期: 2026-08-22
- Target Memo: output/memo_2026-08-22.html
- Status: VALID

## 一、原始备忘录核心裁决
- 最终裁决: CAUTION (综合评分: 72)
- 建议仓位: 30%
- 主线候选: 半导体 ★★★★☆

## 二、红方攻击点清单
1. 【宏观】SOXX 隔夜重挫 2.8%，海外半导体链情绪承压，备忘录仅以 ETF 净申购作为支撑，低估了开盘抛压。
2. 【资金】领涨核心股连续 2 日缩量，板块内部流动性呈现衰竭迹象，存在假突破风险。

## 三、蓝方抗辩与对冲依据
1. 【针对攻击 1 (规则对冲)】国内半导体 ETF 连续 3 日净流入超 15 亿，且 10:00 盯盘清单已设置"未放量即放弃"的硬条件。
2. 【针对攻击 2 (完全化解)】Capital Score 显示主力资金集中度高达 82 分，缩量属于锁仓特征而非资金撤退，且仓位护栏已收紧至 30%。

## 四、裁判终审评分与判定
- 综合评分: 84.0
- 裁决结论: 维持原裁决 (CAUTION)。蓝方抗辩成立，规则护栏与 10:00 盯盘点有效覆盖了外部情绪传导风险。
- 终审评语: 决策链条整体稳健，仓位已做严格压制。
- 盘中关键观察点: 09:45~10:00 核心龙头分时承接量能是否达到昨日同期 1.2 倍。
        """
        is_valid, errors, metrics = parse_and_validate_markdown(sample_md)
        self.assertTrue(is_valid, f"期望通过，实际错误: {errors}")
        self.assertEqual(metrics["score"], 84.0)
        self.assertGreaterEqual(metrics["red_points_count"], 2)
        self.assertGreaterEqual(metrics["blue_points_count"], 2)
        self.assertFalse(metrics["is_invalid_round"])

    def test_missing_judge_verdict_fails(self):
        malformed_md = """# Red-Team 观察层审查记录
- 日期: 2026-08-22
- Target Memo: output/memo_2026-08-22.html
- Status: VALID

## 二、红方攻击点清单
1. 【宏观】攻击点 A。
2. 【资金】攻击点 B。

## 三、蓝方抗辩与对冲依据
1. 【针对攻击 1 (完全化解)】数据支持。
2. 【针对攻击 2 (部分承认)】数据部分支持。

## 四、裁判终审评分与判定
- 综合评分: 60.0
- 终审评语: 未给出结论，仅描述过程
"""
        is_valid, errors, _ = parse_and_validate_markdown(malformed_md)
        self.assertFalse(is_valid)
        self.assertTrue(any("裁判" in e for e in errors))

    def test_invalid_round_warns_but_passes(self):
        """INVALID_ROUND 占位记录：告警但不判 FAIL（供人工审计）。"""
        placeholder_md = """# Red-Team 观察层审查记录
- 日期: 2026-08-22
- Target Memo: output/memo_2026-08-22.html
- Status: INVALID_ROUND
- 失败原因: 红方二次校验失败

_本记录为 INVALID_ROUND 占位（供人工审计，不进入正式观察视图）。_
"""
        is_valid, errors, metrics = parse_and_validate_markdown(placeholder_md)
        self.assertTrue(is_valid)
        self.assertTrue(metrics["is_invalid_round"])
        self.assertTrue(any(e.startswith("⚠️") for e in errors))


if __name__ == "__main__":
    unittest.main()
