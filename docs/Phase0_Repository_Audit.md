# Phase 0 · Repository Audit（只读，未改代码）

> 依据 `docs/PRD_v0.2_Final_v1.0.md` 的 Master Execution Prompt 执行。  
> 本阶段**只审计、不修改**。所有结论基于实际读取的源码（非记忆）。  
> 审计时间：2026-08-13。审计范围：backend 决策主链路 + docs。

---

## 1. 当前真实架构

```
daily_collect.py → tech_fill.py → run_daily.py (编排)
        │
        ├─ decision_tree.py        8 层骨架；L4/L5/L7/情绪/基本面已接；L6 已降级为边界声明(不输出候选)
        │     └─ layer7_risk()     三维加权 composite(市场0.45/行业0.30/个股0.25) → position 字符串
        ├─ investment_committee.py decide()   12 层 _DEBATE_LAYERS 加权投票 + hard_no
        │     └─ hard_no: L1 bearish / FLOW bearish / sentiment 退潮冰点 / L7 composite>=70
        ├─ brain/cio_agent.py produce()       规则驱动 13 段 memo + EvidenceBlock(claim/uncertainty)
        │     └─ 读 brain_report.json + decision_tree.json → InvestmentDecisionMemo
        ├─ learning_center.py              prediction replay / dimension_accuracy / suggested_weights / prediction_feedback(pos_scale)
        ├─ data_health.py                 5 点校验 → trade_allowed（现有 Data Health Gate）
        └─ database/models.py             11 张表，无 Ledger/Evidence/Version
```

**关键事实（已核实）**：

- IC 生产权重是 `_DEBATE_LAYERS`（硬编码），README 宣称的"资金40/产业25/宏观15/技术10/风险10"是 `learning_center._BASE_DECISION_WEIGHTS`，**未回灌生产**。
- `learning_center.suggested_weights()` 计算动态权重但**未接到生产**；`prediction_feedback().pos_scale` **已**在 `investment_committee.decide()` 中缩放 `position_pct`（这是冻结期必须关停的一处）。
- `learning_center` 用文件 `output/learning_log.jsonl` 记录（非 DB），字段简单、无 evidence/version/归因。
- `run_daily.py` 自动归档 `brain_report_{date}.json` 到 `output/archive/`（这是现有最接近快照的机制）。

---

## 2. PRD 与代码的差异

| PRD 要求                 | 代码现状                                    | 差距                                    |
| ---------------------- | --------------------------------------- | ------------------------------------- |
| 冻结权重/评分/Risk Budget    | `_DEBATE_LAYERS` 硬编码、L7 三维权重硬编码         | 已满足（参数本就冻结）                           |
| Risk 前置硬约束（gate 非投票）   | L7 仅 comp>=70 触发 hard_no，中等风险被加权稀释      | 需提取为独立 `risk_guard` 前置 gate（行为零变化）    |
| 停用 pos_scale 自动缩放生产仓位  | `prediction_feedback().pos_scale` 已自动缩放 | **需关停**（唯一在跑的自校准）                     |
| Decision Ledger（不可变账本） | 无，仅 jsonl 轻量日志                          | 新增 7 表                                |
| Evidence 层（结构化）        | EvidenceBlock 是非结构化文字                   | 新增 evidence 表 + 各 layer 钩子            |
| Snapshot Versioning    | VERSION.py 不存在；archive 仅存 brain_report  | 新增 VERSION.py + 6 维版本 + data_snapshot |
| 四层 Outcome 归因 + 错误类型   | 仅 T+1 板块净流命中代理                          | 新增 outcome_attribution                |
| Shadow Mode            | 无                                       | 新增 shadow_run + 影子并行                  |
| 文档 v2                  | README/architecture 写"权重非固定"            | P1 对齐                                 |

---

## 3. 每个改造点对应的真实代码位置

| PRD 项                                                                                            | 改造落点（文件:位置）                                                                                                                                   | 动作                  |
| ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| P0#1 Schema 7 表                                                                                  | `database/models.py:init_db()` (~L26)                                                                                                         | 新增 7 张 CREATE TABLE |
| P0#2 VERSION 六维                                                                                  | 新建 `backend/VERSION.py`；写入 `decision_version`/`decision_run`                                                                                  | 新建 + 在 Ledger 写入时落库 |
| P0#3 Run/Item/Evidence 写入                                                                        | `brain/cio_agent.py:produce()` 末尾；新建 `write_decision_ledger.py`                                                                               | 末尾钩子 + 新建模块         |
| P0#4 data_snapshot(Manifest)                                                                     | 新建 `write_decision_ledger.py` 内生成 snapshot_id + manifest                                                                                      | 新建                  |
| P0#5 risk_guard                                                                                  | 新建 `backend/risk_guard.py`；源逻辑来自 `decision_tree.py:layer7_risk()`(composite) + `investment_committee.py:decide()`(comp>=70→hard_no)           | 仅适配器，读取现有 composite |
| P0#6 pos_scale 冻结                                                                                | `learning_center.py:prediction_feedback()`(~L596) 改 `applied=False`；`investment_committee.py:decide()`(~L284) `feedback.get("pos_scale")` 仅人审 | 关停生产影响              |
| P0#7 流水线接入                                                                                       | `run_daily.py:STEPS`(~L40) 插入 Ledger 步骤                                                                                                       | 插入（单步失败不影响整体）       |
| P0#8 Shadow                                                                                      | 新建 `shadow_run` 表 + `risk_guard` shadow 模式 + `run_daily`                                                                                      | 新建 + 影子并行           |
| P1 Risk Center / Env Gate / Veto Replay / Evidence Independence / Process Score / LLM 边界 / 文档 v2 | 分别在 risk_guard 扩展、data_health 扩展、learning_center、decision_item.independence_flag、cio_agent 注释、docs                                            | P1（不在本阶段）           |

---

## 4. 风险点

1. **cio_agent.py 体量（~2000 行）**：Ledger 钩子必须挂在 `produce()` 已持有 `memo + results + committee` 的位置，且**不改 memo 内容**。建议就在 `produce()` return 前插入 `write_decision_ledger(...)`，传入已存在的 dict。
2. **risk_composite 来源一致性**：Golden Master 取 `risk_composite` 应统一从 `brain_report.results["L7"]["raw"]["composite"]` 读取，避免与 committee 内派生值混淆。
3. **learning_log.jsonl 与 DB Ledger 并存**：PRD 明令"不改现有 jsonl"。新增 DB ledger 是增量，不删 jsonl，避免回放历史断档。
4. **Golden Master 样本可得性**：`output/` 被 gitignore，历史 `brain_report_*.json` 可能仅存近期若干份。审计建议：扫描 `output/archive/brain_report_*.json` 计数；若 <30，用 `run_daily` 历史重跑或放宽 N（但必须覆盖 EXTREME/hard_no 样本）。**此项需在 Phase 1 开工前确认，否则 Golden Master 无法建立。**
5. **冻结守护误伤**：任何新代码若 import `_DEBATE_LAYERS` 并改写，即违规。单测必须静态扫描。
6. **FROZEN_RULE_VIOLATION 上报机制**：需在 CI/测试里定义，违规即停，不自行修复。

---

## 5. 预计修改 / 新增文件

**新增（无现有逻辑风险）**：

- `backend/VERSION.py`
- `backend/risk_guard.py`
- `backend/write_decision_ledger.py`
- `docs/PRD_v0.2_Final_v1.0.md`（已完成）、本审计文件

**修改（逻辑保持不变，仅加钩子/开关）**：

- `backend/database/models.py` — 仅 `init_db()` 追加 7 表
- `backend/brain/cio_agent.py` — `produce()` 末尾加 Ledger 写入钩子
- `backend/learning_center.py` — `prediction_feedback()` 停用生产影响
- `backend/committee/investment_committee.py` — `pos_scale` 改为仅人审
- `backend/decision_tree.py` — 各 layer 返回加 `evidence` 钩子位（不改计算）
- `backend/run_daily.py` — `STEPS` 插入 Ledger 步骤

**现有测试（需确认不被破坏，不修改其行为）**：

- `backend/tests/test_gate.py` `test_scoring.py` `test_constitution.py` `test_api.py` `test_fixes.py` `test_live.py` `test_pure.py` `test_reports_and_security.py` `test_panqian_hotlist.py` `test_flow_e2e.py`
- `backend/asset_intelligence/tests/*` `backend/equity_engine/tests/*`
- 新增 Golden Master 回归测试（独立新文件，如 `backend/tests/test_golden_master.py`）。

---

## 6. 不需要修改的文件（行为/逻辑完全不动）

- `backend/data_health.py` — 现有 Data Health Gate 原样保留（PRD 明确"保留现有 Data Health Gate"）。
- `backend/decision_tree.py` 的**评分与 L7 计算逻辑** — 仅加 evidence 钩子位，composite/position 计算零改动。
- `backend/committee/investment_committee.py` 的 `_DEBATE_LAYERS` 与 `decide()` 投票逻辑 — 仅调整 `pos_scale` 消费方式。
- `backend/learning_center.py` 的 `suggested_weights` / `dimension_accuracy` / `replay` / `build` — 保留为观察工具，不改算法。
- `backend/narrative_engine.py` `capital_migration.py` `relationship_engine.py` `cro_agent.py` `gold_engine/` `capital_flow/` 等引擎 — 不在改造范围。
- `frontend/` — 不在改造范围（P0 不改 UI）。
- `docs/architecture.md` `design-principles.md` `roadmap.md` `README.md` — P1 才对齐（本阶段不改）。

---

## 7. 现场核验补充（Golden Master 样本）

- `backend/output/archive/brain_report_*.json` 现存 **23 份** + 当前 `brain_report.json` 1 份 = **共 24 份**，低于 PRD §1.4 要求的 N≥30。
- 本地 `stock_daily` / `sector_daily` / `market_daily` 含历史数据（最新约 2026-08-12），理论上可对过去日期重跑 `decision_tree + run_brain_report` 回填历史 `brain_report`，补齐到 ≥30 且覆盖 EXTREME/hard_no 样本。
- **建议**：Phase 1 开工第一步即执行"样本补齐"——优先保证类别覆盖（YES/NO/不同 position/L7 各 composite 区间/至少若干 hard_no），N 可暂以"可用覆盖"为准（≥24 但含全类别），并在 `test_golden_master.py` 里固定这批 fixture 路径，禁止后续覆盖。

## 8. Phase 0 结论与下一步

- **就绪度**：架构清晰、冻结项已实质冻结、唯一在跑的自校准（pos_scale）定位明确，改造风险可控。
- **唯一阻塞项**：Golden Master 样本数 ≥30 需先确认 `output/archive/brain_report_*.json` 存量（见风险点 4）。建议 Phase 1 开工第一步即扫描计数。
- **建议进入 Phase 1 的顺序**（与 PRD 时间表一致）：先建 Schema + VERSION + Ledger/Evidence 写入 + data_snapshot（Week 1），跑通后即刻开始每日积累；再 RISK_GUARD + pos_scale 冻结 + 流水线（Week 2）；再 Replay + 归因（Week 3）；最后 Shadow 对照（Week 4 起）。
- **本阶段零代码改动**，遵守 Master Prompt "在 Audit 完成之前不要进行大规模修改"。
