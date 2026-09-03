# P0-A Freeze Record（封板记录）

- **日期**：2026-09-03
- **提交哈希**：见本次提交（commit 完成后回填于对话）
- **父提交**：`adc62a8` daily: sync memo and docs (2026-09-01)
- **性质**：基础设施修复（Failure Visibility + Stale Protection + Shell Cleanup），**不改变任何投资判断逻辑**
- **锁定原则**：任何生产数据只要无法证明「新鲜、完整、时点正确」，就没有资格进入 Brain，更没有资格进入 Memo 和推送。

---

## Gate 1 · Git diff 范围审计 ✅

**被修改的跟踪文件（恰好 7 个，全部 P0-A 代码文件）：**

| 文件 | 增 | 删 | 改动性质 |
|---|---|---|---|
| `backend/daily_collect.py` | +123 | -3 | 新增 `verify_completeness()` + `CRITICAL_STEPS`；失败 `sys.exit(1)` |
| `backend/build_derived_tables.py` | +38 | -1 | 失败 `sys.exit(1)`；计数失败日 |
| `backend/run_brain_report.py` | +76 | -2 | 异常捕获转 `sys.exit(1)` + 核心层降级阻断 + trade_date 校验 |
| `backend/run_daily.py` | +47 | -13 | STEPS 改四元组 + critical 失败即 break（fail-fast） |
| `backend/brain/cio_agent.py` | +31 | -1 | `StaleCacheError` + `_load_data()` 校验 trade_date == 当前数据最新日 |
| `backend/build_market_daily.py` | +29 | -1 | `has_source()` 守卫：无源日期绝不写 NULL 空壳 |
| `backend/database/collector.py` | +7 | -1 | 源全空则跳过保存（防 0 假行） |
| **合计** | **+351** | **-22** | |

**新增未跟踪文件（P0-A 范围，一并提交）：**
- `backend/tests/test_pipeline_failure_visibility.py`（故障注入测试，2 例）
- `backend/database/market_daily_shell_cleanup_manifest_20260903.json`（清理审计清单）
- `docs/P0-A_失败可见_完成报告_2026-09-03.md`（完成报告）
- `docs/P0-A_Freeze_Record_2026-09-03.md`（本文件）

**明确排除、未纳入本次提交的工作树文件（非 P0-A，保持独立 commit 边界）：**
- `backend/database/vibe_research.db.bak_20260825_224037`（5GB 旧备份，非本次产生）
- `docs/XAUUSD_Execution_Engine_PreReg_v0.1.md`、`docs/XAUUSD_G2_*.md`、`docs/量化交易一揽子*.md`、`docs/全盘数据*.md`（2026-08-22，既有未跟踪）
- `trading_os/config/`、`trading_os/probe_xauusd_spec.py`（既有未跟踪）

> 提交用显式 `git add <具体文件>`，**未使用 `git add -A`**，确保上述文件不混入。

---

## Gate 2 · 生产行为边界审计 ✅

| 检查项 | 结果 | 证据 |
|---|---|---|
| 65/80 阈值 | **未改动** | 仅存在于 `scoring_engine.py`（非本次 diff）；7 文件 diff grep 命中 0 |
| 权重 / `DEFAULT_WEIGHTS` | **未改动** | diff grep 命中 0；无路径绕过 |
| veto | **未改动** | diff grep 命中 0 |
| `ADAPTIVE_FEEDBACK_ENABLED` | **仍默认关** | `learning_center.py:48` = `getenv(...,"0")=="1"`；未被打开 |
| `RISK_GUARD_ENABLED` | **仍须人工置 1** | 仅 `approve_risk_guard_takeover.py` / `release_gate.py` 引用，非本次 diff |
| 自动化调度（workbuddy.db / ps1 / bat） | **未触碰** | 无调度文件在本次 diff；automations 外部表未变 |
| Brain 决策逻辑（can_buy / position_pct / confidence / signal） | **未改写** | diff grep 命中 0 改写；仅新增 fail-fast 守卫 |

**⚠️ 一项需显式声明的边界新增（属 fail-fast，不修改决策内容）：**
`run_brain_report.py` 新增 `CORE_LAYERS = {"L4","L5","L6","L7","sentiment"}` 降级阻断门：核心推理层降级时**默认阻断**下游（不产出/不推送），仅 `--allow-degraded` 显式人工豁免（报告内写 `degraded_override` 审计标记）。这是「宁可失败，也绝不悄悄产出错误结果」原则的安全门实现，不改变任何决策阈值/权重/方向。

---

## Gate 3 · 数据库审计 ✅

> 注：DB 文件 `vibe_research.db`（5GB）被 .gitignore 排除，不在本次提交内；以下为运行态审计。

| 检查项 | 结果 |
|---|---|
| `market_daily` 全 NULL 空壳残留 | **0**（已删除 8678 行） |
| `market_daily` 任意 NULL 壳残留 | **0** |
| `market_daily_shell_backup_20260903` 备份表行数 | **8678**（完整，= 删除数） |
| 真实记录（有宽度） | **39**（未变：2026-07-10 ~ 2026-09-02） |
| 真实记录值抽样 | 首尾日期涨跌家数/成交额与清理前一致，未变 |
| 测试临时残留 | **无**（`_bak_brain_report_before_ledger_test.json` 已清理；无 db-wal/journal） |
| `brain_report.json` 是否被测试改写 | 否（mtime 2026-09-03T10:06，早于本审计；测试走 monkeypatch 未落盘） |

审计清单：`backend/database/market_daily_shell_cleanup_manifest_20260903.json`
（含 snapshot_id / old_rule_version / source_commit=`adc62a8` / row_count=8678 / date_range / checksum / backup_table）。

---

## Gate 4 · 测试与语法 ✅

| 项 | 结果 |
|---|---|
| 故障注入测试 `test_pipeline_failure_visibility.py` | **2 passed**（144.6s） |
| 相关已有测试 `backend/tests` | **60 passed**（无回归：58 旧 + 2 新） |
| `run_daily.py` 语法 | PASS |
| `brain/cio_agent.py` 语法 | PASS |
| `build_market_daily.py` 语法 | PASS |
| `database/collector.py` 语法 | PASS |

故障注入覆盖：① `daily_collect` 部分采集失败 → `rc=1`；② `run_daily` 在 critical 步（step1）中断 → 跳过决策树/brain/推送、不重写 `brain_report.json`；③ 单独触发 `push_daily` 因 stale 被 `StaleCacheError` 拒绝、非零退出。

> 已知既有未修复项（非 P0-A 引入，不在本次范围）：`daily-os/test_e2e.py`、`daily-os/test_integration.py` 存在 collection error，会中断 `pytest` 全量收集。建议 P0-A 之后单独立项修复（原报告 P0 #4）。

---

## 提交范围（本次 commit 仅含）

```
backend/brain/cio_agent.py
backend/build_derived_tables.py
backend/build_market_daily.py
backend/daily_collect.py
backend/database/collector.py
backend/run_brain_report.py
backend/run_daily.py
backend/tests/test_pipeline_failure_visibility.py
backend/database/market_daily_shell_cleanup_manifest_20260903.json
docs/P0-A_失败可见_完成报告_2026-09-03.md
docs/P0-A_Freeze_Record_2026-09-03.md
```

## 下一步

- **P0-B（ST Point-in-Time）未启动**，留待独立 commit。
- P0-B 将：建 `security_status_history` 独立 PIT 层 → 旧口径快照冻结为 `historical_baseline_v1` → 重算 `highest_board`/`lianban_count` → 输出 diff/impact 报告。
- 这样未来若情绪周期结论变化，可清晰归因到「P0-A 工程修复」还是「P0-B 数据口径修正」。

---
*Freeze Record 由研投君在 P0-A 封板审计后生成。原则：一个治理变更 = 一个清晰边界 = 一个可追溯基线。*
