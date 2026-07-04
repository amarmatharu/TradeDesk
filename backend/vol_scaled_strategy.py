"""
Volatility-scaled exposure strategy — the deployable champion.

The project's best, most robust system (see docs/WHAT_ACTUALLY_WORKS.md,
vol_scaled_validate.py). It passed every torture test — 12/12 parameter configs,
all four indices, all sub-periods including 2008 — and it's the simplest thing
we tested: size equity exposure by how volatile the market has been lately.

  vol_percentile = rank of current 20-day realized vol vs its own ~2-year history
  target_equity  = clip(1.0 * (1 - vol_percentile), 0, 1.0)   # unlevered (best Sharpe)
  the rest parks in bonds/cash.  Rebalance weekly.

Low vol → hold more; high vol → hold less. No prediction of direction, ever.
`current_allocation()` returns today's target; it only recommends, never trades.
"""

import numpy as np
import alpaca_data

VOL_WINDOW = 20
PCT_LOOKBACK = 504     # ~2 years
CAP = 1.0              # unlevered — best Sharpe (0.95) and safest to run


def _spy_closes():
    for period in ("3y", "2y", "1y"):
        try:
            bars = alpaca_data.get_ohlcv("SPY", period=period, interval="1d")
            c = np.array([b["close"] for b in bars if b.get("close")], dtype=float)
            if len(c) > 120:
                return c
        except Exception:
            continue
    return np.array([])


def current_allocation() -> dict:
    c = _spy_closes()
    if len(c) < 120:
        return {"ok": False, "reason": "insufficient SPY history"}
    rets = np.diff(c) / c[:-1]

    # realized vol series (annualized), then percentile of the latest vs history
    vol = np.array([np.std(rets[max(0, i - VOL_WINDOW):i]) for i in range(1, len(rets) + 1)])
    cur_vol = float(vol[-1])
    window = vol[-min(PCT_LOOKBACK, len(vol)):]
    pct = float(np.mean(window < cur_vol))          # 0 = calmest, 1 = most turbulent
    exposure = round(float(min(CAP, max(0.0, CAP * (1 - pct)))), 2)
    equity_pct = round(min(1.0, exposure) * 100)
    defensive_pct = round(100 - equity_pct)

    ann_vol = round(cur_vol * np.sqrt(252) * 100, 1)
    calm = pct < 0.4
    return {
        "ok": True,
        "target_equity_exposure": exposure,
        "equity_pct": equity_pct,
        "bonds_cash_pct": defensive_pct,
        "signals": {
            "realized_vol_pct": ann_vol,
            "vol_percentile": round(pct, 2),     # where today's vol ranks vs 2y history
            "cap": CAP,
        },
        "regime": "CALM" if calm else "ELEVATED" if pct < 0.75 else "TURBULENT",
        "reasoning": (f"20-day volatility is {ann_vol}% annualized, in the "
                      f"{round(pct*100)}th percentile of its 2-year range → hold "
                      f"{equity_pct}% equities, {defensive_pct}% bonds/cash. "
                      f"{'Calm → stay invested.' if calm else 'Turbulence elevated → de-risk.'}"),
        "rebalance": "weekly",
        "note": "Best risk-adjusted system in testing (Sharpe 0.95 vs SPY 0.67, -19% vs -55% drawdown). Recommendation only.",
    }
