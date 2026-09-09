# P1-C · Canonical Universe Audit — 第一回合（READONLY Inventory + 分类）

- 日期：2026-09-09
- 模式：**READONLY**（不改代码、不改 DB、不 commit、不 push）
- 前置：Recovery Gate ⑤ = `RECOVERED_WITH_VERIFICATION`；B4 = `RECOVERY_READY_WITH_RESTRICTIONS`
- 目标：把「86 处硬编码路径」从数量变成一张可决策的 **Canonical Universe Matrix**，
  回答 C1–C7，形成最小修改方案（C7，仅设计不实施）。

---

## 0. 准确状态（采纳用户纠正）

```yaml
DB_STATE:
  canonical: PRESENT
  integrity: VERIFIED            # size+sha256 与备份 bit-identical
  runtime_readability: VERIFIED # mode=ro healthcheck 通过
  pytest_isolation: VERIFIED     # 17 passed / CANONICAL_UNCHANGED
SYSTEM_RUNTIME:
  canonical_universe: UNRESOLVED # 86 处硬编码 = 多个 DB 定位事实源
  manual_write_surface: RESTRICTED
  production_automation: ALLOWED_BY_SCHEDULE_ONLY
  VIBE_DB_PATH: FORBIDDEN
  p1c: OPEN
```

> **数据库已恢复、系统具备受控工作条件，但 Runtime 治理（Canonical Universe）未完成。**
> 不能解除 B4.8 禁止清单，直到 P1-C 把「多个事实源」收敛为「单一事实源」。

---

## 1. 方法与口径

- 扫描器：`.audit/evidence/p1c_scan.py`（只读，读 backend/scripts/trading_os/daily-os/quant-lab 的 `.py/.bat/.sh`）。
- 信号：对**整文件**检测 `sqlite3.connect`（直连）/ `get_conn`·`get_db`·`import db`·`import models`·`from database`（单点源）/ `VIBE_DB_PATH`（env）/ INSERT·UPDATE·DELETE·CREATE TABLE（写）/ `database/vibe_research.db`（CWD 相对）。
- 分类：ROOT 单点源 / A·B 单点源消费者 / C2 硬编码直写 / C3 硬编码只读 / C4 只读工具 / C5 CWD 相对 / TEST·GUARD / COMMENT。
- **口径声明（第一回合，非终态）**：`PROD-WRITE` 是「文件含写 SQL」的启发式标记，可能高估；
  真正的「硬编码直连写面」= `direct_open=1 且 非单点源` 的子集（约 35 个，与 B4.3 的 35 吻合）。
  4 个 `direct_open=0` 的疑似文件已逐份人工核验（见 §C2 注释），确认均为硬编码事实源。

---

## 2. 聚合分类

| 维度 | 计数 | 说明 |
|---|---:|---|
| 含字面量文件 | 94 | 全仓（backend 为主 + trading_os/daily-os） |
| 字面量命中 | 113 | — |
| ROOT 单点源 | 2 | `backend/db.py` + `backend/database/models.py`（**定义 DB_PATH 的地方**） |
| A·B 单点源消费者 | 1+ | 纯单点源消费者（其余多为「双源」：既 import models 又自建路径） |
| **C2 硬编码直写（须统一）** | **~35** | 硬编码路径 + `sqlite3.connect` + 写；B4.3 同数 |
| C3 硬编码只读（可迁移） | 35 | 硬编码路径但仅读 |
| C4 只读工具（可保留） | 3 | backup / healthcheck / inspect / archive |
| C5 CWD 相对（修基址） | 27 | 用 `database/vibe_research.db` 形式；**统一后被单点源吸收** |
| TEST·GUARD（排除） | 12 | tests/ + conftest（已由 P0 守卫重定向） |
| COMMENT（无副作用） | 0 | — |

> 87 个非 ROOT 文件 = 当前「多个 DB 定位事实源」的真实规模（≈ B4 的 86）。

---

## 3. C1–C7 逐项结论

### C1 · 86 处硬编码重新分类
已重分类为：ROOT×2 / 单点源消费者×~8（含双源）/ C2 直写×~35 / C3 只读×35 / C4 工具×3 / C5 CWD×27 / TEST×12。
不再是「一个 86 的数字」，而是一张可决策的表（见文末全量 Matrix）。

### C2 · 确认真正的写入面
**硬编码直连写面 ≈ 35 个文件**（与 B4.3「直连且含写 SQL = 35」一致）。代表性：
`daily_collect.py` / `cio_decision_engine.py` / `build_derived_tables.py` / `fill_stock_flow.py` /
`fill_market_cap.py` / `fill_daily_quotes.py` / `global_history_backfill.py` /
`build_sector_daily.py` / `build_market_daily.py` / `build_limit_up_daily.py` /
`intraday_watch_runner.py` / `shadow_evaluator.py` / `trader_log.py` / `tdx_daily_import.py` /
`tech_fill.py` / `os_layers/*` / `trading_os/attribution_sink.py` 等。
单点源消费者（`write_decision_ledger.py` 等）已走 `models` → **已安全，不属写面风险**。

### C3 · 可安全迁移到单点 DB_PATH 的入口
**全部 C2 + C3 + C5 的硬编码消费者**（约 87−2−12−3 ≈ 70 个文件）都应改为调用
`db.get_conn()` / `models.get_db()`。单点源已具备 env override（E1）与 conftest 重定向能力，
迁移后「事实源」收敛为 1 处。

### C4 · 必须保留特殊 DB 的入口
- **ROOT 单点源本身**：`db.py` / `models.py` —— 唯一允许含字面量 + `VIBE_DB_PATH` 的地方。
- **只读工具**（C4×3）：`_backup_db_to_d.py`（备份源只读）、`_healthcheck_preopen.py`、
  `flow_evidence_archive.py` 等 inspect/archive 脚本。它们正确指向 canonical 且只读，
  **可保留硬编码**（或顺手迁移，非强制）；不属于写面风险。

### C5 · CWD 相对路径
27 个文件用 `database/vibe_research.db` 相对形式（`regime_backtest.py` / `risk_budget_backtest.py` /
`score_predictive_validation.py` 等研究脚本 + 多个 `_*` 孤儿脚本）。**风险**：运行目录不同会连错库甚至新建。
**该问题被「统一到单点源」天然吸收**——单点源从 `backend` 根解析，与 cwd 无关。

### C6 · VIBE_DB_PATH 逃逸面
仅 `db.py` + `models.py` 读取 `VIBE_DB_PATH`（E1）。逃逸条件=生产环境误设该变量→生产链写非 canonical 库。
**已缓解**：B4.8 禁止清单第 4 条「生产环境禁设 VIBE_DB_PATH」，且已核实当前无任何 automation/脚本设置。
C7 实施时**不得**扩大 E1 的使用范围。

### C7 · 最小修改方案（仅设计，本回合不实施）
```
1. 单一访问器：保留 db.get_conn()（读写）+ models.get_db()（单点源）为唯一入口。
2. 机械迁移：对每个 C2/C3/C5 消费者，删除自建路径变量，替换为 db.get_conn()。
   - 直连形式 sqlite3.connect(os.path.join(...)) → db.get_conn()
   - CWD 相对形式 → db.get_conn()（自动从 backend 根解析）
3. subprocess / re-exec（run_pathA_global_backfill、g2_supervisor、submit_close CLI）：
   不得依赖 VIBE_DB_PATH（生产禁用）；启动时显式传 --db <db._DB_PATH 解析值>。
4. 保留：ROOT 单点源、TEST/GUARD（已由 conftest 重定向）、C4 只读工具（可不动）。
5. 验证门槛（实施轮才跑）：
   - p1c_scan 复扫：PROD 内 C2/C3/C5 = 0
   - pytest Gate ⑦ 复测：exit=0 / CANONICAL_UNCHANGED
   - grep "vibe_research.db" 仅命中 db.py/models.py/tests/guard/tools
6. 完成后：解除 B4.8 对应禁止清单项，P1-C → PASS。
```
**最小变更原则**：只改「路径解析」一处，不碰阈值/逻辑/表结构；与 P1-B 冻结基线零冲突。

---

## 4. 风险与未决

- 本回合为**静态分类**，未运行任何迁移；4 个疑似文件已人工核验，其余 87 个分类为启发式，
  实施前应逐文件二次确认（尤其 `direct_open=0` 但含路径定义的双源/CLI 文件）。
- `research_memo.py` 仅把路径放进列表，无活动连接 → 统一时一并去硬编码即可。
- 残留 `subprocess.Popen`(cli_runtime) / `subprocess.call`(run_pathA) 不在本 Gate 范围（B4.5 已限定仅 `subprocess.run` 关闭）。

---

## 5. 下一步
用户审此 Matrix → 批准 C7 方案 → **另开实施轮**做机械迁移（仍 READONLY 验证门）→ P1-C Gate → 再决定 commit/push 边界。

> 全文量 Matrix（94 行）见文末附录，由 `p1c_scan.py` 生成，源数据 `.audit/evidence/p1c_matrix.json`。

## 附：Canonical Universe Matrix（全量 94 行）

> 列：n=命中行数 | D=直连sqlite3.connect | SS=走单点源 | E=读VIBE_DB_PATH | CWD=用`database/vibe_research.db` | W=含写SQL

| # | File | n | D | SS | E | CWD | W | 迁移类别 |
|---|---|---|---|---|---|---|---|---|
| 1 | backend/write_decision_ledger.py | 1 |  | Y |  |  | Y | A/B single-source (OK, already unified) |
| 2 | backend/_add_systemic.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 3 | backend/_fix_agsc_tmp.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 4 | backend/_quick_today_import.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 5 | backend/audit/cio_historical_baseline.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 6 | backend/brain/cio_agent.py | 2 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 7 | backend/build_crosswalk.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 8 | backend/build_decision_log.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 9 | backend/build_derived_tables.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 10 | backend/build_failure_log.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 11 | backend/build_industry_mapping.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 12 | backend/build_limit_up_daily.py | 1 | Y | Y |  |  | Y | C2 WRITE (must unify) |
| 13 | backend/build_market_daily.py | 1 | Y | Y |  |  | Y | C2 WRITE (must unify) |
| 14 | backend/build_sector_daily.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 15 | backend/build_weekly_intel.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 16 | backend/cio_decision_engine.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 17 | backend/daily_collect.py | 3 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 18 | backend/data_quality_check.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 19 | backend/fetch_industry_map.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 20 | backend/fill_daily_quotes.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 21 | backend/fill_market_cap.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 22 | backend/fill_stock_flow.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 23 | backend/global_history_backfill.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 24 | backend/ingest_sector_flow_westock.py | 1 | Y | Y |  |  | Y | C2 WRITE (must unify) |
| 25 | backend/intraday_watch_runner.py | 1 | Y | Y |  |  | Y | C2 WRITE (must unify) |
| 26 | backend/narrative_layers.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 27 | backend/notify/research_memo.py | 1 |  |  |  |  | Y | C2 WRITE (must unify) |
| 28 | backend/os_layers/tonghuashun_parser.py | 2 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 29 | backend/os_layers/trading_discipline_engine.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 30 | backend/os_layers/wenhua_bill_parser.py | 1 |  |  |  |  | Y | C2 WRITE (must unify) |
| 31 | backend/relationship_engine.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 32 | backend/risk_budget_stress_sim.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 33 | backend/sector_pipeline.py | 1 | Y | Y |  |  | Y | C2 WRITE (must unify) |
| 34 | backend/shadow_evaluator.py | 1 | Y | Y |  |  | Y | C2 WRITE (must unify) |
| 35 | backend/tdx_daily_import.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 36 | backend/tech_fill.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 37 | backend/trader_log.py | 1 | Y |  |  |  | Y | C2 WRITE (must unify) |
| 38 | daily-os/app.py | 1 | Y | Y |  |  | Y | C2 WRITE (must unify) |
| 39 | trading_os/attribution_sink.py | 1 | Y |  |  | Y | Y | C2 WRITE (must unify) |
| 40 | trading_os/g2_supervisor.py | 1 |  |  |  |  | Y | C2 WRITE (must unify) |
| 41 | trading_os/submit_close.py | 3 |  |  |  |  | Y | C2 WRITE (must unify) |
| 42 | backend/database/models.py | 1 | Y | Y | Y |  | Y | ROOT single-source (defines DB_PATH) |
| 43 | backend/_audit2.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 44 | backend/_audit_data.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 45 | backend/_healthcheck_preopen.py | 2 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 46 | backend/_inspect2.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 47 | backend/_inspect_db.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 48 | backend/au_holding_analysis.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 49 | backend/audit/decision_audit_aug.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 50 | backend/build_monthly_cio.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 51 | backend/build_sector_mainline.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 52 | backend/capital_migration.py | 2 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 53 | backend/data_freshness.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 54 | backend/data_health.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 55 | backend/decision_quality_dashboard.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 56 | backend/decision_tree.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 57 | backend/deep_mine.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 58 | backend/export_three_trades.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 59 | backend/gold_engine/data_adapter/gold_data.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 60 | backend/leader_engine.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 61 | backend/main_line_report.py | 1 | Y | Y |  |  |  | C3 READ (migratable to single source) |
| 62 | backend/narrative_engine.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 63 | backend/observation/breadth_cross_check.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 64 | backend/os_layers/execution_intelligence.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 65 | backend/regime_backtest.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 66 | backend/risk_budget_backtest.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 67 | backend/risk_governance.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 68 | backend/risk_stock.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 69 | backend/run_daily.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 70 | backend/run_pathA_global_backfill.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 71 | backend/scenario_engine.py | 2 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 72 | backend/score_predictive_validation.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 73 | backend/sentiment.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 74 | backend/trade_review.py | 2 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 75 | backend/trading_dna_v1.2.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 76 | backend/trading_dna_v1.py | 1 | Y |  |  | Y |  | C3 READ (migratable to single source) |
| 77 | backend/tushare_provider.py | 1 | Y |  |  |  |  | C3 READ (migratable to single source) |
| 78 | backend/_backup_db_to_d.py | 2 |  |  |  | Y |  | C5 CWD-rel (fix path base) |
| 79 | backend/db.py | 1 | Y | Y | Y |  |  | ROOT single-source (defines DB_PATH) |
| 80 | backend/audit/flow_evidence_archive.py | 1 | Y |  |  |  |  | C4-tool-read (legit points to canonical) |
| 81 | backend/panqian_ingest.py | 1 | Y |  |  |  |  | C4-tool-read (legit points to canonical) |
| 82 | backend/panqian_parser.py | 1 | Y |  |  |  |  | C4-tool-read (legit points to canonical) |
| 83 | backend/conftest.py | 4 | Y | Y | Y |  | Y | TEST/GUARD (excluded) |
| 84 | backend/tests/replay_engine.py | 1 | Y | Y |  |  | Y | TEST/GUARD (excluded) |
| 85 | backend/tests/test_data_health_fail_closed.py | 2 |  |  |  |  | Y | TEST/GUARD (excluded) |
| 86 | backend/tests/test_decision_ledger_phase1b.py | 1 | Y | Y |  |  | Y | TEST/GUARD (excluded) |
| 87 | backend/tests/test_investment_committee_sentiment_contract.py | 1 |  |  |  |  |  | TEST/GUARD (excluded) |
| 88 | backend/tests/test_phase1c_regression.py | 1 | Y | Y |  |  | Y | TEST/GUARD (excluded) |
| 89 | backend/tests/test_phase1d_shadow_replay.py | 1 | Y | Y |  |  | Y | TEST/GUARD (excluded) |
| 90 | backend/tests/test_phase1e_shadow_evaluator.py | 1 | Y | Y |  |  | Y | TEST/GUARD (excluded) |
| 91 | backend/tests/test_pipeline_failure_visibility.py | 1 |  |  |  | Y | Y | TEST/GUARD (excluded) |
| 92 | backend/tests/test_prod_db_guard.py | 5 | Y | Y |  | Y | Y | TEST/GUARD (excluded) |
| 93 | backend/tests/test_subprocess_db_isolation.py | 1 | Y | Y | Y |  | Y | TEST/GUARD (excluded) |
| 94 | daily-os/test_integration.py | 1 | Y |  |  |  | Y | TEST/GUARD (excluded) |
