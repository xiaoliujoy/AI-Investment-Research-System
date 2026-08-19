# ATS System Truth Table v1.0（架构事实盘点）

> **性质：Architecture Review，不是 Gap Analysis 2.0，不提新功能。**
> **时点：2026-08-19。** 在 H2-A / EQ-1 封板之后，做一次「我们到底有什么」的事实盘点。
> **四类状态定义（贯穿全文）：**
> - ① **已验证**：有数据、有实验、有明确结论，可依赖。
> - ② **已实现未验证**：代码存在且能跑，但未经独立样本 / 生产验证，不能当成事实。
> - ③ **研究 CLAIM**：有漂亮结果，但尚未通过完整研究 Gate（OOS / Robustness / Cost / Regime）。
> - ④ **尚不存在**：架构上需要，但当前根本没有。

---

## 0. 系统真相地图（System Truth Map）

```
ATS
│
├── Governance（治理层）
│   ├── Research Contract v0.1        ① 已验证（FROZEN，被 H2-A/EQ-1 实际跑过）
│   ├── Strategy Contract v1.0        ② 已实现未验证（DRAFT，空门槛）
│   ├── H2A/EQ1 Freeze Audit          ① 已验证（2026-08-19 封板）
│   ├── Trading Constitution v1.2      ② 已实现未验证（pre_trade_gate，仅卡录入）
│   └── Risk Governance v2.0          ② 已实现未验证（observe-only）
│
├── Data（数据层）
│   ├── MT5 历史导出（XAU/M1/M5/M15/trades）  ① 已验证（存在且被实验消费）
│   ├── Look-ahead 防护               ① 已验证（代码显式防前视）
│   ├── 研究/生产数据隔离             ① 已验证（无 live feed，全手工/批量）
│   ├── A股 / 全球实时行情            ④ 尚不存在
│   └── 实时执行/归因数据             ④ 尚不存在
│
├── Research（研究层）
│   ├── H2-A        FAIL / ARCHIVED           ① 已验证
│   ├── EQ-1        OBSERVATION / ARCHIVED    ① 已验证
│   ├── EQ-1R       OBSERVATION / ARCHIVED    ① 已验证
│   ├── EQ-1M       OBSERVATION / ARCHIVED    ① 已验证
│   ├── 黄金 E1/E4 入场质量          ③ 研究 CLAIM（VALIDATED 行为分类，未转策略）
│   └── 黄金 ATR×3 止损             ③ 研究 CLAIM（证据断链，标记存疑）
│
├── Strategy（策略层）
│   └── NO QUALIFIED STRATEGY         ④ 尚不存在（契约空着，正确）
│
├── Portfolio / CIO（配置层）
│   ├── CIO 决策引擎                  ② 已实现未验证（advisory，position_pct 被硬编码冻结）
│   ├── Risk Budget / Position Layer  ② 已实现未验证（资产配比%，单笔手数未接）
│   └── 自适应反哺（Learning→CIO）    ② 已实现未验证 + 缺口（见边界4）
│
├── Execution（执行层）
│   ├── 订单发送 / 券商连接           ④ 尚不存在（设计上不建）
│   ├── discipline_server pre_trade   ② 已实现未验证
│   ├── RISK_GUARD                    ② 已实现未验证（DISABLED shadow）
│   └── 实时执行流水线                ④ 尚不存在
│
├── Risk / Safety（风险安全层）
│   ├── 交易宪法准入                  ② 已实现未验证
│   ├── 风险治理否决（数据/IC/危机）  ② 已实现未验证（只观测不执行）
│   ├── 单笔/日亏上限                 ④ 尚不存在（契约 R2.1~R2.3 OPEN）
│   ├── Daily Lock（每日锁定）        ④ 尚不存在
│   └── Kill Switch / 熔断            ④ 尚不存在（契约 R2.4 / F4 OPEN）
│
└── Learning / Feedback（学习层）
    ├── Learning Center               ② 已实现未验证（Record-Only，默认 OFF）
    ├── Coach                         ② 已实现未验证（observe-only）
    ├── Release Gate（人工审批）      ② 已实现未验证（存在但未接 ADAPTIVE 开关）
    └── Learning→生产参数自动回写      ✗ 当前不能（靠默认关+硬编码，非架构闸门）
```

---

## 1. 七层事实盘点

### L0 Research Governance（研究治理）
| 组件 | 状态 | 证据 |
|---|---|---|
| Strategy Research Contract v0.1 | ① 已验证 | `docs/Strategy_Research_Contract_v0.1.md` FROZEN；H2-A/EQ-1 实际跑过其 13 字段 + Evidence 状态机 |
| 预登记 + Gate 0 令牌机制 | ① 已验证 | `exit_observation_h2a.py`、`entry_quality_eq1.py` Gate 0 执行过，mtime 检查通过 |
| 冻结 / 归档 / 禁止推论 | ① 已验证 | `docs/H2A_EQ1_Final_Freeze_Audit.md` 已落盘，5 问 + FORBIDDEN 清单 |
| ATS Strategy Contract v1.0 | ② 已实现未验证 | `docs/ATS_Strategy_Contract_v1.0.md` DRAFT，结构完整但尚未被任何策略填充 |

### L1 Data（数据）
| 组件 | 状态 | 证据 |
|---|---|---|
| MT5 历史导出（XAUUSD M1/M5/M15 + trades 2.1万行） | ① 已验证 | `mt5_raw/`，被所有实验消费 |
| Look-ahead 防护 | ① 已验证 | `exit_observation_h2a.py:635` 等显式 `bisect_right(times, entry_unix-300)`；全局 grep `shift(-`/`iloc[+n` 无命中 |
| 研究/生产数据隔离 | ① 已验证 | 无 realtime/websocket/broker 接口；全靠 `mt5_export.py` 手工 + akshare 批量 |
| A股 / 全球行情数据 | ④ 尚不存在 | `a-stock-data/`、`global-stock-data/` 仅含第三方 skill 仓库，无行情文件 |
| 实时行情 / 执行归因流 | ④ 尚不存在 | 同上；无任何 live feed |

### L2 Research（研究）
| 组件 | 状态 | 证据 |
|---|---|---|
| H2-A | ① 已验证 FAIL | baseline E2=46.2%，Archetype A=202(96%)/B=0/C=8，perm pct 40.7% |
| EQ-1 / EQ-1R / EQ-1M | ① 已验证 OBSERVATION | 均 2026-08-15 执行；H3 IAE→Giveback ρ=0.532、EQ-1R ρ=0.571、EQ-1M indirect=0.083（perm 100%） |
| 黄金 E1/E4 入场质量 | ③ 研究 CLAIM | `RC-GOLD-ENTRY-E1E4.json` CLAIM；+$2389.3 / n=46，行为分类非可交易规则 |
| 黄金 ATR×3 止损 | ③ 研究 CLAIM（存疑） | `RC-GOLD-STOP-ATR3.json` CLAIM；PF1.52 证据链断，封板审计已标记 |

### L3 Strategy（策略）
| 组件 | 状态 | 证据 |
|---|---|---|
| 合格 Strategy | ④ 尚不存在 | Strategy Contract v1.0 全部执行段 OPEN/PARTIAL，无 APPROVED 字段 |
| 契约闸门 | ② 已实现未验证 | 结构存在，等策略出现后逐字段 REVIEW |

### L4 Execution（执行）
| 组件 | 状态 | 证据 |
|---|---|---|
| 订单发送 / 券商 API | ④ 尚不存在（设计上不建） | `backend/committee/investment_committee.py:115` "系统不自动下单，权限保留在人"；`backend/brain/render.py:959` 红线"不替你下单" |
| discipline_server pre_trade_gate | ② 已实现未验证 | 只读 trade_path 做计划录入检查，无券商连接 |
| RISK_GUARD | ② 已实现未验证 | `RISK_GUARD_ENABLED=0`，Shadow 只读否决，不接管、不发单 |
| 实时执行流水线 | ④ 尚不存在 | 无任何 Order/Execute/Broker 代码 |

### L5 Risk / Governance（风险治理）
| 组件 | 状态 | 证据 |
|---|---|---|
| Trading Constitution v1.2 | ② 已实现未验证 | `backend/os_layers/trading_constitution.py` 管计划录入准入，不连实盘 |
| Risk Governance v2.0 | ② 已实现未验证 | `backend/risk_governance.py` observe-only，"只记录不修改 CIO 决策" |
| Risk Budget / Position Layer | ② 已实现未验证 | `risk_budget.py` 资产配比%、`position_layer.py` 持仓分层；单笔手数未接自动轨道 |
| 单笔/日亏上限 | ④ 尚不存在 | Strategy Contract R2.1~R2.3 OPEN |
| Daily Lock | ④ 尚不存在 | grep `daily_lock`/`复盘锁` = 0 命中 |
| Kill Switch / 熔断 | ④ 尚不存在 | 仅条件否决（数据异常/IC偏空/危机），无账户级一键停机 |

### L6 Learning / Feedback（学习反馈）
| 组件 | 状态 | 证据 |
|---|---|---|
| Learning Center | ② 已实现未验证 | `backend/learning_center.py`，`ADAPTIVE_FEEDBACK_ENABLED=0` Record-Only |
| Coach | ② 已实现未验证 | `coach_diagnostics.py` observe-only，不回写参数 |
| CIO | ② 已实现未验证 | `cio_agent.py` advisory；`position_pct` 在 `investment_committee.py:288` 被硬编码冻结，不消费学习输出 |
| Release Gate（人工审批） | ② 已实现未验证 | `release_gate.py` 存在，但**未接 `ADAPTIVE_FEEDBACK_ENABLED` 校验**（缺口，见边界4） |
| Learning→生产自动回写 | ✗ 当前不能 | 靠默认 OFF + 硬编码冻结；非架构闸门强制 |

---

## 2. 五个边界审查（最关键部分）

### 边界 1：Research → Strategy
**判定：工作正常。**
- H2-A FAIL + EQ-1 OBSERVATION 已用事实证明「研究发现 ≠ 交易策略」。
- Strategy Contract v1.0 已充当闸门，当前状态 NO QUALIFIED STRATEGY —— 这正是它的设计目的。
- 没有证据显示研究结论被直接当策略用。✓

### 边界 2：Strategy → Execution
**判定：需修正认知。「不建」是设计决策，不是缺口。**
- 用户的原话把 L4 标为「故意不建」。核查后必须拆清：
  - **订单发送 / 券商连接 = 设计上不建**（human-in-the-loop，红线不替你下单）。这与 Trading OS 整体定位一致，决策**仍然正确**，不应补建。
  - **风险治理 / 宪法 / 仓位预算代码 = 已存在**（L5），但它们是「观测 / 建议」，不自动执行。
- 所以准确表述：**L4 自主下单层在架构上不建；L5 治理代码已实现但未验证、且不接管。** 两者不矛盾。

### 边界 3：Execution → Risk（谁决定什么）
**判定：职责清晰但「停止」能力缺失。**
- 准入：代码自动为主（`data_health.py` 数据异常→禁交易；`investment_committee.py` comp≥70→can_buy=NO；宪法闸 + `risk_guard` Shadow）。
- 仓位：资产配比由 `risk_budget` 出，月度人工调仓；**单笔手数未实现**。
- 停止：❌ **无 Daily Lock、无 Kill Switch、无账户级熔断**。目前只有条件否决（数据异常 / IC 偏空 / 危机降仓），**无一键停机**。
- 含义：在人工下单模式下可接受；但若未来走到 Paper/Live，这是硬缺口，必须先补。

### 边界 4：Learning → Production（最高风险边界）
**判定：当前不能越权，但保护靠「默认关+硬编码」，不是「架构闸门」。存在代码级缺口。**
- 事实链条：`ADAPTIVE_FEEDBACK_ENABLED` 默认 `"0"` → `pos_scale` 在 `investment_committee.py:288` 硬冻结（只写 `learning_note`，永不回写）→ 执行/风控层不消费 learning 输出。所以**当前确实不能自动改生产参数**。
- **缺口**：`release_gate.is_approved()` 本应拦截自适应反哺，但 `learning_center.py:48` 只读了 env var，**未调用 release_gate 校验**。文档要求「经 Release Gate 审查」，代码未联动。
- 风险等级：当前低（默认 OFF），但架构不干净。一旦有人开着 env 跑，闸门形同虚设。
- **建议（仅记录，不执行）**：要么删除该 env 开关路径，要么把 `ADAPTIVE_FEEDBACK_ENABLED` 强制接 `release_gate.is_approved("adaptive_feedback")`。

### 边界 5：CIO → Strategy
**判定：解耦成立，但靠「冻结 hack」而非干净接口。**
- CIO 输出 `can_buy` / `position_pct`，但 `investment_committee.py:288` **硬编码忽略 `position_pct`**，CIO 的仓位建议在消费端被丢弃 → 自然避免了「CIO 评分变化 → 策略参数变化 → 交易行为变化」。
- 这是「解耦」，但实现方式是 freeze 而非接口隔离。功能性 OK，工程上脆弱（未来启用自适应时易踩雷）。

---

## 3. 系统真相总表（Truth Table）

列：模块 | 状态(①/②/③/④) | 证据等级 | 依赖 | 允许进生产？ | 下一步

| 模块 | 状态 | 证据等级 | 依赖 | 进生产？ | 下一步 |
|---|---|---|---|---|---|
| Research Contract v0.1 | ① | 高 | — | 是（研究层） | 维持 FROZEN |
| 预登记/Gate0机制 | ① | 高 | — | 是 | 维持 |
| H2A/EQ1 Freeze Audit | ① | 高 | — | 是（归档） | 维持 |
| Strategy Contract v1.0 | ② | 中 | 合格策略 | 否（空门槛） | 等策略填充 |
| MT5 历史数据 | ① | 高 | — | 是（研究） | 维持 |
| Look-ahead 防护 | ① | 高 | — | 是 | 维持 |
| A股/全球实时行情 | ④ | — | 数据源 | 否 | 不急于建 |
| H2-A | ① | 高 | — | 否（已FAIL） | 封存，禁止重战 |
| EQ-1/R/M | ① | 高 | — | 否（OBSERVATION） | 封存，禁止当信号 |
| 黄金 E1/E4 | ③ | 中 | OOS验证 | 否 | 需新预登记转策略 |
| 黄金 ATR×3 | ③ | 低(存疑) | 证据重查 | 否 | 证据断链，标记 |
| 合格 Strategy | ④ | — | 研究Gate | 否 | 暂无，正确 |
| 订单发送/券商 | ④ | — | 设计不建 | 否 | 维持不建 |
| discipline_server | ② | 中 | — | 否 | Paper前验证 |
| RISK_GUARD | ② | 中 | 人工release | 否（Shadow） | 保持DISABLED |
| 交易宪法 v1.2 | ② | 中 | — | 部分（录入） | Paper前验证 |
| Risk Governance v2.0 | ② | 中 | — | 否（观测） | 维持observe |
| Risk Budget/Position | ② | 中 | CIO | 否（建议） | 单笔手数未接 |
| 单笔/日亏上限 | ④ | — | — | 否 | Paper前必建 |
| Daily Lock | ④ | — | — | 否 | Paper前必建 |
| Kill Switch/熔断 | ④ | — | — | 否 | Paper前必建 |
| Learning Center | ② | 中 | 人工审批 | 否（OFF） | 保持OFF |
| Coach | ② | 中 | — | 否（观测） | 维持 |
| CIO | ② | 中 | — | 否（建议） | 维持冻结消费 |
| Release Gate | ② | 中 | 人工 | 部分 | **接ADAPTIVE校验** |

证据等级说明：高=有实验产物+复现；中=代码存在但未独立验证/仅观测；低=存疑或断链；—=不适用。

---

## 4. 截至 2026-08-19，我们到底有什么

**真的（① 已验证）：**
- 一套能跑通「假设→预登记→执行→FAIL/观察→复现→封存→停止」的研究机器（H2-A + EQ-1 家族为证）。
- 完整的研究治理契约（Research Contract + Strategy Contract + Freeze Audit）。
- 干净的历史数据 + 显式防前视。
- 风险治理/宪法/仓位代码骨架（但仅观测/建议）。

**只是代码（② 已实现未验证）：**
- 交易宪法、风险治理、RISK_GUARD、Learning Center、Coach、CIO、discipline_server。
- 它们能跑，但**没有任何一个经过独立样本或生产验证**，不能当成事实依赖。

**只是 CLAIM（③）：**
- 黄金 E1/E4 入场质量、黄金 ATR×3 止损。漂亮，但未转策略、ATR×3 证据断链。

**还没有（④）：**
- 任何合格策略、订单执行层（设计不建）、实时行情、单笔/日亏上限、Daily Lock、Kill Switch。

**绝对不能碰：**
- 把 EQ-1 的 IAE→Giveback 当因果/信号；不经新预登记塞进 Strategy Contract；把黄金 CLAIM 误读为已验证；开启 Learning→生产回写（除非 Release Gate 强制校验先接上）。

---

## 5. 这张表的目的

不是规划未来，而是回答：**截至今天，什么是真的、什么是 CLAIM、什么已失败、什么还没建、什么绝对不能碰。**

下一步（由你从全局视角决定，本表不提案）：
- 若走向 Paper/Live：必建 ④ 中的 单笔/日亏上限 + Daily Lock + Kill Switch，并修边界4的 Release Gate 缺口。
- 若继续研究：从新预登记开始（黄金 E1/E4 转策略 或 前向风险调整收益），不续接 EQ-1。
- 策略层继续保持空：宁可空着，不拼未经完整验证的策略进生产。

---

## 6. 系统基线状态与冻结决策（2026-08-19 收束）

### 6.1 新总状态
`ATS v0.x: RESEARCH-GOVERNANCE COMPLETE / PRODUCTION NOT QUALIFIED`
研究基础设施已达可严肃研究程度；整个 ATS 尚未达到"策略生产化"资格。

### 6.2 冻结决策（本轮拍板 · 今天不开发）
| 项 | 决策 |
|---|---|
| H2-A | 继续封板：不重新解释、不从 FAIL 找新策略、不因 EQ-1 漂亮结果启动 H-Next |
| EQ-1 | 继续 Observation：IAE→Giveback→Exit 不得升级为交易规则；Observation ≠ Strategy Discovery |
| Strategy Contract | 继续保持空（∅）；宁可空，不填 CLAIM |
| Learning→Production | 列为 **P0 Architecture Integrity Gap**；今天不修，仅标记 |
| Daily Lock / Kill Switch | 不立即开发（无合格策略+自动执行前 ROI 低）；属 Paper/Live 前置，非当前 P0 |
| Auto Execution | 不存在，保持不补 |
| Learning | 保持关闭，不打开 |

### 6.3 核心原则（本轮确立）
> 任何没有经过状态升级的东西，都不能因为代码已经存在，就被当成系统能力。

等价于 H2-A / EQ-1 封板逻辑在研究治理层的推广。

### 6.4 Architecture Integrity Gap vs Feature Gap
| 类型 | 含义 | 例子 |
|---|---|---|
| 功能缺失（Feature Gap） | 系统缺少一个能力 | Daily Lock / Kill Switch 不存在 |
| 架构完整性缺口（Integrity Gap） | 系统已有"可能改变生产行为的能力"，但治理边界未真正闭合 | Learning→env flag→Production（靠默认关+硬编码，非 Release Gate 强制） |

判定：**Integrity Gap 优先级 > Feature Gap**。前者是"已存在能力绕过治理"，后者只是"没有能力"。

### 6.5 剩余不确定性（架构可信度审计待解）
1. Risk Governance 真实代码行为是否与文档一致（是否真的只观测不修改）
2. Learning Gate 缺口是否还有其他类似绕行路径
3. CIO / Coach / discipline_server 是否存在未发现的生产影响链
4. 未来是否真出现经预登记、独立验证、稳健性检验后可进 Strategy Contract 的策略

### 6.6 下一阶段唯一允许的活动
从本 Truth Table 出发，做**架构可信度审计**：验证还有没有"事实上的生产影响路径"被漏掉。完成此步，ATS 才从"功能盘点"进入"架构可信度审计"。

---

## 7. 架构可信度审计结果（2026-08-19 · 只读污点追踪）

> 目标：验证除已知 Learning Gate 外，是否还有"研究/学习/观测输出 → 生产决策"的未闸门路径。

### 7.1 闸门分布事实
- `release_gate.is_approved()` 全仓仅一处调用：`backend/risk_guard.py:162`（保护 `risk_guard_takeover` 接管），且 `RISK_GUARD_ENABLED=0` 硬编码。即**唯一被架构闸门保护的只有 RISK_GUARD 接管路径**——该路径正确闭合。

### 7.2 五条路径追踪结论
| 路径 | source → sink | 经闸门？ | 判定 |
|---|---|---|---|
| A Learning Gate（已知） | `learning_center.py:48` env → `orchestrator.py:98` 调总置信度；`investment_committee.py:287` pos_scale 仅入 learning_note | 无 | **Integrity Gap**（真实可达生产的仅"置信度数字"，pos_scale/can_buy 被 IC 冻结隔离） |
| B Risk Governance | `risk_governance.py:134` → `cio_decision_history` 治理列 | 无需 | **安全（只记录不修改，与文档一致）** |
| C CIO | `cio_decision_engine.py:136` → `cio_decision_history`；消费方仅只读报表 | 无需 | **安全（未接入任何交易/准入决策）** |
| D Coach / EQ-1 / H2A | 写 observation JSON（自带契约 Hard Gate） | 契约内 | **安全（无生产消费方）** |
| E discipline_server | 执行层 grep 观测层关键词全无匹配 | — | **安全（执行层不消费观测层）** |

### 7.3 DB 桥接核查
`learning_log.jsonl` 仅学习层自读；`cio_decision_history` 治理列只记不改；**无"观测写→决策读"的未闸门字段桥**。

### 7.4 审计结论
**除已知 Learning Gate 外，未发现第 2、第 3 处未闸门的生产影响路径。** 系统生产决策边界比单一 Learning Gate 暗示的更紧：
- Risk Governance 真实行为 = 文档一致（observe-only）✓ 不确定性#1 消除
- 无其他 Learning 式绕行路径 ✓ 不确定性#2 消除
- CIO/Coach/discipline 均无未发现的生产链 ✓ 不确定性#3 消除

**唯一残留 Integrity Gap（同已知 Learning Gate，非新路径）**：`ADAPTIVE_FEEDBACK_ENABLED`（`learning_center.py:48`）仍可在无 `release_gate` 审批下翻转，当前仅由"默认关闭 + IC 硬编码冻结 pos_scale/can_buy"保护。真实爆炸半径 = 仅总置信度数字，仓位/准入被冻结隔离 → 当前低危，但架构不干净。

### 7.5 对基线状态的修正
`ATS v0.x: RESEARCH-GOVERNANCE COMPLETE / PRODUCTION NOT QUALIFIED` 维持。审计未改变"PRODUCTION NOT QUALIFIED"结论，但将"未知生产影响路径"风险从**开放**降为**已知且隔离**。架构可信度：中等偏高（唯一缺口已定位、低危、未闭合但被默认配置隔离）。
