"""
Multi-quarter backtest — runs the look-ahead-fixed insider-edge test across
many quarters (multiple market regimes) and aggregates into one honest verdict.

Run:  python3 backtest_multi.py
"""

import sys
from collections import defaultdict
import backtest as bt

QUARTERS = ["2024q1", "2024q2", "2024q3", "2024q4",
            "2025q1", "2025q2", "2025q3", "2025q4", "2026q1"]

MAX_PER_QUARTER = 80     # cap per quarter to keep runtime sane
MIN_VALUE = 50_000


def run_all():
    all_results = []
    per_quarter = {}

    for q in QUARTERS:
        try:
            print(f"\n>>> {q} ...")
            clusters = bt.build_clusters(q)
            clusters = [c for c in clusters if c["total_value"] >= MIN_VALUE][:MAX_PER_QUARTER]
            qres = []
            for i, c in enumerate(clusters):
                r = bt.simulate(c)
                if r.get("ok"):
                    r["quarter"] = q
                    qres.append(r); all_results.append(r)
                if (i + 1) % 20 == 0:
                    print(f"    {q}: {i+1}/{len(clusters)} ({len(qres)} valid)")
                import time; time.sleep(0.12)
            per_quarter[q] = qres
            print(f"    {q}: {len(qres)} valid clusters")
        except Exception as e:
            print(f"    {q}: ERROR {e}")

    _report(all_results, per_quarter)


def _stats(results):
    n = len(results)
    if not n:
        return None
    excess20 = [r["fwd"].get("20_vs_spy") for r in results if r["fwd"].get("20_vs_spy") is not None]
    trade_rets = [r["trade_ret"] for r in results]
    r_mults = [r["r_multiple"] for r in results]
    wins = [x for x in trade_rets if x > 0]
    return {
        "n": n,
        "win_rate": round(len(wins)/n*100, 1),
        "avg_ret": round(sum(trade_rets)/n, 2),
        "avg_r": round(sum(r_mults)/n, 2),
        "avg_excess_20d": round(sum(excess20)/len(excess20), 2) if excess20 else None,
        "pct_beat_spy_20d": round(sum(1 for x in excess20 if x > 0)/len(excess20)*100, 1) if excess20 else None,
    }


def _report(all_results, per_quarter):
    print(f"\n{'='*70}")
    print(f"  MULTI-QUARTER INSIDER EDGE BACKTEST (look-ahead fixed: filing-date entry)")
    print(f"{'='*70}")

    # Per-quarter table
    print(f"\n  {'Quarter':<9} {'n':>4} {'win%':>6} {'avgRet':>8} {'avgR':>6} {'excess20d':>10} {'beatSPY%':>9}")
    print(f"  {'-'*58}")
    for q in QUARTERS:
        s = _stats(per_quarter.get(q, []))
        if not s:
            print(f"  {q:<9} {'—':>4}")
            continue
        ex = f"{s['avg_excess_20d']:+.2f}%" if s['avg_excess_20d'] is not None else "—"
        bs = f"{s['pct_beat_spy_20d']:.0f}%" if s['pct_beat_spy_20d'] is not None else "—"
        print(f"  {q:<9} {s['n']:>4} {s['win_rate']:>5.1f}% {s['avg_ret']:>7.2f}% {s['avg_r']:>+6.2f} {ex:>10} {bs:>9}")

    # Aggregate
    agg = _stats(all_results)
    print(f"  {'-'*58}")
    if agg:
        ex = f"{agg['avg_excess_20d']:+.2f}%" if agg['avg_excess_20d'] is not None else "—"
        bs = f"{agg['pct_beat_spy_20d']:.0f}%" if agg['pct_beat_spy_20d'] is not None else "—"
        print(f"  {'ALL':<9} {agg['n']:>4} {agg['win_rate']:>5.1f}% {agg['avg_ret']:>7.2f}% {agg['avg_r']:>+6.2f} {ex:>10} {bs:>9}")

    # Event study aggregate at all horizons
    print(f"\n  EVENT STUDY (all quarters, vs SPY):")
    for h in bt.HORIZONS:
        ex = [r["fwd"].get(f"{h}_vs_spy") for r in all_results if r["fwd"].get(f"{h}_vs_spy") is not None]
        raw = [r["fwd"].get(h) for r in all_results if r["fwd"].get(h) is not None]
        if ex:
            print(f"    +{h:>2}d: {sum(raw)/len(raw):+6.2f}% raw  {sum(ex)/len(ex):+6.2f}% vs SPY  "
                  f"{sum(1 for x in ex if x>0)/len(ex)*100:4.0f}% beat SPY  (n={len(ex)})")

    # Verdict
    print(f"\n  VERDICT:")
    if not agg or not agg["avg_excess_20d"]:
        print("    Insufficient data.")
        return
    n = agg["n"]; ex = agg["avg_excess_20d"]; beat = agg["pct_beat_spy_20d"]
    # How many quarters were individually positive (consistency check)
    pos_quarters = sum(1 for q in QUARTERS
                       if (_stats(per_quarter.get(q, [])) or {}).get("avg_excess_20d", 0) and
                          _stats(per_quarter.get(q, []))["avg_excess_20d"] > 0)
    total_quarters = sum(1 for q in QUARTERS if per_quarter.get(q))
    print(f"    Sample: {n} clusters across {total_quarters} quarters")
    print(f"    Consistency: {pos_quarters}/{total_quarters} quarters beat SPY on average")
    print(f"    Aggregate excess vs SPY (20d): {ex:+.2f}%  ·  {beat:.0f}% of trades beat SPY")
    if n >= 200 and ex > 1 and beat > 52 and pos_quarters >= total_quarters * 0.6:
        print(f"    ✅ VALIDATED: edge holds across regimes with honest filing-date entry.")
        print(f"       This is a backtest you can act on. Proceed to live with confidence.")
    elif ex > 0 and beat >= 50:
        print(f"    🟡 PROMISING BUT NOT BULLETPROOF: positive but check consistency/sample.")
        print(f"       Worth running live (Strategy B) but keep position sizes modest.")
    else:
        print(f"    ❌ EDGE DOES NOT SURVIVE honest entry timing. Retire the thesis.")

    print(f"{'='*70}\n")


if __name__ == "__main__":
    run_all()
