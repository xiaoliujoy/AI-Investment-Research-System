# H1 Pre-Registration v0.1（预登记方案，冻结）

> **状态：PRE-REGISTRATION（已登记，未运行）。**
> 本文件与 `quant-lab/h1_universe_structure.py`（须经合规改造后）+ `docs/H1_Script_Compliance_Audit_v0.1.md` 共同构成 H1 契约。
> 原则：**先登记，后运行。** Gate 0 检查：本文件修改时间必须早于 H1 首次运行时间（脚本内校验）。
> 关联：`docs/ATS_System_Truth_Table_v1.0.md`（ATS 基线）；本实验处于 **Research 层，不触碰 Production / Strategy Contract / 自动执行**。

---

## 0. Gate 0 令牌（脚本必须逐字匹配，任一缺失即拒绝运行）

- `H1 Pre-Registration v0.1`
- `930955`
- `20150101` / `20260821`
- `qfq`
- `MA_FAST=20, MA_SLOW=60`
- `COMM=0.00025, STAMP=0.001/0.0005@2023-08-28, SLIP=0.001`
- `seed=20260821, n_boot=2000`
- `REGIME: 牛=close>MA250*1.05, 熊=close<MA250*0.95, 震荡=其余`

---

## 1. 研究问题

**H1 不是寻找策略，而是验证「研究对象是否值得进入策略研究」。**

具体回答：当前成分定义的高股息低波资产池，其历史日线是否存在跨时期、跨 regime 稳定可观测的波段结构，且该结构扣掉最基本的 A 股交易摩擦后是否仍具经济意义。

- **不是** Strategy Discovery。禁止输出任何「最佳参数 / 最佳持有期 / 最佳策略」。
- 输出：6 维结构基线表 + 三级 Gate 判定（PASS / FAIL / INCONCLUSIVE）。

---

## 2. 宇宙定义（Universe）

- **主宇宙** = 中证红利低波 930955 **当前成分股**（截至数据快照日的成分列表）。
- **Control** = **当前成分等权合成指数**（Current-Component Equal-Weight Synthetic Index）：100 只当前成分前复权 close 按各自首个有效值归一化后等权平均构造，用于 regime 划分与同源基线。
  - Erratum 001（2026-08-22 批准）：原 930955 官方指数因数据管道不可达，替换为本合成指数；"无偏差基线"表述删除（合成指数与主宇宙同源、共享生存者偏差）。

**标签（必须原样使用）**：
> **Current-Component Historical Structure Benchmark**

**Survivorship Bias Status：KNOWN LIMITATION。**

- 本基线回答的问题是：「今天这批成分股，把它们的历史价格拿回来观察，是否存在结构性特征？」
- **不得**写成「930955 历史成分篮子的真实历史结构」。
- 真正的 point-in-time 历史成分动态宇宙 = 后续更高等级的数据工程，**不属于 H1 范围**。H1 不等待它，但必须标记为已知限制。

---

## 3. 样本区间

**2015-01-01 ~ 2026-08-21（冻结）。**

覆盖 regime：2015 股灾 / 2016-17 震荡 / 2018 熊市 / 2019-21 牛市 / 2022 熊市 / 2023-24 弱市 / 2025-26 当前阶段。

**核心动机：结构必须跨 regime 存在，而不是某一段行情里的漂亮曲线。**

---

## 4. 数据口径（Data Contract）

| 项 | 冻结定义 |
|---|---|
| 数据源 | AKShare：`stock_zh_a_hist`（个股）、`index_zh_a_hist`（指数） |
| 复权 | 前复权 `qfq`（波段研究必须用复权价） |
| 数据版本 | 记录 AKShare 版本 + 下载时间戳 + 成分快照日期 → 形成数据版本号，写入输出 |
| 停牌识别 | 无成交 / 当日 NaN → 标记停牌日，不可成交 |
| 涨跌停识别 | 主板涨跌幅 ≥ 9.8%、创业板/科创板 ≥ 19.8% 视为涨停（买入不可成交）；≤ −9.8% / −19.8% 为跌停（卖出不可成交） |
| 价格异常 | 收盘 ≤ 0、单日跳变 > 50% 且非停牌 → 标记异常，计入 Data Gate |
| 复权一致性 | 抽检相邻日涨跌幅与前复权系数，确认无拼接跳变 |
| Data Snapshot | 首次运行前冻结数据集与成分列表，存快照，保证可复现 |

---

## 5. 指标定义（6 维，全部事前冻结）

### D1 收益特征（诊断项，不参与 Gate）
CAGR、年化波动率（日 std × √242）、最大回撤、Calmar。

### D2 时间序列特征
- 日收益 lag-1 自相关 ρ(1)，bootstrap 95% CI（`seed=20260821, n_boot=2000`）。
- ρ(1) > 0 偏动量 / < 0 偏反转，由 CI 是否含 0 判定显著。

### D3 波段特征
- **MA20/60 多头持仓日正收益占比**（标签明确：持仓日胜率，**非交易胜率**）。
- **完整波段胜率**：从 MA20>MA60 金叉进场到 MA20<MA60 死叉出场为一次波段，波段收益 >0 为胜。
- **回撤恢复概率**：从 −5% 回撤起，60 个交易日内收复的比例。
- **突破持续性**：创 20 日新高后，未来 5/10/20 日前向收益中位数。

### D4 横截面特征
- 成分股年化波动的离散度（std / IQR）。
- 成分股日收益相关矩阵的均值（同质化程度）。

### D5 市场环境依赖（Regime，核心输出）
- Regime 定义基于 **当前成分等权合成指数** vs 自身 MA250（point-in-time，无 look-ahead）：
  - 牛：close > MA250 × 1.05
  - 熊：close < MA250 × 0.95
  - 震荡：其余
- 分桶重算 D2/D3 关键指标；**核心输出 = 结构是否跨 regime 同号存在**。
- Erratum 001（2026-08-22）：原「930955 指数」替换为合成指数（见 §2）。

### D6 交易摩擦
- 同时输出 **gross（毛）与 net（净）** 与 **Friction Drag（= gross − net）**。
- net = gross 扣 佣金 + 印花税 + 滑点 + T+1 约束 + 涨跌停/停牌不可成交。
- Gross 回答「有没有统计结构」，Net 回答「结构有没有经济意义」，两者必须分开。

---

## 6. 摩擦模型（Execution Contract）

只冻结最基本的交易经济学，**不升级为逐笔撮合**（那是 RQAlpha 阶段）：

| 项 | 参数 |
|---|---|
| 佣金 | 双边 0.00025（万 2.5） |
| 印花税 | 卖出：0.001（t < 2023-08-28），0.0005（t ≥ 2023-08-28） |
| 滑点 | 单边 0.001（10 bps） |
| T+1 | 信号在 t 日收盘计算，t+1 开盘执行；买入当日不可卖出 |
| 涨跌停 | 涨停日跳过买入、跌停日跳过卖出 |
| 停牌 | 跳过 |

> 参数写在本契约，**不得散落在代码里**（脚本须引用本文件或集中常量 + 契约版本号）。

---

## 7. Regime 定义

见 D5。**冻结于 v0.1，不得因结果调整阈值。**

---

## 8. 三级机械 Gate（全部事前冻结，禁止看结果后设计）

### Gate 1：Data Integrity
- 覆盖 ≥ 80% 股票 × ≥ 90% 交易日；
- 无未修复的价格异常；
- 数据版本号记录完整。
- **FAIL → H1 直接终止（INCONCLUSIVE），需重拉/修复数据，禁止带病运行。**

### Gate 2：Structural Evidence
- 结构存在：(G2a) 篮子日收益 ρ(1) 的 95% CI 不含 0，或 (G2b) MA20/60 持仓日正收益占比的 95% CI 下界 > 50%；
- **且** 该结构在 ≥ 2 个 regime 中方向一致（regime stability）。
- **禁止**用 CAGR / Sharpe / PF 单独定义结构存在——那已经接近策略评价。

### Gate 3：Economic / Friction
- 代表性规则 = MA20/60 多头（冻结参数，作为「结构的经济表达」，**不是最优策略**）；
- PASS = 该规则 net 期望的 bootstrap 95% CI 下界 > 0；
- 若 gross 成立而 net 消失 → **FAIL，不救**（不回头调摩擦参数、不找替代规则）。

### Overall
- G1 + G2 + G3 全过 = **PASS**
- G1 过，G2 或 G3 任一不过 = **FAIL**
- G1 不过 = **INCONCLUSIVE**（数据不可信，结果无意义）

---

## 9. 输出契约

```text
H1_RESULT
├── Data Gate        : PASS / FAIL
├── Structural Gate  : PASS / FAIL
├── Economic Gate    : PASS / FAIL
├── Overall          : PASS / FAIL / INCONCLUSIVE
└── 6 维诊断表（D1~D6，含 gross/net/drag、regime 分桶）
```

**禁止输出**：任何「最佳参数 / 最佳持有期 / 最佳策略」、任何参数扫描结果。一旦出现即视为 research flexibility，该输出作废。

---

## 10. 依赖与环境

- 仅：`pandas`、`numpy`、`akshare`、`scipy`（bootstrap CI）。
- **不安装 RQAlpha / VectorBT**（对 Python 3.13 兼容性未知，且 H1 阶段不需要）。
- 若 H1 PASS → H2 研究问题冻结后，再决定是否建 Python 3.11 独立回测环境装 RQAlpha/VectorBT。

---

## 11. 执行顺序（严格）

```
H1 Contract → Script Audit → Script Modification → Data Snapshot → H1 Run → Gate Evaluation
```

**禁止**：Script → Run → 看结果 → 修改研究问题。

---

## 12. 已知限制（Known Limitations）

1. **Survivorship Bias = KNOWN LIMITATION**（当前成分回溯历史，收益可能系统性偏高）。
2. 无 point-in-time 历史成分数据（AKShare 不直接提供；升级为动态宇宙是未来更高等级数据工程）。
3. AKShare 接口可用性/字段变化风险（通过记录数据版本控制）。
4. 前复权在除权除息密集处的近似（通过复权一致性抽检控制）。
5. **Regime/Control 为合成指数（Erratum 001）**：与主宇宙共享同一生存者偏差，不再具备官方指数意义上的"无偏差基线"；成分含后上市股会缩短合成指数有效历史长度（以 MA250 计算时首 250 日无 regime 判定）。

---

## 13. 禁止事项（Forbidden）

- ❌ 不因结果漂亮调整研究问题或指标定义。
- ❌ 不输出最佳参数 / 最佳持有期 / 最佳策略。
- ❌ 不因 net 消失而调摩擦参数「救回」结构。
- ❌ 不把 H1 结果当成可交易策略。
- ❌ 不把 Current-Component benchmark 说成指数历史真实结构。
