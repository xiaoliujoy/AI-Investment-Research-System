# AI-Investment-Research-System — Research Framework Whitepaper (v0.1)

> An AI-augmented investment research framework — currently a research **system**, evolving toward a personal investment **research operating system**.

This document is the umbrella whitepaper for the repository. It ties together the philosophy, the daily discipline, the architecture, and the trajectory from *System* (today) to *OS* (endgame), so a reader understands the **system** before the **code**.

For deeper detail, see [`investment-philosophy.md`](investment-philosophy.md), [`architecture.md`](architecture.md), [`design-principles.md`](design-principles.md), and [`roadmap.md`](roadmap.md).

---

## 0. Why this document exists

Most "AI investing" projects collapse to a single line:

```
data → LLM → buy / sell
```

That line is a black box, and it is a lie about how investing actually works. This repository refuses it.

What we built is not a predictor and not a trader. It is a **research framework** — a repeatable, auditable daily process that turns messy market data into a small number of well-evidenced questions a human can answer by looking at a chart.

This whitepaper is the "what and why". The code is the "how".

---

## 1. The core stance

Four beliefs separate *research* from *prediction*:

```
Research   >  Prediction      研究 > 预测
Systems    >  Opinions        系统 > 观点
Long-term  >  Short-term      长期 > 短期
Human      >  Black box       人 > 黑盒
```

The investor's edge comes from **better questions and a repeatable process**, not from a model that claims to "predict the market".

> **Human-in-the-loop, by design.** The methodology is *板块 > 龙头 > 资金 > 图形* (Sector → Leader → Capital → Chart). The system only *circles the main themes → lists candidates → attaches the data*. The final buy/sell is always a human decision made by reading the chart.

---

## 2. The daily discipline (the moat)

Every trading day the system runs one discipline, in three steps:

```
判环境   →   选方向   →   定标的
(Judge the environment)  (Pick the direction)  (Identify the candidate)
```

And it answers exactly three questions:

> **今天有没有钱？钱去哪？我怎么办？**
> *(Is there money in the market? Where is it going? What should I do?)*

If the reader finishes the daily memo and does **not** know what to look at tomorrow, the system failed. Everything else exists to serve these three questions.

---

## 3. Methodology red lines

These are non-negotiable and are enforced in the code and in the output:

- **板块 > 龙头 > 资金 > 图形.** Breadth and rotation first; then the leaders inside the winning sectors; then where capital is actually flowing; only then the chart entry. The chart never leads the thesis.
- **Candidates are *circled*, never *filtered* by hard rules.** The system lists candidates and attaches data. It does **not** silently drop names with mechanical filters. Final selection is human.
- **Forbidden fields.** Individual `amount`, `ma20`, `ma60`, and any derivatives of them are **not** used to filter candidates. (Sector scoring is the exception — see below.)
- **Sector scoring uses two equal dimensions.** Net capital inflow **and** turnover must both be considered; neither may be dropped. A sector with inflow but no turnover, or turnover with no inflow, is not a main theme.
- **The system never places an order.** Not now, not in the OS endgame. The committee and CIO produce research and a recommended stance; the human executes.

---

## 4. The framework in one picture — eight layers

Market data flows in; research layers reason; an Investment Committee votes; a CIO agent synthesizes the memo; a Learning Center replays past calls to self-correct.

```
L0  Narrative           盘前纪要叙事层（人工/外部输入）
L1  Global Macro        全球宏观流动性 / 风险偏好
L2  China Macro         政策 / 流动性 / 情绪 regime
L3  Industry Trend      产业趋势 / 周期 / 技术革命
L3.5 Industry Chain     产业链上/下游下钻（drill-down）
L4  Sector Rotation     板块轮动 / 资金迁移链
L5  Leader System       龙头体系 / 四龙头
L6  Execution           买点 / 仓位区间（人工看图）
L7  Risk Control        风险预算 → 仓位上限
L8  Learning            预测回放 / 命中率 / 权重自校准
```

> **Each layer contributes evidence to the final CIO decision memo** — the architecture is readable and auditable end to end. See [`architecture.md`](architecture.md) for the full L0–L8 + L3.5 mapping, the IC/CIO contract, and the data-integrity gate.

---

## 5. The Investment Committee — the differentiator

Between the research layers and the final memo sits a **structured Investment Committee**. Multiple dimensions debate, then vote with fixed weights:

| Dimension | Weight | What it answers |
|-----------|:------:|-----------------|
| 💰 Capital Flow (资金) | **40%** | Where is money *actually* moving? |
| 🏭 Industry (产业) | **25%** | Which sectors have real catalysts? |
| 🌐 Macro (宏观) | **15%** | Headwind or tailwind for risk assets? |
| 📈 Technical (技术) | **10%** | Is the entry timing confirmed? |
| 🛡️ Risk (风险) | **10%** | What is the position budget / guardrail? |

The weighted score drives a single decision: `can_buy / direction / position_pct / debate / verdict`. The CIO agent only synthesizes **after** the committee reaches a verdict — never before.

> **Trust guardrail:** the committee and CIO produce research and a recommended stance. The final buy/sell is always a human reading the chart. See [`design-principles.md`](design-principles.md).

---

## 6. The Learning Loop

The system replays its own past calls:

- Per-dimension hit-rate (e.g. did Capital Flow actually lead?).
- Suggested weight adjustments, fed back into the committee.
- Empirical regularities, each with a sample count `n` — **honest, never fabricated**.

This is what makes it a *framework* rather than a one-shot script: it is supposed to get better at self-calibration over time. See the "系统学习" block of the daily memo.

---

## 7. What ships in v0.1 (the "system" stage)

This repository today is the **research system**: a local-first stack that runs the daily discipline end to end.

| Module | Responsibility |
|--------|----------------|
| `backend/daily_collect.py` | Daily data collection: TDX quotes → Eastmoney fallback → global alignment |
| `backend/tech_fill.py` | Technical field backfill (MA20/60, volume ratio, breakout zone) |
| `backend/data_health.py` | 5-point data integrity gate → `trade_allowed` |
| `backend/committee/investment_committee.py` | Weighted IC voting → the single decision source |
| `backend/brain/cio_agent.py` | CIO synthesizes the daily memo (`produce()`) |
| `backend/notify/os2_report.py` | Compressed 9-block daily memo (HTML / WeChat-compatible) |
| `backend/learning_center.py` | Replays predictions, computes hit-rate, self-calibrates weights |
| `backend/panqian_parser.py` | Ingests pre-market briefing notes into the narrative layer |

- **Local-first.** Python 3.13 · FastAPI · SQLite · React 19 · Vite · TypeScript.
- **No database shipped.** The ~5 GB local `vibe_research.db` is git-ignored; generate your own with `init_db()`.
- **No secrets committed.** `.env`, `.workbuddy/`, `backend/output/`, and personal notes are git-ignored.
- **Degrades gracefully.** The AI reasoning layers call an LLM via a key you supply; with no key, it falls back to rule-based scoring.

---

## 8. From System to OS (the trajectory)

The repository is named **`AI-Investment-Research-System`** at the current v0.1 stage on purpose.

- **Now (System):** a research framework + a running daily pipeline + a methodology. Honest about its scope.
- **Later (OS):** the full *investment research operating system* — data layer + AI agent layer + workflow layer + research-tool layer + decision layer + UI + automation — the kind of closed loop a Bloomberg Terminal / TradingView / Palantir Foundry represents at scale.

We name it *System* today so the expectation matches the delivery. When the ecosystem matures, the long-term vision is **`Investment-Research-OS`**. See [`roadmap.md`](roadmap.md) for the staged plan and the future sibling repositories.

---

## 9. How to use / extend

1. Clone, `pip install -r requirements.txt`, `init_db()` to build an empty local DB.
2. Run `daily_collect.py` → `tech_fill.py` → `run_daily.py --skip-step1 --memo-only` to produce the daily memo.
3. Read the memo. Let the system circle the themes; you make the call.
4. Extend a layer (e.g. a new L3.5 chain drill-down, or a tighter L7 position rule) and feed the result back through the learning loop.

Full steps in [`../README.md`](../README.md) → Quick Start.

---

## 10. Status

**v0.1 — a real, running system, open-sourced.** Not a 1000-line demo. Methodology is the moat; code is copyable, the *判环境 / 选方向 / 定标的* process and its long-term iteration are not.

> Research > Prediction. Systems > Opinions. Long-term > Short-term. The edge is the process, not the algorithm — and a process is worth sharing.
