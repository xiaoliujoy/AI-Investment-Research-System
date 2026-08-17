# P0-B 根因定位：资金维度与 A 股主力资金流"结构性断接"

> 审计阶段：2026-08 Decision Audit 后续
> 性质：**测量/接线问题**（非校准区间压缩）
> 生产代码改动：无（本报告只读诊断）

---

## 1. 结论（一句话）

composite 的"资金"维度（权重 40%）声称衡量"A 股今天有没有钱"，
但它在工程上**完全没有接入 A 股主力净流入信号**——
它读的是一个跨资产资金评分 `flow_score_overall`，
而该评分 5 层里有 3 层是死的（无数据 / 待接入），
唯一活的、与 A 股相关的两层（M4 板块、M5 个股）长期处于"待接入"状态。

真实 A 股主力净流入（`stock_flow_daily.main_net_buy` → `capital_score.py`）被算出来了，
却只用于"龙头资金层"展示，**没有回灌决策链**。

---

## 2. 证据链

### 2.1 composite 资金维度怎么算的
`backend/notify/os2_report.py` `compute_weighted_score()` 第 132-136 行：

```python
mig_r  = (memo.migration or {}).get("rating") or 0          # 0-5，无 migration_report → 0
flow   = getattr(memo.cross_asset, "flow_score_overall", 0) or 0  # 0-100
sb_L4  = _dim_score(_sb_dir(memo, "L4"))
capital = 0.4 * (mig_r / 5.0 * 100) + 0.3 * flow + 0.3 * sb_L4
```

- `mig_r`：`migration_report.json` 不存在 → 恒为 0 → **0.4 权重作废**
- `flow`：来自 `flow_report.json` 的 `flow_score.overall`（见 2.2）
- `sb_L4`：L4 共识方向分（方向，非量级）

### 2.2 `flow_score_overall` 内部（8/14 实测快照）

```
overall = 53
  M1 全球流动性   50  数据不足      ← 无 DXY/美债数据
  M2 跨资产       74  流入          ← 商品动量（与 A 股主力净流无关）
  M3 ETF份额      40  中性          ← ETF 申赎份额
  M4 板块资金     50  待接入        ← 本应接 L4 板块资金，未接
  M5 个股资金     50  待接入        ← 本应接 L5 龙头资金，未接
```

`overall = mean(M1..M5) = mean(50, 74, 40, 50, 50) = 52.8 → 53`

→ 只有 M2（商品）、M3（ETF）是活的，且两者都不代表"A 股主力净流入"。

### 2.3 真实信号其实算好了，但没接
`backend/capital_score.py` 的 `compute_scores()`：
- 输入：`stock_flow_daily.main_net_buy`（东财真实主力净流入）
- 输出：逐股 Capital Score（资金强度 30 + 持续性 20 + 板块 20 + 龙头 15 + 活跃 10 − 风险 15）
- 落库：`stock_capital_score`
- **下游用途：仅 `sector_top_stocks()` 给"龙头资金层"展示**（`os2_report.py` line 51 import 也是为展示）
- **未进入 `compute_weighted_score` 的资金维度**

---

## 3. 为什么"真实资金流 +11 → 系统 55"

| 真实世界 | 系统里对应的量 | 状态 |
|---|---|---|
| A 股行业净流 +11 (8/4) | `sector_daily.net_amount` / `stock_flow_daily` | 未被任何决策层读取量级 |
| A 股主力净流入 | `capital_score.py` 已算 | 仅展示，不进 composite |
| composite 资金维度 | `0.4*mig(=0) + 0.3*flow + 0.3*L4` | flow 由商品+ETF 驱动 |

→ 当 A 股资金洪流涌入时，决策层看到的"资金"几乎纹丝不动。
这不是"评分函数把大数压成小数"，而是**相关输入根本不在函数域内**。
比"校准压缩"更糟：是"测量缺失 / 接线断开"。

---

## 4. 对四层审计框架的影响

- **P0-B 是 PRIMARY（原发）：** 资金维度测量的是"商品动量 + ETF 份额 + 中性默认值"，不是"A 股钱"。
- **P0-A（语义错误：IC=YES 被 Composite 覆盖成 NO）很可能是 P0-B 的症状：**
  因为 capital 维度喂了错误/缺失数据 → composite 系统性偏低 → "取最保守"规则把 YES 覆盖。
- **关键时序结论：**
  **先修 B（把真实 A 股资金流接进资金维度），再谈要不要改 Composite 的否决权（A）。**
  现在若直接剥离/弱化 Composite 否决权，等于在"测量错误"的基础上调"决策规则"，
  仍可能产出无意义结论（overfitting 到这一波）。
- **C / D（IC vs Composite 历史独立有效性、增量价值）：** 当前 9 天、5 个 veto 样本太小，
  且 flow 信号断接意味着"Composite 低分"中混入了测量噪声。
  必须先把 B 修好、积累 30~60 个干净决策日，C/D 矩阵才有意义。

---

## 5. 限制（诚实标注）

- 仅拿到 8/14 一份 `flow_report.json`（引擎只保留最新，不归档历史）。
- M4/M5 "待接入"、M1 "数据不足"是否 8/1~8/14 全程如此，需历史快照确认。
- 建议：① 每日归档 `flow_report.json` 到 `output/archive/`；② 顺带记录 `flow_score` 五层明细，便于复盘 P0-B 修复前后对比。

---

## 6. 修复方向（待放行，非本次执行）

| 层 | 现状 | 修复 |
|---|---|---|
| M4 板块资金 | 待接入 | 接 `capital_score.py` 的板块聚合 net flow 百分位 |
| M5 个股资金 | 待接入 | 接 `capital_score.py` 个股分 |
| M1 全球流动性 | 数据不足 | 接 DXY/美债真实源，或明确标注"不计入 A 股决策" |
| migration | 文件缺失 → 0 | 补 `migration_report` 或临时回退（缺失时不计入 0.4 权重，避免静默压制） |
| composite 资金维度 | 40% 权重喂错信号 | 修 B 后重估权重，再做 C/D |

修复后预期：资金维度将随真实 A 股净流显著波动（不再卡 46~58），
从而让"COMPOSITE_SCORE 否决"具备它声称的测量基础——届时再判断它该不该有否决权。
