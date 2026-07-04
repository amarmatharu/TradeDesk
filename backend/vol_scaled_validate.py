"""
Clean validation of the volatility-scaled exposure strategy (Exp 12).

The ablation surfaced this as the best signal, but with post-hoc selection bias
(best of 6 sensors). So test it honestly and unbiased:

  Strategy: exposure_to_equity = clip(cap * (1 - vol_percentile), 0, cap),
  where vol_percentile = rank of recent realized vol vs its own trailing history.
  Low vol -> lever up; high vol -> de-risk into bonds. Rebalance weekly.

Torture:
  1. PARAMETER SWEEP — vol window x percentile-lookback x cap x rebalance.
     Robust if the large majority of configs beat SPY, not one lucky cell.
  2. LEVERAGE ISOLATION — cap 1.0 (no leverage) vs 1.3: how much is the vol
     signal vs just leverage in a bull market?
  3. GENERALIZATION — does it work on QQQ / IWM / EFA too, or only SPY?
     (the twin-check that killed turn-of-month.)
  4. SUB-PERIOD consistency.

Run:  python3 vol_scaled_validate.py
"""

import os
import json
import time
import pickle
import urllib.request
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".tiingo_cache")
BORROW = 0.04 / 252
COST_BPS = 2.0


def _tiingo(sym):
    fn = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1995-01-01&token={key}&format=json&resampleFreq=daily"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    out = ([r["date"][:10] for r in d], np.array([r["adjClose"] for r in d], float))
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.3)
    return out


def _align(a, b):
    da, ca = a; db, cb = b
    idx = {d: i for i, d in enumerate(db)}
    common = [d for d in da if d in idx]
    return common, np.array([ca[da.index(d)] for d in common]), np.array([cb[idx[d]] for d in common])


def vol_scaled(px, bond, vol_win=20, pct_lb=504, cap=1.3, rebal=5):
    r = np.concatenate([[0], np.diff(px) / px[:-1]])
    rb = np.concatenate([[0], np.diff(bond) / bond[:-1]])
    vol = np.array([np.std(r[max(1, i - vol_win):i]) if i > vol_win else np.nan for i in range(len(px))])
    n = len(px); out = np.zeros(n); w = 0.0
    for t in range(pct_lb + 1, n - 1):
        if (t - pct_lb - 1) % rebal == 0 and not np.isnan(vol[t]):
            window = vol[t - pct_lb:t]
            pct = np.mean(window[~np.isnan(window)] < vol[t])
            new = float(min(cap, max(0.0, cap * (1 - pct))))
            out[t + 1] -= abs(new - w) * COST_BPS / 10000
            w = new
        bond_w = max(0.0, 1 - w); lev = max(0.0, w - 1)
        out[t + 1] += w * r[t + 1] + bond_w * rb[t + 1] - lev * BORROW
    return out


def _stats(r):
    r = np.asarray(r); r = r[np.argmax(r != 0):]
    if len(r) < 100:
        return {"sharpe": None}
    eq = np.cumprod(1 + r)
    return {"cagr": round((eq[-1] ** (252 / len(r)) - 1) * 100, 1),
            "sharpe": round(M._sharpe(list(r), 252), 2),
            "mdd": round(float(np.min(eq / np.maximum.accumulate(eq) - 1)) * 100, 1)}


def _bh(px):
    return np.concatenate([[0], np.diff(px) / px[:-1]])


def _sub(dates, r, a, b):
    idx = [i for i, d in enumerate(dates) if a <= d <= b and r[i] != 0]
    return round(M._sharpe([r[i] for i in idx], 252), 2) if len(idx) > 100 else None


def run():
    print(f"\n{'='*74}\n  VOLATILITY-SCALED EXPOSURE — clean validation\n{'='*74}")
    agg = _tiingo("AGG")

    # ── base case on SPY ──
    dates, spx, aggc = _align(_tiingo("SPY"), agg)
    base = vol_scaled(spx, aggc)
    b = _stats(base); bh = _stats(_bh(spx))
    print(f"\n  SPY base (20d vol, 2y pct, 1.3x cap, weekly):")
    print(f"     strategy: Sharpe {b['sharpe']}  CAGR {b['cagr']}%  maxDD {b['mdd']}%")
    print(f"     SPY B&H : Sharpe {bh['sharpe']}  CAGR {bh['cagr']}%  maxDD {bh['mdd']}%")

    # ── 1. parameter sweep ──
    print(f"\n  [1] PARAMETER SWEEP (Sharpe; robust if most > SPY {bh['sharpe']}):")
    print(f"      {'vol_win':>8} {'cap=1.0':>8} {'cap=1.3':>8} {'cap=1.5':>8}")
    cells = []
    for vw in [10, 20, 40, 60]:
        row = []
        for cap in [1.0, 1.3, 1.5]:
            s = _stats(vol_scaled(spx, aggc, vol_win=vw, cap=cap))["sharpe"]
            row.append(s); cells.append(s)
        print(f"      {vw:>8} " + " ".join(f"{x:>8}" for x in row))
    wins = sum(1 for c in cells if c and c > bh['sharpe'])
    print(f"      -> {wins}/{len(cells)} configs beat SPY on Sharpe")

    # ── 2. leverage isolation ──
    print(f"\n  [2] LEVERAGE ISOLATION (how much is signal vs bull-market leverage?):")
    for cap in [1.0, 1.3]:
        s = _stats(vol_scaled(spx, aggc, cap=cap))
        print(f"      cap {cap}: Sharpe {s['sharpe']}  CAGR {s['cagr']}%  maxDD {s['mdd']}%")

    # ── 3. generalization to other indices ──
    print(f"\n  [3] GENERALIZATION (does it work beyond SPY? unlevered cap=1.0):")
    for sym in ["SPY", "QQQ", "IWM", "EFA"]:
        try:
            dd, px, ac = _align(_tiingo(sym), agg)
            s = _stats(vol_scaled(px, ac, cap=1.0)); h = _stats(_bh(px))
            tag = "✓" if s['sharpe'] > h['sharpe'] else "✗"
            print(f"      {sym}: vol-scaled Sharpe {s['sharpe']} vs B&H {h['sharpe']}  "
                  f"(maxDD {s['mdd']}% vs {h['mdd']}%)  {tag}")
        except Exception as e:
            print(f"      {sym}: err {str(e)[:40]}")

    # ── 4. sub-period ──
    print(f"\n  [4] SUB-PERIOD CONSISTENCY (SPY, cap 1.3):")
    for a, bb in [("2005-01-01", "2011-12-31"), ("2012-01-01", "2018-12-31"), ("2019-01-01", "2026-12-31")]:
        print(f"      {a[:4]}–{bb[:4]}: Sharpe {_sub(dates, base, a, bb)}")

    print(f"\n  VERDICT: real if most sweep cells beat SPY AND it generalizes to")
    print(f"  QQQ/IWM/EFA AND every sub-period is positive. Fragile if SPY-only or")
    print(f"  only the levered config works.")
    print(f"{'='*74}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
