# EQ-1M · IAE Pathway / Mediation-Shaped Association — Pre-Registration v0.1

> 配套 `docs/EQ1M_Pathway_Mediation_Specification_Review_v0.1.md`（已审阅，三层前置 + 9 指标 + 窗口重叠审计已冻结，具备 Pre-Registration 条件）。
> 本文为正式预登记：问题 → 信息集 → 样本 → 变量/路径 → 统计方法 → 窗口重叠缓解 → 选择偏差 → 禁止事项 → 全报 → Gate 0 → 决策 → 下一步。
> 状态：待 `--check` 通过 + 用户批准后 Code → Compile → Gate 0 → Run。

---

## 0. 治理边界（OBSERVATION_ONLY）

- 不接 run_daily / risk_guard / shadow / CIO / Trading Coach / 生产。
- 不读 E1-E4 标签；不优化阈值；不搜变量；不改 EQ-1 / EQ-1R 契约；不改 `k=2`/`W=48`/`IAE_WIN=10`。
- EQ-1M 只回答一个问题：**ETD → IAE → Giveback 是否构成一条可识别的路径机制关联。** 不做因果中介声明，不负责发现新规律。
- Observation ≠ Optimization / Strategy / Param-Tuning。首跑只描述路径结构，不推导交易结论，不产出买卖信号。

---

## 1. Research Question (RQ-EQ1M)

> Entry 相对 CP 的时间位置 **ETD**，是否通过早期逆向暴露 **IAE**，进一步与后续退出失败 **Giveback** 形成一条可识别的路径？
> 即检验：ETD 与 Giveback 之间是否存在与 IAE 相容的间接关联路径（`Indirect = a × b`）。

本质：承接 EQ-1（IAE→Giveback 强，ρ≈0.53）与 EQ-1R（该关系标准化后不消失，C 中等），检验 **ETD→IAE→Giveback** 这一完整路径是否在观察性数据中存在并可被识别。EQ-1M 是这一轮诊断研究的**收尾**，不是无止境研究的开始。

---

## 2. 信息集与因果序（继承 EQ-1 / EQ-1R）

- 所有变量由 entry_time 前客观市场结构 + 交易记录定义，无微观前视（bisect 纪律）。
- `CP` / `ETD` 由 EQ-1 冻结 CP-D（`k=2`/`W=48`）计算，EQ-1M **不重算 CP-D**，仅消费 `ETD`。
- `IAE` / `MFE` / `Giveback` / `PnL` 由 EQ-1 冻结口径计算（`IAE = entry 后 10 根`；`Giveback = max(0, MFE − 退出有利)`）。
- 方向性：完全中性，无「路径必须显著」先验（已知 a×b≈0.08，功效可能不足）。

---

## 3. 样本边界（冻结）

- **Primary**：210 笔全样本，剔除 `no-CP`（CP-D 无合格摆点则排除并报告 exclusion_rate，不设 fallback）。原因：IAE / Giveback 对全部交易有定义，**不依赖 `sl_trigger_price`**，全样本比 EQ-1R 的 142 更有功效。
- **敏感性分层（Selection Diagnostic，非 Rule）**：`SL 142`（`sl_trigger_price` 非空）与 `non-SL 68`，仅描述性分层 + 各自跑 mediation 作为敏感性，不据此筛选 Primary。
- 不补造 68 笔 initial_risk（仅当 R 标准化需要时在分层内标注缺口；主路径不需要 R）。

---

## 4. 路径模型与变量定义

### 4.1 路径（冻结）

```
ETD ──a──> IAE ──b──> Giveback
 │                     ↑
 └────── c ──────┘     │
        (总效应)    c' (直接效应, 控制 IAE)
```

- `a = ETD → IAE`
- `b = IAE → Giveback`（控制 ETD）
- `c = ETD → Giveback`（总效应，不控制 IAE）
- `c' = ETD → Giveback`（控制 IAE，直接效应）
- `Indirect = a × b`

### 4.2 变量（继承 EQ-1，连续量）

- `ETD_bars` = `entry_reference_bar_index − CP_bar_index`（Primary）；`ETD_minutes` 为 Secondary。
- `IAE_usd` = entry 后 10 根最大逆向 excursion × mult（**中介变量，锁定**）。
- `Giveback_usd` = `max(0, MFE_usd − 退出有利部分)`（结果）。
- `MFE_usd` / `MAE_usd` / `PnL_usd` / `initial_risk_usd`：描述与分层用。
- `Giveback_late_usd`（稳健性变体）：以 **IAE 窗口之后** 的 `MFE`（post-IAE-window 有利峰值）为基准的回吐，标注偏离 EQ-1 原定义。

### 4.3 效应量

- `PM = (c − c') / c`（比例中介）；`|c|` 低于 floor 时 PM 不定义，改报标准化 indirect + 标注「总效应≈0，比例中介不适用」（不一致/完全中介情形）。

---

## 5. 统计方法（9 项冻结指标 + bootstrap / permutation）

**主统计（两套并行）：**

- **Primary（标准 mediation）**：OLS 乘积系数 bootstrap。变量标准化（z-score）后：
  - `a = r(ETD, IAE)`；`c = r(Giveback, ETD)`；
  - 多回归标准化系数：`b = (r_GI − a·c) / (1 − a²)`（IAE 系数，控制 ETD）；`c' = (c − a·r_GI) / (1 − a²)`（ETD 系数，控制 IAE）；
  - `Indirect = a × b`。
- **Secondary（Spearman 连续性）**：`a_s = ρ(ETD, IAE)`；`b_s = partial ρ(IAE, Giveback | ETD)`；`Indirect_s = a_s × b_s`，与 EQ-1 Spearman 传统对齐。

**9 项冻结输出指标：**

1. `indirect_effect`（Primary 标准化 + Secondary Spearman）
2. `indirect_CI`（bootstrap BCa 95%）
3. `direct_effect`（c'）
4. `total_effect`（c）
5. `a_path`（ETD→IAE）
6. `b_path`（IAE→Giveback | ETD）
7. `c'_path`（ETD→Giveback | IAE）
8. `effect_size`（PM，或标准化 indirect + 不定义标注）
9. `permutation / bootstrap diagnostic`

**Bootstrap 参数（冻结）**：`N_BOOT = 10000`，区间 **BCa 95%**，重采样单元=交易（有放回）；`boot_seed = 20260817`（与 EQ-1 `20260815` / EQ-1R `20260816` 独立 provenance，仅 reproducibility，不随结果更换）。

**Permutation null（诊断项，非 Hard Gate，冻结）**：固定 `(ETD, Giveback)` 配对，对 `IAE` 向量做**独立保边洗牌**（打破 a、b 两链接），重算 `Indirect`；`N_PERM = 2000`，`perm_seed = 20260817`；输出 `empirical_percentile`（observed 在 null 中的分位），仅标 caveat。

**成功标准（冻结）**：接受 `indirect > 0 / ≈ 0 / < 0` 三种结果，**不要求显著**（a×b≈0.08 功效可能不足）；结论语言受 §6 因果边界约束。

---

## 6. 窗口重叠缓解（关键审计，冻结）

- `overlap_rate` 诊断：报告 `MFE 峰值索引 < IAE_WIN(10)` 占比 + `exit 在 IAE_WIN 内` 占比（窗口污染风险区）。
- **敏感性层 A（窗口不重叠）**：剔除 `duration ≤ IAE_WIN` 短交易（`IAE` 窗口与 `MFE/Giveback` 窗口结构可分离），重跑 indirect，检查路径是否仍存在。
- **敏感性层 B（Giveback_late 变体）**：以 `Giveback_late` 为结果变量重跑完整 mediation，作为稳健性（标注偏离 EQ-1 原 Giveback）。

---

## 7. 选择偏差与异质性诊断（Selection Diagnostic，非 Rule）

- `Giveback` by `exit_reason`：报 SL / non-SL 的 mean/median，暴露结构异质性（SL 交易 `Giveback ≈ MFE`，non-SL 为 `MFE − 已实现有利`），不掩盖。
- `SL 142` / `non-SL 68` 各自跑 mediation，作为描述性敏感性层（非选择规则）。
- 严禁：「142 更稳定所以只研究 SL」「短交易污染所以删掉」等结果驱动重定义。

---

## 8. 禁止事项（10 项）

1. 仅用继承的 210 全样本（剔除 no-CP），不反选。
2. 不补造 68 笔 initial_risk（R 标准化仅分层内标注缺口）。
3. 不把 SL exit 当解释 Giveback 的条件。
4. 报告 SL/non-SL 与 overlap_rate 异质性，但不据此筛选样本。
5. 中介变量只用 `IAE`（前 10 根），不替换为 MFE/MAE。
6. 不改 `k=2` / `W=48` / `IAE_WIN=10`（继承 EQ-1）。
7. 不声称因果中介（受 §6 措辞约束）。
8. 不进行参数敏感性（`k∈{1,2,3}` 等归 v0.2）。
9. 不深挖 H4（ETD+initial_risk exploratory，已降级）。
10. 不寻找新 cutoff / 阈值，不派生交易信号。

---

## 9. 全报纪律

主路径（a/b/c/c'/indirect/CI/PM）+ Spearman 交叉 + permutation + bootstrap BCa + overlap_rate + 层 A/B + SL/non-SL 诊断 + 逐笔 per_trade 全部报告；选择偏差边界显式声明；`initial_risk` 语义（stop-distance proxy）每次出现标注；因果边界每次出现标注。

---

## 10. Gate 0（冻结令牌 + eq1m_result=PENDING）

运行须校验：

- 预登记文档存在、`mtime < 运行时间`、版本 v0.1
- 冻结令牌齐全（见 `frozen_tokens`）：`Pre-Registration v0.1` / `k=2` / `W=48` / `IAE_WIN=10` / `路径机制关联` / `indirect effect` / `bootstrap BCa` / `20260817` / `10000` / `Giveback_late` / `overlap_rate` / `不要求显著` / `观察性` / `参数敏感性` / `cutoff` / `mediation` / `SL/non-SL`
- `eq1m_result = PENDING` 才允许计算
- 任一不符 → `sys.exit(2)`，不产生结果

---

## 11. 决策规则

- 描述 `ETD→IAE→Giveback` 路径结构（a/b/c/c'/indirect + CI + permutation 分位）。
- 允许结论范式（冻结）：「数据与 ETD→IAE→Giveback 路径机制关联相容；控制 ETD 后 IAE 对 Giveback 仍具独立关联，且 ETD→Giveback 总效应弱/≈0 → 模式与 mediation-shaped association 一致。」
- 禁用结论范式（冻结）：「IAE 是 ETD 导致退出失败的中介」「IAE 导致 Giveback」「应据此调整 ETD 改进退出」。
- 若 `indirect CI` 排除 0 且 a>0、b>0 → 表述为「与正向路径机制相容」；若 CI 含 0 → 表述为「与 null 间接效应相容，路径不可与随机区分」；三者均接受，不 cherry-pick。
- 任何二次分析 / 深探 / 接 Trading Coach 须先冻结后跑，不在本轮。

---

## 12. 下一步

`--check` 通过 + 用户批准 → Code（纯 stdlib Observation-only，复用 EQ-1 数据接口）→ py_compile → Gate 0 → Run → 输出 `eq1m_observation_v0_1.json` → 契约收口 `eq1m_result=OBSERVATION` → 起草《EQ Series v0.1 → Trading Coach Diagnostic Mapping》。

---

*本文档为 EQ-1M 正式预登记，冻结值以 `RC-EQ1M-PREREG-v0.1.json` 的 Gate 0 校验为准。*
