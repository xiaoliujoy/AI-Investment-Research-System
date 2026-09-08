# -*- coding: utf-8 -*-
"""T1 #2 Patch P1 — Regression Guard for the sentiment hard-veto.

目的：把「信号层英文枚举 被 决策层用中文 state 比较」这类 silent failure
变成测试明确失败。

召回入口：investment_committee.decide() 的 can_buy 决策（纯函数，无 I/O）。
本测试只 import 该纯函数用于单元测试，**不**导入 run_daily / cio_agent /
push_daily 等生产运行链，**不**写任何 DB。

Case 1 目标历史样本恢复保护（4 真实漏判日 → NO + hard_no 含"情绪退潮/冰点"）
Case 2 边界状态隔离（仅 bearish 触发；neutral_bearish != bearish 防二次 bug）
Case 3 历史 Replay 稳定性（4 目标 YES→NO；其余 58 样本 100% 不变）
Case 4 Enum Contract Guard（direction 必须是合法英文枚举，中文/typo 立即失败）

预期：P1 阶段生产代码未修 → Case 1/2/3 目标断言 RED（精确捕获未修复 bug）；
      Case 4 当前即可 GREEN（现有样本 direction 已是合法英文枚举）。
      P2 修复 :243 后，全部 GREEN。
"""
import os
import sys
import json
import glob
import importlib.util

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)                       # .../backend
COMMITTEE_DIR = os.path.join(BACKEND, "committee")
DB_PATH = os.path.join(BACKEND, "database", "vibe_research.db")

# ── 加载真实 decide() 纯函数（importlib，避免 sys.path 污染 / 命名冲突）──
_SPEC = importlib.util.spec_from_file_location(
    "ic_sentiment_contract_test", os.path.join(COMMITTEE_DIR, "investment_committee.py")
)
_ic_mod = importlib.util.module_from_spec(_SPEC)
# 模块体只含 os/sys + 常量定义，无 DB 连接；安全执行
_spec_loader_exec = getattr(_SPEC, "loader", None)
assert _spec_loader_exec is not None
_spec_loader_exec.exec_module(_ic_mod)
decide = _ic_mod.decide

# ── 契约常量 ──
VALID_SENTIMENT_DIRECTIONS = {
    "bullish",
    "bearish",
    "neutral_bullish",
    "neutral_bearish",
}

# 4 个真实历史漏判日（冰点/退潮，bull>bear 票且 comp<70，无其他 hard_no）
TARGET_DATES = {
    "2026-07-16": "冰点",
    "2026-07-20": "冰点",
    "2026-08-06": "退潮",
    "2026-08-21": "退潮",
}

SENTIMENT_VETO_MSG = "情绪退潮/冰点"


# ── DB 零写入守卫（沿用 T1 #3 Gate C.2 纪律）──
@pytest.fixture(autouse=True)
def _guard_no_db_write():
    before = os.path.getmtime(DB_PATH) if os.path.exists(DB_PATH) else None
    yield
    after = os.path.getmtime(DB_PATH) if os.path.exists(DB_PATH) else None
    assert before == after, "生产库 mtime 改变——测试意外写入了 DB！"


# ── 样本加载（复用 _t1_2_gateB_replay.py 的路径与结构）──
def _iter_sample_files():
    candidates = [
        os.path.join(BACKEND, "output", "brain_report.json"),
        *sorted(glob.glob(os.path.join(BACKEND, "output", "archive", "brain_report_*.json"))),
        *sorted(glob.glob(os.path.join(BACKEND, "tests", "fixtures", "golden_master", "brain_report_*.json"))),
    ]
    for p in candidates:
        if os.path.exists(p):
            yield p


def _date_key(p):
    name = os.path.basename(p).replace("brain_report_", "").replace(".json", "")
    return name or "latest"


def load_samples():
    """返回 {date_key: (results, stored_can_buy)}，archive 优先于 golden_master 镜像。"""
    samples = {}
    golden = {}
    for p in _iter_sample_files():
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        res = data.get("results") or {}
        if not res:
            continue
        stored = (data.get("decision") or {}).get("can_buy")
        if stored is None:
            continue
        key = _date_key(p)
        entry = (res, stored)
        if "golden_master" in p.replace("\\", "/"):
            golden.setdefault(key, entry)
        else:
            samples[key] = entry
    for k, v in golden.items():
        samples.setdefault(k, v)
    return samples


def _mk_results(sentiment_direction, other_direction="neutral_bullish"):
    """构造合成 results：除 sentiment 外所有投票层用 other_direction，
    使投票基线中性；从而 can_buy 是否 NO 只由 sentiment 强否决决定。"""
    layers = ["FLOW", "L1", "L2", "L3", "L3_5", "L4", "L5", "sentiment", "fundamental"]
    results = {}
    for L in layers:
        if L == "sentiment":
            results[L] = {"signal": {"direction": sentiment_direction, "state": "X"}}
        elif L == "L7":
            results[L] = {"raw": {"composite": 60, "position": "30-50%"}}
        else:
            results[L] = {"signal": {"direction": other_direction}}
    return results


# ───────────────────────────────────────────────────────────
# Case 1：目标历史样本恢复保护
# ───────────────────────────────────────────────────────────
def test_case1_target_dates_recover_veto():
    samples = load_samples()
    assert samples, "未加载到任何 brain_report 样本——路径或数据缺失"
    for date, state in TARGET_DATES.items():
        assert date in samples, f"目标样本缺失: {date}"
        res, stored = samples[date]
        dec = decide(res)
        assert dec["can_buy"] == "NO", (
            f"{date}({state}) 应被情绪强否决→NO，但 decide() 返回 {dec['can_buy']} "
            f"(stored={stored})"
        )
        assert SENTIMENT_VETO_MSG in dec["hard_no"], (
            f"{date}({state}) hard_no 应含「{SENTIMENT_VETO_MSG}」，实际: {dec['hard_no']}"
        )


# ───────────────────────────────────────────────────────────
# Case 2：边界状态隔离（防止 `if "bearish" in direction:` 二次 bug）
# ───────────────────────────────────────────────────────────
def test_case2_boundary_isolation():
    # 静态守卫：枚举区分
    assert "neutral_bearish" != "bearish"

    # 只有英文 bearish 触发否决；其它方向绝不触发
    bearish_dec = decide(_mk_results("bearish"))
    assert bearish_dec["can_buy"] == "NO"
    assert SENTIMENT_VETO_MSG in bearish_dec["hard_no"]

    for direction in ("neutral_bearish", "neutral_bullish", "bullish"):
        dec = decide(_mk_results(direction))
        assert SENTIMENT_VETO_MSG not in dec["hard_no"], (
            f"direction={direction} 不应触发情绪强否决，但 hard_no={dec['hard_no']}"
        )


# ───────────────────────────────────────────────────────────
# Case 3：历史 Replay 稳定性
# ───────────────────────────────────────────────────────────
def test_case3_replay_stability():
    samples = load_samples()
    assert samples, "未加载到任何 brain_report 样本"
    flipped = 0
    for date, (res, stored) in samples.items():
        dec = decide(res)
        if date in TARGET_DATES:
            assert dec["can_buy"] == "NO", (
                f"目标样本 {date} 应 YES→NO，但 decide()={dec['can_buy']} (stored={stored})"
            )
            flipped += 1
        else:
            assert dec["can_buy"] == stored, (
                f"非目标样本 {date} 不应被改变：decide()={dec['can_buy']} 但 stored={stored}"
            )
    assert flipped == len(TARGET_DATES), (
        f"目标翻转数应为 {len(TARGET_DATES)}，实际 {flipped}"
    )


# ───────────────────────────────────────────────────────────
# Case 4：Enum Contract Guard（中文 state / typo 立即失败）
# ───────────────────────────────────────────────────────────
def test_case4_enum_contract():
    samples = load_samples()
    assert samples, "未加载到任何 brain_report 样本"
    for date, (res, _stored) in samples.items():
        direction = (
            (res.get("sentiment") or {}).get("signal", {}).get("direction")
        )
        assert direction in VALID_SENTIMENT_DIRECTIONS, (
            f"{date}: sentiment.direction={direction!r} 不是合法英文枚举 "
            f"{sorted(VALID_SENTIMENT_DIRECTIONS)}（中文 state 混入 direction？）"
        )
