"""
Calendar / seasonality effects (Exp 5) — the LOW-TURNOVER angle.

Everything we've tested died to transaction costs or crowding. Calendar effects
are the counter: they're STRUCTURAL (driven by mechanical flows — pension/401k
contributions, month-end index rebalancing, tax dates) and, crucially,
LOW-TURNOVER — you trade a handful of times a month, so costs are trivial. That's
exactly the axis that's been killing the other ideas.

Tests on SPY (and QQQ/IWM to confirm it's not a one-name fluke):

  1. TURN-OF-MONTH (TOM): are returns concentrated in the last day + first ~3
     days of each month? Compare "in-TOM days only" vs "rest-of-month days".
  2. DAY-OF-WEEK: any persistent day effect.
  3. A tradeable TOM timing rule: hold the index ONLY during the TOM window,
     cash otherwise → does it beat buy-and-hold RISK-ADJUSTED with far less
     market exposure? (~30% time in market.)

Daily bars, ~10y for a real seasonal sample. numpy + stdlib only.

Run:  python3 calendar_effects.py
"""

import os
import time
import pickle
from datetime import datetime, timedelta
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".cal_cache")
os.makedirs(CACHE, exist_ok=True)
YEARS = 10
TICKERS = ["SPY", "QQQ", "IWM"]
TOM_BEFORE = 1     # last N trading days of month
TOM_AFTER = 3      # first N trading days of month


def _closes(ticker, start, end):
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


def _tom_mask(dates):
    """True where the date is within the turn-of-month window."""
    months = [d[:7] for d in dates]
    n = len(dates)
    mask = np.zeros(n, dtype=bool)
    # first TOM_AFTER trading days of each month
    seen = {}
    for i, m in enumerate(months):
        seen[m] = seen.get(m, 0) + 1
        if seen[m] <= TOM_AFTER:
            mask[i] = True
    # last TOM_BEFORE trading days of each month
    last = {}
    for i, m in enumerate(months):
        last[m] = i
    # count from the end within each month
    cnt = {}
    for i in range(n - 1, -1, -1):
        m = months[i]
        cnt[m] = cnt.get(m, 0) + 1
        if cnt[m] <= TOM_BEFORE:
            mask[i] = True
    return mask


def _sh(x):
    x = list(x)
    return round(M._sharpe(x, 252), 2) if len(x) > 20 else None

def _ann(x):
    return round(float(np.mean(x)) * 252 * 100, 1) if len(x) else 0.0


def run():
    end = datetime.now(); start = end - timedelta(days=int(YEARS * 365.25) + 20)
    print(f"\n{'='*70}\n  CALENDAR EFFECTS  ({YEARS}y)  TOM=last {TOM_BEFORE}+first {TOM_AFTER} days\n{'='*70}")

    for t in TICKERS:
        d, c = _closes(t, start, end)
        if len(c) < 500:
            print(f"  {t}: insufficient data"); continue
        rets = c[1:] / c[:-1] - 1.0
        dts = d[1:]
        mask = _tom_mask(dts)
        tom = rets[mask]; rest = rets[~mask]
        print(f"\n  ── {t} ──  ({len(rets)} days; {mask.sum()} TOM days = {mask.mean()*100:.0f}% of time)")
        print(f"     TOM days   : ann {_ann(tom):>7}%   Sharpe {_sh(tom)}   avg/day {np.mean(tom)*100:+.3f}%")
        print(f"     rest days  : ann {_ann(rest):>7}%   Sharpe {_sh(rest)}   avg/day {np.mean(rest)*100:+.3f}%")
        # share of total return captured in TOM window
        tot = np.prod(1 + rets) - 1
        tom_only = np.prod(1 + np.where(mask, rets, 0)) - 1
        print(f"     buy&hold total {tot*100:.0f}%  |  TOM-only-invested total {tom_only*100:.0f}% "
              f"(in market {mask.mean()*100:.0f}% of the time)")
        # tradeable timing rule: in market only during TOM (monthly turnover ~2 trades)
        cost_bps = 1.0
        # ~2 transitions per month; approximate daily cost drag only on entry/exit days
        trans = np.abs(np.diff(mask.astype(int)))
        strat = np.where(mask, rets, 0.0)
        strat[1:] -= trans * (cost_bps / 10000.0)
        print(f"     TOM-timing (net): Sharpe {_sh(strat)}  ann {_ann(strat)}%  "
              f"maxDD {round(float(min(np.cumsum(strat)-np.maximum.accumulate(np.cumsum(strat))))*100,1)}%")

    print(f"\n  READ: If TOM days have MUCH higher Sharpe than rest-of-month AND the")
    print(f"  timing rule keeps most of buy&hold's return with ~1/3 the market exposure")
    print(f"  (=> far smaller drawdowns), that's a real, low-cost, structural effect.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    envp = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
