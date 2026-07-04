"""
Multi-strategy blend (Exp 9) — the pod-shop insight.

Every "clever" strategy failed; the only winner is trend/risk-management. So stop
hunting for one magic edge and do what real multi-manager funds do: COMBINE
several decent, UNCORRELATED, risk-managed sleeves. Diversification across
uncorrelated return streams is the actual source of high Sharpe.

Sleeves (both validated earlier, both long history via Tiingo total-return):
  A) TACTICAL EQUITY (GEM): rotate SPY/EFA with a 12m-momentum crash overlay to
     bonds. Our deployed winner. Correlated to equities.
  B) MANAGED-FUTURES TREND: time-series momentum long/short across SPY, bonds
     (AGG), gold (GLD), commodities (DBC), inverse-vol weighted. Historically
     LOW/NEGATIVE correlation to equities and positive in crises.

If A and B are truly uncorrelated, a risk-parity blend should have a HIGHER
Sharpe than either alone — the whole point of diversification.

Run:  python3 multi_strategy.py
"""

import os
import json
import time
import pickle
import urllib.request
import numpy as np
import metrics as M

CACHE = os.path.join(os.path.dirname(__file__), ".tiingo_cache")
REBAL = 21
LB = 252
ASSETS = ["SPY", "EFA", "AGG", "GLD", "DBC"]
BEARS = [("2008", "2007-10-09", "2009-03-09"), ("2020", "2020-02-19", "2020-03-23"),
         ("2022", "2022-01-03", "2022-10-12")]


def _tiingo(sym):
    fn = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(fn):
        with open(fn, "rb") as f:
            return pickle.load(f)
    key = os.environ["TIINGO_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1995-01-01&token={key}&format=json&resampleFreq=daily"
    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        out = ([r["date"][:10] for r in d], np.array([r["adjClose"] for r in d], float))
    except Exception:
        out = ([], np.array([]))
    with open(fn, "wb") as f:
        pickle.dump(out, f)
    time.sleep(0.3)
    return out


def build():
    ser = {s: dict(zip(*_tiingo(s))) for s in ASSETS}
    dates = sorted(set.intersection(*[set(v.keys()) for v in ser.values()]))
    mat = {s: np.array([ser[s][d] for d in dates]) for s in ASSETS}
    return dates, mat


def sleeve_gem(dates, mat):
    n = len(dates); out = np.zeros(n); held = "AGG"
    for t in range(LB + 1, n - 1):
        if (t - LB - 1) % REBAL == 0:
            spy = mat["SPY"][t] / mat["SPY"][t - LB] - 1
            efa = mat["EFA"][t] / mat["EFA"][t - LB] - 1
            held = (("SPY" if spy >= efa else "EFA") if spy > 0 else "AGG")
        out[t + 1] = mat[held][t + 1] / mat[held][t] - 1
    return out


def sleeve_trend(dates, mat):
    rets = {s: np.concatenate([[0], np.diff(mat[s]) / mat[s][:-1]]) for s in ASSETS}
    n = len(dates); out = np.zeros(n); pos = {s: 0.0 for s in ASSETS}
    for t in range(LB + 1, n - 1):
        if (t - LB - 1) % REBAL == 0:
            sig = {s: np.sign(mat[s][t] / mat[s][t - LB] - 1) for s in ASSETS}
            vol = {s: np.std(rets[s][t - 40:t]) or 1e-9 for s in ASSETS}
            inv = {s: 1 / vol[s] for s in ASSETS}
            tot = sum(inv.values())
            pos = {s: sig[s] * inv[s] / tot for s in ASSETS}   # gross ≤ 1
        out[t + 1] = sum(pos[s] * rets[s][t + 1] for s in ASSETS)
    return out


def stats(r, label):
    r = np.asarray(r); r = r[r != 0] if label == "x" else r
    active = np.where(~np.isnan(r))[0]
    r = r[active[0]:] if len(active) else r
    eq = np.cumprod(1 + r)
    cagr = eq[-1] ** (252 / len(r)) - 1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    return {"label": label, "cagr": round(cagr * 100, 1),
            "vol": round(float(np.std(r, ddof=1)) * np.sqrt(252) * 100, 1),
            "sharpe": round(M._sharpe(list(r), 252), 2), "mdd": round(mdd * 100, 1)}


def bench(dates, mat, w):
    n = len(dates); out = np.zeros(n)
    for t in range(LB + 1, n - 1):
        out[t + 1] = sum(wt * (mat[a][t + 1] / mat[a][t] - 1) for a, wt in w.items())
    return out


def bear(dates, series, s, e):
    idx = [i for i, d in enumerate(dates) if s <= d <= e]
    if len(idx) < 2:
        return None
    eq = np.cumprod(1 + series[idx[0]:idx[-1] + 1])
    return round((eq[-1] - 1) * 100, 1)


def run():
    print(f"\n{'='*72}\n  MULTI-STRATEGY BLEND — diversifying uncorrelated sleeves\n{'='*72}")
    dates, mat = build()
    print(f"  data {dates[0]} → {dates[-1]}  ({len(dates)} days)\n")
    start = LB + 2

    A = sleeve_gem(dates, mat)[start:]
    B = sleeve_trend(dates, mat)[start:]
    spy = bench(dates, mat, {"SPY": 1})[start:]
    p6040 = bench(dates, mat, {"SPY": 0.6, "AGG": 0.4})[start:]

    # correlation between sleeves
    corr = float(np.corrcoef(A, B)[0, 1])

    # risk-parity blend of A and B (inverse-vol, static)
    va, vb = np.std(A) or 1e-9, np.std(B) or 1e-9
    wa, wb = (1 / va), (1 / vb); s = wa + wb; wa, wb = wa / s, wb / s
    blend = wa * A + wb * B

    print(f"  sleeve correlation A(tactical) vs B(trend): {corr:+.2f}  "
          f"(low/negative = good diversification)\n")
    print(f"  {'strategy':22} {'CAGR%':>7} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>8}")
    rows = [stats(A, "A: Tactical equity"), stats(B, "B: Managed-futures trend"),
            stats(blend, f"BLEND ({wa:.0%}A/{wb:.0%}B)"), stats(spy, "SPY buy&hold"),
            stats(p6040, "60/40")]
    for x in rows:
        print(f"  {x['label']:22} {x['cagr']:>7} {x['vol']:>6} {x['sharpe']:>7} {x['mdd']:>8}")

    print(f"\n  BEAR MARKETS (return during drawdown):")
    print(f"  {'strategy':22} " + " ".join(f"{b[0]:>8}" for b in BEARS))
    for series, lbl in [(A, "A: Tactical"), (B, "B: Trend"), (blend, "BLEND"), (spy, "SPY")]:
        print(f"  {lbl:22} " + " ".join(f"{str(bear(dates[start:], series, b[1], b[2])):>8}" for b in BEARS))

    sh_blend = stats(blend, "b")["sharpe"]
    best_sleeve = max(stats(A, "a")["sharpe"], stats(B, "b")["sharpe"])
    print(f"\n  VERDICT:")
    if sh_blend > best_sleeve and sh_blend > stats(spy, "s")["sharpe"]:
        print(f"    ✅ DIVERSIFICATION WORKS: blend Sharpe {sh_blend} > best sleeve {best_sleeve} "
              f"and > SPY {stats(spy,'s')['sharpe']}.")
        print(f"       Combining uncorrelated risk-managed sleeves = the pod-shop edge, realized.")
    else:
        print(f"    🟡 blend Sharpe {sh_blend} vs best sleeve {best_sleeve}, SPY {stats(spy,'s')['sharpe']}.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
