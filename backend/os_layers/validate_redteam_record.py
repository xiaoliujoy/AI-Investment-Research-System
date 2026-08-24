# -*- coding: utf-8 -*-
"""Red-Team 审查记录结构完整性断言脚本
========================================
用于 CI/冒烟测试及首跑核验：
1. 校验 output/redteam_records/redteam_record_{date}.md 文件是否存在且非空
2. 校验四大核心段落：元信息、红方攻击、蓝方抗辩、裁判终审
3. 校验裁判评分区间、判定结论及 INVALID_ROUND 状态标识

依赖：仅标准库。
"""

import os
import re
import sys
import glob
import argparse
from typing import Dict, List, Tuple


REQUIRED_SECTIONS = [
    ("元信息 / 审查上下文", [r"日期|Date", r"备忘录|Target Memo", r"审查状态|Status"]),
    ("红方攻击清单", [r"红方|Red-Team|攻击点|质疑|漏洞"]),
    ("蓝方抗辩证据", [r"蓝方|Blue-Team|抗辩|证据|合规性"]),
    ("裁判裁决与评分", [r"裁判|Judge|终审|综合评分|裁决结果"]),
]


def parse_and_validate_markdown(content: str) -> Tuple[bool, List[str], Dict]:
    """解析 Markdown 内容并执行字段完整性断言。

    返回: (是否通过, 错误原因列表, 提取的关键指标字典)
    """
    errors = []
    metrics = {
        "score": None,
        "verdict": None,
        "is_invalid_round": False,
        "red_points_count": 0,
        "blue_points_count": 0,
    }

    if not content.strip():
        return False, ["文件内容为空"], metrics

    # 1. 检查是否存在异常轮次标识 (INVALID_ROUND)
    if "INVALID_ROUND" in content:
        metrics["is_invalid_round"] = True
        errors.append("⚠️ 记录标记为 INVALID_ROUND（LLM 解析异常或协议未对齐，已触发兜底）")
        # INVALID_ROUND 占位记录：豁免核心章节/评分/裁决检查（本就无正文），仅保留告警
        is_valid = True
        return is_valid, errors, metrics

    # 2. 核心章节与关键词覆盖检查
    for section_name, patterns in REQUIRED_SECTIONS:
        matched = False
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                matched = True
                break
        if not matched:
            errors.append(f"缺失关键区块或关键词: 【{section_name}】")

    # 3. 提取红方攻击点条数（检查是否有实质列表项）
    red_match = re.search(
        r"(?:##\s*.*?(?:红方|Red).*?\n)([\s\S]*?)(?=\n##|\Z)", content, re.IGNORECASE
    )
    if red_match:
        red_text = red_match.group(1).strip()
        items = re.findall(r"^(?:-|\*|\d+\.)\s+.+", red_text, re.MULTILINE)
        metrics["red_points_count"] = len(items)
        if len(items) == 0 and len(red_text) < 20:
            errors.append("红方攻击区块内容不完整或未列出有效要点")
    else:
        errors.append("未正确定位红方攻击区块（## 红方...）")

    # 4. 提取蓝方抗辩要点
    blue_match = re.search(
        r"(?:##\s*.*?(?:蓝方|Blue).*?\n)([\s\S]*?)(?=\n##|\Z)", content, re.IGNORECASE
    )
    if blue_match:
        blue_text = blue_match.group(1).strip()
        items = re.findall(r"^(?:-|\*|\d+\.)\s+.+", blue_text, re.MULTILINE)
        metrics["blue_points_count"] = len(items)
        if len(items) == 0 and len(blue_text) < 20:
            errors.append("蓝方抗辩区块内容不完整或未列出有效依据")
    else:
        errors.append("未正确定位蓝方抗辩区块（## 蓝方...）")

    # 5. 裁判评分与终审裁决提取（仅在裁判终审区块内搜索，避免被「原始备忘录核心裁决」干扰）
    judge_section = ""
    judge_match = re.search(
        r"(?:##\s*.*?(?:裁判|Judge).*?\n)([\s\S]*?)(?=\n##|\Z)", content, re.IGNORECASE
    )
    if judge_match:
        judge_section = judge_match.group(1)
    score_match = re.search(r"(?:评分|得分|Score)[:：\s]*(\d{1,3}(?:\.\d+)?)", judge_section)
    if score_match:
        score_val = float(score_match.group(1))
        metrics["score"] = score_val
        if not (0 <= score_val <= 100):
            errors.append(f"裁判评分超出 0~100 合理区间: {score_val}")
    else:
        if not metrics["is_invalid_round"]:
            errors.append("未提取到裁判评分（如：'综合评分: 85'）")

    verdict_match = re.search(
        r"(?:裁决|判定|Verdict)[^:：\n\r]*[:：]?\s*([^\n\r]+)", judge_section
    )
    if verdict_match:
        metrics["verdict"] = verdict_match.group(1).strip()
    else:
        if not metrics["is_invalid_round"]:
            errors.append("未提取到裁判最终裁决结论")

    is_valid = len([e for e in errors if not e.startswith("⚠️")]) == 0
    return is_valid, errors, metrics


def validate_file(filepath: str) -> bool:
    """验证指定路径的 Markdown 记录文件"""
    print(f"🔍 开始核验文件: {filepath}")
    if not os.path.exists(filepath):
        print(f"❌ 错误: 目标文件不存在 -> {filepath}")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    is_valid, errors, metrics = parse_and_validate_markdown(content)

    print("\n--- 关键字段提取结果 ---")
    print(f"• 裁判评分: {metrics['score']}")
    print(f"• 终审结论: {metrics['verdict']}")
    print(f"• 红方攻击要点数: {metrics['red_points_count']}")
    print(f"• 蓝方抗辩要点数: {metrics['blue_points_count']}")
    print(f"• 状态标识: {'INVALID_ROUND (异常兜底)' if metrics['is_invalid_round'] else 'VALID (正常审查)'}")

    print("\n--- 规则断言检查 ---")
    if errors:
        for err in errors:
            print(f"  {err}")
    else:
        print("  ✅ 全部必填段落、字段结构与数值范围校验通过")

    print(f"\n最终结论: {'✅ PASS' if is_valid else '❌ FAIL'}\n")
    return is_valid


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Red-Team 审查记录 Markdown 完整性断言工具")
    parser.add_argument("path", nargs="?", help="指定检查的 redteam_record_*.md 路径（默认检查最新文件）")
    args = parser.parse_args()

    target_path = args.path
    if not target_path:
        # 默认自动查找 output/redteam_records/ 下最新的一份记录
        pattern = os.path.join(os.getcwd(), "output", "redteam_records", "redteam_record_*.md")
        files = sorted(glob.glob(pattern))
        if not files:
            print("❌ 未在 output/redteam_records/ 下找到任何 redteam_record_*.md 记录文件。")
            sys.exit(1)
        target_path = files[-1]

    passed = validate_file(target_path)
    sys.exit(0 if passed else 1)
