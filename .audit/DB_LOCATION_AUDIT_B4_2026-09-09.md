# P1 · DB Location & Runtime Dependency Audit — B4: Canonical Runtime Verdict

- 日期：2026-09-09
- 阶段：P1-B4（承 B1 / B2 / B3）
- 模式：**READONLY**（不恢复、不复制、不移动 DB；不改生产逻辑）
- 任务：回答「canonical DB 到底能不能安全恢复，以及恢复后哪些运行方式被允许」

---

## 0. 最终裁定

```yaml
P1_B4_CANONICAL_RUNTIME_VERDICT:
  verdict: RECOVERY_READY_WITH_RESTRICTIONS   # 裁定本身不变；恢复已执行见 Gate ⑤
  recovery_performed: true
  canonical_db_present: true
  restrictions_count: 5
  next_gate: Recovery Gate ⑤  # ✅ 已执行，结论见 .audit/RECOVERY_GATE_2026-09-09.md
```

> **不是"已经安全，可以恢复"。**
> 准确表述是：**测试执行面的隔离已达到可接受的第一道防线；但整个 Runtime 的
> Canonical Universe 尚未统一。恢复动作本身可以与 pytest 隔离问题分开处理，
> 但恢复后的运行纪律必须先定义并被执行。**

### 三条不可混淆的战线（用户明确要求分开）

| 战线 | 解决什么 | 当前状态 |
|---|---|---|
| **P0-A / E1 / E1.6** | 「pytest 污染生产库」 | ✅ 已关闭（行为级验证） |
| **P1-C** | 「整个系统到底写哪一个 DB」 | ❌ **未开始**（86/95 硬编码路径） |
| **Recovery Gate** | 「恢复 5GB 数据并验证 Runtime 正确工作」 | 🔴 BLOCKED → 现转为有条件放行 |

> **B3 收口 ≠ P1-C 解决。** 本裁定不构成对 P1-C 的任何结论。

---

## 1. B4.1 · Canonical Identity — 🟢 PASS

| 项 | 事实 |
|---|---|
| 唯一 canonical | `C:\Users\JOY\WorkBuddy\个人AI研投系统\backend\database\vibe_research.db` |
| 当前状态 | **不存在**（审计期间已清空并多次验证） |
| 生产库唯一副本 | `D:\AI研投系统备份\2026-09-06\vibe_research.db` |
| 大小 | **5,087,100,928 B**（4.74 GB，与 B1 记载一致） |
| 源文件 mtime | **2026-09-05 09:04:39** |
| 数据截止 | 2026-09-05 09:04 |
| 文件头 | `SQLite format 3` ✅ |
| WAL/SHM 残留 | 无 |
| **SHA-256** | **`30d293093b456242f56465388e5c09cfbac79c25cd85d0965db94ff1245d5d75`** |
| 校验耗时 | 6.7 s（基线留档 `.audit/evidence/B3/backup_2026-09-06_sha256.txt`） |

> 恢复后必须以这三项做**不可变基线**比对：`size=5087100928` / `sha256=30d29309…5d75` / `mtime=2026-09-05 09:04:39`。
> 三者任一不符 → 恢复失败，立即停止并按回滚预案处理。
| 干扰项 | `backend/vibe_research.db` **0 字节历史空壳**（B2-F3，非生产库，但仍被 healthcheck 与备份脚本当候选） |

**判定**：canonical 身份唯一、无歧义、恢复源明确且完整。✅

---

## 2. B4.2 · Runtime Resolution — 🟡 PASS（附 1 条新 caveat）

### 2.1 路径解析方式量化（95 个项目文件含 `vibe_research.db` 字符串）

| 类别 | 数量 | 占比 | 说明 |
|---|---|---|---|
| **C 硬编码**（`os.path.join(__file__/ROOT/…)` 或绝对路径字面量） | **86** | **90%** | 绕过一切单点源 |
| B 走 `database.models` 单点源 | 3 | 3% | `write_decision_ledger` / `shadow_evaluator` / `tests/replay_engine` |
| D 仅注释 / 守卫性提及（不写库） | 6 | 6% | 备份脚本、`_inspect_*`、healthcheck、本轮新增测试 |
| A 走 `db.get_conn()` | **0** | 0% | — |
| 另：走 `db.get_conn()` 但**不含**路径串的模块 | **7** | — | `asset_intelligence/history.py`、`validation/{confidence_eval,regime_eval,returns,signal_eval}.py`、`commodity_engine/snapshot.py`、`regime_history.py`（B1 已列） |

> 结论：**单点契约源在写入面几乎被完全架空**（真正走单点源的仅 3+7=10 处，对面是 86 处硬编码）。

### 2.2 ⚠️ 新 caveat（由 E1 引入）

E1 让 `db.py` / `models.py` 支持 `VIBE_DB_PATH` override。**若生产环境误设该变量，生产链会写入非 canonical 的库**——这是一个新增的、方向相反的静默失效面。

- 已核实：当前**无任何 automation / 脚本 / `.env` 设置该变量**
- 必须写入运维纪律：**生产环境禁止设置 `VIBE_DB_PATH`**（见 B4.8 禁止清单第 4 条）

**判定**：全部解析到同一 canonical（B1 已证），✅ PASS；附上述 caveat。

---

## 3. B4.3 · Write Surface — 🔴 FAIL（归 P1-C）

| 指标 | 数量 |
|---|---|
| 引用 `vibe_research.db` 的 .py | 95（项目文件） |
| ├ 硬编码路径 | **86** |
| ├ 走单点源（models / db） | 10（3 + 7） |
| └ 仅提及不写库 | 6 |
| 直连且含写 SQL | 35 |
| 经 `models.get_db()` 间接写 | 9 |
| 自带 DDL + DML（自建表能力） | 21 |
| 自带 `init_db()`（空库也能静默建表写入成功） | `models.py` / `cio_decision_engine.py` / `build_failure_log.py` / `daily-os/app.py` |

**判定**：写入面**不知道自己写的是哪一个 DB** —— 它们各自硬编码。🔴 归 **P1-C**，不在本轮解决。

---

## 4. B4.4 · Test Isolation — 🟢 PASS（缺失态验证）/ ⏳ 终极验证待 Gate ⑦

### 4.1 已关闭的机制

| 层 | 机制 | 状态 |
|---|---|---|
| P0-A | `models.DB_PATH` + `db._DB_PATH` → 沙箱（预置 23 表） | ✅ |
| P0-B | `sqlite3.connect` 命中 `vibe_research.db` → **raise** | ✅ |
| E1 | `VIBE_DB_PATH` env override → 子进程继承 | ✅ |
| E1.6 | `subprocess.run` 拉起 backend 脚本 → **raise** | ✅ |

### 4.2 行为级证据

| 项 | 结果 |
|---|---|
| `pytest backend/` | **145 passed / 0 failed / 65.24s** |
| canonical 是否被创建 | **否（零创建）** |
| 沙箱承接写入 | **4,026,368 B**（基线 258,048 B；`commodity_daily` 22,193 行 + 8 + 6） |
| 对照：剔除守卫后的裸 pytest | 创建 3.76 MB 库、写 22,193 行（证据留档） |

### 4.3 ⚠️ 必须写明的限定

> **以上全部证据均在 canonical DB「不存在」的状态下取得。**

逻辑上守卫与库是否存在无关（P0-B 在 `connect` **之前** raise；E1.6 在 `subprocess.run` **之前** raise），但**行为级证明必须在恢复后 Gate ⑦ 复测**才能算最终闭环。

**判定**：🟢 PASS（缺失态）；终极判定延后至 Recovery Gate ⑦。

---

## 5. B4.5 · Subprocess — 🟡 PASS（测试面）/ 残留仅限手工面

| 入口 | 行为 | 是否逃逸面 |
|---|---|---|
| `subprocess.run` | **已被 E1.6 硬拒绝** | ❌ 已关闭 |
| `subprocess.Popen` — `cli_runtime.py:168` | 调外部 CLI 二进制（`bin_path` = Claude / Qwen / Codex），**不碰 DB** | ❌ 非逃逸面 |
| `subprocess.call` — `run_pathA_global_backfill.py:71` | **re-exec 自己**（venv 重入），会写 canonical | ⚠️ 是，但**仅手工回填触发，无测试可达** → 归入 B4.6 手工面 |

**准确措辞（用户要求）**：
```yaml
E1.6:
  status: RATIFIED
  scope: subprocess.run
  effect: CLOSED
  known_gap: [subprocess.Popen, subprocess.call, subprocess.check_output, os.system]
```
**不得表述为"所有 subprocess 风险已关闭"** —— 只有 `subprocess.run` 通道关闭。

---

## 6. B4.6 · Manual CLI — 🔴 FAIL（存在直接写 canonical 风险）

### 6.1 无 `--dry-run` 的实验 / 回填 / 孤儿脚本（8 个）

| 脚本 | DML | 性质 |
|---|---|---|
| `backend/risk_budget_stress_sim.py` | 1 | 🟠 **名带 sim 的实验脚本** |
| `backend/global_history_backfill.py` | 3 | 回填 |
| `backend/fill_market_cap.py` / `fill_stock_flow.py` / `fill_daily_quotes.py` | 1~4 | 回填 |
| `backend/_quick_today_import.py` / `_add_systemic.py` | 8 / 1 | 孤儿脚本（`_` 前缀） |
| `backend/run_pathA_global_backfill.py` | 0（`subprocess.call` re-exec） | 回填 |

### 6.2 有 `--dry-run` 的范式（2 个）

`backend/import_tdx.py`、`backend/build_market_daily.py` ✅

### 6.3 CWD 相对路径（B2-F2，3 个研究脚本）

`regime_backtest.py` / `risk_budget_backtest.py` / `score_predictive_validation.py`
→ 用 `"database/vibe_research.db"`，**运行目录不同会连到不同库甚至新建**。

**判定**：🔴 手工面存在直接写 canonical 的通道，且多数无 dry-run、无撤销。**恢复后必须按 B4.8 禁止清单约束。**

---

## 7. B4.7 · Automation — 🟡 Conditional PASS

| Automation | 时间 | 入口 | 对 canonical | 判定 |
|---|---|---|---|---|
| A1 交易日更新+研报 | 15:30 | `run_daily.py` 全链 | **写** | 🟢 生产主链（预期行为） |
| A9 Decision Log 草稿 | 16:30 | `write_decision_ledger.py`（models） | **写** | 🟢 预期行为 |
| A2 盘前健康巡检 | 08:00 | `healthcheck.py`（`mode=ro`） | 只读 | 🟢 SAFE |
| A3 本地备份 → D: | SU 23:30 | `_backup_db_to_d.py` | 只读源 | 🟢 SAFE |
| A5 盘前纪要抓取 | 07:30 | `panqian_ingest.py` | **只读**（`os.path.exists` 守卫 + `SELECT code,name FROM stock_info`） | 🟢 SAFE |
| A8 Flow Evidence Archive | 21:00 | `audit/flow_evidence_archive.py` | **只读**（`DB_PATH.exists()` 守卫 + SELECT；产物是 JSON） | 🟢 SAFE |
| A4 westock 板块资金流 | 18:30 | MCP，非本地 sqlite | N/A | ⚪ |
| A6 全市场动量 | 08:45 | 只写 JSON | N/A | ⚪ |
| A7 美债观察 | 08:10 | 只写 JSON | N/A | ⚪ |
| A10 GitHub 同步 | 21:00 | git | N/A | ⚪ |
| A11–A15 周报 / 一次性 | — | 文档类 | N/A | ⚪ |

- **路径一致性**：全部解析到同一 canonical（B2 已证）✅
- ⚠️ A1 / A9 **缺库时会静默创建 0 字节空库**（B2-F4，已在本次审计中实证两次）

**判定**：🟡 Conditional PASS —— 行为符合预期，但缺库失败语义不达标（B2 遗留）。

---

## 8. B4.8 · Recovery Safety — 允许 / 禁止清单

### ✅ 恢复后**允许**（按顺序）

1. 校验备份 SHA-256 与基线一致
2. 复制 `D:\AI研投系统备份\2026-09-06\vibe_research.db` → `backend\database\vibe_research.db`
3. **恢复前**先在 D 盘新建目录做一次当前状态备份（不覆盖 `2026-09-06` 那份）
4. 恢复后**第一个动作**必须是 `mode=ro` healthcheck
5. 建立不可变基线：size / sha256 / mtime / 关键表 rowcount
6. 运行 `pytest`（守卫已生效；这是 Gate ⑦ 复测）
7. 经授权的 15:30 日常生产链 `run_daily.py`

### 🚫 恢复后**禁止**（P1-C 完成前）

1. **裸跑任何** collector / backfill / `fill_*` / 实验脚本（特指 B4.6 §6.1 的 8 个无 dry-run 脚本）
2. 运行 3 个 CWD 相对路径研究脚本，除非先 `cd backend`（否则可能新建/连错库）
3. 手工触发 `daily_collect` / `run_daily` 全链（除经授权的日常 15:30）
4. **在 canonical 环境设置 `VIBE_DB_PATH`**（会把生产链引向非 canonical 库）
5. 恢复后的第一次运行**不得**是任何写操作 —— 必须先 `mode=ro` healthcheck

---

## 9. B4 裁定汇总表

| Gate | 问题 | 判定 |
|---|---|---|
| **B4.1 Canonical Identity** | canonical 唯一位置是否明确 | 🟢 PASS |
| **B4.2 Runtime Resolution** | 主进程 / models / db.py 是否指向同一 canonical | 🟡 PASS + E1 caveat |
| **B4.3 Write Surface** | 所有写入口是否知道自己可能写 canonical | 🔴 **FAIL → P1-C** |
| **B4.4 Test Isolation** | pytest 能否在 canonical 存在时零写入 | 🟢 PASS（缺失态）/ ⏳ 待 Gate ⑦ 复测 |
| **B4.5 Subprocess** | `run` 是否隔离，其他进程 API 是否逃逸 | 🟡 PASS（run 关闭；Popen 非逃逸；call 归手工面） |
| **B4.6 Manual CLI** | 手工 CLI 是否直接写 canonical | 🔴 **FAIL（8 个无 dry-run）** |
| **B4.7 Automation** | 定时任务是否天然指向 canonical | 🟡 Conditional PASS |
| **B4.8 Recovery Safety** | 恢复后允许/禁止什么 | ✅ 已定义（§8） |

```yaml
P1_B4:
  mode: READONLY
  recovery_performed: false
  verdict: RECOVERY_READY_WITH_RESTRICTIONS
  gates:
    B4.1: PASS
    B4.2: PASS_WITH_CAVEAT      # VIBE_DB_PATH 生产禁用
    B4.3: FAIL_TO_P1C           # 86/95 硬编码
    B4.4: PASS_MISSING_STATE    # 终极证明待恢复后 Gate ⑦
    B4.5: PASS_SCOPE_LIMITED    # 仅 subprocess.run
    B4.6: FAIL                  # 手工面无 dry-run
    B4.7: CONDITIONAL_PASS
    B4.8: DEFINED
  unblock_conditions:
    - "恢复后第一批动作限于 §8 允许清单"
    - "Gate ⑦ 复测 canonical 零写入，否则立即回滚到 B4 重新裁定"
```

---

## 10. 下一步（用户批准的执行顺序）

```text
B3 ✅ 收口
 ↓
B4 Canonical Runtime Verdict  ✅ 本文件
 ↓
Recovery Gate ⑤  🔴 恢复 5GB DB（等授权）
 ↓
⑤  mode=ro healthcheck
 ↓
⑥  恢复后基线（size / sha256 / mtime / 关键表 rowcount）
 ↓
⑦  pytest 隔离复测（canonical 存在态 —— B4.4 的终极证明）
 ↓
⑧  手工 CLI 风险复核
 ↓
⑨  automation / collector 风险复核
 ↓
⑩  Recovery Verdict
```

**DB 已于 2026-09-09 受控恢复并执行完毕（结论见 `.audit/RECOVERY_GATE_2026-09-09.md`）。
本 B4 裁定作为「恢复前的 Runtime Verdict」保留原貌；恢复后限制清单（§8）在 P1-C
完成前持续生效。B4.3（Write Surface）/ B4.6（Manual CLI）仍为 FAIL，不因恢复而变。**
