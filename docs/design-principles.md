# Design Principles / 设计原则

Engineering and methodology guardrails that keep the system honest, auditable, and safe to run daily.

---

## 1. Human-in-the-loop, always / 人在环内

The system never executes a trade. It produces a *circled theme → candidate list → data attachment*. The final buy/sell is a human reading the chart. Any feature that implies "auto-trade" is out of scope.

## 2. Research over prediction / 研究优于预测

Outputs are framed as *research aids and evidence*, not price targets. The system exposes its reasoning (the 9-block memo, the IC debate) so the operator can disagree with it.

## 3. Sector before stock / 板块优先于个股

No stock is ever presented outside a confirmed funded sector regime. The methodology ordering *板块 > 龙头 > 资金 > 图形* is enforced in the candidate pipeline, not left to chance.

## 4. Data integrity gates decisions / 数据优先于决策

A 5-point health check (`data_health.py`) must pass before a decision is trusted. On failure the system degrades to **NO / 数据异常·禁止交易** rather than guessing on incomplete data.

## 5. Graceful degradation / 优雅降级

The AI reasoning layers are optional. With no LLM key configured, the system falls back to **rule-based scoring** and still produces a coherent memo. No hard dependency on a paid API.

## 6. No hardcoded secrets / 无硬编码密钥

LLM keys come from the front-end or a `.env` (git-ignored). Third-party public tokens (e.g. Eastmoney) are read from environment variables, never committed.

## 7. Local-first, portable / 本地优先、可移植

Everything runs on a local SQLite database and a local FastAPI + React stack. No hosted backend, no account lock-in. Build scripts use relative paths so the repo clones and runs anywhere.

## 8. Learning is measured, not claimed / 学习要可度量

The Learning Center replays past calls and reports hit-rate + sample sizes. Claims of "the system learned" are backed by `n`, not by vibes.

## 9. Honest about uncertainty / 坦诚不确定性

When the environment is hostile (no money, no clear rotation), the correct output is often **do nothing / 空仓**. The system is built to say NO, not to manufacture a trade.

## 10. Separate concerns / 关注点分离

Data collection, research reasoning, committee voting, memo synthesis, and learning are independent centers with clear interfaces. This makes the system readable, testable, and extendable — the opposite of a monolithic "bot".
