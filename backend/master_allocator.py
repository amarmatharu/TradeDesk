"""
Master Allocator — the unified decision engine.

Combines everything the research VALIDATED into one daily/weekly plan, in a
core-satellite structure (how real endowments actually run money):

  CORE (validated, does the real work):
    - GEM crash protection: if SPY 12-month return <= 0 -> DEFENSIVE (all bonds).
      Otherwise risk-on, holding the stronger of US(SPY)/Intl(EFA).
    - Volatility-scaled sizing: within risk-on, size equity to (1 - vol_percentile)
      -> hold more when calm, less when turbulent; remainder in bonds.

  SATELLITE (0-10%, strictly capped, SPECULATIVE):
    - High-conviction agent signals (news/insider). The research showed these have
      NO proven edge, so they are hard-capped and flagged. Gated by the Risk Guard;
      the Journal learns from their outcomes. A bad satellite cannot sink the core.

Output: current_plan() -> a clear allocation (% of capital per asset) + any active
trade signals, with full reasoning. RECOMMENDATION ONLY — places no orders.
"""

import os
import numpy as np
import alpaca_data

# ── knobs ──
MOM_LOOKBACK = 240          # ~12 months
VOL_WINDOW = 20
PCT_LOOKBACK = 504          # ~2 years
SATELLITE_MAX_PCT = float(os.environ.get("SATELLITE_MAX_PCT", "10"))   # cap on speculative sleeve
SATELLITE_PER_TRADE_PCT = 2.0
HIGH_CONVICTION = 8         # agent confidence >= this to qualify


def _closes(t):
    try:
        bars = alpaca_data.get_ohlcv(t, period="3y", interval="1d")
        c = np.array([b["close"] for b in bars if b.get("close")], dtype=float)
        return c
    except Exception:
        return np.array([])


def _mom(c):
    if len(c) < MOM_LOOKBACK + 1:
        return (c[-1] / c[0] - 1.0) if len(c) > 40 else None
    return c[-1] / c[-MOM_LOOKBACK] - 1.0


def _vol_percentile(c):
    if len(c) < 60:
        return None, None
    r = np.diff(c) / c[:-1]
    vol = np.array([np.std(r[max(0, i - VOL_WINDOW):i]) for i in range(1, len(r) + 1)])
    cur = float(vol[-1])
    window = vol[-min(PCT_LOOKBACK, len(vol)):]
    return float(np.mean(window < cur)), round(cur * np.sqrt(252) * 100, 1)


def _satellite_signals():
    """High-conviction agent pending trades — the speculative sleeve (capped)."""
    try:
        from database import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT ticker, direction, entry, stop, confidence, thesis FROM pending_trades "
            "WHERE status='pending' AND confidence >= ? ORDER BY confidence DESC LIMIT 5",
            (HIGH_CONVICTION,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def current_plan() -> dict:
    spy = _closes("SPY"); efa = _closes("EFA")
    if len(spy) < 60:
        return {"ok": False, "reason": "insufficient SPY history"}

    spy_m = _mom(spy); efa_m = _mom(efa) if len(efa) > 60 else None
    vol_pct, ann_vol = _vol_percentile(spy)

    # ── satellite first (reserve budget only if real signals exist) ──
    sats = _satellite_signals()
    sat_used = min(SATELLITE_MAX_PCT, len(sats) * SATELLITE_PER_TRADE_PCT)
    core_cap = 100.0 - sat_used

    # ── GEM regime ──
    if spy_m is None or spy_m <= 0:
        regime = "DEFENSIVE"
        core = {"AGG (bonds)": round(core_cap, 1)}
        core_reason = (f"CORE: SPY 12-month return {round((spy_m or 0)*100,1)}% ≤ 0 → GEM crash "
                       f"protection ON. Hold bonds, out of equities entirely.")
    else:
        regime = "RISK_ON"
        asset = "SPY" if (efa_m is None or spy_m >= efa_m) else "EFA"
        eq_frac = float(min(1.0, max(0.0, 1 - (vol_pct if vol_pct is not None else 0.5))))
        eq_pct = round(eq_frac * core_cap, 1)
        bond_pct = round(core_cap - eq_pct, 1)
        core = {asset: eq_pct, "AGG (bonds)": bond_pct}
        core_reason = (f"CORE: SPY 12m {round(spy_m*100,1)}% > 0 → risk-on, hold {asset}"
                       f"{' (Intl momentum stronger)' if asset=='EFA' else ''}. "
                       f"Volatility {ann_vol}% in the {round((vol_pct or 0)*100)}th percentile → "
                       f"size equity to {eq_pct}% of capital, {bond_pct}% bonds.")

    satellite = {
        "budget_pct": SATELLITE_MAX_PCT,
        "used_pct": round(sat_used, 1),
        "active_signals": [{
            "ticker": s["ticker"], "direction": s["direction"], "entry": s["entry"],
            "stop": s["stop"], "confidence": s["confidence"],
            "size_pct": SATELLITE_PER_TRADE_PCT,
            "thesis": (s.get("thesis") or "")[:160],
        } for s in sats],
        "note": ("SPECULATIVE — agent news/insider signals have NO proven edge in our testing; "
                 "hard-capped and Risk-Guard-gated. Do not oversize. Journal tracks outcomes."),
    }

    return {
        "ok": True,
        "regime": regime,
        "core_allocation": core,
        "core_reasoning": core_reason,
        "satellite": satellite,
        "signals": {
            "spy_12m_pct": round(spy_m * 100, 1) if spy_m is not None else None,
            "efa_12m_pct": round(efa_m * 100, 1) if efa_m is not None else None,
            "realized_vol_pct": ann_vol,
            "vol_percentile": round(vol_pct, 2) if vol_pct is not None else None,
        },
        "rebalance": "Core: weekly. Satellite: as signaled (and Risk-Guard-gated).",
        "note": "Recommendation only — places no orders. Core is validated; satellite is speculative and capped.",
    }
