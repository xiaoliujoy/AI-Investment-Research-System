"""pytest 配置：sys.path / live marker / 生产库隔离守卫。

──────────────────────────────────────────────────────────────────────────
P1-B3 · P0-A + P0-B 生产库隔离守卫（2026-09-09 实施）
──────────────────────────────────────────────────────────────────────────

背景（行为级复现，见 .audit/DB_LOCATION_AUDIT_B3_2026-09-09.md）：
    裸跑一次 `pytest` 会在 `backend/database/` 凭空创建一个 3.76 MB 库，
    并向 `commodity_daily` 写入 22,193 行（date 到当天、source 与真实采集
    完全一致 → 污染后不可甄别、不可回滚）。链路为：

        test_pipeline_failure_visibility
          → daily_collect.collect()
            → commodity_engine.collector
              → models.get_db()  →  canonical production DB

    静态扫描无法发现该通道（三级间接：无路径串、不 import models），
    因此这里采用双层守卫：

  P0-A  重定向：`database.models.DB_PATH` 与 `db._DB_PATH` → tmp 沙箱库
        （沙箱库预置生产 schema，保证 `db.get_conn()` 的 exists() 守卫不炸）

  P0-B  硬拒绝：任何 `sqlite3.connect(...)` 若目标解析到生产库 → 立即 raise
        （覆盖硬编码绝对路径、CWD 相对路径、file: URI 等一切绕过 fixture 的路径）

  放行开关：`--allow-prod-db`（显式 opt-in，两级守卫同时关闭）

设计取舍：
  - 作用域 = session（沙箱库全局共享，避免每个测试各建一次 schema）。
    已验证当前 suite 无跨测试 DB 状态依赖；若将来出现，改为 function 级即可。
  - 沙箱文件名刻意不含 `vibe_research.db` 子串，避免与 P0-B 拒绝判据自相冲突。
"""
import os
import sqlite3
import subprocess
import sys

import pytest

BACKEND = os.path.dirname(os.path.abspath(__file__))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# 生产库（唯一 canonical 目标）
CANON_DB = os.path.normpath(os.path.join(BACKEND, "database", "vibe_research.db"))
# 沙箱库文件名：刻意不含 "vibe_research.db" 子串
SANDBOX_NAME = "pytest_sandbox.db"


def _is_production_db(target) -> bool:
    """判定「目标是生产库」：覆盖绝对路径 / 相对路径 / file: URI / 历史空壳。"""
    s = str(target)
    if not s or s == ":memory:":
        return False
    if SANDBOX_NAME in s:          # 沙箱自身，放行
        return False
    return "vibe_research.db" in s


def _is_backend_script_cmd(args) -> bool:
    """判断 subprocess 命令是否在拉起本 backend 目录下的 Python 脚本。"""
    if not isinstance(args, (list, tuple)) or len(args) < 2:
        return False
    exe, script = str(args[0]), str(args[1])
    if "python" not in os.path.basename(exe).lower():
        return False
    if not script.lower().endswith(".py"):
        return False
    try:
        script_abs = os.path.abspath(script)
    except Exception:
        return False
    return os.path.normcase(script_abs).startswith(os.path.normcase(BACKEND + os.sep))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: 打真实数据源的网络冒烟测（会联网、可能受上游/限流影响；默认可 -m 'not live' 跳过）",
    )
    config.addinivalue_line(
        "markers",
        "proddb: 需要访问真实生产库（默认被守卫拒绝；须 --allow-prod-db 显式放行）",
    )


def pytest_addoption(parser):
    parser.addoption(
        "--allow-prod-db",
        action="store_true",
        default=False,
        help="显式放行测试访问真实生产库（默认禁止；仅在明确需要读真实库时使用）",
    )
    parser.addoption(
        "--allow-subprocess",
        action="store_true",
        default=False,
        help="显式放行测试用 subprocess 拉起 backend 下的脚本（默认禁止，见 B3-F8）",
    )


@pytest.fixture(scope="session", autouse=True)
def _prod_db_isolation(request, tmp_path_factory):
    """P1-B3 P0-A + P0-B：测试环境绝不触碰生产库。"""
    if request.config.getoption("--allow-prod-db"):
        yield None
        return

    mp = pytest.MonkeyPatch()
    sandbox = str(tmp_path_factory.mktemp("db") / SANDBOX_NAME)

    # ── P0-B：硬拒绝（先装，保证重定向之前的任何连接也被拦）──────────────
    _orig_connect = sqlite3.connect

    def _guarded_connect(database, *args, **kwargs):
        if _is_production_db(database):
            raise RuntimeError(
                f"[P1-B3 P0-B] 测试环境禁止连接生产库：{database}\n"
                f"  canonical = {CANON_DB}\n"
                f"  测试应写入沙箱库；若确实需要真实库，请显式加 --allow-prod-db。"
            )
        return _orig_connect(database, *args, **kwargs)

    mp.setattr(sqlite3, "connect", _guarded_connect)

    # ── B3-F8：子进程硬拒绝 ──────────────────────────────────────────────
    # E1（VIBE_DB_PATH）只能覆盖走 db.py / database.models 的脚本；实测
    # fill_stock_flow.py / build_derived_tables.py / data_freshness.py 等
    # 全部用 __file__ 或 ROOT 硬编码锚定 canonical，env 对它们无效。
    # 因此这里沿用 P0-B 的哲学：测试期间凡是拉起 backend 下脚本的
    # subprocess 一律拒绝，而不是让它静默连生产库。
    if not request.config.getoption("--allow-subprocess"):
        _orig_run = subprocess.run

        def _guarded_run(args, *a, **kw):
            if _is_backend_script_cmd(args):
                raise RuntimeError(
                    "[P1-B3 B3-F8] 测试环境禁止用 subprocess 拉起 backend 下的脚本：\n"
                    f"  args = {args}\n"
                    "  子进程不加载 conftest，不受生产库隔离守卫保护。\n"
                    "  请在测试内打桩该函数；若确需真实子进程，显式加 --allow-subprocess。"
                )
            return _orig_run(args, *a, **kw)

        mp.setattr(subprocess, "run", _guarded_run)

    # ── P0-A：重定向两个模块级 DB_PATH → 沙箱 ──────────────────────────
    import db as _db
    import database.models as _models
    from pathlib import Path as _Path

    mp.setattr(_db, "_DB_PATH", sandbox, raising=True)
    mp.setattr(_models, "DB_PATH", _Path(sandbox), raising=True)

    # ── E1：进程级传递（P1-B3 B3-F8）────────────────────────────────────
    # monkeypatch 只作用于本进程；subprocess 拉起的子脚本不加载 conftest，
    # 只能靠环境变量把沙箱路径传下去。子进程 os.environ 自动继承此设置。
    mp.setenv("VIBE_DB_PATH", sandbox)

    # 预置生产 schema（db.get_conn() 有 exists() 守卫，沙箱文件必须存在）
    _models.init_db()

    yield sandbox

    mp.undo()
