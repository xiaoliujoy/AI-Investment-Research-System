# -*- coding: utf-8 -*-
"""P1-A.1b：daily-os 测试隔离 fixture。仅测试基础设施，不修改 app.py。

安全约束（用户硬 Gate）：
- teardown 必须恢复 A.DB_PATH / A.TRADING_DB 原始模块级全局，避免测试间隐藏状态污染。
- server 生命周期：start -> tests -> shutdown -> join()，杜绝 daemon thread 残留。
- 所有写操作落在 tmp_path 临时库，真实 daily_os.db / TRADING_DB 绝对不碰。
"""
import os
import sqlite3
import threading
import time
import http.server as hs
import urllib.request
import urllib.error
import pytest
import app as A

TEST_DATE = "2026-08-13"


@pytest.fixture
def app_server(tmp_path):
    # 保存原始模块级全局（硬 Gate：teardown 必须恢复）
    old_db_path = A.DB_PATH
    old_trading_db = A.TRADING_DB

    tmp_db = str(tmp_path / "daily_os.db")
    tmp_trd = str(tmp_path / "trading_os.db")
    A.DB_PATH = tmp_db
    A.TRADING_DB = tmp_trd
    A.init_db()  # 在临时库创建 daily_records schema

    srv = hs.HTTPServer(("127.0.0.1", 0), A.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    # 就绪轮询（替代固定 sleep，避免慢机 flaky）
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 3
    ready = False
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/api/today?date=" + TEST_DATE, timeout=0.5)
            ready = True
            break
        except Exception:
            time.sleep(0.1)
    if not ready:
        srv.shutdown()
        t.join(timeout=2)
        A.DB_PATH = old_db_path
        A.TRADING_DB = old_trading_db
        raise RuntimeError("server 未在 3s 内就绪")

    info = {"base": base, "real_db": old_db_path, "date": TEST_DATE}
    try:
        yield info
    finally:
        srv.shutdown()
        t.join(timeout=2)
        # Lifecycle Integrity：线程必须已终止
        assert not t.is_alive(), "server thread 未终止（daemon 残留）"
        # 恢复模块级全局，杜绝测试间隐藏状态污染
        A.DB_PATH = old_db_path
        A.TRADING_DB = old_trading_db
