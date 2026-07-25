# -*- coding: utf-8 -*-
import sys, types
sys.path.insert(0, "notify")
import os2_report as o
import learning_center as lc

def NS(**kw):
    return types.SimpleNamespace(**kw)

def make_memo(can_buy="YES", pf_pass=6, pf_total=6, base="YES", ic_acc=None,
              n_rep=0, health_failed=False, health_summary="ok"):
    return NS(
        can_buy=can_buy,
        position_pct="50%",
        preflight={"passed_count": pf_pass, "total_count": pf_total,
                   "calibration": {"base_verdict": base}, "verdict": base, "error": None},
        learning={"ic_accuracy": ic_acc, "n_replayed": n_rep},
        data_health={"failed": (["个股资金流"] if health_failed else []),
                     "summary": health_summary},
        migration={"thesis": "资金回流主板", "rotation": {"in_top": ["半导体", "算力"]},
                   "avoid": ["高位题材"], "what_to_do": "盯住资金主线", "focus": "主线"},
        thesis=NS(headline="资金回流主板"),
        trading_plan=NS(opportunities=[{"name": "中芯国际"}], no_opportunity=False),
        debate={"hard_no": ["退市风险"]},
        action_list=[{"time": "10:00", "action": "确认主板放量"}],
    )

print("=== TEST 1: health OK, strong → YES ===")
m = make_memo(health_failed=False)
d = o.resolve_decision(m, {"composite": 90})
print("  final:", d["final"], "| health_failed:", d["health_failed"],
      "| market_state:", d["market_state"])
assert d["final"] == "YES", "expected YES"
assert d["health_failed"] is False

print("=== TEST 2: health FAILED → forced NO (data integrity veto) ===")
m = make_memo(can_buy="YES", health_failed=True, health_summary="个股资金流 60% < 80%")
d = o.resolve_decision(m, {"composite": 95})
print("  final:", d["final"], "| health_failed:", d["health_failed"],
      "| market_state:", d["market_state"])
print("  chain tail:", d["chain"][-1])
assert d["final"] == "NO", "health fail must force NO"
assert d["market_state"] == "数据异常 · 禁止交易"

print("=== TEST 3: Exec Summary labels align with NO (观察方向 / 禁止) ===")
m = make_memo(health_failed=True)
score = {"composite": 95}
d = o.resolve_decision(m, score)
es = o.compute_executive_summary(m, score, d)
print("  do_label:", es["do_label"], "| avoid_label:", es["avoid_label"],
      "| trade_status:", es["trade_status"])
assert es["do_label"] == "🔍 观察方向", es["do_label"]
assert es["avoid_label"] == "🚫 禁止", es["avoid_label"]
assert es["trade_status"] == "交易状态：不交易"

print("=== TEST 4: Exec Summary labels align with YES (可以做 / 不要做) ===")
m = make_memo(health_failed=False)
d = o.resolve_decision(m, {"composite": 95})
es = o.compute_executive_summary(m, {"composite": 95}, d)
print("  do_label:", es["do_label"], "| avoid_label:", es["avoid_label"])
assert es["do_label"] == "✅ 可以做"
assert es["avoid_label"] == "❌ 不要做"

print("=== TEST 5: Learning suggested_weights 3-tier ===")
# suggested_weights 内部用 replay()->dimension_accuracy() 算 total_samples，
# 这里 monkeypatch dimension_accuracy 注入可控的样本量来校验三档闸门逻辑。
# 注：cap_pct 仅内部用于夹权，不进返回 dict；三档通过 applied + note + 实际权重漂移体现。
def fake_da(n_total):
    per = max(1, n_total // 6)
    return {f"L{i}": {"n": per, "acc": 60 if i % 2 else 40} for i in range(1, 7)}

orig = lc.dimension_accuracy
lc.dimension_accuracy = lambda preds: fake_da(20)
sw1 = lc.suggested_weights(preds=[{"x": 1}])
lc.dimension_accuracy = lambda preds: fake_da(60)
sw2 = lc.suggested_weights(preds=[{"x": 1}])
lc.dimension_accuracy = lambda preds: fake_da(150)
sw3 = lc.suggested_weights(preds=[{"x": 1}])
lc.dimension_accuracy = orig
print("  n=20  -> applied:", sw1["applied"], "| note:", sw1["note"][:30])
print("  n=60  -> applied:", sw2["applied"], "| note:", sw2["note"][:45])
print("  n=150 -> applied:", sw3["applied"], "| note:", sw3["note"][:30])
assert sw1["applied"] is False, "n<30 should NOT apply (only record)"
assert "样本不足" in sw1["note"]
assert sw2["applied"] is True, "30-100 should apply"
assert "±5" in sw2["note"], "30-100 should mention ±5% cap"
assert sw3["applied"] is True, ">=100 should apply"
assert "自动校准" in sw3["note"], ">=100 should mention auto-calibrate"

print("\nALL GATE + LABEL + WEIGHT TESTS PASSED")
