"""
Tactical allocation lab — the FAIR test (long history via Tiingo).

Finally testable across real bear markets (2008 GFC -55%, 2020 COVID, 2022),
using total-return-adjusted daily data (Tiingo adjClose, dividends included).

Strategies (all low-turnover, retail-runnable, risk-management edges — NOT
stock-picking alpha):

  1. DUAL MOMENTUM (GEM): monthly, if SPY 12m return > 0 hold the stronger of
     US(SPY)/Intl(EFA); else hold bonds(AGG). Steps aside from equity bears.
  2. VOL-TARGET SPY: hold SPY but scale exposure to a constant risk target
     (Moreira-Muir volatility-managed) — cut size when vol spikes (i.e. in
     crashes), lever modestly when calm. Documented Sharpe improvement.
  3. ABS-MOMENTUM SPY: simplest crash filter — hold SPY when 12m return > 0,
     else T-bills(cash). The "200-day-MA"-style timing rule.

Judged vs SPY buy&hold and 60/40 on Sharpe AND drawdown AND behaviour IN the
bear markets (that's where tactical earns its keep).

Run:  python3 tactical_lab.py
"""

import os
import json
import time
import pickle
import urllib.request
from datetime import datetime
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".tiingo_cache")
os.makedirs(CACHE, exist_ok=True)
REBAL = 21
LOOKBACK = 252
VOL_WIN = 40
TARGET_VOL = 0.12 / np.sqrt(252)     # 12% annualized for the vol-target strategy
COST_BPS = 3.0
ASSETS = ["SPY", "EFA", "AGG"]


def _tiingo(sym):
    fn = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1995-01-01&token={key}&format=json&resampleFreq=daily"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    out = ([r["date"][:10] for r in d], np.array([r["adjClose"] for r in d], dtype=float))
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.3)
    return out


def build():
    series = {s: dict(zip(*_tiingo(s))) for s in ASSETS}
    dates = sorted(set.intersection(*[set(s.keys()) for s in series.values()]))
    mat = {s: np.array([series[s][d] for d in dates]) for s in ASSETS}
    return dates, mat


def gem(dates, mat):
    n = len(dates); out = []; held = "AGG"
    t = LOOKBACK + 1
    while t < n - 1:
        if (t - LOOKBACK - 1) % REBAL == 0:
            spy = mat["SPY"][t] / mat["SPY"][t - LOOKBACK] - 1
            efa = mat["EFA"][t] / mat["EFA"][t - LOOKBACK] - 1
            pick = ("SPY" if spy >= efa else "EFA") if spy > 0 else "AGG"
            cost = 0 if pick == held else COST_BPS / 10000
            held = pick
        else:
            cost = 0
        out.append((dates[t + 1], mat[held][t + 1] / mat[held][t] - 1 - cost))
        t += 1
    return out


def abs_mom(dates, mat):
    n = len(dates); out = []; inmkt = False
    t = LOOKBACK + 1
    while t < n - 1:
        if (t - LOOKBACK - 1) % REBAL == 0:
            spy = mat["SPY"][t] / mat["SPY"][t - LOOKBACK] - 1
            newin = spy > 0
            cost = 0 if newin == inmkt else COST_BPS / 10000
            inmkt = newin
        else:
            cost = 0
        r = (mat["SPY"][t + 1] / mat["SPY"][t] - 1) if inmkt else 0.0
        out.append((dates[t + 1], r - cost))
        t += 1
    return out


def vol_target(dates, mat):
    spy = mat["SPY"]; rets = np.diff(spy) / spy[:-1]
    n = len(dates); out = []
    t = LOOKBACK + 1
    lev = 1.0
    while t < n - 1:
        if (t - LOOKBACK - 1) % REBAL == 0:
            v = np.std(rets[t - VOL_WIN:t]) or 1e-9
            lev = min(TARGET_VOL / v, 2.0)      # cap 2x
        out.append((dates[t + 1], lev * (spy[t + 1] / spy[t] - 1)))
        t += 1
    return out


def bench(dates, mat, w):
    out = []
    t = LOOKBACK + 1
    while t < len(dates) - 1:
        out.append((dates[t + 1], sum(wt * (mat[a][t + 1] / mat[a][t] - 1) for a, wt in w.items())))
        t += 1
    return out


def stats(daily, label):
    rets = np.array([r for _, r in daily])
    eq = np.cumprod(1 + rets)
    cagr = eq[-1] ** (252 / len(rets)) - 1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    return {"label": label, "cagr": round(cagr * 100, 2),
            "vol": round(float(np.std(rets, ddof=1)) * np.sqrt(252) * 100, 2),
            "sharpe": round(M._sharpe(list(rets), 252), 2),
            "mdd": round(mdd * 100, 1),
            "total": round((eq[-1] - 1) * 100, 0)}


def bear_ret(daily, start, end):
    rs = [r for d, r in daily if start <= d <= end]
    return round((np.prod([1 + r for r in rs]) - 1) * 100, 1) if rs else None


def run():
    print(f"\n{'='*74}\n  TACTICAL ALLOCATION LAB — long history (Tiingo, total-return)\n{'='*74}")
    dates, mat = build()
    print(f"  data: {dates[0]} → {dates[-1]}  ({len(dates)} days ≈ {len(dates)//252} yrs)\n")

    strats = {"DUAL MOMENTUM (GEM)": gem(dates, mat), "ABS-MOM SPY (in/out)": abs_mom(dates, mat),
              "VOL-TARGET SPY": vol_target(dates, mat), "SPY buy&hold": bench(dates, mat, {"SPY": 1}),
              "60/40": bench(dates, mat, {"SPY": 0.6, "AGG": 0.4})}
    S = {k: stats(v, k) for k, v in strats.items()}

    print(f"  {'strategy':22} {'CAGR%':>6} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>7} {'total%':>8}")
    for k in strats:
        x = S[k]
        print(f"  {k:22} {x['cagr']:>6} {x['vol']:>6} {x['sharpe']:>7} {x['mdd']:>7} {x['total']:>8}")

    print(f"\n  BEHAVIOUR IN BEAR MARKETS (total return during the drawdown):")
    bears = [("2008 GFC", "2007-10-09", "2009-03-09"), ("2020 COVID", "2020-02-19", "2020-03-23"),
             ("2022 bear", "2022-01-03", "2022-10-12")]
    print(f"  {'strategy':22} " + " ".join(f"{b[0]:>12}" for b in bears))
    for k in strats:
        print(f"  {k:22} " + " ".join(f"{str(bear_ret(strats[k], b[1], b[2])):>12}" for b in bears))

    print(f"\n  VERDICT:")
    spy = S["SPY buy&hold"]
    for k in ["DUAL MOMENTUM (GEM)", "ABS-MOM SPY (in/out)", "VOL-TARGET SPY"]:
        x = S[k]
        better = x["sharpe"] > spy["sharpe"]
        safer = x["mdd"] > spy["mdd"]
        tag = "✅ better Sharpe AND smaller DD" if better and safer else \
              "🟡 better risk-adjusted" if better else \
              "🟡 much safer, lower return" if safer and x["cagr"] > 3 else "❌ no improvement"
        print(f"    {k:22} Sharpe {x['sharpe']} vs {spy['sharpe']}  |  maxDD {x['mdd']}% vs {spy['mdd']}%  -> {tag}")
    print(f"{'='*74}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
