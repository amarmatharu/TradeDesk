"""
Fundamental factor premiums (Exp 10) — value / quality / momentum / size as funds.

A genuinely different family from everything else: not technical, not trend-
timing — just "tilt toward a documented factor and hold it." These are the
academic premia (Fama-French value/size, quality, momentum) packaged as real,
buyable ETFs. If any factor tilt delivers a better long-run risk-adjusted return
than the plain index, that's a real, passive, retail-runnable edge.

Tested via the actual funds vs SPY over their full histories.

Run:  python3 factor_etf.py
"""

import os
import json
import time
import pickle
import urllib.request
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".tiingo_cache")
FUNDS = {
    "SPY": "S&P 500 (baseline)", "IVE": "S&P 500 Value", "IVW": "S&P 500 Growth",
    "IWD": "Russell 1000 Value", "IWF": "Russell 1000 Growth", "RPV": "Pure Value",
    "VLUE": "MSCI USA Value", "MTUM": "MSCI USA Momentum", "QUAL": "MSCI USA Quality",
    "USMV": "Min Volatility", "IWM": "Small-cap (Russell 2000)", "IJR": "Small-cap 600",
}


def _tiingo(sym):
    fn = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1995-01-01&token={key}&format=json&resampleFreq=daily"
    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        out = ([r["date"][:10] for r in d], np.array([r["adjClose"] for r in d], float))
    except Exception:
        out = ([], np.array([]))
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.3)
    return out


def _stats(c):
    r = c[1:] / c[:-1] - 1.0
    eq = np.cumprod(1 + r)
    return {"cagr": round((eq[-1] ** (252 / len(r)) - 1) * 100, 1),
            "sharpe": round(M._sharpe(list(r), 252), 2),
            "mdd": round(float(np.min(eq / np.maximum.accumulate(eq) - 1)) * 100, 1)}


def run():
    print(f"\n{'='*78}\n  FUNDAMENTAL FACTOR ETFs vs SPY (own-a-tilt-and-hold)\n{'='*78}")
    data = {s: _tiingo(s) for s in FUNDS}
    spy_d, spy_c = data["SPY"]
    spy_idx = {d: i for i, d in enumerate(spy_d)}

    print(f"  {'fund':6} {'since':>10} {'CAGR%':>7} {'Sharpe':>7} {'maxDD%':>7}   {'vs SPY (same window)':>22}")
    beat = 0; tested = 0
    for s, label in FUNDS.items():
        d, c = data[s]
        if len(c) < 252:
            print(f"  {s:6} {'(no data)':>10}")
            continue
        st = _stats(c)
        vs = ""
        if s != "SPY":
            common = [x for x in d if x in spy_idx]
            if len(common) > 252:
                cs = np.array([c[d.index(x)] for x in common])
                sp = np.array([spy_c[spy_idx[x]] for x in common])
                a, b = _stats(cs), _stats(sp)
                better = a["sharpe"] > b["sharpe"]
                tested += 1; beat += better
                vs = f"Sharpe {a['sharpe']} vs {b['sharpe']} {'✓' if better else '✗'}"
        print(f"  {s:6} {d[0]:>10} {st['cagr']:>7} {st['sharpe']:>7} {st['mdd']:>7}   {vs:>22}   {label}")

    print(f"\n  {beat}/{tested} factor ETFs beat SPY on Sharpe over their shared window.")
    print(f"  NOTE: factor premia are real long-run but have DECADE-long dry spells")
    print(f"  (value lagged 2007-2020). A tilt that needs 10y of patience to maybe pay")
    print(f"  is a hard thing to actually hold. Watch how few clear the plain index.")
    print(f"{'='*78}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
