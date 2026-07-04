"""
Point-in-time decision snapshots (Phase 0 — ground truth).

Every time the pipeline reaches a real decision, we freeze the exact inputs it
saw (event, price, the scout/research/trader outputs) with a UTC timestamp.
This is what makes decisions *replayable* and backtests *look-ahead-safe*: you
can later ask "given only what was knowable at 14:32, what did/should the agents
do?" without leaking the future.

One row per decision. Linked to the pending_trade / position it produced so the
outcome can be joined back for validation (see replay.py).
"""

import json
import time
from database import get_connection


def ensure_table():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS decision_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc REAL NOT NULL,
            event_id INTEGER,
            ticker TEXT,
            action TEXT,                 -- final_action from the pipeline
            price_at_decision REAL,
            scout_json TEXT,
            research_json TEXT,
            trader_json TEXT,
            rr_computed REAL,
            confidence INTEGER,
            pending_trade_id INTEGER,
            position_id INTEGER,
            prompt_version TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_snap_ticker ON decision_snapshots(ticker);
        CREATE INDEX IF NOT EXISTS idx_snap_ts ON decision_snapshots(ts_utc);
    """)
    conn.commit()
    conn.close()


def _dump(x):
    try:
        return json.dumps(x, default=str)[:8000]
    except Exception:
        return None


def capture(event: dict, pipeline_result: dict, prompt_version: str = "v1") -> int:
    """Freeze a decision. Safe to call on every pipeline run; returns snapshot id
    (or 0 on failure — never raises into the pipeline)."""
    try:
        ensure_table()
        stages = pipeline_result.get("stages", {})
        research = stages.get("research", {}) or {}
        trader = stages.get("trader", {}) or {}
        conn = get_connection()
        cur = conn.execute(
            """INSERT INTO decision_snapshots
               (ts_utc, event_id, ticker, action, price_at_decision,
                scout_json, research_json, trader_json, rr_computed, confidence,
                pending_trade_id, position_id, prompt_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.time(),
                event.get("event_id"),
                research.get("ticker") or (event.get("tickers") or [None])[0],
                pipeline_result.get("final_action"),
                research.get("entry"),
                _dump(stages.get("scout")),
                _dump(research),
                _dump(trader),
                research.get("rr_computed"),
                trader.get("confidence"),
                pipeline_result.get("pending_trade_id"),
                None,
                prompt_version,
            ),
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid
    except Exception as e:
        print(f"[Snapshots] capture failed: {str(e)[:120]}")
        return 0


def recent(limit: int = 50) -> list:
    ensure_table()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM decision_snapshots ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
