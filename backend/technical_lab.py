"""
Technical-analysis strategy lab (Exp 7) — testing the Pine-script canon honestly.

The most popular retail technical strategies, implemented and tested head-to-head
as long/flat timing rules on SPY over ~30 years (Tiingo total-return), net of
cost, vs simply buying and holding. Each strategy is "in the market when the
signal says go, in cash otherwise" — so we isolate whether the signal ADDS value
over just holding.

Strategies:
  - SMA 50/200 (golden cross)      - EMA 9/21 crossover
  - RSI(14) mean reversion         - MACD crossover
  - Bollinger mean reversion       - Donchian 20 breakout (Turtle)
  - Supertrend(10,3)

The academic consensus: most of these don't beat buy&hold net of cost, and the
edge that exists decayed after publication (crowding). We test rather than assert.

Run:  python3 technical_lab.py
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
COST_BPS = 2.0     # per side; SPY is very liquid


def _tiingo_ohlc(sym):
    fn = os.path.join(CACHE, f"{sym}_ohlc.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1995-01-01&token={key}&format=json&resampleFreq=daily"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    out = {
        "date": [r["date"][:10] for r in d],
        "o": np.array([r["adjOpen"] for r in d], float),
        "h": np.array([r["adjHigh"] for r in d], float),
        "l": np.array([r["adjLow"] for r in d], float),
        "c": np.array([r["adjClose"] for r in d], float),
    }
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.3)
    return out


# ─── indicators ───────────────────────────────────────────────────────────────
def sma(x, n):
    out = np.full_like(x, np.nan)
    cs = np.cumsum(np.insert(x, 0, 0))
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out

def ema(x, n):
    a = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out

def rsi(c, n=14):
    d = np.diff(c); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    ru = np.full(len(c), np.nan); rd = np.full(len(c), np.nan)
    ru[n] = up[:n].mean(); rd[n] = dn[:n].mean()
    for i in range(n + 1, len(c)):
        ru[i] = (ru[i - 1] * (n - 1) + up[i - 1]) / n
        rd[i] = (rd[i - 1] * (n - 1) + dn[i - 1]) / n
    rs = ru / np.where(rd == 0, 1e-9, rd)
    return 100 - 100 / (1 + rs)

def macd(c):
    m = ema(c, 12) - ema(c, 26)
    return m, ema(m, 9)

def atr(h, l, c, n=10):
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    tr = np.insert(tr, 0, h[0] - l[0])
    out = np.full(len(c), np.nan); out[n] = tr[:n].mean()
    for i in range(n + 1, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


# ─── strategies → return a position array (1 long / 0 flat), evaluated at close t ─
def st_sma(d):
    c = d["c"]; return (sma(c, 50) > sma(c, 200)).astype(float)

def st_ema(d):
    c = d["c"]; return (ema(c, 9) > ema(c, 21)).astype(float)

def st_macd(d):
    m, s = macd(d["c"]); return (m > s).astype(float)

def st_rsi(d):
    c = d["c"]; r = rsi(c, 14); pos = np.zeros(len(c)); inpos = 0
    for i in range(len(c)):
        if np.isnan(r[i]):
            continue
        if inpos == 0 and r[i] < 30:
            inpos = 1
        elif inpos == 1 and r[i] > 50:
            inpos = 0
        pos[i] = inpos
    return pos

def st_bollinger(d):
    c = d["c"]; mid = sma(c, 20); sd = np.array([np.std(c[max(0, i - 19):i + 1]) if i >= 19 else np.nan for i in range(len(c))])
    lower = mid - 2 * sd; pos = np.zeros(len(c)); inpos = 0
    for i in range(len(c)):
        if np.isnan(mid[i]):
            continue
        if inpos == 0 and c[i] < lower[i]:
            inpos = 1
        elif inpos == 1 and c[i] > mid[i]:
            inpos = 0
        pos[i] = inpos
    return pos

def st_donchian(d):
    c = d["c"]; n = 20; pos = np.zeros(len(c)); inpos = 0
    for i in range(n, len(c)):
        hi = c[i - n:i].max(); lo = c[i - n:i].min()
        if inpos == 0 and c[i] > hi:
            inpos = 1
        elif inpos == 1 and c[i] < lo:
            inpos = 0
        pos[i] = inpos
    return pos

def st_supertrend(d, period=10, mult=3.0):
    c, h, l = d["c"], d["h"], d["l"]; a = atr(h, l, c, period)
    hl2 = (h + l) / 2; n = len(c)
    fu = np.full(n, np.nan); fl = np.full(n, np.nan); pos = np.zeros(n); trend = 1
    for i in range(period + 1, n):
        bu = hl2[i] + mult * a[i]; bl = hl2[i] - mult * a[i]
        fu[i] = bu if (np.isnan(fu[i - 1]) or bu < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl if (np.isnan(fl[i - 1]) or bl > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if trend == 1 and c[i] < fl[i]:
            trend = -1
        elif trend == -1 and c[i] > fu[i]:
            trend = 1
        pos[i] = 1.0 if trend == 1 else 0.0
    return pos


STRATS = {
    "SMA 50/200 (golden cross)": st_sma, "EMA 9/21 crossover": st_ema,
    "MACD crossover": st_macd, "RSI(14) mean-reversion": st_rsi,
    "Bollinger mean-reversion": st_bollinger, "Donchian 20 breakout": st_donchian,
    "Supertrend(10,3)": st_supertrend,
}


def _eval(pos, c, warmup=200):
    rets = c[1:] / c[:-1] - 1.0
    pos = pos[:-1]                          # act on next day's return
    strat = pos * rets
    switches = np.abs(np.diff(np.insert(pos, 0, 0)))
    strat = strat - switches * (COST_BPS / 10000.0)
    strat = strat[warmup:]; bh = rets[warmup:]
    eq = np.cumprod(1 + strat)
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    n_trades = int(switches[warmup:].sum())
    time_in = float(pos[warmup:].mean())
    return {
        "sharpe": round(M._sharpe(list(strat), 252), 2),
        "cagr": round((eq[-1] ** (252 / len(strat)) - 1) * 100, 1),
        "mdd": round(mdd * 100, 1),
        "trades": n_trades,
        "time_in_mkt": round(time_in * 100, 0),
    }


def run(symbol="SPY"):
    print(f"\n{'='*76}\n  TECHNICAL STRATEGY LAB — {symbol}, long/flat timing, net of {COST_BPS:.0f}bps/side\n{'='*76}")
    d = _tiingo_ohlc(symbol)
    c = d["c"]
    print(f"  data {d['date'][0]} → {d['date'][-1]}  ({len(c)} days ≈ {len(c)//252}y)\n")
    # buy & hold baseline
    rets = c[1:] / c[:-1] - 1.0
    bh = rets[200:]; eqb = np.cumprod(1 + bh)
    bh_sh = round(M._sharpe(list(bh), 252), 2)
    bh_cagr = round((eqb[-1] ** (252 / len(bh)) - 1) * 100, 1)
    bh_mdd = round(float(np.min(eqb / np.maximum.accumulate(eqb) - 1)) * 100, 1)

    print(f"  {'strategy':28} {'Sharpe':>7} {'CAGR%':>7} {'maxDD%':>7} {'trades':>7} {'%inMkt':>7} {'vs B&H':>7}")
    print(f"  {'BUY & HOLD':28} {bh_sh:>7} {bh_cagr:>7} {bh_mdd:>7} {'—':>7} {'100':>7} {'—':>7}")
    beat = 0
    for name, fn in STRATS.items():
        r = _eval(fn(d), c)
        tag = "✓" if r["sharpe"] > bh_sh else "✗"
        beat += r["sharpe"] > bh_sh
        print(f"  {name:28} {r['sharpe']:>7} {r['cagr']:>7} {r['mdd']:>7} {r['trades']:>7} "
              f"{r['time_in_mkt']:>7} {tag:>7}")

    print(f"\n  {beat}/{len(STRATS)} technical strategies beat buy&hold on Sharpe.")
    print(f"  NOTE: long/flat timing means these mostly REDUCE risk (less time in market),")
    print(f"  so a higher Sharpe from lower drawdown ≠ higher returns. Watch CAGR vs B&H.")
    print(f"{'='*76}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else "SPY")
