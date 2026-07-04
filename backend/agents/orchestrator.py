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

# Structural reward:risk gate. At the strategy's ~30% win rate, only high-R:R
# trades have positive expectancy, so reject anything below this at T1. The
# "Min R:R 2:1" line in the Research prompt is advisory only — this enforces it.
MIN_REWARD_RISK = 2.5

# Prompt/model version tag — stamped on decision snapshots so A/B of prompt
# changes is possible via the replay harness. Bump when prompts change.
PROMPT_VERSION = "2026.07-debate"


def get_mode() -> str:
    return _mode


def set_mode(mode: str):
    global _mode
    if mode in MODES:
        _mode = mode


def _compute_reward_risk(entry, stop, target, direction):
    """Real reward:risk from the actual prices (not the model's self-reported
    `risk_reward`). Returns None if inputs are unusable or the geometry is wrong
    (stop on the wrong side, target not beyond entry)."""
    try:
        entry = float(entry); stop = float(stop); target = float(target)
    except (TypeError, ValueError):
        return None
    # Both legs must be on the correct side of entry, else the plan is invalid.
    risk = (entry - stop) if direction == "LONG" else (stop - entry)
    reward = (target - entry) if direction == "LONG" else (entry - target)
    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def _net_reward_risk(ticker, entry, stop, target, direction, shares):
    """R:R after subtracting estimated round-trip transaction costs from the
    reward. A 2.5:1 setup with 40bps of friction is not really 2.5:1 — gate on
    the net number so cost can't be ignored. Returns (net_rr, est_cost_bps)."""
    try:
        entry = float(entry); stop = float(stop); target = float(target)
    except (TypeError, ValueError):
        return None, None
    risk = (entry - stop) if direction == "LONG" else (stop - entry)
    reward = (target - entry) if direction == "LONG" else (entry - target)
    if risk <= 0 or reward <= 0:
        return None, None
    est_cost_bps = None
    try:
        import tca
        est = tca.estimate_cost(ticker, shares or 100, entry)
        est_cost_bps = est.get("round_trip_bps")
        cost_per_share = entry * (est_cost_bps or 0) / 10000.0
        reward = max(0.0, reward - cost_per_share)
    except Exception:
        pass
    return round(reward / risk, 2), est_cost_bps


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

    # ─── Stage 2b: Structural reward:risk gate (net of estimated costs) ──
    rr = _compute_reward_risk(
        research_out.get("entry"), research_out.get("stop"),
        research_out.get("target1"), research_out.get("direction"),
    )
    rr_net, est_cost_bps = _net_reward_risk(
        research_out.get("ticker"), research_out.get("entry"), research_out.get("stop"),
        research_out.get("target1"), research_out.get("direction"), research_out.get("shares"),
    )
    research_out["rr_computed"] = rr          # gross (for reference)
    research_out["rr_net"] = rr_net           # net of transaction costs
    research_out["est_cost_bps"] = est_cost_bps
    gate_rr = rr_net if rr_net is not None else rr   # gate on the net number
    if gate_rr is None or gate_rr < MIN_REWARD_RISK:
        pipeline_result["final_action"] = "RR_REJECTED"
        pipeline_result["filter_reason"] = (
            f"Net R:R {gate_rr} < {MIN_REWARD_RISK} required "
            f"(gross {rr}, ~{est_cost_bps}bps cost; "
            f"entry={research_out.get('entry')} stop={research_out.get('stop')} "
            f"T1={research_out.get('target1')})"
        )
        await publish(
            source="agent",
            type="pipeline_complete",
            data={"pipeline": pipeline_result},
            title=f"Net R:R too low ({gate_rr}): {research_out.get('ticker','')}",
            impact="LOW",
        )
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

    # ─── Stage 3b: Researcher debate (bull vs bear) ──────────────
    debate_out = None
    try:
        from agents.debate import debate
        debate_out = await debate(event, research_out)
        pipeline_result["stages"]["debate"] = debate_out
    except Exception as e:
        pipeline_result["stages"]["debate"] = {"available": False, "error": str(e)[:120]}

    # ─── Stage 4: Trader ─────────────────────────────────────────
    try:
        trader_out = await trade_decision(event, scout_out, research_out, risk_out, debate_out)
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

        # Phase 1: portfolio construction — override raw shares with a
        # correlation-aware, edge-weighted (fractional-Kelly) size.
        try:
            import portfolio_construction as pc
            sized = pc.suggest_size(ticker, entry, stop, portfolio_size,
                                    pattern_tags=research_out.get("pattern_tags") or [])
            pipeline_result["sizing"] = sized
            if sized.get("blocked"):
                pipeline_result["final_action"] = "SIZING_BLOCKED"
                pipeline_result["filter_reason"] = sized.get("reason")
                return pipeline_result
            if sized.get("shares"):
                shares = sized["shares"]
        except Exception as e:
            pipeline_result["sizing_error"] = str(e)[:120]

        # Which strategy does this trade belong to?
        import strategies
        strat = strategies.resolve_strategy(event)

        # Phase 4: live-promotion gate — real money requires a passing grade.
        if _mode == "AUTO_LIVE":
            try:
                import promotion
                if not promotion.can_go_live():
                    pipeline_result["final_action"] = "LIVE_BLOCKED_UNPROVEN"
                    pipeline_result["filter_reason"] = (
                        "AUTO_LIVE blocked: strategy has not cleared the promotion "
                        "gate (deflated Sharpe / sample / drawdown). See /api/promotion.")
                    return pipeline_result
            except Exception:
                pass

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

            # Phase 3: record realized slippage (decision price vs actual fill).
            try:
                import tca
                fill = (exec_result or {}).get("fill_price") or (exec_result or {}).get("entry")
                if fill and entry:
                    tca.record_fill(
                        position_id=(exec_result or {}).get("position_id"),
                        ticker=ticker,
                        side="BUY" if research_out.get("direction") == "LONG" else "SELL",
                        decision_price=entry, fill_price=fill, shares=shares,
                    )
            except Exception:
                pass
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

    # Phase 0: freeze a point-in-time snapshot of this decision (replay/validation).
    try:
        import snapshots
        snapshots.capture(event, pipeline_result, prompt_version=PROMPT_VERSION)
    except Exception:
        pass
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
