"""
Risk Agent — Gatekeeper.
Validates trade against portfolio state. Has VETO power.
"""

import json
import time
from ai_brain import get_client
from event_bus import log_agent_run
from database import get_connection

MODEL = "claude-sonnet-4-6"


def get_portfolio_state(portfolio_size: float = 25000) -> dict:
    """Snapshot of current portfolio state for risk checks."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT ticker, direction, entry_price, quantity, stop_loss
        FROM positions WHERE status='OPEN'
    """).fetchall()
    conn.close()

    positions = [dict(r) for r in rows]
    open_count = len(positions)
    tickers_held = [p["ticker"] for p in positions]
    capital_deployed = sum(p["entry_price"] * p["quantity"] for p in positions)
    cash_available = portfolio_size - capital_deployed

    return {
        "portfolio_size": portfolio_size,
        "open_positions": open_count,
        "tickers_held": tickers_held,
        "positions": positions,
        "capital_deployed": round(capital_deployed, 2),
        "cash_available": round(cash_available, 2),
        "cash_pct": round(cash_available / portfolio_size * 100, 1),
    }


async def risk_check(event: dict, scout_output: dict, research_output: dict,
                     portfolio_size: float = 25000) -> dict:
    """
    Returns:
    {
      "approved": bool,
      "reason": "...",
      "warnings": [...],
      "adjustments": {... if shares should be reduced ...},
      "risk_score": 1-10
    }
    """
    if research_output.get("direction") == "NO_TRADE":
        return {"approved": False, "reason": "Research declined trade", "risk_score": 0}

    state = get_portfolio_state(portfolio_size)

    # Hard rule checks first (cheap)
    ticker = research_output.get("ticker", "")
    direction = research_output.get("direction", "")
    entry = research_output.get("entry", 0)
    stop = research_output.get("stop", 0)
    shares = research_output.get("shares", 0)
    position_value = research_output.get("position_value", 0)
    rr = research_output.get("risk_reward", 0)

    hard_failures = []

    # Already in this trade?
    if ticker in state["tickers_held"]:
        hard_failures.append(f"Already holding {ticker} — no doubling down")

    # Risk per trade > 1.5%
    risk_dollars = research_output.get("risk_dollars", 0)
    if risk_dollars > portfolio_size * 0.015:
        hard_failures.append(f"Risk ${risk_dollars:.0f} exceeds 1.5% max (${portfolio_size*0.015:.0f})")

    # R:R < 2:1
    if rr < 2:
        hard_failures.append(f"R:R {rr}:1 below minimum 2:1")

    # Max 5 positions
    if state["open_positions"] >= 5:
        hard_failures.append(f"Already at max positions ({state['open_positions']})")

    # Not enough cash
    if position_value > state["cash_available"]:
        hard_failures.append(f"Position ${position_value:.0f} exceeds cash ${state['cash_available']:.0f}")

    # If hard rules failed, no AI call needed
    if hard_failures:
        output = {
            "approved": False,
            "reason": "; ".join(hard_failures),
            "warnings": hard_failures,
            "risk_score": 1,
            "hard_block": True,
        }
        log_agent_run(
            event_id=event.get("event_id"),
            agent="risk",
            model="hard_rules",
            input={"ticker": ticker, "research": research_output},
            output=output,
            duration_ms=1,
        )
        return output

    # AI check for soft rules: correlation, sector concentration, timing
    client = get_client()
    if not client:
        # No AI, but hard rules passed — approve
        output = {
            "approved": True,
            "reason": "Hard rules passed, AI risk check unavailable",
            "warnings": [],
            "risk_score": 6,
        }
        log_agent_run(
            event_id=event.get("event_id"),
            agent="risk",
            model="hard_rules",
            input={"ticker": ticker, "research": research_output},
            output=output,
            duration_ms=1,
        )
        return output

    positions_summary = ", ".join(
        f"{p['ticker']} {p['direction']} ({p['quantity']} sh)"
        for p in state["positions"]
    ) or "None"

    prompt = f"""You are a Risk Agent. The trade below passed hard rules. Now check soft risks.

PROPOSED TRADE:
- {direction} {ticker} @ ${entry}, stop ${stop}, target ${research_output.get('target1')}
- {shares} shares = ${position_value:.0f} ({position_value/portfolio_size*100:.1f}% of portfolio)
- R:R = {rr}:1
- Risk: ${risk_dollars:.0f}
- Thesis: {research_output.get('thesis', '')[:300]}

CURRENT PORTFOLIO STATE:
- Open positions: {state['open_positions']}/5
- Currently holding: {positions_summary}
- Cash available: ${state['cash_available']:.0f} ({state['cash_pct']}%)

CHECK FOR:
1. Sector correlation — does this overlap with existing positions?
2. Direction conflict — are we already short something correlated?
3. Timing — does this trade make sense in current market conditions?
4. Concentration — is this too much in one theme?

Respond ONLY with JSON (no markdown):
{{
  "approved": true | false,
  "reason": "one sentence — final approval/rejection rationale",
  "warnings": ["w1", "w2"],
  "risk_score": <1-10, where 10 is lowest risk>,
  "adjustments": {{
    "suggested_shares": <if you want to reduce size>
  }}
}}"""

    start = time.time()
    output = {}
    error = ""
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
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
        output = {"approved": False, "reason": f"Risk check error: {e}", "risk_score": 0}
        tokens_in = tokens_out = 0
        cost = 0

    duration_ms = int((time.time() - start) * 1000)
    log_agent_run(
        event_id=event.get("event_id"),
        agent="risk",
        model=MODEL,
        input={"ticker": ticker, "portfolio": state},
        output=output,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        status="error" if error else "success",
        error=error,
    )

    return output
