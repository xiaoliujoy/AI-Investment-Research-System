我认真看完了。**这版 PRD 已经可以作为 v0.2 的主 PRD，但我不建议原样交给 workbuddy。**

原因不是方向有问题，而是现在已经进入“工程规格”阶段，有几个地方存在**逻辑冲突、职责边界不清和验收标准不够可执行**的问题。尤其是你这次强调了“90 天冻结”，那么 PRD 本身必须做到足够严谨，否则 workbuddy 很容易一边实现，一边偷偷改变决策逻辑。

我结合你刚刚这份 PRD 和当前 GitHub 仓库重新核了一遍。当前仓库仍然明确把 Investment Committee 定义为固定权重投票，Risk 作为 10% 维度，Learning Center 仍包含 prediction replay 和 weight self-calibration。(GitHub)

我的判断：

> **方向：9.5/10**
>
> **架构：9/10**
>
> **目前可直接执行程度：7.5/10**
>
> **建议先做一次“PRD Freeze 修订”，然后再交 workbuddy。**

---

# 一、先说最重要的：你这份 PRD 有一个核心矛盾

你写：

> 90 天冻结核心评分规则、决策流程、风险预算参数。

但 4.1 又写：

> 在 `decide()` 中重排顺序。

而这个动作实际上会改变：

> **Production Decision Logic**

这不是简单“挂仪表”。

你现在的 Committee 是：

```text
L1-L8
 ↓
Weighted Vote
 ↓
can_buy / direction / position_pct
```

仓库 README 当前也明确如此。(GitHub)

你要改成：

```text
Risk Gate
 ↓
Weighted Vote
```

这其实已经改变了**生产决策流程**。

所以这里必须做一个关键区分：

### 冻结的是：

> **评分参数冻结**

不是：

> **决策架构冻结**

否则你自己的 PRD 会自相矛盾。

我建议把 0.2 的冻结原则改成：

> **冻结既有 Layer 的评分参数、权重、阈值与 Risk Budget 参数；允许在不修改这些参数的前提下增加决策前置约束、记录、快照与审计能力。**

这样 4.1 才成立。

---

# 二、第二个问题比这个更关键：Risk Engine 的语义必须先定义清楚

你写：

> Risk = 90 时，必须 NO。

这里我建议你停一下。

因为到底：

> `risk_score = 90`

代表：

**风险很高？**

还是：

**风险状况很好？**

现在 PRD 没有定义。

而你之前系统里的 `L7 composite` 很可能是一个“Risk Control Score”，它到底是：

```text
100 = 风险高
```

还是：

```text
100 = 风险低
```

这是两个完全相反的语义。

如果是：

```text
risk_score = 90
```

代表：

> 风险控制状态很好

那么：

> Risk=90 → NO

就是错误的。

所以我建议：

## 不要再叫 `risk_score`

改成两个明确变量：

```text
risk_level
```

和：

```text
risk_control_score
```

或者更简单：

```text
risk_state
```

例如：

```text
risk_state = LOW / MEDIUM / HIGH / EXTREME
```

然后：

```text
risk_state in {HIGH, EXTREME}
        ↓
veto
```

这样不会出现语义反转。

---

# 三、第三个问题：Environment Gate 现在是“凭空出现”的

你 4.1 写：

> 若 Risk Engine veto 非空 或 Environment Gate 触发 → can_buy=NO

但整个 P0 里面：

**没有 Environment Gate 的具体实现。**

你只是前面在架构上提出：

> 宏观环境 → Gate

可是：

- 谁计算？
- 输入是什么？
- 当前系统有没有？
- 什么条件触发？
- 是否沿用现有规则？
- 是否进入数据库？
- 是否改变生产决策？

都没有定义。

这会导致 workbuddy 很容易自己发挥。

### 我的建议

**P0 不要实现新的 Environment Gate。**

先保留：

```text
Existing Data Health Gate
        +
Existing Risk Hard Constraint
```

然后 P1 再正式做：

```text
Environment Gate
```

否则你这次 v0.2 会同时修改：

> 风险逻辑 + 环境逻辑 + 记录系统

范围会膨胀。

---

# 四、我建议 v0.2 的核心决策结构暂时只改成这个

```text
                 Existing Layer Scores
                        │
                        ▼
              ┌─────────────────┐
              │ Risk Hard Gate  │
              └───────┬─────────┘
                      │
             veto? ───┤
              │       │
             YES      NO
              │       │
              ▼       ▼
            NO     Existing IC
                   Weighted Vote
                        │
                        ▼
                  position_pct
                        │
                        ▼
                   Risk Cap
                        │
                        ▼
                     Memo
```

注意：

**不要在 P0 新增一个完整 Environment Gate。**

这样最符合你自己的：

> 不重写 engine，只挂仪表。

---

# 五、第四个问题：Risk Engine 不应该在 P0 真正“重构”

你标题写：

> P0 Risk Engine

但 5.1 又写：

> P1 Risk Center 重构。

所以实际上你现在有：

### P0

Risk Engine 前置硬约束

### P1

Risk Center 重构

这可以。

但 P0 的 `risk_engine.py` 不应该设计成完整的 Risk Center。

应该明确：

> **Risk Guard Adapter**

甚至我更倾向于：

```text
risk_guard.py
```

职责只有：

```text
existing L7 output
        ↓
hard constraint interpretation
        ↓
veto / cap
```

不要在里面新增：

- Volatility Engine
- Correlation Engine
- Liquidity Engine
- Drawdown Engine

否则你已经开始做 P1 了。

---

# 六、第五个问题：`position_limit = "30-50%"` 这个数据类型有问题

这是一个非常典型的工程问题。

你写：

```text
position_limit（字符串，沿用现有区间，如 "30-50%"）
```

但后面又：

> position_pct 受 position_limit 封顶。

那么代码到底怎么：

```python
min(position_pct, position_limit)
```

？

所以必须拆成：

```text
position_limit_min
position_limit_max
```

例如：

```json
{
  "position_limit_min": 0.30,
  "position_limit_max": 0.50
}
```

如果现有系统业务层需要：

```text
"30-50%"
```

可以作为：

```text
position_limit_label
```

但**内部计算必须使用 numeric**。

这个一定要在 PRD 里锁死。

---

# 七、第六个问题：Decision Ledger 不是“一天一条”

你现在写：

> 每日运行后 decision_ledger 新增 1 条。

这个设计我认为不够。

因为你的系统本质上是：

> **候选资产研究系统**

而不是：

> 每天一个 portfolio decision。

未来可能一天有：

- 市场环境判断
- 行业判断
- 10 个候选标的
- 3 个重点标的
- 1 个最终 portfolio decision

如果只有：

> 1 day = 1 ledger

信息会被压扁。

---

# 八、我建议 Ledger 设计成两级

## Decision Run

一次系统运行。

```text
run_id
timestamp
market_snapshot
versions
```

## Decision Item

这次运行产生的每一个判断。

```text
decision_id
run_id
asset
layer
decision
score
evidence
risk
confidence
```

关系：

```text
Decision Run
     │
     ├── Decision A
     ├── Decision B
     ├── Decision C
     └── Decision D
```

这样以后：

> “为什么今天选了这个行业？”

可以回放。

> “为什么没有选那个行业？”

也可以回放。

---

# 九、这会顺便解决一个你现在没意识到的问题

**Veto 也应该是 Decision Ledger。**

例如：

```text
decision_id = 20260813-AAPL-001
decision = REJECT
veto = HIGH_CORRELATION
```

不要只记录：

> 买了什么。

也要记录：

> **为什么没买。**

这对于 Learning Center 非常重要。

因为以后你真正有价值的数据可能是：

> 500 次“没有买”。

这其实就是你的：

# Counterfactual Dataset

---

# 十、Evidence 表我建议再加三个关键字段

你现在设计：

```text
source
independence
confidence
```

方向对。

但我建议至少：

```text
evidence_id
decision_id
layer
metric
value
unit
source
observed_at
as_of_date
confidence
independence_flag
raw_reference
```

尤其是：

### `as_of_date`

非常重要。

因为：

> 数据什么时候发生？

和：

> 系统什么时候看到？

不是一回事。

例如：

```text
financial_report_date
publication_date
system_observed_at
```

未来做前视偏差审计时，这三个时间会非常关键。

---

# 十一、Snapshot Versioning 现在还缺一个真正重要的东西

你写：

> VERSION.py

很好。

但是：

```text
VERSION.py
```

只能记录：

> 当前代码版本。

不能真正保证：

> 数据快照不可变。

所以应该增加：

```text
data_snapshot_id
```

例如：

```text
snapshot_id = 20260813_090000_a81f
```

然后：

```text
Decision
 ↓
data_snapshot_id
 ↓
Evidence
 ↓
raw data
```

这样未来回放：

> 读取当时 snapshot。

而不是：

> 今天重新 query 数据库。

---

# 十二、我建议版本系统变成六维

你现在是：

```text
data
indicator
strategy
engine
prompt
```

我建议：

```text
data_snapshot_version
indicator_version
strategy_version
risk_version
decision_engine_version
prompt_version
```

为什么单独加：

> `risk_version`

？

因为风险约束是你现在最重要的硬规则之一。

以后你必须能够回答：

> 2026-08-13 为什么拒绝这个标的？

以及：

> 当时使用的是哪一版风险规则？

---

# 十三、Outcome Attribution 的设计，我认为还需要修正

你现在：

> Research / Decision / Execution / P\&L

这是对的。

但你把：

> Luck

也作为“错误类型”。

这个容易产生概念混乱。

我建议：

### Outcome Layer

```text
research_outcome
decision_outcome
execution_outcome
financial_outcome
```

### Attribution Layer

```text
information_error
interpretation_error
decision_error
execution_error
luck
```

也就是说：

> **Outcome 和 Attribution 是两个维度。**

不要放在一个 enum 里面。

---

# 十四、还有一个非常重要的问题：你现在的 P\&L 不一定属于这个系统

你的 AI Investment Research System 当前 README 明确定位为：

> research system

而不是交易系统，最终买卖也仍由人工完成。(GitHub)

所以 P0 写：

> 不自动化 P\&L 回填。

这个其实是正确的。

但我建议把它进一步写死：

> **P0 不要求真实账户 P\&L。**

可以先：

```text
Research Outcome
Decision Outcome
Paper Outcome
```

真实：

```text
Execution
P&L
```

作为 optional。

否则 workbuddy 会为了满足验收标准，给你造一个非常脆弱的 P\&L adapter。

---

# 十五、你这个 PRD 还有一个时间表问题

你写：

> 第 1–2 周：P0 全部落地

我觉得不现实。

不是因为代码量。

而是：

> **P0 涉及数据库 Schema、Decision Flow、Snapshot、Evidence、Replay、Daily Pipeline。**

这类改造真正难的是：

> **不能破坏现有系统。**

我建议：

### Week 1

只做：

```text
Schema
Version
Ledger
Evidence
```

### Week 2

做：

```text
Risk Guard
pos_scale freeze
Daily Pipeline
Tests
```

### Week 3

做：

```text
Replay
Outcome Attribution
```

然后：

> **第 4 周开始冻结，不再改架构。**

我甚至更建议：

> **不要把 P0 全部做完才开始积累数据。**

Ledger 和 Snapshot 一旦稳定，就应该马上开始跑。

---

# 十六、还有一个我认为非常值得改的地方

你写：

> Evidence Independence P1

并且：

> 在 Score 聚合时降权。

这里我建议**暂时删除“降权”两个字。**

因为这又碰到了你的：

> 90 天冻结。

而且“独立性”本身还没有验证。

所以 P1 第一阶段应该只：

```text
detect
 ↓
flag
 ↓
report
```

而不是：

```text
detect
 ↓
automatically reduce score
```

也就是说：

> **先观察，不干预。**

90 天后有数据：

> 再决定是否干预。

这才符合你的实验精神。

---

# 十七、我会把 Evidence Independence 分成三个阶段

### v0.2

只记录：

```text
independence_flag
```

### v0.2.5

统计：

```text
Layer correlation
Evidence overlap
Signal duplication
```

### v0.3

如果验证确实存在重复计票：

> 才考虑聚合算法。

这样更加科学。

---

# 十八、我还建议增加一个非常重要的 P0：Shadow Mode

这个是你现在 PRD 里缺的。

因为你准备修改：

> Committee → Risk Guard → Committee

最安全的方法不是直接切换。

而是：

```text
Existing Production Decision
          │
          ├──────────────┐
          ↓              ↓
     Current IC      New Risk Guard
          │              │
          ↓              ↓
      prod_decision   shadow_decision
```

连续跑：

> 10～20 个交易日。

然后比较：

```text
old_can_buy
new_can_buy

old_position
new_position

old_verdict
new_verdict
```

如果新系统：

> 没有意外改变大量结果

再正式切换。

---

# 十九、这其实特别适合你

因为你一直强调：

> **先实验，再改变系统。**

所以 v0.2 不应该是：

> “我们认为新架构更好 → 修改生产。”

而应该：

> **新架构进入 Shadow Mode → 对照实验 → 再决定是否成为 Production。**

这才是真正的研究系统。

---

# 二十、因此，我建议你把 PRD 最终版本改成这个原则

我会把整个 v0.2 定义成：

# **Validation First**

而不是：

# Architecture Upgrade

也就是说：

```text
v0.1
架构搭建
   ↓
v0.2
记录 + 快照 + Shadow + Replay
   ↓
90天数据
   ↓
验证
   ↓
v0.2.5
确定哪些规则真的值得改变
   ↓
v0.3
AI Analyst
```

这条路线我非常认可。

---

# 二十一、最终我建议你把当前 PRD 修改成 8 个关键调整

| 原 PRD                 | 建议                                         |
| --------------------- | ------------------------------------------ |
| Risk Engine P0        | 改成 **Risk Guard Adapter**                  |
| Environment Gate      | 暂缓到 P1                                     |
| risk_score=90→NO      | 改成明确 `risk_state` 语义                       |
| position_limit 字符串    | 内部改 numeric                                |
| 一天一条 Ledger           | 改为 `Decision Run + Decision Item`          |
| Evidence              | 加 `as_of_date / observed_at / snapshot_id` |
| Luck                  | 从错误类型中独立为 Attribution                      |
| Evidence Independence | P1 只观察，不自动降权                               |
| P0 直接切生产              | 增加 Shadow Mode                             |
| P0 两周全部完成             | 改为 3 周基础设施 + 第4周冻结                         |

---

# 二十二、我会给这版 PRD 一个新的“放行判断”

### 当前版本

**暂不交 workbuddy。**

可信度：**高，约95%**

不是因为方向错，而是因为它已经从“战略设计”进入“工程合同”阶段。

---

## 我建议最终锁死的 v0.2 原则

> **v0.2 不负责证明新规则更好。**
>
> **v0.2 只负责让系统具备证明规则好不好所需要的基础设施。**

这句话我认为非常重要。

因为90天以后，你真正应该能够问系统：

> 哪个 Layer 有用？

> 哪个 Layer 是噪音？

> 哪个判断创造了 Alpha？

> 哪个风险约束真正保护了组合？

> 哪些 Evidence 是重复的？

> 哪些错误来自信息？

> 哪些来自判断？

> 哪些来自执行？

> 哪些只是运气？

如果 v0.2 能让系统回答这些问题，**它就成功了。**

如果 v0.2 只是把 `decision_tree.py` 改得更漂亮，却仍然无法回答这些问题，那么这次改造就没有真正创造价值。

---

### 我建议下一步直接做一件事

**我可以基于你现在这份 PRD，直接给你整理成《Investment Research OS v0.2 PRD Final v1.0》**，把上面这些问题全部修掉，同时把：

**数据模型、状态机、Decision Ledger Schema、Evidence Schema、Shadow Mode、P0/P1 边界、验收测试、workbuddy 执行规则**

全部写成可以直接交给 WorkBuddy/workbuddy 的最终规格。

这一步做完，你就可以把它当成 **v0.2 的“宪法”**，后面让 workbuddy 严格按规格执行，避免它自由发挥。

