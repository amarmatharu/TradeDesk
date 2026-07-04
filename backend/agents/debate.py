"""
Researcher Debate (Phase 1 — decision quality).

The single-prompt Research → Trader path collapses competing views into one
voice, which is exactly how confirmation bias sneaks in (the system's own
journal flagged `chased_entry` / `thesis_drift` as top killers). Following the
TradingAgents pattern, this stage pits a committed BULL advocate against a
committed BEAR advocate on the concrete trade plan, then hands both cases to the
Trader to synthesize.

Two Sonnet calls, run concurrently. ~1-2 trades/day reach here, so the added
cost/latency is negligible. Fails open: if the debate errors, the pipeline
proceeds without it (Trader just doesn't get the extra context).
"""

import json
import time
import asyncio
from ai_brain import get_client
from event_bus import log_agent_run

MODEL = "claude-sonnet-4-6"


def _side_prompt(side: str, event: dict, research: dict) -> str:
    stance = ("You are the BULL. Argue AS STRONGLY AS THE EVIDENCE ALLOWS that this "
              "trade WILL work. Marshal the catalysts, technicals and asymmetry."
              if side == "bull" else
              "You are the BEAR. Argue AS STRONGLY AS THE EVIDENCE ALLOWS that this "
              "trade will FAIL. Attack the thesis: what's already priced in, what "
              "breaks it, why the entry is a chase, what the tape is really saying.")
    return f"""{stance}
You are debating a specific proposed trade. Be concrete and cite the actual numbers.
Do NOT be wishy-washy — take your side. The opposing advocate will make the other case;
a Trader will weigh both.

EVENT: {event.get('title','')[:200]}

PROPOSED TRADE:
- {research.get('direction')} {research.get('ticker')}
- Thesis: {research.get('thesis')}
- Entry ${research.get('entry')} / Stop ${research.get('stop')} / T1 ${research.get('target1')} / T2 ${research.get('target2')}
- R:R computed: {research.get('rr_computed')}  Research confidence: {research.get('confidence')}/10
- Catalysts: {research.get('catalysts','')}  Risks: {research.get('risks','')}

Respond ONLY with JSON (no markdown):
{{
  "stance": "{side}",
  "strongest_points": ["3-5 punchy, specific bullet points"],
  "key_risk_to_my_side": "the single best argument against my own position",
  "conviction": <1-10 how strong your case honestly is>
}}"""


async def _run_side(side: str, event: dict, research: dict) -> dict:
    client = get_client()
    if not client:
        return {"stance": side, "error": "no client", "strongest_points": [], "conviction": 0}
    start = time.time()
    output, error = {}, ""
    tokens_in = tokens_out = 0
    cost = 0.0
    try:
        resp = await asyncio.to_thread(
            client.messages.create,
            model=MODEL, max_tokens=500,
            messages=[{"role": "user", "content": _side_prompt(side, event, research)}],
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        output = json.loads(text)
        tokens_in = getattr(resp.usage, "input_tokens", 0)
        tokens_out = getattr(resp.usage, "output_tokens", 0)
        cost = (tokens_in * 3.0 + tokens_out * 15.0) / 1_000_000
    except Exception as e:
        error = str(e)
        output = {"stance": side, "error": error, "strongest_points": [], "conviction": 0}
    log_agent_run(
        event_id=event.get("event_id"), agent=f"debate_{side}", model=MODEL,
        input={"ticker": research.get("ticker")}, output=output,
        duration_ms=int((time.time() - start) * 1000),
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
        status="error" if error else "success", error=error,
    )
    return output


async def debate(event: dict, research: dict) -> dict:
    """Run bull vs bear concurrently. Returns both cases + a simple net signal
    (bull conviction − bear conviction) the Trader can weigh."""
    try:
        bull, bear = await asyncio.gather(
            _run_side("bull", event, research),
            _run_side("bear", event, research),
        )
    except Exception as e:
        return {"available": False, "error": str(e)[:160]}
    net = (bull.get("conviction", 0) or 0) - (bear.get("conviction", 0) or 0)
    return {
        "available": True,
        "bull": bull,
        "bear": bear,
        "net_conviction": net,   # >0 bull-leaning, <0 bear-leaning
        "verdict": "bull-leaning" if net > 1 else "bear-leaning" if net < -1 else "contested",
    }
