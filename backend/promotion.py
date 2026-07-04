"""
Live-promotion gate (Phase 4 — robustness).

The single most important governance control: nothing goes to real money on a
hunch. A strategy (or the whole pipeline) may only be promoted from paper to a
real broker when it clears explicit, statistical, out-of-sample criteria. This
turns "should we go live?" from a feeling into a checklist with a hard verdict.

Gate criteria (all must pass):
  1. Sample size ≥ MIN_TRADES              (enough evidence to mean anything)
  2. Positive expectancy                    (makes money per trade)
  3. Deflated Sharpe ≥ DSR_THRESHOLD        (edge survives multiple-testing penalty)
  4. Max drawdown ≤ MAX_DD_PCT              (survivable)
  5. Profit factor ≥ MIN_PROFIT_FACTOR

This is advisory + enforceable: `can_go_live()` returns a hard bool the broker /
mode layer can check before ever enabling WEBULL_LIVE_TRADING or AUTO_LIVE.
"""

import metrics

MIN_TRADES = 30
DSR_THRESHOLD = 0.90        # deflated Sharpe (prob edge is real) ≥ 90%
MAX_DD_PCT = 15.0           # max drawdown no worse than -15%
MIN_PROFIT_FACTOR = 1.3
MIN_EXPECTANCY = 0.0


def evaluate() -> dict:
    m = metrics.compute_metrics()
    o = m.get("overall", {})
    n = o.get("trades", 0)
    dsr = o.get("deflated_sharpe")
    dd = o.get("max_drawdown_pct")
    pf = o.get("profit_factor")
    exp = o.get("expectancy_usd")

    checks = [
        _chk("sample_size", n >= MIN_TRADES, f"{n} trades", f"need ≥ {MIN_TRADES}"),
        _chk("positive_expectancy", (exp or -1) > MIN_EXPECTANCY, f"${exp}/trade", "need > $0"),
        _chk("deflated_sharpe", (dsr or 0) >= DSR_THRESHOLD, f"{dsr}", f"need ≥ {DSR_THRESHOLD}"),
        _chk("max_drawdown", (dd is not None and dd >= -MAX_DD_PCT), f"{dd}%", f"need ≥ -{MAX_DD_PCT}%"),
        _chk("profit_factor", (pf or 0) >= MIN_PROFIT_FACTOR, f"{pf}", f"need ≥ {MIN_PROFIT_FACTOR}"),
    ]
    passed = all(c["pass"] for c in checks)
    blockers = [c["name"] for c in checks if not c["pass"]]

    return {
        "promotable": passed,
        "verdict": ("READY for live promotion." if passed
                    else f"NOT ready — {len(blockers)} gate(s) failing: {', '.join(blockers)}."),
        "checks": checks,
        "metrics_snapshot": {"trades": n, "expectancy_usd": exp, "deflated_sharpe": dsr,
                             "max_drawdown_pct": dd, "profit_factor": pf},
        "reliability_caveat": m.get("caveat"),
    }


def _chk(name, ok, actual, need):
    return {"name": name, "pass": bool(ok), "actual": actual, "required": need}


def can_go_live() -> bool:
    """Hard gate for the broker/mode layer. Real money requires a passing grade."""
    try:
        return bool(evaluate()["promotable"])
    except Exception:
        return False
