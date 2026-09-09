# Release / Frozen Working Tree Gate — 2026-09-09

> 性质：**独立于 P1-C 验证门的第二道门**。
> P1-C 验证门证明的是「C7/C10 的行为与回归要求通过」；
> 本门回答的是另一个问题：**「工作树里究竟有什么」**。
> 不因为 P1-C PASS 就把当前工作树当成可提交状态。
>
> 本轮为 **READONLY 审计**：未改任何代码、未 commit、未 push。

---

## 1. 审计结果总表

| 项目 | 目标 | 实测 | 判定 |
| --- | --- | --- | --- |
| `git status --short` | 只出现预期文件 | 74 条 = **69 M + 5 ??** | ✅ |
| 非 `backend/` 条目 | 仅 `.audit/` | 仅 `.audit/` | ✅ |
| C7 修改集合 | 与授权范围一致 | 生产消费者 `sqlite3.connect` → `get_conn` | ✅ |
| C10 修改集合 | 与授权范围一致 | `universe.py` 单点 + 3 处 `_is_stock` + 4 处路由 | ✅ |
| `.audit/` | 仅保留正式证据 | 10 份 md + `evidence/`(9 项) | ✅ |
| 临时脚本 | 0 | **0**（`_tmp_*` / `*.bak` 均无） | ✅ |
| DDL / schema | 0 | **0**（CREATE/ALTER/DROP/ADD COLUMN = 0） | ✅ |
| 策略 / 阈值变化 | 0 | **0**（过滤后无 `MIN_*`/阈值常量改动行） | ✅ |
| `VIBE_DB_PATH` 扩散 | 0 | **本轮 0**（现存 6 行 100% 属 P1-B3·E1 历史） | ✅ |
| 北交所 flow 修改 | 0 | **0**（`fill_stock_flow.py` 仅 C7 DB 连接迁移） | ✅ |
| 测试修改 | 仅授权范围内 | 见 §3 | ✅ |
| 最终 pytest | 155 passed | **155 passed, exit 0** | ✅ |
| 最终 compile | 全绿 | **ALL GREEN**（69 py + `universe.py`） | ✅ |
| 回归后条目数稳定 | 与审计前一致 | 审计前后均 **74** | ✅ |

---

## 2. 工作树构成（69 M + 5 ??）

### Untracked（5）
| 条目 | 归属 |
| --- | --- |
| `.audit/` | 审计工件（本门 + P1-C 两轮 + B1~B4 + Recovery） |
| `backend/universe.py` | **本轮 C10** 单点事实源 |
| `backend/tests/test_universe_contract.py` | **本轮 C10** 契约测试（10 项） |
| `backend/tests/test_prod_db_guard.py` | **历史 P0-B** 生产库守卫测试 |
| `backend/tests/test_subprocess_db_isolation.py` | **历史 P1-B3·E1** 子进程隔离测试 |

### Modified（69）按性质分类
- **C7 DB 迁移**：绝大多数生产消费者（`sqlite3.connect(...)` → `get_conn([timeout=N])`，
  `DB/DB_PATH/OUT_DB` → `str(_DB_PATH)`），含 `brain/cio_agent.py` 手动迁移 2 处。
- **C10 Universe 收敛**：`astock.py`、`capital_score.py`、`data_health.py`、`fill_market_cap.py`、
  `fundamental_engine.py`、`tushare_provider.py`、`leader_engine.py`。
- **历史 P1-B3·E1（非本轮）**：`db.py`、`database/models.py`（`VIBE_DB_PATH` 环境传递）。
- **历史 P1-B3·P0-A/P0-B（非本轮）**：`conftest.py`（生产库隔离守卫）。
- **历史 P1-B3·B3-F8（非本轮）**：`tests/test_pipeline_failure_visibility.py`（子进程 `_run` 打桩）。
- **早期 C7 顺带迁移**：`_audit2.py`、`_audit_data.py`、`_quick_today_import.py`（诊断脚本，C7 性质）。

---

## 3. 需向用户如实披露的 3 个发现

### 发现 1（最重要）：工作树**混装了 3 个轮次**的改动，commit 会一并冻结
本工作树不是「纯 C7/C10」。除本轮外还包含**当日更早、且均已单独授权**的历史轮次：

| 轮次 | 涉及文件 |
| --- | --- |
| 本轮 C7/C10 | `universe.py`(新)、`test_universe_contract.py`(新) + 69 M 中的 C7/C10 部分 |
| 历史 P1-B3·E1 | `db.py`、`database/models.py` |
| 历史 P1-B3·P0-A/P0-B | `conftest.py` |
| 历史 P1-B3·B3-F8 | `tests/test_pipeline_failure_visibility.py` |
| 历史 P0-B | `tests/test_prod_db_guard.py`(新) |
| 历史 P1-B3·E1 | `tests/test_subprocess_db_isolation.py`(新) |

→ 这些历史改动此前均已授权，但**若现在 commit，它们会与本轮 C7/C10 进入同一个 commit**。
如需分离，只能用 `git add -p` / 分路径提交。**此为需要用户拍板的决策点。**

### 发现 2：§7.2 carve-out 描述需修正（文档不准确，非代码问题）
P1-C Round2 §7.2 将「`_healthcheck_preopen.py` / `_inspect*.py` 等诊断脚本」整体列为 carve-out。
实测：**`_audit2.py` / `_audit_data.py` / `_quick_today_import.py` 已被迁移**（属 C7 性质，已收敛）。
真正未迁移的诊断脚本仅剩：`_healthcheck_preopen.py`、`_inspect2.py`、`_inspect_db.py`。

### 发现 3：2 处 `DB_PATH = _DB_PATH`（Path 对象）而非 `str(_DB_PATH)`
- `capital_migration.py:36`、`scenario_engine.py:39`
- 全仓唯一用法为 `os.path.exists(DB_PATH)`（接受 PathLike）→ **行为等价，非 bug**。
- 属早期 v3 迁移与 v4 的产物差异。按「不为更漂亮而改代码」原则**本次不动**，仅如实记录。

---

## 4. 验证证据

```
COMPILE: ALL GREEN                 (69 modified .py + backend/universe.py)
pytest : 155 passed, exit 0        (--ignore=test_gate.py)
git status --short : 74 → 回归后 74（无新增意外文件）
DDL/schema 变更行 : 0
阈值/策略变更行   : 0
VIBE_DB_PATH 本轮新增 : 0
北交所 flow 逻辑改动 : 0
临时脚本残留 : 0
```

---

## 5. 判定

**工作树内容 = 授权范围内（C7/C10）+ 已单独授权的历史轮次（P1-B3 / P0-B）。**

无意外修改、无临时文件、无 DDL、无阈值与策略变更、无 `VIBE_DB_PATH` 扩散、无北交所 flow 改动；
回归全绿且条目数稳定。

**本门结论：内容层面具备冻结资格。**
**遗留决策点：是否接受历史轮次与本轮 C7/C10 合并为一次 commit（见 §3 发现 1）。**

本门未 commit、未 push，等待用户确认。
