# System Overview / 系统架构总览

> This document is the **evolution blueprint** — where the system is headed. For the *current* implementation mapping (how the 8 layers map to actual code today), see [`docs/architecture.md`](../architecture.md).

The system is designed as five concentric layers. Data flows up; decisions flow down; learning loops back.

```
        ┌───────────────────────────────────────────────────────────┐
        │                     Portfolio Management                    │
        │        仓位 / 风控 / 复盘 — human makes the final call       │
        └───────────────────────────────┬───────────────────────────┘
                                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │                     Decision Support                        │
        │      Investment Committee (weighted vote) → CIO memo        │
        └───────────────────────────────┬───────────────────────────┘
                                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │                      AI Agent Layer                         │
        │   Macro analyst · Sector analyst · Company research agents  │
        │   (v0.3 — the reasoning layer that explains *why*)          │
        └───────────────────────────────┬───────────────────────────┘
                                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │                      Research Engine                        │
        │   8-layer decision tree (L0–L8 + L3.5) · capital migration  │
        │   · causal reasoning · scenario engine                      │
        └───────────────────────────────┬───────────────────────────┘
                                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │                         Data Layer                          │
        │   TDX local · Eastmoney public APIs · akshare · global      │
        │   SQLite research database · data-integrity gate           │
        └───────────────────────────────────────────────────────────┘
```

---

## Layer by layer

### 1. Data Layer / 数据层
Multi-source market data — TDX local quotes, Eastmoney public APIs, akshare, and global indices — normalized into a local SQLite research database. A 5-point **data-integrity gate** refuses to decide on broken data.

### 2. Research Engine / 研究引擎
The 8-layer decision tree (`L0` narrative → `L1` global macro → `L2` China macro → `L3` market cycle → `L3.5` industry-chain → `L4` sector rotation → `L5` asset research → `L6` execution → `L7` risk → `L8` learning). Plus the cross-cutting engines: capital migration, causal reasoning, scenario engine.

### 3. AI Agent Layer / AI 智能体层 *(planned, v0.3)*
Specialized reasoning agents that turn raw layer output into *explanations*: a macro analyst, a sector analyst, and a company-research agent. This is where "AI-augmented" becomes visible — not prediction, but structured reasoning a human can audit.

### 4. Decision Support / 决策支持
A structured **Investment Committee** votes with fixed weights (资金40 / 产业25 / 宏观15 / 技术10 / 风险10) and produces a single verdict; a CIO agent synthesizes the daily memo. The committee and CIO *never* execute a trade.

### 5. Portfolio Management / 组合管理
Position sizing from a risk budget, invalidation conditions, and the learning-loop replay. The human reads the chart and makes the final buy/sell.

---

## Evolution trajectory

```
AI-Investment-Research-System      (v0.1 · research framework — this repo, today)
            ↓
Investment-Research-OS             (v1.0 · integrated research operating system)
            ↓
Joy Investment Intelligence Platform   (future ecosystem)
```

| Stage | Theme | Status |
|-------|-------|--------|
| **v0.1** Research Framework | Philosophy · decision framework · research workflow | ✅ current |
| **v0.2** Data Infrastructure | Market data pipeline · database design · research DB | 🔜 next |
| **v0.3** AI Research Agents | Macro / Sector / Company analyst agents | 🔜 planned |
| **v1.0** Investment Research OS | Integrated AI-enhanced research operating system | 🎯 long-term |

See [`docs/roadmap.md`](../roadmap.md) for the detailed plan.

---

## Related

- [`docs/architecture.md`](../architecture.md) — current implementation mapping (8 layers ↔ code)
- [`docs/decision-process.md](../decision-process.md) — the five-step discipline
- [`docs/research-framework.md](../research-framework.md) — the framework wrapper
