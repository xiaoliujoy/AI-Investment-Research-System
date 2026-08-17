# P0-RESEARCH-1 · Capital Flow Reconnection Specification

> 属于 **Signal Loss Incident · 2026-08** 的观测层修复第三阶段（研究规格）。
> 状态：**规格书（SPEC ONLY · DO NOT IMPLEMENT）**。
> 在 P0-OBS-1A 积累 ≥ 30~60 个干净决策日、并完成 P0-OBS-2 观测之前，**禁止实施**。
> 本文件不改动任何生产代码。冻结项：65/80 阈值、Composite 权重、M4/M5 生产接入。

---

## 0. 背景：事故根因（来自 P0-B 定位）

2026-08 这波上涨，IC 判 6 次 YES，但公众号驾驶舱几乎全显示「不交易」。审计定位到资本维度：

**`composite` 的资本维度里，A 股真实资金信号的有效权重 ≈ 0%。**

链路断点（2026-08-17 快照证据）：

| 层 | 状态 | effective_weight | 说明 |
|---|---|---|---|
| M1 全球流动性 | NO_DATA | 0.0 | 缺 DXY/美债数据 |
| M2 跨资产 | INFLOW | 0.2 | 商品动量（与 A 股无关） |
| M3 ETF资金 | NEUTRAL | 0.2 | ETF 申赎 |
| M4 板块资金 | NOT_CONNECTED | 0.0 | 标注「待接入」，永久 stub 50 |
| M5 个股资金 | NOT_CONNECTED | 0.0 | 标注「待接入」，永久 stub 50 |

结果：`flow_score_overall=53`（40% 由 stub 拼出），且 `capital_score.py` 已用
`stock_flow_daily.main_net_buy` 算好真实个股资金强度，却**只用于「龙头资金层」展示，从未回灌 composite 资本维度**。

`stock_flow_daily`（8/17 新鲜，5549 只中 2514 只净流入，positive_ratio=45.31%）里的真实 A 股资金，
composite 完全看不到。这是测量/校准断接，不是简单「数据缺失」。

---

## 1. 目标

把真实 A 股资金信号接入 `flow_score` 的 M4/M5，并修正 `migration` 缺失的语义处理，
使资本维度**对真实资金环境变化具备区分能力**。

**但本规格只定义「怎么接、接什么、如何验证」，不写生产实现、不落地。**

---

## 2. 两个独立问题（严禁混为一谈）

### 问题 A：M4/M5 断接（接线问题）
- 现状：M4(板块资金)/M5(个股资金) 无输入，永久 stub 成 50。
- 真实信号源已存在：`capital_score.py` 从 `stock_flow_daily.main_net_buy` 聚合出真实评分。
- 待解决：将真实 A 股资金评分接入 flow_score 的 M4/M5（或等价的资本维度分量）。

### 问题 B：migration 缺失语义（校准/语义问题）
- 现状：`migration_report.json` 缺失 → 资本维度 40% 权重的 migration 挂空，按 0 计。
- 歧义：`migration=0` 究竟是「资本迁移极弱」还是「migration 数据不存在」？两者语义完全不同。
- 待解决：引入 `migration_status` 与 `migration_weight_effective`，让缺失不被伪装成低分。

> 直接「把 65 改成 60」会同时绕过 A 与 B，是最危险的错误修复。

---

## 3. 缺失数据处理：待研究的 4 个方案（本阶段不定论）

| 方案 | 描述 | 适用假设 |
|---|---|---|
| A. 缺失记 50 | 维持现状（中性填充） | 缺失=中性 |
| B. 剔除后重归一化 | 丢弃死层，活层权重重新归一 | 死层无信息量 |
| C. 降低整体 evidence quality | 触发 Evidence Quality=LOW，但不改分数 | 缺失=证据不足，而非市场中性 |
| D. 触发 DATA_INSUFFICIENT | 直接禁止参与或显式标记 | 缺关键证据时不应下注 |

**研究态度**：先用 P0-OBS-1A 积累的历史快照比较「方案 A vs B vs C vs D」在
forward return 上的表现，再决定。现在只记录、不选择。

---

## 4. migration 字段规格（建议，待实施时落地）

```json
{
  "migration_status": "OK | MISSING | STALE | ERROR",
  "migration_score": 0.0,
  "migration_weight_nominal": 0.40,
  "migration_weight_effective": 0.0,
  "migration_source_date": "2026-08-17"
}
```

规则：
- `MISSING` → `effective_weight = 0`，且**不把 score 当作 0 分参与均值**（避免假中性）。
- 真正接入后，`effective_weight` 才等于名义权重。
- 这与 flow_snapshot 既有的 `status / effective_weight` 设计保持一致。

---

## 5. A 股真实资本信号聚合（建议输入，待实施）

数据源（已在库、每日新鲜）：

- `stock_flow_daily.main_net_buy`：个股主力净流入 → 聚合 `positive_ratio / mean / median`
- `sector_daily.net_amount`：行业净流向 → 行业资金强度

建议 M4（板块资金）来自 `sector_daily` 净流截面；M5（个股资金）来自 `stock_flow_daily` 净流截面。
聚合后映射到 0~100 评分（需定义归一化口径，见 §6）。

---

## 6. 验证标准（修复实施后，用 Before/After 对照）

P0-OBS-1A 的快照时间序列天然构成实验基线：

```
Before: 2026-08-17 基线
  M4=NOT_CONNECTED  M5=NOT_CONNECTED
  资本维度有效权重=0.168 / 0.40
  A股信号进composite=FALSE

After:  修复 M4/M5 后第一份快照
  对比 effective_weight_fraction、capital_dimension.effective_weight_in_composite、
  real_ashare_capital_flow.positive_ratio 与 flow_score 的联动
```

需回答：
1. 修复后 `flow_score` 是否随真实 A 股净流明显波动（量程是否被打开）？
2. 修复后 composite 与 IC 的分歧是否减少（Signal Preservation Rate 是否回升）？
3. 修复后 `composite ≥ 65` 的 forward return 是否优于修复前（独立有效性）？

---

## 7. 实施前置条件（铁律）

- ✅ P0-OBS-1A 已每日自动留证（已完成基础设施 + 自动化）
- ✅ P0-OBS-2 telemetry 已设计、可离线回填
- ⏳ 累积 ≥ 30~60 个干净决策日
- ⏳ Composite 独立有效性检验完成（IC YES → fwd / Composite≥65 → fwd / IC+Composite 增量）
- ⏳ 用户显式 release gate 放行

在此之前，M4/M5 保持 `NOT_CONNECTED`，migration 保持 `MISSING`，阈值保持 65/80。
**任何「为补救 8 月漏行情而调参」的冲动，都视为 overfitting，拒绝执行。**

---

## 8. 关联文档

- `flow_snapshots/README.md` — P0-OBS-1 证据链 schema 与五状态枚举
- `flow_snapshot_2026-08-17.json` — 断接持续性基线锚点
- `decision_telemetry_design.md` — P0-OBS-2 决策遥测设计
- `audit_aug_report.md` — 四层一致性审计（5 个数字）
