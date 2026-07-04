"""
Market regime detection (Phase 4 — robustness).

A strategy that works in a calm uptrend can bleed in a high-vol chop. Pros scale
exposure by regime instead of trading the same size into every tape. This infers
a simple, transparent regime from SPY:

  - trend  : price vs EMA50/EMA200 (bull / neutral / bear)
  - vol    : 20d realized vol percentile vs its own 1y history (calm / normal / high)

…and maps it to a suggested risk multiplier the portfolio-construction layer can
apply (e.g. cut size in high-vol bear regimes). numpy-only, cached bars.
"""

import numpy as np
import alpaca_data


def _ema(x, span):
    a = 2 / (span + 1)
    e = x[0]
    for v in x[1:]:
        e = a * v + (1 - a) * e
    return e


def detect(benchmark: str = "SPY") -> dict:
    try:
        bars = alpaca_data.get_ohlcv(benchmark, period="1y", interval="1d")
        c = np.array([b["close"] for b in bars if b.get("close")], dtype=float)
    except Exception as e:
        return {"error": str(e)[:120]}
    if len(c) < 60:
        return {"error": "insufficient history"}

    e50, e200 = _ema(c, 50), _ema(c, 200)
    price = c[-1]
    if price > e50 > e200:
        trend = "bull"
    elif price < e50 < e200:
        trend = "bear"
    else:
        trend = "neutral"

    rets = np.diff(c) / c[:-1]
    win = 20
    rolling = np.array([rets[i - win:i].std() for i in range(win, len(rets))])
    cur_vol = rets[-win:].std()
    pct = float((rolling < cur_vol).mean()) if len(rolling) else 0.5
    vol = "high" if pct > 0.8 else "calm" if pct < 0.3 else "normal"
    ann_vol = round(float(cur_vol) * np.sqrt(252) * 100, 1)

    # Risk posture: full size in calm bull, cut hard in high-vol bear
    mult = 1.0
    if trend == "bear":
        mult *= 0.5
    elif trend == "neutral":
        mult *= 0.8
    if vol == "high":
        mult *= 0.6
    elif vol == "calm":
        mult *= 1.1
    mult = round(min(1.2, max(0.3, mult)), 2)

    return {
        "benchmark": benchmark,
        "trend": trend,
        "volatility": vol,
        "vol_percentile": round(pct, 2),
        "annualized_vol_pct": ann_vol,
        "risk_multiplier": mult,
        "posture": _posture(trend, vol, mult),
    }


def _posture(trend, vol, mult):
    if mult >= 1.0:
        return f"Favorable ({trend}/{vol} vol) — full risk budget."
    if mult >= 0.7:
        return f"Cautious ({trend}/{vol} vol) — trim size to {int(mult*100)}%."
    return f"Defensive ({trend}/{vol} vol) — cut size to {int(mult*100)}%; consider standing aside."
