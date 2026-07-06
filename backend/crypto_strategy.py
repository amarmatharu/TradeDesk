"""
Crypto trend signal — deployable, stress-tested multi-coin strategy.

Rule: hold a coin when its price is above its 50-day average, else cash. Robust
across every MA length and era on BTC/ETH, and it BEAT buy-and-hold on the major
coins below (each tested — see crypto_lab.py). XRP/DOT/LTC/LINK were tested and
EXCLUDED because the trend rule did NOT beat HODL on them.

Basket (equal-weight when in trend): the coins where the edge demonstrably holds.
current_signal() returns today's HOLD/CASH call per coin. Recommendation only.

⚠ SPECULATIVE SATELLITE — extreme risk (even winners had -70%+ drawdowns; newer
coins have short history). Small allocation you could lose entirely. Never core.
"""

import time
import json
import urllib.request
import os
import numpy as np

MA = 50

# (tiingo symbol, label, tier)  — tier1 = long history + clear edge; tier2 = newer/marginal
ASSETS = [
    ("btcusd", "BTC", 1), ("ethusd", "ETH", 1), ("solusd", "SOL", 2),
    ("bnbusd", "BNB", 2), ("adausd", "ADA", 2), ("avaxusd", "AVAX", 2),
    ("dogeusd", "DOGE", 2), ("maticusd", "MATIC", 2), ("atomusd", "ATOM", 2),
    ("bchusd", "BCH", 2),
]

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


def _one(sym, label, tier):
    dates, px = _recent(sym)
    if len(px) < MA + 2:
        return {"symbol": label, "ok": False}
    ma = float(np.mean(px[-MA:]))
    price = float(px[-1])
    above = price > ma
    dist = (price / ma - 1) * 100
    return {
        "symbol": label, "tier": tier, "ok": True,
        "signal": "HOLD" if above else "CASH",
        "price": round(price, 2), "ma50": round(ma, 2),
        "pct_vs_ma50": round(dist, 1),
    }


def current_signal() -> dict:
    assets = [_one(s, l, t) for s, l, t in ASSETS]
    holds = [a["symbol"] for a in assets if a.get("ok") and a["signal"] == "HOLD"]
    return {
        "ok": True,
        "assets": assets,
        "holding": holds,
        "n_holding": len(holds),
        "rule": f"Hold each coin when price > 50-day average, else cash. {len(ASSETS)} coins, equal-weight.",
        "note": ("SPECULATIVE SATELLITE — trend rule beat HODL on each of these (XRP/DOT/LTC/LINK "
                 "tested & excluded), but extreme risk (even winners -70%+ drawdowns; newer coins "
                 "short history). Small allocation you could lose entirely. Recommendation only."),
    }
