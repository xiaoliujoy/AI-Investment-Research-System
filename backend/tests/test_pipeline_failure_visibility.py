"""P0-A5 故障注入测试：验证「宁可失败，也绝不悄悄产出错误结果」。

覆盖三条关：
  1. daily_collect 在关键步（完整性校验）失败时返回 critical_ok=False，
     退出码决策必须非零（复刻 __main__ 逻辑）。
  2. run_daily 在关键步 step1 失败时 fail-fast：中断后续步骤，不重写
     brain_report.json / decision_tree.json（不生成新 brain），不推送。
  3. 即便有人单独调用 push_daily（15:30 automation / --memo-only），
     cio_agent._load_data() 会因 stale-date 保护抛 StaleCacheError，
     使 push_daily 以非零退出——旧缓存绝不被渲染成当日备忘录推送。

设计原则：纯内存 monkeypatch，不碰生产数据、不联网。
"""
import os
import sys
import json

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import daily_collect
import run_daily
from brain import cio_agent


@pytest.fixture
def patch_freshness(monkeypatch):
    """让 run_daily.main() 不触发真实的 freshness 矩阵写库。"""
    monkeypatch.setattr(run_daily, "_build_freshness", lambda write=False: {"health": "TEST"})


def test_daily_collect_exit_nonzero_on_incomplete(monkeypatch):
    """故障注入 ①：目标交易日无数据 → 完整性校验失败 → 退出码必须非零。"""
    # 指向真实无数据日期（market_daily 空壳已清，该日 stock_daily 0 行）
    monkeypatch.setattr(daily_collect, "_target_trade_date", lambda: "1990-12-19")
    # 让 quotes 兜底直接失效（避免真实联网），确保 critical 步失败
    monkeypatch.setattr(
        daily_collect, "ensure_individual_quotes",
        lambda: {"step": "quotes_fallback", "ok": False, "rc": 1, "note": "FAULT-INJECT"},
    )
    # P1-B3 · B3-F8：daily_collect._run() 用 subprocess 拉起子脚本，
    # 子进程不加载 pytest conftest，因此**不受 conftest 生产库隔离守卫保护**
    # （进程边界是 monkeypatch 类隔离的天然盲区）。实测它会连
    # backend/database/vibe_research.db 并创建空库。这里一并打桩，
    # 保证本测试 100% 进程内、零 DB 触碰。
    def _no_subprocess(name, script):
        return {"step": name, "ok": False, "rc": -1, "elapsed_s": 0.0,
                "stderr_tail": "FAULT-INJECT: subprocess disabled in test"}

    monkeypatch.setattr(daily_collect, "_run", _no_subprocess)

    log = daily_collect.collect()

    assert log["critical_ok"] is False, "完整性校验失败必须使 critical_ok=False"
    assert log["overall_ok"] is False

    # 复刻 daily_collect.__main__ 的退出码决策
    critical_ok = log.get("critical_ok", log["overall_ok"])
    exit_code = 0 if (critical_ok and not (False and log.get("steps"))) else 1
    assert exit_code == 1, "daily_collect 在关键步失败时必须 rc=1（旧逻辑恒 rc=0 是 08-31 事故根因）"


def test_run_daily_aborts_on_critical_failure(monkeypatch, patch_freshness):
    """故障注入 ②：step1 采集失败 → run_daily fail-fast，不生成新 brain / 不推送。"""
    calls = []

    def fake_run(script, retries=0):
        calls.append(script)
        if script == "daily_collect.py":
            return {"ok": False, "returncode": 1, "secs": 0.1,
                    "tail": "FAULT-INJECT", "attempt": 1}
        return {"ok": True, "returncode": 0, "secs": 0.1, "tail": "", "attempt": 1}

    monkeypatch.setattr(run_daily, "run_script", fake_run)

    bp = os.path.join(run_daily.OUT, "brain_report.json")
    tp = os.path.join(run_daily.OUT, "decision_tree.json")
    mtime_brain_before = os.path.getmtime(bp) if os.path.exists(bp) else None
    mtime_tree_before = os.path.getmtime(tp) if os.path.exists(tp) else None

    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no-push"])
    # run_daily.main() 在 critical 失败后应以非零退出码终止（正确行为，调度可感知）
    with pytest.raises(SystemExit) as exc:
        run_daily.main()
    assert exc.value.code == 1, "关键步失败后 run_daily 必须 sys.exit(1)"

    # (a) 中断发生在 step1，后续关键步全部未执行
    assert "daily_collect.py" in calls
    assert "decision_tree.py" not in calls, "step1 失败后不应再跑决策树"
    assert "run_brain_report.py" not in calls, "step1 失败后不应再生成 brain"
    assert "notify/push_daily.py" not in calls, "step1 失败后绝不应推送"

    # (b) brain_report.json / decision_tree.json 未被重写（旧缓存保留，不是被当新数据）
    mtime_brain_after = os.path.getmtime(bp) if os.path.exists(bp) else None
    mtime_tree_after = os.path.getmtime(tp) if os.path.exists(tp) else None
    assert mtime_brain_before is not None and mtime_brain_after == mtime_brain_before, \
        "brain_report.json 不应被重写（否则旧数据会被覆盖成缺数据的空壳）"
    assert mtime_tree_before is not None and mtime_tree_after == mtime_tree_before, \
        "decision_tree.json 不应被重写"

    # (c) 即便单独调用 push_daily，stale-date 保护也会拒（produce 抛 StaleCacheError）
    old_td = json.load(open(bp, encoding="utf-8")).get("trade_date")
    monkeypatch.setattr(cio_agent, "_report_date", lambda: "2099-01-01")
    with pytest.raises(cio_agent.StaleCacheError):
        cio_agent._load_data()
    # 还原，避免影响其它测试
    monkeypatch.setattr(cio_agent, "_report_date",
                        __import__("decision_tree", fromlist=["report_date"]).report_date)
