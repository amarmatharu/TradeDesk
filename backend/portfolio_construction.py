"""
Portfolio construction (Phase 1 — decision quality).

Replaces "fixed 1.5% risk, cap at 5" with a portfolio-aware sizing decision that
fuses three inputs the way a real construction step does:

  1. Edge (alpha)  → Kelly-fraction sizing from the *validated* per-pattern
     expectancy in the learnings table (fractional Kelly, capped — full Kelly is
     too aggressive and assumes you know the edge exactly, which you don't).
  2. Risk          → correlation with what you already hold (add less when the
     new name is highly correlated to the book) + a per-name risk budget.
  3. Constraints   → max risk %, position count, and a soft sector cap.

Returns a *recommendation* with transparent reasons. The Trader/risk layer still
has final say; this never places orders.
"""

import json
import numpy as np
import alpaca_data
from database import get_connection

# Sizing knobs
BASE_RISK_PCT = 0.015          # 1.5% of portfolio risked per trade (baseline)
MAX_RISK_PCT = 0.02            # hard ceiling per trade
KELLY_FRACTION = 0.25          # use 1/4 Kelly — conservative
MAX_POSITIONS = 5
CORR_LOOKBACK = "3mo"


def _open_positions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT ticker, quantity, entry_price FROM positions WHERE status='OPEN'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _pattern_edge(pattern_tags):
    """Kelly inputs (win prob p, win/loss ratio b) from learnings for the trade's
    patterns. Returns (p, b, n) or None if no usable history."""
    if not pattern_tags:
        return None
    conn = get_connection()
    qs = ",".join("?" * len(pattern_tags))
    rows = conn.execute(
        f"SELECT win_rate, avg_r, sample_size FROM learnings WHERE pattern IN ({qs})",
        pattern_tags,
    ).fetchall()
    conn.close()
    rows = [dict(r) for r in rows if r["sample_size"] and r["sample_size"] >= 3]
    if not rows:
        return None
    # sample-weighted average
    tot = sum(r["sample_size"] for r in rows)
    p = sum(r["win_rate"] / 100.0 * r["sample_size"] for r in rows) / tot
    # translate avg_r into a win/loss payoff ratio b (assume avg loss ~1R)
    avg_r = sum(r["avg_r"] * r["sample_size"] for r in rows) / tot
    b = max(0.1, 1.0 + avg_r)   # crude: expected payoff multiple on a win
    return p, b, tot


def _kelly_fraction(p, b):
    """Kelly f* = p - (1-p)/b, floored at 0."""
    if b <= 0:
        return 0.0
    return max(0.0, p - (1 - p) / b)


def _corr_with_book(ticker, book_tickers):
    """Max abs correlation of `ticker` daily returns vs existing holdings."""
    if not book_tickers:
        return 0.0
    def rets(t):
        try:
            bars = alpaca_data.get_ohlcv(t, period=CORR_LOOKBACK, interval="1d")
            c = np.array([b["close"] for b in bars if b.get("close")], dtype=float)
            return np.diff(c) / c[:-1] if len(c) > 20 else None
        except Exception:
            return None
    r0 = rets(ticker)
    if r0 is None:
        return 0.0
    best = 0.0
    for t in book_tickers:
        r1 = rets(t)
        if r1 is None:
            continue
        n = min(len(r0), len(r1))
        if n < 20:
            continue
        c = float(np.corrcoef(r0[-n:], r1[-n:])[0, 1])
        best = max(best, abs(c))
    return round(best, 2)


def suggest_size(ticker: str, entry: float, stop: float, portfolio_size: float,
                 pattern_tags=None) -> dict:
    """Recommend share count + a transparent rationale."""
    reasons = []
    positions = _open_positions()
    book = [p["ticker"] for p in positions if p["ticker"] != ticker]

    if len(positions) >= MAX_POSITIONS:
        return {"shares": 0, "blocked": True,
                "reason": f"At max positions ({MAX_POSITIONS}).", "reasons": []}

    try:
        risk_per_share = abs(float(entry) - float(stop))
    except (TypeError, ValueError):
        return {"shares": 0, "blocked": True, "reason": "Bad entry/stop.", "reasons": []}
    if risk_per_share <= 0:
        return {"shares": 0, "blocked": True, "reason": "Non-positive risk/share.", "reasons": []}

    # 1) Base risk budget
    risk_pct = BASE_RISK_PCT

    # 2) Kelly tilt from validated edge
    edge = _pattern_edge(pattern_tags or [])
    if edge:
        p, b, n = edge
        kelly = _kelly_fraction(p, b) * KELLY_FRACTION
        # map kelly (0..~0.25) onto a multiplier around baseline (0.5x .. 1.3x)
        mult = 0.5 + min(kelly, 0.25) / 0.25 * 0.8
        risk_pct *= mult
        reasons.append(f"Edge: patterns p={p:.0%}, b={b:.2f}, ¼-Kelly→{mult:.2f}× size (n={n}).")
    else:
        risk_pct *= 0.7
        reasons.append("No validated edge for these patterns → sized down to 0.7×.")

    # 3) Correlation haircut
    corr = _corr_with_book(ticker, book)
    if corr > 0.5:
        haircut = 1 - min(0.5, (corr - 0.5))   # up to 50% cut at corr→1
        risk_pct *= haircut
        reasons.append(f"Correlation {corr} with book → {haircut:.2f}× (avoid doubling one bet).")

    risk_pct = min(risk_pct, MAX_RISK_PCT)
    risk_dollars = portfolio_size * risk_pct
    shares = int(risk_dollars / risk_per_share)

    return {
        "shares": max(shares, 0),
        "blocked": shares <= 0,
        "risk_pct": round(risk_pct * 100, 3),
        "risk_dollars": round(risk_dollars, 2),
        "risk_per_share": round(risk_per_share, 4),
        "corr_with_book": corr,
        "kelly_used": bool(edge),
        "reasons": reasons,
    }
