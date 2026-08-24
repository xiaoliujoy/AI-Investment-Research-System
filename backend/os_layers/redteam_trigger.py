# -*- coding: utf-8 -*-
"""
观察层 Red-Team 压力测试触发器（事件驱动挂钩）
====================================================

设计契约（与 docs/governance_poc_redteam.md 一致）：
- 仅在 os2_report 成功写盘后由生产链路调用，实现「产出即触发」（事件驱动），
  不依赖任何 cron / 定时任务，天然消除时序竞态与跨平台差异。
- 完全故障隔离：子进程超时 / LLM 异常 / INVALID_ROUND 报警 一律吞掉，
  绝不向上抛出，绝不改变主研报写出与推送的退出码。
- 零生产权限：仅把 memo HTML 作为输入，触发独立的观察层子进程，
  结果写入 output/redteam_records/，不碰任何生产评分 / 调仓 / 下单。
- 环境变量继承：用 sys.executable 启动子进程，自动继承当前解释器与 LLM_* 变量。

开关（环境变量）：
  REDTEAM_HOOK_ENABLED=0   关闭挂钩（不触发，便于调试 / 降级）。
  REDTEAM_HOOK_TIMEOUT     子进程超时秒数，默认 180（两次 LLM 调用 + 重试需留余量）。
"""
import os
import subprocess
import sys
from pathlib import Path

# 本文件位于 backend/os_layers/redteam_trigger.py
_LAYERS_DIR = Path(__file__).resolve().parent
_SCRIPT = _LAYERS_DIR / "redteam_pressure_test.py"
# backend/os_layers -> backend -> 项目根
_PROJECT_ROOT = _LAYERS_DIR.parent.parent
_OUTPUT_DIR = _PROJECT_ROOT / "output" / "redteam_records"


def trigger_redteam_poc(memo_html_path) -> bool:
    """
    观察层 Red-Team 压力测试触发器。

    仅当 memo HTML 成功生成后执行，失败不阻断主生产链路。
    返回 True 表示已成功触发并归档（或正常跳过 / 已禁用）；
    返回 False 表示执行异常（已记录警告，主流程不受影响）。
    """
    if os.getenv("REDTEAM_HOOK_ENABLED", "1") == "0":
        print("[RedTeam] 挂钩已通过环境变量禁用（REDTEAM_HOOK_ENABLED=0），跳过。")
        return True

    memo_html_path = Path(memo_html_path)
    if not memo_html_path.exists():
        print(f"[RedTeam][WARN] 目标研报不存在: {memo_html_path}，跳过 Red-Team 审查")
        return False

    if not _SCRIPT.exists():
        print(f"[RedTeam][WARN] 编排器不存在: {_SCRIPT}，跳过 Red-Team 审查")
        return False

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trade_date = memo_html_path.stem.replace("memo_", "")
    output_file = _OUTPUT_DIR / f"redteam_record_{trade_date}.md"

    cmd = [
        sys.executable,
        str(_SCRIPT),
        "--input", str(memo_html_path),
        "--output", str(output_file),
    ]

    timeout = int(os.getenv("REDTEAM_HOOK_TIMEOUT", "180"))
    try:
        # 非阻塞 / 容错执行：观察层异常绝不影响主流程退出码
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            print(f"[RedTeam][INFO] 压力测试归档完成: {output_file}")
            return True
        # 仅记录，不抛出；INVALID_ROUND 报警日志在子进程 stderr 中
        print(f"[RedTeam][ERROR] 执行失败 (Exit {result.returncode}):\n{result.stderr}")
        return False
    except subprocess.TimeoutExpired as e:
        print(f"[RedTeam][ERROR] 触发超时（>{timeout}s），已跳过（不影响主流程）：{e}")
        return False
    except Exception as e:
        print(f"[RedTeam][ERROR] 触发异常（已吞掉，不影响主流程）：{e}")
        return False
