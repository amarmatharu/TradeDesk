# Edge Analysis: What Profitable Traders Have That We Don't — and Two Tests of Our Best Idea

> Created 2026-07-04. The honest, evidence-based answer to "do we have an edge?"
> Short version: **no demonstrated edge**. This documents why, with research and
> two rigorous out-of-sample backtests, so we don't re-learn it the expensive way.

---

## Part 1 — What the people actually making money have

Researched across institutional quant, multi-manager pod shops, and the academic
literature on why strategies fail. The winners' edges, in order of how much they matter:

1. **A *defined, measured* edge with known capacity.** RenTech's Medallion is "right
   50.75% of the time" — they *know* it. TradeDesk has no identified edge; "an LLM
   reasons about news" is hope, and public-news signals are maximally crowded.
2. **Many small *uncorrelated* bets, not a few big ones.** Medallion: 150–300k trades/day,
   ~2-day holds, 0.01–0.05%/trade, 12.5–20× leverage. Pods: 330+ uncorrelated strategies.
   Sharpe comes from N and orthogonality. TradeDesk runs 5 concentrated, correlated longs.
3. **Transaction-cost obsession.** "Costs will eat you alive" — said about the best fund
   ever. TradeDesk crosses the spread and only started measuring cost this week.
4. **Speed where it's a speed game.** News is priced in ~300ms; latency-arb windows are
   50–200ms. TradeDesk reacts in seconds–minutes → it buys what fast players are selling.
5. **Risk management / capital allocation *as the product*.** Pods: real-time factor
   exposure, ruthless drawdown-based capital cuts, factor-neutral. TradeDesk is long beta.
6. **Information/data advantage** (alt data → act *before* news). TradeDesk acts *on*
   public news. (Silver lining: alt-data costs collapsed, $500k→$5k.)
7. **Playing games retail can win** — small caps, special situations, options/vol. TradeDesk
   plays large-cap, the one arena with zero structural retail edge.

**The core problem:** TradeDesk imitates a discretionary analyst (read story → conviction →
few big bets) — the approach where an LLM has no edge over a pro and gives up the machine's
real strengths (breadth, consistency, systematic diversification).

Sources: RenTech/Medallion (Quartr, Institutional Investor); pod shops (Navnoor Bawa);
alpha decay (López de Prado / Risk.net; arXiv 2605.23905); retail edge (AlgoTrading101,
SMU Cox); news latency (Wharton/Fed IFDP 1233); alt data (ExtractAlpha, Similarweb).

---

## Part 2 — We tested our ONE best idea. Twice. Rigorously.

The insider-cluster signal (≥2 insiders buying the same name) was the only thing with any
prior evidence — structural, slow-burn, lives in less-efficient names. So we tested it the
*right* way: a breadth portfolio of many small 1%-risk positions, net of costs, with each
quarter an independent out-of-sample fold. (`backtest_portfolio.py`, `backtest_refined.py`.)

### Test 1 — broad signal (2025 Q3–Q4, 2026 Q1; 311 trades; 30bps cost)
| | win% | net exp/trade | vs SPY | beat SPY% | Deflated Sharpe |
|---|--:|--:|--:|--:|--:|
| Pooled | 50.5% | +20.7bps | +1.93% | **49.4%** | **0.0** |

Verdict: 🟡 marginal. Profit came almost entirely from **one** quarter (2025 Q4); the other
two were noise. Beat SPY <50% of the time. Positive average = a few fat tails, not breadth.

### Test 2 — refined + fresh data (2024 Q1–Q4, unseen; 283 trades; 60bps cost)
Officer-driven (CEO/CFO), small-cap (<$30M/day), ≥3 insiders — filters chosen from academic
priors, tested on quarters never used to design them.

| Quarter | n | win% | net exp | vs SPY | beat SPY% |
|---|--:|--:|--:|--:|--:|
| 2024 Q1 | 62 | 46.8% | +6.9bps | +0.75% | 46.8% |
| 2024 Q2 | 82 | 48.8% | +21.2bps | −0.20% | 42.7% |
| 2024 Q3 | 69 | 58.0% | +36.6bps | +0.41% | 55.1% |
| 2024 Q4 | 70 | 52.9% | +12.7bps | −0.39% | 44.3% |
| **Pooled** | **283** | 51.6% | +19.7bps | **+0.11%** | **47.0%** |

Verdict: ❌ **no durable edge.** The filter improved *consistency* and cut drawdown (−13%→−6%),
so the methodology works — but **vs SPY it's +0.11% and beats the index only 47% of the time.**
The absolute returns are just "2024 was a bull market and these are longs." No insider alpha
survives the benchmark. Deflated Sharpe 0.

---

## Part 3 — Conclusion & options

**Evidence-based conclusion: do not deploy real money.** Neither the news approach nor the
insider signal (refined or not) beats simply holding SPY. Finding real, durable, cost-surviving
edge is genuinely rare — that's *why* it's valuable.

**What we do have:** an honest validation machine (metrics + Deflated Sharpe + out-of-sample
backtests + reconciliation + promotion gate) that took our best idea and told us the truth
*before* it cost money. That process edge is real and rare among retail.

**Realistic options:**
1. Stop on real money; keep it as a paper/learning platform. The harness vets any future idea.
2. Keep hunting somewhere structurally different (options/vol, market-neutral pairs, genuine
   alt-data) — high failure rate, but failing now costs nothing.
3. Trade tiny as paid education, EV ≈ SPY-at-best, sized so loss is irrelevant.

Ties to [[PRO_GRADE_ROADMAP.md]] and project memory `strategy-expectancy-state`. WeBull real-
money broker stays hard-gated OFF; the promotion gate (`can_go_live()`) correctly returns FALSE.
