"""
Crypto trend signal — the deployable, stress-tested crypto strategy.

The one crypto approach that beat HODL and survived the torture test (see
crypto_lab.py, crypto_stress.py): hold BTC/ETH when price is above its 50-day
average, move to cash when it drops below. Robust across every MA length and
every era; it dodged most of the 2018/2022 crash damage.

current_signal() returns today's HOLD/CASH call for BTC and ETH. Recommendation
only — places no orders. This is a SPECULATIVE SATELLITE (extreme risk, still
-55% drawdowns); never a core holding.
"""

import time
import json
import urllib.request
import os
import numpy as np

MA = 50
_CACHE = {}     # sym -> (ts, (dates, closes))


def _recent(sym):
    c = _CACHE.get(sym)
    if c and time.time() - c[0] < 3600:      # 1h cache
        return c[1]
    key = os.environ.get("TIINGO_KEY", "")
    out = ([], np.array([]))
    if key:
        try:
            url = (f"https://api.tiingo.com/tiingo/crypto/prices?tickers={sym}"
                   f"&startDate=2025-01-01&resampleFreq=1day&token={key}")
            req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
            pd = d[0]["priceData"] if d else []
            out = ([r["date"][:10] for r in pd], np.array([r["close"] for r in pd], float))
        except Exception:
            out = _CACHE.get(sym, (0, out))[1]
    _CACHE[sym] = (time.time(), out)
    return out


def _one(sym, label):
    dates, px = _recent(sym)
    if len(px) < MA + 2:
        return {"symbol": label, "ok": False}
    ma = float(np.mean(px[-MA:]))
    price = float(px[-1])
    above = price > ma
    dist = (price / ma - 1) * 100
    return {
        "symbol": label,
        "ok": True,
        "signal": "HOLD" if above else "CASH",
        "price": round(price, 2),
        "ma50": round(ma, 2),
        "pct_vs_ma50": round(dist, 1),
        "reasoning": (f"{label} ${price:,.0f} is {abs(dist):.1f}% "
                      f"{'above' if above else 'below'} its 50-day average "
                      f"(${ma:,.0f}) → {'HOLD' if above else 'move to CASH'}."),
    }


def current_signal() -> dict:
    return {
        "ok": True,
        "assets": [_one("btcusd", "BTC"), _one("ethusd", "ETH")],
        "rule": "Hold when price > 50-day average, else cash. Check ~daily.",
        "note": ("SPECULATIVE SATELLITE — beat HODL & survived stress-testing, but "
                 "extreme risk (still ~-55% drawdowns). Small allocation you could "
                 "lose entirely. BTC/ETH only; do NOT extend to altcoins. Recommendation only."),
    }
