# -*- coding: utf-8 -*-
"""
asset_intelligence/tests/test_protocol.py —— AIP 核心单元测试（Phase 1.8）

覆盖：
  - AssetIntelligence 序列化 / 反序列化
  - confidence_label / clamp_confidence / clamp_score
  - derive_trend_from_stage / derive_trend_from_slope
  - validator 五项校验 + 自动 clamp + 非空补默认
  - run_protocol_health 聚合
  - 空壳资产工厂（cash / skeleton）通过校验

运行：
  cd backend
  python -m pytest asset_intelligence/tests/test_protocol.py -q
  或
  python asset_intelligence/tests/test_protocol.py
"""
from __future__ import annotations

import os
import sys
import datetime

# 允许直接运行（脚本方式）
_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from asset_intelligence.protocol import (
    ASSET_CLASSES,
    AssetIntelligence,
    confidence_label,
    clamp_confidence,
    clamp_score,
    derive_trend_from_stage,
    derive_trend_from_slope,
    make_cash_hold,
    make_skeleton,
)
from asset_intelligence.validator import (
    validate,
    validate_and_clean,
    run_protocol_health,
)


def _sample(**kw) -> AssetIntelligence:
    base = dict(
        asset_class="commodity", symbol="AU0", name="沪金", state="上行-避险",
        score=62.0, trend="up", drivers=["宏观:DXY走弱"], risks=["宏观:DXY反弹"],
        confidence=0.72,
    )
    base.update(kw)
    return AssetIntelligence(**base)


# ─────────────────────────────────────────────────────────────
# 序列化
# ─────────────────────────────────────────────────────────────
def test_to_dict_roundtrip():
    ai = _sample()
    d = ai.to_dict()
    assert d["asset_class"] == "commodity"
    assert d["symbol"] == "AU0"
    assert isinstance(d["score"], float)
    assert isinstance(d["confidence"], float)
    ai2 = AssetIntelligence.from_dict(d)
    assert ai2.symbol == ai.symbol
    assert ai2.trend == ai.trend
    assert ai2.drivers == ai.drivers


def test_from_dict_missing_optional_defaults():
    ai = AssetIntelligence.from_dict({"asset_class": "commodity", "symbol": "X",
                                      "name": "n", "state": "s", "score": 1, "trend": "up"})
    assert ai.drivers == []
    assert ai.risks == []
    assert ai.confidence == 0.0
    assert ai.detail == {}


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────
def test_confidence_label():
    assert confidence_label(0.9) == "高"
    assert confidence_label(0.5) == "中"
    assert confidence_label(0.1) == "低"


def test_clamp_confidence():
    assert clamp_confidence(1.5) == 1.0
    assert clamp_confidence(-0.2) == 0.0
    assert clamp_confidence("abc") == 0.0
    assert clamp_confidence(0.4) == 0.4


def test_clamp_score():
    assert clamp_score(120) == 100.0
    assert clamp_score(-5) == 0.0
    assert clamp_score("x") == 50.0


def test_derive_trend_from_stage():
    assert derive_trend_from_stage("上涨趋势") == "up"
    assert derive_trend_from_stage("下跌趋势") == "down"
    assert derive_trend_from_stage("震荡整理") == "sideways"
    assert derive_trend_from_stage("未知") == "sideways"


def test_derive_trend_from_slope():
    assert derive_trend_from_slope(0.5) == "up"
    assert derive_trend_from_slope(-0.5) == "down"
    assert derive_trend_from_slope(0.1) == "sideways"
    assert derive_trend_from_slope("bad") == "sideways"


# ─────────────────────────────────────────────────────────────
# 校验
# ─────────────────────────────────────────────────────────────
def test_validate_clean_pass():
    ai = _sample()
    assert validate(ai) == []
    cleaned, issues = validate_and_clean(ai)
    assert issues == []
    assert cleaned["score"] == 62.0
    assert cleaned["confidence"] == 0.72


def test_validate_clamps_out_of_range():
    ai = _sample(score=140, confidence=2.0)
    cleaned, issues = validate_and_clean(ai)
    assert cleaned["score"] == 100.0
    assert cleaned["confidence"] == 1.0
    assert any("score 越界" in i for i in issues)
    assert any("confidence 越界" in i for i in issues)


def test_validate_empty_drivers_risks():
    ai = _sample(drivers=[], risks=[])
    cleaned, issues = validate_and_clean(ai)
    assert cleaned["drivers"] == ["数据不足，信号待验证"]
    assert cleaned["risks"] == ["数据不足，信号待验证"]
    assert any("drivers 为空" in i for i in issues)
    assert any("risks 为空" in i for i in issues)


def test_validate_illegal_asset_class():
    ai = _sample(asset_class="magic")
    issues = validate(ai)
    assert any("asset_class 非法" in i for i in issues)


def test_validate_illegal_trend():
    ai = _sample(trend="sidewayz")
    cleaned, issues = validate_and_clean(ai)
    assert cleaned["trend"] == "sideways"   # 降级修正，不拒绝
    assert any("trend 非法" in i for i in issues)


def test_run_protocol_health_all_pass():
    sigs = [_sample(), _sample(symbol="CU0", state="上行-周期"),
            _sample(symbol="SC0", state="震荡-供给")]
    rep = run_protocol_health(sigs)
    assert rep["overall"] == "PASS"
    assert rep["n_signals"] == 3
    for c in rep["checks"].values():
        assert c["ok"] is True


def test_run_protocol_health_detects_fail():
    bad = _sample(asset_class="magic", score=999, confidence=5, drivers=[], risks=[])
    rep = run_protocol_health([bad])
    assert rep["overall"] in ("WARN", "FAIL")
    assert rep["checks"]["asset_class_valid"]["fail"] == 1
    assert rep["checks"]["score_range"]["fail"] == 1


# ─────────────────────────────────────────────────────────────
# 空壳资产注册
# ─────────────────────────────────────────────────────────────
def test_cash_hold_valid():
    cash = make_cash_hold()
    assert cash.asset_class == "cash"
    assert cash.state == "持有"
    assert validate(cash) == []


def test_skeleton_valid_and_flagged():
    for ac in ("bond", "etf", "crypto", "fx"):
        sk = make_skeleton(ac, f"{ac.upper()}_X", ac)
        assert validate(sk) == []          # 通过校验，但明确未启用
        assert sk.detail.get("enabled") is False


def test_skeleton_rejects_bad_class():
    try:
        make_skeleton("magic", "X", "x")
        assert False, "应抛 ValueError"
    except ValueError:
        pass


if __name__ == "__main__":
    # 极简 runner（无需 pytest 也能验证）
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:  # noqa
            print(f"  ❌ {t.__name__} 异常: {e}")
    print(f"\n=== {passed}/{len(tests)} 通过 ===")
    sys.exit(0 if passed == len(tests) else 1)
