"""P1-B3 · Gate ⑤-Pre：Subprocess Isolation 专项验证。

对应发现 **B3-F8 · 进程边界逃逸**：
    pytest 主进程的 monkeypatch 无法传播到 `subprocess.run()` 拉起的子进程。
    子进程重新解析 DB_PATH → 直达 canonical 生产库。

E1（VIBE_DB_PATH 环境变量 override）是唯一能跨进程边界传播的载体。
本文件验证它确实成立，共四件事 + 一个对照实验：

    1  主进程拿到 VIBE_DB_PATH
    2  子进程能够继承 VIBE_DB_PATH
    3  子进程实际写入 sandbox
    4  canonical path 完全没有 connect / create / write
    C  对照：剔除 VIBE_DB_PATH 后，子进程会解析回 canonical
       （证明隔离确实由 env 生效，而非碰巧；只解析不连接，零副作用）

范围声明：E1 只覆盖走 `db.py` / `database.models` 的子进程。
~100 处硬编码路径仍不受控 —— 那是 P1-C 的课题，不在此 Gate 范围内。
"""
import os
import sqlite3
import subprocess
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

CANON_DB = os.path.normpath(os.path.join(BACKEND, "database", "vibe_research.db"))


def _run_py(code, env_override=None):
    """在本项目 backend/ 下以子进程执行一段 Python。"""
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", BACKEND)
    for k, v in (env_override or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120,
    )


def _fingerprint(path):
    """文件指纹：不存在=None；存在=(size, mtime_ns)。用于零触碰断言。"""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns)


# ── 1. 主进程拿到 VIBE_DB_PATH ───────────────────────────────────────────

def test_main_process_has_sandbox_env():
    sandbox = os.environ.get("VIBE_DB_PATH")
    assert sandbox, "主进程未设置 VIBE_DB_PATH（conftest 守卫未生效？）"

    import db as _db
    import database.models as _models

    assert str(_models.DB_PATH) == sandbox, "models.DB_PATH 与 VIBE_DB_PATH 不一致"
    assert _db._DB_PATH == sandbox, "db._DB_PATH 与 VIBE_DB_PATH 不一致"
    assert os.path.exists(sandbox), "沙箱库不存在"


# ── 2. 子进程继承 VIBE_DB_PATH ───────────────────────────────────────────

def test_subprocess_inherits_env_var():
    r = _run_py("import os; print(os.environ.get('VIBE_DB_PATH', ''))")
    assert r.returncode == 0, f"子进程失败: {r.stderr}"
    assert r.stdout.strip() == os.environ["VIBE_DB_PATH"], "子进程未继承 VIBE_DB_PATH"


def test_subprocess_resolves_sandbox_db():
    code = "import database.models as m; import db; print(m.DB_PATH); print(db._DB_PATH)"
    r = _run_py(code)
    assert r.returncode == 0, f"子进程失败: {r.stderr}"
    lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
    assert lines, "子进程无输出"
    assert lines[0] == os.environ["VIBE_DB_PATH"], f"子进程 models.DB_PATH 未指向沙箱: {lines[0]}"
    if len(lines) > 1:
        assert lines[1] == os.environ["VIBE_DB_PATH"], f"子进程 db._DB_PATH 未指向沙箱: {lines[1]}"


# ── 3 + 4. 子进程实际写 sandbox，canonical 零触碰 ────────────────────────

def test_subprocess_write_lands_in_sandbox_and_never_touches_canonical():
    sandbox = os.environ["VIBE_DB_PATH"]
    before = _fingerprint(CANON_DB)

    code = (
        "import database.models as m;"
        "c = m.get_db();"
        "c.execute('CREATE TABLE IF NOT EXISTS subprocess_probe "
        "(id INTEGER PRIMARY KEY, tag TEXT)');"
        "c.execute(\"INSERT INTO subprocess_probe (tag) VALUES ('from-subprocess')\");"
        "c.commit(); c.close();"
        "print(m.DB_PATH)"
    )
    r = _run_py(code)
    assert r.returncode == 0, f"子进程写入失败: {r.stderr}"
    assert r.stdout.strip() == sandbox, "子进程写入的目标不是沙箱"

    # 3) sandbox 确实收到写入
    conn = sqlite3.connect(sandbox)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM subprocess_probe WHERE tag='from-subprocess'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n >= 1, "沙箱未收到子进程写入"

    # 4) canonical 零触碰
    assert _fingerprint(CANON_DB) == before, \
        "canonical 生产库在子进程执行期间被创建/修改（B3-F8 未关闭）"


# ── C. 对照实验：剔除 env 后子进程解析回 canonical（只解析，不连接）────────

def test_control_without_env_subprocess_resolves_canonical():
    """证明隔离确实由 VIBE_DB_PATH 生效。

    只做路径解析，不建立连接，因此不会创建/写入 canonical。
    """
    before = _fingerprint(CANON_DB)

    code = "import database.models as m; print(m.DB_PATH)"
    r = _run_py(code, env_override={"VIBE_DB_PATH": None})
    assert r.returncode == 0, f"子进程失败: {r.stderr}"

    resolved = r.stdout.strip().replace("/", os.sep)
    assert resolved == CANON_DB, \
        f"剔除 VIBE_DB_PATH 后子进程应解析回 canonical，实际: {resolved}"

    assert _fingerprint(CANON_DB) == before, "对照实验不应触碰 canonical"
