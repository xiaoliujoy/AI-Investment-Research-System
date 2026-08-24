# -*- coding: utf-8 -*-
"""
Red-Team 触发器冒烟测试
======================
验证 trigger_redteam_poc 三条关键路径：
1. REDTEAM_HOOK_ENABLED=0 熔断：静默返回 True，不调用子进程
2. 目标文件不存在：吞掉并返回 False（故障隔离）
3. 子进程超时：异常被捕获，不向上抛出

运行：python -m unittest tests.test_redteam_trigger_smoke -v
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# backend 无 __init__.py，测试内手动加 path 以便 import os_layers
_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from os_layers.redteam_trigger import trigger_redteam_poc  # noqa: E402


class TestRedteamTriggerSmoke(unittest.TestCase):

    def setUp(self):
        self.dummy_html = os.path.join(tempfile.gettempdir(), "_tmp_test_dummy_memo.html")
        with open(self.dummy_html, "w", encoding="utf-8") as f:
            f.write("<html><body>Test Memo</body></html>")

    def tearDown(self):
        try:
            if os.path.exists(self.dummy_html):
                os.remove(self.dummy_html)
        except OSError:
            pass  # 沙箱回收站不可用时忽略清理失败

    def test_switch_disabled(self):
        """验证开关 REDTEAM_HOOK_ENABLED=0 时静默返回 True 且不调子进程"""
        with patch.dict(os.environ, {"REDTEAM_HOOK_ENABLED": "0"}):
            with patch("os_layers.redteam_trigger.subprocess.run") as mock_run:
                result = trigger_redteam_poc(self.dummy_html)
                self.assertTrue(result)
                mock_run.assert_not_called()

    def test_missing_file_isolation(self):
        """验证传入不存在的文件路径时吞掉异常并返回 False"""
        with patch.dict(os.environ, {"REDTEAM_HOOK_ENABLED": "1"}):
            result = trigger_redteam_poc(os.path.join(os.path.dirname(__file__), "_no_such_file.html"))
            self.assertFalse(result)

    @patch("os_layers.redteam_trigger.subprocess.run")
    def test_timeout_swallowed(self, mock_run):
        """验证子进程超时异常被捕获，不向上抛出"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=1)
        with patch.dict(os.environ, {"REDTEAM_HOOK_ENABLED": "1", "REDTEAM_HOOK_TIMEOUT": "1"}):
            try:
                result = trigger_redteam_poc(self.dummy_html)
                self.assertFalse(result)
            except Exception as e:  # noqa: BLE001
                self.fail(f"trigger_redteam_poc 向上抛出了异常: {e}")


if __name__ == "__main__":
    unittest.main()
