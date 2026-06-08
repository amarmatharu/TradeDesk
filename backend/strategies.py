"""
Strategy Registry — run multiple strategies head-to-head on equal capital.

Each strategy:
- has its own capital pool (equal footing for fair comparison)
- is fed by specific signal sources
- applies its own universe filter
- tags every trade it generates → performance tracked separately

Strategy A "momentum"     : the original system — news-reaction on liquid names
Strategy B "insider_edge" : the re-aim — cluster insider buys on under-covered small caps

Both share the same engine (agents, monitor, journal, breakers, broker).
A comparison report shows them vs each other AND vs SPY buy-and-hold.
"""

from database import get_connection

# ─── Registry ─────────────────────────────────────────────────────────────────

STRATEGIES = {
    "momentum": {
        "name": "Momentum / News",
        "description": "News-reaction on liquid large/mid caps (original system)",
        "capital": 25000,
        "sources": ["benzinga", "auto_scanner"],   # what events feed it
        "universe": "liquid",                        # any cap, liquid
        "max_positions": 5,
        "enabled": True,
    },
    "insider_edge": {
        "name": "Insider Edge",
        "description": "Cluster insider buys on under-covered small/micro caps + deep 10-Q read",
        "capital": 25000,
        "sources": ["edgar_cluster"],                # fed by Form 4 cluster events
        "universe": "smallcap",                       # $50M-$2B, liquid enough
        "max_positions": 5,
        "enabled": True,
    },
}


def get_strategy(strategy_id: str) -> dict:
    return STRATEGIES.get(strategy_id, STRATEGIES["momentum"])


def resolve_strategy(event: dict) -> str:
    """Decide which strategy an event belongs to, based on its source/type."""
    src = event.get("source", "")
    typ = event.get("type", "")
    # Insider cluster events → insider_edge
    if typ == "insider_cluster" or src == "edgar_cluster":
        return "insider_edge"
    # Plain Form 4 (single) and 8-K → momentum can still use them, but
    # we route news + scanner to momentum
    if src in ("benzinga", "auto_scanner"):
        return "momentum"
    # EDGAR 8-K material events → momentum (catalyst-driven)
    if typ == "edgar_8k":
        return "momentum"
    # Default
    return "momentum"


# ─── Per-strategy capital tracking ─────────────────────────────────────────────

def deployed_capital(strategy_id: str) -> float:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(entry_price * quantity), 0) FROM positions "
        "WHERE status='OPEN' AND strategy_tag=?", (strategy_id,)
    ).fetchone()
    conn.close()
    return float(row[0]) if row else 0.0


def open_count(strategy_id: str) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status='OPEN' AND strategy_tag=?",
        (strategy_id,)
    ).fetchone()[0]
    conn.close()
    return n


def cash_available(strategy_id: str) -> float:
    cfg = get_strategy(strategy_id)
    return cfg["capital"] - deployed_capital(strategy_id)


def can_open(strategy_id: str) -> tuple:
    """Returns (allowed, reason)."""
    cfg = get_strategy(strategy_id)
    if not cfg.get("enabled"):
        return False, f"Strategy {strategy_id} disabled"
    if open_count(strategy_id) >= cfg["max_positions"]:
        return False, f"{strategy_id} at max positions ({cfg['max_positions']})"
    if cash_available(strategy_id) <= 0:
        return False, f"{strategy_id} out of capital"
    return True, "ok"


# ─── Comparison report ─────────────────────────────────────────────────────────

def compare() -> dict:
    """Head-to-head performance per strategy + SPY benchmark."""
    from alpaca_data import get_snapshot
    conn = get_connection()
    out = {}

    for sid, cfg in STRATEGIES.items():
        # Open positions
        open_rows = conn.execute(
            "SELECT * FROM positions WHERE status='OPEN' AND strategy_tag=?", (sid,)
        ).fetchall()
        upnl = 0.0
        for r in open_rows:
            p = dict(r)
            snap = get_snapshot(p["ticker"])
            cur = snap.get("price") or p["entry_price"]
            mult = 1 if p["direction"] == "LONG" else -1
            upnl += (cur - p["entry_price"]) * p["quantity"] * mult

        # Closed
        closed = conn.execute(
            "SELECT pnl FROM positions WHERE status='CLOSED' AND strategy_tag=?", (sid,)
        ).fetchall()
        closed_pnls = [c["pnl"] or 0 for c in closed]
        realized = sum(closed_pnls)
        wins = [p for p in closed_pnls if p > 0]
        win_rate = round(len(wins) / len(closed_pnls) * 100, 1) if closed_pnls else 0
        total_pnl = realized + upnl
        cap = cfg["capital"]

        out[sid] = {
            "name": cfg["name"],
            "description": cfg["description"],
            "enabled": cfg["enabled"],
            "capital": cap,
            "equity": round(cap + total_pnl, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round(total_pnl / cap * 100, 2),
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(upnl, 2),
            "open_positions": len(open_rows),
            "closed_trades": len(closed_pnls),
            "win_rate": win_rate,
        }
    conn.close()

    # SPY benchmark over the session window
    out["_benchmark"] = _spy_benchmark()
    return out


def _spy_benchmark() -> dict:
    """SPY buy-and-hold return since the paper session started."""
    try:
        import paper_trader
        from alpaca_data import get_ohlcv, get_snapshot
        sess = paper_trader.get_active_session()
        if not sess:
            return {}
        start_date = sess["started_at"][:10]
        bars = get_ohlcv("SPY", "1mo", "1d")
        if not bars:
            return {}
        # First bar on/after session start
        import datetime as _dt
        start_ts = _dt.datetime.fromisoformat(start_date).timestamp()
        start_bar = next((b for b in bars if b["time"] >= start_ts), bars[0])
        snap = get_snapshot("SPY")
        now = snap.get("price") or bars[-1]["close"]
        ret = (now - start_bar["close"]) / start_bar["close"] * 100
        return {
            "name": "SPY buy & hold",
            "start_price": round(start_bar["close"], 2),
            "current_price": round(now, 2),
            "return_pct": round(ret, 2),
        }
    except Exception as e:
        return {"error": str(e)}
