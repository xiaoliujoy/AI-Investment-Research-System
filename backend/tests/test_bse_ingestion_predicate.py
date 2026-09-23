"""P0-C Step 4 (Governance R2, 2026-09-11) —— BSE 920-only ingestion predicate 契约测试。

锁定目标（防回归 / 防被「为了方便」改坏）：

  * 当前行情写入资格门 `_is_canonical_quote_code`：
      沪市/深市        → 沿用 universe.is_stock 契约（不重写前缀规则）
      920 前缀         → True（当前 BSE 上市成员，自 2025-10-09 全面切换）
      83/87/874/875/899→ False（NEEQ 挂牌 / 历史旧码 / 待清理，非当前 BSE 上市）
      非股票(ETF/指数/新三板) → False
  * `_audit_ingest` 计数 raw/accepted/rejected/by_exchange，
      且资格层 FAIL-LOUD（accepted 中若出现 market_of=北交所 但非 920 → 抛错）。
  * `_bse_drift_check` 相对规则：baseline(prev=0) / ok / fail，绝不硬编码绝对成员数（对齐 U1）。

设计原则：全部纯函数，**不连 DB、不联网、不写库**，不受 conftest 沙箱重定向影响。
本测试同时覆盖 fill_daily_quotes 与 fill_stock_flow（两脚本 mirror 同一治理门，须保持等价）。
"""
import os
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import fill_daily_quotes as fdq
import fill_stock_flow as fsf


# ── _is_canonical_quote_code：交易所 / 前缀资格 ────────────────────────
@pytest.mark.parametrize("mod", [fdq, fsf])
def test_920_prefix_accepted_as_bse(mod):
    assert mod._is_canonical_quote_code("920001") is True
    assert mod._is_canonical_quote_code("920123") is True   # 芭薇股份（837023→920123）


@pytest.mark.parametrize("mod", [fdq, fsf])
def test_non_920_bse_old_codes_rejected(mod):
    # 83/87 = NEEQ 挂牌 + 历史 BSE 旧代码混合；874/875 = NEEQ 挂牌；899 = 待清理
    for code in ("830799", "870001", "874001", "875001", "899001"):
        assert mod._is_canonical_quote_code(code) is False, code


@pytest.mark.parametrize("mod", [fdq, fsf])
def test_main_board_and_chinext_follow_is_stock(mod):
    # 沪市/深市 → 沿用 universe.is_stock 契约
    assert mod._is_canonical_quote_code("600000") is True   # 沪市主板
    assert mod._is_canonical_quote_code("000001") is True   # 深市主板
    assert mod._is_canonical_quote_code("300750") is True   # 创业板
    assert mod._is_canonical_quote_code("688981") is True   # 科创板


@pytest.mark.parametrize("mod", [fdq, fsf])
def test_non_stock_rejected(mod):
    assert mod._is_canonical_quote_code("159919") is False  # ETF
    assert mod._is_canonical_quote_code("880001") is False  # 通达信板块指数伪代码（88x→其他）
    assert mod._is_canonical_quote_code("430001") is False  # 新三板
    assert mod._is_canonical_quote_code("") is False


# ── _audit_ingest：计数 + FAIL-LOUD ───────────────────────────────────
@pytest.mark.parametrize("mod", [fdq, fsf])
def test_audit_ingest_counts(mod):
    codes = ["600000", "000001", "300750", "688981", "920001",
             "830799", "874001", "159919", "430001"]
    a = mod._audit_ingest(codes)
    assert a["raw"] == 9
    assert a["accepted"] == 5          # 4 主板/创业/科创 + 1 北交所920
    assert a["rejected"] == 4         # 830799/874001/159919/430001
    assert a["by_exchange"]["SSE"] == 2    # 600000 + 688981
    assert a["by_exchange"]["SZSE"] == 2   # 000001 + 300750
    assert a["by_exchange"]["BSE"] == 1    # 920001


@pytest.mark.parametrize("mod", [fdq, fsf])
def test_audit_ingest_fail_loud_on_non_920_bse(mod, monkeypatch):
    # 防御性守卫：若 predicate 回归导致「北交所分类但非 920」被接受，必须 FAIL-LOUD。
    # 通过 monkeypatch 强制一个违规 accepted 项，验证守卫逻辑本身（当前 predicate 下该分支不可达，
    # 故用假 predicate 触发）。market_of("830799")=="北交所" 且非 920 前缀 → 命中。
    def fake_pred(code):
        return True  # 模拟 predicate 回归：一切都被接受
    monkeypatch.setattr(mod, "_is_canonical_quote_code", fake_pred)
    with pytest.raises(RuntimeError, match="FAIL_LOUD"):
        mod._audit_ingest(["830799", "920001"])


# ── _bse_drift_check：相对规则 ────────────────────────────────────────
@pytest.mark.parametrize("mod", [fdq, fsf])
def test_drift_baseline_when_prev_zero(mod):
    status, _ = mod._bse_drift_check(300, 0)
    assert status == "baseline"


@pytest.mark.parametrize("mod", [fdq, fsf])
def test_drift_ok_within_threshold(mod):
    assert mod._bse_drift_check(300, 300)[0] == "ok"   # 0%
    assert mod._bse_drift_check(330, 300)[0] == "ok"   # +10% < 20%
    assert mod._bse_drift_check(270, 300)[0] == "ok"   # -10% < 20%


@pytest.mark.parametrize("mod", [fdq, fsf])
def test_drift_fail_beyond_threshold(mod):
    assert mod._bse_drift_check(400, 300)[0] == "fail"   # +33.3% > 20%
    assert mod._bse_drift_check(200, 300)[0] == "fail"   # -33.3% > 20%
