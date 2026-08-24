# Automation Registry · 资金权限维度补丁

> 日期：2026-08-22
> 版本：v1.1（E3 权限语义精确化）
> 性质：治理补丁（在现有 14 活跃任务上补「机器真实资金执行权限」维度）
> 依据：`automation_canonical_registry_2026-08-21.md`（14 活跃任务基线）
> Erratum：E3 将 `fund_access` 精确定义为机器执行权，非模糊的「触碰资金」。

---

## 0. 问题

现有分层：Production / Evidence / Publication / Governance。**缺「机器是否拥有真实资金执行权限」维度。**

权限边界的本质变化是：`Human → MT5`（人工交易）变为 `Automation → MT5`（机器执行）。黄金 Execution Engine 上线后，会成为系统里**第一个获得真实资金机器执行权限的 automation / execution component**。必须为这类任务设最高权限标记，防止任何新增 automation 静默获得交易资格。

---

## 1. 分类矩阵（采纳用户第九条 + E3 精确化）

**`fund_access` 精确定义**：表征**自动化组件是否具备向交易终端提交、修改、撤销真实资金订单的机器执行权限**。它描述的是机器权限，不是「人是否在交易」。

| 类型 | 影响生产 | 产生新事实 | 机器执行权限 | 现有任务示例 |
|---|---|---|---|---|
| Data Collection | 是 | 是 | none | Data Health Check |
| Production Research | 是 | 是 | none | Daily Close Production / Decision Log / Weekly Note |
| Observation | 否 | 是 | none | UST / Momentum / Flow Enrich / Finalize Archive |
| Governance | 否 | 否 | none | Checkpoint B/C / Local Backup |
| Publication | 否 | 否 | none | Pre-Market Brief / GitHub Push |
| Strategy Research | 否 | 是 | none | （H1 相关，当前未自动化） |
| **Execution** | **是** | **是** | **execution（最高权限）** | **黄金 Execution Engine（待建）** |

**规则：任何新增 automation 必须回答「它有没有机器真实资金执行权限」。Execution 类为系统最高权限，需独立 Release Gate 批准。**

---

## 2. 现有 14 任务补丁（逐条加 `fund_access` 字段）

| 任务 | task_id | 类型 | fund_access |
|---|---|---|---|
| Pre-Market Brief | 1784175362588 | Publication/Input | none |
| Daily Publication (GitHub) | 1785037277644 | Publication | none |
| Daily Close Production | 1785399819081 | Production | none |
| Checkpoint B | 1785409809893 | Governance | none |
| Checkpoint C | 1785409841264 | Governance | none |
| Weekly Research Note | 1785409881241 | Production/Research | none |
| Decision Log Build | 1785538694105 | Production | none |
| Weekly Cognition Update | 1785559618604 | Production/Knowledge | none |
| Flow Evidence Enrichment | 1785896623311 | Evidence | none |
| Data Health Check | 1786030229208 | Production/Gate | none |
| Local DB Backup | 1786033017776 | Governance | none |
| Global Momentum Refresh | 1786677039167 | Evidence | none |
| Daily Finalize & Archive | 1786966060256 | Evidence/Archive | none |
| UST Yield Observer | 1787098043035 | Evidence | none |

**结论：现有 14 个任务全部 `fund_access=none`（机器无真实资金执行权限）。黄金 Execution Engine 将是系统第一个获得真实资金**机器执行权限**的 automation component——权限边界从 `Human → MT5` 变为 `Automation → MT5`。**

---

## 3. 新增 Execution 类任务的注册要求

任何 Execution 类 automation 注册前必须：
1. 引用 `XAUUSD_Execution_Engine_PreReg_v0.1.md` 的 Gate 状态
2. 在 `release_gate` 表写入 Execution Gate APPROVED 记录
3. Registry 条目显式标 `fund_access=execution` + 关联 Gate 级别（G0~G4）
4. 禁止任何 Execution 任务绕过 Risk Gate 直连 MT5

---

## 4. 建议

在 `automation_canonical_registry` 模板中永久加入 `fund_access` 字段，作为与 `layer` 并列的一级分类。Execution 类单独成节，不与 Production/Evidence 混排。

---

## 5. Erratum 变更日志（v1.0 → v1.1）

| ID | 类型 | 原缺陷 | 修正动作 | 状态 |
|---|---|---|---|---|
| **E3** | 权限语义 | 「系统第一个触碰真实资金的组件」措辞模糊，未区分人与机器 | 精确定义 `fund_access` = 机器向交易终端提交/修改/撤销真实资金订单的执行权限；明确权限边界从 `Human→MT5` 变为 `Automation→MT5`；结论改为「第一个获得机器执行权限的 automation component」 | **已精确化** |
