"""
Robustness sweep for the tactical strategies (the fragility torture test).

A real edge holds across reasonable parameter choices; a lucky one works only at
the exact config you happened to pick. So we sweep:
  - momentum LOOKBACK: 3 / 6 / 9 / 12 months
  - REBALANCE-DAY offset: 5 different day-of-month grids (timing-luck check)
  - vol-target: 3 target vols

Pass bar: the strategy beats SPY buy&hold on Sharpe AND drawdown in the LARGE
MAJORITY of parameter cells — not just one. If results scatter (some great, some
worse than SPY), it's fragile. If they cluster above SPY, it's robust.

Run:  python3 robustness_sweep.py
"""

import os
import numpy as np
import tactical_lab as TL
import metrics as M

LOOKBACKS = [63, 126, 189, 252]        # 3/6/9/12 months
OFFSETS = [0, 4, 8, 12, 16]            # rebalance-day-of-month grids
REBAL = 21
COST = TL.COST_BPS / 10000


def _stats(rets):
    rets = np.asarray(rets)
    eq = np.cumprod(1 + rets)
    cagr = eq[-1] ** (252 / len(rets)) - 1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    return round(M._sharpe(list(rets), 252), 2), round(mdd * 100, 1), round(cagr * 100, 1)


def gem(dates, mat, lb, offset):
    n = len(dates); out = []; held = "AGG"; t = lb + 1 + offset
    while t < n - 1:
        if (t - lb - 1 - offset) % REBAL == 0:
            spy = mat["SPY"][t] / mat["SPY"][t - lb] - 1
            efa = mat["EFA"][t] / mat["EFA"][t - lb] - 1
            pick = ("SPY" if spy >= efa else "EFA") if spy > 0 else "AGG"
            cost = 0 if pick == held else COST; held = pick
        else:
            cost = 0
        out.append(mat[held][t + 1] / mat[held][t] - 1 - cost); t += 1
    return out


def absmom(dates, mat, lb, offset):
    n = len(dates); out = []; inmkt = False; t = lb + 1 + offset
    while t < n - 1:
        if (t - lb - 1 - offset) % REBAL == 0:
            newin = (mat["SPY"][t] / mat["SPY"][t - lb] - 1) > 0
            cost = 0 if newin == inmkt else COST; inmkt = newin
        else:
            cost = 0
        out.append((mat["SPY"][t + 1] / mat["SPY"][t] - 1 if inmkt else 0.0) - cost); t += 1
    return out


def vol_target(dates, mat, target_ann):
    spy = mat["SPY"]; rets = np.diff(spy) / spy[:-1]; tv = target_ann / np.sqrt(252)
    n = len(dates); out = []; t = 253; lev = 1.0
    while t < n - 1:
        if (t - 253) % REBAL == 0:
            v = np.std(rets[t - 40:t]) or 1e-9
            lev = min(tv / v, 2.0)
        out.append(lev * (spy[t + 1] / spy[t] - 1)); t += 1
    return out


def run():
    print(f"\n{'='*72}\n  ROBUSTNESS SWEEP — tactical allocation\n{'='*72}")
    dates, mat = TL.build()
    # SPY baseline over comparable window
    spy_rets = [mat["SPY"][t + 1] / mat["SPY"][t] - 1 for t in range(253, len(dates) - 1)]
    b_sh, b_dd, b_cagr = _stats(spy_rets)
    print(f"  data {dates[0]}→{dates[-1]}   SPY baseline: Sharpe {b_sh}  maxDD {b_dd}%  CAGR {b_cagr}%\n")

    for name, fn in [("DUAL MOMENTUM (GEM)", gem), ("ABS-MOM SPY", absmom)]:
        print(f"  ── {name} ── (Sharpe / maxDD% averaged across {len(OFFSETS)} rebalance-day grids)")
        print(f"     {'lookback':>10} {'Sharpe':>8} {'maxDD%':>8} {'CAGR%':>7} {'beats SPY?':>11}")
        wins = 0; total = 0
        for lb in LOOKBACKS:
            shs, dds, cgs = [], [], []
            for off in OFFSETS:
                sh, dd, cg = _stats(fn(dates, mat, lb, off))
                shs.append(sh); dds.append(dd); cgs.append(cg)
                total += 1; wins += (sh > b_sh and dd > b_dd)
            avg_sh, avg_dd, avg_cg = np.mean(shs), np.mean(dds), np.mean(cgs)
            beat = "✓" if (avg_sh > b_sh and avg_dd > b_dd) else ("~" if avg_sh > b_sh or avg_dd > b_dd else "✗")
            mo = {63: "3mo", 126: "6mo", 189: "9mo", 252: "12mo"}[lb]
            print(f"     {mo:>10} {avg_sh:>8.2f} {avg_dd:>8.1f} {avg_cg:>7.1f} {beat:>11}")
        print(f"     -> {wins}/{total} parameter cells beat SPY on BOTH Sharpe & drawdown\n")

    print(f"  ── VOL-TARGET SPY ── (target-vol sweep)")
    print(f"     {'target':>10} {'Sharpe':>8} {'maxDD%':>8} {'CAGR%':>7}")
    for tv in [0.10, 0.12, 0.15]:
        sh, dd, cg = _stats(vol_target(dates, mat, tv))
        print(f"     {int(tv*100):>8}% {sh:>9.2f} {dd:>8.1f} {cg:>7.1f}")

    print(f"\n  VERDICT: robust if the large majority of cells beat SPY on both metrics")
    print(f"  across lookbacks AND rebalance-day timing (not just one lucky config).")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
