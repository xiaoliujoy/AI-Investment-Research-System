# EQ-1R · Risk-Normalized Robustness Review — Pre-Registration v0.1

> 配套 `docs/EQ1R_Risk_Normalized_Robustness_Specification_Review_v0.1.md`（已审阅，4 项修正落盘，具备冻结条件）。
> 本文为正式预登记：问题 → 信息集 → 变量 → 证据设计 → 检验 → Gate → 负对照 → 预登记 → Code → Compile → Run → 解释。
> 状态：待 `--check` 通过 + 用户批准后 Code → Compile → Gate 0 → Run。

---

## 0. 治理边界（OBSERVATION_ONLY）

- 不接 run_daily / risk_guard / shadow / CIO / Trading Coach / 生产。
- 不读 E1-E4 标签；不优化阈值；不搜变量；不改 EQ-1 v0.1 契约；不改 `k=2`/`W=48`。
- EQ-1R 只回答一个问题：**EQ-1 中观察到的 IAE→Giveback 关系，在剥离 stop-distance 尺度因素后，还剩多少。** 不负责发现新规律。
- Observation ≠ Optimization / Strategy / Param-Tuning。首跑只描述数据，不推导交易结论。

---

## 1. Research Question (RQ-EQ1R)

> 在有可观测 initial risk 的 142 笔 SL 子样本中，IAE 与 Giveback 的关系，在风险标准化（÷ initial_risk）后是否仍然存在？

本质：检验 H3（`IAE_USD → Giveback_USD`, ρ=0.532）是否由 initial risk / stop distance 这一尺度变量制造。EQ-1R **不是重新证明 H3**，而是稳健性检查。

---

## 2. 信息集与因果序（继承 EQ-1）

- 所有变量由 entry_time 前客观市场结构 + 交易记录（`sl_trigger_price`, `volume`）定义，无微观前视。
- `IAE` / `Giveback` / `MFE` 由 EQ-1 v0.1 冻结口径计算（entry 后 10 根窗口等）；本研**不重算 CP / ETD**。
- `initial_risk` 由 `|entry − sl| × 100 × volume` 派生，属交易计划属性，ex-ante 可得。
- 方向性：完全中性，无「标准化后关系应更强 / 更弱」先验。

---

## 3. 样本边界（冻结）

- 仅 142 笔 `sl_trigger_price` 非空（= `exit_reason=sl`）。
- 68 笔无 `sl_trigger_price`：不补造 initial_risk，仅作 Selection Diagnostic。
- 不把 SL exit 本身当解释 Giveback 的研究条件。

---

## 4. 变量定义

继承 EQ-1 v0.1（per-trade，连续量）：

- `IAE_USD` = entry 后 10 根最大逆向 excursion × mult
- `Giveback_USD` = `max(0, MFE_usd − 退出有利部分)`（退出质量）
- `MFE_USD` = entry 后最大有利 excursion × mult
- `P&L_USD` = 该笔盈亏（USD）

新增（仅 142 SL 子集有定义）：

- `initial_risk = |entry_price − sl_trigger_price| × 100 × volume`（stop-distance risk proxy，非真实风险）
- `IAE_norm = IAE_USD / initial_risk`
- `Giveback_norm = Giveback_USD / initial_risk`
- `PnL_norm = P&L_USD / initial_risk`（**Secondary economic diagnostic**）

per-trade vs aggregate：

- per-trade：上述全部。
- aggregate（仅诊断，不进假设）：142 vs 68 描述性比较（Long/Short、ETD、P&L、MFE、IAE、Exit reason）。

---

## 5. 三组证据设计（A/B/C 联合）

- **A（Raw, Primary diagnostic）**：`IAE_USD → Giveback_USD`（复刻 H3）
- **B（Normalized, Primary diagnostic / 风险尺度敏感性检查）**：`IAE_norm → Giveback_norm`。B 不是标准化后的最终稳健性证明。
- **C（Denominator diagnostic）**：`initial_risk → IAE_USD`；`initial_risk → Giveback_USD`；报 `corr(initial_risk, IAE_USD)` 与 `corr(initial_risk, Giveback_USD)`。

联合解释：A、B、C 三者共同决定 H3 是否具有「非纯尺度解释」证据。不单独以 B 显著/强下结论。

---

## 6. 检验方法

- **Primary**：Spearman ρ（连续、分布未知）。
- **CI**：Fisher-z approximation，明确标注为 Spearman 的 descriptive approximation（非严格精确 CI；CI 方法敏感性 / bootstrap 归 v0.2，不引入新随机机制）。
- 三组证据全报告（A/B/C），不藏不显著组（多重比较透明）。
- **permutation null（诊断项，非硬 Gate）**：固定边际、保边洗牌、`stat = max|assoc| over A/B/C`、`N=2000`、`seed=20260816`（与 EQ-1 独立 provenance；仅 reproducibility，不随结果更换）。仅 borderline 诊断。
- 不追求 p<0.05；沿用「方向性 + 效应量 + CI 是否含 1」口径。

---

## 7. 选择偏差诊断（Selection Diagnostic，非 Rule）

142 vs 68 描述性比较六变量；仅暴露偏差，不筛选样本。严禁「142 更稳定所以只研究 SL」。结论仅覆盖 SL 子群体，不可外推 210。

---

## 8. 禁止事项（10 项）

1. 只使用 142 笔 `sl_trigger_price` 有效交易
2. 不补造 68 笔 initial_risk
3. 不把 SL exit 当解释条件
4. 报 142 vs 68 描述差但不筛选样本
5. 核心变量仅 `IAE_USD`/`Giveback_USD`（A）与 `IAE_norm`/`Giveback_norm`（B）；`PnL_norm` 仅 Secondary
6. 保留 raw USD 双轨
7. 不改 `k=2`/`W=48`
8. 不 mediation
9. 不参数敏感性
10. 不搜新 cutoff

---

## 9. 全报纪律

A/B/C 三组证据 + permutation + 142/68 诊断全部报告；选择偏差边界显式声明；`initial_risk` 语义（stop-distance proxy）每次出现标注。

---

## 10. Gate 0（冻结令牌 + eq1r_result=PENDING）

运行须校验：

- 预登记文档存在、`mtime < 运行时间`、版本 v0.1
- 冻结令牌齐全（见 `frozen_tokens`）：`seed=20260816` / `n_perm=2000` / `spearman` / `fisher_z_approx` / `sample=142` / `no_fabricate_68` / `initial_risk_def` / `raw_norm_dual` / `b_not_proof` / `abc_joint` / `pnl_secondary` / `no_mediation` / `no_param_sens` / `no_cutoff` / `k2_w48_inherit`
- `eq1r_result = PENDING` 才允许计算
- 任一不符 → `sys.exit(2)`，不产生结果

---

## 11. 决策规则

- 观察到 A/B/C 联合证据，描述 H3 在剥离 stop-distance 后剩余多少。
- 不声称「稳健」或「被混淆」为确定结论；只用效应量 + CI + 联合解释表述。
- 若 **B ≈ A 且 C 弱** → 表述为「证据支持 IAE→Giveback 非纯尺度解释」；若 **B 弱于 A 或 C 强** → 表述为「关系可能含 stop-distance 尺度成分，IAE 独立性待定」。
- 任何二次分析 / 深探 / mediation 须先冻结后跑，不在本轮。

---

## 12. 下一步

`--check` 通过 + 用户批准 → Code（纯 stdlib Observation-only，复用 EQ-1 数据接口）→ py_compile → Gate 0 → Run → 输出 `eq1r_observation_v0_1.json`。

---

*本文档为 EQ-1R 正式预登记，冻结值以 `RC-EQ1R-PREREG-v0.1.json` 的 Gate 0 校验为准。*
