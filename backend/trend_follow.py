"""
Trend-following on a diversified ETF basket (time-series momentum / managed futures).

Why this is the strongest remaining candidate:
  - It's the ONE systematic style that genuinely runs tens of billions (CTAs),
    documented over a century of data (AQR, "A Century of Evidence on Trend").
  - LOW survivorship: broad ETFs don't delist like single stocks.
  - It's a DIFFERENT bet than everything we tried — not "predict which stock,"
    but "ride persistent trends across uncorrelated assets," which is real
    diversification (equities, bonds, gold, commodities move differently).
  - It's *crisis alpha*: TSMOM tends to make money when stocks crash (it flips
    short), so it can beat buy-and-hold on a RISK-ADJUSTED basis even if not on
    raw return.

Rule (canonical TSMOM, Moskowitz-Ooi-Pedersen):
  signal_i = sign(12-month return)          → long uptrends, short downtrends
  weight_i = (target_vol / realized_vol_i)  → equal-risk across assets
  monthly rebalance, net of turnover costs.

Compared honestly to SPY buy-and-hold and a 60/40, over a window that INCLUDES
the 2022 bear so crisis behavior is actually tested.

Run:  python3 trend_follow.py
"""

import os
import time
import pickle
from datetime import datetime, timedelta

import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".trend_cache")
os.makedirs(CACHE, exist_ok=True)

REBAL = 21                      # monthly
LOOKBACK = 252                 # 12-month signal
VOL_WIN = 60                   # realized-vol window for risk weighting
TARGET_VOL = 0.10 / np.sqrt(252)   # ~10% annualized per-asset target (daily)
COST_BPS = 10.0                # per side per rebalance change
YEARS = 5                      # include the 2022 bear

ETFS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM",     # equities (US, intl, EM)
    "TLT", "IEF", "LQD", "HYG", "TIP",     # bonds (govt, credit, hy, tips)
    "GLD", "SLV", "DBC", "USO",            # commodities
    "VNQ", "UUP",                          # real estate, US dollar
]


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
        data = ([i.strftime("%Y-%m-%d") for i in df.index], df["close"].to_numpy(dtype=float))
    except Exception:
        data = ([], np.array([]))
    with open(fn, "wb") as f:
        pickle.dump(data, f)
    time.sleep(0.1)
    return data


def build():
    end = datetime.now()
    start = end - timedelta(days=int(YEARS * 365.25) + 40)
    series = {}
    print(f"  Fetching {len(ETFS)} ETFs ({YEARS}y)…")
    for t in ETFS:
        d, c = _closes(t, start, end)
        if len(c) > LOOKBACK + VOL_WIN:
            series[t] = dict(zip(d, c))
    dates = sorted(set().union(*[set(s.keys()) for s in series.values()]))
    tks = list(series.keys())
    mat = np.full((len(dates), len(tks)), np.nan)
    di = {d: i for i, d in enumerate(dates)}
    for j, t in enumerate(tks):
        for d, c in series[t].items():
            mat[di[d], j] = c
    # forward-fill small gaps
    for j in range(mat.shape[1]):
        col = mat[:, j]
        last = np.nan
        for i in range(len(col)):
            if np.isnan(col[i]):
                col[i] = last
            else:
                last = col[i]
    return dates, tks, mat


def _daily_rets(mat):
    r = np.full_like(mat, np.nan)
    r[1:] = (mat[1:] - mat[:-1]) / mat[:-1]
    return r


def backtest(dates, tks, mat):
    rets = _daily_rets(mat)
    n = len(dates)
    port = []              # (date, portfolio daily return)
    weights = np.zeros(len(tks))
    signal = np.zeros(len(tks))
    prev_pos = np.zeros(len(tks))
    t = LOOKBACK + 1
    while t < n - 1:
        # rebalance every REBAL days
        if (t - (LOOKBACK + 1)) % REBAL == 0:
            valid = ~np.isnan(mat[t]) & ~np.isnan(mat[t - LOOKBACK])
            signal = np.where(valid, np.sign(mat[t] / mat[t - LOOKBACK] - 1), 0)
            vol = np.nanstd(rets[t - VOL_WIN:t], axis=0)
            inv = np.where((vol > 0) & valid, 1.0 / vol, 0.0)   # inverse-vol risk weights
            weights = inv / inv.sum() if inv.sum() > 0 else inv  # normalize → gross ≤ 1 (100%)
            pos = signal * weights
            turnover = np.nansum(np.abs(pos - prev_pos))
            cost = turnover * (COST_BPS / 10000.0)
            prev_pos = pos
        else:
            cost = 0.0
        pos = signal * weights
        day_ret = np.nansum(pos * rets[t + 1]) - cost
        port.append((dates[t + 1], day_ret))
        t += 1
    return port


def _stats(port, label, n_trials=1):
    rets = [r for _, r in port]
    if len(rets) < 60:
        return {"label": label, "n": len(rets)}
    ppy = 252
    eq = np.cumsum(rets)
    dd = float(min(eq - np.maximum.accumulate(eq)))
    return {
        "label": label, "n": len(rets),
        "ann_return_pct": round(float(np.mean(rets)) * ppy * 100, 2),
        "ann_vol_pct": round(float(np.std(rets, ddof=1)) * np.sqrt(ppy) * 100, 2),
        "sharpe": round(M._sharpe(rets, ppy), 2),
        "sortino": round(M._sortino(rets, ppy), 2),
        "deflated_sharpe": M.deflated_sharpe(rets, n_trials),
        "max_drawdown_pct": round(dd * 100, 2),
    }


def _bench(dates, tks, mat, weights_map):
    """Static buy-and-hold benchmark from a {ticker: weight} map."""
    rets = _daily_rets(mat)
    idx = {t: j for j, t in enumerate(tks)}
    series = []
    for i in range(LOOKBACK + 2, len(dates)):
        r = sum(w * rets[i, idx[t]] for t, w in weights_map.items() if t in idx and not np.isnan(rets[i, idx[t]]))
        series.append((dates[i], r))
    return series


def run():
    print(f"\n{'='*70}\n  TREND-FOLLOWING — diversified ETF time-series momentum\n"
          f"  {len(ETFS)} ETFs  {YEARS}y  monthly  12m signal  ~10% target vol/asset\n{'='*70}")
    dates, tks, mat = build()
    print(f"  panel: {len(dates)} days × {len(tks)} ETFs\n")

    port = backtest(dates, tks, mat)
    s = _stats(port, "TREND", n_trials=1)
    spy = _stats(_bench(dates, tks, mat, {"SPY": 1.0}), "SPY buy&hold")
    p6040 = _stats(_bench(dates, tks, mat, {"SPY": 0.6, "IEF": 0.4}), "60/40")

    print(f"  {'strategy':16} {'annRet%':>8} {'vol%':>6} {'Sharpe':>7} {'Sortino':>8} {'maxDD%':>8} {'DSR':>5}")
    for x in (s, spy, p6040):
        if x.get("n", 0) >= 60:
            print(f"  {x['label']:16} {x['ann_return_pct']:>8} {x['ann_vol_pct']:>6} {x['sharpe']:>7} "
                  f"{x['sortino']:>8} {x['max_drawdown_pct']:>8} {str(x.get('deflated_sharpe','')):>5}")

    # per-year Sharpe of the trend strategy
    years = {}
    for d, r in port:
        years.setdefault(d[:4], []).append(r)
    print("\n  TREND by year (Sharpe / annRet%):")
    for y, rs in sorted(years.items()):
        if len(rs) >= 60:
            print(f"     {y}: {round(M._sharpe(rs, 252),2)}Sh  {round(float(np.mean(rs))*252*100,1)}%")

    print(f"\n  VERDICT:")
    sh = s.get("sharpe", 0)
    if sh >= 1.0 and (s.get("sharpe", 0) > spy.get("sharpe", 0)):
        print(f"    ✅ RISK-ADJUSTED EDGE: Sharpe {sh} (vs SPY {spy.get('sharpe')}), maxDD "
              f"{s.get('max_drawdown_pct')}% (vs SPY {spy.get('max_drawdown_pct')}%). Worth paper validation.")
    elif sh >= 0.6:
        print(f"    🟡 DECENT but not a slam-dunk: Sharpe {sh}. Diversifier, not a money-printer.")
    else:
        print(f"    ❌ Weak: Sharpe {sh}. Trend didn't pay in this window.")
    print(f"  ⚠ 5y is short for trend-following (it shines over full cycles). Directional only.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    envp = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
