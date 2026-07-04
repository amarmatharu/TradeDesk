"""
Tactical allocation strategy — the deployable version of the one system that
cleared the harness (see docs/EDGE_ANALYSIS.md, tactical_lab.py, robustness_sweep.py).

Combines the two robust winners:
  - GEM crash overlay (absolute + relative momentum): if SPY's 12-month total
    return is positive, hold equities (the stronger of US/Intl); if negative,
    step aside into bonds. This is what dodged -55% in 2008.
  - Volatility targeting: size the equity exposure to a constant risk target
    (scale down when vol spikes, up modestly when calm). Stable 0.77 Sharpe
    across all parameters in the sweep.

Rebalanced monthly. This is a RISK-MANAGEMENT strategy, not alpha: it aims for
roughly the market's return with about half the drawdown. Retail-runnable.

`current_allocation()` returns the target the strategy would hold RIGHT NOW,
with full reasoning. It only recommends — it never places orders.
"""

import numpy as np
import alpaca_data

TARGET_VOL = 0.15          # annualized equity-risk target
VOL_WINDOW = 40            # trading days for realized vol
MOM_LOOKBACK = 240         # ~12 months (trading days)
MAX_EXPOSURE = 1.5         # cap leverage (retail-safe)
EQUITY_US = "SPY"
EQUITY_INTL = "EFA"
DEFENSIVE = "AGG"


def _closes(ticker):
    try:
        bars = alpaca_data.get_ohlcv(ticker, period="1y", interval="1d")
        return np.array([b["close"] for b in bars if b.get("close")], dtype=float)
    except Exception:
        return np.array([])


def _mom(c):
    if len(c) < MOM_LOOKBACK + 1:
        return (c[-1] / c[0] - 1.0) if len(c) > 20 else None    # best-effort on short history
    return c[-1] / c[-MOM_LOOKBACK] - 1.0


def _realized_vol(c):
    if len(c) < VOL_WINDOW + 1:
        return None
    r = np.diff(c[-(VOL_WINDOW + 1):]) / c[-(VOL_WINDOW + 1):-1]
    return float(np.std(r) * np.sqrt(252))


def current_allocation() -> dict:
    spy = _closes(EQUITY_US)
    efa = _closes(EQUITY_INTL)
    if len(spy) < 60:
        return {"ok": False, "reason": "insufficient SPY history"}

    spy_mom = _mom(spy)
    efa_mom = _mom(efa) if len(efa) > 60 else None
    rvol = _realized_vol(spy)

    signals = {
        "spy_12m_pct": round(spy_mom * 100, 1) if spy_mom is not None else None,
        "efa_12m_pct": round(efa_mom * 100, 1) if efa_mom is not None else None,
        "realized_vol_pct": round(rvol * 100, 1) if rvol else None,
        "target_vol_pct": round(TARGET_VOL * 100, 1),
    }

    # ── GEM regime: absolute momentum gate ──
    if spy_mom is None or spy_mom <= 0:
        return {
            "ok": True, "regime": "DEFENSIVE",
            "target_asset": DEFENSIVE, "equity_exposure": 0.0, "cash_pct": 0.0,
            "allocation": {DEFENSIVE: 1.0},
            "signals": signals,
            "reasoning": (f"SPY 12-month return {signals['spy_12m_pct']}% ≤ 0 → absolute "
                          f"momentum OFF. Step aside from equities into bonds ({DEFENSIVE}). "
                          f"This is the crash overlay that dodged 2008."),
            "rebalance": "monthly",
        }

    # ── Risk-on: pick stronger equity, vol-target the exposure ──
    if efa_mom is not None and efa_mom > spy_mom:
        eq, eq_mom = EQUITY_INTL, efa_mom
    else:
        eq, eq_mom = EQUITY_US, spy_mom

    if rvol and rvol > 0:
        exposure = min(MAX_EXPOSURE, TARGET_VOL / rvol)
    else:
        exposure = 1.0
    exposure = round(float(exposure), 2)
    equity_w = min(1.0, exposure)            # portion in the equity ETF
    cash_w = round(max(0.0, 1.0 - exposure), 2)
    lev_note = f"{exposure}x (leveraged)" if exposure > 1 else f"{int(exposure*100)}% invested, {int(cash_w*100)}% cash"

    alloc = {eq: equity_w}
    if cash_w > 0:
        alloc["CASH"] = cash_w

    return {
        "ok": True, "regime": "RISK_ON",
        "target_asset": eq, "equity_exposure": exposure, "cash_pct": round(cash_w * 100, 0),
        "allocation": alloc,
        "signals": signals,
        "reasoning": (f"SPY 12m {signals['spy_12m_pct']}% > 0 → risk-on. "
                      f"{'Intl (EFA) momentum stronger → hold EFA. ' if eq == EQUITY_INTL else 'US (SPY) leads → hold SPY. '}"
                      f"Realized vol {signals['realized_vol_pct']}% vs {signals['target_vol_pct']}% target "
                      f"→ {lev_note}."),
        "rebalance": "monthly",
    }
