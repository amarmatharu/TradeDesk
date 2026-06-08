"""
Backtest — Insider Edge thesis validation.

Question: When >=2 insiders buy the same stock within a window, does it
outperform SPY over the next N days? This is the core premise of Strategy B.

Method (honest event-study, not curve-fit):
1. Download SEC's quarterly Form 345 dataset (every insider transaction, free, public)
2. Reconstruct real cluster events (>=2 distinct insiders, transaction code 'P' = purchase)
3. For each cluster, pull Alpaca historical daily bars
4. Measure forward return at 10/20/30 days vs SPY over the same dates (event study)
5. Also simulate a tradeable rule (stop/target/time-stop) → win rate, avg R, expectancy
6. Compare everything to SPY buy-and-hold — the only benchmark that matters

Run:  python3 backtest.py 2026q1
"""

import os, sys, io, csv, zipfile, time
import urllib.request
from datetime import datetime, timedelta
from collections import defaultdict


def _parse_date(s: str):
    """SEC dates come as '31-MAR-2026' or sometimes ISO. Return datetime or None."""
    if not s:
        return None
    s = s.strip().split(".")[0].split(" ")[0]
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

# Load env for Alpaca
_envp = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_envp):
    for line in open(_envp):
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip().strip("'").strip('"')

SEC_BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"
HEADERS = {"User-Agent": "TradeDesk Research backtest@tradedesk.app"}

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".backtest_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ─── Strategy params (match live Strategy B intent) ────────────────────────────
CLUSTER_MIN_INSIDERS = 2
CLUSTER_WINDOW_DAYS = 14
HORIZONS = [10, 20, 30]          # forward-return measurement (trading days approx)
STOP_PCT = 0.10                  # -10% stop
TARGET_PCT = 0.20                # +20% target (2:1)
MAX_HOLD_DAYS = 30               # time stop
MIN_PRICE = 2.0                  # avoid penny stocks


# ─── 1. SEC dataset download + parse ───────────────────────────────────────────

def download_dataset(quarter: str) -> str:
    """Download + cache SEC Form 345 dataset zip for a quarter (e.g. '2026q1')."""
    path = os.path.join(CACHE_DIR, f"{quarter}_form345.zip")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        print(f"  [cache] {quarter} dataset already downloaded")
        return path
    url = f"{SEC_BASE}/{quarter}_form345.zip"
    print(f"  Downloading {url} ...")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {os.path.getsize(path)//1024} KB")
    return path


def _read_tsv(zf, name):
    with zf.open(name) as fh:
        text = io.TextIOWrapper(fh, encoding="latin-1")
        return list(csv.DictReader(text, delimiter="\t"))


def build_clusters(quarter: str) -> list:
    """Reconstruct insider-buy clusters from the SEC dataset."""
    path = download_dataset(quarter)
    print("  Parsing dataset...")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        def find(n): return next((x for x in names if x.upper().endswith(n.upper())), None)
        submissions = _read_tsv(zf, find("SUBMISSION.tsv"))
        nonderiv    = _read_tsv(zf, find("NONDERIV_TRANS.tsv"))
        owners      = _read_tsv(zf, find("REPORTINGOWNER.tsv"))

    # accession -> issuer info
    acc_issuer = {}
    for s in submissions:
        acc = s.get("ACCESSION_NUMBER")
        acc_issuer[acc] = {
            "ticker": (s.get("ISSUERTRADINGSYMBOL") or "").strip().upper(),
            "name": s.get("ISSUERNAME", ""),
            "filing_date": s.get("FILING_DATE", ""),
        }
    # accession -> owner cik
    acc_owner = {}
    for o in owners:
        acc_owner[o.get("ACCESSION_NUMBER")] = o.get("RPTOWNERCIK", "")

    # Collect PURCHASES (transaction code 'P')
    # ticker -> list of (trans_date, owner_cik, shares, price)
    _bad_tickers = {"NONE", "N/A", "", "NA"}
    buys = defaultdict(list)
    for t in nonderiv:
        if (t.get("TRANS_CODE") or "").strip().upper() != "P":
            continue
        acc = t.get("ACCESSION_NUMBER")
        iss = acc_issuer.get(acc)
        if not iss or not iss["ticker"] or iss["ticker"] in _bad_tickers:
            continue
        if not iss["ticker"].isalpha() or len(iss["ticker"]) > 5:
            continue  # skip malformed/OTC symbols
        try:
            shares = float(t.get("TRANS_SHARES") or 0)
            price = float(t.get("TRANS_PRICEPERSHARE") or 0)
        except ValueError:
            continue
        tdate = (t.get("TRANS_DATE") or iss["filing_date"] or "").split(".")[0]
        owner = acc_owner.get(acc, acc)
        buys[iss["ticker"]].append({
            "date": tdate, "filing_date": iss["filing_date"], "owner": owner,
            "shares": shares, "price": price, "value": shares * price, "name": iss["name"]
        })

    # Build clusters: >=2 distinct owners within window
    clusters = []
    for ticker, txns in buys.items():
        txns = [t for t in txns if _parse_date(t["date"])]
        txns.sort(key=lambda x: _parse_date(x["date"]))
        used = set()
        for i, anchor in enumerate(txns):
            if i in used:
                continue
            a_date = _parse_date(anchor["date"])
            if not a_date:
                continue
            window_txns = [anchor]
            window_idx = [i]
            for j in range(i + 1, len(txns)):
                d = _parse_date(txns[j]["date"])
                if not d:
                    continue
                if (d - a_date).days <= CLUSTER_WINDOW_DAYS:
                    window_txns.append(txns[j]); window_idx.append(j)
                else:
                    break
            distinct = {t["owner"] for t in window_txns}
            if len(distinct) >= CLUSTER_MIN_INSIDERS:
                total_val = sum(t["value"] for t in window_txns)
                avg_price = (sum(t["price"] for t in window_txns) / len(window_txns)) if window_txns else 0
                # ACTIONABLE date = latest filing date among clustered txns
                # (the public can only act once the last Form 4 is public — no look-ahead)
                filing_dates = [_parse_date(t.get("filing_date")) for t in window_txns]
                filing_dates = [d for d in filing_dates if d]
                actionable = max(filing_dates) if filing_dates else a_date
                clusters.append({
                    "ticker": ticker,
                    "name": anchor["name"],
                    "cluster_date": a_date.strftime("%Y-%m-%d"),
                    "actionable_date": actionable.strftime("%Y-%m-%d"),
                    "n_insiders": len(distinct),
                    "n_txns": len(window_txns),
                    "total_value": round(total_val, 0),
                    "avg_price": round(avg_price, 2),
                })
                used.update(window_idx)
    # Sort by conviction (more insiders, more $)
    clusters.sort(key=lambda c: (c["n_insiders"], c["total_value"]), reverse=True)
    print(f"  Found {len(clusters)} insider clusters in {quarter}")
    return clusters


# ─── 2. Price simulation via Alpaca ────────────────────────────────────────────

_spy_cache = None

def get_bars(ticker: str, start: str, end: str):
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    key = os.environ.get("ALPACA_API_KEY"); sec = os.environ.get("ALPACA_SECRET_KEY")
    client = StockHistoricalDataClient(key, sec)
    try:
        req = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Day,
                               start=datetime.strptime(start, "%Y-%m-%d"),
                               end=datetime.strptime(end, "%Y-%m-%d"), feed="iex")
        df = client.get_stock_bars(req).df
        if df.empty:
            return []
        import pandas as pd
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level=0)
        return [{"date": idx.strftime("%Y-%m-%d"), "open": float(r["open"]),
                 "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
                for idx, r in df.iterrows()]
    except Exception:
        return []


def simulate(cluster: dict) -> dict:
    """Event study + tradeable-rule sim for one cluster.
    Entry = first trading day's OPEN on/after the actionable (filing) date — no look-ahead."""
    ticker = cluster["ticker"]
    # Use the actionable (filing) date — when the public could really trade.
    cdate = cluster.get("actionable_date") or cluster["cluster_date"]
    start = cdate
    end = (datetime.strptime(cdate, "%Y-%m-%d") + timedelta(days=75)).strftime("%Y-%m-%d")
    bars = get_bars(ticker, start, end)
    if len(bars) < 5:
        return {"ok": False, "reason": "insufficient price data"}

    # Entry = first session OPEN on/after the actionable date (already filtered by start)
    # bars[0] is the first session >= filing date; enter at its open (realistic — you act once public)
    entry_bar = bars[0]
    entry = entry_bar["open"]
    if entry < MIN_PRICE:
        return {"ok": False, "reason": "penny"}

    # SPY for same window (benchmark)
    global _spy_cache
    spy = get_bars("SPY", start, end)
    spy_entry = spy[0]["open"] if spy else None

    # Forward returns at horizons (event study)
    fwd = {}
    for h in HORIZONS:
        if len(bars) > h:
            fwd[h] = (bars[h]["close"] - entry) / entry * 100
            if spy and len(spy) > h and spy_entry:
                fwd[f"{h}_vs_spy"] = fwd[h] - ((spy[h]["close"] - spy_entry) / spy_entry * 100)

    # Tradeable rule sim: stop / target / time-stop
    stop_p = entry * (1 - STOP_PCT)
    target_p = entry * (1 + TARGET_PCT)
    exit_price, exit_reason, days_held = None, None, 0
    for k, b in enumerate(bars[1:MAX_HOLD_DAYS + 2], start=1):
        days_held = k
        if b["low"] <= stop_p:
            exit_price, exit_reason = stop_p, "stop"; break
        if b["high"] >= target_p:
            exit_price, exit_reason = target_p, "target"; break
    if exit_price is None:
        last = bars[min(MAX_HOLD_DAYS, len(bars) - 1)]
        exit_price, exit_reason = last["close"], "time"
    trade_ret = (exit_price - entry) / entry * 100
    risk = STOP_PCT * 100
    r_multiple = trade_ret / risk

    return {
        "ok": True, "ticker": ticker, "cluster_date": cdate, "entry": round(entry, 2),
        "n_insiders": cluster["n_insiders"], "total_value": cluster["total_value"],
        "fwd": fwd, "trade_ret": round(trade_ret, 2), "exit_reason": exit_reason,
        "days_held": days_held, "r_multiple": round(r_multiple, 2),
    }


# ─── 3. Run + aggregate ────────────────────────────────────────────────────────

def run(quarter: str, max_events: int = 150, min_value: float = 50_000):
    print(f"\n{'='*64}\n  INSIDER EDGE BACKTEST — {quarter}\n{'='*64}")
    clusters = build_clusters(quarter)
    # Filter: meaningful $ size
    clusters = [c for c in clusters if c["total_value"] >= min_value][:max_events]
    print(f"  Testing {len(clusters)} clusters (>= ${min_value:,.0f} value)\n")

    results = []
    for i, c in enumerate(clusters):
        r = simulate(c)
        if r.get("ok"):
            results.append(r)
        if (i + 1) % 10 == 0:
            print(f"  ...simulated {i+1}/{len(clusters)} ({len(results)} valid)")
        time.sleep(0.15)  # be gentle on Alpaca

    if not results:
        print("  No valid results.")
        return

    n = len(results)
    print(f"\n{'='*64}\n  RESULTS ({n} tradeable clusters)\n{'='*64}")

    # Event study
    print("\n  EVENT STUDY — avg forward return (raw / vs SPY):")
    for h in HORIZONS:
        rets = [r["fwd"].get(h) for r in results if r["fwd"].get(h) is not None]
        excess = [r["fwd"].get(f"{h}_vs_spy") for r in results if r["fwd"].get(f"{h}_vs_spy") is not None]
        if rets:
            avg = sum(rets)/len(rets)
            win = sum(1 for x in rets if x > 0)/len(rets)*100
            ex = sum(excess)/len(excess) if excess else 0
            print(f"    +{h:>2}d:  {avg:+6.2f}% raw   {ex:+6.2f}% vs SPY   {win:4.0f}% positive")

    # Tradeable rule
    trade_rets = [r["trade_ret"] for r in results]
    r_mults = [r["r_multiple"] for r in results]
    wins = [x for x in trade_rets if x > 0]
    win_rate = len(wins)/n*100
    avg_r = sum(r_mults)/n
    expectancy = sum(trade_rets)/n
    exits = defaultdict(int)
    for r in results: exits[r["exit_reason"]] += 1

    print(f"\n  TRADEABLE RULE (stop -{STOP_PCT*100:.0f}% / target +{TARGET_PCT*100:.0f}% / {MAX_HOLD_DAYS}d):")
    print(f"    Win rate    : {win_rate:.1f}%")
    print(f"    Avg return  : {expectancy:+.2f}% per trade")
    print(f"    Avg R       : {avg_r:+.2f}R")
    print(f"    Exits       : {dict(exits)}")

    # Naive equal-weight portfolio return vs SPY (rough)
    print(f"\n  VERDICT:")
    h = 20
    excess = [r['fwd'].get(f'{h}_vs_spy') for r in results if r['fwd'].get(f'{h}_vs_spy') is not None]
    if excess:
        avg_excess = sum(excess)/len(excess)
        pos = sum(1 for x in excess if x > 0)/len(excess)*100
        if avg_excess > 1 and pos > 52:
            print(f"    ✅ EDGE DETECTED: +{avg_excess:.2f}% avg excess vs SPY at {h}d, {pos:.0f}% beat SPY")
            print(f"       Signal appears to have predictive power. Worth live validation.")
        elif avg_excess > 0:
            print(f"    🟡 WEAK/INCONCLUSIVE: +{avg_excess:.2f}% excess, {pos:.0f}% beat SPY (n={len(excess)})")
            print(f"       Marginal. Need more data / refined filters.")
        else:
            print(f"    ❌ NO EDGE: {avg_excess:+.2f}% excess vs SPY. Signal does not predict outperformance.")
            print(f"       Retire this thesis — it's noise.")

    # Save
    try:
        from database import get_connection
        conn = get_connection()
        conn.execute("""CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, quarter TEXT, n_clusters INTEGER,
            win_rate REAL, avg_r REAL, expectancy REAL, avg_excess_20d REAL,
            created_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("INSERT INTO backtest_runs (quarter,n_clusters,win_rate,avg_r,expectancy,avg_excess_20d) VALUES (?,?,?,?,?,?)",
                     (quarter, n, round(win_rate,1), round(avg_r,2), round(expectancy,2),
                      round(sum(excess)/len(excess),2) if excess else 0))
        conn.commit(); conn.close()
        print(f"\n  Saved to backtest_runs table.")
    except Exception as e:
        print(f"  Save skipped: {e}")
    print(f"{'='*64}\n")


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "2026q1"
    max_ev = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    run(q, max_events=max_ev)
