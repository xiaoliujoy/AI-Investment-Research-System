# P1 · DB Location & Runtime Dependency Audit — B3: Write Surface / Environment Split

- 日期：2026-09-09
- 阶段：P1-B3（承 B1 `..._B1_2026-09-09.md` / B2 `..._B2_2026-09-09.md`）
- 纪律：代码/配置 **READONLY**（不改代码、不 commit、不 push、不恢复 DB）
- 核心问题：**恢复 5GB 生产库之后，跑 pytest / 手工 CLI / automation / collector / backfill / 研究脚本，是否存在任何机会把生产库当成测试库或实验库写进去？**

> ⚠️ 本轮为获得行为级证据**执行了 pytest**（详见 §8 副作用披露）。`pytest` 属测试执行，非代码/数据变更；canonical 路径现状已还原为「不存在」，与审计开始时一致。

---

## 0. 结论摘要（先给答案）

**B3 判定：❌ FAIL — 存在 100% 确定的生产库污染通道，且已行为级复现。**

| 问题 | 结论 |
|---|---|
| Q1 谁可能写 5GB 生产库？ | **91 个 .py 文件**引用 `vibe_research.db`；其中 **35 个直连且含写 SQL**，另有 **9 个经 `models.get_db()` 间接写**。 |
| Q2 测试是否与生产隔离？ | ❌ **否**。`backend/conftest.py` **零 DB 隔离**（只有 sys.path + live marker）。隔离完全靠每个测试自觉。 |
| Q3 是否存在环境分离（dev/test/prod）？ | ❌ **不存在**。91 个引用中 **0 个环境变量配置源**；`.env` 无任何 DB 配置；无 `--db` / `DB_PATH` env override。 |
| Q4 恢复后跑 pytest 会不会污染生产库？ | 🔴 **会，且必然**。`test_pipeline_failure_visibility.py::test_daily_collect_exit_nonzero_on_incomplete` 无隔离，真实触发 `daily_collect.collect()` → **22,193 行 `commodity_daily` + 8 行 symbol_map + 6 行 option_watchlist + 5 张表 DDL**，且写入数据**日期到 2026-09-09（当天）**、**非确定性**。 |
| Q5 污染是否可事后甄别？ | 🔴 **不可甄别**。测试写入行的 `source` 字段与真实采集完全一致（`futures_foreign_hist` / `futures_zh_daily_sina`），写入后无法与真实数据区分。 |

**→ 对恢复动作的硬约束：恢复 5GB DB 之前，必须先落地测试隔离守卫；否则恢复后第一次跑 `pytest` 即污染。**

---

## 1. B3.1 · Write Surface Inventory

### 1.1 规模

| 指标 | 数量 |
|---|---|
| 引用 `vibe_research.db` 的 .py 文件 | **91** |
| ├ 其中直连 + 含写 SQL（INSERT/UPDATE/DELETE/DDL/executemany） | **35** |
| ├ 其中经 `models.get_db()` 间接写（无显式路径串） | **9** |
| └ 其中同时含 DDL + DML（自带建表能力） | **21** |
| 环境变量 / 配置源 | **0** |

### 1.2 直接写入面 TOP 15（按 DML 语句密度）

| 文件 | DML | DDL | 自带 init_db | 性质 |
|---|---|---|---|---|
| `backend/database/models.py` | 14 | 35 | ✅ | **schema 总源**（`init_db()` 建 23 张表） |
| `backend/fetch_industry_map.py` | 9 | 6 | ❌ | 采集 + 自建表 |
| `backend/write_decision_ledger.py` | 8 | 0 | ✅ | 16:30 automation A9 |
| `backend/_quick_today_import.py` | 8 | 0 | ❌ | 🟠 孤儿脚本（`_` 前缀） |
| `backend/os_layers/trading_discipline_engine.py` | 7 | 7 | ❌ | 交易纪律引擎 |
| `backend/build_industry_mapping.py` | 6 | 2 | ❌ | 采集 |
| `backend/ingest_sector_flow_westock.py` | 4 | 2 | ❌ | 18:30 westock 链 |
| `backend/sector_pipeline.py` / `build_decision_log.py` | 4 | 1~2 | ❌ | 生产链 |
| `backend/build_limit_up_daily.py` / `build_sector_daily.py` / `fill_stock_flow.py` / `tech_fill.py` | 4 | 0 | ❌ | 15:30 生产链 |
| `backend/trader_log.py` / `build_crosswalk.py` / `narrative_layers.py` | 3 | 1~3 | ❌ | 生产链 |
| **`backend/cio_decision_engine.py`** | 2 | 3 | ✅ | 🔴 **B2-F1**（自带 init_db） |
| **`backend/build_failure_log.py`** | 2 | 1 | ✅ | 🔴 **B2-F1**（自带 init_db） |

### 1.3 间接写入面（经 `models.get_db()`，静态扫不到路径串）

| 文件 | DML | DDL | 备注 |
|---|---|---|---|
| `backend/commodity_engine/collector.py` | 9 | 7 | 🔴 **本次污染主通道**（见 §3） |
| `backend/omi/storage.py` | 6 | 5 | OMI 期权观察层 |
| `backend/capital_score.py` | 3 | 1 | 自建 `stock_capital_score` |
| `backend/import_tdx.py` | 3 | 0 | ✅ 有 `--dry-run` |
| `backend/commodity_engine/scoring.py` | 3 | 0 | |
| `backend/watchlist/manager.py` | 3 | 0 | |
| `backend/release_gate.py` | 2 | 0 | 🔴 治理表，误写后果最高 |
| `backend/global_market/data_adapter/collector.py` | 2 | 0 | |
| `backend/write_decision_ledger.py` | 8 | 0 | 同时出现在两类 |

---

## 2. B3.2 · Environment Split（环境分离）

**结论：不存在。**

| 检查项 | 结果 |
|---|---|
| 环境变量配置源（`os.getenv` / `os.environ` / `DATABASE_URL` / `*_DB`） | **0 处**（全项目仅 `learning_center.py:48` 有一个 `ADAPTIVE_FEEDBACK_ENABLED`，与 DB 无关） |
| `.env` 中的 DB 配置 | **无**（`.env` 无任何 db/database/sqlite 键） |
| pytest 配置文件（`pytest.ini` / `pyproject.toml` / `setup.cfg` / `tox.ini`） | **0 个** → 无 rootdir 约束、无统一 marker/隔离策略 |
| CLI `--db` / `--env` 参数 | 无（仅 `import_tdx` / `build_market_daily` 等有 `--dry-run`） |
| 只读连接模式 | **仅 1 处**：`healthcheck.py` 用 `sqlite3.connect(..., mode=ro)` |
| 唯一"隔离范式" | `daily-os/conftest.py`（`tmp_path` + teardown 恢复 `A.DB_PATH`）✅ |

### 三个 conftest 对比

| conftest | DB 隔离 | 说明 |
|---|---|---|
| `backend/conftest.py` | ❌ **无** | 仅 `sys.path.insert` + `live` marker 注册 |
| `trading_os/tests/conftest.py` | ❌ 无 | 仅 sys.path |
| `daily-os/conftest.py` | ✅ **有** | 保存原 `A.DB_PATH` / `A.TRADING_DB` → 指向 `tmp_path` → teardown 恢复；注释明确"真实 daily_os.db / TRADING_DB 绝对不碰" |

**→ 生产与测试共用同一物理文件，唯一分界是"测试作者记不记得打桩"。没有兜底。**

---

## 3. B3.3 · Test Isolation — 行为级 Injection（核心证据）

### 3.1 静态分类的失效（方法论警示）

静态扫描（是否含 DB 路径串 / 是否 import models / 是否有 monkeypatch）把 36 个测试文件分成三组：

| 组 | 数量 | 判定 |
|---|---|---|
| 触碰 DB + 有隔离标记 | 11 | ✅ |
| 触碰 DB + 无隔离 | 1 | `backend/tests/replay_engine.py`（非 `test_` 前缀，pytest 默认不收集） |
| 未触碰 DB | 24 | — |

🔴 **`test_pipeline_failure_visibility.py` 被静态判为「未触碰 DB」——但它实际写了 22,193 行。**
因为它既无 DB 路径串、也不 import `models`，而是通过 `import daily_collect` → `collector.py` → `models.get_db()` **三级间接**触达。

> **结论：本项目的写入面无法靠静态分类判定，只能靠行为级 injection。**

### 3.2 Injection #1 · hook + 沙箱重定向（canonical 缺失态）

方法：pytest 插件 hook `sqlite3.connect`，凡目标为 canonical 一律重定向到临时文件（保证 canonical 零污染），并用 `set_trace_callback` 记录全部 SQL 与调用栈。

```
canonical connect attempts: 38
```

**全部 38 次中，产生 DML 的 100% 来自单一测试：**

```
test_pipeline_failure_visibility.py::test_daily_collect_exit_nonzero_on_incomplete (call)
```

| # | DML 语句数 | 调用链（简化） |
|---|---|---|
| #2 | 6 | `daily_collect.collect` → `ensure_commodity_daily` → `collector.ensure_schema` → `models.get_db` → CREATE ×6 |
| #3 | 8 | 同上 → `init_symbol_map` → INSERT `commodity_symbol_map` |
| #6 | 4,548 | 同上 → `save_commodity_rows` → INSERT `commodity_daily` |
| #9 | 5,275 | 同上 |
| #12 | 2,053 | 同上 |
| #15 | 3,489 | 同上 |
| #18 | 4,239 | 同上 |
| #21 | 2,589 | 同上 |
| #32 | 6 | `ensure_commodity_factor` → CREATE ×6 |
| #36 | 1 | `ensure_regime_history` → `db.get_conn` → CREATE `regime_history` |

### 3.3 Injection #2 · 预置完整生产 schema 的沙箱库

方法：先用 `models.init_db()` 在沙箱建 23 张生产表，再把 canonical 重定向到它，跑全量 suite，看哪些表被写入。

```
canonical connect attempts: 38
sandbox tables with rows > 0（= 若恢复生产库，会被真实写入的表）:
   commodity_daily                          22193
   commodity_symbol_map                         8
   option_watchlist                             6
```

（另 `regime_history` / `commodity_factor_daily` / `commodity_supply_daily` 被 CREATE，0 行）

### 3.4 污染数据性质（对比生产备份，只读查询）

| 维度 | 生产库 `commodity_daily` | pytest 写入 |
|---|---|---|
| 行数 | 32,540 | **22,193** |
| date 范围 | 1996-07-29 ~ **2026-09-04** | 2005-01-04 ~ **2026-09-09（当天）** |
| symbol | 8（AG0/AU0/**CL**/CU0/GC/**HG**/RB0/SC0） | 6（AG0/AU0/CU0/GC/RB0/SC0） |
| `source` 字段 | `futures_foreign_hist` / `futures_zh_daily_sina` | **完全相同** |

🔴 **三重危害**：
1. **日期覆盖到今天** → 测试会写入生产库尚不存在的 09-05~09-09 期货数据，与后续真实采集的同一天数据**互相 REPLACE**；
2. **数据非确定性** → 每次跑测试拉到的 close 不同，生产库被随机值污染，且不可复现；
3. **`source` 无法甄别** → 污染行与真实采集行在来源标签上完全一致，事后无法区分、无法回滚。

### 3.5 T1#3 结论纠偏（重要）

工作区记忆记载：「T1#3 … 已修：autouse fixture 打桩 7 写入器 → 2 passed / DB 零变更」。

**实测：该文件当前无任何 autouse fixture，无 DB 隔离。**

| 证据 | 结果 |
|---|---|
| `grep -rn "autouse" backend/` | 仅 2 处：`test_data_health_fail_closed.py:56`、`test_investment_committee_sentiment_contract.py:64` |
| `git log -- backend/tests/test_pipeline_failure_visibility.py` | 仅 1 个 commit `df4ac04` |
| `git status --porcelain` 该文件 | 无本地修改 → 工作区 = HEAD = `df4ac04` |
| 实际行为 | 真实调用 `daily_collect.collect()`，联网拉数，写 22,193 行 |

**→ T1#3 的「DB 零变更」是在 canonical DB 缺失状态下测得的假象（库不存在 → 写入落在新建空库 → 比对基线为空 → 看似零变更）。该结论需要作废/降级，修复实际未落地。**

---

## 4. B3.4 · 其他写入面

### 4.1 实验 / 回填脚本（写生产库，无 dry-run）

| 脚本 | DML | `--dry-run` | 风险 |
|---|---|---|---|
| `backend/risk_budget_stress_sim.py` | 1 | ❌ 无 | 🟠 **名带 sim 的实验脚本直接写生产库** |
| `backend/global_history_backfill.py` | 3 | ❌ 无 | 🟠 回填不可回滚 |
| `backend/fill_market_cap.py` / `fill_stock_flow.py` / `fill_daily_quotes.py` | 1~4 | ❌ 无 | 🟠 回填 |
| `backend/_quick_today_import.py` / `_add_systemic.py` | 8 / 1 | ❌ 无 | 🟠 孤儿脚本（`_` 前缀，8 个 `backend/_*.py` 之一） |
| `backend/import_tdx.py` | 3 | ✅ **有** | 🟢 范式 |
| `backend/build_market_daily.py` | 2 | ✅ **有** | 🟢 范式 |

**→ dry-run 支持率：写入面 8 个实验/回填脚本中 **2 个有**（均为生产采集链），实验与回填类 **0/6**。**

### 4.2 非 `test_` 前缀的 tests 目录脚本

| 文件 | 行为 | 是否自动收集 |
|---|---|---|
| `backend/tests/replay_engine.py` | `db_path = str(models.DB_PATH) if os.path.exists(...) else None` → **读生产库** | ❌ 不自动收集（手工运行） |
| `backend/tests/build_golden_master.py` | 生成黄金样本 | ❌ 不自动收集 |

---

## 5. B3.5 · Test Harness Reliability（四维）

| 维度 | 实测 | 判定 |
|---|---|---|
| Collection | **192 collected + 1 error**；`backend/test_gate.py` → `ModuleNotFoundError: No module named 'os2_report'`，且触发 `Interrupted: 1 error during collection`（**整个 suite 被中断**） | ❌ FAIL |
| Population | collected = 192 > 0 | ✅ |
| Execution | 186 passed / 4 failed / 2 errors | ⚠️ 部分 |
| Result Integrity | 见 §3.5：T1#3「DB 零变更」结论失效 | ❌ FAIL |

**4 failed / 2 errors 明细**（与 DB 缺失的因果关系待确认，均非本次写入面）：
- `quant-lab/tests/test_h1_fetch_resilience.py` × 2
- `trading_os/tests/test_g2_supervisor.py` × 2
- `daily-os/test_e2e.py` / `test_integration.py` × 2（`AttributeError: module 'app' has no attribute ...`）

---

## 6. B3 判定与 Backlog

```yaml
P1_B3_WRITE_SURFACE:
  mode: READONLY (code/config) + pytest behavioral injection
  write_surface_files: 91        # 引用 vibe_research.db
  direct_writers: 35
  indirect_writers: 9
  env_config_source: 0           # 无环境分离
  global_conftest_isolation: 0   # backend/ 与 trading_os/ 均无
  prod_db_pollution_channel: CONFIRMED_BEHAVIORAL
  pollution_trigger: "pytest backend/tests/test_pipeline_failure_visibility.py"
  pollution_volume: "22,193 rows commodity_daily + 8 + 6 rows, 5 tables DDL, 38 connections"
  pollution_distinguishable: false
  status: B3_FAIL
```

| ID | 问题 | 等级 | 归属 |
|---|---|---|---|
| **B3-F1** | `test_pipeline_failure_visibility.py` 无 DB 隔离 → 恢复后跑 pytest 必然污染生产库（22k 行，不可甄别） | 🔴 **P0** | **恢复前置阻断项** |
| **B3-F2** | `backend/conftest.py` 零全局 DB 隔离；隔离靠作者自觉，无兜底 | 🔴 High | backlog（测试基础设施） |
| **B3-F3** | 无任何环境分离（0 配置源、0 pytest 配置、0 env override） | 🔴 High | 并入 P1-C |
| **B3-F4** | 跑 pytest 会在 canonical 路径创建/写入 DB 文件（已实证 3.76 MB） | 🟡 Medium | 与 B2-F4 合并 |
| **B3-F5** | `backend/test_gate.py` collection error → 整个 suite 被 Interrupted | 🟡 Medium | T1#3 遗留 |
| **B3-F6** | 实验/回填脚本 6/8 无 `--dry-run`，直接写生产库 | 🟡 Medium | backlog |
| **B3-F7** | T1#3「DB 零变更」结论失效（缺失态假象），需作废并重新定义验收口径 | 🟡 Medium | T1#3 纠偏 |

---

## 7. 对恢复动作的硬约束（B4 前置）

> **不装隔离，不恢复。**

### 7.1 恢复前置检查清单

- [ ] **P0** 落地 `backend/conftest.py` 全局 DB 隔离守卫（推荐 Option A）
- [ ] **P0** 恢复后立即验证：在 canonical 库存在状态下跑 pytest，库 mtime + `commodity_daily` 行数**零变化**
- [ ] 恢复前确认 `backend/database/` 下无残留 db 文件（当前：**已清空** ✅）
- [ ] 恢复后立刻做一次**只读 healthcheck**（`mode=ro`）
- [ ] 恢复后立刻做一次**全量备份**到 D 盘新目录（不覆盖 2026-09-06 那份）

### 7.2 三个隔离方案（待用户拍板，本轮不实施）

| 方案 | 内容 | 优势 | 劣势 | 变更面 |
|---|---|---|---|---|
| **A（推荐）** | `backend/conftest.py` 加 autouse fixture：把 `database.models.DB_PATH` 与 `db._DB_PATH` 重定向到 `tmp_path` 空库；`--allow-prod-db` 显式开关才放行 | 全局兜底，新测试自动受保护；复用 daily-os 已有范式 | 需要整改可能依赖真实库的测试 | 1 个文件（测试基础设施，零生产影响） |
| **B** | 只修 `test_pipeline_failure_visibility.py`（打桩 `daily_collect` 的 DB 路径） | 最小变更 | 只堵一个点；下一个新测试照样污染 | 1 个文件 |
| **C** | 不装隔离，改为「恢复后禁止在 canonical 环境跑 pytest」，测试一律在 DB 副本上跑 | 零代码变更 | 依赖人记住，无强制；违反 T1#3 铁律 | 0 |

**我的建议：A。** 理由：B3-F1 已证明「靠作者自觉」这条路线失败过一次（该文件 docstring 白纸黑字写着"纯内存 monkeypatch，不碰生产数据、不联网"，实际两条都违反）。只有全局兜底能让这条铁律真正成立。

---

## 8. 纪律遵守声明与副作用披露

### 8.1 遵守

- ✅ 未修改任何代码、配置、数据库内容
- ✅ 未 commit / 未 push / 未触发任何 automation
- ✅ 生产库 & 备份库全程以 `mode=ro` 只读打开（仅 PRAGMA / COUNT / 抽样，无写入）
- ✅ 未恢复 / 未复制 / 未移动任何 DB 文件

### 8.2 副作用（诚实披露）

| 事件 | 说明 | 处置 |
|---|---|---|
| 🔴 **canonical 路径被创建 DB 文件** | 09:24 第一次执行 `pytest -q`（未挂探针）时，`test_pipeline_failure_visibility.py` 真实写库，在 `backend/database/` 生成 **3,764,224 B（3.76 MB）** 的 `vibe_research.db`，含 `commodity_daily` 22,193 行 | **已移出**为证据：`C:\Users\LIU\AppData\Local\Temp\b3_artifact_0byte_vibe_research.db`（移动，非删除） |
| 当前 canonical 路径状态 | `backend/database/vibe_research.db` **不存在** | ✅ 与审计开始时一致 |
| 第二次 / 第三次 pytest | 均挂载重定向探针，canonical 零写入 | ✅ |

> 该副作用本身就是 B3-F1 的**最强证据**：一次裸 `pytest` 就在生产路径上凭空造出一个 3.76 MB 库。

### 8.3 证据工件

| 文件 | 内容 |
|---|---|
| `C:\Users\LIU\AppData\Local\Temp\b3_artifact_0byte_vibe_research.db` | 裸 pytest 误建库（3.76 MB，22,193 行） |
| `C:\Users\LIU\AppData\Local\Temp\b3_probe_*/probe_log.json` | Injection #1：38 次 canonical 连接 + 调用栈 + SQL |
| `C:\Users\LIU\AppData\Local\Temp\b3inj2\vibe_research.db` | Injection #2：预置 23 张生产表的沙箱库（被写入 3 张） |
| `C:\Users\LIU\AppData\Local\Temp\b3_scan*.json` | 静态扫描原始结果 |

---

## 9. 下一步

1. **B4 · Canonical Runtime Verdict**（B1+B2+B3 汇总裁定）
2. **用户拍板隔离方案 A / B / C**（§7.2）→ 本轮不实施
3. **实施隔离 → 恢复 5GB DB → 只读 healthcheck → Recovery Verdict**
4. T1#3 结论纠偏归档（B3-F7）

---

# 补录 · P0 隔离实施与恢复前验证门（2026-09-09 10:00~10:06）

> 用户裁决：**采用 A'（全局隔离 + 生产库硬拒绝）**，并在恢复前增设验证门。
> 本补录记录实施内容、新发现（B3-F8）与验证结果（验证门 ①~④ 全通过）。

## P0-A · 实施内容

| # | 文件 | 变更 |
|---|---|---|
| 1 | `backend/conftest.py` | **重写**：新增 `--allow-prod-db` 选项 + session 级 autouse 守卫 fixture（P0-A 重定向 + P0-B 硬拒绝）+ `proddb` marker |
| 2 | `backend/tests/test_prod_db_guard.py` | **新增**：守卫自身的回归测试（8 项）——防止守卫将来被改坏而无人发现 |
| 3 | `backend/tests/test_pipeline_failure_visibility.py` | **最小修改**：给 `daily_collect._run` 打桩（B3-F8 子进程绕过） |

### P0-A 重定向
```python
db._DB_PATH        →  <tmp>/db0/pytest_sandbox.db
database.models.DB_PATH →  同上（Path 对象）
沙箱预置生产 schema（models.init_db()，23 张表）
```
> 沙箱文件名刻意不含 `vibe_research.db` 子串，避免与 P0-B 判据自相冲突。

### P0-B 硬拒绝
```python
sqlite3.connect(target)  →  若 "vibe_research.db" in str(target) 且非沙箱  →  raise RuntimeError
```
覆盖：绝对路径 / CWD 相对路径（`database/vibe_research.db`）/ `file:` URI / 历史空壳 `backend/vibe_research.db`。
放行：`:memory:`、沙箱、`--allow-prod-db` 显式 opt-in。

### 守卫自测（8 passed）
`test_prod_db_guard.py`：5 种生产库连接形式逐个断言 HARD REJECT + `:memory:` 不被误伤 + 两个 `DB_PATH` 已重定向且沙箱存在 + 沙箱含生产 schema。

---

## 🔴 新发现 · B3-F8：子进程绕过 monkeypatch（进程边界盲区）

**现象**：装上 P0-A + P0-B 后跑全量，canonical 路径**仍被创建 0 字节空库**。

**定位**：逐文件二分 → 唯一创建者仍是 `test_pipeline_failure_visibility.py`。

**根因**：
```python
backend/daily_collect.py:84   _run()  →  subprocess.run([PY, path], cwd=ROOT)
backend/daily_collect.py:193  ensure_individual_quotes()  →  subprocess.run([PY, fill_daily_quotes.py, target])
```
**子进程不加载 pytest conftest → 不继承任何 monkeypatch → 守卫完全失效。**

**危害等级**：🔴 高。当前只是创建 0 字节空库（因为 canonical 不存在，子脚本随即 no such table 崩溃）；**一旦恢复 5GB 生产库，这些子进程会连上真实生产库并执行各自的写入逻辑**（`flow` / `global_align` / `verify_completeness` / `fill_daily_quotes` 等）。

**已处置**：在测试内打桩 `daily_collect._run`（该测试本就打桩 `ensure_individual_quotes`，风格一致）。

**残留**：这是**类别性**问题，不是点状问题。任何测试只要触发 subprocess，就能绕过一切基于 monkeypatch 的隔离。根治需要真正的环境分离（见下）。

---

## 验证门（用户序列 ①~④）

| 步 | 检查 | 结果 |
|---|---|---|
| ① | P0 隔离已实施 | ✅ 3 个文件 |
| ② | canonical DB 仍然不存在 | ✅ 不存在 |
| ③ | pytest 全量（backend/，ignore test_gate.py） | ✅ **138 passed, 0 failed, 61.12s** |
| ④a | canonical 仍不存在 | ✅ **未创建**（前后两次验证均确认） |
| ④b | sandbox 有预期写入 | ✅ **4,022,272 B**（空 schema 基线 258,048 B → +3,764,224 B） |

### ④b 沙箱落点明细（只读核对）

| 表 | 隔离前落点 | 隔离后落点 |
|---|---|---|
| `commodity_daily` | 生产库 22,193 行 | **沙箱 22,193 行** |
| `commodity_symbol_map` | 生产库 8 行 | 沙箱 8 行 |
| `option_watchlist` | 生产库 6 行 | 沙箱 6 行 |
| `regime_history` / `stock_daily` / `sector_daily` / `market_daily` | 生产库建表/写入 | 沙箱 0 行（仅建表） |

沙箱最新行：`('2026-09-09', 'GC', 4417.4, 'futures_foreign_hist')`
（对比 B3-F1 首次观测 `4415.7` → **再次证明写入数据非确定性**）

**→ 结论：原本会落进生产库的 3.76 MB / 22,193 行，现已 100% 改道沙箱，生产库路径零触碰。B3-F1 关闭。**

---

## T1#3 状态正式变更

```
T1#3 · Backend Test DB Write Surface Audit
  原判定：PASS（autouse 打桩 7 写入器 / DB 零变更）
  现判定：🔴 REVOKED（结论作废，不得再作为任何 Release Gate 证据）
  作废依据：行为级反证 —— 裸 pytest 创建 canonical DB 并写入 22,193 行
  失效机理：验收在 canonical DB 缺失态下进行（写入落在新建空库，比对基线为空 → 假象）
  重新验收：本轮 P0 实施后，以验证门 ④a/④b 为新口径（canonical 零触碰 + 沙箱有写入）
```

---

## 证据工件（`.audit/evidence/B3/`，全部保留）

| 文件 | 说明 |
|---|---|
| `pytest_unisolated_created_vibe_research_3.76MB.db` | 🔴 裸 pytest 误建库（22,193 行） |
| `canonical_0byte_shell_created_during_injection2.db` | injection #2 期间创建的 0 字节空壳 |
| `canonical_0byte_shell_created_with_guard_0956.db` | 🔴 **守卫已装仍被创建** → B3-F8 证据 |
| `post_isolation_sandbox_22k_rows.db` | ✅ 隔离后沙箱（4.02 MB，22,193 行） |
| `injection1_probe_log.json` | 38 次 canonical 连接 + 调用栈 + SQL |
| `injection2_sandbox_db/` | 预置 23 张生产表的沙箱 |
| `b3_scan*.py` / `b3_probe*.py` / `*.json` | 静态扫描与注入脚本 |

---

## 恢复前剩余事项

| 项 | 状态 |
|---|---|
| 验证门 ①~④ | ✅ 全通过 |
| **B3-F8 类别性残留** | ⏳ 待用户拍板（见下） |
| 验证门 ⑤~⑩（恢复 + healthcheck + 基线 + 复测） | 🔴 等授权 |

### B3-F8 根治选项（需用户授权，本轮未做）

| 方案 | 内容 | 变更面 | 效果 |
|---|---|---|---|
| **E1（推荐）** | `backend/db.py` + `backend/database/models.py` 支持 `VIBE_DB_PATH` 环境变量 override（env 未设 → 行为 100% 不变）；conftest 设置该 env → **子进程自动继承** | 2 个生产文件，各 ~3 行，向后兼容 | 覆盖走 `db.py`/`models.py` 的子进程；不覆盖 ~100 处硬编码路径 |
| E2 | 逐个给子进程脚本加 `--db` 参数 | 面大 | 彻底但侵入 |
| E3 | 维持现状（仅靠测试内打桩） | 0 | 遗留类别性风险，靠 code review 兜底 |

**说明**：E1 只解一半（硬编码路径仍漏），彻底解要等到 P1-C 的 Canonical Universe 单点契约源。但 E1 是"环境分离从 0 到 1"的正经起点，且零行为变化。

---

# 补录 2 · E1 实施与 Gate ⑤-Pre（2026-09-09 10:13~10:25）

> 用户裁决：**E1 批准 / E2 暂缓 / E3 否决 / 恢复继续 BLOCKED**，并要求
> E1 完成后先做 B4 再进恢复 Gate ⑤。本补录记录 E1 实施、Gate ⑤-Pre 验证，
> 以及一个**必须诚实说明的结果：E1 单独不足以关闭 B3-F8**。

## E1 · 实施（按批准 scope）

| 文件 | 变更 |
|---|---|
| `backend/db.py` | `_DB_PATH` = `os.environ.get("VIBE_DB_PATH") or _DEFAULT_DB_PATH` |
| `backend/database/models.py` | `DB_PATH` 同上口径（Path 对象）；新增 `import os` |
| `backend/conftest.py` | 守卫 fixture 内 `mp.setenv("VIBE_DB_PATH", sandbox)` → 子进程自动继承 |

**向后兼容性**：env 未设置时，两个文件的行为与历史 **100% 一致**（生产环境不设该变量 → 零影响）。

## Gate ⑤-Pre · Subprocess Isolation 专项验证

新增 `backend/tests/test_subprocess_db_isolation.py`（5 项），**全部 PASSED**：

| # | 验证项 | 结果 |
|---|---|---|
| 1 | 主进程拿到 `VIBE_DB_PATH`，且 `models.DB_PATH` / `db._DB_PATH` 与之对齐 | ✅ |
| 2 | 子进程继承 `VIBE_DB_PATH`（`subprocess` 跑 `os.environ` 打印） | ✅ |
| 3 | 子进程解析 `models.DB_PATH` / `db._DB_PATH` = 沙箱 | ✅ |
| 3 | 子进程**真实写入** → 落在沙箱（`subprocess_probe` 表收到行） | ✅ |
| 4 | canonical 在子进程执行期间 **零 connect / create / write** | ✅ |
| C | **对照实验**：剔除 `VIBE_DB_PATH` 后，子进程解析回 canonical（只解析不连接，零副作用） | ✅ |

对照组证明：隔离确实由 `VIBE_DB_PATH` 生效，而非碰巧。

---

## 🔴 关键结果：E1 单独不能关闭 B3-F8

**验证方法**：临时复制 `test_pipeline_failure_visibility` 的故障注入，**故意不打桩 `daily_collect._run`**，让 subprocess 真实运行，观察 canonical。

**结果**：`assert None == (0, 1788920165607868100)` → **canonical 仍被创建 0 字节空库。**

**根因定位**（逐个脚本实跑，均带 `VIBE_DB_PATH`）：

| 脚本 | 路径定义 | 是否触碰 canonical |
|---|---|---|
| `tdx_daily_import.py` | `Path(__file__).parent / "database" / "vibe_research.db"` | 未触碰（提前退出） |
| `fill_stock_flow.py` | `Path(__file__).parent / "database" / "vibe_research.db"` | 🔴 **创建 0 B** |
| `build_derived_tables.py` | `os.path.join(ROOT, "database", "vibe_research.db")` | 🔴 **创建 0 B** |
| `data_freshness.py` | `os.path.join(ROOT, "database", "vibe_research.db")` | 🔴 **创建 0 B** |

**→ 这些脚本用 `__file__` / `ROOT` 硬编码锚定，不读 `db.py` / `models.py`，env override 对它们无效。**
这正是 B3-F3「~100 处硬编码路径」的实证，也是 E1 的已知边界（实施前已声明：E1 只覆盖走 db.py/models.py 的进程）。

---

## E1.6 · 补充：subprocess 硬拒绝（沿用 P0-B 哲学）

既然无法从路径侧拦截（脚本不读 env），改从**调用侧**拦截。在 `backend/conftest.py` 守卫内追加：

```python
subprocess.run(args)  →  若 args 是 "python <backend 下任意 .py>"  →  raise RuntimeError
```

- 判据：`args[0]` 是 python 解释器 且 `args[1]` 是 `BACKEND` 目录下的 `.py`
- 放行：`--allow-subprocess` 显式 opt-in
- **不改任何生产代码**，覆盖面不依赖脚本内部用什么路径定义方式

### E1.6 验证（不打桩 subprocess）

```
steps: ['tdx','quotes_fallback','sector','cap','flow','global_align',
        'commodity_daily','commodity_health','commodity_factor',
        'regime_history','verify_completeness']
critical_ok = False
canonical   = 未创建 ✅
```
11 个 step 全部执行，subprocess 被拦截走 except，canonical **零触碰**。

---

## 全量验证（E1 + E1.6 之后）

| 项 | 结果 |
|---|---|
| `pytest backend/` | ✅ **145 passed / 0 failed / 65.24s**（138 + 新增 7 项守卫测试） |
| canonical | ✅ **不存在**（零创建） |
| sandbox | ✅ **4,026,368 B**（基线 258,048 B） |

---

## B3-F8 状态与残留

```yaml
B3-F8:
  subprocess.run 通道: CLOSED        # E1（env）+ E1.6（硬拒绝）双重覆盖
  其它进程逃逸面（未覆盖）:
    - backend/cli_runtime.py:168          subprocess.Popen
    - backend/run_pathA_global_backfill.py:71  subprocess.call
  说明: 这两个入口当前无测试触发；若将来有，需把 E1.6 的守卫扩展到 Popen/call/check_output/os.system
```

**E1 + E1.6 ≠ DB 架构问题解决。** ~100 处硬编码路径仍不受控，根目录是 P1-C 的 Canonical Universe 单点契约源，两者不可混为一谈。

---

## 当前总状态

```yaml
P1_B3:
  B3-F1: CLOSED            # A' 主进程隔离 + 验证门 ④a/④b
  B3-F8: CLOSED_SUBPROCESS_RUN   # E1 + E1.6；Popen/call 为已知残留
  B3-F3: OPEN -> P1-C      # 环境分离只做了 1/N（db.py + models.py）
  T1#3:  REVOKED
  recovery: BLOCKED        # 等待 B4
  next: B4 · Canonical Runtime Verdict
```

### 本轮文件变更清单

| 文件 | 类型 |
|---|---|
| `backend/conftest.py` | 修改（P0-A + P0-B + E1 setenv + E1.6 subprocess 守卫 + 两个 option） |
| `backend/db.py` | 修改（E1 env override，向后兼容） |
| `backend/database/models.py` | 修改（E1 env override，向后兼容） |
| `backend/tests/test_prod_db_guard.py` | 新增（守卫自回归，10 项） |
| `backend/tests/test_subprocess_db_isolation.py` | 新增（Gate ⑤-Pre，5 项） |
| `backend/tests/test_pipeline_failure_visibility.py` | 修改（打桩 `daily_collect._run`） |
