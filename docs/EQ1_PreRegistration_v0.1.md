# EQ-1 Pre-Registration v0.1

> 配套 `docs/EQ1_Methodology_Review_v0.1.1.md` 与 `docs/EQ1_CP_D_Specification_Review_v0.1.md`。
> **状态：FROZEN · NOT RUN。** 本文为预登记，冻结后未经运行。
> 机器可读契约：`backend/output/research_contracts/RC-EQ1-PREREG-v0.1.json`（`eq1_result = PENDING`）。
> 运行时纪律：Gate 0 冻结令牌校验 → Code → `py_compile` → Run；**第一次 Run 只允许回答「数据是什么」，不回答「应如何交易」**。

---

## 0. 纪律红线（本文适用）

1. **显式解耦 H2-A**：H2-A FAIL（分类标签 E2 可识别性）**不构成** EQ-1 先验。EQ-1 不预测任何事后标签 E1–E4。
2. **禁止数据窥探**：所有变量、统计量、阈值在运行前写死；不允许「看 210 笔结果后改定义/改检验/改阈值」。
3. **ex-ante 铁律**：CP 与 ETD 只用 `close_time <= entry_unix` 的已收盘 bar；Outcome 只用 `entry` 之后的 bar；禁未来 MFE/IAE/Giveback 反推 ETD 或 CP。
4. **ETD 完全中性**：`ETD↑→IAE↑` / `≈0` / `↓` 三种结果均接受，无「提前 = 差」先验。
5. **全报纪律**：H1–H4 无论方向、显著与否全报告，禁 cherry-pick。
6. **v0.1 故意粗糙**：不加 trend / ATR / swing-strength filter，不设 no-CP fallback，不做参数敏感性调参。

---

## 1. Research Question（RQ-EQ1）

> 在完全冻结的 Pre-Trade 信息集下，entry 相对最近方向性结构摆点（CP）的时间距离 **ETD**，是否与：
> - 初始逆向暴露 **IAE**
> - 机会成本 **MFE**
> - 执行质量 **Giveback / MFE Realization**
> - 经济结果 **R / P&L**
>
> 存在可识别的**连续**关系？
>
> 这是中性 **Entry Quality** 研究，不是标签预测，不是模型优化。

研究链（最终形态）：

```
            ┌──────────────────┐
            │ Entry-time info  │
            └────────┬─────────┘
                     ↓
                CP-D / ETD
                     │
         ┌───────────┴───────────┐
         ↓                       ↓
       IAE                      MFE
         ↓                       ↓
   Exit / Giveback            P&L
         │                       │
         └───────────┬───────────┘
                     ↓
            Economic Outcome
```

---

## 2. Ex-ante Information Set 与因果序

| 角色            | 时间约束                                            | 用途                       |
| ------------- | ----------------------------------------------- | ------------------------ |
| Exposure（ETD） | 仅读 `entry_time` 及之前已收盘 bar                      | 自变量，客观市场结构位置             |
| Outcome        | 仅读 `entry_time` **之后**的已收盘 bar                  | 因变量，执行/经济结果              |
| 禁止            | 任何 outcome 量反改 ETD / CP 定义                      | 杜绝后视偏差                   |

`entry_reference_bar` = entry timestamp 之前**最后一根已收盘 M5 bar**（绝不用 forming entry bar）。

---

## 3. 变量分类（Variable Taxonomy）

### 3.1 Exposure（自变量，每笔交易）

| 变量              | 定义                                         | 角色          |
| --------------- | ------------------------------------------ | ----------- |
| **ETD_bars**    | `entry_reference_bar_index − CP_bar_index`（整数 ≥ 1） | **Primary** |
| **ETD_minutes** | `(entry_timestamp − CP_timestamp) / 60`     | Secondary   |

### 3.2 Per-Trade Outcomes（单笔交易连续 Outcome）

| 类别          | 变量                                                    | 定义                                              |
| ----------- | ----------------------------------------------------- | ----------------------------------------------- |
| Risk        | `MAE_USD`                                             | entry 后最大不利漂移（USD）                            |
| Risk        | `IAE_USD`                                             | entry 后 10 根完整 M5 最大逆向 excursion（USD），R1 冻结      |
| Opportunity  | `MFE_USD`                                             | entry 后最大有利漂移（USD）                            |
| Execution   | `Giveback_USD`                                        | 从 MFE 回吐到 exit 的幅度（USD）                       |
| Execution   | `MFE_Realization`                                     | **exploratory / 条件量**（见 §5 H4），非 Primary          |
| Execution   | `R`                                                   | 以 initial_risk 归一化的结果单位                       |
| Execution   | `P&L_USD`                                             | 单笔盈亏（USD）                                     |

### 3.3 Aggregate Diagnostics（样本级聚合，**不是单笔 Outcome**）

| 变量          | 说明                              | 定位                       |
| ----------- | ------------------------------- | ------------------------ |
| `PF`        | Profit Factor（样本级聚合）               | **仅 sample-level**，不进 `ETD → PF` |
| `Sharpe`    | 样本级收益风险比                        | 仅 sample-level            |
| `MaxDD`     | 样本级最大回撤                        | 仅 sample-level            |
| `win_rate`  | 样本级胜率                          | 仅 sample-level            |

> **修正 #4（PF 定位）**：PF / Sharpe / MaxDD / win_rate 是样本级聚合统计量，**不是一笔交易的连续 Outcome**，因此**不能进入 `ETD → PF` 这类单笔交易关联**。它们在 EQ-1 中只作为运行结束后的 aggregate diagnostics 报告，不参与 H1–H4 的暴露–结果检验。

---

## 4. 冻结定义（R1–R3 + CP-D）

### R1 — IAE 窗口（冻结）

`IAE = entry 后 10 根完整 M5 的最大逆向 excursion（USD）`。
固定 10 根，不依赖止损；拒 `0.5R` 混合尺度（R 内生性会混淆结果）。

### R2 — MFE Realization floor（冻结：移出 Primary）

`0.2R` floor **不进入 Primary**。Primary 用原始连续量 `MFE_USD` / `Giveback_USD` / `P&L_USD`；capture ratio 仅作 secondary。

### R3 — 双轨（冻结）

Primary 用 **USD 原始路径**（MAE/IAE/MFE/Giveback/P&L）；Secondary 用 `÷ initial_risk` 归一化量并陈。

### CP-D（已冻结，方向 + 六参数）

> CP 是 entry timestamp 之前、最近 W 根已收盘 M5 bar 中满足严格 `(2k+1)` 局部极值规则的方向性 swing point。
> Long 使用最近 swing high，Short 使用最近 swing low。
> `k = 2`，`W = 48`。
> ETD 参考点 = entry timestamp 之前最后一根完整收盘 M5 bar。
> `ETD_bars = last_closed_bar_index − CP_bar_index`（Primary）；`ETD_minutes = (entry_timestamp − CP_timestamp) / 60`（Secondary）。
> W 窗口内无合格 CP → 排除该交易并报 exclusion rate，不设 fallback。

**修正 #1（CP 确认边界，必须修正）**：一个 swing point 需要右侧 `k` 根 bar 才能确认。因此 CP 候选不仅须满足 `CP_bar_index < entry_reference_bar_index`，还须满足：

```
CP_confirmed_bar_index = CP_bar_index + k
CP_confirmed_bar_index <= entry_reference_bar_index      # k = 2
```

即：CP 候选 swing 的**确认状态必须在 `entry_reference_bar` 之前已经完成**，不得把尚未被右侧 k 根确认的局部极值误当作 CP。此条件写入 Gate 0 冻结令牌（见 §8）。

---

## 5. 假设 H1–H4（主统计量，全报告）

Primary association measure：**Spearman 秩相关 ρ**（对单调非线性和离群稳健）；Pearson `r` 作 secondary 报告。H4 用关联/回归。

### H1 — ETD → IAE

`H1: ρ(ETD_bars, IAE_USD) ≠ 0`
检验 entry 时间位置（相对结构点）是否系统关联于初始逆向暴露。

### H2 — ETD → MFE

`H2: ρ(ETD_bars, MFE_USD) ≠ 0`
检验 ETD 是否系统关联于机会成本（最大有利漂移）。

### H3 — IAE → Exit Quality（**修正 #2：降级为中介前置条件的关联检验**）

`H3: ρ(IAE_USD, Giveback_USD) ≠ 0`

- **定义修正**：H3 不声称 IAE 是 ETD 与 Exit Quality 之间的中介。它只检验**中间变量（IAE）与结果（Exit Quality / Giveback）是否存在系统性关联**，并验证「进一步中介分析的必要条件」是否满足。
- **v0.1 不执行正式 mediation analysis。**
- 只有未来**同时满足**以下三条，才有资格进入独立的 mediation study（须单独预登记、先冻结后跑）：
  - `ETD → IAE`（H1 成立）
  - `IAE → Exit Quality`（H3 成立）
  - `ETD → Exit Quality`（独立关联成立）

### H4 — ETD + initial_risk → Execution Outcome（**修正 #3：降级为 exploratory**）

`H4: {Giveback_USD, MFE_USD, P&L_USD} 各自 ~ ETD_bars + initial_risk`

- **定义修正**：H4 保留，但**降级为 exploratory**。
- **Primary 不使用 `MFE Realization = P&L / MFE`**：该指标在 `MFE ≈ 0` 附近爆炸，且对亏损交易符号不稳定（如 `P&L=-100, MFE=10 → -10`），不是天然稳定的 execution-quality 量。把它当无条件可回归的连续变量，只是把 R2 的定义问题变成「模型运行时异常」。
- Primary 改为分别研究 `Giveback_USD` / `MFE_USD` / `P&L_USD` 三个原始连续 Outcome（各对 `ETD_bars + initial_risk` 做关联/回归），全报告。
- 若保留 `MFE Realization` 作 **secondary / exploratory**，须冻结 eligibility condition：
  `MFE >= 0.2 × initial_risk`
  且**必须报告** `N_total` / `N_excluded_due_to_MFE_floor` / `exclusion_rate`，不得静默过滤。

---

## 6. 负对照（Negative Control）

**ETD permutation null**（对齐 H2-A 纪律）：

- 固定 Archetype / CP-D 定义 / 样本；仅置换 ETD 与 outcome 的配对（保留边际分布）。
- `N_PERM = 2000`，`seed = 20260815`。
- 统计量 `stat = max |assoc|` over H1 / H2 / H3 primary（含 H4 exploratory 各 outcome 的 max |assoc|）。
- 输出 `empirical_percentile`（observed stat 在 null 分布中的分位）。
- **仅 diagnostic，不新增 Hard Gate**；`empirical_percentile < 95` 仅标 caveat，不复活任何被否假设。

**Y_neg（概念负对照）**：ETD 不应与「entry 后 10 根随机收益方向」存在特异关联——用于排除「机制在 null 下也能造显著性」。

---

## 7. 多重比较与全报纪律

- H1–H4 同属一个 family，报告时标注 family-wise 视角，不靠单 p 值下结论。
- 小样本（N 可能 < 210，no-CP 排除后更小）不追 `p < 0.05`；以效应量 + 置信区间 + permutation 分位为主。
- 四态全报告，禁 cherry-pick。

---

## 8. Gate 0 冻结令牌（运行时由 `entry_quality_eq1.py` 核对）

| 令牌                                 | 冻结值                                            |
| ---------------------------------- | ---------------------------------------------- |
| `k`                                | 2                                              |
| `W`                                | 48                                             |
| `price_field`                      | High / Low                                      |
| `tie_rule`                         | nearest（等价格取更晚）                              |
| `no_cp`                            | exclude + report exclusion_rate（无 fallback）        |
| `iae_win`                          | 10                                             |
| `r2_floor`                         | out_of_primary                                 |
| `r3_track`                         | dual（USD raw + risk-normalized）               |
| `perm_n`                           | 2000                                           |
| `perm_seed`                         | 20260815                                       |
| `perm_stat`                        | max\|assoc\| over H1–H4                         |
| `etd_primary`                      | bars                                           |
| `etd_secondary`                    | minutes                                        |
| `entry_ref`                        | last_closed_bar_before_entry（杜绝 forming bar）      |
| **`cp_confirm_rule`**               | **`CP_bar_index + k <= entry_reference_bar_index`（k=2）** |
| `h3_mode`                          | precondition_association（非 mediation）              |
| `h4_mode`                          | exploratory，不使用未处理 MFE Realization 作 Primary       |
| `pf_location`                      | aggregate_diagnostics（不进单笔 ETD→outcome）            |

缺失任一令牌 / 预登记 mtime 晚于首次运行 → `sys.exit(2)`（STOP）。

---

## 9. 执行序（待用户批准后）

1. 写 `entry_quality_eq1.py`（纯 stdlib，Observation-only）。
2. `py_compile` 通过。
3. Run：先过 Gate 0，再产出固定输出表。
4. **第一次 Run 只描述「数据是什么」（效应量 / 方向 / 置信区间 / permutation 分位 / exclusion_rate），不推导交易含义。**

---

## 10. 范围之外（v0.2+，独立预登记）

- 参数敏感性：`k ∈ {1, 2, 3}`、W 取值、price field 替代。
- 摆点增强：trend / ATR / swing-strength filter、被尊重摆点、多摆点融合。
- 正式 mediation analysis（须 H1/H3/ETD→ExitQuality 全成立）。
- MFE Realization 作为 Primary outcome（须先解决 floor / 爆炸问题并预登记 eligibility）。

---

*本文档为 EQ-1 正式预登记 v0.1。冻结值以本文 §4 / §8 与 `RC-EQ1-PREREG-v0.1.json` 的 Gate 0 为准；运行以该契约的 `--check` 通过 + Gate 0 运行时校验为准。*
