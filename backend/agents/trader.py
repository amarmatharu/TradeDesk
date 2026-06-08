"""
Trader Agent — Final decision maker.
The only agent that creates pending trades.
"""

import json
import time
from ai_brain import get_client
from event_bus import log_agent_run
from database import get_connection

MODEL = "claude-sonnet-4-6"   # Could upgrade to opus for higher conviction trades


async def trade_decision(event: dict, scout_output: dict, research_output: dict,
                         risk_output: dict) -> dict:
    """
    Final decision: BUY | WAIT | PASS
    Returns:
    {
      "action": "BUY" | "WAIT" | "PASS",
      "confidence": 1-10,
      "reasoning": "...",
      "final_shares": int,
      "final_entry": float,
      "final_stop": float,
      "final_target1": float,
      "final_target2": float
    }
    """
    if not risk_output.get("approved"):
        # Hard block — never trade if risk vetoes
        output = {
            "action": "PASS",
            "confidence": 0,
            "reasoning": f"Risk veto: {risk_output.get('reason', 'unknown')}",
        }
        log_agent_run(
            event_id=event.get("event_id"),
            agent="trader",
            model="auto_pass",
            input={"reason": "risk_vetoed"},
            output=output,
            duration_ms=1,
        )
        return output

    client = get_client()
    if not client:
        return {"action": "PASS", "confidence": 0, "reasoning": "No AI client"}

    prompt = f"""You are the Trader Agent. You are the final decision-maker.
Synthesize all agent outputs into a clear action.

SCOUT (initial triage):
- Score: {scout_output.get('tradable_score')}/10
- Direction: {scout_output.get('direction')}
- Category: {scout_output.get('category')}
- Urgency: {scout_output.get('urgency')}
- One-liner: {scout_output.get('one_liner')}

RESEARCH (deep dive):
- Ticker: {research_output.get('ticker')}
- Direction: {research_output.get('direction')}
- Thesis: {research_output.get('thesis')}
- Entry: ${research_output.get('entry')}, Stop: ${research_output.get('stop')}
- T1: ${research_output.get('target1')}, T2: ${research_output.get('target2')}
- R:R: {research_output.get('risk_reward')}:1
- Confidence: {research_output.get('confidence')}/10
- Invalidation: {research_output.get('invalidation', '')}

RISK CHECK:
- Approved: {risk_output.get('approved')}
- Risk score: {risk_output.get('risk_score')}/10
- Warnings: {risk_output.get('warnings', [])}
- Suggested adjustments: {risk_output.get('adjustments', {})}

Decide:
- BUY: All signals aligned, confidence high, execute now
- WAIT: Good setup but not optimal timing/price — wait for better entry
- PASS: Not worth the risk/setup is weak/conflicts with portfolio

Respond ONLY with JSON (no markdown):
{{
  "action": "BUY" | "WAIT" | "PASS",
  "confidence": <1-10>,
  "reasoning": "2 sentences max — why this final call",
  "wait_condition": "if WAIT, what would trigger BUY",
  "final_shares": <use risk adjustments if any, else research value>,
  "final_entry": <price>,
  "final_stop": <price>,
  "final_target1": <price>,
  "final_target2": <price>
}}"""

    start = time.time()
    output = {}
    error = ""
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
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
        output = {"action": "PASS", "confidence": 0, "reasoning": f"Error: {e}"}
        tokens_in = tokens_out = 0
        cost = 0

    duration_ms = int((time.time() - start) * 1000)
    log_agent_run(
        event_id=event.get("event_id"),
        agent="trader",
        model=MODEL,
        input={
            "scout": scout_output.get("tradable_score"),
            "research": research_output.get("confidence"),
            "risk": risk_output.get("risk_score"),
        },
        output=output,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        status="error" if error else "success",
        error=error,
    )

    return output


def create_pending_trade(event: dict, scout_out: dict, research_out: dict,
                         risk_out: dict, trader_out: dict) -> int:
    """Save approved trade to pending_trades for user review."""
    if trader_out.get("action") != "BUY":
        return 0

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pending_trades (
            event_id, ticker, direction, entry, stop, target1, target2,
            shares, risk_dollars, position_value, thesis, confidence,
            scout_output, research_output, risk_output, trader_output
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("event_id"),
        research_out.get("ticker"),
        research_out.get("direction"),
        trader_out.get("final_entry") or research_out.get("entry"),
        trader_out.get("final_stop") or research_out.get("stop"),
        trader_out.get("final_target1") or research_out.get("target1"),
        trader_out.get("final_target2") or research_out.get("target2"),
        trader_out.get("final_shares") or research_out.get("shares"),
        research_out.get("risk_dollars"),
        research_out.get("position_value"),
        research_out.get("thesis"),
        trader_out.get("confidence"),
        json.dumps(scout_out)[:5000],
        json.dumps(research_out)[:5000],
        json.dumps(risk_out)[:5000],
        json.dumps(trader_out)[:5000],
    ))
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id
