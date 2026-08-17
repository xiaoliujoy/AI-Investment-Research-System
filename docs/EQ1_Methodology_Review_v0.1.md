# EQ-1 · Entry Quality / Execution Quality — 方法学审查 v0.1（修订 v0.1.1）

> **本文档性质：方法学审查（Methodology Review），不是 Pre-Registration，不写代码，不跑实验，不做变量调优。**
> 目的：在建立 `EQ-1 Pre-Registration v0.1` 之前，先把研究变量、Outcome、因果顺序、候选假设冻结并审查。
> 审查通过后，才进入正式预登记。
>
> **修订记录 v0.1.1（用户审查通过后调整）**：
> 1. `ETQ`（Entry Timing Quality）→ **`ETD`（Entry Timing Distance）**，去掉"Quality"隐含的方向预设；先测距离，让数据决定它是否=质量。
> 2. **R1 已决**：IAЕ = entry 后 **10 根完整 M5 K 线**内的最大逆向 excursion（固定时间窗，不依赖止损、不混合时间尺度）。
> 3. **R2 已决**：MFE Realization 的 0.2R 地板**移出 Primary**；Primary = 原始 MFE / Giveback，MFE Realization = P&L/MFE 仅作 Secondary/Exploratory。
> 4. **R3 已决**：双轨——Primary 用 USD 原始路径量；Secondary 做风险标准化（÷初始风险）并同时报告未控制 vs 控制初始风险。
> 5. H1-H4 按用户重构（H3 不再预设中介；H4 = ETD + 初始风险 → MFE Realization）。
> 6. **CP 定义仍为开放决策**（见 §2.3 + §5 R8），待用户冻结后才进预登记。

---

## 0. 与 H2-A 的显式解耦（必须先写死）

H2-A 的结论是：

> 在当前预登记、当前信息集、当前 Archetype 定义下，没有证据表明历史 E2 能被 entry_time 当时的信息稳定识别。

**这一结论不得成为 EQ-1 的先验。** 两者方法学独立：

| 维度 | H2-A | EQ-1 |
|---|---|---|
| 因变量 | 事后标签 E2（分类） | 原始路径量 MAE/MFE/Giveback/R（连续，无分类） |
| 核心问题 | 能否**预测**某类结果 | 入场**行为/时机**是否改变风险暴露与兑现 |
| 自变量 | 机械市场状态 Archetype（A/B/C） | Entry Timing Distance（入场相对市场事件点的时间距离） |
| 性质 | 标签预测（falsified） | 暴露→结果关联（待建） |

EQ-1 的 ETD 定义必须**完全独立于任何 E1-E4 标签**，仅由 entry_time 及之前的客观市场结构定义。禁止为了让 ETD "避开 E2" 或"复刻 anticipatory"而设计——这正是 H2-A 之后最该警惕的隐性反向链路。

---

## 1. 冻结元素 ①：Outcome（研究什么）

分四类。所有 Outcome 均为**交易后可由 K 线路径机械计算的连续量**，不含任何 post-trade 分类——这是与 E1-E4 的根本区别（连续量可关联，分类标签不可预测）。

| 类 | 指标 | 操作定义（候选） | look-ahead 风险 |
|---|---|---|---|
| **Risk** | MAE | 入场后至平仓，价格相对 entry 的最大逆向幅度（USD） | 低（纯路径量） |
| | **IAЕ (Initial Adverse Excursion)** | **entry 后 10 根完整 M5 K 线内**相对 entry 的最大逆向幅度（USD）。仅用 entry 之后完成的 K 线（见 §3 micro look-ahead 排除） | 低，窗口已冻结=10 |
| | Stop-hit prob | 二元：价格是否在平仓前先触止损 | 低 |
| **Opportunity** | MFE | 入场后至平仓，价格相对 entry 的最大有利幅度（USD） | 低 |
| | Time-to-MFE | 入场至 MFE 峰值的 K 线数 | 低 |
| **Execution** | **MFE Realization（Secondary）** | realized_pnl_usd / MFE_usd（比率）；**仅作 Secondary/Exploratory，不进 Primary** | 中（分母需地板，留待 H4 单独预登记） |
| | **Giveback（Primary）** | MFE_usd − realized_pnl_usd | 低 |
| | Exit Efficiency（Secondary） | realized_pnl / (MFE_usd + |MAE_usd|) 或类似归一化捕获率 | 中（定义须冻结） |
| **Economic** | R | realized_pnl / 初始风险 | 中（见 §5 R3 双轨） |
| | P&L / PF | 已实现盈亏 / 盈利因子 | 低 |

**关键纪律**：Primary 优先使用 **USD 原始路径量**（MAE / IAЕ / MFE / Giveback / P&L）；R 标准化与 MFE Realization 仅作 Secondary。连续量不是标签，look-ahead 风险不在"计算它们"，而在"用它们反推 ETD"——只要 ETD 纯由 entry_time 前信息定义（§2），因果序即成立。

---

## 2. 冻结元素 ②：Exposure = Entry Timing Distance（中性）

第一阶段**只研究 Entry Timing Distance（ETD）**，不研究 position sizing、vol regime、candle structure 等其他暴露。ETD 是**连续量**，可直接检验"入场离市场结构事件越远 → IAЕ 越大"的单调关系，而非切成 3 个空细胞（H2-A 的失效模式）。

### 2.1 语义变化（重要）

原框架称 ETQ（Quality），隐含"更接近确认点=更高质量"。这会把 H2-A 的经验（anticipatory 历史上表现差）偷运回新假设。改为 **ETD（Distance）**：

- 只测"入场时间相对一个预定义市场事件 CP 的时间距离"。
- **距离越远是否=越差，让数据回答**，不在定义里预设方向。

### 2.2 ETD 操作定义（骨架，CP 见 §2.3）

1. 定义**客观市场事件点 CP(t)**：由 entry_time 及之前 K 线纯机械计算的市场结构函数。**CP 不得引用任何交易结果量（MFE/MAE/PnL/E-label）。**
2. `ETD = entry_time − CP_time`（时间距离，连续，≥0）。
   - ETD 小 = 入场紧邻市场结构事件（confirmation-like）
   - ETD 大 = 入场远早于结构事件形成（anticipatory-like）
3. 副指标（可选，预登记时定）：`price_distance(entry, CP_level)`（价格维度），用于稳健性。

**为何不用 A/B/C**：H2-A 已证明 3 态切割把 96% 压进 A、B=0、C=8，检验力崩溃。ETD 连续化后可避免该失效模式。

### 2.3 CP 定义 —— 开放决策（R8，待冻结，详见 §5）

CP 是 EQ-1 **最核心的研究设计决策**，决定 ETD 测的到底是什么。当前候选（不冻结）：

- **CP-A：N 根突破位**（如突破过去 20 根最高/最低）。客观、易复现，但**仅当近期发生突破时才有意义**；对 anticipatory 交易者（多数 entry 不在突破点）会大量出现"无 CP / CP 远在过去" → 退化分布。
- **CP-B：回踩确认位**。已**否决**——与 H2-A 的 A/B/C 逻辑过近，会背回 H2-A 的结构假设。
- **CP-C：趋势事件位**（某客观趋势状态改变）。理论上更宽，但定义难度高、易主观。
- **CP-D（推荐）：摆点时间戳（swing-pivot），方向镜像**。CP = entry_time 之前 W 根窗口内**最近一个结构性摆点**的时间戳；Long 取最近 swing high（阻力），Short 取最近 swing low（支撑）。ETD = entry_time − CP_time。
  - **全部 210 笔均有定义**（任何窗口都有最近摆点），无空细胞。
  - **ex-ante 安全**：摆点在 entry_time 之前已存在，不需未来信息。
  - **中性**：测的是"入场距最近结构的时间距离"，方向由数据决定。
  - 摆点操作定义须预登记（如 (2k+1) 根窗口内的 close 局部极值，或 N 根最高/最低 close）；k、W 预登记。
  - 已知局限：时间距离不均匀（摆点间隔不规则），v0.1 作探索性暴露可接受；后续可补 price_distance 作 secondary。

> 用户原"第四种方案"（过去 N 根结构突破点）本质是 CP-A 的重构，继承了 CP-A 的空细胞风险；且若 CP 取"该笔后来参与的突破"，则对 anticipatory 交易突破在 entry 之后 → **需未来信息 = look-ahead**。故推荐 CP-D（纯 entry 前摆点）规避这两类失效。

**阶段范围**：Phase 1 仅 ETD。position sizing / stop-distance-choice 等作为 Phase 2 候选暴露，不进入 EQ-1 v0.1。

---

## 3. 冻结元素 ③：Causal Ordering（继承 H2-A 纪律）

```
Entry-time information (t ≤ entry_time)
        ↓
ETD = entry_time − CP_time（纯 entry_time 前机械量）
        ↓
future path: MAE / MFE / Exit (t > entry_time)
        ↓
Outcomes (Risk / Opportunity / Execution / Economic)
```

**硬性边界（代码层须强制）**：
- ETD 仅读 `time < entry_time` 的已收盘 K 线（沿用 H2-A 的 `close_time ≤ entry_time` 修正，排除正在形成的 entry bar）。
- 任何 Outcome 仅读 `time > entry_time` 的 K 线。
- **IAЕ 的 10 根窗口**：仅取 entry 之后**完整收盘**的 M5 K 线（第一根完整 post-entry bar 起算，不含 entry 所在 bar 的剩余部分）。
- **禁止**：用未来 MFE → 反推 ETD。ETD 与 Outcome 之间单向。

此边界在结构上保证无 micro look-ahead（ETD 不碰 entry bar；Outcome 不碰 entry 前）。

---

## 4. 冻结元素 ④：Research Question + 候选假设

**母问题（RQ-EQ1）**：
> Entry Timing Distance 是否系统性改变交易的初始风险暴露与后续机会空间？

**候选假设（明确：仅为候选，不写入正式预登记，不锁定 Gate）**：

| 假设 | 内容 | 类型 | 当前优先级 |
|---|---|---|---|
| H1 | ETD 越大（越 anticipatory）→ IAЕ 越大 | 关联（暴露→风险） | ★★★ |
| H2 | ETD 越大 → MFE 越小（机会成本） | 关联（暴露→机会） | ★★ |
| H3 | IAЕ 与 Giveback / Exit Efficiency 相关 | 关联（风险→执行） | ★★★★★ |
| H4 | ETD + 初始风险 → MFE Realization | 条件关联（暴露+风险→兑现） | ★★★★★ |

**重要重构（用户定）**：
- H3 **不再预设"IAЕ 是中介变量"**。先研究 IAЕ 与 Exit Outcome 是否相关；只有当 H1 与该相关都成立后，才讨论正式 mediation。否则现在把"中介"写进去，因果结构会比数据能支持的程度更强。
- H4 改用 MFE Realization（已降为 Secondary），作为"控制初始风险后兑现是否仍为主瓶颈"的检验。

**注意**：H1-H4 此处仅为"研究问题清单"，不是预登记假设。进入 Pre-Registration 时须对每个假设指定主统计量、Gate、负对照，且**四假设全部报告，禁止只报显著者**。

---

## 5. 方法学审查发现的必需决策（预登记前必须冻结）

| # | 风险 | 处理（状态） |
|---|---|---|
| R1 | **IAЕ 窗口** | **已决：entry 后 10 根完整 M5 K 线**（固定时间窗，不依赖止损、不混合时间尺度）。micro look-ahead 排除：首根取 entry 之后完整收盘 bar。 |
| R2 | **MFE Realization 分母爆炸** | **已决：移出 Primary**。Primary 用原始 MFE / Giveback；MFE Realization = P&L/MFE 仅 Secondary/Exploratory，其分母地板（如 0.2R）留待 H4 单独预登记，不在 v0.1 主分析引入人为阈值。 |
| R3 | **止损内生性** | **已决：双轨**。Primary = USD 原始路径量（MAE/IAЕ/MFE/Giveback/PnL），不控制初始风险；Secondary = 风险标准化（IAЕ/初始风险、MFE/初始风险）并**同时报告未控制总效应与控制初始风险后的条件关联**，二者并陈更有解释力。初始风险口径须预登记（实际 SL 若存在；否则用 R 代理）。 |
| R4 | **多重比较** | 母问题 RQ-EQ1 为纲，四假设全报；主统计量各自预登记。 |
| R5 | **小样本** | 210 笔；H3/H4 定为方向性/探索，不依赖 p<0.05 为唯一 Gate。 |
| R6 | **负对照设计** | 预登记 ETD permutation：固定 Archetype 分配（此处=固定 ETD 值），随机重排 Outcome 标签或重排 ETD 分配，重算 primary stat（如 Spearman(ETD,IAЕ) 斜率 / IAЕ~ETD 回归系数），2000 次固定种子，报经验百分位；仅诊断不 Gate。 |
| R7 | **关联≠处方** | 结论限定"给定已入场，timing 与暴露的关联"，不产出交易规则。 |
| **R8** | **CP 定义方向**（核心） | **开放**：CP-A（突破位，空细胞+潜在 look-ahead 风险）/ CP-B（否决）/ CP-C（难）/ **CP-D（推荐：entry 前摆点时间戳，方向镜像，连续、ex-ante、全样本有定义）**。待用户冻结。 |

---

## 6. 建议执行顺序（我的判断，供你定）

你倾向 H3/H4 优先（★★★★★）。我补充一个方法学依赖：**H3（IAЕ→Exit 失败）的因果解释力，依赖于 H1（ETD→IAЕ 存在）成立**。若 ETD 根本不动 IAЕ，则"IAЕ 中介 Exit"无从谈起。

因此建议顺序（不违反你的优先级，只是先花极低成本确认地基）：

```
H1+H2 联合（trade-off gate：越 anticipatory 是否增风险但牺牲机会？）  ← 低成本，建立暴露→结果映射
        ↓
H3（IAЕ 是否与 Giveback/Exit Efficiency 相关）                        ← 你的核心，依赖 H1 成立
        ↓
H4（控制初始风险后，MFE Realization 是否仍为主瓶颈）                  ← 系统级结论
```

H2（机会成本）作为 H1 的伴随检验一起跑，避免"只看到增风险、忽略牺牲 MFE"。

---

## 7. 进入 Pre-Registration 的 Gate（本审查通过后）

须先冻结并写入 `EQ-1 Pre-Registration v0.1` 的项：
- **CP 定义（R8，待冻结：推荐 CP-D 摆点时间戳）**
- ETD 主/副指标（中性距离，方向由数据定）
- IAЕ = 10 根完整 post-entry M5（R1，已决）
- Primary = 原始 MFE/Giveback；MFE Realization 仅 Secondary（R2，已决）
- 双轨报告：USD 原始 + 风险标准化（R3，已决）
- 四假设各自主统计量 + Gate + 全报纪律（R4）
- ETD permutation 负对照（R6，固定种子/次数）
- 关联≠处方声明（R7）

---

## 8. 当前状态

```
H2-A FAILED（封存，E2 路线终止）
        ↓
EQ-1 方法学审查 v0.1（本文，审查通过，含 v0.1.1 调整）
        ↓ CP 冻结（待用户定）
EQ-1 Pre-Registration v0.1
        ↓
Code → Compile → Run → 解释
```

**可信度（本审查框架）：高，约 92%。** 唯一未定 = **CP 的具体操作定义（R8）**，须在预登记时由你拍板，不能由我替定。R1-R3 已按用户决策冻结。
