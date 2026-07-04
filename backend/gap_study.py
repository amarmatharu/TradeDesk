"""
Gap study (Exp 13) — do opening gaps predict the day, net of cost?

Popular retail day-trade: a stock gaps up/down at the open (on overnight news);
you either "gap and go" (bet it continues) or "fade the gap" (bet it fills back
toward yesterday's close). Research says ~70% of gaps fill but the edge has
decayed and doesn't reliably survive costs. Let's measure it on real data.

Method (daily OHLC — official open/close, NOT pre-market/tick):
  gap_t      = open_t / close_{t-1} - 1          (the overnight gap)
  intraday_t = close_t / open_t - 1              (what happens during the day)
  next_t     = close_{t+1} / close_t - 1         (the following day)
Pool across a universe of stocks, bucket by gap size, and ask:
  - Does the intraday move FADE the gap (mean-revert) or CONTINUE it?
  - What's the intraday "fill" rate (did price touch yesterday's close)?
  - Can a simple fade/continuation rule make money NET of realistic cost?

HONEST CAVEATS: liquid names rarely gap big (understates opportunity) but also
have tiny spreads (understates cost). The real gappers are illiquid small-caps
where costs are brutal — so treat any edge here as an OPTIMISTIC upper bound.

Run:  python3 gap_study.py
"""

import os
import json
import time
import pickle
import urllib.request
import numpy as np

CACHE = os.path.join(os.path.dirname(__file__), ".gap_cache")
os.makedirs(CACHE, exist_ok=True)
COST_BPS = 5.0     # per side (open + close = 2 sides); optimistic for gappy names

UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","NFLX","INTC","MU","QCOM","AVGO","CRM","ADBE",
    "ORCL","CSCO","IBM","PYPL","SHOP","UBER","SNAP","PINS","ROKU","SQ","COIN","PLTR","NET","DDOG","ZS",
    "JPM","BAC","GS","WFC","C","MS","V","MA","AXP","SCHW",
    "UNH","JNJ","PFE","MRK","LLY","ABBV","BMY","GILD","MRNA","CVS",
    "XOM","CVX","OXY","SLB","COP","WMT","TGT","HD","NKE","SBUX","MCD","DIS","BA","CAT","GE","F","GM",
]


def _ohlc(sym):
    fn = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=2010-01-01&token={key}&format=json&resampleFreq=daily"
    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        out = {"o": np.array([r["adjOpen"] for r in d], float),
               "h": np.array([r["adjHigh"] for r in d], float),
               "l": np.array([r["adjLow"] for r in d], float),
               "c": np.array([r["adjClose"] for r in d], float)}
    except Exception:
        out = None
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.25)
    return out


def collect():
    gaps, intr, nxt, fills = [], [], [], []
    got = 0
    for s in UNIVERSE:
        d = _ohlc(s)
        if not d or len(d["c"]) < 400:
            continue
        got += 1
        o, h, l, c = d["o"], d["h"], d["l"], d["c"]
        for t in range(1, len(c) - 1):
            pc = c[t - 1]
            if pc <= 0 or o[t] <= 0:
                continue
            g = o[t] / pc - 1
            if abs(g) < 0.002:      # ignore trivial gaps (<0.2%)
                continue
            gaps.append(g)
            intr.append(c[t] / o[t] - 1)
            nxt.append(c[t + 1] / c[t] - 1)
            filled = (l[t] <= pc) if g > 0 else (h[t] >= pc)   # did it touch prev close intraday?
            fills.append(1 if filled else 0)
    return got, np.array(gaps), np.array(intr), np.array(nxt), np.array(fills)


def run():
    print(f"\n{'='*72}\n  GAP STUDY — do opening gaps predict the day? (net of cost)\n{'='*72}")
    got, g, intra, nxt, fills = collect()
    print(f"  {got} stocks, {len(g):,} gap events (>0.2%) since 2010\n")

    # ── fill rates + intraday behaviour by gap bucket ──
    buckets = [(-9, -0.05, "gap DOWN >5%"), (-0.05, -0.02, "down 2-5%"), (-0.02, -0.002, "down 0.2-2%"),
               (0.002, 0.02, "up 0.2-2%"), (0.02, 0.05, "up 2-5%"), (0.05, 9, "gap UP >5%")]
    print(f"  {'bucket':16} {'n':>7} {'fill%':>7} {'avg intraday':>13} {'avg next-day':>13} {'fade?':>7}")
    for lo, hi, name in buckets:
        m = (g > lo) & (g <= hi)
        if m.sum() < 50:
            continue
        gi, ii, ni, fi = g[m], intra[m], nxt[m], fills[m]
        # "fade" = intraday moves OPPOSITE to the gap
        fade = np.mean(ii * -np.sign(gi.mean() if False else np.sign(gi)))  # avg (intraday in fade direction)
        tag = "fade" if np.mean(ii * -np.sign(gi)) > 0 else "cont"
        print(f"  {name:16} {m.sum():>7,} {fi.mean()*100:>6.0f}% {ii.mean()*100:>12.2f}% {ni.mean()*100:>12.2f}% {tag:>7}")

    # ── correlation: does gap predict intraday? ──
    corr = float(np.corrcoef(g, intra)[0, 1])
    print(f"\n  correlation(gap, intraday move): {corr:+.3f}  "
          f"({'negative = fade tendency' if corr < 0 else 'positive = continuation'})")

    # ── tradeable rules, net of cost (enter open, exit close) ──
    cost = 2 * COST_BPS / 10000       # round trip (open + close)
    print(f"\n  TRADEABLE RULES (enter at open, exit at close; cost {COST_BPS:.0f}bps/side):")
    for thr in [0.02, 0.05]:
        big = np.abs(g) >= thr
        # FADE: position opposite the gap
        fade_ret = (-np.sign(g[big]) * intra[big]) - cost
        # CONTINUATION: position with the gap
        cont_ret = (np.sign(g[big]) * intra[big]) - cost
        n = big.sum()
        def desc(r):
            wr = (r > 0).mean() * 100
            return f"exp {r.mean()*10000:+.1f}bps/trade  win {wr:.0f}%  net {r.sum()*100:+.0f}%"
        print(f"    |gap|>={int(thr*100)}%  (n={n:,}):")
        print(f"       FADE the gap        : {desc(fade_ret)}")
        print(f"       GO with the gap     : {desc(cont_ret)}")

    print(f"\n  READ: 'fill%' high looks great, but the tradeable expectancy (bps/trade)")
    print(f"  net of cost is what matters. On LIQUID names costs are ~5bps; real gappers")
    print(f"  (small-caps) cost 50-200bps — so a small positive here likely goes negative there.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
