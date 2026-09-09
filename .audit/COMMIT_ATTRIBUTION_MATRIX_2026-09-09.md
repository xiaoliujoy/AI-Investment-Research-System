# Commit Attribution Matrix — 2026-09-09

> 门状态：**Release / Frozen Working Tree Gate = CONTENT PASS / COMMIT FROZEN / STAGING NOT AUTHORIZED**
> 工作树内容已通过审计，可以冻结；但**尚未获得 staging / commit 授权**。
> 本文档为**只读归因审计产物**，未 staging、未 commit、未 push。

用户裁定：**拆成两个 commit**（不把历史 P1-B3/P0-B 与本轮 C7/C10 混在一起）。

---

## 1. 归因方法

特征匹配（脚本 `.audit/evidence/commit_attribution_audit.py`，只读调用 `git diff`）：

| 归属 | 特征 |
| --- | --- |
| `HISTORICAL` | `VIBE_DB_PATH`、`allow-prod-db`、`生产库隔离守卫`、`P0-A`/`P0-B`/`P1-B3`、`_no_subprocess`、`monkeypatch.setenv`、`sandbox` |
| `C7` | `from db import get_conn`、`get_conn(`、`str(_DB_PATH)`、`sqlite3.connect`、`DB/DB_PATH/OUT_DB =` |
| `C10` | `from universe import`、`is_stock`、`market_of`、`_gtimg_prefix`、`_ts_code`、`get_prefix`、`BJ_PREFIXES` |

先做**文件级**归属，再对同时命中两类的文件做 **hunk 级**拆分。

---

## 2. 结论：MIXED 只有 1 个文件

| 类别 | 数量 | 处理 |
| --- | --- | --- |
| COMMIT1 纯 HISTORICAL（整文件） | 3 | 整文件 stage |
| COMMIT2 纯 C7 | 58 | 整文件 stage |
| COMMIT2 纯 C10 | 3 | 整文件 stage |
| COMMIT2 C7+C10（同文件两类，但**同属本轮**） | 4 | 整文件 stage（无需拆分） |
| **MIXED（跨轮次，必须 hunk 级拆分）** | **1** | `backend/db.py` |
| 误报校正 | 1 | `backend/conftest.py`（脚本误判，实为纯 HISTORICAL） |

---

## 3. COMMIT 1 — 历史轮次冻结（P1-B3·E1 / P0-A·P0-B / B3-F8 / 历史 P0-B）

**整文件 stage（3）**
| 文件 | 轮次 | 内容 |
| --- | --- | --- |
| `backend/database/models.py` | P1-B3·E1 | `import os`；`DB_PATH` → `_DEFAULT_DB_PATH` + `VIBE_DB_PATH` 环境覆盖 |
| `backend/conftest.py` | P1-B3·P0-A/P0-B | 生产库隔离守卫：`CANON_DB`、`SANDBOX_NAME`、`_is_production_db()`、`_is_backend_script_cmd()`、sys.path 改造、`mp.setenv("VIBE_DB_PATH", sandbox)` |
| `backend/tests/test_pipeline_failure_visibility.py` | P1-B3·B3-F8 | 子进程 `_run` 打桩（`_no_subprocess`），避免测试触碰生产库 |

**hunk 级 stage（1，仅取前 2 个 hunk）**

`backend/db.py`
| hunk | 行范围 | 内容 | 归属 |
| --- | --- | --- | --- |
| 1 | `@@ -24,3 +24,3 @@` | `-_DB_PATH = os.path.normpath(` → `+_DEFAULT_DB_PATH = os.path.normpath(`（为 env 覆盖让路） | **COMMIT1** |
| 2 | `@@ -32,2 +32,8 @@` | `+# 未设置 VIBE_DB_PATH 时…` / `+_DB_PATH = os.environ.get("VIBE_DB_PATH") or _DEFAULT_DB_PATH` | **COMMIT1** |
| 3 | `@@ -43,3 +49,3 @@` | `def get_conn()` → `def get_conn(timeout: int = 5)` | COMMIT2 |
| 4 | `@@ -47,2 +53,8 @@` | `+Args: timeout …`（docstring） | COMMIT2 |
| 5 | `@@ -50,2 +62,2 @@` | `sqlite3.connect(_DB_PATH)` → `sqlite3.connect(_DB_PATH, timeout=timeout)` | COMMIT2 |

**新文件（untracked，2）**
| 文件 | 轮次 |
| --- | --- |
| `backend/tests/test_prod_db_guard.py` | 历史 P0-B |
| `backend/tests/test_subprocess_db_isolation.py` | 历史 P1-B3·E1 |

---

## 4. COMMIT 2 — 本轮 C7 + C10

**整文件 stage：65 个 modified**（= 69 − COMMIT1 的 3 个整文件 − `db.py`）

其中需点名的：

*纯 C10（3）* — `backend/astock.py`、`backend/capital_score.py`、`backend/fundamental_engine.py`

*C7+C10 同文件（4，同属本轮故整体 stage）* —
`backend/data_health.py`、`backend/fill_market_cap.py`、`backend/leader_engine.py`、`backend/tushare_provider.py`

*纯 C7（58）* — 其余全部（生产消费者 `sqlite3.connect` → `get_conn` / `DB*` → `str(_DB_PATH)`），
含 `backend/brain/cio_agent.py`（手动迁移 2 处）、`_audit2.py`/`_audit_data.py`/`_quick_today_import.py`（诊断脚本顺带收敛）。

**`db.py` 的 COMMIT2 部分**：hunk 3/4/5（`get_conn(timeout=5)` + docstring + `timeout=timeout`）。
此改动 docstring 明示 "P1-C migration"，是为本轮 C7 服务的，故归 COMMIT2。

**新文件（untracked，2）**
| 文件 | 说明 |
| --- | --- |
| `backend/universe.py` | C10 单点事实源 |
| `backend/tests/test_universe_contract.py` | C10 契约测试（10 项） |

---

## 5. 误报校正说明

`backend/conftest.py` 被脚本判为 MIXED，**人工复核为误报**：
命中 C7 特征只是因为守卫 docstring 里提到了 `db.get_conn()` 与 `sqlite3.connect(...)`（描述性文字），
实质改动 100% 属于 P1-B3 P0-A/P0-B。→ **整文件归 COMMIT1**。

---

## 6. `.audit/` — 单独处理（含体积风险盘点）

按用户指示：不混进生产功能 commit，作为**第三个 commit**（或按用户后续指定策略）。

### 6.1 若执行 `git add .audit/`，实际会纳入 30 个文件

| 类别 | 数量 | 体积 | 建议 |
| --- | --- | --- | --- |
| `.md` 审计文档（B1~B4 / P1-C×2 / Recovery×3 / Release / T1_2 / 本矩阵） | 12 | ~125 KB | ✅ 提交（治理资产） |
| 可复现脚本 `.py`（p1c_scan / p1c_universe_probe / recovery_gate_snapshot / commit_attribution_audit / b3_×5） | 7 | ~24 KB | ✅ 提交 |
| 结构化证据 `.json` / `.txt`（recovery_pre|post / p1c_inventory / p1c_matrix / b3_scan* / b3_tests / sha256） | 10 | ~78 KB | ✅ 提交 |
| **`injection1_probe_log.json`** | **1** | **5.9 MB** | ⚠️ **建议排除** |

### 6.2 已被 `.gitignore` 保护、**不会**被提交（约 12 MB）

```
.gitignore:15  *.db       → 5 个 .db + .db-shm / .db-wal
.gitignore     *.log      → pytest_gate7.log
```
含 `.audit/evidence/B3/` 下：
`post_isolation_sandbox_22k_rows.db`(3.84M)、
`injection2_sandbox_db/vibe_research.db`(3.84M)、
`pytest_unisolated_created_vibe_research_3.76MB.db`(3.59M)、
`canonical_0byte_shell_*.db`(0B)。

> **结论：12 MB 二进制已受保护，无需额外动作。** 唯一漏网的是 `.json` 扩展名的 probe log。

### 6.3 `injection1_probe_log.json` 处置建议

- 性质：B3 injection #1 原始命中日志（`sandbox` / `canon` / `hits[]`，逐次记录 `sqlite3.connect` 是否命中生产库）。
- 证据价值：**结论已固化**在 `DB_LOCATION_AUDIT_B3_2026-09-09.md`（22,193 行、3.76 MB、不可甄别等关键判断均在文档内）。
- 建议：**排除出版本库**，本地保留原件。做法二选一：
  - A. 加 `.gitignore` 规则 `.audit/evidence/B3/injection1_probe_log.json`
  - B. 物理删除原件（文档已承载结论）
- **待用户拍板，本次未执行。**

### 6.4 一个命名隐患（仅提示，未改动）

`.audit/evidence/B3/injection2_sandbox_db/vibe_research.db` 与生产库**同名**。
当前被 gitignore 且不参与任何运行路径（P0-B 守卫按路径判定，沙箱库刻意避开该子串），风险为 0。
但若将来出现按文件名匹配的扫描/守卫，存在误判可能。可选改为 `sandbox_probe.db`。
**属"不为更漂亮而改"范畴，仅记录，未执行。**

### 6.5 根目录临时文件澄清

`_tmp_update_rc2.py`（项目根，**非** `backend/`）：
被 `.gitignore:169:_tmp_*.py` 忽略、未 tracked、创建于 Aug 14，内容为一次性更新 research-contract JSON 的脚本，
与本轮 P1-C 无关。→ **不构成提交风险**。同理 `.pytest_cache/` 亦被忽略。

本次新增：`.audit/RELEASE_WORKING_TREE_GATE_2026-09-09.md`、
`.audit/COMMIT_ATTRIBUTION_MATRIX_2026-09-09.md`、
`.audit/evidence/commit_attribution_audit.py`；
并已更新 `.audit/P1C_ROUND2_UNIVERSE_AUDIT_2026-09-09.md` §7。

---

## 7. 暂停点

**已暂停，等待用户确认本 manifest。**

确认后才执行：staging → `git diff --cached` 复审 → 两个 commit 分别提交 → 各自跑验证并记录 SHA。

未执行任何 staging / commit / push。
