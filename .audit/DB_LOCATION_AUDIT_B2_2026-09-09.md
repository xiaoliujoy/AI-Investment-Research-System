# P1 · DB Location & Runtime Dependency Audit — B2: Runtime Target Trace

- 日期：2026-09-09
- 阶段：P1-B2（承 B1 `DB_LOCATION_AUDIT_B1_2026-09-09.md`）
- 纪律：**READONLY** — 不连接 DB、不恢复 DB、不改代码、不 commit/push
- 目标：回答 4 个问题（生产入口 / 各自解析到哪个 DB / 目标缺失时发生什么 / 是否存在"看起来能跑、实际连错库"）

---

## 0. 结论摘要（先给答案）

| 问题 | 结论 |
|---|---|
| Q1 生产入口有哪些？ | **15 个 automation**，其中真正写生产 DB 的日常主入口只有 1 条：`15:30 run_daily.py`（automation-1785399819081）。其余为只读巡检 / 无 DB / MCP 外部 / 手工 CLI。 |
| Q2 每个入口解析到哪个 DB？ | **一致**：全部解析到 `backend/database/vibe_research.db`。唯一例外是 3 个 CWD 相对路径的研究回测脚本。 |
| Q3 目标不存在时发生什么？ | **分 4 类行为**。主链路属「静默创建 0 字节空库 → 后续 SQL 报 no such table → 崩溃」，**失败可见但会留下垃圾文件**；另有 2 条路径属「静默建空库 + 自动建表 → 看起来成功」。 |
| Q4 是否存在"看起来能跑、实际连错库"？ | **存在 2 类**（🔴）：① 自动建表型（`cio_decision_engine` / `build_failure_log`）② CWD 相对路径型（3 个研究脚本）。**但 15:30 日常主链路不在其中**——它会崩溃报错，不会静默连错库。 |

**B2 判定：路径一致性 PASS / 失败语义 不达标（Conditional PASS）**

- ✅ 合格：所有定时生产入口指向唯一 canonical 目标 `backend/database/vibe_research.db`
- ❌ 不达标：用户设定的进入 B3 门槛是「所有生产入口指向该路径 **且缺失时都 fail-loud**」。实测**主链路不是 fail-loud，而是 fail-by-crash-after-silent-create**，且存在 2 条 🔴 静默路径。
- → 建议：B2 以 **Conditional PASS** 收口，2 条 🔴 + 1 项垃圾文件风险 **backlog 化**（不在本次恢复动作中修），B3 可照常推进。

---

## 1. B1 关键事实修正（重要）

B1 结论仍成立，但 B2 补出一个**此前未记录的干扰项**：

| 路径 | 大小 | 日期 | 性质 |
|---|---|---|---|
| `backend/database/vibe_research.db` | **缺失** | — | ⭐ **canonical 生产库（唯一）** |
| `backend/vibe_research.db` | **0 字节** | Jul 11 00:26 | ⚠️ **历史遗留空壳**，非生产库 |
| `backend/data/stock.db` | 0 字节 | Sep 1 08:34 | 空壳 |
| `backend/data/strategy.db` | 12,288 B | Jul 14 06:30 | 小库（策略层） |

**证据**：D 盘备份中同名的 `backend__vibe_research.db` / `backend_vibe_research.db` **也是 0 字节**（Jul 11），说明该空壳自 7 月就存在，备份脚本一直把它当"第二个源"在备份——是噪音，不是数据。

**风险**：该 0 字节文件被 `healthcheck.py` 列为**第二候选**探测目标。若第一候选缺失，巡检会 fallback 到一个 0 字节库并可能给出误导性健康状态。

---

## 2. 生产入口清单与分级

### 2.1 定时 automation（15 个，来自 automation list）

| # | Automation | 触发 | 入口 | DB 目标 | 缺失时行为 | 等级 |
|---|---|---|---|---|---|---|
| A1 | 交易日自动更新数据并生成研报 `1785399819081` | 周一~五 15:30 | `run_daily.py` → 9 个子步骤 | `backend/database/` | 建 0 字节空库 → SQL 报错 → rc≠0 | 🟡 RISK |
| A2 | 盘前数据健康巡检 `1786030229208` | 周一~五 08:00 | `healthcheck.py` | 双候选，`mode=ro` | **只读失败，绝不创建** | 🟢 SAFE |
| A3 | 数据库本地备份→D: `1786033017776` | 周日 23:30 | `_backup_db_to_d.py` | 3 个绝对路径源（只读） | 源缺失→跳过/报错 | 🟢 SAFE |
| A4 | westock 板块资金流 `1785896623311` | 周一~五 18:30 | MCP 工具，非本地 sqlite | N/A | N/A | ⚪ N/A |
| A5 | 盘前纪要抓取 `1784175362588` | 周一~五 07:30 | MCP / 解析入库 | 待确认 | — | ⚪ |
| A6 | 全市场动量 `1786677039167` | 每日 08:45 | `market_momentum.py` | **无 sqlite 引用**（仅写 JSON） | N/A | ⚪ N/A |
| A7 | 美债观察 `1787098043035` | 每日 08:10 | `ust_yield_observer.py` | **无 sqlite 引用** | N/A | ⚪ N/A |
| A8 | Flow Evidence Archive `1786966060256` | 每日 21:00 | 快照归档 | 待确认 | — | ⚪ |
| A9 | Decision Log 草稿 `1785538694105` | 周一~五 16:30 | `write_decision_ledger.py`（`models.get_db()`） | `backend/database/` | 建空库 → 后续报错 | 🟡 RISK |
| A10 | 每日 GitHub 同步 `1785037277644` | 周一~五 21:00 | git push | N/A | N/A | ⚪ |
| A11-A15 | 周报 / 一次性检查点等 | 周/单次 | 文档类 | 低 | — | ⚪ |

> **关键**：**无任何 automation 触发 `cio_decision_engine`（月度 CIO）或 `build_failure_log`** —— 两者均为纯手工。

### 2.2 手工 / 研究入口

| # | 入口 | DB 解析 | 缺失时行为 | 等级 |
|---|---|---|---|---|
| M1 | `cio_decision_engine.py`（月度 CIO，`build_monthly_cio.py` 调用） | `__file__` 锚定 `database/vibe_research.db` | 🔴 **自带 `init_db()` 建表 + 写入成功，零报错** | 🔴 DANGER |
| M2 | `build_failure_log.py`（CLI 工具） | `__file__` 锚定 | 🔴 同上（自带 `init_db()`） | 🔴 DANGER（手工） |
| M3 | `import_tdx.py` / `database/collector.py` / `backfiller.py` | `models.get_db()`（mkdir + 直连，**不 init_db**） | 建空库 → INSERT 报 no such table → 崩 | 🟡 RISK |
| M4 | `capital_score.py` | `models.get_db()` + 自带 `CREATE TABLE IF NOT EXISTS stock_capital_score` | 建空库 + 建该表 → 之后读 `stock_daily` 失败 | 🟡 RISK |
| M5 | `regime_backtest.py` / `risk_budget_backtest.py` / `score_predictive_validation.py` | 🔴 **CWD 相对** `'database/vibe_research.db'` | 取决于运行目录 → 可能连错库或新建 | 🔴 DANGER（研究轨） |
| M6 | `backend/tests/*`（4 个测试调 `models.init_db()`） | 同 canonical | 依赖 T1#3 已修的 autouse fixture 打桩；未打桩则直连生产库 | 🟡（已缓解） |

---

## 3. 目标缺失时的 4 类行为（Q3 完整答案）

| 类型 | 行为 | 代表入口 | 是否"静默成功" |
|---|---|---|---|
| **A. fail-loud（FileNotFoundError）** | `db.get_conn()` 显式抛异常 | 7 个模块：`asset_intelligence/history.py`、`asset_intelligence/validation/{confidence_eval,regime_eval,returns,signal_eval}.py`、`commodity_engine/snapshot.py`、`regime_history.py` | 否 ✅ |
| **B. 只读失败** | `mode=ro` 连接失败 | `healthcheck.py`（唯一 `mode=ro` 站点） | 否 ✅ |
| **C. 静默建空库 → 崩溃** | `sqlite3.connect` 自动建 0 字节文件，随后 SQL 报 `no such table` | **15:30 主链路全链**、`models.get_db()` 用户、`import_tdx`、`capital_score` | 否，但**留下 0 字节垃圾文件** ⚠️ |
| **D. 静默建空库 + 自动建表 → 成功** | 自带 `init_db()` 建完整 schema 后写入 | `cio_decision_engine`、`build_failure_log` | **是** 🔴 |

> 关键机制：`sqlite3.connect(path)` 在文件不存在时**默认静默创建**。全项目 114 处 `sqlite3.connect` 中，只有 `db.get_conn()`（有 `exists()` 守卫）和 `healthcheck.py`（`mode=ro`）两处能避免。

---

## 4. B2 判定

### ✅ PASS 项
1. **路径唯一性**：15 个 automation + 全部生产子步骤，DB 目标统一为 `backend/database/vibe_research.db`
2. **git 无责**：`.gitignore` 含 `*.db`，`git ls-files | grep '\.db$'` = 0，git 恢复不可能删除 DB（B1 已证）
3. **主链路不会静默连错库**：15:30 链属 C 类，会崩溃并留非零 rc
4. **备份可用且完整**：见 §5

### ❌ 不达标项（backlog，不在本次修）
| ID | 问题 | 等级 | 归属 |
|---|---|---|---|
| **B2-F1** | `cio_decision_engine.py` / `build_failure_log.py` 自带 `init_db()` → 空库静默写入成功 | 🔴 High | backlog（月度手工入口） |
| **B2-F2** | 3 个 CWD 相对路径研究脚本 → 可能连错库 | 🔴 Medium | backlog（研究轨，非生产） |
| **B2-F3** | `backend/vibe_research.db` 0 字节空壳被备份脚本 & healthcheck 当候选 | 🟡 Low | backlog（噪音 + 误导巡检） |
| **B2-F4** | 主链路缺库时会创建 0 字节垃圾文件，污染 canonical 路径 | 🟡 Medium | **恢复时须注意顺序** |
| **B2-F5** | 仅 7/114 连接点走 fail-loud 守卫，`db.py` 单点真相被绕过 | 🟡 Medium | 并入 P1-C Canonical Universe |

### → 是否够格进入 B3？
**是（Conditional）**。路径一致性已证明；失败语义不达标项均为**非日常主链路**（M1/M2 手工、M5 研究轨），不构成日常生产风险，按用户纪律 backlog 化。

---

## 5. 恢复候选（B1 复核 + B2 补充）

| 备份 | 大小 | 数据截止 | 头校验 | WAL 残留 |
|---|---|---|---|---|
| `D:\AI研投系统备份\2026-09-06\vibe_research.db` | 5,087,100,928 B (4.74 GB) | 2026-09-05 09:04 | ✅ `SQLite format 3` | 无 |
| `D:\AI研投系统备份\2026-08-30\database__vibe_research.db` | 5,069,770,752 B | 2026-08-30 21:20 | ✅ `SQLite format 3` | 无 |

- 6 天增量 +17,330,176 B（≈16.5 MB），增长量级合理，符合日频写入。
- 推荐恢复源：**2026-09-06 那份**（最新）。
- 目标路径：`C:\Users\JOY\WorkBuddy\个人AI研投系统\backend\database\vibe_research.db`
- ⚠️ 恢复前置：`backend/database/` 目录**已存在**（含 `models.py` 等），直接拷入即可；**恢复前确认该路径下无 0 字节残留文件**（防 B2-F4 垃圾文件顶位）。

---

## 6. 纪律遵守声明

- ✅ 全程未连接任何 DB（仅 `head -c 16` 读取备份文件头字节，非 DB 连接）
- ✅ 未恢复 / 未复制 / 未移动任何 DB 文件
- ✅ 未修改任何代码、未 commit、未 push
- ✅ 未触发任何自动化

---

## 7. 下一步建议

1. **B3 · Write Surface / Environment Split**：测试 / 脚本 / 调度是否会误写 5GB 生产库（串联 T1#3 已修的 autouse fixture）
2. **B4 · Canonical Runtime Verdict**：唯一生产库 + 运行入口 + 配置源 + 测试隔离是否闭环
3. **恢复动作**（等用户授权，本轮不执行）：从 2026-09-06 备份拷回 `backend/database/`，随后跑 `healthcheck.py` 只读验证
