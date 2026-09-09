# P1 · DB Location & Runtime Dependency Audit — B1 · DB Location Inventory

> 时间：2026-09-09 · **模式：READONLY**
> 仅使用：`find`（路径/大小/mtime 元数据）、`grep`、`git ls-tree/ls-files`、读源码、读 `.gitignore`
> **未执行**：连接 DB / SQL / 写入 / 改配置 / 改代码 / git 写操作 / gc

---

## 🎯 核心问题与答案

> 「代码里声明的 DB 路径」=「运行时实际打开的 DB」=「我们认定的生产 DB」吗？

**答：路径声明三者一致，但运行时目标文件缺失 → 三者不能闭环。**

| 维度 | 结论 |
|---|---|
| **代码声明路径** | ✅ 全部收敛于 `backend/database/vibe_research.db`（无分歧） |
| **运行时实际打开** | ❌ 该文件**不存在** → `db.get_conn()` 会 **raise FileNotFoundError** |
| **认定的生产 DB（5.09GB）** | ⚠️ **不在工作树**，仅存在于 **D 盘备份** `/d/AI研投系统备份/2026-09-06/vibe_research.db`（数据截至 **2026-09-05 09:04**） |

**→ Git 恢复即使 98% 完整，系统整体仍不能认为恢复完成：代码链已恢复，但运行时数据（DB）未连接。**

---

## B1-1 全项目 DB 文件清单

| 文件 | 大小 | mtime |
|---|---|---|
| `backend/data/stock.db` | 0 B | 2026-09-01 |
| `backend/data/strategy.db` | 12 KB | 2026-07-14 |
| `backend/vibe_research.db` | 0 B | 2026-07-11 |
| `daily-os/daily_os.db` | 12 KB | 2026-09-03 |
| **`backend/database/vibe_research.db`** | **不存在** | — ← **生产目标** |

**工作树内无任何 >12KB 的 DB。**

### D 盘备份（`_backup_db_to_d.py` 产出，KEEP=4）
| 备份目录 | 文件 | 大小 | 数据时间 |
|---|---|---|---|
| `2026-09-06` | `vibe_research.db` | **5,087,100,928 B（5.09 GB）** | **2026-09-05 09:04** ← 最新 |
| `2026-08-30` | `database__vibe_research.db` | 5,069,770,752 B | 2026-08-30 21:20 |
| `2026-08-23` | `database__vibe_research.db` | 5,053,935,616 B | 2026-08-22 17:30 |
| 各目录 | `backend__vibe_research.db` / `backend_vibe_research.db` | 0 B | 2026-07-11 |
| `/d/$RECYCLE.BIN/…/vibe_research.db` | 0 B | — | 垃圾 |

**5.09 GB 与历史记载完全吻合 → 生产库未丢失，有 3 份可用快照（最新为 Sep-06 目录）。**

---

## B1-2 完整映射表：DB 文件 → 代码引用 → 配置来源 → 运行入口 → 环境属性 → 是否生产目标

| DB 文件 | 代码引用 | 配置来源 | 运行入口 | 环境属性 | 生产目标 |
|---|---|---|---|---|---|
| **`backend/database/vibe_research.db`（不存在）** | `db.py:_DB_PATH`（声明的唯一真源）+ ~100 处 `sqlite3.connect` + 4 处硬编码 `C:/Users/LIU/…` + 3 处相对路径 `"database/vibe_research.db"` | **无**（硬编码；`.env` 经查**无任何 DB 配置**） | `run_daily.py` / `daily_collect` / `build_*` / `brain` / 审计脚本 | **生产** | ✅ **唯一生产目标（当前缺失）** |
| `backend/vibe_research.db`（0 B） | `healthcheck.py` 候选 2；`_backup_db_to_d.py` SOURCES[1] | 无 | 无 | 历史遗留空占位 | ❌ |
| `backend/data/strategy.db`（12 KB） | `market_amount.py: _DB_PATH = Path(__file__).parent/"data"/"strategy.db"` | 无 | `market_amount` | 策略小库 | ⚠️ 独立小库 |
| `backend/data/stock.db`（0 B） | **无任何代码引用** | — | — | 空占位 | ❌ |
| `daily-os/daily_os.db`（12 KB） | `daily-os/app.py: DB_PATH` | 无 | daily-os app | 独立库（测试用 `tmp_path` 隔离） | ⚠️ 独立小库 |
| `/d/AI研投系统备份/2026-09-06/vibe_research.db` | 备份产物 | `_backup_db_to_d.py` SOURCES[0] | 备份脚本 | **备份** | ✅ **生产库最新副本** |
| 2026-08-30 / 2026-08-23 的 `database__vibe_research.db` | 备份产物 | 同上 | 备份脚本 | 备份 | 旧快照 |
| `/d/$RECYCLE.BIN/…/vibe_research.db`（0 B） | 无 | — | 回收站 | 垃圾 | ❌ |

---

## B1-3 路径解析一致性（Runtime Target Trace 前置）

全部解析方式**收敛到同一目标** `backend/database/vibe_research.db`：

| 定义方式 | 示例模块 |
|---|---|
| `os.path.join(dirname(__file__), "database", "vibe_research.db")` | **`db.py`**（声明唯一真源）、`build_market_daily.py`、`build_derived_tables.py`、`data_freshness.py`、`daily_collect.py` |
| `Path(__file__).parent.parent / "database" / "vibe_research.db"` | `database/models.py` |
| `os.path.join(ROOT, "backend/database/vibe_research.db")` | `audit/cio_historical_baseline.py`、`audit/decision_audit_aug.py`、`deep_mine.py`、`export_three_trades.py` |
| 硬编码绝对路径 `C:/Users/LIU/WorkBuddy/…/database/vibe_research.db` | `build_crosswalk.py`、`build_industry_mapping.py`、`fetch_industry_map.py`、`leader_engine.py` |
| ⚠️ **相对路径** `"database/vibe_research.db"`（CWD 依赖） | `regime_backtest.py`、`risk_budget_backtest.py`、`score_predictive_validation.py` |
| 双候选探测 | `automation-1786030229208/healthcheck.py`（先 `database/`，后 `backend/`，只读 `mode=ro`） |

`db.py` 设计为 **fail loud**：`get_conn()` 在文件缺失时 `raise FileNotFoundError`（不静默）。

---

## B1-4 与 Git 恢复的因果关系（自证清白）

| 证据 | 结果 |
|---|---|
| `git ls-files \| grep '\.db$'` | **count = 0**（git 从不 track 任何 DB） |
| `git ls-tree df4ac04 backend/database/` | 仅 5 个非 db 文件（`.py` ×4 + manifest ×1） |
| `git ls-tree 074e467 backend/database/` | 同上 |
| `.gitignore` | 4 条 `*.db` 家族规则（`*.db` / `*.sqlite3` / `-wal` / `-shm` 等），注释「绝不入库」 |
| 本轮执行过的 git 命令 | 仅 `show-ref` / `for-each-ref` / `fsck` / `cat-file` / `rev-list` / `count-objects`；**未执行 `git clean`** |

**→ 结论：git 从未 track DB，且未执行 `git clean`；`reset --hard` / `checkout` 不会删除或覆盖未跟踪/被忽略的 `.db`。**
**本次 `.git` 损坏与恢复在原理上不可能删除 5GB 生产库。DB 缺席为既有状态**（Sep-06 备份时尚在工作树，之后由非 git 原因消失）。

---

## B1-5 发现的风险项（供 B2/B3/B4 跟进）

1. **运行时断链**（P0 级现象）：生产目标文件缺失 → 任何走 `db.get_conn()` 的入口都会 `FileNotFoundError`。
2. **多真源**：`db.py` 自称 single source of truth，但全项目 **114 处 `sqlite3.connect`**，仅 **14 个模块**引用 `db` 模块 → 约 100 处绕过单真源（正是 `db.py` docstring 所述 Phase 1.6 事故要消除的类别）。
3. **CWD 依赖**：3 个模块用相对路径 `"database/vibe_research.db"`，运行目录不同会指向不同库（甚至新建空库）。
4. **硬编码用户名**：4 处 `C:/Users/LIU/…`（当前 LIU 为真目录、JOY 为 junction，可解析，但换机即断）。
5. **无环境变量配置**：`.env` 不含任何 DB 配置，路径完全硬编码 → 无法在不改代码的情况下切换 DB 环境。
6. **备份可用**：D 盘 3 份快照（最新 5.09GB / 数据截至 2026-09-05 09:04），恢复窗口存在，但**恢复动作属写操作，不在本 READONLY 轮执行**。

---

## B1 结论

```yaml
P1_B1_DB_LOCATION:
  mode: READONLY
  db_files_in_worktree: 4            # 均 <= 12KB
  production_target_declared: "backend/database/vibe_research.db"
  production_target_exists: false    # ← 运行时会 FileNotFoundError
  production_db_5gb:
    found: true
    location: "/d/AI研投系统备份/2026-09-06/vibe_research.db"
    size_bytes: 5087100928
    data_as_of: "2026-09-05 09:04"
    older_snapshots: ["2026-08-30 (5.07GB)", "2026-08-23 (5.05GB)"]
  git_causation: EXONERATED          # git 从不 track .db, 未跑 git clean
  loop_closed: false                 # 声明一致 but 运行时缺失
  status: B1_COMPLETE_AWAITING_B2
```

**下一步：B2 · Runtime Target Trace**（静态追踪各运行入口实际解析的 DB 路径与失败模式，不连接 DB）。
