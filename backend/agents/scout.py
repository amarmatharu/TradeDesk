"""
Scout Agent — Triage every event.
Fast, cheap (Claude Haiku). Sole job: is this tradable? Score 1-10.
Filters thousands of events into the 10-20 worth investigating.
"""

import json
import time
import asyncio
from ai_brain import get_client
from event_bus import log_agent_run

MODEL = "claude-haiku-4-5-20251001"
SCOUT_THRESHOLD = 7   # events with score ≥ this advance to Research


async def scout(event: dict) -> dict:
    """
    Returns:
    {
      "tradable_score": 1-10,
      "direction": "BULLISH|BEARISH|NEUTRAL",
      "tickers": ["XXX"],
      "urgency": "IMMEDIATE|TODAY|THIS_WEEK|LOW",
      "one_liner": "what this means for traders",
      "should_research": bool
    }
    """
    client = get_client()
    if not client:
        return {"tradable_score": 0, "should_research": False, "error": "No Anthropic API key"}

    # Build prompt based on event type
    title = event.get("title", "")
    impact = event.get("impact", "")
    data = event.get("data", {})
    source = event.get("source", "")
    type_ = event.get("type", "")
    tickers_hint = event.get("tickers", [])

    # Get user's watchlist for context — watchlist tickers get priority weight
    watchlist = []
    try:
        from database import get_connection
        conn = get_connection()
        watchlist = [r["ticker"] for r in conn.execute("SELECT ticker FROM watchlist").fetchall()]
        conn.close()
    except Exception:
        pass
    on_watchlist = any(t.upper() in [w.upper() for w in watchlist] for t in (tickers_hint or []))

    # Extract relevant context per event type
    if type_ == "news" or source == "benzinga":
        body = (data.get("body") or data.get("summary") or "")[:400]
        context = f"Source: Benzinga News\nTitle: {title}\nBody: {body}\nKeyword: {data.get('signal','')}"
    elif type_ == "edgar_8k" or "8-K" in type_:
        items = data.get("title", "") or data.get("items", "")
        company = data.get("company", "")
        keyword = data.get("keyword", "")
        context = f"Source: SEC 8-K Filing\nCompany: {company}\nFiling items: {items}\nKeyword match: {keyword}"
    elif type_ == "insider_cluster":
        company = data.get("company", "")
        n = data.get("distinct_insiders", 0)
        value = data.get("total_value", 0)
        qualified = data.get("smallcap_qualified", False)
        screen = data.get("screen", {})
        context = (f"Source: SEC Form 4 INSIDER CLUSTER (high-edge signal)\n"
                   f"Company: {company} ({data.get('ticker')})\n"
                   f"{n} DISTINCT insiders bought within {data.get('window_days')} days, total ${value:,.0f}\n"
                   f"Small-cap qualified: {qualified} ({screen.get('reason','')})\n"
                   f"NOTE: Cluster insider buying on under-covered small caps is one of the few "
                   f"academically-documented retail edges. Weight this heavily if small-cap qualified.")
    elif type_ == "edgar_form4":
        company = data.get("company", "")
        insider = data.get("insider", "")
        role = data.get("role", "")
        value = data.get("total_value", 0)
        action = "INSIDER BUY" if data.get("buys", 0) > 0 else "INSIDER SELL"
        context = f"Source: SEC Form 4\nCompany: {company}\nInsider: {insider} ({role})\nAction: {action} ${value:,.0f}"
    else:
        context = f"Source: {source}\nType: {type_}\nTitle: {title}"

    # Phase 4: Inject accumulated learnings
    playbook = ""
    try:
        from agents.journal import format_playbook_for_prompt
        playbook = format_playbook_for_prompt()
    except Exception:
        pass

    playbook_block = f"\n\nSYSTEM LEARNINGS (from past trades):\n{playbook}\n" if playbook else ""

    watchlist_note = ""
    if on_watchlist:
        watchlist_note = f"\n📌 NOTE: This event involves a watchlist ticker the user actively tracks ({watchlist}). Give it modestly higher attention but still score on merit alone."

    prompt = f"""You are a Scout Agent. Triage this event for trading edge.
Be ruthlessly selective — only score 7+ if there's a clear, tradable setup.
You are scanning the ENTIRE market — not just the user's watchlist.
A great catalyst on an unknown ticker is more valuable than weak news on a known one.
{watchlist_note}
{playbook_block}
EVENT:
{context}

Tickers mentioned: {tickers_hint}

Respond ONLY with JSON (no markdown):
{{
  "tradable_score": <1-10, where 7+ means worth researching>,
  "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
  "tickers": [list of relevant tickers to investigate],
  "urgency": "IMMEDIATE" | "TODAY" | "THIS_WEEK" | "LOW",
  "one_liner": "one sentence — why this matters for traders",
  "category": "M&A" | "FDA" | "EARNINGS" | "GUIDANCE" | "ANALYST" | "INSIDER" | "MACRO" | "PRODUCT" | "OTHER",
  "reasoning": "one sentence — why you scored it this way"
}}

Scoring guide:
- 9-10: Major catalyst (M&A confirmed, FDA approval, earnings beat with raised guidance)
- 7-8: Strong directional signal (price target hike, insider buy >$1M, analyst upgrade)
- 5-6: Possible signal but unclear (mixed news, lower-impact filing)
- 1-4: Noise (routine filings, market commentary, opinion pieces)"""

    start = time.time()
    output = {}
    error = ""
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        output = json.loads(text)
        output["should_research"] = output.get("tradable_score", 0) >= SCOUT_THRESHOLD

        tokens_in = resp.usage.input_tokens if hasattr(resp, 'usage') else 0
        tokens_out = resp.usage.output_tokens if hasattr(resp, 'usage') else 0
        # Haiku 4.5 pricing: $0.80/MTok in, $4/MTok out
        cost = (tokens_in * 0.80 + tokens_out * 4.0) / 1_000_000
    except Exception as e:
        error = str(e)
        output = {"tradable_score": 0, "should_research": False, "error": error}
        tokens_in = tokens_out = 0
        cost = 0

    duration_ms = int((time.time() - start) * 1000)

    # Log to DB
    log_agent_run(
        event_id=event.get("event_id"),
        agent="scout",
        model=MODEL,
        input={"context": context[:500], "tickers": tickers_hint},
        output=output,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        status="error" if error else "success",
        error=error,
    )

    return output
