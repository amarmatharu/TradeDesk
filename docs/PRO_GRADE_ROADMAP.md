# TradeDesk → Professional Grade: Research, Gap Analysis & Roadmap

> Status: living document. Created 2026-07-04. Owner: Amardeep.
> Purpose: benchmark TradeDesk against the most advanced trading systems
> (institutional quant + state-of-the-art multi-agent LLM research), identify
> the gaps, and sequence the work to close them.
>
> **BUILD STATUS (2026-07-04):** An initial implementation of **all five phases**
> shipped on branch `feat/pro-grade-phases` (commits 79bc9c2, 16551f3, b2b55ca,
> 201391d, c78f8c8). These are v1 foundations — real, tested, and wired into the
> pipeline — not the final word on each area. Live endpoints below.

---

## TL;DR

TradeDesk is a strong **event-driven decision harness** with good safety
scaffolding — better bones than most hobby projects. But it is missing the
three things that separate "AI that talks about trades" from "a system with a
validated edge":

1. **Honest validation of the agent pipeline** (it currently trades live-paper
   at ~30% win / negative expectancy with no backtest of the pipeline that
   generates those trades).
2. **Portfolio construction & quantitative risk** (fixed 1.5% risk + 5-position
   cap is not portfolio management).
3. **Adversarial, memory-rich decision-making** (single linear prompts, shallow
   learning loop).

**Build order: validation first.** We are currently tuning a car with no
speedometer. No strategy should reach real money (WeBull) until it clears
out-of-sample statistical gates.

---

## Part 1 — Reference model: what "advanced" looks like

### A. Institutional quant stack
The canonical separation of concerns (Narang, *Inside the Black Box* + modern infra):

| Layer | Responsibility |
|---|---|
| Data layer | Multi-source, **point-in-time**, survivorship-bias-free, tick/L2 |
| Alpha model | Systematic signals/factors → forecasts, combined with *learned* weights |
| Risk model | Factor exposures, VaR, correlation, drawdown limits — quantitative, real-time |
| Transaction-cost model | Estimates slippage/impact *before* sizing |
| Portfolio construction | Optimizer fusing alpha + risk + cost → target weights/sizes (Kelly, risk-parity, mean-variance) |
| Execution (OMS/EMS) | OMS = lifecycle/compliance record; EMS = smart routing, VWAP/TWAP/IS algos |
| Post-trade / TCA | Execution quality, P&L attribution, reconciliation |
| Validation | Walk-forward, purged/combinatorial CV, Deflated Sharpe, Probability of Backtest Overfitting |

### B. State-of-the-art multi-agent LLM trading
- **TradingAgents** (UCLA/MIT): Analyst team → **bull-vs-bear Researcher debate (multi-round)** → Trader → Risk-management team → Portfolio Manager. The debate is the key innovation.
- **FinMem / FinAgent**: **layered memory** (recency + relevance weighting) + **reflection**; retrieves analogous past situations; reduces hallucination.
- **AI Hedge Fund** (virattt, 45k★): **persona agents** each emit signal+confidence → Risk Manager sets position limits → Portfolio Manager aggregates into allocations.

### Sources
- Quant system architecture — https://mbrenndoerfer.com/writing/quant-trading-system-architecture-infrastructure
- OMS/EMS/TCA — https://finerymarkets.com/blog/execution-management-system-explained
- Deflated Sharpe Ratio (Bailey & López de Prado) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Purged cross-validation — https://en.wikipedia.org/wiki/Purged_cross-validation
- 10 Reasons Most ML Funds Fail (López de Prado) — https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf
- TradingAgents — https://arxiv.org/abs/2412.20138 · https://github.com/tauricresearch/tradingagents
- FinMem — https://arxiv.org/abs/2311.13743
- AI Hedge Fund — https://github.com/virattt/ai-hedge-fund

---

## Part 2 — Scorecard: TradeDesk vs professional grade

| Capability | Pro-grade standard | TradeDesk today | Status |
|---|---|---|---|
| Event pipeline | Ingest → triage → decide | Scout→Research→Risk→Trader, event-bus, SSE | ✅ Strong |
| Safety ladder | Staged rollout | SHADOW/SUGGEST/AUTO_PAPER/AUTO_LIVE + breakers | ✅ Strong |
| Audit trail | Every decision logged | `agent_runs`, `events`, `position_checks` | ✅ Good |
| Learning loop | Reflection + memory | Journal→learnings→prompt injection | 🟡 Shallow |
| Adversarial research | Bull/bear debate | Single linear prompts | ❌ Missing |
| Portfolio construction | Optimizer, correlation-aware sizing | Fixed 1.5% risk, cap 5 positions | ❌ Missing |
| Quant risk model | VaR, factor/correlation exposure | Rule breakers only | ❌ Missing |
| Alpha model | Systematic factors + weights | Ad-hoc LLM judgment on news | ❌ Missing |
| Backtesting rigor | Walk-forward, purged CV, Deflated Sharpe, cost-aware | Honest event-study for **one** strategy (insider edge); **agent pipeline untested** | ❌ Critical |
| Execution / TCA | EMS algos, slippage model, post-trade TCA | Market/bracket orders, no TCA | ❌ Missing |
| Data integrity | Point-in-time, survivorship-free | On-demand Alpaca/yfinance, look-ahead risk | 🟡 Weak |
| Reconciliation | Broker ↔ ledger truth | Internal ledger diverges from broker | ❌ Missing |

---

## Part 3 — Phased roadmap

Sequenced by "what must be true before the next thing is worth doing."

### Phase 0 — Ground truth ✅ v1 shipped (`79bc9c2`)
*Goal: honestly measure the system.*
- [x] **Reconciliation service** — `reconciliation.py`, `/api/recon`. (Already caught real ledger↔broker drift.)
- [x] **Point-in-time data capture** — `snapshots.py`; every pipeline decision frozen with a PROMPT_VERSION tag. *(v1 = decision inputs; full market-state snapshotting is a later extension.)*
- [x] **Pipeline replay & validation harness** — `replay.py`, `/api/validation`: pipeline realized edge + confidence calibration.
- [x] **Metrics that matter** — `metrics.py`, `/api/metrics`: expectancy, Sharpe/Sortino, max DD, **Deflated Sharpe**, per-pattern/strategy breakdown, with small-sample caveat. **Dashboard: the "Health" tab (`SystemHealth.jsx`) surfaces all of this + regime/recon/promotion, auto-refresh 30s.**

### Phase 1 — Decision quality ✅ v1 shipped (`16551f3`)
- [x] **Bull/bear Researcher debate** — `agents/debate.py`; both cases injected into the Trader.
- [x] **Portfolio construction** — `portfolio_construction.py`: correlation haircut + fractional-Kelly from validated edge; wired to override raw share counts. *(TODO: explicit sector taxonomy.)*
- [x] **Quantitative risk model** — `risk_model.py`, `/api/risk/portfolio`: correlation matrix, betas, 95% 1-day VaR, HHI concentration.

### Phase 2 — Memory & alpha ✅ v1 shipped (`b2b55ca`)
- [x] **Semantic memory** — `memory.py`, `/api/memory/similar`: dependency-free TF-IDF analogical recall over the trade journal; injected into Research. *(v1 = TF-IDF; embeddings/vector DB are a later upgrade.)*
- [x] **Systematic factor layer** — `signals.py`, `/api/signals/{ticker}`: momentum/trend/mean-reversion/RSI composite. *(TODO: learned combination weights; insider-cluster factor.)*

### Phase 3 — Execution & ops ✅ v1 shipped (`201391d`)
- [x] **TCA** — `tca.py`, `/api/tca` + `/api/tca/estimate`: pre-trade cost estimate (spread + sqrt-impact) and post-trade implementation shortfall. **The R:R gate now subtracts estimated round-trip cost, so the 2.5:1 threshold is net-of-costs.** *(TODO: actual VWAP/TWAP order routing.)*
- [x] **Prompt/model versioning** — stamped on decision snapshots (Phase 0). *(TODO: observability dashboard.)*

### Phase 4 — Robustness & scale ✅ v1 shipped (`c78f8c8`)
- [x] **Regime detection** — `regime.py`, `/api/regime`: trend + volatility regime → risk multiplier, wired into sizing. *(TODO: stress testing, multi-model ensemble.)*
- [x] **Formal live-promotion gate** — `promotion.py`, `/api/promotion`: `can_go_live()` blocks real money until Deflated-Sharpe / sample / drawdown / profit-factor gates pass; wired into the AUTO_LIVE path. *(Currently returns FALSE — as it should.)*

---

## Part 4 — Recommendation

Do **Phase 0 first**, and before a single real-money WeBull trade. The R:R gate
and pattern-veto already shipped (commit `abc134b`) were good instinct but are
patches on an unvalidated pipeline.

**Single highest-leverage build:** the **pipeline replay + validation harness**
(Phase 0) — it converts existing `agent_runs` logs into an evaluation engine,
enabling A/B of prompts, measuring the debate's lift, and proving edge before
risking capital.

---

## Related context
- Current architecture: [ARCHITECTURE.md](../ARCHITECTURE.md), [AGENT_PLAN.md](../AGENT_PLAN.md)
- Strategy state / known negative expectancy + the R:R gate & pattern veto already applied (see project memory `strategy-expectancy-state`).
- WeBull real-money broker is integrated but hard-gated OFF; keep it off until the live-promotion gate (Phase 4) is met.
