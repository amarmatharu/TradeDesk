"""
Ablation + robustness test for the Fragility Thermostat (validating my own design).

Two honest questions:
  1. Is the 6-sensor FUSION real, or is one sensor doing all the work?
     -> Leave-one-out: drop each sensor, re-run. If Sharpe holds up regardless of
        which we drop, the fusion is robust. Also test each sensor ALONE.
  2. Is it consistent across time, or one lucky period?
     -> Sub-period Sharpe (2005-2011 / 2012-2018 / 2019-2026).

Run:  python3 fragility_ablation.py
"""

import os
import numpy as np
import fragility_engine as FE
import metrics as M

NAMES = ["vol_level", "vol_accel", "trend_break", "hedge_fail", "drawdown", "flight_safety"]


def _F_from(sensors, cols, n):
    F = np.full(n, np.nan)
    for t in range(260, n):
        F[t] = np.mean(sensors[t, cols])
    return F


def _run(dates, mat, F):
    r = FE.backtest(dates, mat, F)
    return r, FE._stats(r)


def _subperiod_sharpe(dates, r, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end and r[i] != 0]
    if len(idx) < 60:
        return None
    return round(M._sharpe([r[i] for i in idx], 252), 2)


def run():
    print(f"\n{'='*72}\n  FRAGILITY THERMOSTAT — ABLATION & ROBUSTNESS\n{'='*72}")
    dates, mat = FE.build()
    F_all, sensors = FE.fragility_series(dates, mat)
    n = len(dates)

    r_full, s_full = _run(dates, mat, _F_from(sensors, list(range(6)), n))
    print(f"\n  FULL (6 sensors): Sharpe {s_full['sharpe']}  CAGR {s_full['cagr']}%  maxDD {s_full['mdd']}%")

    print(f"\n  [1] LEAVE-ONE-OUT (drop each sensor — Sharpe should stay ~{s_full['sharpe']} if fusion is real):")
    loo = []
    for i in range(6):
        cols = [j for j in range(6) if j != i]
        _, s = _run(dates, mat, _F_from(sensors, cols, n))
        loo.append(s["sharpe"])
        flag = "" if abs(s["sharpe"] - s_full["sharpe"]) <= 0.06 else "  <-- material change"
        print(f"      without {NAMES[i]:14}: Sharpe {s['sharpe']}  maxDD {s['mdd']}%{flag}")
    print(f"      range across leave-one-out: {min(loo)}–{max(loo)}")

    print(f"\n  [2] EACH SENSOR ALONE (which carry signal on their own?):")
    solo = []
    for i in range(6):
        _, s = _run(dates, mat, _F_from(sensors, [i], n))
        solo.append((NAMES[i], s["sharpe"], s["mdd"]))
    for nm, sh, dd in sorted(solo, key=lambda x: -x[1]):
        print(f"      {nm:14} only: Sharpe {sh}  maxDD {dd}%")

    print(f"\n  [3] SUB-PERIOD CONSISTENCY (full model):")
    for a, b in [("2005-01-01", "2011-12-31"), ("2012-01-01", "2018-12-31"), ("2019-01-01", "2026-12-31")]:
        print(f"      {a[:4]}–{b[:4]}: Sharpe {_subperiod_sharpe(dates, r_full, a, b)}")

    spy_sh = FE._stats(FE._bench(dates, mat, {"SPY": 1}))["sharpe"]
    print(f"\n  VERDICT:")
    robust_fusion = (max(loo) - min(loo)) <= 0.10 and min(loo) > spy_sh
    best_solo = max(s[1] for s in solo)
    if robust_fusion and s_full["sharpe"] >= best_solo:
        print(f"    ✅ FUSION IS REAL: dropping any single sensor keeps Sharpe in [{min(loo)},{max(loo)}],")
        print(f"       all still > SPY {spy_sh}; and the full model ({s_full['sharpe']}) >= best solo sensor ({best_solo}).")
        print(f"       No single sensor carries it — the multi-sensor design genuinely adds robustness.")
    elif s_full["sharpe"] < best_solo:
        print(f"    🟡 A single sensor ({[s for s in solo if s[1]==best_solo][0][0]}, Sharpe {best_solo}) matches/beats")
        print(f"       the full 6-sensor model ({s_full['sharpe']}) — the fusion adds little; simplify.")
    else:
        print(f"    🟡 Mixed: LOO range {min(loo)}–{max(loo)}. Some sensors matter more than others.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
