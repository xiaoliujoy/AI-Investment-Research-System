# SYSTEM_GOVERNANCE · 唯一当前状态源

> **版本**：v1.0 · **生效**：2026-09-24 · **依据**：治理裁定 **R8**（`.audit/P0C_STEP5C_RULING_R8_2026-09-24.md`）+ **V2 CIO Reconciliation 纠偏**（见 §0.1）
> **效力**：本文件是**唯一**当前治理状态源。任何旧文档（含 `AGENTS.md`、各 HANDOVER 文档、
> 历史 MEMORY）中与本文件冲突的表述，**一律以本文件为准**。
> **历史 audit 文件保持原样，不改写历史**（R8 §9.3）。

---

## 0. 全局治理模式

```yaml
GLOBAL_RELEASE_HOLD: RETIRED          # 2026-09-24 由 CIO 正式废止
SYSTEM_MODE:
  governance: COMPONENT_GATED
  effective: 2026-09-24
  principle: >-
    一个已证明的局部风险只能冻结它自己，不得再冻结整个系统开发。

NO_LONGER_AUTO_FROZEN_BY_ANY_LOCAL_BLOCKER:
  - Research / Ad-hoc Research
  - Architecture / M4 Design / Contracts
  - Documentation
  - Sandbox / Offline validation
  - Non-production development
```

**已废止的旧规则**（不再适用）：
- `RELEASE HOLD → automatically NO PUSH`
- 「任何 component HOLD ⇒ 全项目停摆」

### 0.1 V2 CIO Reconciliation 纠偏（2026-09-24，supersede R8 对应表述）

R8 与本文件 v1.0 中两处表述经 CIO 与 Codex 独立核对后被纠偏，以下为**当前执行状态**：

- **F17: PARTIAL_FIX → UNFIXED**。理由：`main_line_report.py` 的 F17 修复仅存在于 dirty working tree，未经独立 commit、未经回归验证、未经 ratification；dirty tree ≠ 已修复。F17 与 F17B 同处一文件，须与 Step 4（已 `ede5ea1` 版本化）分离提交。
- **NON_PRODUCTION_DEVELOPMENT: OPEN → CONDITIONAL_OPEN**。非生产开发允许开放，但受以下 4 项硬约束：

```yaml
NON_PRODUCTION_DEVELOPMENT: CONDITIONAL_OPEN
requirements:
  - isolated_environment:         # 不得触碰 canonical 生产库 vibe_research.db
  - zero_production_credentials:  # 不加载 backend/.env 真实密钥
  - zero_production_db_connection: # 任何连接须经 storage_policy 令牌裁决
  - no_automatic_deployment:      # 不自动发布 / 不自动下单
```

---

## 1. 组件状态表（当前）

| 组件 | 状态 | Gate 依据 | 最新证据 |
|---|---|---|---|
| STEP_4 | **RATIFIED_PASS** | 已独立复审，代码已版本化 | `P0C_STEP4D_TXN_INTEGRITY_2026-09-11.md`；commit `fix(bse)` |
| STEP_5A | **RATIFIED_PASS** | 不重复审计 | `P0C_STEP5A_SINGLE_DAY_CANARY_2026-09-11.md` |
| STEP_5B | **RATIFIED_PASS** | 幂等性 + S1=S2 有效 | `P0C_STEP5B_IDEMPOTENT_2026-09-12.md` |
| STEP_5C | **HOLD** | 连续 3 真实交易日 rc=0 未达成 | `P0C_STEP5C_RULING_R8_2026-09-24.md` |
| STEP_5D1 | **LOCKED** | gated by STEP_5C_RATIFIED_PASS | `P0C_CLOSURE_ORDER_LOCK_2026-09-15.md` |
| STEP_5D2 | **LOCKED** | 同上 | 同上 |
| STEP_5D3 | **HOLD** | blocker = HISTORICAL_MEMBERSHIP | `CANONICAL_UNIVERSE_GOVERNANCE_R2_2026-09-11.md` §4 |
| UNIVERSE_ENFORCE | **HOLD** | 待 5C RATIFIED 后验证 | 同上 |
| G01 | **HOLD (P0)** | FIXED_PENDING_RATIFICATION（commit `7d4b8df`；72 passed incl -O；Codex READONLY 复审） | `docs/HANDOVER/G01_CLOSURE_EVIDENCE_2026-09-24.md` |
| F17 | **HOLD** | FIXED_PENDING_RATIFICATION（commit `0c033a2`；V2 由 UNFIXED 升级） | `F17_UNIT_LINEAGE_AUDIT_2026-09-14.md`；main_line_report.py:100 二次 /1e8 |
| F17B | **HOLD** | FIXED_PENDING_RATIFICATION（commit `0c033a2`；latest_full_day ORDER BY date DESC） | `main_line_report.py:35-38`；test_f17b_latest_full_day.py |
| ARCHITECTURE | **OPEN** | — | R8 §1 |
| RESEARCH | **OPEN** | — | R8 §1 |
| NON_PRODUCTION_DEVELOPMENT | **CONDITIONAL_OPEN** | V2 supersede R8 OPEN；4 项 requirements 见 §0.1 | V2 CIO Reconciliation |
| PUSH | **COMPONENT_GATED** | 见 §3（t1-2-release 已推送 origin，main 未动） | R8 §7 |
| PRODUCTION_RELEASE | **COMPONENT_GATED** | — | R8 §1 |

---

## 2. Step 5C 当前窗口（R8）

```yaml
STEP_5C:
  mode: FORWARD_LIVE_3_TRADING_DAYS
  window: [2026-09-24, 2026-09-28, 2026-09-29]
  progress: 0/3
  physical_ledger: 12
  cumulative_ceiling: 18
  protocol: UNCHANGED (C1-C8 / K+4 / L1 lease / S1 窗 / verifier / no-retroactive)
  history:
    2026-09-16: PASS
    2026-09-17: PASS
    2026-09-18: SKIP (S1 时间门)
    2026-09-21: SKIP (S1 时间门)
    2026-09-22: NO_VALID_EXECUTION
    2026-09-23: NO_VALID_EXECUTION
  historical_valid_passes: [2026-09-16, 2026-09-17]   # 永久保留，不续入新序列
  retroactive_ratification: FORBIDDEN
  ratification: 3/3 rc=0 后仍须单独 STEP_5C_RATIFICATION
```

---

## 3. Push 治理（PUSH ≠ RELEASE）

```yaml
push_policy:
  verified_non_prod_changes: ALLOW
  ratified_governance_docs: ALLOW
  previously_verified_commits: ALLOW_AFTER_TOPOLOGY_CHECK
  unresolved_G01_F17_F17b_changes: NO
  canonical_db_mutation: SEPARATE_GOVERNANCE

FORBIDDEN:
  - force_push
  - public_visibility_change
  - new_public_remote
  - mixing_unverified_production_fix_into_verified_commit
```

---

## 4. 硬红线（任何 component 状态下均不得触碰）

- `canonical_db_manual_write: FORBIDDEN`
- `historical_membership_fabrication: FORBIDDEN`（禁用 current membership 冒充历史成员）
- `retroactive_ratification: FORBIDDEN`
- `historical_replay (for 5C): FORBIDDEN`
- Phase 1E FROZEN：不调阈值 / 权重 / veto / scoring
- P0-A：禁止重开 H2-A
- 生产安全纪律不变：不自动下单

---

## 5. 关联文档

- 裁定链：R5（09-18）→ R6（09-20）→ R7（09-21）→ **R8（09-24，现行）** → **V2 CIO Reconciliation（09-24 纠偏）**
- Step 5C 准据：`.audit/P0C_STEP5C_RUNBOOK_2026-09-12.md` §0
- 闭环顺序：`.audit/P0C_CLOSURE_ORDER_LOCK_2026-09-15.md`
- Universe 裁定：`.audit/CANONICAL_UNIVERSE_GOVERNANCE_R2_2026-09-11.md`
