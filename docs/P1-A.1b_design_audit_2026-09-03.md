# P1-A.1b · daily-os 测试转换 · 只读设计审计

> 阶段：P1-A Test Harness Reliability Audit
> 范围：仅读取 `test_e2e.py` / `test_integration.py` / `app.py`，画出真实依赖图与最小改造方案
> **本文件不含任何代码修改**。实际改写（option a）待用户授权后另立任务执行。
> 生成时间：2026-09-03

---

## 0. P1-A.1 结论重标（按用户拍板）

| 层级 | 状态 | 含义 |
|---|---|---|
| Import safety | **PASS** | app.py:22 不再因 pytest argv 崩溃 |
| Collection errors | **PASS** | 0 errors（2 → 0） |
| Test population | **FAIL** | 0 个 pytest tests |
| Execution | **BLOCKED** | 没有 pytest test 可以执行 |
| CLI regression | **PASS** | `python app.py` / `python app.py 8777` 正常启动路径保持 |
| Production safety | **PASS** | DB / 生产流水线未触碰 |

**准确表述**：daily-os 已从「collection crash」恢复为「可导入」，但确认其当前**不存在 pytest-native test coverage**。「daily-os 测试恢复正常」这个说法不成立。

---

## 1. 系统级 Reliability Principle（建议写入治理）

> **「0 collection errors」≠「test suite healthy」。**

Harness 健康必须同时满足四维 Integrity：

| Integrity | 标准 | 当前 daily-os |
|---|---|---|
| Collection Integrity | collection errors = 0 | PASS |
| Population Integrity | collected > 0 | **FAIL (0)** |
| Execution Integrity | executed = collected（允许显式 skip） | BLOCKED (0) |
| Result Integrity | PASS/FAIL 可审计、不被静默吞 | 不适用（无测试） |

此四维标准应成为整个 AI 研投系统测试体系的统一 Gate。

---

## 2. P1-A.1b 目标与边界

**唯一目标**：将 `test_e2e.py` / `test_integration.py` 从「顶层副作用脚本」转换为可被 pytest 发现、隔离、执行的测试。

**必须满足的链路**：
```
pytest collection → N > 0 → 实际执行 → 测试不写生产 daily_os.db → PASS/FAIL 可观察
```

**改写前必须先审计（本次已完成）**：
1. app.py 的 server 生命周期 ✓
2. daily_os.db schema ✓
3. 两个脚本实际访问哪些 API ✓
4. 哪些 API 会产生 DB 写入 ✓
5. 能否使用 tmp_path / 临时 SQLite ✓
6. 是否存在后台线程未正常 shutdown 的问题 ✓

---

## 3. app.py server / DB 生命周期（只读发现）

### 3.1 两个 DB 句柄
| 全局 | 默认指向 | 用途 | 被谁写 |
|---|---|---|---|
| `DB_PATH` = `daily_os.db`（daily-os 目录内，**真实本地库**） | `get_db()` 所有读写 | `daily_records` 表 | POST noon/trade/evening/link |
| `TRADING_DB` = `backend/database/vibe_research.db` | 交易 OS 主库 | `import_trades_from_os`（读 trade_journal）/ `sync_review_to_os`（写 trader_review） | POST sync_review |

### 3.2 server 生命周期
- `run()` 仅在 `if __name__ == "__main__"` 下调用：`init_db()` → `HTTPServer(("127.0.0.1", PORT), Handler)` → `serve_forever()`。
- 两个脚本**不走 `run()`**，而是自己 `hs.HTTPServer(("127.0.0.1", 8779/8781), A.Handler)` + `threading.Thread(daemon=True)` + `time.sleep(0.6)` 等待绑定，结束 `srv.shutdown()`。
- `init_db()` 创建 `daily_records` 表；当前 `daily_os.db` 已存在（Aug-13 生成）。**隔离改造必须在临时库上显式调用 `A.init_db()`**，否则 `daily_records` 表不存在 → API 报错。

### 3.3 API → DB 写入依赖图
| 端点 | 方法 | 读写 | 目标库 | 是否写真实库 |
|---|---|---|---|---|
| /api/today | GET | 读 | daily_records (DB_PATH) | 读 |
| /api/trend | GET | 读 | daily_records (DB_PATH) | 读 |
| /api/record | GET | 读 | daily_records (DB_PATH) | 读 |
| /api/import_trades | GET | 读 | trade_journal (TRADING_DB) | 读（脚本已重定向到临时库） |
| /api/noon | POST | **写** | daily_records (DB_PATH) | **写真实 daily_os.db ★** |
| /api/trade | POST | **写** | daily_records (DB_PATH) | **写真实 daily_os.db ★** |
| /api/evening | POST | **写** | daily_records (DB_PATH) | **写真实 daily_os.db ★** |
| /api/link | POST | **写** | daily_records (DB_PATH) | **写真实 daily_os.db ★** |
| /api/sync_review | POST | **写** | trader_review (TRADING_DB) | 写（脚本已重定向到临时库） |

**核心安全结论**：脚本只重定向了 `TRADING_DB`，但 `noon/trade/evening/link` 四个 POST 全部写**真实** `daily_os.db`。隔离改造必须同时重定向 `A.DB_PATH` 到临时库。

---

## 4. 当前两个测试的真实依赖图

```
test_e2e.py（当前：顶层副作用脚本，pytest 不可发现）
└─ import app as A
   └─ A.Handler 读 A.DB_PATH = daily_os.db(真实)
   start() → HTTPServer(127.0.0.1:8779, A.Handler) + 守护线程 + sleep(0.6)
   ├─ POST /api/noon    → WRITE daily_records(真实 daily_os.db) ★污染
   ├─ POST /api/trade   → WRITE daily_records(真实)            ★污染
   ├─ GET  /api/today   → READ
   ├─ GET  /api/trend   → READ
   └─ srv.shutdown()
   print("E2E_OK")                         # 无 assert 包裹，靠打印判断

test_integration.py（当前：顶层副作用脚本，pytest 不可发现）
└─ import app as A
   └─ A.TRADING_DB = temp fake db(trade_journal+trader_review)  # 仅此重定向
   start HTTPServer(127.0.0.1:8781, A.Handler) + 守护线程 + sleep(0.6)
   ├─ GET  /api/import_trades → READ temp TRADING_DB
   ├─ POST /api/link    → WRITE daily_records(真实 daily_os.db) ★污染
   ├─ POST /api/evening → WRITE daily_records(真实)            ★污染
   ├─ POST /api/sync_review → WRITE trader_review(temp TRADING_DB)
   ├─ GET  /api/today   → READ daily_records(真实)
   └─ assert ... ; srv.shutdown()
```

两个脚本均有「import 即起服务器 + 写真实库 + 靠 print/裸 assert 判断」的副作用，是 Population=0 的根因。

---

## 5. 最小改造方案（option a，仅设计，未实施）

### 5.1 新增 `daily-os/conftest.py`（集中管理 server 生命周期 + DB 隔离）
```python
import pytest, threading, time, http.server as hs
import app as A

@pytest.fixture
def app_server(tmp_path):
    # 隔离 daily_os.db：重定向到临时库并初始化 schema（避免写真实库）
    A.DB_PATH = str(tmp_path / "daily_os.db")
    A.init_db()
    srv = hs.HTTPServer(("127.0.0.1", 0), A.Handler)  # 0 = 系统分配空闲端口
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start(); time.sleep(0.3)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown(); t.join(timeout=2)                  # 后台线程正常退出
```

### 5.2 `test_e2e.py` → `def test_e2e(app_server):`
- 删除模块顶层 `start()` / `print` / 裸逻辑；改为函数内用 `app_server` 作 base url。
- 用 `assert` 替代 `print("E2E_OK")`。

### 5.3 `test_integration.py` → `def test_integration(app_server, tmp_path):`
- 额外在测试内重定向 `A.TRADING_DB` 到 `tmp_path` 下的 fake db（建 `trade_journal`+`trader_review` 表、插一行），验证 `sync_review` 写回该临时库。
- 用 `assert` 校验 `trader_review` 真实写入。

### 5.4 预期收益（Gate 全过）
- Collection: 2 tests collected（N>0）✓
- Execution: 2 executed，不写真实 `daily_os.db`（DB_PATH 重定向 tmp_path）✓
- Result: assert 失败即 FAIL，可见可审计 ✓
- 不改 `app.py` 任何业务代码，仅新增 `conftest.py` + 改写两个测试文件。

---

## 6. 改写前仍需你确认的两点（不改写，先留痕）
1. **端口策略**：设计用 `port=0` 系统分配，避免 8779/8781 硬编码冲突；是否接受？
2. **是否保留 `print` 调试输出**：建议改为纯 `assert`；若你希望保留运行痕迹，可在 fixture 内开 `Handler.log_message`。

---

## 7. 状态
- P1-A.1b 设计审计：**完成（只读）**。
- 实际改写（option a）：**待授权**，不在此轮执行。
- P1-A.2（整体 harness 健康度）：**待 A.1b 改写完成后再做**，不提前进入。
