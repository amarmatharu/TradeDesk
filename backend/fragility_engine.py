"""
THE FRAGILITY THERMOSTAT (an original design — Exp 11).

Not copied from anyone. Designed from first principles on what this whole project
PROVED: you cannot forecast direction, but you can measure systemic fragility.

Philosophy: like an aircraft or a reactor, don't trust one gauge. Fuse several
INDEPENDENT stress sensors into a single "how safe is it to be exposed?" score,
and set equity exposure from that — 0 (all bonds) to 1.3x (levered) — rebalanced
weekly. The system NEVER bets on up/down; it only bets on calm vs stress.

Six orthogonal fragility sensors (each mapped to 0=safe .. 1=fragile):
  1. vol_level     — 20d realized vol, percentile vs its own 2y history
  2. vol_accel     — short vol / long vol (turbulence rising fast = early warning)
  3. trend_break   — price below its 200d trend (and how far)
  4. hedge_fail    — 60d stock/bond correlation turning POSITIVE (diversification dying)
  5. drawdown      — current drop from the 1y high
  6. flight_safety — bonds+gold outrunning stocks over 20d (smart money de-risking)

Fragility F = mean(sensors). Equity exposure = clip(1.3*(1-F), 0, 1.3); the rest
parks in bonds. Thresholds are round, a-priori numbers (no optimization) so this
is an honest test of the DESIGN, not a curve-fit.

Run:  python3 fragility_engine.py
"""

import os
import json
import time
import pickle
import urllib.request
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".tiingo_cache")
REBAL = 5           # weekly
MAX_EXP = 1.3
BORROW = 0.04 / 252
COST_BPS = 2.0
BEARS = [("2008", "2007-10-09", "2009-03-09"), ("2020", "2020-02-19", "2020-03-23"),
         ("2022", "2022-01-03", "2022-10-12")]


def _tiingo(sym):
    fn = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1995-01-01&token={key}&format=json&resampleFreq=daily"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    out = ([r["date"][:10] for r in d], np.array([r["adjClose"] for r in d], float))
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.3)
    return out


def _clip01(x):
    return float(min(1.0, max(0.0, x)))


def build():
    ser = {s: dict(zip(*_tiingo(s))) for s in ["SPY", "TLT", "GLD", "AGG"]}
    dates = sorted(set.intersection(*[set(v.keys()) for v in ser.values()]))
    return dates, {s: np.array([ser[s][d] for d in dates]) for s in ser}


def fragility_series(dates, mat):
    spy, tlt, gld = mat["SPY"], mat["TLT"], mat["GLD"]
    rs = np.concatenate([[0], np.diff(spy) / spy[:-1]])
    rt = np.concatenate([[0], np.diff(tlt) / tlt[:-1]])
    n = len(dates)
    F = np.full(n, np.nan)
    sensors = np.zeros((n, 6))
    for t in range(260, n):
        v20 = np.std(rs[t - 20:t]); v60 = np.std(rs[t - 60:t])
        hist = np.array([np.std(rs[i - 20:i]) for i in range(t - 252, t, 5)])
        s1 = _clip01((hist < v20).mean())                              # vol level percentile
        s2 = _clip01((v20 / (v60 + 1e-9) - 0.9) / 0.6)                 # vol acceleration
        ma200 = spy[t - 200:t].mean(); dist = spy[t] / ma200 - 1
        s3 = _clip01(-dist / 0.10)                                     # below-trend
        corr = np.corrcoef(rs[t - 60:t], rt[t - 60:t])[0, 1]
        s4 = _clip01((corr + 0.2) / 0.4)                              # hedge failing (corr → positive)
        dd = spy[t] / spy[t - 252:t].max() - 1
        s5 = _clip01(-dd / 0.15)                                       # drawdown depth
        sh = ((tlt[t] / tlt[t - 20] - 1) + (gld[t] / gld[t - 20] - 1)) / 2 - (spy[t] / spy[t - 20] - 1)
        s6 = _clip01(sh / 0.05)                                        # flight to safety
        sensors[t] = [s1, s2, s3, s4, s5, s6]
        F[t] = np.mean(sensors[t])
    return F, sensors


def backtest(dates, mat, F):
    spy, agg = mat["SPY"], mat["AGG"]
    rs = np.concatenate([[0], np.diff(spy) / spy[:-1]])
    ra = np.concatenate([[0], np.diff(agg) / agg[:-1]])
    n = len(dates); out = np.zeros(n); w_eq = 0.0
    for t in range(261, n - 1):
        if (t - 261) % REBAL == 0 and not np.isnan(F[t]):
            new = _clip01_max(MAX_EXP * (1 - F[t]))
            turnover = abs(new - w_eq)
            out[t + 1] -= turnover * COST_BPS / 10000
            w_eq = new
        bond_w = max(0.0, 1.0 - w_eq)
        lev = max(0.0, w_eq - 1.0)
        out[t + 1] += w_eq * rs[t + 1] + bond_w * ra[t + 1] - lev * BORROW
    return out


def _clip01_max(x):
    return float(min(MAX_EXP, max(0.0, x)))


def _stats(r):
    r = np.asarray(r); r = r[np.argmax(r != 0):]
    eq = np.cumprod(1 + r)
    return {"cagr": round((eq[-1] ** (252 / len(r)) - 1) * 100, 1),
            "vol": round(float(np.std(r, ddof=1)) * np.sqrt(252) * 100, 1),
            "sharpe": round(M._sharpe(list(r), 252), 2),
            "mdd": round(float(np.min(eq / np.maximum.accumulate(eq) - 1)) * 100, 1)}


def _bench(dates, mat, w):
    n = len(dates); out = np.zeros(n)
    for t in range(261, n - 1):
        out[t + 1] = sum(wt * (mat[a][t + 1] / mat[a][t] - 1) for a, wt in w.items())
    return out


def _voltarget(dates, mat):
    spy = mat["SPY"]; rs = np.concatenate([[0], np.diff(spy) / spy[:-1]])
    n = len(dates); out = np.zeros(n); lev = 1.0
    for t in range(261, n - 1):
        if (t - 261) % REBAL == 0:
            v = np.std(rs[t - 40:t]) or 1e-9
            lev = min(0.15 / np.sqrt(252) / v, MAX_EXP)
        out[t + 1] = lev * rs[t + 1] - max(0, lev - 1) * BORROW
    return out


def _bear(dates, r, s, e):
    idx = [i for i, d in enumerate(dates) if s <= d <= e]
    if len(idx) < 2:
        return None
    eq = np.cumprod(1 + r[idx[0]:idx[-1] + 1])
    return round((eq[-1] - 1) * 100, 1)


def run():
    print(f"\n{'='*74}\n  THE FRAGILITY THERMOSTAT — an original multi-sensor risk engine\n{'='*74}")
    dates, mat = build()
    print(f"  data {dates[0]} → {dates[-1]}  ({len(dates)} days)\n")
    F, sensors = fragility_series(dates, mat)

    eng = backtest(dates, mat, F)
    spy = _bench(dates, mat, {"SPY": 1})
    p6040 = _bench(dates, mat, {"SPY": 0.6, "AGG": 0.4})
    vt = _voltarget(dates, mat)

    print(f"  {'strategy':26} {'CAGR%':>7} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>8}")
    for lbl, r in [("FRAGILITY THERMOSTAT", eng), ("Vol-target SPY (1-sensor)", vt),
                   ("SPY buy&hold", spy), ("60/40", p6040)]:
        s = _stats(r)
        print(f"  {lbl:26} {s['cagr']:>7} {s['vol']:>6} {s['sharpe']:>7} {s['mdd']:>8}")

    print(f"\n  BEARS (return during drawdown):")
    print(f"  {'strategy':26} " + " ".join(f"{b[0]:>8}" for b in BEARS))
    for lbl, r in [("FRAGILITY THERMOSTAT", eng), ("Vol-target SPY", vt), ("SPY", spy)]:
        print(f"  {lbl:26} " + " ".join(f"{str(_bear(dates, r, b[1], b[2])):>8}" for b in BEARS))

    # avg exposure + how often fully defensive
    valid = ~np.isnan(F)
    exp = np.clip(MAX_EXP * (1 - F[valid]), 0, MAX_EXP)
    print(f"\n  behaviour: avg equity exposure {exp.mean():.2f}x, "
          f"defensive (<0.5x) {100*(exp<0.5).mean():.0f}% of the time, "
          f"levered (>1x) {100*(exp>1).mean():.0f}% of the time")

    se, sv, ss = _stats(eng), _stats(vt), _stats(spy)
    print(f"\n  VERDICT (does fusing 6 sensors beat 1-sensor vol-target and buy&hold?):")
    if se["sharpe"] > sv["sharpe"] and se["sharpe"] > ss["sharpe"]:
        print(f"    ✅ THE DESIGN WORKS: Sharpe {se['sharpe']} > vol-target {sv['sharpe']} > /and SPY {ss['sharpe']},")
        print(f"       maxDD {se['mdd']}% vs SPY {ss['mdd']}%. Multi-sensor fusion added value.")
    elif se["sharpe"] >= sv["sharpe"]:
        print(f"    🟡 MATCHES/edges the 1-sensor version (Sharpe {se['sharpe']} vs {sv['sharpe']}); "
              f"beats SPY {ss['sharpe']}. Robust but the extra sensors added little.")
    else:
        print(f"    ❌ No better than simpler vol-target ({se['sharpe']} vs {sv['sharpe']}). "
              f"The extra sensors didn't help.")
    print(f"{'='*74}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
