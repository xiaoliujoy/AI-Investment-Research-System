# H2-A Pre-Registration v0.1（预登记方案，冻结，未运行）

> 本文件与 `backend/output/research_contracts/RC-H2A-PREREG-v0.1.json` 共同构成 H2-A 的预登记契约。
> 状态：**PRE-REGISTRATION（已登记，未运行）**——本步骤不写代码、不算特征、不读取 E2 结果、不跑任何实验。
> 原则：**先登记，后运行。** 预登记文件修改时间必须早于 H2-A 首次运行时间。

---

## 0. 为什么需要预登记

H2 定义 v0.1 已冻结（`docs/H2_PreTrade_Entry_Archetype_v0.1.md`）。但 H2-A 本身仍有研究自由度：

> 若等看到 Archetype 与 E2 的结果后，再决定用 Lift / MI / Chi-square，以及 τ 取多少，则只是把 look-ahead 从「变量选择」转移到「检验方法选择」。

因此 H2-A 遵循 Research Contract 原则：**先登记，后运行。**

---

## 1. H2-A 的问题定义

**不要问**：「能不能找到一个变量组合解释 E2？」（这是模型优化，会 data mining）

**要问**：「在完全冻结的 Pre-Trade Information Set 下，预先定义的机械 Archetype，能否在**未使用结果信息**的情况下，对历史 E2 标签产生稳定的区分能力？」

这是一个 **identifiability test**，不是预测建模。

---

## 2. Archetype 复杂度限制（第一轮只用 3 个状态）

禁止把 6 类变量组合成几十种 archetype（210 笔样本会立刻陷入 data mining）。第一轮只定义 3 个最简单的 Pre-Trade State，全部由 `entry_time` 之前的信息定义：

| State | 含义 | 核心事前变量（冻结阈值见 §2.1） |
| --- | --- | --- |
| **A** Anticipatory-like | 尚未突破 / 无确认 | `NOT breakout_before_entry` |
| **B** Confirmation-like | 已突破 + 回踩确认 | `breakout_before_entry AND pullback_confirm` |
| **C** Expansion-like | 已突破 + 价格扩张 + 波动扩张 | `breakout_before_entry AND NOT pullback_confirm AND entry_expansion AND vol_state=expansion` |
| Other | 残余（不匹配 A/B/C） | 汇报但不参与 PASS 评估 |

三者构成对全样本的主划分（Other 为残余桶）。

### 2.1 冻结的 Archetype 规则（PRE-REGISTERED，a priori，非 E2 调参）

基于 H2 定义文档 §3 的 6 类变量，阈值在登记时一次性固定：

- `breakout_before_entry`：入场前 20 根（N_break=20）内最高价被 `entry_price` 越过（严格在 entry_time 之前）。→ 突破发生。
- `pullback_confirm`：突破后至 entry_time 之间，价格回踩突破位（距突破位 ≤ 0.1×ATR）并收回到突破位之上；回踩窗口=突破后 10 根（retest_tol=0.1×ATR, lookback=10）。
- `entry_expansion`：入场价位于当根 K 线区间上四分位，`(entry-low)/(high-low) > 0.75`（q=0.75）。
- `vol_state`：扩张 `atr_entry > 1.1 × mean(ATR, 50)`；收缩 `< 0.9 ×`；否则中性（mult=1.1/0.9, win=50）。
- `chasing_state`（C 的辅助判据已含于 entry_expansion + vol_state）：入场近 10 根高点且波动扩张。

> 全部阈值在看到任何 E2 关联前即冻结。运行阶段**禁止**用 E1/E2/E3/E4 结果反向修改上述任何规则。

---

## 3. 主检验指标：Lift（唯一主指标）

定义：

```
Lift = P(E2 | Archetype) / P(E2)
```

- 分母 `P(E2)` = 全样本基线 = 97 / 210 ≈ 46.2%（固定历史事实，非调参）。
- 分子 = 该 Archetype 子集内 E2 占比。

例：某 Archetype 子集 E2=70/120=58.3%，Lift=58.3%/46.2%=1.26 → 进入该状态后 E2 发生率约为总体基准 1.26 倍。

**选 Lift 不选 MI / Chi-square 的理由**：我们不是建预测模型，而是回答「某 Pre-Trade State 出现时，E2 是否显著高于基准」。Lift 解释最直观，且贴近当前问题。

### 3.1 次要统计检验（辅助，非 Gate）

- **Fisher exact / Chi-square**：对「Archetype × E2」列联表做显著性检验，作为辅助证据。
- **禁止**根据结果挑选「最好看」的指标作为结论。主指标恒为 Lift。

---

## 4. τ 不拍脑袋：Gate 拆三层

| Gate | 条件 | 含义 |
| --- | --- | --- |
| **A1 方向** | `Lift > 1` | Archetype 与 E2 正相关 |
| **A2 稳定** | `Lift_train > 1` **AND** `Lift_validation > 1` | 时间两段方向一致 |
| **A3 经济意义** | `Lift_validation ≥ 1.25` | 事前固定最低 Lift；要求 E2 发生率至少 +25% |

> **1.25 是研究门槛，不代表统计显著。** 它只要求 Archetype 把 E2 发生率提高 ≥25%；显著性看置信区间与辅助检验。

### 4.1 时间切分（禁止优化）

- 仅 2026-03-02 ~ 2026-08-05 数据。
- **Discovery = 前 70%**（按 entry_time 升序），**Validation = 后 30%**。
- cutoff 日期由程序按交易时间排序后**机械计算**（第 70 百分位的 entry_time），**禁止**手挑「表现最好」的日期。
- 三列 Lift 均使用**全局基线** P(E2)=46.2% 作分母：
  - `Lift`（全样本）、`Lift_train`（Discovery 子集 E2 率 / 全局基线）、`Lift_validation`（Validation 子集 E2 率 / 全局基线）。

---

## 5. H2-A 的 PASS / FAIL 判定

**PASS（全部满足，且至少一个 Archetype 命中）**：

1. `Lift > 1`（方向）
2. `Lift_train > 1` 且 `Lift_validation > 1`（稳定）
3. `Lift_validation ≥ 1.25`（经济门槛）
4. Archetype 样本量 `N ≥ 20`
5. 结果**非单笔驱动**（剔除 E2 贡献最大的单笔后 Lift 不坍塌）
6. 未用 E1/E2/E3/E4 结果反向修改 Archetype
7. （见 §7 负对照）区分具有特异性

**FAIL** → **终止 E2-conditioned Exit 路线**；记录 E2 为纯 post-trade artifact；不进 H2-B / OOS。

### 5.1 统计显著性的定位

210 笔样本过小（E2≈97，切半后每段≈100）。若要求 `p<0.05` 可能把**真实弱信号**被小样本噪声直接淘汰。因此：

- 统计检验（Fisher/Chi-square）仅作**辅助证据**，不是唯一 Gate。
- 第一阶段以 Lift 的方向 + 稳定性 + 经济门槛 + 样本量 + 非单笔驱动 为 PASS 条件。

---

## 6. H2-A 固定输出表

不是「E2 被预测出来了」，而是一张固定表：

| Archetype | N | E2 Rate | Baseline E2 Rate | Lift | Train Lift | Validation Lift |
| --- | --: | ------: | ---------------: | ---: | ---------: | --------------: |
| A | | | 46.2% | | | |
| B | | | 46.2% | | | |
| C | | | 46.2% | | | |
| Other | | | 46.2% | | | |

决策流：

```
Pre-Trade Archetype (A/B/C)
        ↓
是否稳定区分 E2？（§5 PASS 条件）
        ↓
YES ──→ H2-B
NO  ──→ E2 路线终止
```

---

## 7. Negative Control（负对照，强烈建议）

E2 本身是事后标签，需防止：某 Archetype 与**任何**交易结果都相关，只是碰巧和 E2 相关。

- 定义**非目标标签** `Y_neg` = 入场后固定 10 根窗口的收益率方向（涨/跌），固定定义，**不涉及 MFE/MAE/capture**。
- 计算 `Lift_A(Y_neg)`、`Lift_B(Y_neg)`、`Lift_C(Y_neg)`。
- 要求：在 E2 上 Lift>1.25 的 Archetype，**不得在 Y_neg 上同样出现 Lift>1.25**（特异性）。若同样被 lift，则 E2 信号非特异 → 降级解释置信度。

> 负对照在看到 H2-A 结果前冻结。它不阻塞 PASS，但影响解释置信度与是否进 H2-B。

---

## 8. 冻结结构（最终）

```
H2-A Pre-Registration
│
├── Frozen Feature Set          (H2 定义 §3, 6 类)
├── Frozen Archetype Rules      (A/B/C + Other, §2.1 阈值)
├── Frozen Primary Metric       └── Lift = P(E2|A)/P(E2)
├── Frozen Secondary Test       └── Fisher / Chi-square (辅助, 非 Gate)
├── Frozen Time Split           └── 70% / 30% by entry_time (机械 cutoff)
├── Frozen Minimum Sample       └── N ≥ 20
├── Frozen Economic Threshold   └── Validation Lift ≥ 1.25
├── Stability Requirement       └── Train>1 AND Validation>1
├── Negative Control            └── Y_neg (post-entry 10-bar return dir)
└── Decision
       ├── PASS → H2-B
       └── FAIL → terminate E2-conditioned Exit
```

---

## 9. 执行纪律（写死）

- **预登记文件修改时间必须早于 H2-A 首次运行时间。** 未来可清晰区分：研究设计 → 实验 → 结果 → 解释。
- 禁止：结果 → 找解释 → 找变量 → 找策略。
- 本文件为**设计冻结**；`exit_observation_h2a.py` 待用户批准后另立，且首个运行须校验本文件 mtime < 运行时间。
- 当前研究状态：RC FROZEN / Exit H1 REPRODUCED / E1-E4 attribution REPRODUCED / E1-E4 identifiability FAILED·LOOK-AHEAD / H2 定义 v0.1 冻结 / **H2-A Pre-Registration v0.1 冻结（未运行）**。
