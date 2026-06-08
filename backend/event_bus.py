"""
Central Event Bus for TradeDesk multi-agent system.

All feeds (Benzinga, EDGAR, manual) publish events here.
All agents subscribe to relevant events.
Decisions and outputs are persisted to SQLite.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Optional, Callable, List
from database import get_connection


# ─── Event bus state ─────────────────────────────────────────────────────────

_subscribers: List[asyncio.Queue] = []   # downstream consumers (UI streams)
_agent_handlers: List[Callable] = []     # agent triggers


# ─── Publish / Subscribe ─────────────────────────────────────────────────────

async def publish(source: str, type: str, data: dict, tickers: list = None,
                  title: str = "", impact: str = "MEDIUM") -> int:
    """
    Publish an event to the bus.
    Persists to DB and broadcasts to all subscribers + agent handlers.
    Returns event_id.
    """
    # Persist
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO events (source, type, tickers, title, impact, data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        source, type,
        ",".join(tickers) if tickers else "",
        title[:500] if title else "",
        impact,
        json.dumps(data, default=str)[:50000],
    ))
    event_id = cur.lastrowid
    conn.commit()
    conn.close()

    event = {
        "event_id": event_id,
        "source": source,
        "type": type,
        "tickers": tickers or [],
        "title": title,
        "impact": impact,
        "data": data,
        "ts": time.time(),
    }

    # Broadcast to UI subscribers
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)

    # Trigger agent handlers (async, fire-and-forget)
    for handler in _agent_handlers:
        asyncio.create_task(_safe_handle(handler, event))

    return event_id


async def _safe_handle(handler: Callable, event: dict):
    try:
        await handler(event)
    except Exception as e:
        print(f"[EventBus] Handler {handler.__name__} error: {e}")


def subscribe() -> asyncio.Queue:
    """Subscribe to all bus events (for UI streaming)."""
    q = asyncio.Queue(maxsize=200)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    if q in _subscribers:
        _subscribers.remove(q)


def register_agent_handler(handler: Callable):
    """Register a function to be called on every published event."""
    _agent_handlers.append(handler)


# ─── Persistence helpers ────────────────────────────────────────────────────

def log_agent_run(event_id: int, agent: str, model: str, input: dict, output: dict,
                  duration_ms: int = 0, tokens_in: int = 0, tokens_out: int = 0,
                  cost_usd: float = 0, status: str = "success", error: str = "") -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO agent_runs (event_id, agent, model, input, output,
            duration_ms, tokens_in, tokens_out, cost_usd, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id, agent, model,
        json.dumps(input, default=str)[:10000],
        json.dumps(output, default=str)[:10000],
        duration_ms, tokens_in, tokens_out, cost_usd, status, error
    ))
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def get_recent_events(limit: int = 50) -> list:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, source, type, tickers, title, impact, data, created_at
        FROM events ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [{
        "event_id": r["id"], "source": r["source"], "type": r["type"],
        "tickers": r["tickers"].split(",") if r["tickers"] else [],
        "title": r["title"], "impact": r["impact"],
        "data": json.loads(r["data"]) if r["data"] else {},
        "created_at": r["created_at"],
    } for r in rows]


def get_agent_runs(limit: int = 100, agent: str = None, event_id: int = None) -> list:
    conn = get_connection()
    q = "SELECT * FROM agent_runs WHERE 1=1"
    params = []
    if agent:
        q += " AND agent = ?"
        params.append(agent)
    if event_id:
        q += " AND event_id = ?"
        params.append(event_id)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [{
        **dict(r),
        "input": json.loads(r["input"]) if r["input"] else {},
        "output": json.loads(r["output"]) if r["output"] else {},
    } for r in rows]
