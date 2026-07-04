# TradeDesk → Professional Grade: Research, Gap Analysis & Roadmap

> Status: living document. Created 2026-07-04. Owner: Amardeep.
> Purpose: benchmark TradeDesk against the most advanced trading systems
> (institutional quant + state-of-the-art multi-agent LLM research), identify
> the gaps, and sequence the work to close them.

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

### Phase 0 — Ground truth (do first, before any real-money trade)
*Goal: honestly measure the system.*
- [ ] **Reconciliation service** — continuously diff broker positions vs internal ledger; alert on drift.
- [ ] **Point-in-time data capture** — snapshot exact decision inputs (price/news/fundamentals) so decisions are replayable and backtests are look-ahead-safe.
- [ ] **Pipeline replay & validation harness** — turn `agent_runs` logs into a deterministic replay + evaluation engine (A/B prompts, measure lift).
- [ ] **Metrics that matter** — expectancy, Deflated Sharpe, max drawdown, hit-rate by pattern/strategy, P&L attribution — on a dashboard.

### Phase 1 — Decision quality (highest ROI for the losing win-rate)
*Goal: make each decision more robust.*
- [ ] **Bull/bear Researcher debate** — split Research into adversarial bull vs bear before the Trader synthesizes.
- [ ] **Portfolio construction layer** — correlation-aware sizing, sector/factor exposure limits, Kelly-fraction sizing driven by *validated* per-pattern edge.
- [ ] **Quantitative risk model** — correlation matrix, portfolio beta, simple VaR, concentration limits.

### Phase 2 — Memory & alpha
*Goal: reason from own history + systematic signals.*
- [ ] **Layered/semantic memory** — vector store of past trades/situations; Research retrieves the N most similar setups and how they resolved.
- [ ] **Systematic factor layer** — continuous signals (momentum, mean-reversion, volatility, insider-cluster) to complement reactive news, with learned combination weights.

### Phase 3 — Execution & ops
*Goal: professional execution + observability.*
- [ ] **EMS upgrade** — limit/VWAP/TWAP entries, slippage model feeding pre-trade cost into sizing; post-trade TCA.
- [ ] **Observability & governance** — structured metrics, prompt/model versioning, deterministic replay for model-risk.

### Phase 4 — Robustness & scale
- [ ] Regime detection, stress testing, multi-model ensemble.
- [ ] **Formal live-promotion gate** — no strategy reaches real money until it clears Deflated-Sharpe / PBO thresholds out-of-sample.

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
