"""
Paper Trader — auto-executes agent BUY decisions against a simulated paper account.

In AUTO_PAPER mode:
- When Trader says BUY (or Auto-Scanner finds a HIGH conviction setup),
  a position is opened immediately using the live Alpaca price as the fill.
- The existing Monitor agent manages exits (trim/stop/target/thesis).
- The existing Journal agent learns from every close.

This creates a closed feedback loop that runs autonomously for days/weeks,
building the `learnings` table that feeds back into Scout + Research.

A "paper session" tracks the experiment: start time, starting capital, config.
"""

import json
from datetime import datetime
from database import get_connection
from alpaca_data import get_snapshot
from event_bus import publish, log_agent_run


# ─── Session management ──────────────────────────────────────────────────────

def init_paper_tables():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT DEFAULT (datetime('now')),
            ended_at TEXT,
            starting_capital REAL,
            status TEXT DEFAULT 'active',
            mode TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS paper_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            equity REAL,
            total_pnl REAL,
            realized_pnl REAL,
            unrealized_pnl REAL,
            open_count INTEGER,
            closed_count INTEGER,
            win_rate REAL,
            patterns_learned INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


async def record_snapshot():
    """Append a point to the equity curve. Called hourly during market hours."""
    sess = get_active_session()
    if not sess:
        return
    rep = session_report()
    conn = get_connection()
    conn.execute("""
        INSERT INTO paper_snapshots (session_id, equity, total_pnl, realized_pnl,
            unrealized_pnl, open_count, closed_count, win_rate, patterns_learned)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sess["id"], rep["current_equity"], rep["total_pnl"], rep["realized_pnl"],
        rep["unrealized_pnl"], rep["open_count"], rep["closed_count"],
        rep["win_rate"], rep["patterns_learned"]
    ))
    conn.commit()
    conn.close()


def get_snapshots(limit: int = 200) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM paper_snapshots ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


import asyncio as _asyncio
_snapshot_running = False
_snapshot_task = None

async def _snapshot_loop(interval_sec: int = 3600):
    global _snapshot_running
    _snapshot_running = True
    while _snapshot_running:
        try:
            if get_active_session():
                await record_snapshot()
        except Exception as e:
            print(f"[PaperTrader] Snapshot error: {e}")
        await _asyncio.sleep(interval_sec)

def start_snapshots(interval_sec: int = 3600):
    global _snapshot_task
    loop = _asyncio.get_event_loop()
    _snapshot_task = loop.create_task(_snapshot_loop(interval_sec))
    return _snapshot_task

def stop_snapshots():
    global _snapshot_running, _snapshot_task
    _snapshot_running = False
    if _snapshot_task:
        _snapshot_task.cancel()


def start_session(starting_capital: float = 25000, notes: str = "") -> int:
    init_paper_tables()
    conn = get_connection()
    # Close any existing active session
    conn.execute("UPDATE paper_sessions SET status='ended', ended_at=datetime('now') WHERE status='active'")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO paper_sessions (starting_capital, status, mode, notes) VALUES (?, 'active', 'AUTO_PAPER', ?)",
        (starting_capital, notes)
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_active_session() -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM paper_sessions WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def end_session():
    conn = get_connection()
    conn.execute("UPDATE paper_sessions SET status='ended', ended_at=datetime('now') WHERE status='active'")
    conn.commit()
    conn.close()


# ─── Paper execution ─────────────────────────────────────────────────────────

def _open_positions_count() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    conn.close()
    return n


def _already_holding(ticker: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM positions WHERE ticker=? AND status='OPEN' LIMIT 1", (ticker.upper(),)
    ).fetchone()
    conn.close()
    return bool(row)


async def execute_paper_trade(ticker: str, direction: str, entry: float, stop: float,
                              target1: float, target2: float, shares: int,
                              thesis: str = "", confidence: int = 0,
                              source: str = "agent", max_positions: int = 5,
                              strategy_tag: str = "momentum") -> dict:
    """
    Open a paper position using the live Alpaca price as the fill.
    Tagged with strategy_tag for the A/B comparison.
    Returns the created position info or a skip reason.
    """
    ticker = ticker.upper()

    # Guard rails (mirror Risk agent hard rules)
    if _already_holding(ticker):
        return {"executed": False, "reason": f"Already holding {ticker}"}

    # Per-strategy capacity check (each strategy has its own pool)
    try:
        import strategies
        ok, reason = strategies.can_open(strategy_tag)
        if not ok:
            return {"executed": False, "reason": reason, "strategy": strategy_tag}
    except Exception:
        if _open_positions_count() >= max_positions:
            return {"executed": False, "reason": f"At max positions ({max_positions})"}

    # Get live fill price
    snap = get_snapshot(ticker)
    fill = snap.get("price") or entry
    if not fill:
        return {"executed": False, "reason": "No live price for fill"}

    if not shares or shares <= 0:
        shares = 1

    # ── Circuit breaker check ───────────────────────────────────────
    import risk_guard
    guard = risk_guard.check()
    if not guard["allowed"]:
        await publish(
            source="risk_guard", type="trade_blocked",
            data={"ticker": ticker, "reason": guard["reason"], "metrics": guard["metrics"]},
            title=f"🛑 BLOCKED {ticker}: {guard['reason']}",
            impact="HIGH", tickers=[ticker],
        )
        return {"executed": False, "reason": f"Circuit breaker: {guard['reason']}", "guard": guard}

    # Capital guard — per-strategy pool (each strategy gets equal, separate capital).
    try:
        import strategies
        scfg = strategies.get_strategy(strategy_tag)
        start_cap = scfg["capital"]
        cash_avail = strategies.cash_available(strategy_tag)
    except Exception:
        sess = get_active_session()
        start_cap = sess["starting_capital"] if sess else 25000
        cash_avail = start_cap
    max_position_value = min(cash_avail, start_cap * 0.40)
    if fill * shares > max_position_value:
        shares = int(max_position_value // fill)
    if shares <= 0:
        return {"executed": False, "reason": f"Insufficient {strategy_tag} cash (${cash_avail:.0f})"}

    # ── Place REAL paper order via Alpaca (bracket: entry + hard stop + target) ──
    broker_result = None
    try:
        import broker
        if broker.is_available():
            broker_result = broker.place_bracket_order(
                symbol=ticker, qty=shares, direction=direction,
                stop=stop, target=target1, wait_for_fill=True, timeout=12,
            )
            if broker_result.get("ok") and broker_result.get("fill_price"):
                fill = broker_result["fill_price"]   # use REAL fill price
            elif broker_result.get("ok"):
                pass  # order placed but not yet filled (pending) — use snapshot as estimate
            else:
                # Broker rejected — log and fall back to simulated fill
                print(f"[PaperTrader] Broker rejected {ticker}: {broker_result.get('reason')}")
    except Exception as e:
        print(f"[PaperTrader] Broker error for {ticker}: {e}")

    # Order metadata for notes
    if broker_result and broker_result.get("ok"):
        order_id = broker_result.get("order_id", "")
        bracket = broker_result.get("bracket", True) is not False
        fill_note = f"[REAL Alpaca paper fill @ ${fill:.2f} · order {order_id[:8]} · {'bracket' if bracket else 'market'}]"
    else:
        fill_note = f"[SIM fill @ ${fill:.2f} · broker unavailable]"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO positions (ticker, direction, entry_price, quantity,
            stop_loss, target1, target2, strategy, strategy_tag, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
    """, (
        ticker, direction, round(fill, 2), shares,
        stop, target1, target2,
        f"AI Paper ({source})", strategy_tag,
        f"[{strategy_tag}] {fill_note} conf={confidence}/10. {thesis[:360]}",
    ))
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    # Track for circuit breaker (over-trading guard)
    risk_guard.record_trade_opened()

    position_value = round(fill * shares, 2)

    await publish(
        source="paper_trader",
        type="paper_position_opened",
        data={
            "position_id": pid, "ticker": ticker, "direction": direction,
            "fill_price": round(fill, 2), "shares": shares,
            "stop": stop, "target1": target1, "target2": target2,
            "position_value": position_value, "confidence": confidence,
        },
        title=f"📝 PAPER OPEN: {direction} {shares} {ticker} @ ${fill:.2f} (conf {confidence}/10)",
        impact="HIGH",
        tickers=[ticker],
    )

    log_agent_run(
        event_id=None, agent="paper_trader", model="execution",
        input={"ticker": ticker, "direction": direction, "intended_entry": entry, "source": source},
        output={"executed": True, "position_id": pid, "fill": round(fill, 2), "shares": shares},
    )

    return {
        "executed": True, "position_id": pid, "ticker": ticker,
        "fill_price": round(fill, 2), "shares": shares, "position_value": position_value,
    }


# ─── Reporting ───────────────────────────────────────────────────────────────

def session_report() -> dict:
    """Full snapshot of the current paper session's performance."""
    sess = get_active_session()
    conn = get_connection()

    # Open positions with live P&L
    open_rows = conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()
    open_positions = []
    open_pnl = 0.0
    for r in open_rows:
        p = dict(r)
        snap = get_snapshot(p["ticker"])
        cur_price = snap.get("price") or p["entry_price"]
        mult = 1 if p["direction"] == "LONG" else -1
        upnl = (cur_price - p["entry_price"]) * p["quantity"] * mult
        open_pnl += upnl
        open_positions.append({
            "ticker": p["ticker"], "direction": p["direction"],
            "entry": p["entry_price"], "current": round(cur_price, 2),
            "shares": p["quantity"], "unrealized_pnl": round(upnl, 2),
        })

    # Closed (paper) trades
    closed = conn.execute(
        "SELECT ticker, direction, entry_price, exit_price, pnl, exit_date FROM positions "
        "WHERE status='CLOSED' AND strategy LIKE 'AI Paper%' ORDER BY id DESC"
    ).fetchall()
    closed = [dict(r) for r in closed]
    realized = sum(c["pnl"] or 0 for c in closed)
    wins = [c for c in closed if (c["pnl"] or 0) > 0]
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0

    # Journal/learning stats
    total_journaled = conn.execute("SELECT COUNT(*) FROM trade_journal").fetchone()[0]
    patterns = conn.execute(
        "SELECT pattern, sample_size, win_rate, avg_r, recommendation FROM learnings "
        "ORDER BY sample_size DESC LIMIT 15"
    ).fetchall()
    conn.close()

    start_cap = sess["starting_capital"] if sess else 25000
    total_pnl = realized + open_pnl
    return {
        "session": sess,
        "starting_capital": start_cap,
        "current_equity": round(start_cap + total_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_pnl / start_cap * 100, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(open_pnl, 2),
        "open_positions": open_positions,
        "open_count": len(open_positions),
        "closed_count": len(closed),
        "win_rate": win_rate,
        "patterns_learned": total_journaled,
        "top_patterns": [dict(p) for p in patterns],
    }
