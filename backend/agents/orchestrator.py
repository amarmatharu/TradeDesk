"""
Orchestrator — Runs the full agent pipeline on each event.
Scout → (if score ≥7) → Research → Risk → Trader → Pending Trade.
"""

import asyncio
import time
from agents.scout import scout, SCOUT_THRESHOLD
from agents.research import research
from agents.risk import risk_check
from agents.trader import trade_decision, create_pending_trade
from event_bus import publish

# Mode state — controls execution
MODES = ["SHADOW", "SUGGEST", "AUTO_PAPER", "AUTO_LIVE"]
_mode = "SUGGEST"


def get_mode() -> str:
    return _mode


def set_mode(mode: str):
    global _mode
    if mode in MODES:
        _mode = mode


# ─── Pipeline ─────────────────────────────────────────────────────────────────

async def run_pipeline(event: dict, portfolio_size: float = 25000) -> dict:
    """Run an event through the full agent pipeline."""
    pipeline_start = time.time()
    pipeline_result = {
        "event_id": event.get("event_id"),
        "event_title": event.get("title", "")[:100],
        "stages": {},
        "final_action": "PASS",
        "pending_trade_id": None,
    }

    # ─── Stage 1: Scout ──────────────────────────────────────────
    try:
        scout_out = await scout(event)
        pipeline_result["stages"]["scout"] = scout_out
    except Exception as e:
        pipeline_result["error"] = f"Scout error: {e}"
        return pipeline_result

    score = scout_out.get("tradable_score", 0)
    if score < SCOUT_THRESHOLD:
        pipeline_result["final_action"] = "FILTERED_OUT"
        pipeline_result["filter_reason"] = f"Scout score {score} < {SCOUT_THRESHOLD}"
        # Broadcast lightweight update so UI can show "considered but skipped"
        await publish(
            source="agent",
            type="pipeline_complete",
            data={"pipeline": pipeline_result},
            title=f"Filtered: {event.get('title','')[:60]}",
            impact="LOW",
        )
        return pipeline_result

    # ─── Stage 2: Research ───────────────────────────────────────
    try:
        research_out = await research(event, scout_out, portfolio_size)
        pipeline_result["stages"]["research"] = research_out
    except Exception as e:
        pipeline_result["error"] = f"Research error: {e}"
        return pipeline_result

    if research_out.get("direction") == "NO_TRADE" or research_out.get("confidence", 0) < 5:
        pipeline_result["final_action"] = "RESEARCH_DECLINED"
        pipeline_result["filter_reason"] = "Research declined or low confidence"
        return pipeline_result

    # ─── Stage 3: Risk ───────────────────────────────────────────
    try:
        risk_out = await risk_check(event, scout_out, research_out, portfolio_size)
        pipeline_result["stages"]["risk"] = risk_out
    except Exception as e:
        pipeline_result["error"] = f"Risk error: {e}"
        return pipeline_result

    if not risk_out.get("approved"):
        pipeline_result["final_action"] = "RISK_BLOCKED"
        pipeline_result["filter_reason"] = risk_out.get("reason")
        return pipeline_result

    # ─── Stage 4: Trader ─────────────────────────────────────────
    try:
        trader_out = await trade_decision(event, scout_out, research_out, risk_out)
        pipeline_result["stages"]["trader"] = trader_out
    except Exception as e:
        pipeline_result["error"] = f"Trader error: {e}"
        return pipeline_result

    pipeline_result["final_action"] = trader_out.get("action", "PASS")

    # ─── Stage 5: Act on BUY decision ─────────────────────────────
    if trader_out.get("action") == "BUY" and _mode != "SHADOW":
        ticker = research_out.get("ticker")
        entry = trader_out.get("final_entry") or research_out.get("entry")
        stop = trader_out.get("final_stop") or research_out.get("stop")
        t1 = trader_out.get("final_target1") or research_out.get("target1")
        t2 = trader_out.get("final_target2") or research_out.get("target2")
        shares = trader_out.get("final_shares") or research_out.get("shares")
        confidence = trader_out.get("confidence", 0)
        thesis = research_out.get("thesis", "")

        # Which strategy does this trade belong to?
        import strategies
        strat = strategies.resolve_strategy(event)

        if _mode in ("AUTO_PAPER", "AUTO_LIVE"):
            # Auto-execute the trade (paper), tagged with its strategy
            from paper_trader import execute_paper_trade
            exec_result = await execute_paper_trade(
                ticker=ticker, direction=research_out.get("direction"),
                entry=entry, stop=stop, target1=t1, target2=t2,
                shares=shares, thesis=thesis, confidence=confidence,
                source="agent", strategy_tag=strat,
            )
            pipeline_result["paper_execution"] = exec_result
            pipeline_result["strategy"] = strat
        else:
            # SUGGEST mode — create pending trade for user approval
            trade_id = create_pending_trade(event, scout_out, research_out, risk_out, trader_out)
            pipeline_result["pending_trade_id"] = trade_id
            await publish(
                source="agent",
                type="new_pending_trade",
                data={
                    "trade_id": trade_id, "ticker": ticker,
                    "direction": research_out.get("direction"),
                    "entry": entry, "confidence": confidence, "thesis": thesis,
                },
                title=f"🤖 New Trade: {research_out.get('direction')} {ticker} @ ${entry}",
                impact="CRITICAL",
                tickers=[ticker] if ticker else [],
            )

    pipeline_result["duration_ms"] = int((time.time() - pipeline_start) * 1000)
    return pipeline_result


# ─── Event handler ──────────────────────────────────────────────────────────

async def handle_event(event: dict):
    """Called by event bus on every published event."""
    # Skip pipeline-generated events (avoid infinite recursion)
    if event.get("source") in ("agent", "monitor", "journal"):
        return

    # Process EVERY market event from feeds — Scout filters cheap.
    # MEDIUM and HIGH always processed. LOW skipped to save Scout cost
    # (LOW events are usually market commentary / opinion pieces).
    impact = event.get("impact", "")
    if impact == "LOW":
        return

    try:
        await run_pipeline(event)
    except Exception as e:
        print(f"[Orchestrator] Pipeline error: {e}")
