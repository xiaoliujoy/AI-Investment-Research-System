# H2-A / EQ-1 Final Freeze Audit（封板审计）

> 目的：把 H2-A 与 EQ-1 研究线从「半开放」推进到「可审计关闭」。
> 审计标准（封板五问，每问必答）：
> 1. 研究问题是什么
> 2. 预登记假设是什么
> 3. 实际执行了什么
> 4. 结果支持还是拒绝假设
> 5. 哪些东西已**不能**从这批数据继续解释
>
> 范围：XAUUSD M5 / MT5 210 笔交易（2026-03-19 ~ 2026-08-05）。
> 不在范围：黄金 E1/E4 合约（RC-GOLD-ENTRY-E1E4，状态 CLAIM，独立资产、未验证）；任何生产/自动交易动作。
> 生成日期：2026-08-19。

---

## 一、H2-A

### Q1 研究问题
在完全冻结的 Pre-Trade 信息集下，入场前的结构形态（3 类 Archetype：A=无突破 / B=突破+回踩 / C=突破+扩张）能否稳定识别 E2（anticipatory_suffered，入场即陷）？

### Q2 预登记假设
`N_break=20` / `atr_entry > 1.1×mean(ATR,50)` / `pullback_confirm` 定义的 A/B/C 中，至少一类在 train/val 切分下对 E2 的 Lift ≥ 1.25，且通过 permutation null + 负对照 Y_neg + 多重比较控制。否则 FAIL。

### Q3 实际执行
`backend/os_layers/exit_observation_h2a.py`，2026-08-14 首次运行；2026-08-19 复现（字节级一致）。
Gate 0 令牌全部命中，A/B/C 三态、train/val 切分、Y_neg、2000 次 permutation 全执行。

### Q4 结果：拒绝（FAIL）
| Archetype | N | E2率 | Lift | train Lift | val Lift | yneg Lift | 过 Gate |
|---|--:|--:|--:|--:|--:|--:|:--:|
| A（无突破） | 202 | 47.5% | 1.029 | 0.984 | 1.138 | 0.987 | 否（A2/A3 失败） |
| B（突破+回踩） | 0 | — | — | — | — | — | 否（N<20） |
| C（突破+扩张） | 8 | 12.5% | 0.271 | 0.000 | 0.541 | 1.326 | 否（N<20，负对照不特异） |
| baseline | 210 | 46.2% | — | — | — | — | — |

- Permutation：observed max Lift=1.029 **低于** null 均值 1.156，empirical_percentile=40.7%。
- **决策：FAIL → 终止 E2-conditioned Exit 研究线；E2 记为纯事后分型。**

### Q5 已不能从这批数据继续解释（禁止推论）
- ❌ 「入场前 Archetype 能识别 E2」——直接被拒绝。
- ❌ 「这套 3 类形态在 A 股/其他品种也成立」——样本仅 XAUUSD 210 笔。
- ❌ 「E2 在其他定义下可能有效」——除非新预登记，禁止用 H2-A 数据再挖。
- ❌ 「B/C 类因为样本少所以只是可惜」——N=0 / N=8 是设计结果，不是偶然；不得以此为理由重设 Archetype。

### H2-A 封板戳
`EXPERIMENT #001 · EXECUTED · FAIL · REPRODUCED · ARCHIVED`
原始预登记（`docs/H2A_PreRegistration_v0.1.md`）、首次运行产物、复现产物、FAIL 原因均原样保留，未改实验设计。

---

## 二、EQ-1 家族（EQ-1 主实验 / EQ-1R 稳健性 / EQ-1M 路径）

> 三份均按预登记纪律「第一次 Run 只描述数据、不推导交易结论、不产买卖信号」，故决策字段统一为 `OBSERVATION`（设计如此，非未完）。

### Q1 研究问题
在完全冻结的 Pre-Trade 信息集下，entry 相对最近方向性结构摆点 CP 的时间距离 **ETD**，是否与 IAE / MFE / Giveback / PnL 存在可识别的连续关系？（中性 Entry Quality 研究，非标签预测、非模型优化。）
EQ-1R：上述 IAE→Giveback 强关系是否由 stop-distance 尺度变量制造。
EQ-1M：ETD→IAE→Giveback 是否构成可识别的路径机制关联（非因果中介）。

### Q2 预登记假设
- H1 ETD→IAE ≠ 0；H2 ETD→MFE ≠ 0；H3 IAE→Giveback ≠ 0（中介前置关联，非正式中介）；H4 ETD→执行结果（exploratory）。
- EQ-1R：A=raw / B=风险标准化 / C=分母诊断，三者联合判断 IAE→Giveback 是否含纯尺度成分。
- EQ-1M：indirect=a·b，不要求显著（已知功效可能不足）。

### Q3 实际执行
- EQ-1：`entry_quality_eq1.py`，2026-08-15T05:05，Gate 0 通过，decision=OBSERVATION。
- EQ-1R：2026-08-15T14:12，142 笔 SL 子集 + 68 笔 non-SL 诊断，decision=OBSERVATION。
- EQ-1M：2026-08-15T15:06，210 全样本路径，bootstrap BCa 10000 + permutation，decision=OBSERVATION。

### Q4 结果（描述性，非 PASS/FAIL）
| 实验 | 关键读数 | 含义 |
|---|---|---|
| EQ-1 H1 ETD→IAE | ρ=0.153（CI 0.018~0.283） | 弱正，permutation 92.35%（临界） |
| EQ-1 H2 ETD→MFE | ρ=−0.089（CI 含 0） | **零效应** |
| EQ-1 H3 IAE→Giveback | ρ=0.532（CI 0.428~0.623） | **强关联**，全样本最稳定信号 |
| EQ-1 H4 ETD→执行结果 | ρ≈0（Giveback/MFE/PnL 对 ETD） | **零效应** |
| EQ-1R A/B/C | A ρ=0.571 / B ρ=0.571 / C(分母) 0.35&0.24 | 风险标准化后关系**仍成立**，非纯尺度制造；perm 100% |
| EQ-1M 路径 | Spearman indirect=0.083（CI 0.007~0.157，不含 0）；perm 100% | ETD→IAE→Giveback 路径机制关联成立（**非因果**）；Pearson 0.11 vs Spearman 0.53 提示离群杠杆，秩路径为稳健读数 |

**结论（描述性）**：入场时机 ETD 对收益/机会成本几乎无解释力（H2/H4 零），但**入场后的初期逆向暴露 IAE 强预测回吐 Giveback**——这是一个稳健、可复现的「执行质量签名」，与「方向可能没大错、但执行吃掉收益」的 Execution Gap 假说一致。

### Q5 已不能从这批数据继续解释（禁止推论）
- ❌ 「ETD / 入场时机可预测收益」——H2/H4 直接零效应。
- ❌ 「IAE→Giveback 是因果中介」——EQ-1M 明确为路径机制关联，禁止上升为因果。
- ❌ 「这是一个可交易 edge」——三份均为 OBSERVATION，无 entry/exit/position 规则，不进入 Strategy Contract。
- ❌ 「结论适用于 non-SL 68 笔」——EQ-1R 核心证据仅覆盖 142 笔 SL 子集，不得外推全样本。
- ❌ 「Pearson 读数可信」——离群杠杆下 Pearson 严重衰减，仅秩/Spearman 路径为科学读数。

### EQ-1 家族封板戳
`EXECUTED · OBSERVATION · DESCRIPTIVE SIGNAL CAPTURED · ARCHIVED`
- 描述性信号：IAE→Giveback 稳健关联（≡ Execution Gap 量化签名）。
- 非策略、非因果、非可交易。Strategy Contract v1.0 保持 DRAFT / NO QUALIFIED STRATEGY。

---

## 三、跨实验结论

1. **入场侧（时机/形态）预测力弱**：H2-A Archetype 失败、EQ-1 H2/H4 零效应，一致表明「事前状态」对结果解释力低。
2. **入场后执行质量有真实结构**：IAE→Giveback 在 EQ-1 / EQ-1R / EQ-1M 三份独立运行中一致成立（perm 均超 95%），是这批数据中最稳的描述性发现。
3. **两者都不是策略**：一个 FAIL，一个 OBSERVATION。没有一条满足 Strategy Contract v1.0 的准入门槛。
4. **文档漂移已修正**：H2-A / EQ-1 / EQ-1R / EQ-1M 四份文档原状态行写「未运行 / 待审阅」，实际均已于 2026-08-14~15 执行；本次审计将状态行更正为 EXECUTED，原实验设计（§0–§9 / Gate 0 令牌）一字未动。

---

## 四、OPEN 与 FORBIDDEN

**FORBIDDEN（封板即锁死）**
- 为 H2-A 重设 Archetype / 重跑找 E2 替代定义。
- 将 EQ-1 的 IAE→Giveback 当作因果机制或交易信号使用。
- 不经新预登记、直接把 EQ-1 描述性发现塞进 Strategy Contract。
- 把黄金 E1/E4 的 CLAIM 状态误读为已验证证据。

**OPEN（如需推进，必须新预登记，不得续接 EQ-1）**
- OOS 验证：IAE→Giveback 在独立样本/未来数据是否仍成立？
- 策略化：能否把「初期逆向暴露」转成可执行规则（如 ETD 后 N 根内 IAE 超阈 → 减仓/退出）？这是**新假设**，需独立 Pre-Registration + 独立 Strategy Contract，不是 EQ-1 的延续。
- 黄金 E1/E4 的 CLAIM 需独立验证运行，方能升级状态。

---

## 五、归档清单（Archived Manifest）

| 实验 | 预登记文档 | 运行产物 | 状态 |
|---|---|---|---|
| H2-A | `docs/H2A_PreRegistration_v0.1.md`（已标 EXECUTED/FAIL/ARCHIVED） | `backend/output/research_contracts/h2a_observation_v0_1.json` + `.firstrun.bak` | EXECUTED·FAIL·REPRODUCED·ARCHIVED |
| EQ-1 | `docs/EQ1_PreRegistration_v0.1.md` | `eq1_observation_v0_1.json` | EXECUTED·OBSERVATION·ARCHIVED |
| EQ-1R | `docs/EQ1R_Risk_Normalized_Robustness_Specification_Review_v0.1.md` | `eq1r_observation_v0_1.json` | EXECUTED·OBSERVATION·ARCHIVED |
| EQ-1M | `docs/EQ1M_Pathway_Mediation_Specification_Review_v0.1.md` | `eq1m_observation_v0_1.json` | EXECUTED·OBSERVATION·ARCHIVED |

> 审计结论：两条研究线均已可审计关闭。H2-A 产出一枚被机器可靠杀死的假设（Asset 001）；EQ-1 家族产出一枚稳健但非策略的描述性执行质量签名。研究系统具备「结束研究」的能力——本轮封板即证据。
