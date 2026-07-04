"""
Dual Momentum / GEM (Exp 6) — a DIFFERENT game: tactical asset allocation.

Every prior test tried to find stock-selection alpha and failed. This changes the
mechanism entirely: don't predict individual names — just decide, once a month,
WHICH asset class to hold, and step aside into bonds when equities are in a
downtrend. Gary Antonacci's Global Equities Momentum (GEM):

  Each month, look at trailing 12-month returns:
    - ABSOLUTE momentum: is SPY's 12m return > T-bills? (are stocks trending up?)
        - if NO  -> hold BONDS (AGG). This is the crash-protection switch.
        - if YES -> RELATIVE momentum: hold whichever of US (SPY) / Intl (EFA)
                    has the higher 12m return.

Why it can actually work where stock-picking didn't:
  - It doesn't need alpha — it harvests the equity premium but SIDESTEPS big
    drawdowns (2000-02, 2008, 2022), which is where buy&hold bleeds.
  - Low turnover (a few switches/year) -> costs are trivial.
  - It's a risk-management edge, not a prediction edge.

Tested honestly vs SPY buy&hold and 60/40, net of cost, over all available data
(IEX ~2016+, so it includes 2018, the 2020 COVID crash, and the 2022 bear).

Run:  python3 dual_momentum.py
"""

import os
import time
import pickle
from datetime import datetime, timedelta
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".dm_cache")
os.makedirs(CACHE, exist_ok=True)
LOOKBACK = 252       # 12-month momentum
REBAL = 21           # monthly
COST_BPS = 3.0       # per switch (round-trip-ish); low-turnover so it barely matters
ASSETS = ["SPY", "EFA", "AGG", "BIL"]     # US eq, intl eq, bonds, T-bills(cash)


def _closes(ticker):
    fn = os.path.join(CACHE, f"{ticker}.pkl")
    if os.path.exists(fn):
        try:
            with open(fn, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    import pandas as pd
    end = datetime.now(); start = end - timedelta(days=int(11 * 365.25))
    client = StockHistoricalDataClient(os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY"))
    try:
        req = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Day,
                               start=start, end=end, feed="iex")
        df = client.get_stock_bars(req).df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level=0)
        data = ([i.strftime("%Y-%m-%d") for i in df.index], df["close"].to_numpy(float))
    except Exception:
        data = ([], np.array([]))
    with open(fn, "wb") as f:
        pickle.dump(data, f)
    time.sleep(0.1)
    return data


def build():
    series = {t: dict(zip(*_closes(t))) for t in ASSETS}
    dates = sorted(set.intersection(*[set(s.keys()) for s in series.values()]))
    mat = {t: np.array([series[t][d] for d in dates]) for t in ASSETS}
    return dates, mat


def _mom(arr, t):
    return arr[t] / arr[t - LOOKBACK] - 1.0 if t >= LOOKBACK else None


def backtest(dates, mat):
    n = len(dates)
    daily = []           # (date, return, held_asset)
    held = "BIL"
    t = LOOKBACK + 1
    while t < n - 1:
        if (t - (LOOKBACK + 1)) % REBAL == 0:
            spy_m = _mom(mat["SPY"], t); bil_m = _mom(mat["BIL"], t)
            efa_m = _mom(mat["EFA"], t)
            if spy_m is None:
                pick = "BIL"
            elif spy_m > bil_m:                      # absolute momentum ON
                pick = "SPY" if spy_m >= efa_m else "EFA"
            else:                                     # crash protection
                pick = "AGG"
            cost = 0.0 if pick == held else COST_BPS / 10000.0
            held = pick
        else:
            cost = 0.0
        r = mat[held][t + 1] / mat[held][t] - 1.0 - cost
        daily.append((dates[t + 1], r, held))
        t += 1
    return daily


def _bh(dates, mat, ticker, t0):
    arr = mat[ticker]
    return [(dates[i], arr[i + 1] / arr[i] - 1.0) for i in range(t0, len(dates) - 1)]


def _blend(dates, mat, w, t0):
    out = []
    for i in range(t0, len(dates) - 1):
        r = sum(wt * (mat[tk][i + 1] / mat[tk][i] - 1.0) for tk, wt in w.items())
        out.append((dates[i], r))
    return out


def _stats(daily, label):
    rets = [r for _, r, *_ in daily]
    if len(rets) < 100:
        return {"label": label, "n": len(rets)}
    eq = np.cumprod([1 + r for r in rets])
    cagr = eq[-1] ** (252 / len(rets)) - 1
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1))
    return {
        "label": label, "n": len(rets),
        "cagr_pct": round(cagr * 100, 2),
        "vol_pct": round(float(np.std(rets, ddof=1)) * np.sqrt(252) * 100, 2),
        "sharpe": round(M._sharpe(rets, 252), 2),
        "max_drawdown_pct": round(mdd * 100, 1),
        "total_return_pct": round((eq[-1] - 1) * 100, 1),
    }


def run():
    print(f"\n{'='*70}\n  DUAL MOMENTUM (GEM) — tactical asset allocation\n{'='*70}")
    dates, mat = build()
    print(f"  data: {dates[0]} → {dates[-1]}  ({len(dates)} days)\n")
    t0 = LOOKBACK + 2

    dm = backtest(dates, mat)
    s_dm = _stats(dm, "DUAL MOMENTUM")
    s_spy = _stats(_bh(dates, mat, "SPY", t0), "SPY buy&hold")
    s_6040 = _stats(_blend(dates, mat, {"SPY": 0.6, "AGG": 0.4}, t0), "60/40")

    print(f"  {'strategy':16} {'CAGR%':>7} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>8} {'totalRet%':>10}")
    for x in (s_dm, s_spy, s_6040):
        print(f"  {x['label']:16} {x['cagr_pct']:>7} {x['vol_pct']:>6} {x['sharpe']:>7} "
              f"{x['max_drawdown_pct']:>8} {x['total_return_pct']:>10}")

    # what it held over time (regime awareness)
    from collections import Counter
    holds = Counter(h for *_, h in [(d, r, h) for d, r, h in dm])
    total = sum(holds.values())
    print(f"\n  time in each asset: " + ", ".join(f"{k} {v/total*100:.0f}%" for k, v in holds.most_common()))

    # per-year
    years = {}
    for d, r, _ in dm:
        years.setdefault(d[:4], []).append(r)
    spy_y = {}
    for d, r in _bh(dates, mat, "SPY", t0):
        spy_y.setdefault(d[:4], []).append(r)
    print(f"\n  by year (DM total% / SPY total%):")
    for y in sorted(years):
        dmr = (np.prod([1 + x for x in years[y]]) - 1) * 100
        spyr = (np.prod([1 + x for x in spy_y.get(y, [0])]) - 1) * 100
        print(f"     {y}: {dmr:+6.1f}%  /  {spyr:+6.1f}%")

    print(f"\n  VERDICT:")
    better_sharpe = s_dm["sharpe"] > s_spy["sharpe"]
    smaller_dd = s_dm["max_drawdown_pct"] > s_spy["max_drawdown_pct"]  # closer to 0
    if better_sharpe and smaller_dd:
        print(f"    ✅ WORKS (risk-adjusted): Sharpe {s_dm['sharpe']} vs SPY {s_spy['sharpe']}, "
              f"maxDD {s_dm['max_drawdown_pct']}% vs {s_spy['max_drawdown_pct']}%.")
        print(f"       Not by predicting — by dodging drawdowns. This is retail-runnable.")
    elif smaller_dd:
        print(f"    🟡 Smaller drawdown ({s_dm['max_drawdown_pct']}% vs {s_spy['max_drawdown_pct']}%) but "
              f"Sharpe {s_dm['sharpe']} vs {s_spy['sharpe']} — defensive, gives up return.")
    else:
        print(f"    ❌ No improvement over buy&hold this window.")
    print(f"  ⚠ ~10y window is short & equity-bull-heavy; GEM shines by dodging LONG bears")
    print(f"     (2000-02, 2008) not in this data. Directional, not the full picture.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    envp = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
