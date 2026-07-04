"""
Upcoming earnings calendar.

Real forward earnings dates (yfinance is blocked in this environment). Primary
source: Alpha Vantage EARNINGS_CALENDAR (free, ~6000 names, 3-month horizon) —
cached hard because AV free tier allows only ~25 calls/day. Time-of-day (BMO/AMC)
enriched from Benzinga for the names you actually care about (watchlist + holdings).

Rows are flagged so the UI can surface YOUR tickers (watchlist + current broker
positions) first.
"""

import os
import csv
import io
import json
import time
import urllib.request
from datetime import datetime, timedelta

_CACHE = {"ts": 0, "rows": None}
_BZ_CACHE = {"ts": 0, "map": {}}
_TR_CACHE = {}                # ticker -> (ts, record)
CACHE_TTL = 6 * 3600          # AV: refresh at most every 6h (respect 25/day limit)

# Curated large/mega-cap universe for the "large-cap only" noise filter.
LARGE_CAP = set("""
AAPL MSFT NVDA AMZN GOOGL GOOG META TSLA AVGO BRK.B LLY JPM V UNH XOM MA JNJ PG COST HD
ABBV MRK CVX WMT KO PEP BAC ADBE CRM NFLX AMD TMO ACN LIN MCD ABT ORCL CSCO DIS WFC
INTC QCOM TXN DHR VZ CMCSA PM NKE INTU AMGN NEE RTX HON UNP LOW SPGI IBM GE CAT BA
UPS BKNG NOW GS MS AXP BLK C SCHW T PFE BMY GILD CVS MDT ISRG AMAT MU ADI LRCX KLAC
DE MMM EMR ETN ITW GD LMT NOC SLB EOG COP MPC PSX OXY VLO WMB KMI TGT SBUX CMG BKNG
PYPL SQ SHOP UBER ABNB PLTR SNOW CRWD PANW NET DDOG ZS MRNA REGN VRTX TMUS CL KHC MDLZ
MO SO DUK PLD AMT CCI EQIX PSA SPG O DOW DD PPG SHW FCX NEM NUE APD ECL PH ROK PCAR
F GM PYPL WFC USB PNC TFC COF SYK BDX BSX ZTS HCA CI ELV HUM GEHC IDXX A DXCM
V MA FIS FISV GPN AON MMC PGR TRV ALL AFL MET PRU CB
""".split())


def is_large_cap(t):
    return t.upper() in LARGE_CAP


def _av_calendar():
    if _CACHE["rows"] is not None and time.time() - _CACHE["ts"] < CACHE_TTL:
        return _CACHE["rows"]
    key = os.environ.get("ALPHA_VANTAGE_KEY", "")
    if not key:
        return []
    try:
        url = f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey={key}"
        txt = urllib.request.urlopen(url, timeout=40).read().decode()
        if txt.strip().startswith("{"):
            return _CACHE["rows"] or []       # rate-limited note → keep old cache
        rows = list(csv.DictReader(io.StringIO(txt)))
        _CACHE["rows"], _CACHE["ts"] = rows, time.time()
        return rows
    except Exception:
        return _CACHE["rows"] or []


def _benzinga_times(date_from, date_to):
    """ticker -> time-of-day (BMO/AMC/HH:MM) + eps_est from Benzinga, cached 3h."""
    if _BZ_CACHE["map"] and time.time() - _BZ_CACHE["ts"] < 3 * 3600:
        return _BZ_CACHE["map"]
    tok = os.environ.get("BENZINGA_API_KEY", "")
    if not tok:
        return {}
    out = {}
    try:
        url = (f"https://api.benzinga.com/api/v2.1/calendar/earnings?token={tok}"
               f"&parameters[date_from]={date_from}&parameters[date_to]={date_to}&pagesize=1000")
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        for e in d.get("earnings", []):
            t = (e.get("time") or "")
            when = "BMO" if t and t < "09:30:00" else "AMC" if t else ""
            out[(e.get("ticker", "").upper(), e.get("date", ""))] = {
                "when": when, "time": t, "eps_est": e.get("eps_est")}
        _BZ_CACHE["map"], _BZ_CACHE["ts"] = out, time.time()
    except Exception:
        pass
    return out


_EARN_CACHE = {}              # ticker -> (ts, quarterlyEarnings list)
_PRICE_CACHE = {}            # ticker -> (ts, (dates, closes))


def _av_earnings(ticker: str):
    """Full quarterly earnings history from AV (dates + surprises). Cached 24h."""
    tk = ticker.upper()
    c = _EARN_CACHE.get(tk)
    if c and time.time() - c[0] < 24 * 3600:
        return c[1]
    key = os.environ.get("ALPHA_VANTAGE_KEY", "")
    q = []
    if key:
        try:
            url = f"https://www.alphavantage.co/query?function=EARNINGS&symbol={tk}&apikey={key}"
            d = json.loads(urllib.request.urlopen(url, timeout=30).read().decode())
            q = d.get("quarterlyEarnings", []) or []
        except Exception:
            q = _EARN_CACHE.get(tk, (0, []))[1]
    _EARN_CACHE[tk] = (time.time(), q)
    return q


def _daily_closes(ticker: str):
    """Tiingo daily closes -> (dates_list, closes_array). Cached 24h."""
    import numpy as np
    tk = ticker.upper()
    c = _PRICE_CACHE.get(tk)
    if c and time.time() - c[0] < 24 * 3600:
        return c[1]
    key = os.environ.get("TIINGO_KEY", "")
    out = ([], np.array([]))
    if key:
        try:
            url = (f"https://api.tiingo.com/tiingo/daily/{tk}/prices?startDate=2016-01-01"
                   f"&token={key}&format=json&resampleFreq=daily")
            req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
            d = json.loads(urllib.request.urlopen(req, timeout=40).read().decode())
            out = ([r["date"][:10] for r in d], np.array([r["adjClose"] for r in d], float))
        except Exception:
            out = _PRICE_CACHE.get(tk, (0, out))[1]
    _PRICE_CACHE[tk] = (time.time(), out)
    return out


def get_track_record(ticker: str) -> dict:
    """Beat/miss history (last 8 quarters). Only for YOUR tickers (AV-limit safe)."""
    tk = ticker.upper()
    c = _TR_CACHE.get(tk)
    if c and time.time() - c[0] < 24 * 3600:
        return c[1]
    q = _av_earnings(tk)[:8]
    surprises, beats = [], 0
    for e in q:
        try:
            sp = float(e.get("surprisePercentage"))
            surprises.append(sp)
            beats += sp > 0
        except (TypeError, ValueError):
            continue
    rec = {"beats": beats, "of": len(surprises),
           "avg_surprise_pct": round(sum(surprises) / len(surprises), 1)} if surprises else {}
    _TR_CACHE[tk] = (time.time(), rec)
    return rec


def get_expected_move(ticker: str) -> dict:
    """How much the stock TYPICALLY moves around earnings (historical reaction).
    This is RISK, not a direction prediction: the median absolute move from the
    close before each of the last ~8 reports to the close 2 days later."""
    import numpy as np
    q = _av_earnings(ticker)[:8]
    dates, closes = _daily_closes(ticker)
    if not q or len(closes) < 60:
        return {}
    didx = {d: i for i, d in enumerate(dates)}
    sorted_dates = dates  # already ascending
    moves = []
    for e in q:
        rd = (e.get("reportedDate") or "")[:10]
        if not rd:
            continue
        # index of last trading day strictly before the report
        i0 = None
        for i in range(len(sorted_dates) - 1, -1, -1):
            if sorted_dates[i] < rd:
                i0 = i
                break
        if i0 is None or i0 + 2 >= len(closes):
            continue
        moves.append(abs(closes[i0 + 2] / closes[i0] - 1.0))   # 2-day reaction window
    if len(moves) < 3:
        return {}
    m = np.array(moves)
    return {
        "typical_move_pct": round(float(np.median(m)) * 100, 1),
        "biggest_move_pct": round(float(np.max(m)) * 100, 1),
        "smallest_move_pct": round(float(np.min(m)) * 100, 1),
        "n": len(moves),
    }


def _my_tickers():
    watch, held = set(), set()
    try:
        from database import get_connection
        conn = get_connection()
        watch = {r["ticker"].upper() for r in conn.execute("SELECT ticker FROM watchlist").fetchall()}
        conn.close()
    except Exception:
        pass
    try:
        import broker
        held = {p["ticker"].upper() for p in broker.get_positions()}
    except Exception:
        pass
    return watch, held


def get_upcoming(days: int = 14) -> dict:
    rows = _av_calendar()
    today = datetime.now().date()
    horizon = today + timedelta(days=days)
    watch, held = _my_tickers()
    bz = _benzinga_times(today.isoformat(), horizon.isoformat())

    out = []
    for r in rows:
        try:
            d = datetime.strptime(r.get("reportDate", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (today <= d <= horizon):
            continue
        tk = (r.get("symbol") or "").upper()
        b = bz.get((tk, r.get("reportDate")), {})
        out.append({
            "ticker": tk,
            "company": r.get("name", ""),
            "date": r.get("reportDate"),
            "days_until": (d - today).days,
            "eps_estimate": r.get("estimate") or b.get("eps_est"),
            "when": b.get("when", ""),          # BMO / AMC
            "fiscal_end": r.get("fiscalDateEnding"),
            "in_watchlist": tk in watch,
            "held": tk in held,
            "large_cap": is_large_cap(tk),
        })

    out.sort(key=lambda x: (x["date"], x["ticker"]))
    mine = [x for x in out if x["in_watchlist"] or x["held"]]
    # For YOUR tickers only (AV rate-limit friendly): beat/miss record + expected move
    for x in mine:
        tr = get_track_record(x["ticker"])
        if tr:
            x["track_record"] = tr
        em = get_expected_move(x["ticker"])
        if em:
            x["expected_move"] = em
    return {
        "days": days,
        "count": len(out),
        "mine": mine,                # your watchlist + holdings, earnings soon
        "all": out,
        "source": "alphavantage" + ("+benzinga" if bz else ""),
        "as_of": datetime.now().isoformat(timespec="minutes"),
    }
