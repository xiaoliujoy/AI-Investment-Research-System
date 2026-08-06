# Phase 2.0 Risk Governance Layer（风险治理层）设计文档 v1.0

> 来源：用户在 Phase 1.9B/1.9C 之后提案（2026-08-04）。
> 核心判断（用户，可信度 85%）：**1.9C 把 Risk Budget 系统的核心风险从"规则问题"定位到了"信号质量问题"。**
> 因此下一步不是继续扩大回测，而是**升级核心决策层 = 风险治理系统**，而非堆选股模型。

---

## 一、为什么是"治理层"而不是"策略层"

1.9B 回答：规则可能有效（Sharpe/Calmar/MaxDD 同步改善）。
1.9C 回答：规则为什么有效（尾部风险被砍）、在哪里可能失败（信号过敏→过度去风险→全周期 Calmar 跑输固定 60/40）。
结论：规则成立，**命门在信号的选择性**。所以系统价值来自"风险管理与决策纪律"，不是来自某个收益 alpha。

Phase 2.0 把研究客体从"交易策略"升级为"个人 CIO 的风险治理系统"。

---

## 二、组件清单

| 组件 | 状态 | 说明 |
|---|---|---|
| Risk Budget Engine 2.0 | 新增(`risk_governance.py`) | 在 1.9B 连续预算之上加状态机治理 |
| Crisis Protocol | 已有(1.9B, score<30→股20%) | 保持不变 |
| Recovery Protocol | 新增(本层) | Crisis 的镜像：渐进恢复 |
| Crisis Aging | 新增(本层) | 危机持续天数追踪与强制复核 |
| Opportunity Cost Monitor | 新增(本层) | 低仓但广度恢复 → 标记防御错误 |
| Failure Log | 升级(`build_failure_log.py`) | 5 类错误分类（结果错误，滞后） |
| Decision Conflict Log | 新增(观测字段 `decision_conflict_type`) | 依据不一致（症状，提前） |
| Decision Quality Dashboard | 新增(`decision_quality_dashboard.py`) | Checkpoint C 四指标 |

---

## 三、Risk Budget Engine 2.0（状态机）

```
risk_score
   ↓
score_to_budget()  →  基础暴露(连续, 1.9B)
   ↓
[Governance Layer]
   ├─ Crisis Aging      : 危机持续第30天提示复核 / 第90天强制回答
   ├─ Recovery Protocol : score>=55 且广度恢复 → 渐进 +10% 权益/次(镜像)
   └─ Opportunity Cost  : 权益<=30% 且广度恢复 → 标记"防御可能错误"
   ↓
动态风险暴露 + 治理告警
```

工程判断（已落地，用户可推翻）：
- **恢复为渐进式 step ramp（+10% 权益/次）**，不做硬反转，避免熊市反弹陷阱（whipsaw）。
- **Opportunity Cost 用广度(market_daily 的 up/down_count 占比)作 coincident sanity-check**，
  不是领先信号——广度与价格同为滞后/同步，组合二者**不产生领先性**。
  真正的恢复领先性只能来自真实 Risk Temperature 的修复（2026-12-31 前无法测试）。
- 阈值（30/90天、55分、60%广度、+10%步进）均为**文档默认值，未用历史拟合**。冻结期内不调参。

---

## 四、Failure Log 5 类分类

| failure_type | 含义 | 案例 |
|---|---|---|
| false_positive | 误降仓（狼来了） | 触发 Crisis 但市场随后恢复 |
| false_negative | 该降未降 | 重大下跌前未提前降风险 |
| recovery_failure | 恢复太慢 | 危机解除后久未恢复正常风险 |
| asset_correlation_failure | 防御资产失效 | 股债双杀、黄金同跌 |
| signal_drift | 模型失效 | 信号预测力漂移/转负 |

系统级发现（来自 1.9C）已入库为 `false_positive`：代理分全周期触发 Crisis 1039 天，印证"信号选择性"是命门。

---

## 四-B、Decision Conflict Log（与 Failure Log 的区别）

用户 2026-08-04 末提议：现有 Failure Log 记录"结果错误"（病情，滞后），
但还需要记录"决策依据之间不一致"（症状，提前）。二者不同：

| 类型 | 记录什么 | 例子 | 价值 |
|---|---|---|---|
| Failure Log | 结果错误 | 降仓后市场涨 30% | 事后问责 |
| Conflict Log | 依据不一致 | 风险高但广度强 | 提前发现 |

Conflict 往往早于 Failure，类似医学"症状出现即记录，不等恶化"。
实现方式（已在 2.0-A 落地，observation-only）：`cio_decision_history` 增加观测字段
`decision_conflict_type`，由 `risk_governance.decision_conflict_type()` 判定，取值：

- `risk_vs_breadth`：防御信号 vs 广度强势（过度保护风险）/ 扩张信号 vs 广度弱势（冒进风险）
- `risk_vs_trend`：信号与趋势（stage）背离
- `signal_vs_market`：其他信号-市场背离

首条真实记录（2026-08-04）即命中 `risk_vs_breadth`：score=45（防御）但 breadth=0.672（67% 个股上涨）。
这正是"系统认知冲突事件"——优秀系统的进化不来自预测正确的数据，而来自判断分歧在哪里、为何产生。

Conflict 与 Failure 的关联（Checkpoint C 后回看）：
- **有价值冲突**：risk 高但后来真跌 → Risk 领先，保留。
- **无价值冲突**：risk 高市场续涨 → 过度防御，对应 Failure Log 的 false_positive。

---

## 五、Checkpoint C（2026-12-31）四指标

| 指标 | 公式 | 目标 |
|---|---|---|
| Crisis Precision | 成功Crisis / 全部Crisis | > 70% |
| Miss Rate | 重大下跌前未降风险的比例 | < 20% |
| Recovery Speed | 危机解除→恢复正常风险天数 | < 60 天 |
| Decision Conflict Rate | 冲突决策 / 全部决策 | < 25%（暂定，验收前钉死） |

**分母定义须在验收前钉死（防游戏化）**：
- Crisis 事件 = 未来 60 日出现 >=20% 回撤的窗口起点
- 成功 Crisis = 触发后该窗口确实发生 >=20% 回撤
- Miss = 发生 >=20% 回撤但前 20 日未触发 Crisis

现状：真实 decision history 仅 1 条，四指标 `insufficient_data`，框架已就绪待累积。

---

## 六、冻结纪律对齐

- 不碰 Layer1 评分模型、不加新数据源、不接全球资产、不扩日报。
- 仅消费已有：regime_history.risk_score + market_daily 广度。
- 未来 5 个月（至 Checkpoint C）**只观察、不优化**：三指标与 Failure Log 随真实决策累积自动填充。
- 验收全过（三指标达标 + 真实信号长周期成立）后，才进入 Phase 2.0 之后的全球资产扩展。

---

## 附录 A、系统版本标签：AI Investment Research OS v2.0-alpha

用户在 2026-08-04 末将本里程碑标记为 **Phase 2.0 的真正起点**，并建议冻结版本标签：

| 模块 | 状态 |
|---|---|
| 数据层 | 稳定 |
| Regime Engine | 运行 |
| Risk Budget | 验证中 |
| Risk Governance | 上线 |
| Failure Log | 运行 |
| Decision History | 积累中 |

**目标不是优化，而是积累第一批"系统自我认知数据"**（Decision Trace）。
Phase 2.0-A 让系统从"产生判断"进入"记录自己如何判断、何时可能犯错"，
是架构跃迁：从"产生判断的系统"→"记录自己判断的系统"。

---

## 七、对用户三个阈值的工程保留意见

1. **Crisis Precision > 70% 对基数敏感**：危机是稀有事件，若定义过宽易"从不触发→Precision 无意义"。必须先用第五节分母定义钉死"什么是 Crisis 事件"。
2. **Miss Rate < 20% 依赖"重大下跌"的精确定义**：20% 回撤 vs 10% 修正，结论差异巨大。
3. **Recovery Speed < 60 天**与 Crisis Aging 第90天强制复核存在张力：若第90天才强制恢复，Recovery Speed 天然偏长。建议把"渐进恢复"与"强制复核"解耦——恢复走渐进，复核走告警，不互相阻塞。

以上三点不构成否定，而是把阈值从"目标"变成"可度量、防游戏化"的工程口径。
