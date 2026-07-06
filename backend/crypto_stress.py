"""
Stress-test the crypto MA-trend edge before believing/deploying it.

The MA-50 trend beat HODL on 11y of BTC/ETH — but that's one big bull. Torture it:
  1. DID IT DODGE THE CRASHES? Return during the 2018 (-84%), 2020 COVID, and
     2022 (-77%) crypto bears — strategy vs HODL. This is the whole thesis: does
     it actually step to cash before the wipeouts, or just ride the bull?
  2. SUB-PERIOD consistency: Sharpe of the strategy in 3 separate eras.
  3. PARAMETER robustness: does the edge hold across MA 30..200 (not just 50)?

Run:  python3 crypto_stress.py
"""

import numpy as np
import crypto_lab as CL
import metrics as M

BEARS = [("2018 bear", "2017-12-16", "2018-12-15"),
         ("2020 COVID", "2020-02-13", "2020-03-13"),
         ("2022 bear", "2021-11-10", "2022-11-21")]
ERAS = [("2015-2018", "2015-01-01", "2018-12-31"),
        ("2019-2021", "2019-01-01", "2021-12-31"),
        ("2022-2026", "2022-01-01", "2026-12-31")]


def _cum(dates, r, a, b):
    idx = [i for i, d in enumerate(dates) if a <= d <= b]
    if len(idx) < 2:
        return None
    return round((np.prod(1 + r[idx[0]:idx[-1] + 1]) - 1) * 100, 1)


def _sharpe_period(dates, r, a, b):
    seg = [r[i] for i, d in enumerate(dates) if a <= d <= b and not np.isnan(r[i])]
    return round(M._mean(seg) / (M._std(seg) or 1e-9) * np.sqrt(365), 2) if len(seg) > 60 else None


def run():
    print(f"\n{'='*70}\n  CRYPTO MA-TREND STRESS TEST\n{'='*70}")
    for sym, label in [("btcusd", "BITCOIN"), ("ethusd", "ETHEREUM")]:
        dates, px = CL._tiingo_crypto(sym)
        hodl = CL.hodl(px)
        trend = CL.ma_trend(px, 50)
        pos = np.where(px > np.array([np.mean(px[max(0, i - 50):i]) if i >= 50 else np.nan for i in range(len(px))]), 1.0, 0.0)

        print(f"\n  ── {label} ──")
        print(f"  [1] BEAR-MARKET BEHAVIOUR (return during each crash; trend should ≈ flat):")
        print(f"      {'crash':12} {'MA-50 trend':>13} {'HODL':>10}")
        for name, a, b in BEARS:
            t = _cum(dates, trend, a, b); h = _cum(dates, hodl, a, b)
            saved = "  ✓ dodged" if (t is not None and h is not None and t > h + 10) else ""
            print(f"      {name:12} {str(t)+'%':>13} {str(h)+'%':>10}{saved}")

        print(f"  [2] SUB-PERIOD Sharpe (trend / HODL):")
        for name, a, b in ERAS:
            st = _sharpe_period(dates, trend, a, b); sh = _sharpe_period(dates, hodl, a, b)
            print(f"      {name:12} trend {str(st):>6}  vs HODL {str(sh):>6}")

        print(f"  [3] PARAMETER robustness (MA-N: Sharpe / maxDD% — all should beat HODL):")
        base = CL._stats(hodl)
        print(f"      {'HODL':>8}: Sharpe {base['sharpe']}  maxDD {base['mdd']}%")
        for n in [30, 50, 75, 100, 150, 200]:
            s = CL._stats(CL.ma_trend(px, n))
            tag = "✓" if s['sharpe'] > base['sharpe'] and s['mdd'] > base['mdd'] else "~"
            print(f"      MA-{n:<5}: Sharpe {s['sharpe']}  maxDD {s['mdd']}%  {tag}")

    print(f"\n  VERDICT: real if the trend rule was ≈FLAT (not -70%) through the 2018 &")
    print(f"  2022 crashes, Sharpe holds across eras, and most MA lengths beat HODL.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    import os
    from pathlib import Path
    for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))
    run()
