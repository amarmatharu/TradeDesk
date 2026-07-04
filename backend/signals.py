"""
Systematic factor signals (Phase 2 — memory & alpha).

TradeDesk is purely *reactive* — it only acts on news/filing events. Real desks
also run *continuous* systematic factors so they're not blind between catalysts.
This computes classic, well-documented factors from daily bars and blends them
into one composite score in [-1, 1]:

  - momentum      : 12-1 style (skip most recent 5d to avoid reversal noise)
  - trend         : EMA20/50/200 stack alignment
  - mean_reversion: z-score of price vs 20d mean (contrarian)
  - volatility    : ATR% (used as a risk scaler, not a directional signal)
  - rsi           : classic 14 (over/under-bought)

numpy-only, cached bars. Directional composite is a transparent weighted blend;
the point is a defensible, inspectable signal — not a black box.
"""

import numpy as np
import alpaca_data


def _closes(ticker, period="1y"):
    bars = alpaca_data.get_ohlcv(ticker, period=period, interval="1d")
    c = np.array([b["close"] for b in bars if b.get("close")], dtype=float)
    h = np.array([b.get("high", b["close"]) for b in bars if b.get("close")], dtype=float)
    l = np.array([b.get("low", b["close"]) for b in bars if b.get("close")], dtype=float)
    return c, h, l


def _ema(x, span):
    if len(x) == 0:
        return None
    a = 2 / (span + 1)
    e = x[0]
    for v in x[1:]:
        e = a * v + (1 - a) * e
    return e


def _rsi(c, n=14):
    if len(c) < n + 1:
        return 50.0
    d = np.diff(c[-(n + 1):])
    up = d[d > 0].sum() / n
    dn = -d[d < 0].sum() / n
    if dn == 0:
        return 100.0
    rs = up / dn
    return 100 - 100 / (1 + rs)


def _atr_pct(c, h, l, n=14):
    if len(c) < n + 1:
        return None
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = tr[-n:].mean()
    return float(atr / c[-1] * 100) if c[-1] else None


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def compute(ticker: str) -> dict:
    """Per-ticker factor bundle + composite directional score in [-1, 1]."""
    try:
        c, h, l = _closes(ticker)
    except Exception as e:
        return {"ticker": ticker, "error": str(e)[:120]}
    if len(c) < 60:
        return {"ticker": ticker, "error": "insufficient history"}

    # Momentum: return from ~252d..5d ago (skip last week)
    look = min(252, len(c) - 6)
    mom = (c[-6] / c[-look] - 1) if look > 5 else 0.0
    mom_score = _clip(mom / 0.4)   # ±40% maps to ±1

    # Trend: EMA stack
    e20, e50, e200 = _ema(c, 20), _ema(c, 50), _ema(c, 200)
    stack = 0
    if e20 and e50 and e200:
        stack = (1 if e20 > e50 else -1) + (1 if e50 > e200 else -1) + (1 if c[-1] > e20 else -1)
    trend_score = _clip(stack / 3.0)

    # Mean reversion: -z-score of price vs 20d mean (contrarian → negative sign)
    m20 = c[-20:].mean(); s20 = c[-20:].std() or 1e-9
    z = (c[-1] - m20) / s20
    mr_score = _clip(-z / 2.0)

    # RSI centered
    rsi = _rsi(c)
    rsi_score = _clip((50 - rsi) / 30.0)   # oversold → positive (contrarian)

    atrp = _atr_pct(c, h, l)

    # Composite: momentum + trend dominate; MR/RSI are smaller contrarian tilts
    composite = _clip(0.4 * mom_score + 0.35 * trend_score + 0.15 * mr_score + 0.10 * rsi_score)

    return {
        "ticker": ticker,
        "composite": round(composite, 3),
        "bias": "LONG" if composite > 0.15 else "SHORT" if composite < -0.15 else "NEUTRAL",
        "factors": {
            "momentum_12_1": round(mom, 3),
            "momentum_score": round(mom_score, 3),
            "trend_stack_score": round(trend_score, 3),
            "mean_reversion_z": round(float(z), 2),
            "rsi_14": round(rsi, 1),
            "atr_pct": round(atrp, 2) if atrp else None,
        },
    }


def scan(tickers: list) -> list:
    """Composite score for a list of tickers, ranked by absolute conviction."""
    out = [compute(t) for t in tickers]
    out = [o for o in out if "error" not in o]
    return sorted(out, key=lambda x: -abs(x["composite"]))
