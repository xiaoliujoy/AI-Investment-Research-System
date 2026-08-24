# H1 Script Compliance Audit v0.1（合规审计，未运行前审查）

> **关联契约**：`docs/H1_PreRegistration_v0.1.md`（v0.1，冻结）
> **审查对象**：`quant-lab/h1_universe_structure.py`（2026-08-21 06:45 草稿，**尚未运行**，无 `h1_result.csv`）
> **处置动作说明**：`保留` = 与契约一致，可直接用；`修改` = 方向对但需按契约改口径/加结构；`删除` = 与契约冲突或属 research flexibility；`新增` = 契约要求但脚本缺失。
> **结论**：草稿可作为骨架，但**不得直接运行**。必须按本审计改造后方可进入 Data Snapshot → Run。

---

## 1. 逐项审计表

| # | 位置 | 现状 | 处置 | 审计意见 |
|---|---|---|---|---|
| 1 | 文件 docstring | 只写「高股息篮子是否有可交易结构」，无契约引用 | 修改 | 改为引用 H1 Contract v0.1，标注 `Current-Component Historical Structure Benchmark` + `Survivorship Bias = KNOWN LIMITATION`，并声明 Gate 0 |
| 2 | `UNIVERSE_INDEX = "930955"` | 中证红利低波 | 保留 | 与契约一致；但需补 **指数价格序列 Control**（新增 index 拉取） |
| 3 | `START="20150101", END="20260821"` | 与契约一致 | 保留 | 冻结区间 |
| 4 | `QFQ="qfq"` | 前复权 | 保留 | 与契约一致 |
| 5 | `MA_FAST=20, MA_SLOW=60` | 均线参数 | 保留 | 与契约一致（结构性指标，非策略参数） |
| 6 | `import akshare` 等 | 仅 pandas/numpy/akshare | 修改 | 新增 `scipy`（bootstrap CI）。**不装 RQAlpha/VectorBT** |
| 7 | `get_universe()` | 拉当前成分，双接口回退 | 修改 | 补：记录成分快照日期 + AKShare 版本 + 下载时间戳 → 数据版本号；明确标注「当前成分」 |
| 8 | `get_daily()` | 仅取 `date/close` 两列 | 修改 | **严重不足**。需保留 `high/low/涨跌幅/成交量` 等列，否则无法做涨跌停识别、停牌识别、价格异常检查（契约 D4/§6） |
| 9 | `get_daily()` | 无停牌/涨跌停/异常处理 | 新增 | 按契约 §4：停牌标记、涨跌停阈值（主板±9.8% / 创业科创±19.8%）、价格异常标记 |
| 10 | `get_daily()` | 无复权一致性检查 | 新增 | 抽检相邻日涨跌幅与前复权系数 |
| 11 | `analyse()` 的 `if len(ret) < 250: return {}` | 硬编码最小样本 | 修改 | 改为 Data Gate 判据（≥90% 交易日覆盖），不在此处静默丢弃 |
| 12 | `vol = ret.std()*sqrt(242)` | 年化波动 | 保留 | D1 诊断项 |
| 13 | `ac1 = ret.autocorr(lag=1)` | 一阶自相关 | 修改 | 补 bootstrap 95% CI（`seed=20260821, n_boot=2000`），这是 G2a 判据 |
| 14 | `ma_f / ma_s / pos` | MA20/60 多头 | 保留 | 方向正确 |
| 15 | `strat_ret = ret * pos.shift(1)` | 次日执行（无 look-ahead） | 保留 | 与 T+1 兼容；但需补：涨跌停/停牌日跳过、gross/net 双轨 |
| 16 | `win_rate = (strat_ret > 0).mean()` | 持仓日正收益占比 | 修改 | 契约要求**明确标签**为「持仓日胜率（非交易胜率）」；并**新增完整波段胜率**（金叉→死叉） |
| 17 | `equity / strat_mdd / price_mdd` | 回撤 | 保留 | D1 诊断项 |
| 18 | — | 无「回撤恢复概率」 | 新增 | D3：从 −5% 回撤起，60 日内收复比例 |
| 19 | — | 无「突破持续性」 | 新增 | D3：创 20 日新高后 5/10/20 日前向收益 |
| 20 | — | 无横截面分析 | 新增 | D4：成分股年化波动离散度（std/IQR）、相关矩阵均值 |
| 21 | — | 无 regime 分桶 | 新增 | D5：930955 vs MA250 分牛/熊/震荡，分桶重算 D2/D3，输出跨 regime 同号性 |
| 22 | `main()` 取全篮子中位数 | 只出中位数 | 修改 | 补横截面离散（std/IQR/分位）；分 regime 汇总 |
| 23 | 底部 print「解读」与内联阈值（vol<25%、win>50% 等） | 把阈值写进代码 | **删除** | 属「看结果前预设解读门槛」，与 Gate 设计冲突；阈值只存在于契约 Gate，脚本只输出事实 |
| 24 | `out = "quant-lab/h1_result.csv"` | 固定覆盖写 | 修改 | 版本化输出（带数据版本号/时间戳），并补 `H1_RESULT` 结构（三个 Gate + Overall + 6 维表） |
| 25 | — | 无 Gate 0 校验 | 新增 | 运行前校验契约令牌 + 契约文件 mtime < 运行时间，不符则拒绝运行 |
| 26 | — | 无 Data Snapshot | 新增 | 首次运行前冻结数据与成分快照，保证可复现 |

---

## 2. 处置汇总

| 处置 | 项数 | 明细 |
|---|---|---|
| 保留 | 7 | #2,3,4,5,11→部分,12,14,15→部分,17 |
| 修改 | 8 | #1,6,7,8,11,13,16,22,24 |
| 删除 | 1 | #23 |
| 新增 | 10 | #9,10,18,19,20,21,25,26 + 指数 Control + net/friction 双轨 |

---

## 3. 改造后必须验证的事（进入运行前 Checklist）

- [ ] Gate 0 令牌逐字匹配，契约 mtime 检查通过
- [ ] 数据版本号（AKShare 版本 + 下载时间戳 + 成分快照日期）已记录
- [ ] 涨跌停/停牌/价格异常识别已实现并测试（样本抽查）
- [ ] bootstrap CI 种子固定（`seed=20260821`），可复现
- [ ] gross / net / drag 三列同时输出
- [ ] regime 分桶无 look-ahead（用 930955 指数，MA250 为当日可得）
- [ ] 输出不含任何「最佳参数 / 最佳持有期 / 最佳策略」
- [ ] RQAlpha / VectorBT 未安装、未 import

---

## 4. 审计结论

**草稿方向正确（尤其 `pos.shift(1)` 的次日执行无 look-ahead），但距离契约合规缺少约一半工作量。** 核心缺口：(a) 数据层只取 close 两列，无法做涨跌停/停牌/异常识别；(b) 无 regime 分桶与横截面；(c) 无 gross/net；(d) 无 Gate 0 与 Data Snapshot；(e) 代码内联解读阈值需删除。

按契约 §11 顺序：本审计通过后 → Script Modification → Data Snapshot → H1 Run → Gate Evaluation。**当前不得运行。**
