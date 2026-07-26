# Decision Process / 决策流程

The decision process is the project's moat. It is deliberately **not** a black-box `data → model → buy/sell` pipeline. It is a **readable, repeatable five-step discipline** where the human stays in the loop at the final call.

The system's job at every step is to *circle the theme, list candidates, and attach the data*. It never makes the final trade.

```
Market Environment ──▶ Sector Selection ──▶ Stock Selection ──▶ Position Management ──▶ Risk Control
   (判环境)              (选方向)             (定标的)            (定仓位)               (控风险)
```

---

## 0. The one-line discipline / 三条铁律

> **判环境 → 选方向 → 定标的**

And the filtering order that never inverts:

> **板块 > 龙头 > 资金 > 图形**
> *(Sector → Leader → Capital → Chart)*

The system circles the main themes; the human reads the chart and makes the call.

---

## 1. Market Environment / 判环境

*Answer: 今天有没有钱？风险偏好在哪？*

- Global macro liquidity & risk appetite (Layer 1)
- China macro & policy regime, onshore liquidity (Layer 2)
- Market cycle / breadth / total capital in the market (Layer 3)
- Cross-asset context: USD, rates, gold, crude, BTC (global layer)

Output: a regime read — risk-on / risk-off / transitional — and the total "money available" signal. If the environment says *no money*, the process stops here and the stance is defensive.

---

## 2. Sector Selection / 选方向（定主线）

*Answer: 钱去哪？今天的主线板块是哪几个？*

Every trading day the system ranks sectors by **two dimensions, weighted equally** (never one alone):

- **Capital net inflow** (近 5 日资金持续流入)
- **Turnover / trading volume** (成交额放大)

Plus a quality filter: **赚钱效应** (does the sector actually make money for participants?).

Hard rule: pick **1–3 main-theme sectors per day**. Every candidate stock downstream must belong to one of these sectors.

> Sector score = capital net inflow **and** turnover, both required. Skipping either dimension distorts the ranking.

---

## 3. Stock Selection / 定标的（只圈不筛）

*Answer: 主线板块里，谁值得放进观察池？*

Inside the chosen sectors, the system **circles candidates** — it does **not** auto-filter or auto-rank them away. Human hard conditions (for the operator's own later review) include:

- Capital net inflow within the sector
- 20MA > 60MA (trend intact)
- Daily turnover > ¥1B
- Total market cap ¥10B–¥100B
- Volume ratio, high → low

Methodology guardrail: the system **only circles, never screens**. It lists candidates and attaches the data; it does **not** drop stocks by `amount / ma20 / ma60` derived rules. The final pick is the human's.

---

## 4. Position Management / 定仓位

*Answer: 如果做，做多少？*

- Risk budget → position ceiling (Layer 7)
- Investment Committee weighted vote (资金40 / 产业25 / 宏观15 / 技术10 / 风险10) drives `can_buy / direction / position_pct`
- IC hit-rate feeds back into the position guardrail: low hit-rate tightens the cap

The human confirms the **entry chart pattern** (breakout from a dense trading zone, or imminent breakout) before any position.

---

## 5. Risk Control / 控风险

*Answer: 什么情况下我错了？错了怎么办？*

- **Invalidation conditions** — explicit signals that the thesis is dead
- **Max risk** — position budget breach, data-integrity gate failure
- **Data gate** — `data_health.py` 5-point check; if it fails, the system forces `final = NO` + *数据异常·禁止交易*

Risk control is not a footnote; it is the gate that can veto the entire day.

---

## Human-in-the-loop, by design

| Step | System does | Human does |
|------|-------------|------------|
| Environment | ranks regime, flags money | judges conviction |
| Sector | ranks & circles 1–3 themes | confirms the theme |
| Stock | circles candidates + data | picks the name |
| Position | suggests %, guardrails | sizes & times entry |
| Risk | sets invalidation + gate | pulls the trigger / walks away |

The system produces research and a recommended stance. **The final buy/sell is always a human reading the chart.**

---

## Related

- [`docs/investment-philosophy.md`](investment-philosophy.md) — why *research > prediction*
- [`docs/research-framework.md`](research-framework.md) — the full framework wrapper
- [`docs/architecture.md`](architecture.md) — how the 8 layers map to this process
- [`docs/design-principles.md`](design-principles.md) — the guardrails that keep it honest
