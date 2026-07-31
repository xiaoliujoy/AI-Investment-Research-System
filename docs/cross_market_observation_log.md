# Cross-Market Observation Log (v2) — Trading OS 3.0-alpha

> **跨市场传导观察层（Observation Layer，非决策层）**。冻结期（2026-07-30 起 60 天）作为
> **Research Note 的分析模块 + 手工样本积累**，不建引擎、不产生任何交易信号。
>
> **定位**：这不是「看盘笔记」，而是 **Cross-Market Observation Dataset（跨市场观察数据集）**——
> 与 `asset_intelligence_history` 同一逻辑：市场变化 → 结构化观察 → 记录假设 → 未来验证 → 形成统计 → 修正认知。
> 现在积累的样本，是未来 `market_linkage` 引擎的**训练数据**：先搞清楚「哪些观察值得成为因子」，再决定进不进模型。
>
> **填写方式**：每个交易日收盘后，按下方「v2 八字段」手工补一段。数字尽量填实际涨跌幅；无数据标 `—`。
> 每周五 Research Note 自动从本文件抽取本周条目，汇入《Cross-Market Observation》页。
>
> ⚠️ 本文件**全部是观察，不含任何买卖建议**。v2 升级（2026-07-31）强化了**事件定义 / 对象字段 / 事实-假设分离 / 反例 / Regime 上下文**，专为 9/30、12/31 Checkpoint 的可统计性服务。

---

## 0. 定义标准（必读，保证未来可统计）

### Market Move Definition（涨跌幅阈值，统一口径）

| 事件类型 (Event Type) | 指数单日涨跌幅 | 标记 |
|----------------------|----------------|------|
| 大涨 (Surge)         | ≥ +1.5%        | SURGE |
| 明显上涨 (Up)        | ≥ +1.0%        | UP |
| 震荡 (Range)         | -1.0% ~ +1.0%  | RANGE |
| 明显下跌 (Down)      | ≤ -1.0%        | DOWN |
| 大跌 (Crash)         | ≤ -1.5%        | CRASH |

> 以后统计「KOSPI SURGE 后次日 A股上涨概率」才有统一标准，不再是人工描述「韩股大涨」。

### Market Object（市场对象字段，区分传导真正载体）

| 区域 | 对象 (Object) | 备注 |
|------|---------------|------|
| 韩国 | KOSPI | 综合 |
| 韩国科技 | KOSDAQ | 创业板性质 |
| 韩国半导体 | KR Semiconductor Index / SK Hynix | 真正传导载体常在此 |
| 美国 | NASDAQ / S&P 500 | |
| 美国AI | SOX / NVIDIA | AI 资本开支锚 |
| 台湾 | TAIEX / 台积电 | |
| 香港 | HSI / HS Tech | |
| 中国A股 | 创业板 / 沪深300 / 上证 | |
| 中国AI产业链 | 算力 / 光模块 / 芯片ETF | A股侧传导落点 |

> 真正的传导链往往不是「韩国 → A股」，而是 `NVIDIA → SOX → SK Hynix → 韩国半导体 → 中国AI产业链`。
> 记录时**必须填 Object**，否则未来研究价值差异巨大。

---

## 1. v2 八字段模板（每个交易日填一份）

```
Date: 2026-MM-DD (领先市场日) / 2026-MM-DD (跟随市场日)

1. Market Move
   Leading Market: 韩国 / 美国 / 台湾 / 香港
   Object:         KOSPI / SOX / SK Hynix / ...   ← 必须用 §0 的对象字段
   Move(%):        +x.x%
   Event Type:     SURGE / UP / RANGE / DOWN / CRASH

2. Transmission Chain
   Observed (事实，已发生，可验证):
     NVDA +x% → SOX +x% → SK Hynix +x% → KOSPI +x%
   Hypothesis (推测，待验证):
     AI资本开支预期改善 → 半导体景气提升 → 亚洲科技风险偏好增强 → A股算力跟随

3. Sector Linkage
   Leader Sector:  韩国 HBM / AI / 半导体
   Follower Sector: A股 算力 / 光模块 / 芯片
   Consistency:    ★★★★★（产业一致性，1~5 星）

4. Capital Flow
   Foreign:        北向 +x亿 / 南向 +x亿
   Currency:       美元指数 / 人民币
   ETF:            韩国 ETF 资金流

5. Regime Context（与当前系统连接，Validation 分组依据）
   Global:         Risk-On / Neutral / Risk-Off
   China Equity:   趋势修复 / 震荡 / 防御

6. Next-Day Validation
   Expected:   A股AI产业链跟随走强
   Actual:     2026-MM-DD A股 +x%（待填）
   Result:     PASS / FAIL

7. Failure Analysis（反例最重要，必须记录）
   Why worked:   （若 PASS）风险偏好扩散 / 半导体景气共振
   Why failed:   （若 FAIL）政策约束 / 估值高位 / 资金只交易韩国自身事件 / 中国风险偏好未修复

8. Research Question Update
   RQ-004 Evidence: 样本 +1；当前累计 N；韩国领先成功率（待样本≥30 后计算）
```

> **反例（Failed Transmission）与正例同等重要**：正常 `NASDAQ AI涨 → A股AI涨`，失效 `NASDAQ AI涨 → A股不涨`，
> 后者往往意味着 Market Regime 已变——这是 Regime Engine 未来最该关注的信号。

---

## 2. 已记录样本

### 2026-07-30 / 31 — 种子样本（韩国 → A股）【正例·待补数】
- **1. Market Move**：Leading=韩国；Object=KOSPI（待填实际 %）；Event Type=SURGE（若 ≥+1.5%，待核对）
- **2. Transmission Chain**
  - Observed：NVDA(?) SOX(?) SK Hynix(?) KOSPI(?) —— **待填实际 %**
  - Hypothesis：AI 资本开支预期改善 → 半导体景气 → 亚洲科技风险偏好 → A股算力跟随
- **3. Sector Linkage**：Leader=韩 HBM/AI/半导体；Follower=A股 算力/光模块/芯片；Consistency=待逐只核对（是否同涨）
- **4. Capital Flow**：北向/南向净额（待填）；美元/人民币（待填）；韩 ETF（待填）
- **5. Regime Context**：Global=待填；China Equity=07-31 memo 综合 50/100·偏弱·防守 → 偏「防御/震荡」（待确认）
- **6. Next-Day Validation**：Expected=A股AI产业链跟随；Actual=2026-07-31 A股大涨（待填具体指数与板块）；Result=待定（须核对是否 AI/算力领涨）
- **7. Failure Analysis**：待（08-01 看韩股是否延续、A股是否如期）
- **8. RQ-004 Evidence**：样本 = 1（单样本，可信度**低**，仅触发观察，不构成结论）

> ⚠️ 此条为种子样本，仅示范 v2 格式。**真实数字请手工补入**（实际涨跌幅、北向净额等）。
> 勿因单次观察下「韩股带动A股」的因果结论——这正是 RQ-004 要长期验证的假设。

---

## 3. 反例记录示例（模板示范，非真实数据）

> 以下为**格式示范**，帮助理解「Failed Transmission」如何记。请勿当作真实样本。

### 2026-08-10 — 示范：韩国半导体涨，A股不跟【反例】
- **1. Market Move**：Leading=韩国半导体；Object=SK Hynix；Move=+3.0%；Event Type=SURGE
- **2. Transmission Chain**
  - Observed：SK Hynix +3.0%（事实）
  - Hypothesis：半导体景气 → A股算力跟随（推测）
- **3. Sector Linkage**：Leader=韩半导体；Follower=A股芯片；Consistency=★（未联动）
- **5. Regime Context**：Global=Risk-On；China Equity=防御（国内风险偏好未修复）
- **6. Next-Day Validation**：Expected=A股芯片跟随；Actual=A股半导体 -1.0%；Result=**FAIL**
- **7. Failure Analysis**：Why failed=中国风险偏好仍在防御态、估值高位、资金只交易韩国自身事件
- **8. RQ-004 Evidence**：反例 +1 → 提示「韩国→A股」传导并非无条件成立，须加 Regime 条件

---

## 4. 周汇总（由 Research Note 自动生成）

每周五从本文件抽取本周条目，填入 Research Note 《Cross-Market Observation》页，固定呈现：
Date / Leading+Object / Event Type / Observed vs Hypothesis 链 / Sector Consistency / Regime Context /
Next-Day PASS·FAIL / **Failed Transmission 条数**。若无本周条目，周报标注「本周未记录（请手工补：填各市场实际涨跌幅与 Event Type）」，**绝不编造数字**。
