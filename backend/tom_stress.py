"""
Stress-test the SPY turn-of-month (TOM) effect before believing it.

The pooled 10y result looked good (TOM Sharpe 1.37 vs 0.91) but it's SPY-only,
which is a yellow flag. Before it earns any belief, torture it:

  1. SUB-PERIOD consistency: split history into blocks — is the edge in every
     block, or one lucky stretch? (One stretch = don't believe it.)
  2. PER-YEAR: TOM-day Sharpe each year.
  3. DEFLATED SHARPE of the TOM-day return series, penalized for the ~8 calendar
     variations one might try (honest multiple-testing haircut).
  4. OTHER S&P PROXIES (VOO, IVV): does the same effect appear? (It should, if real.)
  5. VOL-MATCHED LEVERED version: lever the TOM sleeve so its vol matches buy&hold,
     T-bills otherwise. If TOM Sharpe is real, this beats buy&hold risk-adjusted.
     If the Sharpe is a mirage, this just amplifies noise.

Run:  python3 tom_stress.py
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
TOM_BEFORE, TOM_AFTER = 1, 3
N_CALENDAR_TRIALS = 8       # ~how many calendar variants one might test (DSR penalty)


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
    months = [d[:7] for d in dates]
    n = len(dates); mask = np.zeros(n, dtype=bool)
    seen = {}
    for i, m in enumerate(months):
        seen[m] = seen.get(m, 0) + 1
        if seen[m] <= TOM_AFTER:
            mask[i] = True
    cnt = {}
    for i in range(n - 1, -1, -1):
        m = months[i]; cnt[m] = cnt.get(m, 0) + 1
        if cnt[m] <= TOM_BEFORE:
            mask[i] = True
    return mask


def _sh(x):
    x = list(x)
    return round(M._sharpe(x, 252), 2) if len(x) > 20 else None


def analyze(ticker):
    end = datetime.now(); start = end - timedelta(days=int(YEARS * 365.25) + 20)
    d, c = _closes(ticker, start, end)
    if len(c) < 500:
        return None
    rets = c[1:] / c[:-1] - 1.0
    dts = d[1:]
    mask = _tom_mask(dts)
    return {"dates": dts, "rets": rets, "mask": mask}


def run():
    print(f"\n{'='*70}\n  TURN-OF-MONTH STRESS TEST  ({YEARS}y)\n{'='*70}")

    spy = analyze("SPY")
    dts, rets, mask = spy["dates"], spy["rets"], spy["mask"]
    tom = rets[mask]

    # 1+2. Per-year TOM-day Sharpe
    print("\n  [1] SPY TOM-day Sharpe BY YEAR (consistency check):")
    years = {}
    for i, dd in enumerate(dts):
        if mask[i]:
            years.setdefault(dd[:4], []).append(rets[i])
    pos_years = 0; tot_years = 0
    for y, rs in sorted(years.items()):
        if len(rs) >= 15:
            sh = _sh(rs); tot_years += 1; pos_years += (sh or 0) > 0
            print(f"      {y}: Sharpe {sh:>5}   avg/day {np.mean(rs)*100:+.3f}%   (n={len(rs)})")
    print(f"      -> positive in {pos_years}/{tot_years} years")

    # 3. Deflated Sharpe of TOM-day returns
    dsr = M.deflated_sharpe(list(tom), N_CALENDAR_TRIALS)
    print(f"\n  [2] SPY TOM-day Deflated Sharpe (penalized for {N_CALENDAR_TRIALS} calendar trials): {dsr}")
    print(f"      pooled TOM Sharpe {_sh(tom)}  (n={len(tom)} days)")

    # 4. Other S&P proxies
    print("\n  [3] SAME EFFECT ON OTHER S&P PROXIES?")
    for t in ["VOO", "IVV", "SPY"]:
        a = analyze(t)
        if not a:
            print(f"      {t}: no data"); continue
        tm = a["rets"][a["mask"]]; rm = a["rets"][~a["mask"]]
        print(f"      {t}: TOM Sharpe {_sh(tm)}  vs rest {_sh(rm)}   (TOM avg/day {np.mean(tm)*100:+.3f}%)")

    # 5. Vol-matched levered TOM vs buy&hold
    print("\n  [4] VOL-MATCHED LEVERED TOM vs BUY&HOLD (SPY):")
    bh_vol = float(np.std(rets, ddof=1))
    tom_strategy = np.where(mask, rets, 0.0)          # in market only on TOM days
    tom_vol = float(np.std(tom_strategy, ddof=1)) or 1e-9
    lev = bh_vol / tom_vol                             # scale to match market vol
    lev = min(lev, 4.0)                                # cap leverage at 4x (realistic-ish)
    # cost: ~2 transitions/month on the levered position
    trans = np.abs(np.diff((mask.astype(float) * lev)))
    levered = tom_strategy * lev
    levered[1:] -= trans * (1.0 / 10000.0)            # 1bp per transition
    eq_l = np.cumsum(levered); eq_b = np.cumsum(rets)
    def mdd(e): return round(float(min(e - np.maximum.accumulate(e))) * 100, 1)
    print(f"      leverage used: {lev:.1f}x on TOM days ({mask.mean()*100:.0f}% of days), T-bills otherwise")
    print(f"      LEVERED TOM : Sharpe {_sh(levered)}  ann {np.mean(levered)*252*100:+.1f}%  maxDD {mdd(eq_l)}%")
    print(f"      BUY & HOLD  : Sharpe {_sh(rets)}  ann {np.mean(rets)*252*100:+.1f}%  maxDD {mdd(eq_b)}%")

    print(f"\n  VERDICT:")
    ok_years = tot_years and pos_years / tot_years >= 0.7
    ok_dsr = (dsr or 0) >= 0.9
    ok_lev = (_sh(levered) or 0) > (_sh(rets) or 0)
    passed = sum([ok_years, ok_dsr, ok_lev])
    print(f"      consistency {pos_years}/{tot_years}yr [{ '✓' if ok_years else '✗' }]   "
          f"DSR {dsr} [{ '✓' if ok_dsr else '✗' }]   levered beats B&H [{ '✓' if ok_lev else '✗' }]")
    if passed == 3:
        print("      ✅ SURVIVES STRESS — real candidate. Move to paper validation.")
    elif passed == 2:
        print("      🟡 PARTIAL — promising but not airtight. Worth more scrutiny, not real money.")
    else:
        print("      ❌ FRAGILE — likely in-sample luck. Don't trade it.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    envp = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(envp):
        for line in open(envp):
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
