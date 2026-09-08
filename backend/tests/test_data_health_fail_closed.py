"""df4ac04 Regression Guard —— 锁定 Data Health 的 fail-closed 行为契约。

背景（T3 Release Gate A.3.2 · 2026-09-08）
------------------------------------------------------------------
`df4ac04` 修复了一个静默失败通道（SF-013）：当 `data_health.check()` 抛异常时，
`cio_agent._build_data_health()` 原本返回 `trade_allowed=True / failed=[] / checks=[]`，
使 OS2 报告渲染出绿色「✅ 数据健康 · 允许交易」徽章 —— 即 **数据完整性层不可用，
却对外表现为健康可交易**。修复后改为 fail-closed。

本测试锁定三条契约（不是覆盖全部逻辑，而是锁死失败语义与状态表达）：

  Test 1  `_build_data_health()` 的失败语义 —— 异常 → 不放行 → failed 可归因 → summary 降级
          （并带反向对照：正常路径不得被误伤，证明是 fail-closed 而非 always-closed）
  Test 2  红态在 HTML 中真实可见 —— 防「后端健康失败 / 报告看起来一切正常」
  Test 3  状态切换正确 —— False 态绝不出绿灯，True 态才出（杜绝静默绿灯回归）

设计原则
------------------------------------------------------------------
* 纯内存 monkeypatch，不碰生产数据、不联网、不写库（autouse 夹具守卫 DB mtime）。
* `render_html` 需要真实数值字段，裸 `InvestmentDecisionMemo()` 会在
  `os2_report.py:904 _render_gold_opportunity` 因缺少 tips 数值而 TypeError。
  故仅打桩这一个与 data_health 无关的版块渲染器；**health 版块保持真实代码路径**。

已知边界（不在本测试范围）
------------------------------------------------------------------
* `data_health` 目前**未接入决策门**：`memo.data_health` 仅被 os2_report 渲染消费，
  `trade_allowed / failed` 不进入 can_buy / hard_no / veto / position_pct
  （见 Gate A.2 F-2）。本测试锁定的是「渲染层不得撒谎」，不是「决策门」。
* `data_health.py:6` docstring 声称「唯一裁决器强制 NO」未实现 —— 属治理缺口 backlog。
"""
import os
import sys
import types

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import notify.os2_report as os2_report
from brain import cio_agent
from brain.cio_agent import InvestmentDecisionMemo


# ── 真实契约文案（2026-09-08 实测确认，勿凭直觉改写）──────────────────
# 注意：用户初稿伪代码中的 "交易禁止" 在代码中并不存在，真实文案为 "禁止交易"。
GREEN_BADGE = "✅ 数据健康 · 允许交易"
RED_BADGE = "⛔ 数据健康未通过 · 禁止交易"
UNAVAILABLE_SUMMARY = "数据健康模块暂不可用"
UNAVAILABLE_FAILED = "数据健康模块不可用"

DB_PATH = os.path.join(BACKEND, "database", "vibe_research.db")


@pytest.fixture(autouse=True)
def _guard_no_db_write():
    """生产库零写入守卫（T1 #3 铁律）：本测试不得改动 vibe_research.db。"""
    before = os.path.getmtime(DB_PATH) if os.path.exists(DB_PATH) else None
    yield
    after = os.path.getmtime(DB_PATH) if os.path.exists(DB_PATH) else None
    assert before == after, "生产库被写入，测试隔离失败"


@pytest.fixture
def _render_html(monkeypatch):
    """返回 render_html，并打桩与 data_health 无关的黄金版块渲染器。

    裸 `InvestmentDecisionMemo()` 在 `os2_report.py:904 _render_gold_opportunity`
    会因 tips 为 None 而 `TypeError: unsupported format string passed to NoneType`。
    打桩它即可渲染；health 版块仍走真实代码，保证断言有意义。
    """
    monkeypatch.setattr(os2_report, "_render_gold_opportunity", lambda memo: "")
    return os2_report.render_html


def _memo(dh: dict) -> InvestmentDecisionMemo:
    """构造最小可用 memo（InvestmentDecisionMemo 全字段 default_factory）。"""
    m = InvestmentDecisionMemo()
    m.data_health = dh
    return m


def _inject_data_health(monkeypatch, check_func):
    """把 sys.modules['data_health'] 换成可控假模块（_build_data_health 内部 from-import）。"""
    fake = types.ModuleType("data_health")
    fake.check = check_func
    monkeypatch.setitem(sys.modules, "data_health", fake)
    return fake


# ══════════════════════════════════════════════════════════════════
# Test 1 —— Data Health fail-closed 本体（失败语义，非展示）
# ══════════════════════════════════════════════════════════════════
def test_build_data_health_fail_closed_on_exception(monkeypatch):
    """契约①：data_health 模块异常 → fail-closed（既不放行，也不是恒 False）。"""

    def _boom():
        raise RuntimeError("BOOM-FAULT-INJECT")

    _inject_data_health(monkeypatch, _boom)
    dh = cio_agent._build_data_health()

    # (a) 失败语义：绝不放行
    assert dh["trade_allowed"] is False, (
        "data_health 不可用时必须 fail-closed；旧实现返回 True 会让报告渲染绿色"
        "「允许交易」徽章（SF-013 静默失败通道）"
    )
    # (b) failed 必须被填充 —— 不可用状态必须可归因，不能是空列表
    assert dh["failed"], "failed 不得为空——不可用状态必须可归因"
    assert UNAVAILABLE_FAILED in dh["failed"]
    # (c) summary 降级文案（调用方 / 报告可见）
    assert dh["summary"] == UNAVAILABLE_SUMMARY
    assert dh["checks"] == []
    # (d) error_detail 仅内部诊断字段
    assert "error_detail" in dh and dh["error_detail"], "应保留内部诊断信息供排查"

    # (e) 反向对照：模块正常时不得被误伤为 False
    #     → 证明实现是 fail-closed，而不是 always-closed（防止过度修复）
    _inject_data_health(monkeypatch, lambda: {
        "trade_date": "2026-09-07", "checks": [], "trade_allowed": True,
        "failed": [], "summary": "数据健康 · 允许交易",
    })
    ok = cio_agent._build_data_health()
    assert ok["trade_allowed"] is True, "正常路径不得被误判为不可用（fail-closed ≠ always-closed）"


# ══════════════════════════════════════════════════════════════════
# Test 2 —— HTML 红态可见
# ══════════════════════════════════════════════════════════════════
def test_degraded_state_visible_in_html(_render_html):
    """契约②：trade_allowed=False → 红徽章 + P0 标记 + summary 在 HTML 中真实可见。"""
    html = _render_html(_memo({
        "trade_date": "2026-09-07", "checks": [],
        "trade_allowed": False,
        "failed": [UNAVAILABLE_FAILED],
        "summary": UNAVAILABLE_SUMMARY,
    }))

    assert RED_BADGE in html, "禁止交易徽章必须渲染（防『后端失败 / 报告看起来正常』）"
    assert ">P0<" in html, "P0 标记必须渲染（不可用 = P0 级）"
    assert UNAVAILABLE_SUMMARY in html, "summary 必须对最终用户可见（df4ac04 新增渲染）"
    assert "hbadge bad" in html, "不可用样式类必须出现"


# ══════════════════════════════════════════════════════════════════
# Test 3 —— 禁止静默绿灯（状态切换正确）
# ══════════════════════════════════════════════════════════════════
def test_no_silent_green_path(_render_html):
    """契约③：False 态绝不出绿灯，True 态才出 —— 证明状态切换正确，而非仅『红色存在』。"""
    html_false = _render_html(_memo({
        "trade_date": "2026-09-07", "checks": [],
        "trade_allowed": False,
        "failed": [UNAVAILABLE_FAILED],
        "summary": UNAVAILABLE_SUMMARY,
    }))
    html_true = _render_html(_memo({
        "trade_date": "2026-09-07", "checks": [],
        "trade_allowed": True,
        "failed": [],
        "summary": "数据健康 · 允许交易",
    }))

    # 核心断言：False 态不得出现绿灯
    assert GREEN_BADGE not in html_false, "静默绿灯：数据不可用却渲染『允许交易』"
    # 正向对照：True 态必须出现绿灯（否则本测试可能空转）
    assert GREEN_BADGE in html_true, (
        "正向对照失效——绿灯文案可能已被改动，需同步更新契约常量后重审"
    )
    # 状态切换确实产生不同输出
    assert html_false != html_true, "False/True 两态渲染结果相同，状态未正确切换"
