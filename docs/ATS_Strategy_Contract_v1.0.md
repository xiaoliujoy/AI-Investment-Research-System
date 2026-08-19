# Automated Trading System · Strategy Contract v1.0（草案）

> **状态：v1.0 DRAFT（结构定义，2026-08-19 定稿）。未批准为生产契约。**
> **定位：生产层执行语言。** 在 `Strategy_Research_Contract_v0.1`（研究语言）之上，把已通过研究审计的结论转化为机器可执行的固定规则。
> **治理：** 本契约本身不产生订单、不触碰 `run_daily` / `risk_guard` / `shadow`。契约的每一个字段获得「APPROVED」之前，对应策略不得进入自动执行。
> **与交易宪法 v1.2 的关系：** 交易宪法管人工 A 股下单的 pre-trade 资格；本契约管自动交易轨道（初始目标 XAUUSD / MT5）。两者不互相替代。

---

## 1. 为什么需要第二份契约

Research Contract v0.1 回答「这个发现是真是假」。但它不回答「机器到底怎么交易」。

例：研究结论「E3/E4 的入场质量明显优于 E1/E2」——这是研究结论，不是交易规则。自动交易必须继续回答：

- 什么情况定义为 E3？E4？
- 什么时候允许入场？
- 止损在哪？
- 退出条件是什么？
- 仓位怎么算？
- 最大风险是多少？
- 数据缺失 / 信号冲突 / 程序异常怎么办？

只有全部固定，才进入 Strategy Specification，再往后才能 Backtest → Paper → Live。

**本契约的每一个字段都必须是机械可执行、不可人工解释的。** 任何「到时候看情况」的描述都属于无效字段。

---

## 2. 契约状态机

```
DRAFT → REVIEW → APPROVED → ACTIVE → SUSPENDED → RETIRED
```

| 状态 | 含义 |
|---|---|
| DRAFT | 结构已定义，字段未填或有 OPEN |
| REVIEW | 字段全部填满，待人工审查 |
| APPROVED | 经人工 Release Gate，允许进入 Backtest（非实盘） |
| ACTIVE | 允许 Paper / 小资金 Live |
| SUSPENDED | 触发熔断或失效条件，暂停执行 |
| RETIRED | 永久淘汰 |

**单向前进原则（同 Research Contract）**：状态升级必须逐级，回退必须走 Erratum/事件记录，禁止静默篡改。

---

## 3. 字段结构（10 大段 + 2 治理段）

> 每段字段必须包含：定义（机械可执行） + 现状审查（OPEN / PARTIAL / APPROVED）+ Evidence 支撑（引用 Research Contract 的 RC-ID 与 Evidence Status）。

### M. Market（市场 / 标的）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| M1 资产/品种 | 交易什么？XAUUSD？多个品种列表？ | OPEN |
| M2 周期 | M5？M15？多周期？ | OPEN |
| M3 时间区 | 交易时段（伦敦/纽约/亚洲）是否限制 | OPEN |
| M4 数据源 | 历史+实时行情来自哪（MT5？） | OPEN |
| M5 数据版本 | 数据冻结版本号（防 look-ahead 必备） | OPEN |

### R. Regime（环境过滤）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| R1 环境定义 | 什么算趋势/震荡/高波动？须全部事前变量 | PARTIAL（观察层有 Risk State，未接决策） |
| R2 过滤规则 | 某 Regime 下：禁止开仓 / 降权 / 正常 | OPEN |
| R3 Regime 切换 | 状态切换的滞后规则，防 whipsaw | OPEN |

### S. Setup（可交易形态）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| S1 Setup 定义 | 完整可交易形态 = Signal + 条件组合，每个条件机械可复现 | **OPEN（H2-A 3 Archetype 已 FAIL）** |
| S2 条件参数 | lookback / 阈值 / 过滤器全部写死 | OPEN |
| S3 Setup 版本 | 冻结，禁调参 | OPEN |

### E1. Entry（入场）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| E1.1 触发条件 | 精确触发（价格/时间/指标条件） | PARTIAL（黄金 E1/E4 有入场实证，非自动规则） |
| E1.2 订单类型 | Market / Limit / Stop | OPEN |
| E1.3 生效时段 | 何时允许入场 | OPEN |

### S2. Stop（止损 / 失效位）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| S2.1 失效位定义 | 精确位置（ATR×N？结构位？） | **OPEN（ATR×3 PF1.52 为 CLAIM，找不到来源，证据断链）** |
| S2.2 触发执行 | 触发即平仓，无例外 | OPEN |

### E2. Exit（退出）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| E2.1 兑现规则 | TP / Trailing / Time stop / 事件退出，至少定一种 | **OPEN（最大泄漏点：exit capture −0.697）** |
| E2.2 Exit 参数 | 固定，禁调 | OPEN |

### P. Position Size（仓位）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| P1 风险预算 | 每笔固定风险（如账户 0.5%） | PARTIAL（风险预算公式已有，未接自动轨道） |
| P2 手数公式 | 手数 = 风险预算 ÷ (入场价 − 止损价) | PARTIAL |
| P3 上限约束 | 最大手数 / 杠杆上限 | OPEN |

### R2. Risk Limit（账户级风险）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| R2.1 单笔上限 | 单笔最大亏损 | OPEN |
| R2.2 日亏上限 | 日亏触发停机 | OPEN |
| R2.3 连亏停摆 | 连续 N 笔亏损强制暂停 | OPEN |
| R2.4 熔断 | 账户级熔断条件 | OPEN |

### X. Execution（执行）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| X1 下单通道 | 券商/Broker API | OPEN |
| X2 滑点容忍 | 最大接受滑点，超出放弃 | OPEN |
| X3 部分成交 | 部分成交怎么办 | OPEN |
| X4 重试策略 | 下单失败重试几次 | OPEN |

### F. Failure Handling（异常处理）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| F1 数据缺失 | 行情中断 → 不开仓 / 平仓 | OPEN |
| F2 信号冲突 | 多信号矛盾 → 不开仓 | OPEN |
| F3 程序异常 | 异常 → 平仓 + 停机 + 人工接管 | OPEN |
| F4 Kill Switch | 一键熔断入口 | OPEN |

### G. Governance（治理段）

| 字段 | 必须回答 | 现状 |
|---|---|---|
| G1 版本 | 契约版本号 + 冻结声明 | DRAFT |
| G2 Evidence 链 | 每字段引用 RC-ID + Evidence Status | OPEN |
| G3 Decision Log | 每笔交易记录（信号→计划→执行→结果） | OPEN |
| G4 变更通道 | 只允许 Erratum 记录式变更，禁静默改 | OPEN |

---

## 4. 用本契约审查现状：我们现在有没有资格开始自动交易？

**答案：没有。** 这是本契约的第一个真实用途。

| 大段 | 现状 | 硬事实依据 |
|---|---|---|
| Market | OPEN | 历史数据在 `mt5_raw/`，实时接口未验证 |
| Regime | PARTIAL | 观察层有 Risk State / AIP，未接决策 |
| Setup | **OPEN** | H2-A 3 Archetype 已 FAIL（permutation pct 40.7%，A=202/210 无区分） |
| Entry | PARTIAL | 黄金 E1/E4 入场实证 VALIDATED（+$2389.3 / n=46），但属行为分类非自动规则 |
| Stop | **OPEN** | ATR×3 → PF1.52 是 CLAIM，找不到来源，证据断链 |
| Exit | **OPEN** | 最大泄漏点：exit capture −0.697、giveback 5473 ≫ pnl 43.89 |
| Position Size | PARTIAL | 风险预算公式已有 |
| Risk Limit | OPEN | 自动轨道无账户级熔断 |
| Execution | OPEN | 无 MT5 自动下单代码（只有 `mt5_export.py` 导出历史） |
| Failure Handling | OPEN | 无 |

**结论**：没有任何一个完整策略能填满本契约。这正是契约的价值——它是一份**准入门槛清单**，不是授权书。当未来某个策略（如 Exit 引擎的产出）逐字段填满并通过 REVIEW，它才自动获得 Backtest 资格。

---

## 5. 与现有资产的关系（不重复建设）

| 已有资产 | 与本契约关系 |
|---|---|
| `Strategy_Research_Contract_v0.1` | 研究语言，本契约的证据来源（G2 引用其 RC-ID） |
| `trading_constitution.py` v1.2 | 人工 A 股下单 gate，不替代 |
| `risk_governance_v2.0` | 账户级风险治理框架可复用（R2 段可继承其 Crisis/Recovery 逻辑） |
| `XL_Trading_System_Gap_Analysis_v1.0` | 13 层闭环审计，本契约的 Market→Failure 顺序与其一致 |

---

## 6. 本契约的下一步（非代码）

1. 定目标资产：第一份契约的品种（XAUUSD M5？）。
2. 逐字段审查：从 Gap Analysis 确认哪个字段已有可复用结论。
3. 等待一个完整策略通过 Research Gate 后，用它逐字段回填。

**冻结纪律**：本契约 v1.0 结构冻结前，不允许新增字段、不允许为填满而弱化定义。
