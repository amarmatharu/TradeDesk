"""
Quantitative risk model (Phase 1 — decision quality).

The existing risk layer is rule-based (max 5 positions, 1.5% per trade, breakers).
That's necessary but not a *portfolio* view. This adds the quantitative lens a
desk actually watches:

  - correlation matrix of open positions (are we secretly one bet?)
  - portfolio beta vs SPY (market exposure)
  - parametric 1-day Value-at-Risk (95%)
  - concentration (Herfindahl index + largest-position weight)

Uses daily closes from alpaca_data (cached). numpy-only, no new deps. Read-only.
"""

import numpy as np
import alpaca_data
from database import get_connection

LOOKBACK = "6mo"


def _open_positions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT ticker, direction, quantity, entry_price FROM positions WHERE status='OPEN'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _returns(ticker):
    """Daily log-ish simple returns from cached OHLCV. Returns np.array or None."""
    try:
        bars = alpaca_data.get_ohlcv(ticker, period=LOOKBACK, interval="1d")
        closes = np.array([b["close"] for b in bars if b.get("close")], dtype=float)
        if len(closes) < 20:
            return None
        return np.diff(closes) / closes[:-1]
    except Exception:
        return None


def _align(series_map):
    """Trim all return series to the same (shortest) length, most recent."""
    lengths = [len(v) for v in series_map.values() if v is not None]
    if not lengths:
        return {}, 0
    n = min(lengths)
    return {k: v[-n:] for k, v in series_map.items() if v is not None}, n


def portfolio_risk() -> dict:
    positions = _open_positions()
    if not positions:
        return {"positions": 0, "note": "No open positions."}

    # Position market values (approx via entry price × qty; sign by direction)
    weights_raw = {}
    for p in positions:
        signed_val = p["entry_price"] * p["quantity"] * (1 if p["direction"] == "LONG" else -1)
        weights_raw[p["ticker"]] = weights_raw.get(p["ticker"], 0.0) + signed_val
    gross = sum(abs(v) for v in weights_raw.values()) or 1.0
    weights = {k: v / gross for k, v in weights_raw.items()}

    # Return series for each name + SPY benchmark
    series = {t: _returns(t) for t in weights}
    series["SPY"] = _returns("SPY")
    aligned, n = _align(series)
    spy = aligned.pop("SPY", None)

    result = {
        "positions": len(positions),
        "gross_exposure": round(gross, 2),
        "net_exposure": round(sum(weights_raw.values()), 2),
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "concentration_hhi": round(sum(w ** 2 for w in weights.values()), 3),
        "largest_weight": round(max((abs(w) for w in weights.values()), default=0), 3),
        "sample_days": n,
    }

    tickers = [t for t in weights if t in aligned]
    if len(tickers) >= 2 and n >= 20:
        mat = np.array([aligned[t] for t in tickers])
        corr = np.corrcoef(mat)
        # average pairwise correlation (off-diagonal)
        iu = np.triu_indices(len(tickers), k=1)
        result["avg_pairwise_corr"] = round(float(np.mean(corr[iu])), 3)
        result["correlation_matrix"] = {
            tickers[i]: {tickers[j]: round(float(corr[i, j]), 2) for j in range(len(tickers))}
            for i in range(len(tickers))
        }
        # Portfolio daily vol & parametric VaR (95%, 1-day)
        w = np.array([weights[t] for t in tickers])
        cov = np.cov(mat)
        port_var = float(w @ cov @ w.T)
        port_vol = float(np.sqrt(max(port_var, 0)))
        result["portfolio_daily_vol_pct"] = round(port_vol * 100, 3)
        result["VaR_95_1d_pct"] = round(1.645 * port_vol * 100, 3)   # of gross exposure
        result["VaR_95_1d_usd"] = round(1.645 * port_vol * gross, 2)

    # Beta vs SPY (single-name weighted)
    if spy is not None and tickers:
        betas = {}
        var_spy = float(np.var(spy)) or 1e-9
        for t in tickers:
            betas[t] = round(float(np.cov(aligned[t], spy)[0, 1] / var_spy), 2)
        result["betas"] = betas
        result["portfolio_beta"] = round(sum(weights[t] * betas[t] for t in tickers), 2)

    result["flags"] = _flags(result)
    return result


def _flags(r):
    out = []
    if r.get("avg_pairwise_corr", 0) > 0.6:
        out.append(f"High avg correlation ({r['avg_pairwise_corr']}) — positions move together; less diversified than it looks.")
    if r.get("largest_weight", 0) > 0.4:
        out.append(f"Concentrated: largest position is {r['largest_weight']*100:.0f}% of gross.")
    if abs(r.get("portfolio_beta", 0)) > 1.5:
        out.append(f"High market exposure: portfolio beta {r['portfolio_beta']}.")
    return out
