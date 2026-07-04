"""
Gap-down overnight reversal (Exp 13b) — torturing the one gap flicker.

The only real signal in the gap study: stocks that gap DOWN hard bounce the next
day (overreaction to bad news). Trade: when a stock gaps down > threshold at the
open, BUY at that day's CLOSE and hold to the next close ("buy the panic, hold a
day"). Now stress it honestly:

  1. FAT-TAIL check  — is the +avg driven by a few lottery winners? (median, win%,
     how much of the profit comes from the top 5% of trades)
  2. TIME clustering — big gap-downs cluster in crashes (Mar-2020). Is the edge
     real, or just a few crisis days? -> by-year expectancy.
  3. COST sensitivity — expectancy at 5 / 20 / 50 / 100 bps round-trip. These are
     panicky names; real costs are high. At what cost does it die?
  4. THRESHOLD + HOLD robustness.

Run:  python3 gap_reversal.py
"""

import os
import numpy as np
import gap_study as GS


def collect_trades(threshold, hold):
    """Return list of (year, ret) for buy-at-close-of-gap-down, hold `hold` days."""
    trades = []
    for s in GS.UNIVERSE:
        d = GS._ohlc(s)
        if not d or len(d["c"]) < 400:
            continue
        c, o = d["c"], d["o"]
        # need dates for by-year — refetch not stored; approximate year by index position
        n = len(c)
        for t in range(1, n - hold - 1):
            if c[t - 1] <= 0:
                continue
            gap = o[t] / c[t - 1] - 1
            if gap <= -threshold:
                ret = c[t + hold] / c[t] - 1     # buy close[t], sell close[t+hold]
                trades.append(ret)
    return np.array(trades)


def _year_index_map():
    """Map each stock's bar index to a calendar year via a fresh light fetch of one
    date axis is overkill; instead approximate: we re-fetch dates for by-year."""
    return None


def collect_by_year(threshold, hold):
    """Same but keyed by actual year (needs dates -> refetch raw once per name)."""
    import json, urllib.request, pickle
    by_year = {}
    key = os.environ["TIINGO_KEY"]
    for s in GS.UNIVERSE:
        fn = os.path.join(GS.CACHE, f"{s}_dates.pkl")
        if os.path.exists(fn):
            with open(fn, "rb") as f:
                dates = pickle.load(f)
        else:
            try:
                url = f"https://api.tiingo.com/tiingo/daily/{s}/prices?startDate=2010-01-01&token={key}&format=json&resampleFreq=daily&columns=date"
                req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
                dd = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
                dates = [r["date"][:4] for r in dd]
            except Exception:
                dates = None
            with open(fn, "wb") as f:
                pickle.dump(dates, f)
        d = GS._ohlc(s)
        if not d or not dates or len(dates) != len(d["c"]):
            continue
        c, o = d["c"], d["o"]
        for t in range(1, len(c) - hold - 1):
            if c[t - 1] <= 0:
                continue
            if o[t] / c[t - 1] - 1 <= -threshold:
                by_year.setdefault(dates[t], []).append(c[t + hold] / c[t] - 1)
    return by_year


def stats(r, cost_bps):
    net = r - 2 * cost_bps / 10000
    return {"n": len(r), "mean_bps": round(net.mean() * 10000, 1),
            "median_bps": round(np.median(net) * 10000, 1),
            "win": round((net > 0).mean() * 100, 1)}


def run():
    print(f"\n{'='*70}\n  GAP-DOWN OVERNIGHT REVERSAL — torture test\n{'='*70}")

    r = collect_trades(0.05, 1)
    print(f"  base: gap-down >5%, buy close, hold 1 day — {len(r):,} trades\n")

    print(f"  [1] FAT-TAIL CHECK (gross):")
    print(f"      mean {r.mean()*10000:+.1f}bps   median {np.median(r)*10000:+.1f}bps   "
          f"win {np.mean(r>0)*100:.0f}%")
    top5 = np.sort(r)[-max(1, len(r)//20):]
    print(f"      top 5% of trades contribute {top5.sum()/r.sum()*100:.0f}% of all profit "
          f"(>60% = lottery, not edge)")

    print(f"\n  [2] COST SENSITIVITY (net expectancy per trade):")
    for cb in [5, 20, 50, 100]:
        s = stats(r, cb)
        alive = "✓" if s["mean_bps"] > 0 else "✗"
        print(f"      {cb:>3}bps/side: mean {s['mean_bps']:+.1f}bps  median {s['median_bps']:+.1f}bps  win {s['win']}%  {alive}")

    print(f"\n  [3] BY-YEAR (is it just crash years? gross mean bps/trade):")
    by_year = collect_by_year(0.05, 1)
    yrs = sorted(by_year)
    pos = 0
    for y in yrs:
        v = np.array(by_year[y])
        if len(v) >= 20:
            m = v.mean() * 10000
            pos += m > 0
            print(f"      {y}: {len(v):>5} trades  mean {m:+7.1f}bps")
    ny = len([y for y in yrs if len(by_year[y]) >= 20])
    print(f"      -> positive in {pos}/{ny} years")

    print(f"\n  [4] THRESHOLD x HOLD (gross mean bps/trade):")
    print(f"      {'threshold':>10} {'hold=1d':>9} {'hold=2d':>9} {'hold=5d':>9}")
    for thr in [0.03, 0.05, 0.07, 0.10]:
        row = [collect_trades(thr, h) for h in (1, 2, 5)]
        print(f"      {int(thr*100):>9}% " + " ".join(f"{x.mean()*10000:>8.1f}" for x in row))

    print(f"\n  VERDICT: real only if median is positive (not just mean), the top-5%")
    print(f"  contribution is modest, it's positive in MOST years (not just 2020), AND")
    print(f"  it survives ~50bps cost (realistic for panicky names).")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
