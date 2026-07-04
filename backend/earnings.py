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
CACHE_TTL = 6 * 3600          # AV: refresh at most every 6h (respect 25/day limit)


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
        })

    out.sort(key=lambda x: (x["date"], x["ticker"]))
    mine = [x for x in out if x["in_watchlist"] or x["held"]]
    return {
        "days": days,
        "count": len(out),
        "mine": mine,                # your watchlist + holdings, earnings soon
        "all": out,
        "source": "alphavantage" + ("+benzinga" if bz else ""),
        "as_of": datetime.now().isoformat(timespec="minutes"),
    }
