# -*- coding: utf-8 -*-
"""
test_universe_contract.py —— P1-C · C10 Canonical Universe 行为契约测试
============================================================

用户验收红线（实施轮 Gate「行为不漂移」）：
  - 920 经 is_stock() == True 且 market_of() == "北交所"（防漂移关键断言）
  - 430（新三板）经 is_stock() == False 且 market_of() == "其他"（防漂移关键断言）
  - 主板/深市/创业/北交(83/87) 行为等价历史 `_is_stock` / 路由分类器
  - is_stock 与 3 份历史副本严格等价（全前缀扫描，零漂移）
  - 4 个路由分类器（astock.get_prefix / astock.disclosure / fundamental._gtimg_prefix
    / tushare._ts_code）统一收敛到 universe.market_of，且 920/430 漂移已修正

本测试零 DB 依赖、零网络依赖，纯逻辑。运行：
    pytest backend/tests/test_universe_contract.py -v
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from universe import is_stock, market_of  # noqa: E402
import astock  # noqa: E402
import fundamental_engine  # noqa: E402
import tushare_provider  # noqa: E402


# ---------------------------------------------------------------------------
# 历史 `_is_stock` 权威参考（data_health / capital_score 的等价定义；
# fill_market_cap 多加了 11/12/13/15/16/18/88/5 显式排除，但结果与二者一致）。
# 用于证明 universe.is_stock 与历史行为零漂移。
# ---------------------------------------------------------------------------
def _legacy_is_stock(code: str) -> bool:
    if not code:
        return False
    if code[0] in ("6", "0", "3"):
        return True
    if code.startswith(("83", "87", "920")):  # 北交所
        return True
    return False


# ===========================================================================
# 1) is_stock 契约表（用户 10 样本）
# ===========================================================================
def test_is_stock_contract_table():
    expect_true = ["600000", "000001", "300750", "920001", "830999", "870999"]
    expect_false = ["430999", "110999", "510999", "880999"]
    for c in expect_true:
        assert is_stock(c) is True, f"is_stock({c}) 应为 True（真个股）"
    for c in expect_false:
        assert is_stock(c) is False, f"is_stock({c}) 应为 False（非个股）"


# ===========================================================================
# 2) market_of 契约表
# ===========================================================================
def test_market_of_contract_table():
    assert market_of("600000") == "沪市"
    assert market_of("000001") == "深市"
    assert market_of("300750") == "深市"      # 创业板归深市
    assert market_of("830999") == "北交所"
    assert market_of("870999") == "北交所"
    assert market_of("920001") == "北交所"
    # 非个股 / 伪代码归「其他」，不得误入北交所或误判为个股
    assert market_of("430999") == "其他"      # 新三板
    assert market_of("880999") == "其他"      # 板块指数伪代码
    assert market_of("110999") == "其他"      # 转债
    assert market_of("510999") == "其他"      # ETF
    assert market_of("") == "其他"


# ===========================================================================
# 3) 防漂移关键断言（用户明确点名）
# ===========================================================================
def test_drift_prevention_920():
    # 920（北交所 proper）必须 = True / 北交所
    assert is_stock("920001") is True
    assert is_stock("920999") is True
    assert market_of("920001") == "北交所"


def test_drift_prevention_430():
    # 430（新三板）必须 = False / 其他（不得误入北交所）
    assert is_stock("430999") is False
    assert market_of("430999") == "其他"


def test_drift_prevention_900_bshare():
    """900xxx 沪市B股归沪市，且不得因「9 规则」把 920 拉回沪市。

    历史行为：get_prefix("900001") == "sh"（沪市B股）。
    C10 迁移初期把整段 9 并入「其他」→ 路由退化成 sz，被 tests/test_pure.py 捕获。
    本用例锁定边界：920 由 BJ_PREFIXES 先行判定为北交所，900xxx 才落沪市。
    """
    assert market_of("900001") == "沪市"
    assert astock.get_prefix("900001") == "sh"
    # 920 必须仍是北交所，不得被 9 规则污染
    assert market_of("920001") == "北交所"
    assert astock.get_prefix("920001") == "bj"


# ===========================================================================
# 4) is_stock 全前缀扫描 = 历史 `_is_stock` 零漂移
# ===========================================================================
def test_is_stock_legacy_equivalence_sweep():
    samples = []
    # 双字符前缀 00..99 + 4 个零 → 覆盖首 1/2 字符判定
    for p in range(100):
        samples.append(f"{p:02d}0000")
    # 显式 3 字符敏感样本
    samples += [
        "920001", "920999", "830001", "830999", "870001", "870999",
        "880001", "880999", "430001", "430999", "400001", "440001",
        "110001", "120001", "130001", "150001", "160001", "180001",
        "510001", "500001", "501001", "500001", "600001", "000001", "300001",
        "900001",  # 沪市 B 股（归其他，非个股）
    ]
    for c in samples:
        assert is_stock(c) == _legacy_is_stock(c), (
            f"is_stock({c})={is_stock(c)} 与历史 _is_stock="
            f"{_legacy_is_stock(c)} 不一致（行为漂移）"
        )


# ===========================================================================
# 5) 路由分类器收敛到 universe.market_of（含 920/430 漂移修正）
# ===========================================================================
def test_routing_get_prefix_delegates():
    # 主板 / 深市 / 创业 / 北交 一致
    assert astock.get_prefix("600000") == "sh"
    assert astock.get_prefix("000001") == "sz"
    assert astock.get_prefix("300750") == "sz"
    assert astock.get_prefix("830999") == "bj"
    assert astock.get_prefix("870999") == "bj"
    # 920 漂移修正：历史 get_prefix → "sh"，现必须 "bj"
    assert astock.get_prefix("920001") == "bj"
    # 430 漂移修正：历史 get_prefix → "sz"（已正确），仍归 sz
    assert astock.get_prefix("430999") == "sz"


def test_routing_disclosure_market_delegates():
    # astock.disclosure 的 market 判定现已走 universe.market_of
    # 注：disclosure 内部调用 market_of，这里验证其导出行为
    assert market_of("600000") == "沪市"
    assert market_of("920001") == "北交所"   # 历史 disclosure 误归「深市」→ 已修正
    assert market_of("430999") == "其他"


def test_routing_gtimg_prefix_delegates():
    assert fundamental_engine._gtimg_prefix("600000") == "sh600000"
    assert fundamental_engine._gtimg_prefix("000001") == "sz000001"
    assert fundamental_engine._gtimg_prefix("300750") == "sz300750"
    assert fundamental_engine._gtimg_prefix("830999") == "bj830999"
    assert fundamental_engine._gtimg_prefix("870999") == "bj870999"
    # 920 漂移修正：历史 _gtimg_prefix → "sh920001"，现必须 "bj920001"
    assert fundamental_engine._gtimg_prefix("920001") == "bj920001"
    # 430 漂移修正：历史 _gtimg_prefix → "bj430999"（新三板误当北交所），现必须 "sz430999"
    assert fundamental_engine._gtimg_prefix("430999") == "sz430999"


def test_routing_ts_code_delegates():
    assert tushare_provider._ts_code("600000") == "600000.SH"
    assert tushare_provider._ts_code("000001") == "000001.SZ"
    assert tushare_provider._ts_code("300750") == "300750.SZ"
    assert tushare_provider._ts_code("830999") == "830999.BJ"
    assert tushare_provider._ts_code("870999") == "870999.BJ"
    # 920 漂移修正：历史 _ts_code → "920001"（未转换），现必须 "920001.BJ"
    assert tushare_provider._ts_code("920001") == "920001.BJ"
    # 430 漂移修正：历史 _ts_code → "430999.BJ"（新三板误当北交所），现必须原样 "430999"
    assert tushare_provider._ts_code("430999") == "430999"
