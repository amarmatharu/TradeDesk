"""
Overnight vs intraday return anomaly (Exp 4).

One of the most robust, least-"predictive" anomalies in equities: for decades,
essentially ALL of the market's return has accrued OVERNIGHT (close -> next open),
while the INTRADAY session (open -> close) has been roughly flat-to-negative.
It's structural, not a forecast — driven by overnight risk premia, ETF creation/
redemption flows, and retail buying-at-the-open. That makes it interesting: a
structural effect is harder to arbitrage away than a clever signal.

Two tests:
  1. INDEX-LEVEL — decompose SPY/QQQ/IWM total return into overnight vs intraday.
     If overnight Sharpe >> total Sharpe, the effect is present and huge.
  2. TRADEABILITY — the catch: capturing overnight-only means a round trip EVERY
     day (buy MOC, sell MOO), so it's cost-murdered. We charge realistic per-day
     costs and see what survives. This is the honest part everyone skips.

Uses open+close daily bars (own cache). numpy-only.

Run:  python3 overnight.py
"""

import os
import time
import pickle
from datetime import datetime, timedelta
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".overnight_cache")
os.makedirs(CACHE, exist_ok=True)
YEARS = 6
INDICES = ["SPY", "QQQ", "IWM"]
# a few liquid single names to check it's not just an index artifact
NAMES = ["AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "META", "JPM", "XOM", "WMT", "UNH"]


def _oc(ticker, start, end):
    """Cached (dates, opens, closes)."""
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
        data = ([i.strftime("%Y-%m-%d") for i in df.index],
                df["open"].to_numpy(float), df["close"].to_numpy(float))
    except Exception:
        data = ([], np.array([]), np.array([]))
    with open(fn, "wb") as f:
        pickle.dump(data, f)
    time.sleep(0.1)
    return data


def _series(ticker, start, end):
    d, o, c = _oc(ticker, start, end)
    if len(c) < 200:
        return None
    o, c = np.asarray(o), np.asarray(c)
    overnight = o[1:] / c[:-1] - 1.0        # close[t-1] -> open[t]
    intraday = c[1:] / o[1:] - 1.0          # open[t]   -> close[t]
    total = c[1:] / c[:-1] - 1.0
    return {"overnight": overnight, "intraday": intraday, "total": total}


def _sh(x):
    return round(M._sharpe(list(x), 252), 2)

def _ann(x):
    return round(float(np.mean(x)) * 252 * 100, 1)


def run():
    end = datetime.now(); start = end - timedelta(days=int(YEARS * 365.25) + 20)
    print(f"\n{'='*70}\n  OVERNIGHT vs INTRADAY ANOMALY  ({YEARS}y)\n{'='*70}")
    print(f"  {'ticker':7} {'total_Sh':>9} {'ON_Sh':>7} {'ID_Sh':>7} {'total%':>8} {'ON%':>8} {'ID%':>8}")

    all_on, all_id = [], []
    for t in INDICES + NAMES:
        s = _series(t, start, end)
        if not s:
            continue
        all_on.append(s["overnight"]); all_id.append(s["intraday"])
        print(f"  {t:7} {_sh(s['total']):>9} {_sh(s['overnight']):>7} {_sh(s['intraday']):>7} "
              f"{_ann(s['total']):>8} {_ann(s['overnight']):>8} {_ann(s['intraday']):>8}")

    # Portfolio: equal-weight all names, overnight-only vs intraday-only vs total
    n = min(len(x) for x in all_on)
    ON = np.mean([x[-n:] for x in all_on], axis=0)
    ID = np.mean([x[-n:] for x in all_id], axis=0)
    TOT = ON + ID
    print(f"\n  EQUAL-WEIGHT BASKET ({len(all_on)} names):")
    print(f"    total      : Sharpe {_sh(TOT)}   ann {_ann(TOT)}%")
    print(f"    overnight  : Sharpe {_sh(ON)}   ann {_ann(ON)}%")
    print(f"    intraday   : Sharpe {_sh(ID)}   ann {_ann(ID)}%")

    # Tradeability: overnight-only requires a round trip EVERY day. Charge cost.
    print(f"\n  TRADEABILITY of overnight-only (daily round trip, net of cost):")
    for cost_bps in (1, 2, 5, 10):
        net = ON - 2 * cost_bps / 10000.0        # buy MOC + sell MOO
        print(f"    @ {cost_bps:>2}bps/side: Sharpe {_sh(net):>6}   ann {_ann(net):>6}%   "
              f"{'✅ survives' if _ann(net) > 3 and _sh(net) > 0.7 else '❌ eaten by costs'}")

    print(f"\n  VERDICT:")
    on_sh, tot_sh = _sh(ON), _sh(TOT)
    if on_sh > tot_sh + 0.3:
        print(f"    ✓ Anomaly PRESENT: overnight Sharpe {on_sh} vs total {tot_sh} — return is")
        print(f"      structurally overnight. BUT tradeability depends entirely on getting")
        print(f"      sub-2bps execution (MOC/MOO) — realistic retail cost likely kills it.")
    else:
        print(f"    ✗ Anomaly weak/absent this window: overnight Sharpe {on_sh} vs total {tot_sh}.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    envp = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
