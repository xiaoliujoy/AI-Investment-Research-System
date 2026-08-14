# H2：Pre-Trade Entry Archetype 定义草案 v0.1

> 本文件与 `backend/output/research_contracts/RC-ENTRY-ARCHETYPE-ID-v0.1.json` 共同构成 **H2 的 Research Contract**。
> 状态：**定义草案（DEFINITION ONLY）**——本步骤不跑实验、不算特征、不比较标签。

---

## 0. 核心原则（先定调，再干活）

**现在不能说「E2 是 Entry Archetype」；只能说「E2 是一个事后结果分型（post-trade result classification）」。**

下一步的核心任务，是把它从 Post-Trade Label 转化为可在 `entry_time` 时点复现的 **Pre-Trade State**。

- E2（anticipatory_suffered）在当前数据中 = 事后用 MFE/MAE/PnL 反推的标签，**不可在交易当时识别**（见 `entry_archetype_identifiability_audit_v0.1.json`，look-ahead = HIGH）。
- 因此「E2 + Trailing 有效」目前是一个 **hindsight artifact**，不构成可实盘执行的策略，禁止升级为策略。

---

## 1. 路径选择

| 路径 | 优点 | 问题 | 决策 |
| --- | --- | --- | --- |
| (a) 人工记录入场意图 | 最接近真实交易逻辑 | 新增数据、主观性强、无法回溯历史 | **延后** |
| **(b) 机械 Pre-Trade State** | 可回溯 210 笔、客观、可计算、可复现 | 需验证是否真能解释 E2 | **现在做** |

走 (b)。(a) 待有结构化录入手段后再议。

---

## 2. 关键边界：禁止「为复现 E2 设计变量」

否则会产生**第二层 look-ahead bias**：

> 先看到 E2 → 再寻找能解释 E2 的事前变量 → 再用这些变量重新定义 E2。

正确流程必须反过来：

```
historical data
      ↓
冻结 Pre-Trade 可用信息集合（变量集，不含阈值）
      ↓
定义机械状态（对冻结集的确定性规则）
      ↓
生成 Archetype（在 entry_time 给每笔打标签）
      ↓
再与历史 E1-E4 结果标签比较
      ↓
判断是否具有解释力
```

**变量集必须在「看见 E2 关联」之前冻结；关联比较必须在 Archetype 生成之后才发生。**

---

## 3. Entry-time Information Set（冻结变量集，暂不设阈值）

> 约束：所有变量 **只能读取 `t ≤ entry_time` 的信息**。
> 代码层强制：`feature_timestamp <= entry_timestamp`，否则拒绝生成 Archetype。

### 3.1 Price Structure（价格结构）
- `entry_vs_range[N]`：入场价相对近 N 根高低点的归一化位置，`N ∈ {20, 50, 100}`
- `breakout_status`：入场价是否越过此前摆动高点 / 低点（摆动由 N 根 fractal 定义）
- `breakout_distance_pct`：入场价相对前摆动高的超出幅度（%）
- `dist_to_prior_high_low`：相对前高 / 前低的归一化距离

### 3.2 Trend（趋势）
- `multi_tf_direction[tf]`：多周期趋势方向，`tf ∈ {D1, H4, H1}`，由 `close ≤ entry_time` 的 `close vs MA_tf` 判定
- `ma_slope`：MA 在回看窗口上的斜率符号
- `trend_consistency`：多周期方向一致的比例（对齐周期数 / 总周期数）

### 3.3 Volatility（波动）
- `atr_entry`：入场时 ATR(14)
- `atr_pctile`：入场 ATR 在回看 100 根 ATR 分布中的分位排名
- `vol_state`：入场 ATR 相对回看均值 ATR 的比值（扩张 / 收缩）

### 3.4 Confirmation（确认）
- `breakout_before_entry`：入场前是否发生过突破（bool）
- `breakout_duration_bars`：自突破至入场的 K 线数
- `pullback_confirm`：入场前 N 根内价格是否回踩突破位并守住（bool）

### 3.5 Regime（市场状态，须为事前变量）
- `regime_label`：trend / range / transition，由事前可算指标判定（如 ADX<20 为 range，ADX>25 且方向明确为 trend，状态切换检测为 transition）

### 3.6 Entry Location（入场位置）
- `dist_to_trigger`：入场价相对触发 / setup 位的归一化距离
- `entry_expansion`：入场价相对当根 K 线区间的位置（近高点 = 扩张 / 追价；近中点 = 非追价）
- `chasing_state`：入场是否处于近 N 根高点且伴随同期波动扩张（bool）

> 以上 6 类变量为 **SPEC 提案**，具体阈值 / 二分切点将在 H2-A 执行时**预先登记（pre-register）**，绝不从 E2 结果反推。

---

## 4. 代码层约束（草案，待执行阶段实现）

- `PreTradeFeatureSet`：给定 `entry_time` 与 K 线迭代器，**只访问 `timestamp <= entry_time` 的 bar**；任何越界访问直接 `raise`。
- Archetype 生成函数必须是冻结变量集的**纯函数**，不得引用任何结果变量（MFE / MAE / PnL / capture / E1-E4 标签）。
- 静态断言：`feature_timestamp <= entry_timestamp` 对所有特征成立，否则拒绝产出 Archetype。

---

## 5. 两个 Gate（每层独立过，防止「好分组 → 配 Exit → 宣布 Edge」）

### H2-A：Identifiability（可识别性）
- **问题**：历史上的 E2，能否仅凭事前信息稳定识别？
- **方法**：用**仅冻结集**定义机械 Archetype（定义时**不看 E2**），给 210 笔打 entry_time 标签，再与历史 E2 标签比较分布。
- **预登记指标**（执行前固定，含阈值 τ 与稳定性检验）：
  - 关联度量 M：候选「anticipatory」类的 lif / mutual information / chi-square（择一，事前定）
  - 稳定性：按时间切分（如 cutoff 日期前后），关联须在**两段同时**满足 M > τ
- **决策**：
  - PASS → 进入 H2-B
  - FAIL → **终止 E2-conditioned Exit 路线**；记录 E2 为纯事后 artifact；不进 H2-B / OOS

### H2-B：Incremental Value（增量价值）
- 仅当 H2-A PASS。
- **问题**：即使能识别 E2，E2 条件化 Exit 是否优于统一 Exit？
- **方法**：在 H1 同口径（Signal/Entry/Stop/Position/Data/Cost 全固定，Exit = 唯一变量）下，仅对 Pre-Trade Archetype 命中的交易施加 trailing（或选定 Exit），与统一 Exit 对比。
- **预登记指标**：H1 的 6 指标（Net P&L / PF / MFE Capture / Giveback / MaxDD / Trade Distribution）。PASS = 条件化在命中子集上改善 **且** 改善非单笔驱动。
- **决策**：PASS → 进 OOS → Robustness；否则终止。

---

## 6. H2 第一阶段「不要做」清单

- 不优化分类器
- 不训练 ML
- 不搜索最佳阈值
- 不以 P&L 作为分类依据
- 不以 MFE / MAE / capture 参与 Archetype 定义
- 不用 E1/E2/E3/E4 标签反向选择特征
- 不直接测试 trailing 参数

**本阶段只回答一个更基础的问题**：历史上的 E2，能否被 entry_time 当时已存在的信息稳定识别？

---

## 7. 当前研究状态

```
Research Contract       FROZEN
        ↓
Exit H1                 REPRODUCED
        ↓
E1-E4 attribution       REPRODUCED
        ↓
E1-E4 identifiability   FAILED / LOOK-AHEAD
        ↓
H2 Pre-Trade Archetype  NEXT（本文件 = 定义草案）
        ↓
H2-A Identifiability
        ↓
H2-B Incremental Exit
        ↓
OOS
        ↓
Robustness
```

**可信度：高，约 95%。**
唯一尚未确定：是否存在一组真正的、事前可得的市场状态变量，可稳定映射到原来的 E2。这是 H2-A 要回答的问题。

---

## 8. 下一步（待用户批准）

本文件仅交付**定义**。执行阶段（H2-A）的对应用法草案、预登记指标与阈值、切分方式，将在用户批准后另立 `exit_observation_h2a` 类脚本；当前不写、不跑。
