# EQ-1M · IAE Pathway / Mediation-Shaped Association — Specification Review v0.1

> 配套 `docs/EQ1_PreRegistration_v0.1.md`（EQ-1 v0.1，已 OBSERVATION）、`docs/EQ1R_Risk_Normalized_Robustness_Specification_Review_v0.1.md`（EQ-1R v0.1，已 OBSERVATION）。
> 本文只解决 **「ETD → IAE → Giveback 是否构成一条可识别的路径机制关联」** 的规格审查。
> **不写代码、不跑 210 笔数据、不对任何参数做数据驱动调优。**
> 状态：经用户 2026-08-15 枢轴决策批准进入「路径机制研究」（可信度中高 ~85%），明确**先于**参数敏感性 v0.2 与 H4 深挖。本文为 Spec Review，待用户审阅后进入 `EQ-1M Pre-Registration v0.1`，再 `--check` → Code → Compile → Gate 0 → Run。**已于 2026-08-15T15:06 执行（`eq1m_observation_v0_1.json`，decision=OBSERVATION），状态升级为 EXECUTED · OBSERVATION · ARCHIVED；原规格设计未改。**

---

## 0. 纪律红线（本文适用）

1. **禁止数据窥探**：所有路径定义、统计方法、窗口边界一律来自方法学推理与 EQ-1 / EQ-1R 已暴露的证据，**不看 210 笔结果反选**。
2. **路径机制关联，非因果中介**：本研究命名为 **IAE Pathway / Mediation-Shaped Association Study（IAE 路径机制关联研究）**；数据是观察性单级（每笔交易=一个单元，非随机实验），**严禁**任何「IAE 是 ETD 导致退出失败的中介变量 / IAE 导致 Giveback」的因果措辞。
3. **不碰 EQ-1 / EQ-1R 冻结结果**：`k=2` / `W=48` / `IAE_WIN=10` / CP-D / ETD / IAE / Giveback 定义全部继承，不可改。
4. **先规格、后预登记、后跑**：本文件仅 Spec Review；下一阶段才写 Pre-Registration + 契约 + 代码。
5. **不派生交易规则**：首跑只描述路径关联结构，不产出任何 Entry/Exit 信号或参数。

---

## 1. 研究问题与三层前置结构

核心研究问题：

> Entry 相对 CP 的时间位置 **ETD**，是否通过早期逆向暴露 **IAE**，进一步与后续退出失败 **Giveback** 形成一条可识别的路径？
> 即检验：**ETD 与 Giveback 之间是否存在与 IAE 相容的间接关联路径。**

路径：

```
ETD
 │  (a: ETD → IAE)
 ▼
IAE
 │  (b: IAE → Giveback, 控制 ETD)
 ▼
Giveback
```

其中 `Indirect Effect = a × b`，`c' = ETD → Giveback（控制 IAE）`，`c = ETD → Giveback（总效应，不控制）`。

**为何现在可以做——三层 prerequisite（来自前两轮，非本研新证据）：**

| 层级 | 证据来源 | 结果 | 含义 |
| --- | --- | --- | --- |
| 第一层：IAE 不是随机噪声 | EQ-1 H1 | `ρ(ETD→IAE) = 0.153` | 弱正，但有方向性（真实存在一定方向） |
| 第二层：IAE 与退出失败高度相关 | EQ-1 H3 / EQ-1R A·B | `ρ=0.532` / `0.5705` / `0.5711` | 强关系，且标准化后几乎不衰减 |
| 第三层：尺度解释吃不掉该关系 | EQ-1R C1·C2 | `initial_risk→IAE=0.3533`、`→Giveback=0.235` | 有尺度影响，但不足以简单解释全部 |

> 关键读数：**A ≈ B（而非 B 消失）** → H3 的 ~0.53 相关很难仅解释成「止损距离大 → IAE 大 → Giveback 大」的机械尺度关系。这把研究推到下一层：**ETD → IAE → Giveback 是一条合理的下一步科学问题**。

> **克制声明（沿用 EQ-1R 边界）**：上述证据只证明 H3 具有较强的稳健性，**不证明 IAE 是 Giveback 的因果原因**。EQ-1M 的定位是「路径机制关联」，不是「因果中介检验」。

---

## 2. 样本边界（已冻结原则）

- **Primary 样本**：继承 EQ-1 v0.1 的 210 笔全样本，剔除 `no-CP` 排除交易（CP-D `k=2/W=48`，无合格 CP 则排除并报告 exclusion_rate，不设 fallback）。原因：IAE（前 10 根）与 Giveback（全程）均对全部交易有定义，**不依赖 `sl_trigger_price`**，故 EQ-1M 可用全样本（比 EQ-1R 的 142 更有统计功效）。
- **敏感性分层（非选择规则，仅诊断）**：
  - `SL 子集（142 笔）`：`sl_trigger_price` 非空（与 EQ-1R 对齐）。
  - `non-SL 子集（68 笔）`：无预设计止损。
  - 两者仅作描述性分层报告，不据此筛选 Primary 或外推结论。
- **不补造** 68 笔的 initial_risk（若某敏感性需要 R 标准化，则仅在该分层内做并明确标注缺口）。
- **结构异质性诊断（必报）**：SL 交易的 `Giveback ≈ MFE`（exit 在 SL，有利部分≈0），non-SL 交易的 `Giveback = MFE − 已实现有利部分`；两者 `Giveback` 的经济含义不同。必须在结果中报告 `mean/median(Giveback)` by `exit_reason`，作为异质性边界，不掩盖。

---

## 3. 变量与时间顺序（关键审计：防止窗口重叠造成解释污染）

### 3.1 精确窗口（继承自 `entry_quality_eq1.py`）

- `ETD`：仅由 `entry_time` 之前已收盘 bar 计算（`bisect_right(times, entry_unix−300)` 纪律，杜绝 micro look-ahead）。**早于** entry。
- `IAE`：`entry 后 10 根完整 M5（post[:IAE_WIN], IAE_WIN=10）的最大逆向 excursion（USD）`。**窗口 = [entry, entry+10 根]**（约前 50 分钟）。
- `MFE`：`entry 后全程 post bar 的极值`（含 exit_price）。**窗口 = [entry, exit]**。
- `Giveback = max(0, MFE − max(0, fav_exit))`：从 MFE 回吐到 exit 的幅度。**窗口 = [entry, exit]**。

### 3.2 污染机制（必须冻结识别）

`IAE` 在**前 10 根**测量，而 `MFE`/`Giveback` 在**全程**测量。当一笔交易的 `MFE` 峰值出现在**前 10 根之内**（或 exit 发生在前 10 根之内），则：

- `IAE`（前 10 根最大逆向）与该笔 `Giveback`（MFE − fav_exit，其中 MFE/fav_exit 也落在前 10 根）**由同一段局部价格路径计算**；
- 两者都相对 `entry` 定价 → 在此类「短交易」中，`IAE` 与 `Giveback` 可因**窗口重叠**而机械耦合，并非真实路径机制。

这是 EQ-1M 开始前**最后一个真正值得做的方法学审计点**。

### 3.3 冻结的缓解方案（四件套）

1. **`overlap_rate` 诊断（必报）**：报告 `MFE 峰值索引 < IAE_WIN(10)` 的交易占比，以及 `exit 在 IAE_WIN 内` 的交易占比。该子群体即窗口重叠 / 污染风险区。
2. **Primary 路径（全样本，连续性）**：在全 eligible 样本上跑完整 mediation（复刻 EQ-1 H3 上下文），作为主读数。
3. **敏感性层 A（窗口不重叠）**：剔除 `duration ≤ IAE_WIN` 的短交易（此时 IAE 窗口与 MFE/Giveback 窗口在结构上可分离），重跑 indirect effect，检查路径是否仍然存在。若 Primary 显著而层 A 消失 → 提示关系可能是窗口重叠假象；若两层均存在 → 路径更可信。
4. **敏感性层 B（Giveback 口径变体，标注偏离）**：额外计算 `Giveback_late`——以 **IAE 窗口之后**的 `MFE`（post-IAE-window 有利峰值）为基准的回吐。此定义**偏离 EQ-1 原 Giveback**（原用全程 MFE），仅作稳健性变体，明确标注，不替代 Primary。

> 三条路径的因果时序本身无反向泄漏：`ETD` 早于 entry；`IAE` 为前 10 根（早）；`Giveback` 含后期（晚）。仅当 MFE/exit 落回前 10 根时产生重叠，由 `overlap_rate` + 层 A 处理。

---

## 4. 路径模型定义（a / b / c / c' + indirect；术语冻结）

| 符号 | 定义 | 角色 |
| --- | --- | --- |
| `a` | `ETD → IAE`（控制无） | 路径 a（前因→中介） |
| `b` | `IAE → Giveback`（控制 ETD） | 路径 b（中介→结果，部分相关/回归系数） |
| `c` | `ETD → Giveback`（不控制 IAE） | 总效应 |
| `c'` | `ETD → Giveback`（控制 IAE） | 直接效应 |
| `Indirect` | `a × b` | 间接效应（核心） |
| `PM` | `(c − c') / c`（比例中介） | 效应量；`&#124;c&#124;` 过小时不定义（见 §5） |

- **中介变量锁定 = `IAE`**（前 10 根逆向暴露），不替换为 MFE/MAE。
- **术语冻结（中英文并列）**：
  - 英文：**Pathway / Mediation-Shaped Association Study**
  - 中文：**IAE 路径机制关联研究**
  - 禁用：**「IAE mediates…」/「IAE 是中介变量」/「IAE 导致 Giveback」/「改变 ETD 经由 IAE 改变 Giveback」**。
  - 允许：**「数据与 ETD→IAE→Giveback 路径相容」/「间接关联路径存在（方向为正）」**。

---

## 5. 统计方法（9 项冻结指标 + bootstrap / permutation）

**主统计量（两套并行，冻结）：**

- **Primary（标准 mediation）**：OLS 乘积系数 bootstrap。
  - `a` = `IAE ~ ETD` 系数；`b` = `Giveback ~ IAE + ETD` 系数；`c` = `Giveback ~ ETD`；`c'` = `Giveback ~ IAE + ETD`（直接）。
  - 报告标准化系数（z-score 化后），使 `a×b` 跨变量可比。
- **Secondary（Spearman 连续性）**：`a = ρ(ETD, IAE)`、`b = partial ρ(IAE, Giveback &#124; ETD)`、`Indirect = a × b`，与 EQ-1 的 Spearman 传统对齐，作交叉验证。

**9 项冻结输出指标：**

1. `indirect_effect`（a×b，Primary 标准化 + Secondary Spearman）
2. `indirect_CI`（bootstrap BCa 95%）
3. `direct_effect`（c'）
4. `total_effect`（c）
5. `a_path`（ETD→IAE）
6. `b_path`（IAE→Giveback &#124; ETD）
7. `c'_path`（ETD→Giveback &#124; IAE，等同 direct）
8. `effect_size`（PM = (c−c')/c；`&#124;c&#124;` 低于 floor 时 PM 不定义，改报标准化 indirect + 标注「总效应≈0，比例中介不适用」）
9. `permutation / bootstrap diagnostic`（见下）

**Bootstrap 参数（冻结）：**

- `N_BOOT = 10000`，`bootstrap_seed` 待 Pre-Registration 冻结（建议 `20260817`，与 EQ-1 `20260815` / EQ-1R `20260816` 独立 provenance；仅为可复现性，不随结果更换）。
- 区间：**Bias-Corrected and Accelerated (BCa)**。
- 重采样单元 = 交易（单级 observation），有放回。

**Permutation null（诊断项，非 Hard Gate，冻结）：**

- 固定 `(ETD, Giveback)` 配对，对 `IAE` 向量做**独立保边洗牌**（打破 a、b 两条链接），重算 `a×b`。
- `N_PERM = 2000`，seed 同上（独立随机化，`&#124;` 仅 reproducibility）。
- 输出 `empirical_percentile`（observed indirect 在 null 中的分位）；仅标 caveat，不据此复活/否定结论（沿用 EQ-1/EQ-1R 纪律）。

**功效与成功标准（关键，冻结）：**

- `a ≈ 0.153`、`b ≈ 0.53` → `a×b ≈ 0.08`（粗略 Spearman 估算）；基于单级 210 样本，bootstrap CI **很可能包含 0**。
- **不设置「mediation 必须显著」为成功标准**。Pre-Registration 冻结接受三种结果：
  - `indirect > 0`（CI 排除 0）→ 与正向路径机制相容；
  - `indirect ≈ 0`（CI 含 0）→ 与 null 间接效应相容，路径不可与随机区分；
  - `indirect < 0` → 与负向路径相容。
- 三者均允许，不 cherry-pick；结论语言严格受 §6 因果边界约束。

---

## 6. 因果边界（观察性 mediation 的准确措辞与红线）

1. 数据为**观察性、单级、横截面式**（每笔交易一个观测，非时间序列内中介，非随机实验）。
2. `a×b` 显著 ≠ 因果中介；未观测混杂（如波动率/趋势 regime 同时影响 ETD 定位质量与 IAE/Giveback）可能存在。
3. 唯一支撑方向性的证据是**交易内时序**：`ETD` 早于 entry、`IAE` 为前 10 根（早）、`Giveback` 含后期（晚）——这支持「方向」声明，但**不证明因果**。
4. 允许的结论范式（冻结）：
   > 「数据与 ETD→IAE→Giveback 的**路径机制关联**相容；在控制 ETD 后，IAE 对 Giveback 仍具独立关联，且 ETD→Giveback 总效应弱/≈0，模式与 mediation-shaped association 一致。」
5. 禁用的结论范式（冻结）：
   > 「IAE 是 ETD 导致退出失败的中介」「IAE 造成 Giveback」「应据此调整 ETD 以改进退出」。
6. 未观测混杂的敏感性分析（如 regime 控制）**归 v0.2**，不在 v0.1 引入新预测子。

---

## 7. 选择偏差与异质性诊断（非选择规则）

| 诊断项 | 做法 | 定位 |
| --- | --- | --- |
| `Giveback` by `exit_reason` | 报 SL / non-SL 的 mean/median | 暴露结构异质性，不掩盖 |
| `overlap_rate` | MFE 峰值 / exit 落在 IAE_WIN 内占比 | 窗口污染风险区（§3.3） |
| 敏感性层 A（剔短交易） | duration > IAE_WIN 重跑 | 窗口不重叠验证 |
| 敏感性层 B（142 / 68 分层） | 同 EQ-1R Selection Diagnostic | 描述性，不筛选 |

严禁：「142 更稳定所以只研究 SL」「短交易污染所以删掉」等结果驱动的样本重定义。诊断只暴露边界。

---

## 8. 禁止事项（10 项冻结）

1. 仅使用继承的 210 全样本（剔除 no-CP），不反选。
2. 不补造 68 笔 initial_risk（R 标准化仅在该分层内做并标注缺口）。
3. 不把 SL exit 本身当解释条件去解释 Giveback。
4. 报告 SL/non-SL 与 overlap_rate 异质性，但**不据此筛选样本**。
5. 中介变量只用 `IAE`（前 10 根）；不替换为 MFE/MAE。
6. 不改变 `k=2` / `W=48` / `IAE_WIN=10`（继承 EQ-1）。
7. 不声称因果中介（受 §6 措辞约束）。
8. 不进行参数敏感性（`k∈{1,2,3}` 等归 v0.2）。
9. 不深挖 H4（ETD+initial_risk exploratory，已降级）。
10. 不寻找新的 cutoff / 阈值，不派生交易规则。

---

## 9. 已知局限 / 方向性偏差（v0.2 处理）

- 单级观察数据，未观测混杂（volatility/trend regime）无法在 v0.1 控制；regime 敏感性归 v0.2。
- `Giveback` 在 SL / non-SL 间结构含义不同（§2、§7），全样本合并可能稀释信号；分层已作诊断但未解决。
- 窗口重叠（§3）仅由 `overlap_rate` + 层 A 缓解，未完全消除（短交易不可避免共享局部路径）。
- 功效可能不足（a×b≈0.08），CI 含 0 概率高 → 结论以「相容/不可区分」为主，不追求显著。
- `Giveback_late` 变体偏离 EQ-1 原定义，仅稳健性参考。

---

## 10. 可复现性 / ex-ante

- 所有路径定义、窗口、统计量、bootstrap/permutation 参数确定，无优化器（bootstrap/permutation 除外，seed 固定）。
- 继承 EQ-1 / EQ-1R 的 ex-ante 纪律（CP/ETD/IAE/Giveback 已由 EQ-1 冻结，不重算）。
- 同一种子数据上结果逐次一致，可被第三方独立复现。

---

## 11. 冻结清单（已冻结）

| 参数 / 决策 | 冻结值 | 依据 | 状态 |
| --- | --- | --- | --- |
| 命名 | IAE Pathway / Mediation-Shaped Association Study（IAE 路径机制关联研究） | 观察性，非因果中介 | ✅ 已冻结 |
| 样本 | 210 全样本（剔除 no-CP）；SL/non-SL 为敏感性分层 | IAE/Giveback 不依赖 sl_trigger_price | ✅ 已冻结 |
| 中介变量 | `IAE`（前 10 根逆向暴露） | 继承 EQ-1 R1 | ✅ 已冻结 |
| k / W / IAE_WIN | 2 / 48 / 10 | 继承 EQ-1，不可改 | ✅ 已冻结 |
| 路径模型 | a=ETD→IAE；b=IAE→Giveback&#124;ETD；c=ETD→Giveback；c'=ETD→Giveback&#124;IAE；Indirect=a×b | 标准中介分解 | ✅ 已冻结 |
| 主统计 | OLS 乘积系数 bootstrap（标准化）+ Spearman partial 交叉 | 双轨并行 | ✅ 已冻结 |
| 9 指标 | indirect / indirect_CI / direct / total / a / b / c' / PM / perm_diag | 用户指定全冻结 | ✅ 已冻结 |
| N_BOOT / 区间 | 10000 / BCa | 标准 | ✅ 已冻结 |
| bootstrap_seed | 建议 `20260817`（PR 冻结；仅 reproducibility） | 与 EQ-1/EQ-1R 独立 | ✅ 待 PR |
| Permutation | N=2000，洗牌 IAE，仅诊断 | 打破 a·b 链接 | ✅ 已冻结 |
| 成功标准 | 接受 indirect 正/零/负三种；不要求显著 | 功效不足，防结果驱动 | ✅ 已冻结 |
| 窗口重叠缓解 | overlap_rate + 层 A(剔短交易) + 层 B(Giveback_late 变体) | §3.3 审计 | ✅ 已冻结 |
| 因果边界 | 禁「IAE 是中介/导致」；允「路径机制相容」 | §6 | ✅ 已冻结 |
| 参数敏感性 / H4 | 禁止（归 v0.2） | 防拉回参数优化 | ✅ 已冻结 |

---

## 12. 下一步

EQ-1M Specification Review v0.1 已完成，待用户审阅。下一步：写 `EQ-1M Pre-Registration v0.1`（对齐 RC 结构，含 `frozen_gates` + `frozen_tokens` + `eq1m_result=PENDING`，独立字段不复用 `eq1_result`/`eq1r_result`）→ `--check` → Code（纯 stdlib Observation-only）→ Compile → Gate 0 → Run。

全程零数据窥探；任何增强（regime 控制、参数敏感性、H4）归入 v0.2 独立预登记。

---

## 13. EQ-1M 最终冻结协议（逐字，供 Pre-Registration 引用）

> **EQ-1M · IAE Pathway / Mediation-Shaped Association Study（IAE 路径机制关联研究）**
>
> 在 210 全样本（剔除 no-CP，CP-D k=2/W=48）中检验路径 ETD → IAE → Giveback：
>
> - `a = ETD → IAE`；`b = IAE → Giveback（控制 ETD）`；`c = ETD → Giveback（总）`；`c' = ETD → Giveback（控制 IAE）`；`Indirect = a × b`。
> - 中介变量 = `IAE`（entry 后 10 根最大逆向 excursion，USD，继承 EQ-1 R1）。
> - 主统计：OLS 乘积系数 bootstrap（标准化系数，N_BOOT=10000，BCa 95% CI）+ Spearman partial 交叉验证。
> - 9 项冻结指标：indirect_effect / indirect_CI / direct_effect / total_effect / a_path / b_path / c'_path / effect_size(PM) / permutation_diagnostic。
> - Permutation null（N=2000，独立洗牌 IAE 打破 a·b 链接，仅诊断，非 Hard Gate）。
> - 窗口重叠缓解：报告 overlap_rate（MFE 峰值/exit 落 IAE_WIN 内占比）；敏感性层 A 剔 duration≤IAE_WIN 短交易重跑；层 B 用 Giveback_late（post-IAE-window MFE 口径，标注偏离 EQ-1）。
> - 成功标准：接受 indirect 正/零/负三种结果，不要求显著（a×b≈0.08 功效可能不足）。
> - 因果边界：观察性单级数据，严禁「IAE 是中介/导致 Giveback」；仅允许「数据与 ETD→IAE→Giveback 路径机制关联相容」。未观测混杂敏感性归 v0.2。
> - SL/non-SL 为敏感性分层（Selection Diagnostic，非 Rule）；不补造 68 笔 initial_risk。
> - 禁止：改 k/W/IAE_WIN、参数敏感性、H4 深挖、新 cutoff、因果措辞、派生交易规则。
> - 结论边界：仅描述路径关联结构，不产出交易信号。

---

*本文档为 EQ-1M 规格审查，冻结值以 §11 / §13 为准。正式运行以 `EQ-1M Pre-Registration v0.1` 的 Gate 0 校验为准。*
