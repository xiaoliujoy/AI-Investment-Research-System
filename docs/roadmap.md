# Roadmap / 路线图

Status of the flagship repository `AI-Investment-Research-System` (currently the v0.1 research-system stage; the long-term vision is `Investment-Research-OS`), and where it fits in the broader `Joy Research Lab` open-source plan.

---

## Done / 已完成

- [x] **Eight-layer decision architecture** (L0–L8 + L3.5) with readable, auditable reasoning
- [x] **Investment Committee** weighted voting as the single decision source (weights: 资金40 / 产业25 / 宏观15 / 技术10 / 风险10)
- [x] **CIO memo synthesis** + compressed 9-block daily report (`os2_report.py`, HTML / WeChat-compatible)
- [x] **Learning loop** — prediction replay, per-layer hit-rate, weight self-calibration, empirical regularities (with sample counts)
- [x] **Data integrity gate** — 5-point health check → `trade_allowed`
- [x] **Daily pipeline** — `daily_collect` → `tech_fill` → `run_daily` → memo, with Eastmoney fallback + global alignment
- [x] **Pre-market narrative ingest** — `panqian_parser.py` structures briefing notes into the L0 layer

---

## In progress / 进行中

- [ ] **Broader industry-chain drill-down (L3.5)** — deeper upstream/downstream confirmation
- [ ] **Risk-budget → position sizing refinement (L7)** — tighter, evidence-driven position caps
- [ ] **Public `strategy/` docs expansion** — market cycle / sector / leader / risk method papers

---

## Future repositories / 未来仓库（独立，不塞进本仓库）

The flagship is intentionally narrow. Adjacent capabilities will live in their own repos under `xiaoliujoy/`:

| Repo | Purpose |
|------|---------|
| `AI-Investment-Research-System` | The core decision research system (this repo); evolves into `Investment-Research-OS` |
| `Market-Intelligence-Agent` | Automated news / macro / flow / sentiment intelligence |
| `Investment-Knowledge-Base` | Obsidian / RAG / LLM-connected knowledge base |
| `AI-Research-Workflow` | Reusable AI research workflows and prompt systems |

---

## Philosophy of releases / 发布哲学

- **v0.1 mindset:** ship the real, running system + methodology first; polish later. A working operating system beats a 1000-line demo.
- **Methodology is the moat:** code is copyable; the *判环境 / 选方向 / 定标的* process and its long-term iteration are not.
- **Learning in public:** this repo is the "technical paper"; the YouTube channel is the "open classroom"; the system is the "core product".
