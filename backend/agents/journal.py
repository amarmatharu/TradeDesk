"""
Journal Agent — Post-mortem on every closed trade.

When a position closes:
1. Pull original thesis from notes/research output
2. Pull all monitor checks that happened during the trade
3. Pull price action during hold period
4. Ask Claude to analyze: what worked, what failed, what's the lesson
5. Tag with patterns (earnings_beat, oversold_bounce, m&a_play, etc)
6. Update aggregate learnings table

Aggregated learnings feed back into Scout and Research prompts —
the system gets smarter with every trade.
"""

import json
import time
import re
from datetime import datetime
from ai_brain import get_client
from event_bus import log_agent_run

# ─── Canonical pattern taxonomy ───────────────────────────────────────────────
# The Journal MUST tag trades using ONLY these patterns so the learnings table
# aggregates correctly (free-text tags fragment and never reach n>=4).

PATTERN_TAXONOMY = {
    # Entry setups
    "earnings_beat": "Bought on earnings beat / strong report",
    "earnings_miss_short": "Shorted on earnings miss",
    "guidance_raise": "Traded a raised-guidance catalyst",
    "guidance_cut_short": "Shorted a lowered-guidance catalyst",
    "analyst_upgrade": "Entered on analyst upgrade / PT raise",
    "analyst_downgrade_short": "Shorted on downgrade / PT cut",
    "mna_target": "M&A / acquisition / buyout play",
    "fda_catalyst": "FDA approval / clinical result catalyst",
    "insider_buy": "Followed insider buying",
    "spinoff_play": "Spinoff / corporate restructuring catalyst",
    "breakout_continuation": "Momentum breakout above resistance",
    "oversold_bounce": "Mean-reversion bounce from oversold",
    "trend_continuation": "Pullback entry in an established trend",
    "support_reclaim": "Bought a reclaim of key support",
    "delisting_short": "Shorted delisting / going-concern risk",
    # Execution-quality outcomes (what went right/wrong)
    "stopped_out": "Stop loss hit",
    "target_hit": "Hit profit target cleanly",
    "took_profit_too_early": "Exited before target, left gains",
    "held_too_long": "Overstayed — gave back profit / time-stopped",
    "thesis_drift": "Held past the catalyst / thesis no longer valid",
    "chased_entry": "Chased a move instead of waiting for entry",
    "good_risk_reward": "Well-structured R:R, disciplined execution",
    "unhedged_binary_event": "Held through a binary event unhedged",
}

VALID_PATTERNS = set(PATTERN_TAXONOMY.keys())


def normalize_patterns(tags: list) -> list:
    """Map raw tags to canonical taxonomy. Drops anything that can't be matched."""
    out = []
    for t in (tags or []):
        key = re.sub(r"[^a-z0-9]+", "_", str(t).lower()).strip("_")
        if key in VALID_PATTERNS:
            out.append(key)
            continue
        # Fuzzy: match on keyword overlap with taxonomy keys
        best = None
        for canon in VALID_PATTERNS:
            ct = set(canon.split("_"))
            kt = set(key.split("_"))
            if ct & kt:  # any shared token
                best = canon
                break
        if best:
            out.append(best)
    # Dedup, preserve order
    seen = set()
    return [p for p in out if not (p in seen or seen.add(p))]
from database import get_connection

MODEL = "claude-sonnet-4-6"


# ─── Post-mortem on a single trade ──────────────────────────────────────────

async def analyze_closed_trade(position_id: int) -> dict:
    """Generate a journal entry for one closed position."""
    conn = get_connection()
    pos = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if not pos:
        conn.close()
        return {"error": "Position not found"}
    pos = dict(pos)
    if pos["status"] != "CLOSED":
        conn.close()
        return {"error": "Position still open"}

    # Already analyzed?
    existing = conn.execute(
        "SELECT id FROM trade_journal WHERE position_id=?", (position_id,)
    ).fetchone()
    if existing:
        result = dict(conn.execute(
            "SELECT * FROM trade_journal WHERE id=?", (existing["id"],)
        ).fetchone())
        conn.close()
        return result

    # Pull monitor checks that happened during the trade
    checks = conn.execute(
        "SELECT verdict, reason, current_price, unrealized_pnl_pct, created_at "
        "FROM position_checks WHERE position_id=? ORDER BY id ASC",
        (position_id,)
    ).fetchall()
    checks = [dict(c) for c in checks]

    # Look for the original research/agent output (if agent-created)
    research_output = None
    if pos.get("notes") and "AI Agent" in (pos.get("strategy") or ""):
        # Find original event/research
        try:
            pt = conn.execute("""
                SELECT research_output, scout_output, thesis, confidence
                FROM pending_trades
                WHERE ticker=? AND status='approved'
                ORDER BY id DESC LIMIT 1
            """, (pos["ticker"],)).fetchone()
            if pt:
                research_output = dict(pt)
        except Exception:
            pass

    conn.close()

    # Calculate trade metrics
    entry = pos.get("entry_price", 0)
    exit_p = pos.get("exit_price", 0)
    stop = pos.get("stop_loss") or 0
    qty = pos.get("quantity") or 0
    direction = pos.get("direction", "LONG")
    mult = 1 if direction == "LONG" else -1
    pnl = pos.get("pnl") or ((exit_p - entry) * qty * mult if entry and exit_p else 0)
    pnl_pct = ((exit_p - entry) / entry * 100 * mult) if entry and exit_p else 0
    initial_risk = abs(entry - stop) * qty if stop else abs(pnl)
    r_multiple = pnl / initial_risk if initial_risk else 0

    days_held = 0
    try:
        created = datetime.fromisoformat(pos.get("created_at", "").replace(" ", "T"))
        exited = datetime.fromisoformat((pos.get("exit_date") or "").replace(" ", "T"))
        days_held = max(0, (exited - created).days)
    except Exception:
        pass

    outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"

    # Build context for AI
    notes = pos.get("notes") or ""
    strategy = pos.get("strategy") or "Manual"

    monitor_summary = ""
    if checks:
        verdicts = [c["verdict"] for c in checks]
        monitor_summary = f"Monitor ran {len(checks)} times. Verdicts: {dict((v, verdicts.count(v)) for v in set(verdicts))}"
        # Include first/last few notable verdicts
        notable = [c for c in checks if c["verdict"] not in ("HOLD", None)][:5]
        if notable:
            monitor_summary += "\nKey decisions:\n" + "\n".join(
                f"  - [{c['created_at']}] {c['verdict']}: {c['reason']}"
                for c in notable
            )

    thesis_block = ""
    if research_output:
        thesis_block = f"Original thesis: {research_output.get('thesis', '')}\nResearch confidence: {research_output.get('confidence')}/10"
    else:
        thesis_block = f"Strategy/notes: {strategy} — {notes[:300]}"

    prompt = f"""You are the Journal Agent. Analyze this closed trade for learnings.
Be honest and specific — vague analysis is useless. Goal is to make future trades better.

TRADE SUMMARY:
- {direction} {pos['ticker']}
- Entry: ${entry}  Exit: ${exit_p}  Stop: ${stop}
- Quantity: {qty}
- P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)
- R-multiple: {r_multiple:.2f}R (profit / initial risk)
- Held: {days_held} days
- Outcome: {outcome}

{thesis_block}

{monitor_summary}

Final notes: {notes[:500]}

Analyze deeply:
1. Was the original thesis sound? Did it play out as expected?
2. Was the entry timing good?
3. Was the exit timing good — or did we leave money on the table / overstay?
4. What pattern does this trade represent? Tag with 1-3 specific patterns.
5. What's the single biggest lesson for next time?
6. Quality score: 1-10, how well-EXECUTED was this trade (independent of outcome)?
   A losing trade with disciplined execution can still be 8/10.
   A winning trade with sloppy execution can still be 4/10.

Respond ONLY with JSON (no markdown):
{{
  "outcome": "WIN" | "LOSS" | "BREAKEVEN",
  "what_worked": "specific things that worked",
  "what_failed": "specific things that didn't",
  "lessons": ["lesson 1", "lesson 2", "lesson 3"],
  "pattern_tags": ["pattern1", "pattern2"],
  "quality_score": <1-10>,
  "thesis_validity": "VALIDATED" | "PARTIAL" | "INVALIDATED",
  "exit_timing": "TOO_EARLY" | "OPTIMAL" | "TOO_LATE",
  "key_takeaway": "single most important lesson for the system to remember"
}}

pattern_tags MUST be chosen ONLY from this exact taxonomy (use the keys verbatim, 1-3 of them):
""" + "\n".join(f'  "{k}" — {v}' for k, v in PATTERN_TAXONOMY.items()) + """

Do NOT invent new tags. If nothing fits, use the closest match from the list above."""

    client = get_client()
    if not client:
        return {"error": "No Anthropic API key"}

    start = time.time()
    output = {}
    error = ""
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=800,
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
        cost = (tokens_in * 3.0 + tokens_out * 15.0) / 1_000_000
    except Exception as e:
        error = str(e)
        output = {"error": error}
        tokens_in = tokens_out = 0
        cost = 0

    duration_ms = int((time.time() - start) * 1000)
    log_agent_run(
        event_id=None,
        agent="journal",
        model=MODEL,
        input={"position_id": position_id, "ticker": pos["ticker"]},
        output=output,
        duration_ms=duration_ms,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
        status="error" if error else "success", error=error,
    )

    if "error" in output:
        return output

    # Normalize pattern tags to the canonical taxonomy (critical for aggregation)
    norm_patterns = normalize_patterns(output.get("pattern_tags", []))
    output["pattern_tags"] = norm_patterns

    # Persist journal entry
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO trade_journal (
            position_id, ticker, direction, entry_price, exit_price,
            pnl, pnl_pct, r_multiple, days_held, outcome,
            thesis_original, what_worked, what_failed, lessons,
            pattern_tags, quality_score, analysis_full
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        position_id, pos["ticker"], direction, entry, exit_p,
        round(pnl, 2), round(pnl_pct, 2), round(r_multiple, 2), days_held, outcome,
        (research_output.get("thesis") if research_output else notes[:500]),
        output.get("what_worked", ""),
        output.get("what_failed", ""),
        json.dumps(output.get("lessons", [])),
        json.dumps(norm_patterns),
        output.get("quality_score", 5),
        json.dumps(output, default=str),
    ))
    journal_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Update aggregate learnings table (normalized patterns only)
    update_learnings(norm_patterns, outcome, r_multiple)

    return {
        "journal_id": journal_id,
        "ticker": pos["ticker"],
        "outcome": outcome,
        "r_multiple": r_multiple,
        **output,
    }


# ─── Aggregate learnings ────────────────────────────────────────────────────

def update_learnings(patterns: list, outcome: str, r_multiple: float):
    """Update the learnings table with this trade's pattern data."""
    conn = get_connection()
    cur = conn.cursor()
    for pattern in patterns:
        pattern = pattern.lower().strip()
        if not pattern:
            continue
        # Get or create
        cur.execute("INSERT OR IGNORE INTO learnings (pattern) VALUES (?)", (pattern,))
        # Get current stats
        row = cur.execute(
            "SELECT sample_size, wins, losses, avg_r FROM learnings WHERE pattern=?",
            (pattern,)
        ).fetchone()
        sample = (row["sample_size"] if row else 0) + 1
        wins = (row["wins"] if row else 0) + (1 if outcome == "WIN" else 0)
        losses = (row["losses"] if row else 0) + (1 if outcome == "LOSS" else 0)
        old_avg_r = (row["avg_r"] or 0) if row else 0
        new_avg_r = ((old_avg_r * (sample - 1)) + r_multiple) / sample
        win_rate = wins / sample * 100 if sample else 0

        # Confidence based on sample size
        confidence = "HIGH" if sample >= 10 else "MEDIUM" if sample >= 4 else "LOW"

        # Recommendation
        if sample >= 4 and win_rate >= 60 and new_avg_r >= 1.5:
            recommendation = "FAVOR"
        elif sample >= 4 and (win_rate < 30 or new_avg_r < -0.5):
            recommendation = "AVOID"
        else:
            recommendation = "NEUTRAL"

        cur.execute("""
            UPDATE learnings
            SET sample_size=?, wins=?, losses=?, avg_r=?, win_rate=?,
                confidence=?, recommendation=?, updated_at=datetime('now')
            WHERE pattern=?
        """, (sample, wins, losses, round(new_avg_r, 2), round(win_rate, 1),
              confidence, recommendation, pattern))
    conn.commit()
    conn.close()


def get_playbook(limit: int = 10) -> dict:
    """
    Returns the system's accumulated wisdom — fed into Scout/Research prompts.
    Patterns with high confidence are highlighted.
    """
    conn = get_connection()
    favored = conn.execute("""
        SELECT pattern, sample_size, win_rate, avg_r, confidence
        FROM learnings WHERE recommendation='FAVOR' AND sample_size >= 3
        ORDER BY avg_r DESC LIMIT ?
    """, (limit,)).fetchall()
    avoided = conn.execute("""
        SELECT pattern, sample_size, win_rate, avg_r, confidence
        FROM learnings WHERE recommendation='AVOID' AND sample_size >= 3
        ORDER BY avg_r ASC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return {
        "favor": [dict(r) for r in favored],
        "avoid": [dict(r) for r in avoided],
    }


def format_playbook_for_prompt() -> str:
    """Returns a short string injectable into Scout/Research prompts.

    Avoid-patterns are framed as HARD RULES (not soft bias): patterns that have
    lost money over a real sample must be treated as NO_TRADE unless the evidence
    is exceptional and clearly differentiated from the past failures."""
    pb = get_playbook(limit=5)
    lines = []
    if pb["favor"]:
        lines.append("PATTERNS THAT HAVE WORKED FOR US (favor, all else equal):")
        for p in pb["favor"]:
            lines.append(f"  ✓ {p['pattern']}: win_rate={p['win_rate']}%  avg_R={p['avg_r']}  (n={p['sample_size']})")
    if pb["avoid"]:
        lines.append(
            "HARD AVOID — these setups have repeatedly LOST money. If this "
            "candidate matches one, return NO_TRADE unless there is exceptional, "
            "differentiated evidence this time (say explicitly what is different):"
        )
        for p in pb["avoid"]:
            lines.append(f"  ⛔ {p['pattern']}: win_rate={p['win_rate']}%  avg_R={p['avg_r']}  (n={p['sample_size']}) — DO NOT repeat this mistake")
    if not lines:
        return ""
    return "\n".join(lines)


# ─── Queries ────────────────────────────────────────────────────────────────

def list_journal_entries(limit: int = 50) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trade_journal ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for k in ("lessons", "pattern_tags"):
            try:
                d[k] = json.loads(d[k]) if d.get(k) else []
            except Exception:
                d[k] = []
        try:
            d["analysis_full"] = json.loads(d["analysis_full"]) if d.get("analysis_full") else {}
        except Exception:
            pass
        result.append(d)
    return result


def list_learnings() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM learnings ORDER BY sample_size DESC, avg_r DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_journal_stats() -> dict:
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM trade_journal").fetchone()[0]
    wins = conn.execute("SELECT COUNT(*) FROM trade_journal WHERE outcome='WIN'").fetchone()[0]
    losses = conn.execute("SELECT COUNT(*) FROM trade_journal WHERE outcome='LOSS'").fetchone()[0]
    avg_r = conn.execute("SELECT AVG(r_multiple) FROM trade_journal").fetchone()[0] or 0
    total_pnl = conn.execute("SELECT SUM(pnl) FROM trade_journal").fetchone()[0] or 0
    avg_quality = conn.execute("SELECT AVG(quality_score) FROM trade_journal").fetchone()[0] or 0
    best = conn.execute(
        "SELECT ticker, pnl, r_multiple FROM trade_journal ORDER BY r_multiple DESC LIMIT 1"
    ).fetchone()
    worst = conn.execute(
        "SELECT ticker, pnl, r_multiple FROM trade_journal ORDER BY r_multiple ASC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "avg_r_multiple": round(avg_r, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_quality_score": round(avg_quality, 1),
        "best": dict(best) if best else None,
        "worst": dict(worst) if worst else None,
    }
