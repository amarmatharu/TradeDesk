"""
Monitor Agent — Watches every open position.
Runs every 60 seconds. Decides: HOLD | TRIM | EXIT.
Uses hard rules for fast decisions (stop hit, target hit).
Uses Claude for nuanced calls (thesis still valid? momentum dying?).
"""

import json
import time
import asyncio
from datetime import datetime, timedelta
from ai_brain import get_client
from event_bus import log_agent_run, publish
from database import get_connection
from alpaca_data import get_snapshot

MODEL = "claude-haiku-4-5-20251001"

# Verdicts the monitor can return
VERDICTS = ["HOLD", "TRIM_HALF", "EXIT_FULL", "EXIT_STOP", "EXIT_TARGET", "EXIT_THESIS_BROKEN", "MOVE_STOP_TO_BE"]


def get_open_positions() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status='OPEN' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_position_meta(position_id: int) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM position_meta WHERE position_id=?", (position_id,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"position_id": position_id, "t1_hit": 0, "t2_hit": 0, "be_moved": 0, "trim_count": 0}


def upsert_meta(position_id: int, **fields):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO position_meta (position_id) VALUES (?)", (position_id,))
    if fields:
        set_clause = ", ".join(f"{k}=?" for k in fields.keys())
        cur.execute(
            f"UPDATE position_meta SET {set_clause}, last_check_at=datetime('now') WHERE position_id=?",
            (*fields.values(), position_id)
        )
    else:
        cur.execute(
            "UPDATE position_meta SET last_check_at=datetime('now') WHERE position_id=?",
            (position_id,)
        )
    conn.commit()
    conn.close()


def log_check(position_id: int, ticker: str, snap: dict, verdict: str, reason: str,
              action: str, position: dict):
    conn = get_connection()
    entry = float(position.get("entry_price") or 0)
    qty = float(position.get("quantity") or 0)
    stop = float(position.get("stop_loss") or 0)
    t1 = float(position.get("target1") or 0)
    direction = position.get("direction") or "LONG"
    price = float(snap.get("price") or entry or 0)

    mult = 1 if direction == "LONG" else -1
    pnl = (price - entry) * qty * mult if entry else 0
    pnl_pct = (price - entry) / entry * 100 * mult if entry else 0
    stop_dist = (price - stop) / price * 100 * mult if stop and price else None
    t1_dist = (t1 - price) / price * 100 * mult if t1 and price else None

    conn.execute("""
        INSERT INTO position_checks (position_id, ticker, current_price,
            unrealized_pnl, unrealized_pnl_pct, stop_distance_pct, t1_distance_pct,
            verdict, reason, action_taken, data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        position_id, ticker, price,
        round(pnl, 2), round(pnl_pct, 2),
        round(stop_dist, 2) if stop_dist is not None else None,
        round(t1_dist, 2) if t1_dist is not None else None,
        verdict, reason, action, json.dumps(snap, default=str)[:2000]
    ))
    conn.commit()
    conn.close()


# ─── Hard-rule checks (no AI needed) ────────────────────────────────────────

def hard_rule_check(position: dict, snap: dict, meta: dict) -> tuple:
    """Returns (verdict, reason) if any hard rule fires, else (None, None)."""
    direction = position.get("direction", "LONG")
    entry = float(position.get("entry_price") or 0)
    stop = float(position.get("stop_loss") or 0)
    t1 = float(position.get("target1") or 0)
    t2 = float(position.get("target2") or 0)
    price = float(snap.get("price") or 0)

    if not price:
        return None, None

    # If this position has a REAL broker bracket, Alpaca enforces stop + target
    # server-side. Skip local stop/target rules to avoid double-handling —
    # reconcile_broker() will catch broker-side fills. Only run discretionary
    # rules (thesis/time-stop) below.
    broker_managed = "REAL Alpaca" in (position.get("notes") or "")

    if not broker_managed:
        if direction == "LONG":
            if stop and price <= stop:
                return "EXIT_STOP", f"Stop ${stop} hit at ${price}"
            if t2 and price >= t2 and meta.get("t1_hit"):
                return "EXIT_TARGET", f"Target 2 ${t2} hit — close all"
            if t1 and price >= t1 and not meta.get("t1_hit"):
                return "TRIM_HALF", f"Target 1 ${t1} hit — trim 50% & move stop to breakeven"
        else:  # SHORT
            if stop and price >= stop:
                return "EXIT_STOP", f"Stop ${stop} hit at ${price}"
            if t2 and price <= t2 and meta.get("t1_hit"):
                return "EXIT_TARGET", f"Target 2 ${t2} hit — close all"
            if t1 and price <= t1 and not meta.get("t1_hit"):
                return "TRIM_HALF", f"Target 1 ${t1} hit — trim 50% & move stop to breakeven"

    # Time stop — held too long without progress
    try:
        created = datetime.fromisoformat(position.get("created_at", "").replace(" ", "T"))
        days_held = (datetime.utcnow() - created).days
        mult = 1 if direction == "LONG" else -1
        pnl_pct = (price - entry) / entry * 100 * mult if entry else 0
        if days_held > 15 and pnl_pct < 1:
            return "EXIT_THESIS_BROKEN", f"Time stop: {days_held} days held with {pnl_pct:.1f}% return"
    except Exception:
        pass

    return None, None


# ─── AI-based monitor (for nuanced calls) ────────────────────────────────────

async def ai_monitor(position: dict, snap: dict, meta: dict) -> dict:
    """Claude reviews position. Asks: is thesis still valid? Should we exit early?"""
    client = get_client()
    if not client:
        return {"verdict": "HOLD", "reason": "No AI; default hold"}

    direction = position.get("direction") or "LONG"
    entry = float(position.get("entry_price") or 0)
    stop = float(position.get("stop_loss") or 0)
    t1 = float(position.get("target1") or 0)
    price = float(snap.get("price") or 0)
    qty = float(position.get("quantity") or 0)
    mult = 1 if direction == "LONG" else -1
    pnl = (price - entry) * qty * mult if entry else 0
    pnl_pct = (price - entry) / entry * 100 * mult if entry else 0
    stop_dist = (price - stop) / price * 100 * mult if stop and price else 0
    t1_dist = (t1 - price) / price * 100 * mult if t1 and price else 0
    notes = (position.get("notes") or "")[:300]
    chg_today = snap.get("change_pct") or 0

    prompt = f"""You are a Monitor Agent. Review this open position. Decide if we hold or exit early.

POSITION:
- {direction} {position.get('ticker')} @ ${entry}, qty {qty}
- Current: ${price} ({chg_today:+.2f}% today)
- P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)
- Stop: ${stop} ({stop_dist:.1f}% away)
- Target 1: ${t1} ({t1_dist:.1f}% away)
- Already T1 hit: {bool(meta.get('t1_hit'))}
- Strategy: {(position.get('strategy') or '')[:100]}
- Original thesis: {notes}

Only consider EXIT_THESIS_BROKEN if there's a clear reason the trade no longer works.
Default to HOLD unless you have high conviction the position should be closed.

Respond ONLY with JSON (no markdown):
{{
  "verdict": "HOLD" | "EXIT_THESIS_BROKEN" | "MOVE_STOP_TO_BE",
  "confidence": 1-10,
  "reason": "one sentence",
  "thesis_status": "INTACT" | "WEAKENED" | "BROKEN"
}}"""

    start = time.time()
    output = {}
    error = ""
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        output = json.loads(text)
        tokens_in = resp.usage.input_tokens if hasattr(resp, 'usage') else 0
        tokens_out = resp.usage.output_tokens if hasattr(resp, 'usage') else 0
        cost = (tokens_in * 0.80 + tokens_out * 4.0) / 1_000_000
    except Exception as e:
        error = str(e)
        output = {"verdict": "HOLD", "reason": f"AI error, default hold: {e}"}
        tokens_in = tokens_out = 0
        cost = 0

    duration_ms = int((time.time() - start) * 1000)
    log_agent_run(
        event_id=None,
        agent="monitor",
        model=MODEL,
        input={"ticker": position.get("ticker"), "position_id": position.get("id")},
        output=output,
        duration_ms=duration_ms,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
        status="error" if error else "success", error=error,
    )
    return output


# ─── Execution helpers ──────────────────────────────────────────────────────

def execute_trim(position: dict, price: float) -> dict:
    """Close half the position. Updates positions table."""
    pid = position["id"]
    qty = position.get("quantity", 0)
    half = max(1, int(qty // 2))
    new_qty = qty - half

    conn = get_connection()
    # Realize partial PnL
    entry = position.get("entry_price", 0)
    mult = 1 if position.get("direction") == "LONG" else -1
    partial_pnl = round((price - entry) * half * mult, 2)

    # Reduce quantity and move stop to breakeven
    conn.execute(
        "UPDATE positions SET quantity=?, stop_loss=? WHERE id=?",
        (new_qty, entry, pid)
    )

    # Log the trim as a partial closed position entry in notes
    notes = position.get("notes", "") or ""
    notes += f"\n[{datetime.utcnow().isoformat()}] TRIM 50% @ ${price:.2f} | Partial P&L: ${partial_pnl}"
    conn.execute("UPDATE positions SET notes=? WHERE id=?", (notes, pid))
    conn.commit()
    conn.close()

    upsert_meta(pid, t1_hit=1, be_moved=1, trim_count=position.get("quantity", 0) // 2)
    return {"trimmed_qty": half, "remaining_qty": new_qty, "partial_pnl": partial_pnl, "new_stop": entry}


def execute_exit(position: dict, price: float, reason: str) -> dict:
    """Close entire position. Updates positions table."""
    pid = position["id"]
    qty = position.get("quantity", 0)
    entry = position.get("entry_price", 0)
    mult = 1 if position.get("direction") == "LONG" else -1

    # Close the REAL broker position first; use its actual fill price
    exit_price = price
    try:
        import broker
        if broker.is_available():
            r = broker.close_position(position["ticker"])
            if r.get("ok") and r.get("fill_price"):
                exit_price = r["fill_price"]
    except Exception as e:
        print(f"[Monitor] Broker close error: {e}")

    pnl = round((exit_price - entry) * qty * mult, 2)

    conn = get_connection()
    conn.execute("""
        UPDATE positions
        SET status='CLOSED', exit_price=?, exit_date=?, pnl=?,
            notes=COALESCE(notes,'') || ?
        WHERE id=?
    """, (exit_price, datetime.utcnow().isoformat(), pnl, f"\n[EXIT] {reason} @ ${exit_price:.2f}", pid))
    conn.commit()
    conn.close()

    # Update circuit-breaker loss streak
    try:
        import risk_guard
        risk_guard.record_trade_closed(pnl)
    except Exception:
        pass

    return {"exit_price": exit_price, "final_pnl": pnl, "reason": reason}


# ─── Monitor loop ────────────────────────────────────────────────────────────

_running = False
_task = None


async def monitor_position(position: dict) -> dict:
    """Run one monitor check on a position."""
    pid = position["id"]
    ticker = position["ticker"]
    snap = get_snapshot(ticker)
    if not snap.get("price"):
        return {"verdict": "SKIP", "reason": "No price available"}

    meta = get_position_meta(pid)

    # Hard rules first (cheap, fast)
    verdict, reason = hard_rule_check(position, snap, meta)

    if not verdict:
        # No hard rule fired — use AI for nuanced judgment
        # Only call AI every 5 minutes per position to control costs
        try:
            last_check = meta.get("last_check_at")
            if last_check:
                last_dt = datetime.fromisoformat(last_check.replace(" ", "T"))
                if (datetime.utcnow() - last_dt).total_seconds() < 300:
                    # Skip AI, just record check
                    log_check(pid, ticker, snap, "HOLD", "Within AI cooldown", "none", position)
                    return {"verdict": "HOLD", "reason": "Cooldown"}
        except Exception:
            pass

        ai_out = await ai_monitor(position, snap, meta)
        verdict = ai_out.get("verdict", "HOLD")
        reason = ai_out.get("reason", "")

    # Execute the verdict
    action_taken = "none"
    extra = {}
    price = snap["price"]
    direction = position.get("direction", "LONG")

    if verdict == "EXIT_STOP" or verdict == "EXIT_TARGET" or verdict == "EXIT_THESIS_BROKEN" or verdict == "EXIT_FULL":
        extra = execute_exit(position, price, reason)
        action_taken = "closed"
        await publish(
            source="monitor",
            type="position_exit",
            data={"position_id": pid, "ticker": ticker, "reason": reason, **extra},
            title=f"🚪 EXIT {direction} {ticker} @ ${price:.2f} — {reason}",
            impact="CRITICAL" if extra.get("final_pnl", 0) < 0 else "HIGH",
            tickers=[ticker],
        )
        # Trigger Journal post-mortem (Phase 4 learning loop)
        try:
            from agents.journal import analyze_closed_trade
            journal_result = await analyze_closed_trade(pid)
            if journal_result and "error" not in journal_result:
                await publish(
                    source="journal",
                    type="journal_entry_created",
                    data={"position_id": pid, "ticker": ticker, "journal": journal_result},
                    title=f"📔 Journal: {ticker} — {journal_result.get('outcome')} (key takeaway: {journal_result.get('key_takeaway','')[:80]})",
                    impact="MEDIUM",
                    tickers=[ticker],
                )
        except Exception as e:
            print(f"[Monitor] Journal trigger error: {e}")
    elif verdict == "TRIM_HALF":
        extra = execute_trim(position, price)
        action_taken = "trimmed"
        await publish(
            source="monitor",
            type="position_trim",
            data={"position_id": pid, "ticker": ticker, **extra},
            title=f"✂️ TRIM 50% {direction} {ticker} @ ${price:.2f} — T1 hit",
            impact="HIGH",
            tickers=[ticker],
        )
    elif verdict == "MOVE_STOP_TO_BE":
        # Move stop to breakeven
        conn = get_connection()
        conn.execute(
            "UPDATE positions SET stop_loss=? WHERE id=?",
            (position["entry_price"], pid)
        )
        conn.commit()
        conn.close()
        upsert_meta(pid, be_moved=1)
        action_taken = "stop_moved"

    log_check(pid, ticker, snap, verdict, reason, action_taken, position)
    upsert_meta(pid)
    return {"verdict": verdict, "reason": reason, "action": action_taken, **extra}


async def _monitor_loop(interval: int = 60):
    global _running
    _running = True
    print(f"[Monitor] Started — checking positions every {interval}s")

    while _running:
        try:
            # 1. Reconcile broker-side fills (bracket stop/target hit at Alpaca)
            await reconcile_broker()
            # 2. Run discretionary monitor checks on remaining open positions
            positions = get_open_positions()
            for pos in positions:
                try:
                    result = await monitor_position(pos)
                    if result.get("action") and result["action"] != "none":
                        print(f"[Monitor] {pos['ticker']}: {result.get('verdict')} → {result.get('action')}")
                except Exception as e:
                    print(f"[Monitor] Error on {pos.get('ticker')}: {e}")
        except Exception as e:
            print(f"[Monitor] Loop error: {e}")

        await asyncio.sleep(interval)


async def reconcile_broker():
    """
    Detect positions closed server-side by Alpaca bracket legs (stop/target hit).
    If a local OPEN position is no longer in Alpaca's positions, it was closed —
    sync it, trigger journal, update loss streak.
    """
    try:
        import broker
        if not broker.is_available():
            return
        live = {p["ticker"] for p in broker.get_positions()}
        local = get_open_positions()
        recent_fills = broker.get_order_activity(limit=40)
        # Map symbol → closing fill (stop/limit legs are the bracket exits)
        closing_fills = {}
        for f in recent_fills:
            otype = f.get("order_type", "")
            if otype in ("stop", "limit", "OrderType.STOP", "OrderType.LIMIT"):
                closing_fills.setdefault(f["symbol"], f["fill_price"])

        for pos in local:
            ticker = pos["ticker"]
            # Skip simulated positions (no real broker order)
            if "REAL Alpaca" not in (pos.get("notes") or ""):
                continue
            if ticker in live:
                continue  # still open at broker
            # Fill-driven: only treat as closed if we SEE a closing fill.
            # (Absence alone could mean a still-pending entry — e.g. weekend queue.)
            if ticker not in closing_fills:
                continue

            exit_fill = closing_fills[ticker]
            entry = pos["entry_price"]
            qty = pos["quantity"]
            mult = 1 if pos["direction"] == "LONG" else -1
            exit_price = exit_fill or entry
            pnl = round((exit_price - entry) * qty * mult, 2)

            conn = get_connection()
            conn.execute("""
                UPDATE positions SET status='CLOSED', exit_price=?, exit_date=?, pnl=?,
                    notes=COALESCE(notes,'') || ?
                WHERE id=?
            """, (exit_price, datetime.utcnow().isoformat(), pnl,
                  f"\n[BROKER EXIT] bracket leg filled @ ${exit_price:.2f}", pos["id"]))
            conn.commit()
            conn.close()

            # Update loss streak + publish + journal
            try:
                import risk_guard
                risk_guard.record_trade_closed(pnl)
            except Exception:
                pass

            await publish(
                source="monitor", type="position_exit",
                data={"position_id": pos["id"], "ticker": ticker,
                      "reason": "Broker bracket leg filled", "exit_price": exit_price, "final_pnl": pnl},
                title=f"🎯 BRACKET EXIT {ticker} @ ${exit_price:.2f} · P&L ${pnl:+.2f}",
                impact="HIGH" if pnl >= 0 else "CRITICAL",
                tickers=[ticker],
            )
            try:
                from agents.journal import analyze_closed_trade
                jr = await analyze_closed_trade(pos["id"])
                if jr and "error" not in jr:
                    await publish(
                        source="journal", type="journal_entry_created",
                        data={"position_id": pos["id"], "ticker": ticker, "journal": jr},
                        title=f"📔 Journal: {ticker} — {jr.get('outcome')} ({jr.get('key_takeaway','')[:70]})",
                        impact="MEDIUM", tickers=[ticker],
                    )
            except Exception as e:
                print(f"[Monitor] Reconcile journal error: {e}")
            print(f"[Monitor] Reconciled broker exit: {ticker} @ ${exit_price:.2f} P&L ${pnl:+.2f}")
    except Exception as e:
        print(f"[Monitor] Reconcile error: {e}")


def start_monitor(interval: int = 60):
    global _task
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_monitor_loop(interval))
    return _task


def stop_monitor():
    global _running, _task
    _running = False
    if _task:
        _task.cancel()


# ─── Stats ───────────────────────────────────────────────────────────────────

def get_position_checks(position_id: int = None, limit: int = 50) -> list:
    conn = get_connection()
    if position_id:
        rows = conn.execute(
            "SELECT * FROM position_checks WHERE position_id=? ORDER BY id DESC LIMIT ?",
            (position_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM position_checks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
