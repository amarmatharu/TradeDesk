"""
Factor Lab — market-neutral cross-sectional factor backtester.

Why this is different from the insider tests: those were long-only, so a bull
market flattered them (we saw it — absolute gains, ~0 vs SPY). Here we build
DOLLAR-NEUTRAL long/short portfolios: each rebalance, rank the universe by a
factor, go long the top quintile and short the bottom quintile in equal size.
The return is the long−short *spread* — market beta cancels out, so "did it beat
SPY" is the wrong question; the question is "does the factor itself carry alpha,
net of costs?" This is how pod shops actually run money (factor-neutral).

Factors tested (all classic, documented, retail-accessible):
  - momentum      : 12-1 month return (long winners / short losers)
  - reversal      : short-term (5-day) reversal (long losers / short winners)
  - low_vol       : inverse 20-day volatility (long calm / short wild)

HONEST CAVEATS baked into the output:
  - Survivorship: the universe is *currently* liquid names, so delisted losers
    are missing → results are optimistic, especially for momentum. Flagged.
  - Costs: charged on turnover each rebalance (reversal turns over ~100%/week,
    which is where that anomaly usually dies).
  - Deflated Sharpe penalizes for testing multiple factors.

Run:  python3 factor_lab.py
"""

import os
import json
import time
import pickle
from datetime import datetime, timedelta

import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".factor_cache")
os.makedirs(CACHE, exist_ok=True)

REBALANCE_DAYS = 5            # weekly
QUINTILE = 0.2               # top/bottom 20%
COST_BPS = 10.0             # per side, per name traded (round-trip handled via turnover)
YEARS = 4

# A diversified, liquid universe. NOTE: current-membership → survivorship bias.
UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","AMD","INTC","QCOM","TXN","MU","ADI","AMAT",
    "CRM","ORCL","ADBE","NOW","INTU","IBM","CSCO","ACN","UBER","SHOP","PANW","SNOW","PLTR","NET","DDOG",
    "JPM","BAC","WFC","GS","MS","C","SCHW","AXP","BLK","SPGI","V","MA","PYPL","COF","USB",
    "UNH","JNJ","LLY","PFE","MRK","ABBV","TMO","ABT","DHR","BMY","AMGN","GILD","CVS","MDT","ISRG",
    "XOM","CVX","COP","SLB","EOG","MPC","PSX","OXY","VLO","WMB",
    "WMT","COST","HD","LOW","TGT","NKE","SBUX","MCD","CMG","BKNG","DIS","PG","KO","PEP","PM",
    "CAT","DE","BA","HON","GE","LMT","RTX","UPS","UNP","MMM","EMR","ETN",
    "LIN","APD","SHW","FCX","NEM","NUE",
    "T","VZ","TMUS","CMCSA","NFLX",
    "SPY","QQQ","IWM",   # benchmarks / for reference (excluded from ranks)
]
BENCH = {"SPY","QQQ","IWM"}


def _fetch_closes(ticker, start, end):
    """Disk-cached daily closes as (dates, np.array of closes)."""
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
        if df.empty:
            data = ([], np.array([]))
        else:
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(ticker, level=0)
            dates = [i.strftime("%Y-%m-%d") for i in df.index]
            closes = df["close"].to_numpy(dtype=float)
            data = (dates, closes)
    except Exception:
        data = ([], np.array([]))
    with open(fn, "wb") as f:
        pickle.dump(data, f)
    time.sleep(0.1)
    return data


def build_panel():
    """Aligned close-price panel: {date_index: {ticker: close}} → returns matrix."""
    end = datetime.now()
    start = end - timedelta(days=int(YEARS * 365.25) + 40)
    series = {}
    print(f"  Fetching {len(UNIVERSE)} names ({YEARS}y)…")
    for i, t in enumerate(UNIVERSE):
        d, c = _fetch_closes(t, start, end)
        if len(c) > 252:
            series[t] = dict(zip(d, c))
        if (i + 1) % 25 == 0:
            print(f"    …{i+1}/{len(UNIVERSE)}")
    # common date axis = union sorted; forward-align by intersection of available
    all_dates = sorted(set().union(*[set(s.keys()) for s in series.values()]))
    tickers = [t for t in series if t not in BENCH]
    # matrix: rows=dates, cols=tickers, NaN where missing
    mat = np.full((len(all_dates), len(tickers)), np.nan)
    didx = {d: i for i, d in enumerate(all_dates)}
    for j, t in enumerate(tickers):
        for d, c in series[t].items():
            mat[didx[d], j] = c
    return all_dates, tickers, mat, series


# ─── Factors: return a cross-sectional score per ticker at row t (higher=more long) ──
def f_momentum(mat, t):
    if t < 252:
        return None
    past = mat[t - 252]; recent = mat[t - 21]
    with np.errstate(invalid="ignore", divide="ignore"):
        return (recent - past) / past

def f_reversal(mat, t):
    if t < 6:
        return None
    with np.errstate(invalid="ignore", divide="ignore"):
        return -(mat[t] - mat[t - 5]) / mat[t - 5]   # long recent losers

def f_lowvol(mat, t):
    if t < 21:
        return None
    window = mat[t - 20:t + 1]
    rets = np.diff(window, axis=0) / window[:-1]
    vol = np.nanstd(rets, axis=0)
    return -vol   # long low-vol

FACTORS = {"momentum": f_momentum, "reversal": f_reversal, "low_vol": f_lowvol}


def backtest_factor(dates, tickers, mat, score_fn):
    """Weekly dollar-neutral long/short quintile spread, net of turnover costs."""
    n = len(dates)
    period_rets = []
    prev_long, prev_short = set(), set()
    t = 260
    while t + REBALANCE_DAYS < n:
        scores = score_fn(mat, t)
        if scores is None:
            t += REBALANCE_DAYS; continue
        valid = ~np.isnan(scores) & ~np.isnan(mat[t]) & ~np.isnan(mat[t + REBALANCE_DAYS])
        idx = np.where(valid)[0]
        if len(idx) < 20:
            t += REBALANCE_DAYS; continue
        order = idx[np.argsort(scores[idx])]
        k = max(1, int(len(order) * QUINTILE))
        short_i, long_i = order[:k], order[-k:]
        fwd = (mat[t + REBALANCE_DAYS] - mat[t]) / mat[t]
        long_ret = np.nanmean(fwd[long_i]); short_ret = np.nanmean(fwd[short_i])
        gross = long_ret - short_ret
        # turnover cost: names changed since last rebalance × 2 sides
        long_set, short_set = set(long_i.tolist()), set(short_i.tolist())
        turnover = (len(long_set ^ prev_long) + len(short_set ^ prev_short)) / (2 * k)
        cost = turnover * (COST_BPS / 10000.0) * 2
        period_rets.append((dates[t], gross - cost))
        prev_long, prev_short = long_set, short_set
        t += REBALANCE_DAYS
    return period_rets


def _stats(period_rets, n_trials):
    rets = [r for _, r in period_rets]
    if len(rets) < 10:
        return {"n": len(rets)}
    ppy = 52
    eq = np.cumsum(rets)
    return {
        "n": len(rets),
        "ann_return_pct": round(float(np.mean(rets)) * ppy * 100, 2),
        "ann_vol_pct": round(float(np.std(rets, ddof=1)) * np.sqrt(ppy) * 100, 2),
        "sharpe": round(M._sharpe(rets, ppy), 2),
        "deflated_sharpe": M.deflated_sharpe(rets, n_trials),
        "max_drawdown_pct": round(float(min(eq - np.maximum.accumulate(eq))) * 100, 2),
        "hit_rate_pct": round(len([r for r in rets if r > 0]) / len(rets) * 100, 1),
    }


def _by_year(period_rets, n_trials):
    years = {}
    for d, r in period_rets:
        years.setdefault(d[:4], []).append((d, r))
    return {y: _stats(v, n_trials) for y, v in sorted(years.items())}


def run():
    print(f"\n{'='*70}\n  FACTOR LAB — market-neutral long/short quintile spread\n"
          f"  universe={len([t for t in UNIVERSE if t not in BENCH])}  weekly  cost={COST_BPS:.0f}bps/side\n{'='*70}")
    dates, tickers, mat, _ = build_panel()
    print(f"  panel: {len(dates)} days × {len(tickers)} names\n")
    n_trials = len(FACTORS)
    for name, fn in FACTORS.items():
        pr = backtest_factor(dates, tickers, mat, fn)
        s = _stats(pr, n_trials)
        print(f"  ── {name.upper()} ──")
        if s.get("n", 0) < 10:
            print("     insufficient data"); continue
        print(f"     ann_return={s['ann_return_pct']}%  vol={s['ann_vol_pct']}%  Sharpe={s['sharpe']}  "
              f"DSR={s['deflated_sharpe']}  maxDD={s['max_drawdown_pct']}%  hit={s['hit_rate_pct']}%  (n={s['n']}wk)")
        yr = _by_year(pr, n_trials)
        print("     by year: " + "  ".join(
            f"{y}:{v.get('sharpe','—')}Sh/{v.get('ann_return_pct','—')}%" for y, v in yr.items() if v.get('n',0) >= 10))
        # verdict
        dsr = s['deflated_sharpe'] or 0
        if s['sharpe'] >= 1.0 and dsr >= 0.9:
            print(f"     ✅ promising — Sharpe {s['sharpe']}, DSR {dsr}. Worth paper validation.")
        elif s['sharpe'] >= 0.5:
            print(f"     🟡 weak-positive — real but thin; costs/survivorship likely eat it.")
        else:
            print(f"     ❌ no edge net of cost.")
        print()
    print(f"  ⚠ CAVEAT: universe is current liquid names (survivorship bias) → these are")
    print(f"     OPTIMISTIC, especially momentum. A real edge must survive that haircut.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    # load env
    envp = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
