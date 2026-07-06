"""
Crypto strategy lab (Exp 14) — does trend/vol-management beat HODL on BTC/ETH?

Crypto is the one asset class where research says trend-following genuinely beats
buy-and-hold — because it trends violently and has huge momentum. Test that on 11
years of daily BTC/ETH (Tiingo), net of cost, same discipline as everything else.

The honest question is NOT raw return (BTC's secular bull makes HODL's CAGR
astronomical) — it's whether trend/vol rules keep most of the upside while cutting
the brutal -80% drawdowns. That drawdown reduction is what makes crypto actually
holdable.

Strategies (long/flat, daily):
  - HODL (buy & hold)
  - MA trend (long when price > N-day average, else cash)  N = 50/100/200
  - Vol-scaled (size by inverse vol percentile — our equity champion, on crypto)

⚠ CAVEATS baked in: crypto history is short (~10y) and one giant bull; momentum
works on BTC/ETH but NEAR-TOTAL LOSSES on small altcoins — this is a BTC/ETH-only
finding. And even the "good" strategy has scary drawdowns.

Run:  python3 crypto_lab.py
"""

import os
import json
import time
import pickle
import urllib.request
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".crypto_cache")
os.makedirs(CACHE, exist_ok=True)
COST_BPS = 10.0     # per side; realistic for BTC/ETH on a major exchange


def _tiingo_crypto(sym):
    fn = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/crypto/prices?tickers={sym}&startDate=2015-01-01&resampleFreq=1day&token={key}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    pd = d[0]["priceData"] if d else []
    out = ([r["date"][:10] for r in pd], np.array([r["close"] for r in pd], float))
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.3)
    return out


def _stats(r):
    r = np.asarray(r); r = r[np.argmax(r != 0):]
    if len(r) < 100:
        return {}
    eq = np.cumprod(1 + r)
    cagr = eq[-1] ** (365 / len(r)) - 1                 # crypto trades 365 days
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    return {"cagr": round(cagr * 100, 1),
            "vol": round(float(np.std(r, ddof=1)) * np.sqrt(365) * 100, 1),
            "sharpe": round(M._mean(list(r)) / (M._std(list(r)) or 1e-9) * np.sqrt(365), 2),
            "mdd": round(mdd * 100, 1),
            "total_x": round(float(eq[-1]), 1)}


def hodl(px):
    return np.concatenate([[0], np.diff(px) / px[:-1]])


def ma_trend(px, n):
    r = hodl(px); ma = np.array([np.mean(px[max(0, i - n):i]) if i >= n else np.nan for i in range(len(px))])
    pos = np.where(px > ma, 1.0, 0.0); pos = np.nan_to_num(pos)
    out = pos[:-1] * r[1:]
    switches = np.abs(np.diff(np.insert(pos[:-1], 0, 0)))
    out = out - switches * COST_BPS / 10000
    return np.concatenate([[0], out])


def vol_scaled(px, cap=1.0, win=20, lb=365):
    r = hodl(px)
    vol = np.array([np.std(r[max(1, i - win):i]) if i > win else np.nan for i in range(len(px))])
    n = len(px); out = np.zeros(n); w = 0.0
    for t in range(lb + 1, n - 1):
        if (t - lb - 1) % 5 == 0 and not np.isnan(vol[t]):
            window = vol[t - lb:t]; pct = np.mean(window[~np.isnan(window)] < vol[t])
            new = float(min(cap, max(0.0, cap * (1 - pct))))
            out[t + 1] -= abs(new - w) * COST_BPS / 10000; w = new
        out[t + 1] += w * r[t + 1]
    return out


def run():
    print(f"\n{'='*72}\n  CRYPTO STRATEGY LAB — trend/vol vs HODL (BTC & ETH, net of {COST_BPS:.0f}bps)\n{'='*72}")
    for sym, label in [("btcusd", "BITCOIN"), ("ethusd", "ETHEREUM")]:
        dates, px = _tiingo_crypto(sym)
        print(f"\n  ── {label} ──  {dates[0]} → {dates[-1]}  ({len(px)} days)")
        print(f"     {'strategy':16} {'CAGR%':>8} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>8} {'grew':>7}")
        rows = [("HODL (buy&hold)", hodl(px)), ("MA-50 trend", ma_trend(px, 50)),
                ("MA-100 trend", ma_trend(px, 100)), ("MA-200 trend", ma_trend(px, 200)),
                ("Vol-scaled", vol_scaled(px))]
        base = _stats(hodl(px))
        for name, r in rows:
            s = _stats(r)
            if not s:
                continue
            better_dd = s['mdd'] > base['mdd']
            print(f"     {name:16} {s['cagr']:>8} {s['vol']:>6} {s['sharpe']:>7} {s['mdd']:>8} {str(s['total_x'])+'x':>7}"
                  + ("  ← smaller DD" if better_dd and name != "HODL (buy&hold)" else ""))

    print(f"\n  READ: HODL's raw CAGR is huge (secular bull) — the real question is whether")
    print(f"  trend rules keep a similar Sharpe with a MUCH smaller max drawdown (the -80%")
    print(f"  HODL crashes are what nobody can actually sit through).")
    print(f"  ⚠ BTC/ETH only. Momentum on small alts = near-total loss. Crypto = extreme risk.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
