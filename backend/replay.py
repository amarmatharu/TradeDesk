"""
Pipeline replay & validation harness (Phase 0 — ground truth).

The agent pipeline itself has never been backtested — only the standalone
insider-edge study (backtest.py) was. This module turns the decision record
(`pending_trades` + `positions` + `decision_snapshots`) into an evaluation
engine so you can answer:

  1. Does the pipeline's *conviction* actually predict outcome?
     (bucket realized R by trader confidence — if it doesn't slope up, the
      confidence signal is noise.)
  2. What is the realized edge of trades the pipeline chose to take?
  3. A/B: given two prompt versions, which decisions differ and how did the
     ones that reached a position resolve?

Read-only. This is measurement, not execution. Actual replay-through-current-
prompts (re-running a frozen snapshot) is exposed via `decisions_for_replay()`
which hands back the exact frozen inputs for an offline re-run.
"""

import json
from database import get_connection


def _pipeline_trades():
    """Agent-originated trades that became positions, joined to outcome."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT pt.id AS pending_id, pt.ticker, pt.confidence, pt.direction,
               pt.entry, pt.stop, pt.target1, pt.status AS pending_status,
               p.id AS position_id, p.status AS pos_status, p.pnl,
               j.r_multiple, j.outcome
        FROM pending_trades pt
        LEFT JOIN positions p
               ON p.ticker = pt.ticker AND p.status = 'CLOSED'
              AND ABS(p.entry_price - pt.entry) < 0.01
        LEFT JOIN trade_journal j ON j.position_id = p.id
        ORDER BY pt.id DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def confidence_calibration() -> dict:
    """Does higher trader-confidence actually mean better outcomes? Buckets
    realized R-multiple by confidence band. A well-calibrated pipeline slopes
    up; a flat/negative slope means confidence is decorative."""
    trades = [t for t in _pipeline_trades() if t.get("r_multiple") is not None]
    bands = {"low (≤5)": [], "med (6-7)": [], "high (8-10)": []}
    for t in trades:
        c = t.get("confidence") or 0
        r = t["r_multiple"]
        if c <= 5:
            bands["low (≤5)"].append(r)
        elif c <= 7:
            bands["med (6-7)"].append(r)
        else:
            bands["high (8-10)"].append(r)
    out = {}
    for k, rs in bands.items():
        out[k] = {
            "n": len(rs),
            "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
            "win_rate": round(len([x for x in rs if x > 0]) / len(rs) * 100, 1) if rs else None,
        }
    # Is it monotonic (calibrated)?
    avgs = [out[k]["avg_r"] for k in ["low (≤5)", "med (6-7)", "high (8-10)"] if out[k]["avg_r"] is not None]
    calibrated = len(avgs) >= 2 and all(avgs[i] <= avgs[i + 1] for i in range(len(avgs) - 1))
    return {"bands": out, "calibrated": calibrated,
            "note": "Confidence predicts outcome (monotonic)." if calibrated
                    else "Confidence does NOT reliably predict outcome — treat as noise until it does."}


def pipeline_edge() -> dict:
    """Realized edge of pipeline-selected trades that reached a closed position."""
    trades = [t for t in _pipeline_trades() if t.get("pnl") is not None]
    n = len(trades)
    if not n:
        return {"n": 0, "note": "No pipeline trades have closed yet."}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    return {
        "n": n,
        "win_rate": round(len(wins) / n * 100, 1),
        "expectancy_usd": round(sum(pnls) / n, 2),
        "net_pnl": round(sum(pnls), 2),
        "reliable": n >= 30,
    }


def decisions_for_replay(limit: int = 200) -> list:
    """Return frozen decision snapshots (inputs only) for offline re-run through
    a new prompt version. Enables A/B without touching the live system."""
    try:
        import snapshots
        snapshots.ensure_table()
    except Exception:
        pass
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, ts_utc, ticker, action, price_at_decision, scout_json, "
        "research_json, prompt_version FROM decision_snapshots ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("scout_json", "research_json"):
            try:
                d[k] = json.loads(d[k]) if d.get(k) else None
            except Exception:
                pass
        out.append(d)
    return out


def validation_report() -> dict:
    """One call for the whole Phase-0 picture."""
    return {
        "pipeline_edge": pipeline_edge(),
        "confidence_calibration": confidence_calibration(),
        "snapshots_captured": _snapshot_count(),
    }


def _snapshot_count():
    try:
        conn = get_connection()
        n = conn.execute("SELECT COUNT(*) FROM decision_snapshots").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0
