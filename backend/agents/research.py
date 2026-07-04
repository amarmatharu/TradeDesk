"""
Research Agent — Deep thinker.
Triggered when Scout returns score ≥7.
Pulls live price, technicals, fundamentals, and builds full trade thesis.
"""

import json
import time
from ai_brain import get_client
from event_bus import log_agent_run
from alpaca_data import get_snapshot, get_technicals, get_stock_info

MODEL = "claude-sonnet-4-6"


async def research(event: dict, scout_output: dict, portfolio_size: float = 25000) -> dict:
    """
    Returns a complete trade plan:
    {
      "ticker": "XXX",
      "direction": "LONG|SHORT",
      "thesis": "...",
      "entry": number,
      "stop": number,
      "target1": number,
      "target2": number,
      "risk_reward": number,
      "shares": number,
      "risk_dollars": number,
      "position_value": number,
      "time_horizon": "X-Y days",
      "confidence": 1-10,
      "catalysts": [...],
      "risks": [...]
    }
    """
    client = get_client()
    if not client:
        return {"error": "No Anthropic API key", "confidence": 0}

    tickers = scout_output.get("tickers", [])
    if not tickers:
        return {"error": "No tickers to research", "confidence": 0}

    primary_ticker = tickers[0].upper()

    # Pull live market data
    snap = get_snapshot(primary_ticker)
    tech = get_technicals(primary_ticker)
    info = get_stock_info(primary_ticker)

    if not snap.get("price"):
        return {"error": f"No live price data for {primary_ticker}", "confidence": 0}

    market_data = f"""
TICKER: {primary_ticker}
Current Price: ${snap.get('price')}
Today's Change: {snap.get('change_pct', 0):+.2f}%
Day Range: ${snap.get('low')} - ${snap.get('high')}
Volume: {snap.get('volume'):,}

TECHNICALS:
- Trend: {tech.get('trend')}
- RSI: {tech.get('rsi', 0):.1f} ({tech.get('rsi_signal')})
- MACD: {tech.get('macd_cross')}
- EMA20: ${tech.get('ema20')}
- EMA50: ${tech.get('ema50')}
- EMA200: ${tech.get('ema200')}
- Support (20-day low): ${tech.get('support')}
- Resistance (20-day high): ${tech.get('resistance')}
- ATR: {tech.get('atr_pct', 0):.1f}% (volatility)
- BB position: {tech.get('bb_pct', 0):.2f} (0=lower, 1=upper)

FUNDAMENTALS:
- Sector: {info.get('sector', 'N/A')} / {info.get('industry', 'N/A')}
- P/E: {info.get('pe_ratio')}
- Beta: {info.get('beta')}
- 52W Range: ${info.get('52w_low')} - ${info.get('52w_high')}
- Analyst Target: ${info.get('analyst_target')}
"""

    event_context = f"""
EVENT TRIGGERING RESEARCH:
Title: {event.get('title', '')}
Source: {event.get('source')}
Impact: {event.get('impact')}
Scout score: {scout_output.get('tradable_score')}/10
Scout direction: {scout_output.get('direction')}
Scout one-liner: {scout_output.get('one_liner')}
Category: {scout_output.get('category', 'OTHER')}
Urgency: {scout_output.get('urgency')}
"""

    risk_per_trade = portfolio_size * 0.015

    # Phase 4: Inject accumulated learnings
    playbook = ""
    try:
        from agents.journal import format_playbook_for_prompt
        playbook = format_playbook_for_prompt()
    except Exception:
        pass

    playbook_block = f"\n\nSYSTEM LEARNINGS — treat HARD AVOID items as rules, not hints:\n{playbook}\n" if playbook else ""

    prompt = f"""You are a Research Agent. Build a complete trade plan from this event + market data.
{playbook_block}
{event_context}

{market_data}

RISK PARAMETERS:
- Portfolio: ${portfolio_size:,.0f}
- Max risk per trade: 1.5% = ${risk_per_trade:.0f}
- Min R:R required: 2.5:1 (ENFORCED in code from entry/stop/target1 — trades below this are auto-rejected, so set targets/stops accordingly)
- Time horizon: 3-15 day swing trades

Build a complete trade plan. Be specific with prices anchored to the actual current price and technicals.

Respond ONLY with JSON (no markdown):
{{
  "ticker": "{primary_ticker}",
  "direction": "LONG" | "SHORT" | "NO_TRADE",
  "thesis": "2-3 sentences — why this trade works",
  "entry": <price>,
  "entry_condition": "specific trigger to enter",
  "stop": <price>,
  "target1": <price>,
  "target2": <price>,
  "risk_reward": <T1 R:R>,
  "shares": <calculated based on risk>,
  "risk_dollars": <actual risk per trade>,
  "position_value": <shares * entry>,
  "time_horizon": "X-Y days",
  "confidence": <1-10>,
  "catalysts": ["c1", "c2"],
  "risks": ["r1", "r2"],
  "invalidation": "what kills this thesis",
  "key_levels": {{"resistance": [], "support": []}}
}}

If the event doesn't warrant a trade given technicals, return direction: "NO_TRADE" with confidence ≤3 and explain in thesis."""

    start = time.time()
    output = {}
    error = ""
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1500,
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
        # Sonnet 4.6 pricing: $3/MTok in, $15/MTok out
        cost = (tokens_in * 3.0 + tokens_out * 15.0) / 1_000_000
    except Exception as e:
        error = str(e)
        output = {"error": error, "confidence": 0, "direction": "NO_TRADE"}
        tokens_in = tokens_out = 0
        cost = 0

    duration_ms = int((time.time() - start) * 1000)

    log_agent_run(
        event_id=event.get("event_id"),
        agent="research",
        model=MODEL,
        input={"ticker": primary_ticker, "scout": scout_output},
        output=output,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        status="error" if error else "success",
        error=error,
    )

    return output
