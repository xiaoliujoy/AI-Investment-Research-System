# Architecture / 架构

The system is a **five-center, eight-layer** decision loop. This document maps the public-facing layer names (used in the README) to the internal implementation, and explains how the five centers connect.

---

## Five Centers / 五个中心

```
Data Layer → Research Center → Investment Committee → CIO Agent → Learning Center
```

| Center | Role | Key module(s) |
|--------|------|---------------|
| **Data Layer** | Collect & normalize market data | `daily_collect.py`, `tech_fill.py`, `data_health.py`, `gstock.py`, `astock.py` |
| **Research Center** | Eight-layer reasoning | `decision_tree.py`, `gold_engine/`, `capital_flow/`, `capital_migration.py` |
| **Investment Committee** | Single weighted decision source | `committee/investment_committee.py` (`decide()`) |
| **CIO Agent** | Synthesize the memo | `brain/cio_agent.py` (`produce()`) |
| **Learning Center** | Replay & self-correct | `learning_center.py` |

---

## Eight Layers (public names ↔ internal)

The README uses human-readable layer names. Internally the decision tree carries finer sub-layers (L0 narrative, L3.5 industry-chain drill-down). Mapping:

| Public layer | Internal | Responsibility |
|--------------|----------|----------------|
| Layer 1 — Global Macro Environment | L1 | 全球流动性 / 科技风险偏好 / 中国相对强度 |
| Layer 2 — China Macro & Policy | L2 | 政策 / 流动性 / 情绪 regime |
| Layer 3 — Market Cycle | L3 | 产业趋势（技术革命 / 国产替代 / 周期涨价） |
| Layer 4 — Sector Rotation | L4 | 资金净流入 / 成交额 / 资金迁移链 |
| Layer 5 — Asset Research (Stock) | L5 | 产业 / 资金 / 技术 / 情绪 四龙头体系 |
| Layer 6 — Portfolio Management | L6 | 买点 / 仓位区间（人工看图最终确认） |
| Layer 7 — Risk Control | L7 | 风险预算 → 仓位上限 |
| Layer 8 — Learning & Reflection | L8 | 预测回放 / 命中率 / 权重自校准 |

**Supporting sub-layers:**
- **L0 — Narrative:** pre-market briefing ingest (`panqian_parser.py`) — 连板高度, 地雷股, 主线信号. Feeds the day's narrative context.
- **L3.5 — Industry Chain:** drill-down into upstream/downstream of a theme to confirm the thesis is spreading, not isolated.

> **Each layer contributes evidence to the final CIO decision memo.** The architecture is readable and auditable end to end — no hidden "AI says buy".

---

## Investment Committee / 投资委员会

`committee/investment_committee.py` is the **single decision source**. It runs a weighted vote across dimensions:

```
资金 (Capital)        40
产业 (Industry)       25
宏观 (Macro)          15
技术 (Technique)      10
风险 (Risk)           10
```

`decide()` returns: `can_buy / direction / position_pct / debate / weighted_vote / verdict`. The weights are **not fixed** — the Learning Center can suggest recalibration based on historical hit-rate (`weight_src` marks a weight as `learning` or `base`).

---

## CIO Agent / 总指挥

`brain/cio_agent.py` (`produce()`) consumes the Committee output plus the narrative feed and emits an `InvestmentDecisionMemo` — the structured daily brief. It is then compressed by `notify/os2_report.py` into a 9-block memo:

```
执行摘要 → 最终裁决(加权IC评分) → 盯盘清单 → 候选主线 → 为什么
        → 失效条件 → 系统学习 → 今日Alpha → 附录
```

---

## Learning Loop / 学习闭环

`learning_center.py` replays each day's predictions against realized outcomes and computes:

- `dimension_accuracy` — per-layer hit-rate
- `suggested_weights` — proposed IC weight recalibration
- `regularities` — empirical patterns mined from replay (each carries a sample count `n`, no fabrication)

This closes the loop: the system does not just produce signals, it **measures whether its own reasoning was right** and adjusts.

---

## Data Integrity Gate / 数据闸门

`data_health.py` runs a 5-point check before any decision is trusted:

1. Stock count coverage
2. Individual capital-flow coverage
3. Market-cap coverage
4. ST-filter applied
5. Global data present

`trade_allowed` aggregates the result. If the gate fails, the memo is forced to **NO + 市场状态=数据异常·禁止交易** — the system refuses to decide on bad data.

---

## See also

- [`docs/investment-philosophy.md`](investment-philosophy.md) — the methodology behind the layers
- [`docs/design-principles.md`](design-principles.md) — engineering guardrails
- 内部详细规格：`docs/八层决策树_架构设计.md`（中文深度版）
