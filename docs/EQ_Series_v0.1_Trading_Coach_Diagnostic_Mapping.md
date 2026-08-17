# EQ Series v0.1 → Trading Coach Diagnostic Mapping

> 把"统计上发现了什么"翻译成"Coach 能观察什么、告诉你什么"。

- 文档类型：**Diagnostic Layer 设计预登记（翻译层）**
- 状态：**OBSERVATION / DESIGN**（设计态，仅描述，不跑新统计）
- 作者：research layer → diagnostic layer 桥接
- 日期：2026-08-15
- 关联研究契约：`RC-EQ1-PREREG-v0.1` / `RC-EQ1R-PREREG-v0.1` / `RC-EQ1M-PREREG-v0.1`
- 关联既有 Coach 设计：`docs/trading_coach/Trading_Coach_v0.2_设计.md`、`docs/trading_coach_prd_v0.1.md`

---

## 0. 边界（先读这段）

本文档是 **Research Layer 与 Diagnostic Layer 之间的单向翻译接口**，不是统计研究。

- **是**：把 EQ-1 / EQ-1R / EQ-1M 已验证的观察结论，压缩成 Coach 可长期使用的 4 个诊断维度。
- **不是**：新实验、新假设检验、参数优化、交易信号、执行规则。
- **防火墙**：只**消费** EQ 系列的"已验证观察（效应方向 + 量级）"；**不回写**任何研究参数；**不接入**生产（`run_daily` / `risk_guard` / `shadow`）。

严禁的链路：

```
一次相关性 → Coach 标签 → 交易规则     （绝不允许）
```

正确链路：

```
Research (EQ 已验证观察)
   │  validated observation（方向+量级）
   ▼
Diagnostic (Coach 4 维度，只读观测)
   │  repeated evidence（跨多笔/多样本一致）
   ▼
Potential Rule (Phase D，须独立样本重复验证)
```

---

## 1. 一句话目标

> **把"统计上发现了什么"，翻译成"Coach 能观察什么、告诉你什么"。**

Coach 不再问"这笔赚没赚钱？"，而开始问：

> **"这笔交易失败在哪里？"**

这与既有 `docs/trading_coach_prd_v0.1.md` 的核心问题一致——Coach 测量"认知 → 行为"的转化损耗；本文档提供**经研究验证的、可观测的执行质量输入**，不是新的 Coach 架构。

---

## 2. 证据底座（Diagnostic Layer 被允许使用的唯一事实源）

仅引用 EQ 系列已收口 OBSERVATION 的结论（方向 + 量级），并标注出处。未观测混杂（regime/vol）仍可能；仅允许"相容/关联"，严禁因果升级。

| 来源 | 契约 / 运行时间 | 已验证结论（方向 + 量级） | Coach 可观察 |
| --- | --- | --- | --- |
| EQ-1 H1 | `RC-EQ1-PREREG-v0.1` (2026-08-15T05:05:15Z) | ETD→IAE 弱正（ρ≈0.15） | **入场时机质量**有诊断信号 |
| EQ-1 H3 | 同上 | IAE→Giveback 强（ρ≈0.53） | **早期逆向暴露**是最有价值维度 |
| EQ-1R | `RC-EQ1R-PREREG-v0.1` (2026-08-15T14:12:44Z) | 关系不能简单归因于止损距离尺度（A raw ρ≈0.57 ≈ B norm ρ≈0.57；C 中等） | **IAE 与 Giveback 的关系不能简单由 initial risk 尺度解释**（非尺度假象；注意：尚未证明 IAE 独立于所有其他因素） |
| EQ-1M | `RC-EQ1M-PREREG-v0.1` (2026-08-15T15:08:36Z) | ETD→IAE→Giveback 与数据相容：indirect=0.0827，BCa CI `[0.0074, 0.157]` 排除 0，permutation pct=100%；c(总效应)≈−0.006 完全由 IAE 承载 | **Entry Timing 与 Exit Failure 间存在路径结构** |
| PnL / MFE | EQ-1R `PnL_sec_A`：IAE_usd→PnL_usd ρ=−0.40 | 方向判断与利润兑现存在差异 | **Opportunity vs Execution** |

---

## 3. 因果防火墙（铁律）

1. **单向**：Research → Diagnostic 单向。Diagnostic 不得回写研究冻结参数（`k=2 / W=48 / IAE_WIN=10 / seed / N_BOOT / N_PERM / 路径定义` 一律不可动）。
2. **重复证据才进 Rule**：Diagnostic → Rule 必须"跨多笔/多样本一致"串联，禁止单次相关性直推规则。
3. **只读观测**：Diagnostic 层不写生产决策链；出错归因若需回 Research，须独立预登记，不静默改。

---

## 4. v1 诊断四维（最小集，先不做十几个标签）

单笔交易拆解链：

```
Timing (D1)
   ↓
Early Exposure (D2)
   ↓
Opportunity (D3)
   ↓
Profit Capture (D4)
```

比单纯看 win/loss 有价值：把"是否赚钱"拆成"在哪一步漏了"。

> **v0.1 定调（关键）**：本版 Diagnostic Engine **只做"稳定测量"，不做"分类"**。四个维度一律输出**连续原始值 + 样本内描述性百分位**；`diagnostic_label = null`。`Early/Late`、`Low/Moderate/High`、`High/Partial/Low Capture` 等标签是**未来诊断词汇草图（归 Phase D 才冻结）**，v0.1 不输出。先把"研究变量 → 稳定测量"做干净，分类属下一层。

### D1 · Timing Quality（入场时机质量）
- **源变量**：`ETD`（Entry Timing Dislocation；继承 EQ-1 CP-D `k=2 / W=48`，即 entry 前最后已收盘 M5 bar 的相对位置）
- **回答**：你是在市场结构的什么位置进入的？
  - **描述标签（未来诊断词汇，v0.1 不输出）**：`Early` / `Neutral` / `Late`
  - **v0.1 引擎输出**：连续原始值 `etd_bars` + 样本内描述性百分位（`etd_percentile`，仅描述在样本中的分布位置，**无任何交易决策含义**）；`diagnostic_label = null`。
  - **依据**：EQ-1 H1 `ETD→IAE` 弱正（ρ≈0.15）→ 时机偏位会带入早期逆向暴露。
  - **护栏**：任何 cutoff / 标签化归 Phase D；v0.1 严禁从本样本优化 cutoff 或输出 High/Low 式决策标签。

### D2 · Early Adverse Exposure（早期逆向暴露）★ 旗舰维度
- **源变量**：`IAE`（entry 后 10 根 M5 最大逆向暴露；EQ-1R 已验证非止损距离尺度假象）
- **回答**：入场后，市场多快、多深地与你的交易假设发生冲突？
- **关键语义**：IAE **不是亏损金额**，而是"交易进入后，市场曾多大程度朝不利方向运动"。这使它天然适合进 Coach。
  - **描述标签（未来诊断词汇，v0.1 不输出）**：`Low` / `Moderate` / `High`（按 IAE 相对分布描述，非硬阈值）
  - **v0.1 引擎输出**：连续原始值 `IAE_usd` + 样本内描述性百分位（`iae_percentile`，仅描述分布位置，**无交易决策含义**）；`diagnostic_label = null`。
  - **依据**：EQ-1 H3（ρ≈0.53）+ EQ-1R（关系不能简单由 initial risk 尺度解释）+ EQ-1M（路径 `b=0.54`）。EQ 系列价值最高的维度。
- **护栏**：禁止把 IAE 重解释为"该笔亏了多少钱"；它是暴露/冲突度量。

### D3 · Opportunity（市场给过的机会）
- **源变量**：`MFE`（Max Favorable Excursion）
- **回答**：市场实际上有没有给过你赚钱机会？
- **描述**：
  - MFE 小 → 方向/时机本身可能就有问题
  - MFE 大 → 市场给过空间（问题更可能在执行/兑现）
- **依据**：PnL/MFE 联动（方向正确 ≠ 利润兑现）。

### D4 · Profit Capture / Exit Quality（利润兑现效率）
  - **源变量**：`Giveback`（post-MFE 逆向回吐）+ 派生 `Capture Efficiency = (MFE − Giveback) / MFE`
  - **回答**：市场给你的机会，你兑现了多少？
  - **数学边界（必锁）**：`capture_efficiency = (MFE − Giveback) / MFE`；当 `MFE <= 0` 时效率**无定义 → 置 null**（避免 0/0 或极小 MFE 导致极端不稳定）。**保留三原始字段** `MFE_usd` / `Giveback_usd` / `capture_efficiency`，不折叠为单一效率指标（低 Capture 与低 Opportunity 是不同问题，须分别可观测）。
  - **描述标签（未来诊断词汇，v0.1 不输出）**：`High Capture` / `Partial` / `Low Capture`
  - **v0.1 引擎输出**：连续原始值 `MFE_usd` / `Giveback_usd` / `capture_efficiency` + 样本内描述性百分位（`mfe_percentile` / `giveback_percentile` / `capture_percentile`，仅描述分布，**无决策含义**）；`diagnostic_label = null`。
  - **依据**：EQ-1M 路径终点 Giveback；EQ-1R `PnL_sec_A`（IAE 越大 P&L 越差，部分经 Giveback 中介）。
- **与既有 Coach 对齐**：本维度即 `docs/trading_coach/Trading_Coach_v0.2_设计.md` §四"利润泄漏率 Profit Leakage Ratio"的研究验证版输入——Coach 已有该指标概念，本文档仅提供其 EQ-validated 测量口径，不重定义 Coach 指标。

---

## 5. 单笔交易输出 schema（v0.1：测量态，非分类态）

v0.1 引擎**不输出 High / Low / Early / Late 式决策标签**；只输出连续原始测量 + 样本内描述性百分位。下列 labeled 形式是**未来 Diagnostic 词汇草图**（归 Phase D 才冻结），本版仅作示意。

**v0.1 实际输出（连续测量 + 描述性排名）**：
```
Trade #127
  D1 Timing
    etd_bars       = +3.2
    etd_percentile = 78%      # 仅描述在 210 笔样本中的位置，无决策含义
  D2 Exposure
    iae_usd        = 18.4
    iae_percentile = 84%
  D3 Opportunity
    mfe_usd        = 52.7
    mfe_percentile = 91%
  D4 Profit Capture
    giveback_usd      = 41.3
    capture_efficiency= 0.216    # (MFE-Giveback)/MFE；MFE<=0 时为 null
  diagnostic_label   = null      # v0.1 不分类
```

**未来词汇草图（Phase D 才考虑，本版不输出）**：
```
Trade #127
  Entry Timing ..... Late
  Early Exposure ... High
  Opportunity ...... High
  Profit Capture ... Low
  Diagnosis:
    市场曾提供明显有利空间（Opportunity=High），
    但交易在早期经历较大逆向暴露（Early Exposure=High），
    最终主要损失来自利润兑现效率不足（Profit Capture=Low）。
```

- 两类输出均**纯描述**；不出现任何买卖建议、不出现"应该…"，**不含交易信号**。
- v0.1 的 `diagnostic_label = null` 是刻意设计：把"研究变量 → 稳定测量"先做干净，分类归下一层。

---

## 6. Trading DNA（累计层）

单笔是第一层；累计到 100 / 200 / 500 笔后，聚合四维得到个人画像：

```
Trading DNA
   ├─ Entry Bias      (D1 分布：偏 Early / Neutral / Late)
   ├─ Exposure Pattern (D2 分布：Low / Moderate / High 占比)
   └─ Exit Profile    (D4 分布：High / Partial / Low Capture)
```

可能发现：

- "分析方向常对，但 Entry Timing 偏早"
- "Entry Timing 本身无大问题，但早期逆向暴露过大"
- "市场常给足够 MFE，但 Exit Efficiency 低"

**v0.1 DNA 仅做分布/描述统计**（N、ETD/IAE/MFE/Giveback/Capture 的 median、P25/P75、exit_reason 分布），**不做"你的最大问题是…"式结论**。任何行为定性须基于**重复证据**（多笔一致），不得由单笔下断言；N<100 仅作探索，不对外定性。

---

## 7. 研发阶段顺序（正式定稿）

```
Phase A 研究层（已完成）
  EQ-1 → EQ-1R → EQ-1M → Methodological closure

Phase B 诊断层（现在开始）
  EQ Series → Diagnostic Mapping → 最小诊断测量原型 → Observation

Phase C 长期 Coach（以后）
  真实交易 → 自动采集 → EQ Diagnostics → Trading DNA → 行为反馈

Phase D 规则层（最后）
  稳定发现 → 重复验证 → 独立样本验证 → 是否值得形成执行规则
```

---

## 8. 治理禁令（v0.1）

1. 不跑新统计实验（无 EQ-2 / EQ-3）。
2. 不定义 / 优化 cutoff（标签描述性；cutoff 归 Phase D）。
3. 不生成交易信号 / 执行规则。
4. 不接入生产（`run_daily` / `risk_guard` / `shadow` 一律不写）。
5. 不改任何 EQ 研究冻结参数（`k=2 / W=48 / IAE_WIN=10 / seed / N_BOOT / N_PERM / 路径定义`）。
6. 不因果升级（"IAE 导致 Giveback" 封死，仅"路径机制关联相容"）。
7. 不把单笔 / 单次相关性直推规则（防火墙）。
8. Diagnostic 层只读；回 Research 须独立预登记，不静默改。

---

## 9. 与既有 Trading Coach 的关系（桥接，非重定义）

- `docs/trading_coach_prd_v0.1.md`：Coach 测量"认知 → 行为"转化损耗。本文档提供其**执行质量输入**的研究验证口径。
- `docs/trading_coach/Trading_Coach_v0.2_设计.md`：交易状态机 + 盈利保护 + 利润泄漏率 + 执行分。本文档的 D4 对应其"利润泄漏率"，D1–D3 补足 EQ-validated 的时机/暴露/机会粒度。
- **本文档不改动 Coach 的状态机、硬 BLOCK、盈利保护模块或执行分公式**；它只定义"哪些维度由 EQ 研究背书、用哪个变量计算"。Coach 是否采纳、如何加权，归 Coach 自身设计（Phase C），不在本文档权限内。

---

## 10. 最小诊断测量原型实现说明（Phase B.1 · Trading Coach Diagnostic Engine v0.1）

- **命名**：`Trading Coach Diagnostic Engine v0.1`（Research-derived Trade Measurement Engine），**不是分类器**。文件建议 `backend/os_layers/coach_diagnostics.py`。
- **本质**：只读 EQ-1M 既有结果、逐笔产出 4 维**原始测量**的引擎；不分类、不判 High/Low。
- **v0.1 只做 5 件事**：
  1. **读** `eq1m_observation_v0_1.json` 的 `per_trade`（210 行）；**不重算 EQ**。
  2. **每笔生成四维原始诊断**：`etd_bars` / `iae_usd` / `mfe_usd` / `giveback_usd` / `capture_efficiency`（MFE<=0→null）。
  3. **生成诊断事实**：仅报告数值（如 `ETD=+3.2, IAE=$18.4, MFE=$52.7, Giveback=$41.3, Capture=21.6%`）；**只告诉发生了什么，不告诉该怎么办**。
  4. **结构化 Diagnosis（事实型）**：v0.1 仅产出 `opportunity_available = (MFE>0)`、`giveback_occurred = (Giveback>0)`、`giveback_to_mfe_ratio` 等事实描述，**不进入解释层**（如"你止盈太晚"）；任何布尔均为符号检查（sign-check），不含 cutoff。
  5. **Trading DNA（仅分布/描述）**：N、ETD/IAE/MFE/Giveback/Capture 的 median、P25/P75、exit_reason 分布；**不做定性结论**。
- **允许的**：连续原始值输出、样本内描述性百分位（明确标注无决策含义）、`diagnostic_label = null`、DNA 描述统计。
- **禁止的**：分类 / cutoff / 新统计 / 规则 / 生产链 / 解释性结论 / 回写研究参数。
- **输出**：每笔诊断 JSON + DNA 聚合摘要（观察态）。
- **触发条件**：用户批准 Phase B.1 后实现。

---

## 11. 决策 / 下一步

- 本文档为 **Diagnostic Layer v0.1 设计预登记（OBSERVATION / DESIGN）**。
- 立即下一步（待批准）：实现 §10 **最小诊断测量原型（Diagnostic Engine v0.1）**——先做"研究变量 → 稳定测量"，分类归下一层。
- 之后：Observation（跑既有 210 笔数据，产出首批诊断画像 + DNA 探索摘要）。
- 严禁 premature optimization；规则化（Phase D）须独立样本重复验证后才考虑。
- 这是整个系统从"研究发现"到"个人能力测量"的第一次真正连接。
