"""
Volatility risk premium (Exp 8) — the one real edge in the options space.

Option buyers systematically overpay: implied vol > realized vol, on average.
So SELLERS of premium collect that gap — a genuine, documented risk premium (you
get paid for underwriting crash risk, like an insurance company). We can't easily
test granular options here, but there are MECHANICAL premium-selling indices/ETFs
that do exactly this on the S&P 500 every month:

  - PutWrite (sell cash-secured ATM puts): PUTW etf, ^PUT index
  - BuyWrite / covered call (hold SPX, sell calls): BXMX, PBP, XYLD etfs, ^BXM
  - JEPI: modern active premium-income (2020+)

The honest questions:
  1. Does premium-selling beat SPY RISK-ADJUSTED (higher Sharpe / lower vol)?
     — that's what the vol risk premium should deliver.
  2. Does the STEAMROLLER show up? i.e. does it still crash in 2008/2020?
     — premium-sellers have NO crash protection; the tail is the catch.

Run:  python3 vol_premium.py
"""

import os
import json
import time
import pickle
import urllib.request
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".tiingo_cache")
os.makedirs(CACHE, exist_ok=True)

# premium-selling proxies (longest history first where possible)
CANDIDATES = ["SPY", "BXMX", "PBP", "PUTW", "XYLD", "QYLD", "JEPI"]
BEARS = [("2008 GFC", "2007-10-09", "2009-03-09"),
         ("2020 COVID", "2020-02-19", "2020-03-23"),
         ("2022 bear", "2022-01-03", "2022-10-12")]


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


def _stats(dates, c):
    rets = c[1:] / c[:-1] - 1.0
    eq = np.cumprod(1 + rets)
    cagr = eq[-1] ** (252 / len(rets)) - 1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    return {"start": dates[0], "cagr": round(cagr * 100, 1),
            "vol": round(float(np.std(rets, ddof=1)) * np.sqrt(252) * 100, 1),
            "sharpe": round(M._sharpe(list(rets), 252), 2), "mdd": round(mdd * 100, 1)}


def _bear(dates, c, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if len(idx) < 2:
        return None
    return round((c[idx[-1]] / c[idx[0]] - 1) * 100, 1)


def run():
    print(f"\n{'='*76}\n  VOLATILITY RISK PREMIUM — mechanical premium-selling vs SPY\n{'='*76}")
    data = {}
    for s in CANDIDATES:
        d, c = _tiingo(s)
        if len(c) > 252:
            data[s] = (d, c)

    print(f"  {'ticker':7} {'since':>10} {'CAGR%':>7} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>8}   what")
    labels = {"SPY": "the index (baseline)", "BXMX": "covered-call (Nuveen)", "PBP": "covered-call (Invesco)",
              "PUTW": "put-write", "XYLD": "covered-call (Global X)", "QYLD": "covered-call (Nasdaq)",
              "JEPI": "active premium-income"}
    for s in CANDIDATES:
        if s not in data:
            print(f"  {s:7} {'(no data)':>10}")
            continue
        st = _stats(*data[s])
        print(f"  {s:7} {st['start']:>10} {st['cagr']:>7} {st['vol']:>6} {st['sharpe']:>7} {st['mdd']:>8}   {labels.get(s,'')}")

    # apples-to-apples: compare each proxy to SPY over their COMMON window
    print(f"\n  APPLES-TO-APPLES (each vs SPY over their shared history):")
    spy_d, spy_c = data["SPY"]
    spy_idx = {d: i for i, d in enumerate(spy_d)}
    for s in CANDIDATES[1:]:
        if s not in data:
            continue
        d, c = data[s]
        common = [x for x in d if x in spy_idx]
        if len(common) < 252:
            continue
        cs = np.array([c[d.index(x)] for x in common])
        sp = np.array([spy_c[spy_idx[x]] for x in common])
        a = _stats(common, cs); b = _stats(common, sp)
        verdict = "✓ better Sharpe" if a["sharpe"] > b["sharpe"] else "✗ worse Sharpe"
        print(f"    {s:6} ({common[0]}→): Sharpe {a['sharpe']} vs SPY {b['sharpe']}  | "
              f"CAGR {a['cagr']}% vs {b['cagr']}%  | maxDD {a['mdd']}% vs {b['mdd']}%  {verdict}")

    print(f"\n  THE STEAMROLLER CHECK (return during each bear market):")
    print(f"  {'ticker':7} " + " ".join(f"{b[0]:>12}" for b in BEARS))
    for s in CANDIDATES:
        if s not in data:
            continue
        d, c = data[s]
        print(f"  {s:7} " + " ".join(f"{str(_bear(d, c, b[1], b[2])):>12}" for b in BEARS))

    print(f"\n  READ: vol risk premium is real if premium-sellers show HIGHER Sharpe /")
    print(f"  LOWER vol than SPY. But watch the bear columns — if they crash nearly as")
    print(f"  hard as SPY, there's your steamroller: real edge, but NO crash protection.")
    print(f"{'='*76}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
