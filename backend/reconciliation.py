"""
Reconciliation service (Phase 0 — ground truth).

The internal ledger (`positions` table / paper_trader) and the actual broker
account can silently drift — partial fills, manual trades, missed exits. A
professional desk treats the broker as the source of truth and reconciles
continuously. This module diffs the two and flags every discrepancy.

Read-only. Never mutates positions or places orders.
"""

import broker
from database import get_connection

# How much share-count difference to tolerate before flagging (fractional shares).
QTY_TOLERANCE = 0.01


def _ledger_positions():
    """Open positions per the internal ledger, keyed by ticker (net qty)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT ticker, direction, quantity FROM positions WHERE status='OPEN'"
    ).fetchall()
    conn.close()
    agg = {}
    for r in rows:
        d = dict(r)
        signed = d["quantity"] * (1 if d["direction"] == "LONG" else -1)
        agg[d["ticker"]] = agg.get(d["ticker"], 0.0) + signed
    return agg


def _broker_positions():
    """Open positions per the active broker, keyed by ticker (net qty)."""
    out = {}
    try:
        for p in broker.get_positions():
            out[p["ticker"]] = out.get(p["ticker"], 0.0) + float(p.get("qty", 0))
    except Exception as e:
        return None, str(e)
    return out, None


def reconcile() -> dict:
    """Compare ledger vs broker. Returns a structured diff + a clean/dirty flag."""
    ledger = _ledger_positions()
    bpos, err = _broker_positions()
    if bpos is None:
        return {"ok": False, "reason": f"Broker read failed: {err}",
                "broker": broker.active_broker_name()}

    tickers = set(ledger) | set(bpos)
    matched, mismatched, ledger_only, broker_only = [], [], [], []

    for t in sorted(tickers):
        lq = ledger.get(t, 0.0)
        bq = bpos.get(t, 0.0)
        diff = round(bq - lq, 4)
        row = {"ticker": t, "ledger_qty": round(lq, 4), "broker_qty": round(bq, 4), "diff": diff}
        if t not in bpos:
            ledger_only.append(row)      # ledger thinks we hold it; broker doesn't
        elif t not in ledger:
            broker_only.append(row)      # broker holds it; ledger missed it
        elif abs(diff) > QTY_TOLERANCE:
            mismatched.append(row)       # both hold it, different size
        else:
            matched.append(row)

    clean = not (mismatched or ledger_only or broker_only)
    return {
        "ok": True,
        "clean": clean,
        "broker": broker.active_broker_name(),
        "broker_env": broker.broker_env(),
        "summary": {
            "matched": len(matched),
            "mismatched": len(mismatched),
            "ledger_only": len(ledger_only),
            "broker_only": len(broker_only),
        },
        "matched": matched,
        "mismatched": mismatched,       # size disagreements
        "ledger_only": ledger_only,     # phantom ledger positions (missed exit?)
        "broker_only": broker_only,     # untracked broker positions (manual/partial?)
    }
