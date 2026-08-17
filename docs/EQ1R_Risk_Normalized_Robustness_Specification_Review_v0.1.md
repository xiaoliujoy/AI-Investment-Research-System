# EQ-1R · Risk-Normalized Robustness Review — Specification Review v0.1

> 配套 `docs/EQ1_PreRegistration_v0.1.md`（EQ-1 v0.1，已 OBSERVATION）与 `docs/EQ1_Methodology_Review_v0.1.1.md`。
> 本文只解决 **「IAE→Giveback 强关系是否由 initial risk / stop distance 这个尺度变量制造」** 的稳健性检验规格。
> **不写代码、不跑 142 笔数据、不对任何参数做数据驱动调优。**
> 状态：经用户 2026-08-15 审阅，4 项方法学修正已落盘（seed=`20260816` 冻结 / `P&L_norm`=Secondary economic diagnostic / B 收紧为风险尺度敏感性检查且 A·B·C 联合解释 / Fisher-z 标为 approximation）；**具备正式冻结条件**，进入 `EQ-1R Pre-Registration v0.1`，再 Code → Compile → Gate 0 → Run。

---

## 0. 纪律红线（本文适用）

1. **禁止数据窥探**：本研究的任何设计决策（变量定义、标准化方式、诊断分组）一律来自方法学推理与 EQ-1 v0.1 已暴露的问题，**不看 142 笔结果反选**。
2. **只做稳健性检查，不做新发现检验**：EQ-1R 的定位是检验 H3（IAE_USD→Giveback_USD, ρ=0.532）是否由尺度变量混淆；结论边界天然只覆盖 SL 子群体，不声称新发现。
3. **不碰 EQ-1 v0.1 冻结结果**：`k=2` / `W=48` / CP-D / ETD 定义全部继承，不可改。
4. **不进入 mediation**：ETD→IAE→Giveback 的中介检验属另一契约，本研严禁。
5. **不补造数据**：68 笔无 `sl_trigger_price` 的交易，不反向推断 / 补造 initial_risk。

---

## 1. 研究问题与三层结构

核心研究问题：

> 在有可观测 initial risk 的 142 笔 SL 子样本中，IAE 与 Giveback 的关系，在风险标准化后是否仍然存在？

本质：EQ-1R **不是重新证明 H3**，而是检验 H3 是否可能被 initial risk / stop distance 这一尺度变量制造。

| 层次        | 要回答的问题                                     | 地位                      |
| --------- | ------------------------------------------ | ----------------------- |
| H3 原始结果   | `IAE_USD → Giveback_USD`                   | 已观察到 ρ=0.532（EQ-1 v0.1） |
| EQ-1R（核心） | `IAE/initial_risk → Giveback/initial_risk` | **风险尺度敏感性检查（联合证据之一）**     |
| 142 vs 68 | SL 子样本是否明显不同                               | **选择偏差诊断（非筛选规则）**       |

---

## 2. 样本边界（已冻结原则）

- 仅使用 210 笔中 `sl_trigger_price` 有效（非空）的 **142 笔**（恰为 `exit_reason=sl`）。
- 其余 68 笔无预设计止损 → 无 initial_risk → 不参与 EQ-1R 的相关性检验。
- **不补造** 68 笔的 initial_risk。
- **不把「SL exit」本身当成解释 Giveback 的研究条件**：样本由数据可得性（是否有 sl_trigger_price）定义，exit_reason=sl 不作为预测子 / 调节子进入模型。

---

## 3. initial_risk 定义（锁死措辞）

```
initial_risk = |entry_price − sl_trigger_price| × CONTRACT_MULT(=100) × volume
```

- 经济含义：**planned/observed stop-distance risk proxy**（计划 / 观测止损距离风险代理），**不是严格意义上的「交易真实风险」**。
- 此措辞从本文件起锁死，后续文档沿用，避免把「止损距离」误称为「真实风险」。
- 仅 142 笔有值；SL 子集才做 R 标准化，明确标注数据缺口（非参数修改，沿用 EQ-1 v0.1 的标注）。

---

## 4. raw / normalized 双轨（已冻结）

继承 EQ-1 v0.1 的 per-trade 变量定义（不重定义）：

- `IAE_USD` = entry 后 10 根最大逆向 excursion × mult
- `Giveback_USD` = `max(0, MFE_usd − 退出有利部分)`（退出质量，具体口径见 EQ-1 Pre-Registration）
- `P&L_USD` = 该笔盈亏（USD）
- `MFE_USD` = entry 后最大有利 excursion × mult

核心标准化变量：

| 变量              | 定义                            | 角色                                       |
| --------------- | ----------------------------- | ---------------------------------------- |
| `IAE_norm`      | `IAE_USD / initial_risk`      | Primary diagnostic（核心）                     |
| `Giveback_norm` | `Giveback_USD / initial_risk` | Primary diagnostic（核心）                     |
| `PnL_norm`      | `P&L_USD / initial_risk`      | **Secondary economic diagnostic（非假设定义终点）** |

**保留 raw USD 结果**，形成 raw vs normalized 双轨并陈，不偏废任何一方。

`P&L_norm` 仅作 **Secondary economic diagnostic**，帮助判断经济意义；它**不能改变 EQ-1R 的研究定位**，更不得派生新研究问题（例如「IAE_norm 与 PnL_norm 关系更强 → IAE 是更好预测变量」属独立预登记范畴）。

---

## 5. 三组证据设计（共同分母问题解法）

**共同分母问题**：`X = IAE/R`，`Y = Giveback/R` 共享分母 `R`，若 `R` 自身变化很大，可能制造 / 放大相关性。因此即使 `corr(IAE, Giveback)` 很强，共同除以 `R` 后仍可能产生机械相关。

因此 EQ-1R 设计成三组证据，而非单一检验：

**A. 原始尺度（H3 replication，Primary diagnostic）**

```
IAE_USD → Giveback_USD
```

预期复刻 ρ≈0.532，作为基准。

**B. 风险尺度敏感性检查（Normalized，Primary diagnostic）**

```
IAE_norm → Giveback_norm
```

报告去除 stop-distance 尺度后，H3 关系是否仍存在。**B 不是「标准化后的最终稳健性证明」**，它只提供「跨风险尺度保持」这一维证据。

**C. 分母敏感性诊断**

```
initial_risk → IAE_USD
initial_risk → Giveback_USD
```

并报告 `corr(initial_risk, IAE_USD)` 与 `corr(initial_risk, Giveback_USD)`。

**解释逻辑（A/B/C 联合，不单独决定结论）**：

- 真正的判断由 **A、B、C 三者共同决定 H3 是否具有「非纯尺度解释」的证据**，而非「B 显著/强，所以 H3 稳健」。
- 若 **B ≈ A（仍强）** 且 **C 中 initial_risk 与 IAE/Giveback 关系弱** → 支持「IAE→Giveback 非 stop-distance 尺度混淆所致」。
- 若 **B 明显弱于 A** 或 **C 中 initial_risk 与两者强相关** → 该关系可能由「大止损交易天然拥有更大 IAE 与更大 Giveback」制造，IAE 未必是独立的重要变量。

这是 EQ-1R 最核心的方法学价值：区分

> 「IAE 真是后续退出失败的重要变量」

与

> 「大止损交易天然更大 IAE 和更大 Giveback」。

---

## 6. 142 vs 68 选择偏差诊断（Selection Diagnostic，非 Selection Rule）

比较以下变量在 142 SL 与 68 non-SL 间的描述性差异（均值 / 中位数 / 分布），**仅作诊断报告，不据此筛选样本**：

| 变量                  | 142 SL | 68 non-SL |
| ------------------- | ------ | --------- |
| Long/Short 占比       | 描述     | 描述        |
| ETD（bars / minutes） | 描述     | 描述        |
| P&L_USD             | 描述     | 描述        |
| MFE_USD             | 描述     | 描述        |
| IAE_USD             | 描述     | 描述        |
| Exit reason 分布      | 描述     | 描述        |

**严禁出现**：

> 「142 笔更稳定，所以以后只研究 SL」

这类结果驱动的样本定义。诊断目的只是暴露选择偏差边界；结论只能声称覆盖 SL 子群体，**不可外推全部 210**。

---

## 7. 检验方法（待 Pre-Registration 冻结细节）

- **主统计量**：Spearman 秩相关（继承 EQ-1 v0.1 Primary），因变量连续且分布未知。
- **置信区间**：Fisher-z CI，明确标注为 Spearman 的 **descriptive approximation**（非严格精确 CI；CI 方法敏感性 / bootstrap 归 v0.2，不引入新随机机制）。
- **三组证据 A/B/C 全报告**，不藏不显著的那组（多重比较透明）。
- **permutation null（诊断项，非硬 Gate）**：固定边际分布、保边洗牌、`stat = max|assoc| over A/B/C`、`N=2000`、固定 seed = `20260816`（与 EQ-1 的 `20260815` 区分，独立随机化 provenance）。**seed 仅为可复现性参数，无任何统计意义，不得根据结果更换**。已冻结。
  - 仅作 borderline 诊断，不据此复活 / 否定任何结论。
- 不追求 p<0.05（小样本 142，沿用 EQ-1 的「方向性 + 效应量 + CI 是否含 1」口径）。

---

## 8. 禁止事项（10 项冻结）

1. 只使用已有 142 笔 `sl_trigger_price` 有效交易。
2. 不补造 68 笔 initial_risk。
3. 不把 SL exit 本身当成研究条件去解释 Giveback。
4. 报告 142 vs 68 描述性差异，但**不据此筛选样本**。
5. 核心变量只用 `IAE_USD`/`Giveback_USD`（A）与 `IAE_norm`/`Giveback_norm`（B）；`PnL_norm` 仅作 Secondary economic diagnostic。
6. 同时保留 raw USD 结果，形成 raw vs normalized 双轨。
7. 不改变 `k=2` / `W=48`（继承 EQ-1 v0.1）。
8. 不进行 mediation。
9. 不进行参数敏感性。
10. 不寻找新的 cutoff / 阈值。

---

## 9. 已知局限 / 方向性偏差（v0.2 处理）

- `initial_risk` 是 stop-distance proxy，非真实风险；若用户实际风险承受由其他因素（波动率、账户尺度）定义，本标准化只控制「止损距离」维度。
- 142 子集代表性未知：若与 68 存在系统差异，结论只覆盖 SL 子群体。
- 共同分母问题只能靠 C 组诊断缓解，不能完全消除（`R` 与 `IAE` 可能本身相关）。
- 不引入 trend/volatility filter、不做多摆点、不加任何「更聪明」的标准化 → 进 v0.2 独立预登记。

---

## 10. 可复现性 / ex-ante

- 所有变量定义确定，无优化器、无随机性（permutation 除外，seed 固定）。
- 继承 EQ-1 v0.1 的 ex-ante 纪律（CP/ETD 已由 EQ-1 冻结，不重算）。
- 同一种子数据上结果逐次一致，可被第三方独立复现。

---

## 11. 冻结清单（已冻结）

| 参数 / 决策           | 冻结值                                       | 依据                        | 状态       |
| ----------------- | ----------------------------------------- | ------------------------- | -------- |
| 样本                | 142 笔 SL（`sl_trigger_price` 非空）           | 数据可得性定义子集                 | ✅ 已冻结    |
| initial_risk 定义   | &#124;entry−SL&#124; × 100 × volume          | 锁死措辞 = stop-distance risk proxy | ✅ 已冻结    |
| 核心变量（Primary）      | `IAE_USD→Giveback_USD`（A）与 `IAE_norm→Giveback_norm`（B） | raw vs normalized 双轨         | ✅ 已冻结    |
| `PnL_norm`        | Secondary economic diagnostic（非假设定义终点）       | 仅经济意义判断，不派生新问题             | ✅ 已冻结    |
| 三组证据             | A raw / B normalized / C 分母诊断             | **联合解释，不单独决定结论**；解共同分母问题      | ✅ 已冻结    |
| 142/68            | Selection Diagnostic，非 Rule               | 暴露偏差不筛选                   | ✅ 已冻结    |
| 主统计量              | Spearman ρ                                | 继承 EQ-1 Primary             | ✅ 已冻结    |
| CI                | Fisher-z approximation（descriptive，标注近似）      | Spearman 无严格闭式 CI；bootstrap 敏感性归 v0.2 | ✅ 已冻结    |
| k / W             | 2 / 48                                    | 继承 EQ-1，不可改                | ✅ 已冻结    |
| mediation         | 禁止                                        | 属另一契约                     | ✅ 已冻结    |
| 参数敏感性             | 禁止                                        | 归 v0.2                    | ✅ 已冻结    |
| 新 cutoff          | 禁止                                        | 不搜阈值                      | ✅ 已冻结    |
| permutation seed      | `20260816`                                | 与 EQ-1 独立 provenance；仅 reproducibility，不随结果更换 | ✅ 已冻结    |

---

## 12. 下一步

EQ-1R Specification Review v0.1 已完成，经用户审阅具备冻结条件。下一步：写 `EQ-1R Pre-Registration v0.1`（对齐 RC 结构，含 `frozen_gates` + `frozen_tokens` + `eq1r_result=PENDING`）→ `--check` → Code（纯 stdlib Observation-only）→ Compile → Gate 0 → Run。

全程零数据窥探；任何增强归入 v0.2 独立预登记。

---

## 13. EQ-1R 最终冻结协议（逐字，供 Pre-Registration 引用）

> **EQ-1R · Risk-Normalized Robustness Review**
>
> 在 142 笔 SL 子集（`sl_trigger_price` 非空）中检验：
>
> - H3 原始（Primary diagnostic）：`IAE_USD → Giveback_USD`（复刻）
> - 风险尺度敏感性检查 B（Primary diagnostic）：`IAE_norm → Giveback_norm`，其中 `IAE_norm = IAE_USD / initial_risk`，`initial_risk = |entry − sl| × 100 × volume`（stop-distance risk proxy，非真实风险）。B 不是标准化后的最终稳健性证明。
> - 分母敏感性诊断 C：`initial_risk → IAE_USD`、`initial_risk → Giveback_USD`，报告两者相关。
> - `PnL_norm`（Secondary economic diagnostic，非假设定义终点）：`P&L_USD / initial_risk`，仅经济意义判断。
> - A、B、C 三者联合解释，不单独决定结论。
>
> 双轨保留 raw USD。142 vs 68 仅作 Selection Diagnostic（描述性比较），不筛选样本。
>
> 主统计量 Spearman ρ；CI = Fisher-z approximation（标注近似，非严格精确 CI）；permutation null（N=2000，seed=`20260816`，仅诊断）。
>
> 禁止：改 `k=2`/`W=48`、mediation、参数敏感性、新 cutoff、补造 68 笔 initial_risk、把 SL 当解释条件。
>
> 结论边界：仅覆盖 SL 子群体，不可外推全部 210。

---

*本文档为 EQ-1R 规格审查，冻结值以 §11 / §13 为准。正式运行以 `EQ-1R Pre-Registration v0.1` 的 Gate 0 校验为准。*
