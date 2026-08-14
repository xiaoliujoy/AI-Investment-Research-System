# XL Professional Trading System Gap Analysis v1.0

> 方法论来源：Perry J. Kaufman《Trading Systems and Methods》(6th ed., 2019)  
> 用途：用书中「专业交易系统架构」逐层审计现有系统，定位缺口与优先级  
> 配套文档：《XL Trading System Framework》（规划中）  
> 治理基线：项目处于 Phase 1E FROZEN / OBSERVATION MODE，RISK_GUARD_ENABLED=0

---

## 0. 怎么用这份文档

每一层按固定 7 列审计：

| 列          | 含义                     |
| ---------- | ---------------------- |
| Kaufman 原则 | 书中这一层要回答什么问题           |
| 现有实现       | 你已有的对应模块 / 项目          |
| 代码 / 模块    | 真实文件路径（已核实）            |
| 实验结果       | 实测数值（标注「已核实」或「待核实」）    |
| 缺口         | 距离专业系统的距离              |
| 优先级        | P0 立即 / P1 近期 / P2 观察  |
| 下一步实验      | 具体动作（一律 Observation 层） |

---

## 1. 架构总图（13 层闭环）

```
Regime → Signal → Selection → Entry → Stop → Exit → Position Sizing
   → Testing → Robustness → Portfolio → Execution → Attribution → Research Loop
```

- 前 11 层是书中「单一系统」骨架；后 2 层（Attribution / Research Loop）是你已经走在前面、书里偏薄弱的部分。
- 你的四个项目已分别覆盖：Momentum A/B（Signal/Selection/Testing）、黄金实验（Entry/Stop/Exit/Position Sizing）、Trading Coach（Execution/Plan-Execution Gap）、AI CIO（Regime/Portfolio/Risk Budget）。
- 关键结论：**模块已经分别存在，缺的是统一架构与 2 个引擎（Exit / Robustness）。**

---

## 2. 逐层 Gap Analysis

### 2.1 Regime（市场环境识别）

| 项          | 内容                                                                                                                                                |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Kaufman 原则 | 任何方法都有适用环境；Signal 本身无绝对意义，先问「当前市场允许它工作吗」                                                                                                          |
| 现有实现       | AI CIO Regime Engine：Market Regime / Risk Score / Risk Temperature / Breadth / Trend / Global Market / Asset Class / Risk Budget                  |
| 代码 / 模块    | `backend/cio_decision_engine.py`、`backend/risk_budget.py`、`regime_history.py`、`regime_backtest.py`、`asset_intelligence/validation/regime_eval.py` |
| 实验结果       | Regime→Risk Budget 链路已落地（CIO 接 `score_to_budget`）                                                                                                 |
| 缺口         | **Regime→Strategy Selection 不存在**（已核实 NOT FOUND）：CIO 只做资产类别配置，不按 Regime 选具体策略                                                                     |
| 优先级        | P1                                                                                                                                                |
| 下一步实验      | 建 Regime×Strategy 兼容矩阵（Strong Trend/Mild Trend/Range/High Vol/Crisis × Momentum/Mean Reversion/Breakout/Trend），先观察、不执行                            |

### 2.2 Signal（关注信号）

| 项          | 内容                                                                                                                                      |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Kaufman 原则 | Signal 五问：是什么 / 为何存在 / 在何种市场存在 / 何时失效 / 强度如何量化                                                                                          |
| 现有实现       | Momentum Model A/B                                                                                                                      |
| 代码 / 模块    | `backend/os_layers/market_momentum.py`（MODELS A={20:0.2,60:0.4,120:0.4}、B={5:0.1,20:0.2,60:0.35,120:0.35}；Tilt=B−A 五档 `_tilt_classify`） |
| 实验结果       | 宇宙=219、drift=0、快照累积中；Momentum Tilt 已领先书里「短中期动量背离」思路                                                                                     |
| 缺口         | Signal 仍停在 Score 层，未形成「定义→验证→排序→分层」的统计优势表达                                                                                              |
| 优先级        | P1                                                                                                                                      |
| 下一步实验      | 给每个 Signal 补「失效条件」与「Regime 兼容性」字段，进入 Scorecard                                                                                          |

### 2.3 Selection（候选选择）

| 项          | 内容                                                                                                     |
| ---------- | ------------------------------------------------------------------------------------------------------ |
| Kaufman 原则 | Signal 产生后买谁：Top N / Equal Weight / Score Weight / Vol Weight / Risk Parity                            |
| 现有实现       | Global/Momentum 侧 Selection 研究中；A 股 Selection 人为驱动                                                     |
| 代码 / 模块    | `market_momentum.py`（Ranking 雏形）；A 股侧无自动 Selection 模块                                                  |
| 实验结果       | Momentum A/B 在比 Formula，尚未扩展成 Ranking→Portfolio Construction                                           |
| 缺口         | **设计注记**：A 股 Selection 按方法论红线「板块>龙头>资金>图形、候选只圈不筛」是**有意人为层**，不是待补的自动化缺口；Global/Momentum 侧才需研究 Top N 与加权 |
| 优先级        | P2                                                                                                     |
| 下一步实验      | Momentum 侧先做 Top N + Score Weight vs Vol Weight 的 Observation 对比                                       |

### 2.4 Entry（入场）

| 项          | 内容                                                                                                   |
| ---------- | ---------------------------------------------------------------------------------------------------- |
| Kaufman 原则 | Entry 是独立变量；正确方向 ≠ 正确 Entry                                                                          |
| 现有实现       | 黄金实验 E1-E4                                                                                           |
| 代码 / 模块    | `mt5_raw/entry_experiments_report.json`、`entry_timing_report.json`（来源 `entry_timing_experiments.py`） |
| 实验结果       | **已核实**：E1/E2 预期入场 164 笔净亏 −$2345.41；E3/E4 确认入场 46 笔净盈 +$2389.3                                      |
| 缺口         | 结论强，但仅覆盖黄金；A 股「多周期确认入场」尚未做同类对照实验                                                                     |
| 优先级        | P2                                                                                                   |
| 下一步实验      | 对 A 股趋势单复刻 E1-E4 对照（预期 vs 确认入场），验证跨市场一致性                                                             |

### 2.5 Stop（止损 / 失效位）

| 项          | 内容                                                                                                                                                                                             |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Kaufman 原则 | Stop 是策略结构的一部分，不是执行附属参数                                                                                                                                                                        |
| 现有实现       | 黄金 ATR 实验                                                                                                                                                                                      |
| 代码 / 模块    | `mt5_raw/exit_lifecycle_report.json`（来源 `exit_lifecycle_analysis.py`）                                                                                                                          |
| 实验结果       | **已核实**：原止损基线 PF≈1.0182；ATR×3 后 PF=1.52（n=210）。⚠️ 用户口述「Median ATR≈$8.49」**待核实**：项目中 8.49 实为 subtype `A_immediate_continuation` 的 median_mfe，非 ATR 中位数；exit_lifecycle 以 r_usd（median≈4.34）为止损单位 |
| 缺口         | Stop 规则未从黄金推广到 A 股 / 跨资产组合层                                                                                                                                                                    |
| 优先级        | P2                                                                                                                                                                                             |
| 下一步实验      | 把「失效位=结构的一部分」写成通用 Stop 定义，接入等待型趋势交易执行卡                                                                                                                                                         |

### 2.6 Exit（兑现）★最大机会

| 项          | 内容                                                                                                                |
| ---------- | ----------------------------------------------------------------------------------------------------------------- |
| Kaufman 原则 | Exit 决定优势能否留存；很多系统死在 Exit                                                                                         |
| 现有实现       | Trading DNA / 黄金实验 Exit 段                                                                                         |
| 代码 / 模块    | `backend/trading_dna_v1.2.py`、`mt5_raw/execution_intelligence.json`、`exit_lifecycle_report.json`                  |
| 实验结果       | **已核实**：MT5 225 笔净 +9.01、PF 1.0036；exit median_capture_ratio **−0.697**；giveback 5473 远高于 pnl 43.89，印证「Exit 吃掉优势」 |
| 缺口         | **Exit Research 几乎空白**：目前只描述问题，无系统化的 Exit 规则库（trailing / MFE capture / time stop）                                 |
| 优先级        | **P0**                                                                                                            |
| 下一步实验      | 用 MT5 + 黄金数据做 Exit 规则网格（ATR 倍数 trailing、MFE 百分比 capture、持有时长 stop），全部 Observation 层，产出 PF / capture 对比            |

### 2.7 Position Sizing（仓位）

| 项          | 内容                                                                                         |
| ---------- | ------------------------------------------------------------------------------------------ |
| Kaufman 原则 | 赚多少由市场给，亏多少由自己定；最终是 Risk-Adjusted Return 最大化                                               |
| 现有实现       | AI CIO Risk Budget                                                                         |
| 代码 / 模块    | `backend/risk_budget_backtest.py`、输出 `backend/output/risk_budget_backtest_2026-08-04.json` |
| 实验结果       | **已核实**：C_AI_RiskBudget CAGR=8.56%、Sharpe=0.91、MaxDD=−8.78%                                |
| 缺口         | 仍是单策略预算；未进「Signal×Regime×Vol×Correlation×PortfolioRisk → Size」的多因子 Risk Engine             |
| 优先级        | P1                                                                                         |
| 下一步实验      | 在 Observation 层把 Volatility / Correlation 因子叠进 sizing 公式，对比回撤与 Sharpe                      |

### 2.8 Testing（验证）

| 项          | 内容                                                                                               |
| ---------- | ------------------------------------------------------------------------------------------------ |
| Kaufman 原则 | Hypothesis→Rule→Backtest→OOS→Walk Forward→Robustness→Live Obs→Live                               |
| 现有实现       | Momentum Backtest + 黄金实验 + Trading DNA                                                           |
| 代码 / 模块    | `market_momentum.py`、`momentum_incremental_test.py`                                              |
| 实验结果       | Backtest + 历史数据已有；`momentum_incremental_test.py` 自述「骨架占位、不可运行」，ft_ret\_* 全 None，MIN_SNAPSHOTS=20 |
| 缺口         | **校准注记**：用户评 7/10 偏乐观；OOS / Walk-forward 未标准化成统一流水线 → 实际约 6/10                                   |
| 优先级        | P1                                                                                               |
| 下一步实验      | 定 Unified Research Protocol（见 2.10 / 第 5 节），把每个新想法强制走完 11 步                                      |

### 2.9 Robustness（稳健性）★最大结构性缺口

| 项          | 内容                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------- |
| Kaufman 原则 | 发现必须在一组合理参数与环境变化下仍保持统计优势，才叫 Robust                                                          |
| 现有实现       | 无独立模块                                                                                       |
| 代码 / 模块    | 仅 `momentum_incremental_test.py`（未就绪）                                                       |
| 实验结果       | 无系统化的参数稳定性 / 跨市场 / 跨时段 / 跨 Regime 检验                                                        |
| 缺口         | 距专业系统最远：不知道 Alpha 是真优势还是参数偶然性                                                               |
| 优先级        | **P0**                                                                                      |
| 下一步实验      | 对 Momentum A/B 做参数网格（10/20/60/120 日）＋跨资产（A股/美股/黄金/原油/铜/债券）＋跨年（2020-2026）稳健性矩阵，Observation 层 |

### 2.10 Portfolio + Execution（组合与执行）

| 项          | 内容                                                                                                                                             |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Kaufman 原则 | 多系统组合 + 真实执行；Research Edge 与 Execution Edge 分离                                                                                                 |
| 现有实现       | AI CIO（组合） + Trading Coach（执行）+ Trading Constitution（交易宪法）                                                                                     |
| 代码 / 模块    | `cio_decision_engine.py`、`backend/os_layers/trading_constitution.py`（`pre_trade_gate()` ALLOW/BLOCK/WARN）、`docs/trading_coach_prd_v0.1.md`     |
| 实验结果       | Regime→Risk Budget 已落地；`pre_trade_gate` 已定义在 L170；Trading Coach 设计文档齐                                                                          |
| 缺口         | **校准注记**：用户评 7/10 偏乐观。Plan-Execution Gap 目前只在 `trading_rules_v0.2.md` 作一级指标，**无独立 `plan_execution.py` / `execution_quality.py` 模块** → 实际约 6/10 |
| 优先级        | P1                                                                                                                                             |
| 下一步实验      | 把 Plan-Execution Gap 从指标升级为可追踪模块（每笔：信号→计划→实际执行偏差）                                                                                              |

### 2.11 Attribution（绩效归因，书里偏薄弱、你已领先）

| 项          | 内容                                                 |
| ---------- | -------------------------------------------------- |
| Kaufman 原则 | 不直说，但专业系统必须能回答「收益来自哪」                              |
| 现有实现       | 概念在 Trading DNA / execution_intelligence 中         |
| 代码 / 模块    | `mt5_raw/execution_intelligence.json`              |
| 实验结果       | 已有经济画像雏形                                           |
| 缺口         | 未形成「Signal/Entry/Exit/Sizing/Regime/Execution」六维拆解 |
| 优先级        | P1                                                 |
| 下一步实验      | 见第 5 节 Strategy Scorecard，把归因字段挂到每个策略              |

### 2.12 Research Loop（研究闭环，书里偏薄弱、你已领先）

| 项          | 内容                                                                  |
| ---------- | ------------------------------------------------------------------- |
| Kaufman 原则 | 系统要持续学习、淘汰失效策略                                                      |
| 现有实现       | Observation 面 + Shadow 评估（三平面分离）                                    |
| 代码 / 模块    | `shadow_run` / `shadow_evaluator.py`、自动化 `automation-1786677039167` |
| 实验结果       | 每日积累快照、达条件才谈接管，纪律已建立                                                |
| 缺口         | 观察成果尚未回流成「模型改进」的标准动作                                                |
| 优先级        | P2                                                                  |
| 下一步实验      | 把 Robustness / Exit 实验结果定义成「接管门槛」输入 Shadow Review                   |

---

## 3. 成熟度评分（含校准注记）

| 模块              | 用户评 | 研投君校准 | 注记                             |
| --------------- | --- | ----- | ------------------------------ |
| Regime          | 8   | 8     | 成熟；缺 Strategy Selection        |
| Signal          | 7   | 7     | Momentum 在补强                   |
| Selection       | 6   | 6     | A 股侧为有意人为层，非缺口                 |
| Entry           | 7   | 7     | 黄金已实证，待跨市场                     |
| Stop            | 7   | 7     | ATR×3 已量化；8.49 待核实             |
| Exit            | 4   | 4     | 最大机会，几乎空白                      |
| Position Sizing | 7   | 7     | Risk Budget 已验证                |
| Testing         | 7   | 6     | OOS/Walk-forward 未标准化          |
| Robustness      | 3   | 3     | 最大结构性缺口                        |
| Portfolio       | 7   | 7     | CIO 已形成；缺 Allocation           |
| Execution       | 7   | 6     | pre_trade_gate 在，独立 Coach 模块未立 |

**总判断**：系统已过「学策略」阶段，进入「建系统」阶段；下一跳是「系统平台」。最该补的不是更多 Signal，而是 **Exit Engine + Robustness Engine + Strategy Allocation + Unified Research Protocol + Performance Attribution**。

---

## 4. 五大缺口与优先级

| # | 缺口                        | 解决什么                                              | 优先级    | 合规归属          |
| - | ------------------------- | ------------------------------------------------- | ------ | ------------- |
| ① | Exit Engine               | 把 MFE 变 Realized P\&L                             | **P0** | Observation 层 |
| ② | Robustness Engine         | Alpha 是真优势还是参数偶然                                  | **P0** | Observation 层 |
| ③ | Strategy Allocation       | 什么 Regime 用什么 Strategy                            | P1     | Observation 层 |
| ④ | Unified Research Protocol | 新想法如何进统一实验体系                                      | P1     | Observation 层 |
| ⑤ | Performance Attribution   | 收益来自 Signal/Entry/Exit/Sizing/Regime/Execution 哪层 | P1     | Observation 层 |

---

## 5. Trading System Scorecard（Strategy DNA 模板）

以后每个策略不再只看 CAGR/Sharpe/MaxDD，而填这张表：

| 维度            | 指标                   | 现有数据源                                   |
| ------------- | -------------------- | --------------------------------------- |
| Alpha         | IC / Rank IC         | market_momentum（待补）                     |
| Hit Rate      | 胜率                   | mt5_raw / 黄金实验                          |
| Payoff        | 盈亏比                  | 同上                                      |
| Profitability | PF                   | exit_lifecycle / execution_intelligence |
| Drawdown      | MaxDD                | risk_budget_backtest                    |
| Stability     | Rolling Sharpe       | 待建                                      |
| Regime        | Regime Attribution   | cio_decision_engine                     |
| Entry         | Entry Efficiency     | 黄金 E1-E4                                |
| Exit          | MFE Capture          | trading_dna（现 −0.697）                   |
| Risk          | Risk Efficiency      | risk_budget                             |
| Robustness    | Parameter Stability  | Robustness Engine（待建）                   |
| Execution     | Plan-Execution Gap   | trading_rules_v0.2（待升级为模块）              |
| Portfolio     | Correlation          | 待建                                      |
| Capacity      | Turnover / Liquidity | 待建                                      |

核心升级：研究一个策略时，问题从「赚不赚钱」变成「**Edge 到底来自哪一层**」。

---

## 6. 治理约束：新模块必须 Observation-only

项目当前 **Phase 1E FROZEN / OBSERVATION MODE**，RISK_GUARD_ENABLED=0，三平面分离（生产 `run_daily` / 观察 `shadow_run` / 控制 人工 Release Gate）。因此：

- 第 4 节五个新模块（Exit Engine / Robustness Engine / Strategy Allocation / Research Protocol / Attribution）**一律只做 Observation 层**，不接 `run_daily` / `risk_guard` / `shadow`。
- 冻结项（权重/公式/阈值/L7 composite/Risk Budget 生产效应）**暂不动**。
- 接管须人工置 RISK_GUARD_ENABLED=1 且 release_gate APPROVED。
- 研究产出先成 Shadow Review 输入，达「≥10 交易日 / replay drift=0 / 非 EXTREME 意外 DIFF=0 / veto 等价 100% / GM 回归通过」才谈接管。

---

## 7. 三个月研究路线（做什么 / 暂不碰什么）

**Month 1（P0 起步）**

- Exit Engine（Observation）：MT5 + 黄金数据做 Exit 规则网格，产出 PF / capture 对比
- Robustness Engine 起步：对 Momentum A/B 做参数网格 + 跨资产 + 跨年稳健性矩阵

**Month 2（P1 成型）**

- Unified Research Protocol：把 Hypothesis→…→Live 11 步固化成 Observation 流水线
- Strategy Allocation 草图：Regime×Strategy 兼容矩阵，先观察不执行

**Month 3（P1 收口）**

- Performance Attribution 框架：收益拆到六层，挂进 Scorecard
- 把 Exit / Robustness 结果定义成 Shadow Review 接管门槛

**暂不碰（冻结期）**

- 生产面权重 / 公式 / 阈值 / Risk Guard 接管
- 把任何新引擎接 run_daily
- 用未核实数字（ATR 8.49 / Mixed PF 2.28）做决策

---

## 8. 事实核实注记

| 用户口述                                               | 状态     | 说明                                                           |
| -------------------------------------------------- | ------ | ------------------------------------------------------------ |
| 黄金 E1/E2 164 笔净亏 −$2345.41                         | ✅ 已核实  | `mt5_raw/entry_experiments_report.json`                      |
| 黄金 E3/E4 46 笔净盈 +$2389.3                           | ✅ 已核实  | 同上                                                           |
| ATR×3 → PF 1.52（基线 ≈1.02）                          | ⚠️ 部分  | 基线 `pf=1.0182` 已复现（`entry_experiments_report.json:333`）；uplift `1.52` 在项目任何 artifact 均找不到 → 标 `CLAIM`，待 LOCATE |
| Risk Budget CAGR 8.56 / Sharpe 0.91 / MaxDD −8.78% | ✅ 已核实  | `risk_budget_backtest_2026-08-04.json`                       |
| MT5 225 笔净 +9.01 / PF 1.0036                       | ✅ 已核实  | `mt5_raw/report_..._summary.json`                            |
| Exit capture −0.697 / giveback 5473≫pnl 43.89      | ✅ 已核实  | `execution_intelligence.json` / `exit_lifecycle_report.json` |
| Median ATR ≈ $8.49                                 | ⚠️ 待核实 | 项目中 8.49 实为 subtype median_mfe，非 ATR 中位数                     |
| Mixed Strategy PF ≈ 2.28                           | ❌ 未找到  | 项目无「Mixed Strategy」PF；2.28 仅作价格/mae 数值出现                     |

可信度：本审计对架构与成熟度的判断 **高（约 90%）**，基于你已完成的四条真实工作线；两处数字偏差已在上文标红，不影响主结论。

---

## 9. 修订附录 v1.0.1（2026-08-14 架构修正）

用户审阅后给出一处关键架构修正，已落地为独立文档 `docs/Strategy_Research_Contract_v0.1.md`：

**原文档优先级（§7）写为 P0 Exit / P0 Robustness / P1 Research Protocol —— 顺序有误。**

修正后依赖关系（Research Protocol 是基础设施，先于 Exit / Robustness，而非 P1 排在二者之后）：

```
Research Contract / Protocol  ──（基础设施，先做）
        ├─→ Exit Engine Observation v0.1      （第一实验位：真实数据证明 Exit 是最大泄漏点）
        ├─→ Robustness Engine Observation v0.1（回答"这个 Edge 是不是真的"）
        ├─→ Attribution（Performance Attribution）
        └─→ Strategy Allocation（Regime→Strategy，进控制面，需人工 Release Gate）
```

核心原则（本次修正固化）：
1. 先有统一研究语言（Contract），再决定先做哪个引擎；不二选一开工。
2. 每个实验字段带 `Evidence Status`（CLAIM→LOCATED→REPRODUCED→VALIDATED→ROBUST→ACCEPTED→PRODUCTION），强制 `Claim→Source→Reproduce→Validate→Record` 可信度链。
3. 聊天结论不能直接进 Research Record；未 `VALIDATED` 的数字不得写进交付物结论。

落地物：
- `docs/Strategy_Research_Contract_v0.1.md`：13 字段模板 + Evidence Status 状态机 + 3 个已核实实例（黄金 E1/E4、ATR×3、Momentum A/B）+ 断链数字纠偏。
- `backend/os_layers/research_contract.py`：机器可读内核（`ResearchContract` dataclass + `EvidenceStatus` 枚举 + JSON I/O + `validate()`），Observation 层，不碰生产。
- `backend/output/research_contracts/`：实例存放（`RC-GOLD-EXIT-TRAIL.json` 模板 + `RC-GOLD-ENTRY-E1E4.json` 已填实例，均已 `--check` 通过）。

治理不变：全部 Observation-only，不接 `run_daily` / `risk_guard` / `shadow`；冻结项（权重/公式/阈值/Risk Budget 生产效应）待 `release_gate` APPROVED。

---
