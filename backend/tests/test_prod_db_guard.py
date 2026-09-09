"""守卫的守卫：验证 P1-B3 P0-A / P0-B 生产库隔离本身有效。

为什么需要这个文件：
    B3-F1 的根因是「隔离靠测试作者自觉，没有兜底，且已经失手一次」。
    如果 conftest 里的守卫将来被人改坏/删掉，而没有任何测试能发现，
    那么守卫就退化成另一句书面承诺。本文件让守卫自身变成可回归验证的对象。

覆盖：
    P0-B  硬拒绝：任何形式的生产库连接（绝对路径 / 相对路径 / file: URI）必须 raise
    P0-A  重定向：models.DB_PATH / db._DB_PATH 必须指向沙箱，且沙箱真实存在
"""
import os
import sqlite3
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

CANON_DB = os.path.normpath(os.path.join(BACKEND, "database", "vibe_research.db"))


# ── P0-B 硬拒绝 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", [
    CANON_DB,                                        # 绝对路径
    os.path.join("backend", "database", "vibe_research.db"),   # CWD 相对路径
    "database/vibe_research.db",                     # 研究脚本用的相对路径形式
    "file:" + CANON_DB.replace("\\", "/") + "?mode=ro",         # file: URI（只读也算）
    os.path.normpath(os.path.join(BACKEND, "vibe_research.db")),  # 历史空壳候选
], ids=["abs", "rel_backend", "rel_database", "file_uri", "legacy_shell"])
def test_connect_production_db_is_hard_rejected(target):
    with pytest.raises(RuntimeError, match="禁止连接生产库"):
        sqlite3.connect(target)


def test_memory_db_still_allowed():
    """守卫不能误伤正常的内存库。"""
    conn = sqlite3.connect(":memory:")
    try:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()


# ── P0-A 重定向 ──────────────────────────────────────────────────────────

def test_module_db_paths_are_redirected_to_sandbox():
    import db as _db
    import database.models as _models

    sandbox = str(_models.DB_PATH)
    assert "vibe_research.db" not in sandbox, \
        f"models.DB_PATH 未重定向到沙箱，仍指向生产库：{sandbox}"
    assert os.path.exists(sandbox), \
        f"沙箱库不存在（db.get_conn() 有 exists() 守卫，会 FileNotFoundError）：{sandbox}"
    assert _db._DB_PATH == sandbox, "db._DB_PATH 与 models.DB_PATH 未对齐到同一沙箱"
    assert _db.exists() is True, "db.exists() 应对沙箱返回 True"


# ── B3-F8 · 子进程硬拒绝 ─────────────────────────────────────────────────

def test_subprocess_run_of_backend_script_is_rejected():
    """子进程不加载 conftest，不受 DB 守卫保护 → 默认一律拒绝。"""
    import subprocess

    with pytest.raises(RuntimeError, match="禁止用 subprocess 拉起"):
        subprocess.run([sys.executable, os.path.join(BACKEND, "data_freshness.py")])


def test_subprocess_run_of_non_backend_python_is_allowed():
    """守卫不能误伤与本项目无关的子进程。"""
    import subprocess

    r = subprocess.run([sys.executable, "-c", "print(1)"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "1"


def test_sandbox_has_production_schema():
    """沙箱预置生产 schema，保证走 db.get_conn() 的模块能正常工作。"""
    import db as _db

    conn = _db.get_conn()
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    for required in ("market_daily", "sector_daily", "stock_daily", "limit_up_daily"):
        assert required in tables, f"沙箱缺少生产表 {required}"
