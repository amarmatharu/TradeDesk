"""
Transaction Cost Analysis (Phase 3 — execution & ops).

Two halves of the EMS story a pro desk always measures:

  PRE-TRADE  — estimate_cost(): before sizing, estimate the round-trip friction
    (spread + market impact) for an order so it can be fed into expectancy. A
    2.5:1 setup with 40bps of round-trip cost is not really 2.5:1.

  POST-TRADE — record_fill() / report(): after execution, compare the *decision
    price* (what Research planned at) to the *actual fill* → implementation
    shortfall in basis points. Aggregate to see if the system systematically
    pays up (a hidden alpha leak).

Impact model is a simple, transparent square-root law scaled by ATR% — good
enough to make cost visible and act on. numpy-only, no new deps.
"""

import numpy as np
import alpaca_data
from database import get_connection


def ensure_table():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tca_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER,
            ticker TEXT,
            side TEXT,
            decision_price REAL,
            fill_price REAL,
            shares REAL,
            slippage_bps REAL,          -- signed: + = paid worse than decision
            est_cost_bps REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tca_ticker ON tca_records(ticker);
    """)
    conn.commit()
    conn.close()


def _atr_pct(ticker):
    try:
        bars = alpaca_data.get_ohlcv(ticker, period="3mo", interval="1d")
        c = np.array([b["close"] for b in bars if b.get("close")], dtype=float)
        h = np.array([b.get("high", b["close"]) for b in bars if b.get("close")], dtype=float)
        l = np.array([b.get("low", b["close"]) for b in bars if b.get("close")], dtype=float)
        if len(c) < 15:
            return None
        tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        return float(tr[-14:].mean() / c[-1] * 100)
    except Exception:
        return None


def estimate_cost(ticker: str, shares: float, price: float,
                  adv_shares: float = 2_000_000) -> dict:
    """Pre-trade round-trip cost estimate in basis points.

    spread_cost  ~ half-spread proxy from ATR (illiquid/volatile names cost more)
    impact       ~ k * sigma * sqrt(order/ADV)   (square-root market-impact law)
    """
    atrp = _atr_pct(ticker) or 2.0
    notional = abs(shares) * price
    participation = min(1.0, abs(shares) / max(adv_shares, 1))

    spread_bps = min(50.0, max(2.0, atrp * 3.0))          # volatility → spread proxy
    impact_bps = 10.0 * (atrp / 2.0) * np.sqrt(participation) * 100  # sqrt-law, scaled
    impact_bps = float(min(80.0, impact_bps))
    one_way = spread_bps / 2 + impact_bps
    round_trip = 2 * one_way

    return {
        "ticker": ticker,
        "notional": round(notional, 2),
        "participation_of_adv": round(participation, 5),
        "spread_bps": round(spread_bps, 1),
        "impact_bps": round(impact_bps, 1),
        "one_way_bps": round(one_way, 1),
        "round_trip_bps": round(round_trip, 1),
        "round_trip_usd": round(round_trip / 10000 * notional, 2),
        "note": "Estimate — feed round_trip_bps into R:R so cost isn't ignored.",
    }


def record_fill(position_id, ticker, side, decision_price, fill_price, shares) -> dict:
    """Post-trade: log realized implementation shortfall vs the decision price."""
    ensure_table()
    try:
        dp = float(decision_price); fp = float(fill_price)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "bad prices"}
    # For a BUY, paying above decision price is a cost (+bps); reverse for SELL.
    sign = 1 if str(side).upper() in ("BUY", "LONG") else -1
    slippage_bps = sign * (fp - dp) / dp * 10000 if dp else 0.0
    est = estimate_cost(ticker, shares, fp)
    conn = get_connection()
    conn.execute(
        "INSERT INTO tca_records (position_id, ticker, side, decision_price, fill_price, "
        "shares, slippage_bps, est_cost_bps) VALUES (?,?,?,?,?,?,?,?)",
        (position_id, ticker, side, dp, fp, shares, round(slippage_bps, 2),
         est.get("one_way_bps")),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "slippage_bps": round(slippage_bps, 2), "estimated_one_way_bps": est.get("one_way_bps")}


def report() -> dict:
    """Aggregate realized execution quality."""
    ensure_table()
    conn = get_connection()
    rows = conn.execute("SELECT ticker, side, slippage_bps FROM tca_records").fetchall()
    conn.close()
    if not rows:
        return {"n": 0, "note": "No fills recorded yet. Slippage is logged as trades execute."}
    sl = [r["slippage_bps"] for r in rows if r["slippage_bps"] is not None]
    return {
        "n": len(sl),
        "avg_slippage_bps": round(sum(sl) / len(sl), 2) if sl else 0,
        "worst_bps": round(max(sl), 2) if sl else 0,
        "best_bps": round(min(sl), 2) if sl else 0,
        "paying_up": (sum(sl) / len(sl) > 5) if sl else False,
        "note": "Positive avg = systematically filling worse than plan (alpha leak).",
    }
