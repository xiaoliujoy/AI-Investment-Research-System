# EQ-1 · CP-D Specification Review v0.1

> 配套 `docs/EQ1_Methodology_Review_v0.1.1.md` 与 `docs/EQ1_PreRegistration_v0.1.md`。
> 本文只解决 **Confirmation Point (CP) 的摆点算法规格**，不碰代码、不跑 210 笔交易、不对任何参数做数据驱动调优。
> **状态：六参数已由用户于 2026-08-15 冻结，进入 EQ-1 Pre-Registration v0.1。**

---

## 0. 纪律红线（本文适用）

1. **禁止数据窥探**：k / W / price field / tie / no-CP 的取值，一律来自市场结构理论、M5 数据频率、可复现性要求，**不看 210 笔结果反选**。
2. **参数敏感性 ≠ 调参**：任何「换个 k 看分布变不变」的检查，都归入 v0.2 独立预登记研究，不在此轮作为调参循环。
3. **ex-ante 铁律**：CP 只由 `close_time <= entry_unix` 的已收盘 bar 计算（复用 H2-A 的 `bisect_right(times, entry_unix-300)` 纪律，杜绝微观前视）。
4. **v0.1 故意粗糙**：不加 trend / ATR / swing-strength filter，不设计 fallback。任何「更聪明」的摆点都进 v0.2 单独预登记。

---

## 1. CP-D 定义（方向已冻结）

```
CP = entry 之前最近的、满足预先登记局部极值规则的方向性 swing point。
Long  → 最近 swing high
Short → 最近 swing low
```

研究真正检验的是：

```
ETD  →  IAE / MFE
```

而不是「确认入场比提前入场好」。ETD 只度量 entry 在客观市场结构中的时间位置，不预设质量方向。

---

## 2. 六参数规格审查（已冻结）

### 2.1 swing 数学定义（严格局部极值）

给定 M5 bar 序列、索引 `i`、确认半径 `k`：

- **Long / swing high**：`High[i] > High[i-j]` 且 `High[i] > High[i+j]`，对 `j = 1..k` 全部成立
- **Short / swing low**：`Low[i] < Low[i-j]` 且 `Low[i] < Low[i+j]`，对 `j = 1..k` 全部成立
- 边界：要求 `i-k >= 0` 且 `i+k < len(prior_bars)`（窗口内才能判极值）

即标准 **严格 `(2k+1)` 窗口局部极值**。严格不等号保证每个窗口内极值唯一，正常数据下无并列。

### 2.2 `k`（左右确认根数）—— 已冻结 `k=2`

| 取值  | 问题                                                  |
| --- | --------------------------------------------------- |
| k=1 | 只要比相邻两根高/低即判摆点 → 震荡市几乎每根都是摆点，ETD 被局部噪声主导，无结构含义      |
| k=5 | 需要左右各 5 根严格更低/高 → 真正有意义的摆点大量漏判，ETD 被拉得很长，且易触发 no-CP |

**冻结：`k = 2`**

- 方法学选择（非事后验证）：`k=2` 是一个低复杂度、最小的非相邻局部结构定义，在 M5 频率下能够避免 `k=1` 过度依赖单根相邻波动，同时保留较高的结构事件密度。
- 这不证明「k=2 一定不是噪声」——它只是本轮选定的、可被第三方复现的机械定义。
- `k ∈ {1, 2, 3}` 的敏感性分析归入 v0.2 独立预登记研究，不是调参循环。

### 2.3 `W`（向前搜索根数）—— 已冻结 `W=48`

**冻结：`W = 48` M5 bar（= 4 小时）**

- `W` 是**搜索窗口，不是研究假设**。我们真正研究的是 `ETD = Entry − CP`，不是「W 越大越好」。
- `W=48` 代表「寻找 entry 前约 4 小时内最近的方向性结构点」：对 M5 entry 给了足够的结构上下文，同时仍保持 CP 是 entry 前**近期**结构而非无限期历史结构。
- 你明确支持 48 而非 24：24 会把 CP 强限制在当前短线波动结构里，可能让 CP 对短线局部结构过度敏感；48 是合理的有界结构定义，不强行压窄。
- `W=48` ≈ 4 根 H1，覆盖你 M5 entry 通常参照的 H1 回撤腿端点（M5 上约 12–36 根），同时排除跨 session 远古摆点；典型 ETD 落在 3–20 根，48 只作天花板使 `ETD_bars <= 48` 天然有界。
- 关键：k=2 + W=48 下，48 根内存在合格摆点的概率≈1，no-CP 几乎不触发（见 2.6）。

### 2.4 price field（High / Low / Close）—— 已冻结 `High / Low`

**冻结：`swing high → High`，`swing low → Low`**

- 拒绝 Close：CP 定义为「潜在阻力/支撑」，而支撑阻力由**影线极值**定义，不是收盘。Close-based 摆点与阻力/支撑语义错位。
- 严格用对应极值字段，与方向性定义天然一致。

### 2.5 tie rule（并列极值处理）—— 已冻结

- **选择规则**：在 `index < entry_reference_bar_index` 的合格摆点中取**时间戳最大（离 entry 最近）**者。
- **tie rule**（仅在两摆点极值价格相等时生效）：**取更晚（离 entry 更近）的那根**。
- 严格不等号下，相邻 bar 极值相等近乎不可能，故 tie rule 实际退化为「最近者胜」，无额外复杂度。

### 2.6 no-CP 处理 —— 已冻结

**冻结：No-CP = 排除该笔交易，并报告 exclusion rate**

- 不做 fallback（不退回「取次近摆点 / 取中枢 / 取前高」等任何特殊规则）——fallback 会重新打开研究自由度。
- 报告格式：`exclusion_rate = n_excluded / n_total`，作为诊断量随结果公开。
- 因 k=2 + W=48 下摆点几乎必存在，no-CP 是安全网而非常触发路径。

### 2.7 minimum separation —— 无独立参数

**Minimum separation：不设置独立参数。**

Swing 是否成立完全由严格 `(2k+1)` 局部极值规则决定。该规则只保证**单个** swing point 需要左右各 `k` 根参与确认；它**不必然推出两个同方向 swing point 之间的最小间隔下界**（尤其在不同极值类型交替时，两局部高点之间完全可能以小于 `2k+1` 的距离各自满足局部条件）。

因此本文**不声明任何「minimum separation = 2k+1」的数学必然性质**，避免把未被定义保证的推论写进规格。这是方法学表述的纠正，不改变任何研究设计。

---

## 3. ETD 双单位定义（已冻结）

| 单位              | 定义                                          | 角色          |
| --------------- | ------------------------------------------- | ----------- |
| **ETD_bars**    | `entry_reference_bar_index − cp_bar_index`（整数 ≥ 1） | **Primary** |
| **ETD_minutes** | `(entry_timestamp − cp_timestamp) / 60`      | Secondary   |

- **entry_reference_bar（关键定义）**：`entry timestamp` **之前最后一根已收盘 M5 bar**。**绝不使用 entry 所在的 forming bar**——这正是 H2-A 抓出过的微观前视坑。
  - 例：entry 发生在 `18:49:27`，entry bar `18:45–18:50` 在 `18:49:27` 尚未收盘 → `entry_reference_bar` = `18:40` 那根（最后已收盘 bar），ETD 从该 bar 起算。
  - 代码层：用 `bisect_right(times, entry_unix - 300)` 取 `close_time <= entry_unix` 的已收盘 bar 作为 entry 时间参考点，与 CP 的计算纪律一致。
- Primary 选 **ETD_bars**：直接对应 M5 数据结构，整数、确定、无时区/会话歧义。
- Secondary 保留 ETD_minutes：XAUUSD 非完全规则连续时间轴（周五收盘→周日开盘有 gap），bar 数与真实 elapsed time 可能背离，故两者含义不同、都报。

---

## 4. v0.1 明确不做的事

- 不加 trend filter（不在摆点判定里引入更高周期方向）
- 不加 ATR / volatility filter
- 不加 swing-strength filter（不要求摆点「幅度够大」）
- 不设计 no-CP fallback
- 不对摆点做聚类 / 多摆点融合
- 不声明任何 minimum separation 数学下界

任何上述增强 = 独立预登记（v0.2+），不是本轮调参。

---

## 5. 方向性偏差（已知局限，v0.2 处理）

Long 的最近 swing high 可能只是局部噪声，未必是交易者实际交易的那段结构的端点。

- v0.1 **接受此局限**（故意粗糙）。
- v0.2 可预登记更严的摆点定义（例如要求该 swing 是价格曾回踩/反弹验证过的「被尊重的」摆点），但必须是**独立研究、先冻结后跑**，不能回灌本轮。

---

## 6. 可复现性 / ex-ante 保证

- CP 计算完全确定：给定 `(k, W, price field, tie rule, no-CP)` 无随机性、无优化器。
- 只读取 `close_time <= entry_unix` 的 bar（微观前视已堵）。
- 同一种子数据上结果逐次一致，可被第三方独立复现。

---

## 7. 冻结清单（已冻结）

| 参数                 | 冻结值                   | 依据                       | 状态     |
| ------------------ | --------------------- | ------------------------ | ------ |
| swing 定义           | 严格 `(2k+1)` 局部极值      | 标准、唯一、确定                 | ✅ 已冻结 |
| `k`                | 2                     | 低复杂度最小非相邻结构定义；方法学选择      | ✅ 已冻结 |
| `W`                | 48（4h）                | 有界结构窗口，非研究假设；避短线过度敏感   | ✅ 已冻结 |
| price field        | High / Low            | 阻力支撑由影线极值定义              | ✅ 已冻结 |
| tie rule           | 最近者胜；等价格取更晚           | 严格不等号下退化为最近              | ✅ 已冻结 |
| no-CP              | 排除 + 报 exclusion rate | 杜绝 fallback 重开自由度          | ✅ 已冻结 |
| minimum separation | 无独立参数，由 swing 定义自然决定   | 不写未被定义保证的数学下界           | ✅ 已冻结 |
| ETD_bars           | Primary               | 对应 M5 结构、整数确定            | ✅ 已冻结 |
| ETD_minutes        | Secondary             | gap 下与 bars 含义不同         | ✅ 已冻结 |
| entry_reference_bar | entry 前最后已收盘 M5 bar    | 杜绝 forming bar 微观前视       | ✅ 已冻结 |

---

## 8. 下一步

CP-D 六参数已冻结，正式冻结动作写入 `EQ-1 Pre-Registration v0.1`。下一步：

1. 预登记 `--check` 通过 → Code → Compile → Run。
2. 全程零数据窥探；任何参数敏感性归入 v0.2 独立预登记。

---

## 9. CP-D 最终冻结协议（逐字，供 Pre-Registration 引用）

> **CP-D**
>
> CP 是 entry timestamp 之前、最近 W 根已收盘 M5 bar 中满足严格 `(2k+1)` 局部极值规则的方向性 swing point。
>
> Long 使用最近 swing high，Short 使用最近 swing low。
>
> `k=2`，`W=48`。
>
> ETD 的参考点为 entry timestamp 之前最后一根完整收盘 M5 bar。
>
> Primary exposure：
>
> `ETD_bars = last_closed_bar_index − CP_bar_index`
>
> Secondary：
>
> `ETD_minutes = (entry_timestamp − CP_timestamp) / 60`
>
> 若 W 窗口内不存在合格 CP，则排除该交易并报告 exclusion rate，不使用 fallback。

---

*本文档为 CP-D 规格审查，冻结值以 §7 / §9 为准。正式运行以 `EQ-1 Pre-Registration v0.1` 的 Gate 0 校验为准。*
