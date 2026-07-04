# What Actually Works — the definitive record

> The honest conclusion of a 12-experiment research program that tested essentially
> every retail-accessible strategy family with the same rigor: net of costs,
> out-of-sample, stress-tested, and *believed only after surviving torture.*
> If it isn't here as a ✅, we tested it and it failed.

---

## The one-paragraph truth
**Nothing beats the market's raw return** — not stock-picking, not technical
patterns, not options income, not factor tilts, not a novel system we designed
ourselves. But **three things reliably beat it on *risk-adjusted* terms**, and all
three do the same one thing: **get smaller before trouble, using volatility and
trend as the signal.** The durable retail edge is *risk management and
diversification, not prediction.* And the deepest lesson: **simple beat clever,
every time** — our fanciest invention lost to a one-line volatility rule.

---

## The scoreboard (12 experiments)

| # | Family | Module | Verdict |
|---|---|---|:--:|
| 1 | Insider-cluster signals | `backtest_portfolio.py`, `backtest_refined.py` | ❌ no alpha vs SPY |
| 2 | Cross-sectional factors (mom/rev/low-vol) | `factor_lab.py` | ❌ |
| 3 | Trend-following (ETF basket) | `trend_follow.py` | 🟡 diversifier only |
| 4 | Overnight vs intraday anomaly | `overnight.py` | ❌ real but untradeable (cost) |
| 5 | Calendar / turn-of-month | `calendar_effects.py`, `tom_stress.py` | ❌ in-sample luck |
| 6 | **Tactical allocation (GEM / vol-target)** | `tactical_lab.py` | ✅ **works** |
| 7 | Technical / Pine-script setups | `technical_lab.py` | ❌ 6 of 7 lose |
| 8 | Options income / vol risk premium | `vol_premium.py` | ❌ loses to buy&hold |
| 9 | **Multi-strategy blend** | `multi_strategy.py` | ✅ **works (crisis-positive)** |
| 10 | Fundamental factor tilts (value/quality/…) | `factor_etf.py` | ❌ 1 of 11 |
| 11 | Original "Fragility Thermostat" (6-sensor) | `fragility_engine.py`, `fragility_ablation.py` | ❌ lost to simple vol |
| 12 | **Volatility-scaled exposure** | `vol_scaled_validate.py` | ✅ **best & most robust** |

---

## The three winners (all risk-management, none beats market raw return)

| System | Sharpe | Return | Max DD | Character |
|---|--:|--:|--:|---|
| **Volatility-scaled exposure** 🏆 | **0.95** | ~8–9% | **−19%** | Simplest, most robust; best risk-adjusted |
| Tactical allocation (deployed) | 0.77 | ~11.6% | −34% | Keeps market return, dodges slow bears |
| Multi-strategy blend | 0.74 | 5.7% | −16% | Max defense; +2.9% in 2008 |
| — SPY buy & hold (benchmark) | 0.67 | 11.3% | −55% | The thing to beat |

**Champion rule (vol-scaled):** *hold more equities when 20-day volatility is low, fewer
(park in bonds) when it spikes; rebalance weekly, no leverage.* It passed every torture test —
12/12 parameter configs beat SPY, works on SPY/QQQ/IWM/EFA, positive in all sub-periods incl. 2008,
and the edge is the vol signal (unlevered beats levered). Deployed live: `vol_scaled_strategy.py`,
`/api/volscaled/allocation`, Health tab.

---

## What we proved does NOT work (so you never pay this tuition)
- **Stock-picking / news / LLM prediction** — you're on the wrong side of speed, data, and crowding.
- **Technical patterns** (RSI, MACD, EMA cross, Bollinger, breakout) — 6 of 7 lose to buy&hold;
  high-turnover ones die to costs. Only the slow golden cross works — because it's trend-following.
- **Options income** (covered calls, put-write, the wheel) — cap upside, keep downside;
  every proxy had a *worse* Sharpe than the index. The "income" is an illusion.
- **Factor tilts** (value/size/quality) — decayed after they were packaged as ETFs; 1 of 11 beat SPY.
- **Calendar / overnight anomalies** — real but either untradeable (cost) or in-sample luck.
- **Complex/clever designs** — our 6-sensor engine lost to one volatility gauge.

## The meta-lessons (worth more than any single strategy)
1. **Prediction is a losing game for retail; risk management is a winnable one.**
2. **Volatility is the king signal** — it appears in every winner. It clusters and predicts risk.
3. **Simple > clever.** Complexity added noise, not signal. Occam's razor generalizes.
4. **Costs and out-of-sample testing kill most "edges."** Test net-of-cost or fool yourself.
5. **The real edge is the *process*** — the harness that generates, tests, and *kills* ideas
   honestly (including our own). Almost nobody has it. That is the system that "doesn't exist."

## Standing rules
- Real money stays gated: WeBull `WEBULL_LIVE_TRADING=false`; promotion gate must pass first.
- No strategy is trusted until it survives: net-of-cost + out-of-sample + parameter sweep +
  cross-asset/twin check + sub-period consistency.

See also: [PRO_GRADE_ROADMAP.md](PRO_GRADE_ROADMAP.md), [EDGE_ANALYSIS.md](EDGE_ANALYSIS.md).
