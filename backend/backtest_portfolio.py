"""
Breadth-first portfolio backtest of the insider-cluster edge.

This is the "should I bother?" test. It takes the ONE signal TradeDesk ever
found real evidence for (>=2 insiders buying the same name — a structural,
slow-burn signal that lives in less-efficient stocks where a small player
actually has an edge) and asks the honest questions the per-event study can't:

  - As a *portfolio of many small positions* (breadth, not conviction), does it
    make money NET OF TRANSACTION COSTS?
  - Does it hold up OUT-OF-SAMPLE — i.e. quarter after quarter, not just pooled?
  - What's the Deflated Sharpe (edge survives the multiple-testing penalty)?

Reuses backtest.py's cluster reconstruction + look-ahead-safe filing-date entry.
Each quarter is an independent out-of-sample fold. No parameter mining — fixed,
sensible rules — so the result is honest rather than curve-fit.

Run:  python3 backtest_portfolio.py 2025q2 2025q3 2025q4 2026q1
"""

import sys
import time
import backtest as bt
import metrics as M

# ─── Portfolio model ──────────────────────────────────────────────────────────
RISK_PCT = 0.01              # risk 1% of capital per position (at the stop)
ROUND_TRIP_BPS = 30.0        # assumed round-trip cost — insider names skew smaller/
                             # less liquid, so this is realistic-to-slightly-optimistic
MIN_VALUE = 50_000           # cluster must be >= $50k of insider buying
MAX_EVENTS_PER_Q = 120       # breadth cap per quarter (keep runtime sane)

# position notional as a fraction of capital: risk / stop-distance
POS_NOTIONAL_FRAC = RISK_PCT / bt.STOP_PCT           # e.g. 0.01/0.10 = 0.10
COST_ON_CAPITAL = POS_NOTIONAL_FRAC * ROUND_TRIP_BPS / 10000.0

# Simple in-memory bars cache so SPY + repeats aren't refetched every cluster.
_orig_get_bars = bt.get_bars      # keep the real fetcher before patching
_bars_cache = {}
def _bars(ticker, start, end):
    k = (ticker, start, end)
    if k not in _bars_cache:
        _bars_cache[k] = _orig_get_bars(ticker, start, end)
    return _bars_cache[k]
bt.get_bars = _bars   # patch so backtest.simulate() uses the cache


def run_quarter(quarter: str) -> list:
    """Return a list of per-trade results for one quarter (out-of-sample fold)."""
    clusters = bt.build_clusters(quarter)
    clusters = [c for c in clusters if c["total_value"] >= MIN_VALUE][:MAX_EVENTS_PER_Q]
    trades = []
    for i, c in enumerate(clusters):
        r = bt.simulate(c)
        if r.get("ok"):
            # net return on TOTAL capital = risk% * R-multiple  −  round-trip cost
            gross = RISK_PCT * r["r_multiple"]
            net = gross - COST_ON_CAPITAL
            r["ret_gross"] = gross
            r["ret_net"] = net
            r["quarter"] = quarter
            trades.append(r)
        if (i + 1) % 20 == 0:
            print(f"    ...{quarter}: {i+1}/{len(clusters)} simulated ({len(trades)} valid)")
        time.sleep(0.12)
    return trades


def _portfolio_stats(trades, label, n_trials):
    rets = [t["ret_net"] for t in trades]
    n = len(rets)
    if n == 0:
        return {"label": label, "n": 0}
    equity = []
    cum = 0.0
    for r in rets:
        cum += r
        equity.append(cum)
    wins = [r for r in rets if r > 0]
    ppy = 400  # insider clusters resolve in ~2-6 weeks; ~hundreds of trades/yr at breadth
    # excess vs SPY at 20d (from the event study fwd)
    excess = [t["fwd"].get("20_vs_spy") for t in trades if t["fwd"].get("20_vs_spy") is not None]
    return {
        "label": label,
        "n": n,
        "win_rate": round(len(wins) / n * 100, 1),
        "net_return_on_capital_pct": round(cum * 100, 2),          # summed, 1% risk/trade
        "expectancy_bps_per_trade": round(M._mean(rets) * 10000, 1),
        "gross_expectancy_bps": round(M._mean([t["ret_gross"] for t in trades]) * 10000, 1),
        "cost_drag_bps_per_trade": round(COST_ON_CAPITAL * 10000, 1),
        "sharpe_annualized": round(M._sharpe(rets, ppy), 2),
        "deflated_sharpe": M.deflated_sharpe(rets, n_trials),
        "max_drawdown_pct": round(M._max_drawdown(equity) * 100, 2),
        "avg_excess_vs_spy_20d_pct": round(M._mean(excess), 2) if excess else None,
        "pct_beat_spy_20d": round(len([x for x in excess if x > 0]) / len(excess) * 100, 1) if excess else None,
        "reliable": n >= 30,
    }


def run(quarters):
    print(f"\n{'='*70}\n  BREADTH-FIRST INSIDER-EDGE PORTFOLIO BACKTEST\n"
          f"  quarters={quarters}  risk/trade={RISK_PCT*100:.0f}%  cost={ROUND_TRIP_BPS:.0f}bps\n{'='*70}")

    per_q = {}
    all_trades = []
    for q in quarters:
        print(f"\n  ── {q} ──")
        t = run_quarter(q)
        per_q[q] = t
        all_trades.extend(t)

    # n_trials for Deflated Sharpe: we tested this ONE thesis with a couple of
    # sensible rule variants — keep the penalty honest but modest.
    n_trials = 3

    print(f"\n{'='*70}\n  PER-QUARTER (each is an out-of-sample fold)\n{'='*70}")
    print(f"  {'quarter':10} {'n':>4} {'win%':>6} {'exp_bps':>8} {'net%':>7} {'maxDD%':>7} {'vsSPY%':>7} {'beatSPY%':>8}")
    for q in quarters:
        s = _portfolio_stats(per_q[q], q, n_trials)
        if s["n"]:
            print(f"  {q:10} {s['n']:>4} {s['win_rate']:>6} {s['expectancy_bps_per_trade']:>8} "
                  f"{s['net_return_on_capital_pct']:>7} {s['max_drawdown_pct']:>7} "
                  f"{str(s['avg_excess_vs_spy_20d_pct']):>7} {str(s['pct_beat_spy_20d']):>8}")
        else:
            print(f"  {q:10}   (no valid trades)")

    pooled = _portfolio_stats(all_trades, "POOLED", n_trials)
    print(f"\n{'='*70}\n  POOLED PORTFOLIO ({pooled['n']} trades)\n{'='*70}")
    for k in ["win_rate", "gross_expectancy_bps", "cost_drag_bps_per_trade",
              "expectancy_bps_per_trade", "net_return_on_capital_pct",
              "sharpe_annualized", "deflated_sharpe", "max_drawdown_pct",
              "avg_excess_vs_spy_20d_pct", "pct_beat_spy_20d", "reliable"]:
        print(f"    {k:28}: {pooled.get(k)}")

    print(f"\n  VERDICT:")
    exp = pooled.get("expectancy_bps_per_trade") or 0
    dsr = pooled.get("deflated_sharpe") or 0
    beat = pooled.get("pct_beat_spy_20d") or 0
    if pooled["n"] < 50:
        print("    ⚠ Sample too small to conclude — extend the quarter range.")
    elif exp > 0 and dsr >= 0.90 and beat > 52:
        print(f"    ✅ REAL EDGE (net of cost): +{exp}bps/trade, Deflated Sharpe {dsr}, beats SPY {beat}%.")
        print("       Worth promoting to paper as a breadth strategy.")
    elif exp > 0:
        print(f"    🟡 MARGINAL: +{exp}bps/trade but Deflated Sharpe {dsr} (want >=0.90).")
        print("       Possible edge, not proven. More data / tighter filters before real money.")
    else:
        print(f"    ❌ NO EDGE net of cost: {exp}bps/trade. The signal does not survive costs.")
        print("       Don't trade it. Better to know now for free.")
    print(f"{'='*70}\n")
    return pooled


if __name__ == "__main__":
    qs = sys.argv[1:] or ["2025q3", "2025q4", "2026q1"]
    run(qs)
