# Investment Research OS v0.2 PRD · Final v1.0

> **副标题**：Validation First —— 让系统具备"证明规则好不好"所需的基础设施，而非证明新规则更好。
> **状态**：评审通过后的最终执行规格（已冻结微调，可交 workbuddy 执行）。
> **定位**：v0.2 不负责证明新规则更好；v0.2 只负责让系统具备证明规则好不好所需的基础设施。

---

## workbuddy 执行总指令（Master Execution Prompt）

```text
你现在负责执行 Investment Research OS v0.2 PRD Final v1.0。

这是一个“Validation First”改造任务。

你的首要目标不是优化系统，而是为未来90天的规则验证建立可靠基础设施。

==================================================
一、最高优先级原则
==================================================

1. 行为零变化是最高级别约束。
2. 禁止修改：_DEBATE_LAYERS、Layer 权重、Layer 评分公式、Layer 阈值、Risk Budget 参数、L7 composite 计算方式、指标定义。
3. Risk Guard 只是 Adapter，不是新的 Risk Engine。
4. P0 不新增 Environment Gate。
5. P0 不新增 AI Agent。
6. P0 不进行自动权重调整。
7. pos_scale 不得自动影响生产 position_pct。
8. Shadow Mode 下，新系统绝对不能接管生产裁决。
9. Evidence Independence 在 P1 只检测、标记、报告，不允许降权。
10. 不允许为了通过测试而制造数据或修改历史数据。

==================================================
二、执行前必须先做
==================================================

不要立即修改代码。第一阶段必须进行 Repository Audit。

检查：
- backend/database/models.py
- backend/decision_tree.py
- backend/committee/investment_committee.py
- backend/brain/cio_agent.py
- backend/learning_center.py
- backend/run_daily.py
- backend/data_health.py
- 所有现有测试
- 当前数据库 schema
- 当前 brain_report / decision_tree 输出结构
- 当前 learning_center prediction_feedback / pos_scale
- 当前 L7 composite 与 hard_no 实现

输出：
1. 当前真实架构
2. PRD 与代码的差异
3. 每个改造点对应的真实代码位置
4. 风险点
5. 预计修改文件
6. 不需要修改的文件

在 Audit 完成之前不要进行大规模修改。

==================================================
三、建立 Golden Master
==================================================

改造前建立行为基线。

选择至少30个历史样本，尽量覆盖：
- YES / NO / 不同 position_pct / L7 不同 composite / hard_no / 正常样本 / 极端风险样本

保存：can_buy / direction / position_pct / verdict / risk composite / debate / layer outputs
作为 Golden Master。所有后续修改必须通过 Regression Test。

==================================================
四、实施顺序
==================================================

Phase 1  Schema / VERSION / Snapshot Manifest / Decision Run / Decision Item / Evidence / Decision Version
Phase 2  Risk Guard / pos_scale freeze / Shadow Mode
Phase 3  Ledger pipeline / CIO hook / run_daily integration
Phase 4  Replay / Outcome Attribution
Phase 5  Full regression / Golden Master comparison

不要一次性修改全部模块。每个 Phase 完成后：运行测试 → 检查 git diff → 检查冻结项 → 输出结果 → 再进入下一阶段。

==================================================
五、Risk Guard 特别规则
==================================================

Risk Guard 只能读取现有 L7 输出。映射：<30 LOW / 30-50 MEDIUM / 50-70 HIGH / >=70 EXTREME。
只有 EXTREME → veto=True。除此之外不得产生新的 veto。
不得增加 volatility / correlation / liquidity / drawdown（属 P1）。
position_limit 必须同时保存 position_limit_min / position_limit_max / position_limit_label。

==================================================
六、Shadow Mode
==================================================

Shadow Mode 下：Old IC → Production；Risk Guard + New Flow → Shadow。
Shadow 不得改变 production verdict / position / memo。所有差异必须写入 shadow_run。

==================================================
七、Ledger
==================================================

Decision Run ≠ Decision Item。一个 Run 可含多个 Item。
每个 Item 必须可追溯：Run → Item → Evidence → Version → Outcome。
建议支持 parent_item_id / item_type / decision_basis。否决必须成为 Item。

==================================================
八、Evidence
==================================================

Evidence 必须保存：source / metric / value / unit / observed_at / as_of_date / confidence / raw_reference。
P0 不计算 independence，只保留 independence_flag。

==================================================
九、Replay
==================================================

Replay 禁止实时重新计算历史判断。必须优先使用 Ledger snapshot / Evidence snapshot / Version metadata。
禁止使用当前数据库最新数据重新解释历史判断。

==================================================
十、完成标准
==================================================

1. Golden Master 全绿
2. 非 EXTREME 样本生产行为零变化
3. EXTREME 样本 risk_state=EXTREME
4. veto 可追溯
5. 每次运行产生 decision_run
6. 每个运行至少 1 个 decision_item
7. Evidence 可追溯
8. Version 六维齐全
9. Snapshot 可追溯
10. Shadow Mode 可比较 old/new
11. pos_scale 不自动改变生产仓位
12. Replay 不产生前视偏差
13. Outcome Attribution 可回填
14. 所有新增测试通过
15. Git diff 中没有冻结项修改

若任何冻结项发生变化：立即停止，不要自行修复，报告 FROZEN_RULE_VIOLATION（文件/行号/修改内容/原因）。

==================================================
十一、工作方式
==================================================

禁止自由发挥 / 顺手重构 / 优化旧代码 / 修改函数签名 / 为“更优雅”改变现有逻辑。
优先新增 Adapter / Hook / Schema / Test。每完成一个阶段，先报告再继续。

最终输出：修改文件清单 / 新增文件清单 / Schema / 测试结果 / Golden Master 结果 / Shadow Mode 状态 / 冻结项检查结果 / 已知风险 / 下一阶段建议。

现在开始 Phase 0：Repository Audit。不要修改代码。
```

---

## 0. 与 Draft 的关键差异（变更对比）

| # | Draft 问题 | Final 修正 |
|---|---|---|
| 1 | "90天冻结"与"4.1 重排 decide()"自相矛盾 | 明确定义**冻结评分参数、不冻结决策架构**；4.1 仅提取现有 `comp>=70→NO` 为前置 gate，**行为零变化** |
| 2 | `risk_score=90→NO` 语义未定义 | 废除 `risk_score`，改 `risk_state ∈ {LOW,MEDIUM,HIGH,EXTREME}`，显式映射到现有 L7 composite |
| 3 | Environment Gate 凭空出现、无实现 | **P0 不实现新 Environment Gate**；保留现有 Data Health Gate + 现有 Risk 硬约束；Environment Gate 推迟 P1 |
| 4 | Risk Engine 标题与 P1 Risk Center 重叠 | P0 改名 **`risk_guard.py`（Risk Guard Adapter）**，只解释现有 L7 输出为 veto/cap，不新增任何 Engine |
| 5 | `position_limit` 用字符串，无法封顶计算 | 内部拆 `position_limit_min/max`(numeric)，`position_limit_label` 仅展示 |
| 6 | Ledger "一天一条"压扁信息 | 改为两级：**Decision Run + Decision Item**；否决也入库（Counterfactual Dataset） |
| 7 | Evidence 缺时间维度 | 加 `as_of_date` / `observed_at` / `raw_reference` |
| 8 | 版本只五维，风险规则无版本 | 升六维，单独加 `risk_version` |
| 9 | Luck 混入错误类型 enum | Outcome（四层）与 Attribution（错误标志）拆为两个维度 |
| 10 | P0 要求真实 P&L | P0 **不要求真实账户 P&L**；financial_outcome 为 optional |
| 11 | Evidence Independence "在 Score 聚合时降权" | P1 只 **detect/flag/report**，不干预评分；v0.2.5 才统计，v0.3 才考虑聚合 |
| 12 | P0 直接切生产 | 新增 **Shadow Mode**：新旧并行 10–20 交易日对照后再接管 |
| 13 | 时间表 2 周不现实 | 改为 Week1 Schema/Version/Ledger/Evidence → Week2 Risk Guard/冻结/流水线/测试 → Week3 Replay/归因 → Week4 起冻结并积累 |

---

## 1. 冻结原则（PRD 的宪法条款，最高优先级）

### 1.1 冻结（禁止任何 P0/P1 改造项修改）
- 既有 Layer 的**评分参数**：权重（`_DEBATE_LAYERS`）、阈值、公式。
- **Risk Budget 参数**：仓位区间阈值（`<30→80-100%` 等）、L7 三维权重（市场0.45/行业0.30/个股0.25）。
- 指标定义（`stock_daily` 各字段语义、L7 composite 计算方式）。

### 1.2 允许（在不触碰 1.1 的前提下）
- 增加**决策前置约束**（Risk Guard 提取现有硬否决为 gate）。
- 增加**记录 / 快照 / 审计 / Shadow 对照**能力。
- 新增独立子模块，保持现有函数签名与返回值兼容。

### 1.3 违规判据（交付验收的硬红线）
> 本 PRD 任何 P0/P1 改造项，若导致**既有数据**上 memo 产出变化（除 Risk Guard 在 `risk_state=EXTREME` 下的既有否决外），视为违规，必须回滚。

### 1.4 Golden Master Regression（行为基线守护）
改造开始前，必须建立行为基线，所有后续修改通过回归测试：
1. 选取 **N≥30** 份历史 `brain_report.json`，覆盖：正常样本 / YES / NO / 不同 `position_pct` / L7 不同 composite 区间 / 至少若干 `hard_no` 样本 / 极端风险样本。
2. 用当前生产代码运行一次，将以下字段保存为 **immutable golden fixtures**：
   ```json
   { "sample_id":"...", "can_buy":"...", "direction":"...", "position_pct":"...",
     "verdict":"...", "risk_composite":"...", "debate":"...", "layers":"..." }
   ```
3. v0.2 改造完成后再次运行同一批输入，逐字段自动比较。
4. **允许变化**的字段仅限：`risk_state` / `veto` / `risk_guard` metadata / `ledger` / `evidence` / `version` metadata。
5. **生产裁决字段**（`can_buy` / `direction` / `position_pct` / `verdict`）必须保持一致。
6. **失败标准**：任何未在 PRD 明确允许范围内的变化 → `FAIL`（不是 warning），立即停手并报告 `FROZEN_RULE_VIOLATION`。

### 1.5 90 天只观察、不优化（系统级原则）
> **90 天不优化系统，只观察系统。**

明确**不做**：不调权 / 不改阈值 / 不追求命中率 / 不追求收益率 / 不训练 Agent / 不让 AI 自我修改。
只做：记录 / 冻结 / 执行 / 回放 / 归因 / 比较。

90 天后才问：哪个 Layer 有信息价值？哪个没有？哪个 Risk Guard 有价值？哪些 Evidence 重复？哪些判断只是运气？哪些错误来自执行？——这是从 Research Framework 走向 Investment Research OS 的真正分水岭。

---

## 2. 目标架构 v2（Validation First）

```
            Existing Layer Scores (L1..L8, 参数冻结)
                        │
                        ▼
              ┌──────────────────────┐
              │   Risk Hard Gate     │  ← risk_guard.py 提取现有 comp>=70→NO
              │  (前置硬约束, 非投票)  │     行为零变化；不新增任何否决条件
              └──────────┬───────────┘
                         │
                veto? ───┤
                 │       │
                YES      NO
                 │       │
                 ▼       ▼
               NO    Existing IC Weighted Vote (逻辑不变)
                         │
                         ▼
                   position_pct (受 Risk Cap 封顶)
                         │
                         ▼
                   CIO Memo ──→ 写入 Decision Run + Decision Items + Evidence
                         │
                         ▼
                   (Shadow Mode: 并行记录旧/新裁决对照)
                         │
                         ▼
                   Outcome Attribution (四层 + 错误标志, 人工/半自动回填)
                         │
                         ▼
                   Replay (读冻结快照, 无前视偏差)
```

**注意**：P0 **不新增 Environment Gate**。现有 `data_health.py` 的 5 点闸门与 IC 内既有 `hard_no`（L1 bearish / FLOW bearish / sentiment 退潮冰点）保持原样，仍属"Existing IC"内部逻辑，不在本 PRD 改动范围。

---

## 3. 五中心重定义（锁死 Layer ≠ Center）

| Center | 职责 | 关键模块 | 本 PRD 动作 |
|---|---|---|---|
| Data Center | 事实采集归一 | `daily_collect.py` `tech_fill.py` `data_health.py` | 不变 |
| Research Center | 证据生产 L1–L8 | `decision_tree.py` 各 layer | 仅加 evidence 钩子位 |
| Decision Center | 判断裁决 | `committee/investment_committee.py` `brain/cio_agent.py` | IC 逻辑不变；CIO 末尾写 Ledger |
| Risk Center | 约束 | 新增 `risk_guard.py`（P0 适配器）；P1 升级 Risk Center | P0 仅适配器 |
| Learning Center | 反馈归因 | `learning_center.py` + Ledger/Replay | 四层归因 + Veto Replay(P1) |

---

## 4. 数据模型（Schema）— P0 核心

> 规则：**只增表，不改现有表**。`backend/database/models.py` **新增 7 张表**（清单见 §12）。

### 4.1 `data_snapshot`（Snapshot Manifest，非完整数据拷贝）
```sql
CREATE TABLE data_snapshot (
    snapshot_id     TEXT PRIMARY KEY,   -- 20260813_090000_a81f
    captured_at     TEXT,              -- 采集完成时刻
    manifest        TEXT,              -- JSON: 各源表/日期范围/行数/源版本哈希
    created_at      REAL
);
```
- **P0 实现 Snapshot Manifest**：记录"当时系统看到的数据来源是什么"（source + date + hash），用于溯源与防前视偏差审计。
- **P0 不复制完整数据库**（避免工程复杂度暴涨）。Replay 必须优先读取 Ledger 中已冻结的 `evidence` / `evidence_snapshot`，而非今天数据库里的世界。
- **完整原始数据快照（immutable data artifact：market_daily / sector_daily / stock_daily ... 的 Parquet/JSON 冻结）属于 v0.2.5**，不在本 PRD 范围。

### 4.2 `decision_run`（一次系统运行）
```sql
CREATE TABLE decision_run (
    run_id          TEXT PRIMARY KEY,   -- 20260813_0930_a1b2
    trade_date      TEXT,
    triggered_by    TEXT,              -- scheduled / manual
    market_snapshot TEXT,              -- JSON: regime / width / emotion / 主要指数
    versions_json   TEXT,              -- 六维版本（见 §5）
    snapshot_id     TEXT,              -- 关联 data_snapshot
    shadow_mode     INTEGER DEFAULT 1, -- 1=shadow 并行记录, 0=生产接管
    created_at      REAL
);
```

### 4.3 `decision_item`（本次运行产生的每一个判断，含否决）
```sql
CREATE TABLE decision_item (
    item_id             TEXT PRIMARY KEY,  -- run_id + "_" + seq
    run_id              TEXT,
    parent_item_id      TEXT,             -- Decision Graph: 指向父判断(见 §4.3.1)
    item_type           TEXT,             -- MARKET / SECTOR / ASSET / RISK / IC / HUMAN
    asset               TEXT,     -- 板块/个股代码/NULL(市场级)
    layer               TEXT,     -- 产生该判断的层, 或 "IC"(最终裁决)
    decision            TEXT,     -- BUY_WATCH / CAUTION / REJECT / YES / NO ...
    decision_basis      TEXT,     -- SCORE / RISK_VETO / DATA_HEALTH / HUMAN_OVERRIDE
    direction           TEXT,     -- bullish / bearish / neutral
    score               REAL,
    evidence_ref        TEXT,     -- JSON array of evidence_id
    risk_state          TEXT,     -- LOW/MEDIUM/HIGH/EXTREME/NULL
    veto                TEXT,     -- NULL 或否决原因码(如 HIGH_CORRELATION)
    confidence          TEXT,     -- JSON: 各层置信度
    position_limit_min  REAL,     -- numeric, 如 0.30
    position_limit_max  REAL,     -- numeric, 如 0.50
    position_limit_label TEXT,    -- 展示用 "30-50%"
    invalidation        TEXT,     -- 证伪条件
    human_decision      TEXT,     -- 人工最终动作(用户回填, 可空)
    created_at          REAL
);
```
- **否决也是 Item**：`decision=REJECT` + `veto=原因码` 同样入库，构成 Counterfactual Dataset（"为什么没买"）。
- 一天可产生多条 Item（市场环境 / 行业 / 候选标的 / 最终 portfolio 裁决各一条）。
- **§4.3.1 Decision Graph**：`parent_item_id` + `item_type` 把判断组织成有向图 `Market → Sector → Asset → Risk → IC → Human`，未来可直接查询"某个最终决策由哪些研究判断组成"，这是回答"哪个 Layer 创造 Alpha"的基础数据结构。
- **`decision_basis`** 区分价值来源：
  - `SCORE → YES → 赚钱`
  - `SCORE → YES` / `RISK_VETO → NO` / 市场后来暴跌（Guard 正确）
  - `SCORE → YES` / `RISK_VETO → NO` / 市场后来暴涨（Guard 有误杀）
  - `System → YES` / `HUMAN_OVERRIDE → NO` / 后来暴跌（人错）
  四种对系统学习的意义完全不同，复盘必须可区分。

### 4.4 `evidence`（结构化证据）
```sql
CREATE TABLE evidence (
    evidence_id     TEXT PRIMARY KEY,   -- run_id + "_E" + seq
    item_id         TEXT,
    layer           TEXT,
    metric          TEXT,              -- 指标名, 如 "20D_capital_inflow"
    value           TEXT,              -- 指标值, 如 "+18.2B"
    unit            TEXT,              -- B / % / 天 ...
    source          TEXT,              -- 数据源, 如 "sector_mainline.json"
    observed_at     TEXT,              -- 系统何时读到
    as_of_date      TEXT,              -- 数据本身发生于何时(与前视偏差审计强相关)
    confidence      TEXT,              -- High / Medium / Low
    independence_flag INTEGER DEFAULT 1,-- 1=独立 0=疑似与其他层重复(P1 才填, P0 不计算)
    raw_reference   TEXT,              -- 源文件/行 指针
    created_at      REAL
);
```

### 4.5 `decision_version`（六维版本，按 run 记录）
```sql
CREATE TABLE decision_version (
    run_id              TEXT PRIMARY KEY,
    data_snapshot_version    TEXT,
    indicator_version        TEXT,
    strategy_version         TEXT,
    risk_version             TEXT,   -- 单独版本: 风险约束是硬规则, 必须可溯源
    decision_engine_version  TEXT,
    prompt_version           TEXT
);
```

### 4.6 `outcome_attribution`（四层 Outcome + 错误标志，两个维度分离）
```sql
CREATE TABLE outcome_attribution (
    id                  INTEGER PRIMARY KEY,
    item_id             TEXT,
    -- Outcome Layer (结果层, 互不排斥的四问)
    research_outcome    TEXT,   -- correct / incorrect / na
    decision_outcome    TEXT,   -- sound / flawed / na
    execution_outcome   TEXT,   -- compliant / violated / na
    financial_outcome   TEXT,   -- profit / loss / na  (P0 optional, 不强制真实账户)
    -- Attribution Layer (归因层, 可多选的布尔标志)
    information_error   INTEGER DEFAULT 0,
    interpretation_error INTEGER DEFAULT 0,
    decision_error      INTEGER DEFAULT 0,
    execution_error     INTEGER DEFAULT 0,
    luck                INTEGER DEFAULT 0,
    notes               TEXT
);
```
- **Luck 是独立布尔**，不混入 error enum；可与其他 error 并存或独立。
- P0 `financial_outcome` 不要求真实账户 P&L；可用 Research/Decision/Paper 结果，真实 Execution/P&L 为 optional 回填。

### 4.7 `shadow_run`（Shadow Mode 对照记录）
```sql
CREATE TABLE shadow_run (
    run_id          TEXT PRIMARY KEY,
    prod_can_buy    TEXT, prod_direction TEXT, prod_position TEXT,
    shadow_can_buy  TEXT, shadow_direction TEXT, shadow_position TEXT,
    shadow_veto     TEXT,
    diff            TEXT,   -- 如 "can_buy: YES->NO by RISK_GUARD"
    created_at      REAL
);
```

---

## 5. 版本系统（六维）

`backend/VERSION.py`：
```python
DATA_SNAPSHOT_VERSION     = "1.4"
INDICATOR_VERSION         = "1.2"
STRATEGY_VERSION          = "0.8"
RISK_VERSION              = "0.3"   # 风险约束单独版本(硬规则可溯源)
DECISION_ENGINE_VERSION  = "0.3"
PROMPT_VERSION            = "0.5"
```
每次 `run_daily.py` 把当前常量 + 生成的 `snapshot_id` 写入 `decision_version` 与 `decision_run`。未来任一规则修改 → 升对应版本号 → 回放按版本分组。

---

## 6. Risk Guard Adapter（P0 唯一的风险改造，行为零变化）

### 6.1 语义定义（必须显式，禁止歧义）
现有 L7 `composite`（0–100，**越高越危险**）映射为：
| composite | risk_state | 动作 |
|---|---|---|
| `< 30` | LOW | 无 |
| `30 – 50` | MEDIUM | 无 |
| `50 – 70` | HIGH | 不否决，但 Risk Cap 收紧（沿用现有区间） |
| `≥ 70` | EXTREME | **veto → NO**（与现有 `comp>=70→hard_no` 完全一致） |

### 6.2 `backend/risk_guard.py` 职责（仅适配器，不新增 Engine）
```
existing L7 output (composite, position string)
        ↓
risk_state 映射 (上表)
        ↓
veto?  (仅当 EXTREME, 即现有 comp>=70)
        ↓
输出: { risk_state, veto: bool, veto_reason, position_limit_min, position_limit_max, position_limit_label }
```
- **position_limit 内部 numeric**：由现有 position 字符串解析，如 `"30-50%"` → min=0.30, max=0.50, label="30-50%"。内部封顶一律用 numeric：`position_pct = min(ic_position_pct, position_limit_max)`。
- **不新增**：Volatility / Correlation / Liquidity / Drawdown Engine。这些属 P1 Risk Center。

### 6.3 行为零变化保证
`risk_guard` 在 `risk_state=EXTREME` 时的 `veto` 等价于现有 IC `hard_no`（comp>=70）。其余状态不改变任何现有裁决。单测必须断言：在既有 brain_report 样本上，新流水线产出的 `can_buy/direction/position_pct` 与旧 IC 完全一致（除 EXTREME 风险样本，其裁决本就是 NO）。

---

## 7. Shadow Mode（安全切换机制，P0 必做）

```
Existing Production IC  ──┐
                          ├─→ 比较 old_can_buy / new_can_buy / position / verdict
New Risk Guard + IC ─────┘        ↓
                        shadow_run 表记录 diff
```
- `decision_run.shadow_mode = 1` 期间：Risk Guard 与既有 IC 并行运行，**生产仍以既有 IC 为准**（即 `risk_guard` 只记录 `shadow_veto`/`shadow_can_buy`，不接管）。
- Shadow 只能 READ → CALCULATE → RECORD → COMPARE，绝不修改 production verdict / position / memo / IC 使用的库状态。
- 连续 **10–20 个交易日**后，对比 diff 分布：若新系统未意外改变大量结果（尤其非 EXTREME 样本），由人工（用户）将 `RISK_GUARD_ENABLED` 置 1，正式接管前置 gate。
- 在此之前，任何"Risk Guard 改变裁决"都必须能在 shadow_run 中追溯，绝不静默切换。

---

## 8. 改造范围与优先级（最终）

### P0（基础设施，不碰冻结项）
1. 数据库 Schema（§4 七张表）
2. `VERSION.py` 六维 + `decision_version` 落库
3. `decision_run` / `decision_item` / `evidence` 写入（CIO `produce()` 末尾钩子）
4. `data_snapshot` 采集与关联（Manifest 语义，P0）
5. `risk_guard.py` 适配器（行为零变化）
6. 冻结 `prediction_feedback().pos_scale` 对生产仓位的影响（仅记录+人审）
7. `run_daily.py` 插入 Ledger 步骤（单步失败不影响整体）
8. **Shadow Mode**（§7）

### P1（数据积累后，不碰冻结项）
9. Risk Center 重构（在 risk_guard 上扩展 Volatility/Correlation/Liquidity/Drawdown 输入）
10. Environment Gate 正式实现（P0 明确不做）
11. Veto Replay（Precision / Opportunity Cost / Asymmetry，基于 decision_item 中 REJECT 记录）
12. Process Score（information_quality / logic_consistency / risk_discipline / evidence_quality）
13. Evidence Independence **观察阶段**：detect / flag / report（**不降权**）
14. CIO LLM 边界锁定（代码注释 + 原则文档）
15. 文档 v2（architecture / design-principles / roadmap / README 对齐真实实现 + 冻结声明）

### P2（数据积累后，明确暂缓）
16. AI Analyst Agents（Macro/Sector/Company/Risk）
17. Research Hypothesis Engine
18. Automated Strategy Discovery

### 明确不做（冻结期禁止）
- 修改 `_DEBATE_LAYERS` 权重 / 任何评分公式阈值 / Risk Budget 参数
- 启用 `suggested_weights` 回灌生产 / 启用 `pos_scale` 自动缩放
- 新增 AI Agent 进决策主链路
- 重写现有 engine
- P0 阶段实现 Environment Gate

---

## 9. 执行时间表（务实版）

| 周次 | 范围 | 交付 |
|---|---|---|
| **Week 1** | Schema + VERSION + Ledger/Evidence/Version 写入 + data_snapshot(Manifest) | 数据库与记录能力就位，**即刻开始积累** |
| **Week 2** | risk_guard.py + pos_scale 冻结 + run_daily Ledger 步骤 + 单测(含行为零变化断言) | Risk Guard 进 Shadow；流水线产出 Ledger |
| **Week 3** | Replay 引擎(读冻结快照) + Outcome Attribution 回填(人工/半自动) | 回放可读历史快照，无前视偏差 |
| **Week 4 起** | Shadow 对照评估(10–20 交易日) → 稳定后 `RISK_GUARD_ENABLED=1`；此后**冻结架构不再改** | 进入 90 天数据积累期 |

> 关键：Ledger + Snapshot 一旦稳定（Week 1 末）就应立即开始每日积累，**不等 P0 全部做完**。

---

## 10. 验收测试（workbuddy 交付必须全绿）

### 10.1 Golden Master 回归（红线）
- 取 ≥30 份历史 `brain_report.json`（含 EXTREME 与非 EXTREME 样本），跑新流水线：
  - 非 EXTREME 样本：`can_buy / direction / position_pct` 与旧 IC 逐字段一致。
  - EXTREME 样本：旧 IC 本就 `NO`；新系统 `NO` + `risk_state=EXTREME` + `veto` 记录。
- 任一非 EXTREME 样本产出变化 → 交付判违规（`FAIL`）。

### 10.2 数据模型
- `decision_run` 每日 1 条；`decision_item` ≥1 条（含最终 IC 裁决 Item）；否决场景产生 `decision=REJECT` Item。
- `evidence` 对每日 Ledger 有 ≥1 条，且 `as_of_date` / `observed_at` 均非空。
- `decision_version` 六维齐全；`snapshot_id` 与 `data_snapshot` 可外键追溯。

### 10.3 Risk Guard
- `position_limit_min/max` 为 numeric；`min(position_pct, position_limit_max)` 正确封顶。
- `risk_state=EXTREME` → `veto=True` 且仅在此条件；其余状态 `veto=False` 且不改变裁决。

### 10.4 Shadow Mode
- `shadow_mode=1` 期间，生产裁决仍由旧 IC 决定；`shadow_run` 完整记录 old/new diff。
- 单测：构造 risk_guard 会否决但旧 IC 会 YES 的样本，断言生产输出仍为 YES（shadow 仅记录）。

### 10.5 冻结守护
- 单测扫描：本 PRD 任何新增代码不得 import 并修改 `_DEBATE_LAYERS`、不得调用 `suggested_weights` 结果写回生产、不得引用 `pos_scale` 缩放生产仓位。

---

## 11. workbuddy 执行规则（防止自由发挥）

1. **只读不改冻结项**：任何 P0/P1 代码不得修改 Layer 权重、评分公式/阈值、Risk Budget 参数、指标定义。改动即视为 bug。
2. **增量子模块**：所有新增功能以独立文件/函数实现，现有函数签名与返回值保持兼容；数据库只 `CREATE TABLE`，不改现有表。
3. **行为零变化为默认**：除非 PRD 显式允许的 EXTREME 风险否决，新流水线在既有数据上必须产出一致。
4. **先观察不干预**：Evidence Independence 在 P1 只写 `independence_flag`，绝不在评分聚合中降权。
5. **Shadow 优先**：Risk Guard 必须先 Shadow 运行并积累对照，禁止直接接管生产。
6. **不造数据**：P0 不要求真实 P&L；financial_outcome 留空/可选，禁止为通过验收造脆弱 adapter。
7. **每改必测**：每个 P0 项落地必须附对应单测，且包含 §10 的相关断言。
8. **文档与代码一致**：P1 文档 v2 必须反映真实实现，删除"权重非固定"等误导表述。

---

## 12. 附录：P0 新增 7 张表 + 修改文件清单

**新增 7 张表**：`data_snapshot` / `decision_run` / `decision_item` / `evidence` / `decision_version` / `outcome_attribution` / `shadow_run`

| 文件 | 动作 |
|---|---|
| `backend/database/models.py` | 新增 7 张表 |
| `backend/VERSION.py` | 新增（六维常量） |
| `backend/risk_guard.py` | 新增（Risk Guard Adapter，行为零变化） |
| `backend/write_decision_ledger.py` | 新增（流水线步骤） |
| `backend/committee/investment_committee.py` | 仅加冻结标注 + `pos_scale` 开关（逻辑不变） |
| `backend/learning_center.py` | 停用 `pos_scale` 生产影响；四层归因 + 错误标志 |
| `backend/brain/cio_agent.py` | `produce()` 末尾写 Ledger + Evidence |
| `backend/decision_tree.py` | 各 layer 返回增加 evidence 钩子位（不改逻辑） |
| `backend/run_daily.py` | 插入 Ledger / Shadow 步骤 |
| docs（P1） | architecture / design-principles / roadmap / README 对齐 |

---

## 13. 终局判断

v0.2 成功标准不是"把 `decision_tree.py` 改得更漂亮"，而是 90 天后系统能回答：

- 哪个 Layer 创造 Alpha？哪个是噪音？
- 哪个风险约束真正保护了组合？
- 哪些 Evidence 是重复的（Independence）？
- 错误来自信息 / 判断 / 执行 / 运气？
- Counterfactual：那些"没买"的决定，事后看对不对？

若 v0.2 让系统能回答这些，它就成了 v0.2.5（确定改哪些规则）与 v0.3（AI Analyst）的真实地基。代码可重写、权重可重估、Agent 可替换，但**"当时系统看到了什么、相信了什么、为什么做此判断、后来发生了什么"**这条 Decision Ledger 一旦连续积累，极难被替代。
