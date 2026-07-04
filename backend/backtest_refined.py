"""
Experiment A — refined insider edge (officer-driven, small-cap, larger clusters).

The broad ">=2 insiders" signal was marginal & inconsistent. Academic literature
says the insider effect concentrates where information asymmetry is highest:
  - OFFICER buys (CEO/CFO/President) >> director/10%-owner buys
  - SMALLER / less-liquid names (where a retail-size player actually has an edge)
  - LARGER conviction clusters (>=3 insiders or bigger $)

These filters are chosen from PRIORS, not fitted to data, and — critically —
tested on FRESH quarters (2024) not examined in the first run, so this is a
genuine out-of-sample test of the refined hypothesis, not curve-fitting.

Run:  python3 backtest_refined.py 2024q1 2024q2 2024q3 2024q4
"""

import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

import backtest as bt
import backtest_portfolio as bp
import metrics as M

# ─── Refined filters (a-priori) ───────────────────────────────────────────────
REQUIRE_OFFICER = True         # cluster must include >=1 officer (CEO/CFO/etc.)
MIN_INSIDERS = 3               # larger clusters (vs 2 in the broad test)
MIN_VALUE = 100_000
MAX_ADV_USD = 30_000_000       # avg daily $ volume < $30M → smaller/less-liquid
ROUND_TRIP_BPS = 60.0          # honest cost for less-liquid names (2x the broad test)

_OFFICER_WORDS = ("officer", "chief", "ceo", "cfo", "coo", "president", "vp",
                  "vice president", "treasurer", "principal")


def _is_officer(relationship: str, title: str) -> bool:
    s = f"{relationship} {title}".lower()
    return any(w in s for w in _OFFICER_WORDS)


def build_clusters_refined(quarter: str) -> list:
    """Like backtest.build_clusters but captures owner role and keeps only
    officer-inclusive clusters of >= MIN_INSIDERS distinct insiders."""
    path = bt.download_dataset(quarter)
    with __import__("zipfile").ZipFile(path) as zf:
        names = zf.namelist()
        def find(n): return next((x for x in names if x.upper().endswith(n.upper())), None)
        submissions = bt._read_tsv(zf, find("SUBMISSION.tsv"))
        nonderiv = bt._read_tsv(zf, find("NONDERIV_TRANS.tsv"))
        owners = bt._read_tsv(zf, find("REPORTINGOWNER.tsv"))

    acc_issuer = {s.get("ACCESSION_NUMBER"): {
        "ticker": (s.get("ISSUERTRADINGSYMBOL") or "").strip().upper(),
        "name": s.get("ISSUERNAME", ""), "filing_date": s.get("FILING_DATE", ""),
    } for s in submissions}
    acc_owner = {o.get("ACCESSION_NUMBER"): {
        "cik": o.get("RPTOWNERCIK", ""),
        "officer": _is_officer(o.get("RPTOWNER_RELATIONSHIP", ""), o.get("RPTOWNER_TITLE", "")),
    } for o in owners}

    bad = {"NONE", "N/A", "", "NA"}
    buys = defaultdict(list)
    for t in nonderiv:
        if (t.get("TRANS_CODE") or "").strip().upper() != "P":
            continue
        acc = t.get("ACCESSION_NUMBER")
        iss = acc_issuer.get(acc)
        if not iss or not iss["ticker"] or iss["ticker"] in bad:
            continue
        if not iss["ticker"].isalpha() or len(iss["ticker"]) > 5:
            continue
        try:
            shares = float(t.get("TRANS_SHARES") or 0); price = float(t.get("TRANS_PRICEPERSHARE") or 0)
        except ValueError:
            continue
        own = acc_owner.get(acc, {"cik": acc, "officer": False})
        buys[iss["ticker"]].append({
            "date": (t.get("TRANS_DATE") or iss["filing_date"] or "").split(".")[0],
            "filing_date": iss["filing_date"], "owner": own["cik"], "officer": own["officer"],
            "value": shares * price, "price": price, "name": iss["name"],
        })

    clusters = []
    for ticker, txns in buys.items():
        txns = [t for t in txns if bt._parse_date(t["date"])]
        txns.sort(key=lambda x: bt._parse_date(x["date"]))
        used = set()
        for i, anchor in enumerate(txns):
            if i in used:
                continue
            a_date = bt._parse_date(anchor["date"])
            win = [anchor]; idx = [i]
            for j in range(i + 1, len(txns)):
                d = bt._parse_date(txns[j]["date"])
                if d and (d - a_date).days <= bt.CLUSTER_WINDOW_DAYS:
                    win.append(txns[j]); idx.append(j)
                elif d:
                    break
            distinct = {t["owner"] for t in win}
            has_officer = any(t["officer"] for t in win)
            if len(distinct) >= MIN_INSIDERS and (has_officer or not REQUIRE_OFFICER):
                fds = [bt._parse_date(t.get("filing_date")) for t in win]
                fds = [d for d in fds if d]
                clusters.append({
                    "ticker": ticker, "name": anchor["name"],
                    "cluster_date": a_date.strftime("%Y-%m-%d"),
                    "actionable_date": (max(fds) if fds else a_date).strftime("%Y-%m-%d"),
                    "n_insiders": len(distinct), "has_officer": has_officer,
                    "total_value": round(sum(t["value"] for t in win), 0),
                })
                used.update(idx)
    clusters = [c for c in clusters if c["total_value"] >= MIN_VALUE]
    clusters.sort(key=lambda c: (c["n_insiders"], c["total_value"]), reverse=True)
    print(f"  Found {len(clusters)} refined clusters in {quarter} "
          f"(officer-inclusive, >={MIN_INSIDERS} insiders, >=${MIN_VALUE:,.0f})")
    return clusters


def _bars_with_volume(ticker, start, end):
    """Alpaca daily bars including volume (for the liquidity filter)."""
    import os
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    import pandas as pd
    client = StockHistoricalDataClient(os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY"))
    try:
        req = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Day,
                               start=datetime.strptime(start, "%Y-%m-%d"),
                               end=datetime.strptime(end, "%Y-%m-%d"), feed="iex")
        df = client.get_stock_bars(req).df
        if df.empty:
            return []
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level=0)
        return [{"date": i.strftime("%Y-%m-%d"), "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"]), "volume": float(r.get("volume", 0))}
                for i, r in df.iterrows()]
    except Exception:
        return []


def simulate_refined(cluster: dict) -> dict:
    """Trade sim + liquidity filter (drop names that are too liquid/large)."""
    ticker = cluster["ticker"]
    cdate = cluster.get("actionable_date") or cluster["cluster_date"]
    end = (datetime.strptime(cdate, "%Y-%m-%d") + timedelta(days=75)).strftime("%Y-%m-%d")
    bars = _bars_with_volume(ticker, cdate, end)
    if len(bars) < 5:
        return {"ok": False}
    adv = sum(b["close"] * b["volume"] for b in bars[:20]) / min(20, len(bars))
    if adv > MAX_ADV_USD:
        return {"ok": False, "reason": "too_liquid"}        # not our edge — skip
    entry = bars[0]["open"]
    if entry < bt.MIN_PRICE:
        return {"ok": False, "reason": "penny"}

    spy = bp._bars("SPY", cdate, end)
    spy_entry = spy[0]["open"] if spy else None
    fwd = {}
    for h in [20]:
        if len(bars) > h and spy and len(spy) > h and spy_entry:
            fwd["20_vs_spy"] = (bars[h]["close"] - entry) / entry * 100 - (spy[h]["close"] - spy_entry) / spy_entry * 100

    stop_p = entry * (1 - bt.STOP_PCT); target_p = entry * (1 + bt.TARGET_PCT)
    exit_price = exit_reason = None
    for b in bars[1:bt.MAX_HOLD_DAYS + 2]:
        if b["low"] <= stop_p:
            exit_price, exit_reason = stop_p, "stop"; break
        if b["high"] >= target_p:
            exit_price, exit_reason = target_p, "target"; break
    if exit_price is None:
        exit_price, exit_reason = bars[min(bt.MAX_HOLD_DAYS, len(bars) - 1)]["close"], "time"
    trade_ret = (exit_price - entry) / entry * 100
    r_multiple = trade_ret / (bt.STOP_PCT * 100)
    return {"ok": True, "ticker": ticker, "r_multiple": round(r_multiple, 2),
            "trade_ret": round(trade_ret, 2), "exit_reason": exit_reason,
            "adv_usd": round(adv, 0), "fwd": fwd}


def run(quarters):
    cost_on_capital = bp.POS_NOTIONAL_FRAC * ROUND_TRIP_BPS / 10000.0
    bp.COST_ON_CAPITAL = cost_on_capital     # use the honest higher cost for stats
    print(f"\n{'='*70}\n  EXPERIMENT A — REFINED INSIDER EDGE (officer/small-cap/larger)\n"
          f"  quarters={quarters}  cost={ROUND_TRIP_BPS:.0f}bps  ADV<${MAX_ADV_USD/1e6:.0f}M\n{'='*70}")
    per_q, all_tr = {}, []
    for q in quarters:
        print(f"\n  ── {q} ──")
        cl = build_clusters_refined(q)[:200]
        tr = []
        for i, c in enumerate(cl):
            r = simulate_refined(c)
            if r.get("ok"):
                r["ret_gross"] = bp.RISK_PCT * r["r_multiple"]
                r["ret_net"] = r["ret_gross"] - cost_on_capital
                tr.append(r)
            if (i + 1) % 25 == 0:
                print(f"    ...{q}: {i+1}/{len(cl)} ({len(tr)} valid, others too-liquid/no-data)")
            time.sleep(0.12)
        per_q[q] = tr; all_tr.extend(tr)

    print(f"\n{'='*70}\n  PER-QUARTER (fresh out-of-sample folds)\n{'='*70}")
    print(f"  {'quarter':10} {'n':>4} {'win%':>6} {'exp_bps':>8} {'net%':>7} {'maxDD%':>7} {'vsSPY%':>7} {'beatSPY%':>8}")
    for q in quarters:
        s = bp._portfolio_stats(per_q[q], q, 3)
        if s["n"]:
            print(f"  {q:10} {s['n']:>4} {s['win_rate']:>6} {s['expectancy_bps_per_trade']:>8} "
                  f"{s['net_return_on_capital_pct']:>7} {s['max_drawdown_pct']:>7} "
                  f"{str(s['avg_excess_vs_spy_20d_pct']):>7} {str(s['pct_beat_spy_20d']):>8}")
        else:
            print(f"  {q:10}   (no valid trades)")
    pooled = bp._portfolio_stats(all_tr, "POOLED", 3)
    print(f"\n{'='*70}\n  POOLED ({pooled['n']} trades)\n{'='*70}")
    for k in ["win_rate", "expectancy_bps_per_trade", "net_return_on_capital_pct",
              "sharpe_annualized", "deflated_sharpe", "max_drawdown_pct",
              "avg_excess_vs_spy_20d_pct", "pct_beat_spy_20d", "reliable"]:
        print(f"    {k:28}: {pooled.get(k)}")

    exp = pooled.get("expectancy_bps_per_trade") or 0
    beat = pooled.get("pct_beat_spy_20d") or 0
    dsr = pooled.get("deflated_sharpe") or 0
    print(f"\n  VERDICT:")
    if pooled["n"] < 40:
        print("    ⚠ Too few refined trades to conclude — widen quarter range.")
    elif exp > 0 and beat > 55 and dsr >= 0.9:
        print(f"    ✅ REFINED EDGE HOLDS OUT-OF-SAMPLE: +{exp}bps/trade, beats SPY {beat}%, DSR {dsr}.")
    elif exp > 0 and beat > 52:
        print(f"    🟡 IMPROVED but not conclusive: +{exp}bps/trade, beats SPY {beat}%.")
    else:
        print(f"    ❌ FILTER DID NOT CREATE A DURABLE EDGE: {exp}bps/trade, beats SPY {beat}%.")
    print(f"{'='*70}\n")
    return pooled


if __name__ == "__main__":
    qs = sys.argv[1:] or ["2024q1", "2024q2", "2024q3", "2024q4"]
    run(qs)
