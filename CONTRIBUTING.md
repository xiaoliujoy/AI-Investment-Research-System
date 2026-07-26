# Contributing / 如何参与

Thank you for your interest in **AI-Investment-Research-System**. This is an open, research-first project — contributions that improve *research quality, methodology, and decision discipline* are especially welcome.

> 这是一个以"研究"为先的开源项目。我们欢迎能提升研究质量、方法论与决策纪律的贡献。

---

## Principles / 红线

Before opening an issue or PR, please internalize the project's core stance:

- **AI augments, never replaces.** The system is a research co-pilot. It must **never** become an automated trader, a black-box "buy/sell" generator, or a financial-advice product.
- **Research > Prediction.** We value better questions and a repeatable process over claims of "forecasting the market".
- **Human-in-the-loop, by design.** Final buy/sell decisions stay with the human reading the chart.
- **No secrets, no data.** Never commit `.env`, database files (`*.db`), personal holdings, or `backend/output/`. These are git-ignored on purpose.

---

## How to contribute

### 1. Documentation & methodology (highest priority)

The project's differentiation lives in its *thinking*, not just its code. Strong contributions:

- New or improved docs under `docs/` (e.g. market regime, sector rotation, leader-selection methodology).
- Public strategy essays under `strategy/`.
- Clarifications to the Investment Committee weighting logic or the 8-layer discipline.

### 2. Code

- **Backend:** Python 3.13, FastAPI, SQLite. Keep modules readable and auditable end to end.
- **Frontend:** React 19 + Vite + TypeScript + Tailwind. `pnpm` is the pinned package manager.
- **Tests:** add or update tests for any logic you change. Run `pytest` before submitting.
- **LLM keys:** never hardcode. Read from env / front-end config; degrade gracefully to rule-based scoring when absent.

### 3. Data & adapters

- New data sources must go through the existing `daily_collect` / `tech_fill` pipeline and respect the data-integrity gate (`data_health.py`).
- Keep the local-first principle: no calls that require shipping user data off-machine.

---

## Workflow

1. **Open an issue first** for anything beyond a trivial doc fix — to align on direction before code.
2. Fork → branch (`feat/...`, `fix/...`, `docs/...`) → PR to `main`.
3. Keep PRs focused. Describe *what* changed and *why*, linking the issue.
4. For docs, a short PR is fine — clarity beats ceremony.

---

## Local setup (for testing)

```bash
# backend
cd backend && pip install -r requirements.txt
python -c "from database.models import init_db; init_db()"
python daily_collect.py && python tech_fill.py
python run_daily.py --skip-step1 --memo-only

# frontend
cd frontend && pnpm install && pnpm dev
```

---

## Code of Conduct

Be respectful. We are here to improve how humans and AI research markets together — not to sell predictions. Disagreement about *methodology* is welcome; personal attacks are not.

By contributing, you agree your contributions are released under the [MIT License](LICENSE).
