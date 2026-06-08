import os
import anthropic
import json

_PLACEHOLDER = "your_key_here"


def get_client():
    """Always read from env so key updates in Settings take effect immediately."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key == _PLACEHOLDER:
        return None
    return anthropic.Anthropic(api_key=api_key)


def reset_client():
    """No-op now that we don't cache — kept for API compatibility."""
    pass


def analyze_trade(ticker: str, info: dict, technicals: dict, news: list, portfolio_size: float = 25000) -> dict:
    c = get_client()
    if not c:
        return {"error": "ANTHROPIC_API_KEY not set. Add it to backend/.env"}

    news_text = "\n".join([f"- {n.get('title','')}: {n.get('summary','')[:150]}" for n in news[:5]])

    prompt = f"""You are an expert swing trader and analyst. Analyze ${ticker} and provide a structured trade recommendation.

FUNDAMENTAL DATA:
- Sector: {info.get('sector')} | Industry: {info.get('industry')}
- Current Price: ${info.get('current_price')}
- Market Cap: {info.get('market_cap')}
- P/E: {info.get('pe_ratio')} | Forward P/E: {info.get('forward_pe')}
- Revenue Growth: {info.get('revenue_growth')} | Earnings Growth: {info.get('earnings_growth')}
- Profit Margin: {info.get('profit_margins')} | ROE: {info.get('return_on_equity')}
- Debt/Equity: {info.get('debt_to_equity')} | Free Cash Flow: {info.get('free_cashflow')}
- Beta: {info.get('beta')} | Short Ratio: {info.get('short_ratio')}
- Analyst Target: ${info.get('analyst_target')} | Rating: {info.get('analyst_rating')} (lower=better, 1=strong buy)
- 52W High: ${info.get('52w_high')} | 52W Low: ${info.get('52w_low')}

TECHNICAL DATA:
- Trend: {technicals.get('trend')} (EMA20={technicals.get('ema20')}, EMA50={technicals.get('ema50')}, EMA200={technicals.get('ema200')})
- RSI: {technicals.get('rsi')} ({technicals.get('rsi_signal')})
- MACD Cross: {technicals.get('macd_cross')} (MACD={technicals.get('macd')}, Signal={technicals.get('macd_signal')})
- Bollinger Band %: {technicals.get('bb_pct')} (Upper={technicals.get('bb_upper')}, Lower={technicals.get('bb_lower')})
- ATR: {technicals.get('atr')} ({technicals.get('atr_pct')}% of price)
- Support: ${technicals.get('support')} | Resistance: ${technicals.get('resistance')}
- Price vs EMA20: {technicals.get('price_vs_ema20_pct')}%

RECENT NEWS:
{news_text}

RISK PARAMETERS:
- Portfolio: ${portfolio_size}
- Max risk per trade: 1.5% (${portfolio_size * 0.015:.0f})
- Min R:R required: 2:1

Respond ONLY with a JSON object (no markdown, no explanation outside JSON):
{{
  "action": "BUY" | "SELL_SHORT" | "WATCH" | "AVOID",
  "conviction": "HIGH" | "MEDIUM" | "LOW",
  "strategy": "brief strategy name (e.g. EMA Pullback, Breakout, Mean Reversion)",
  "thesis": "2-3 sentence trade thesis",
  "entry_price": number,
  "entry_condition": "specific entry trigger",
  "stop_loss": number,
  "target1": number,
  "target2": number,
  "target3": number,
  "risk_reward": number,
  "time_horizon": "X-Y days",
  "position_size_shares": number,
  "position_value": number,
  "risk_dollars": number,
  "catalysts": ["catalyst1", "catalyst2"],
  "risks": ["risk1", "risk2"],
  "sentiment_score": number between -1 and 1,
  "fundamental_score": number 1-10,
  "technical_score": number 1-10,
  "overall_score": number 1-10,
  "news_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "summary": "one line executive summary"
}}"""

    try:
        response = c.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Clean up if wrapped in markdown
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}", "raw": text[:500]}
    except Exception as e:
        return {"error": str(e)}


def score_news_sentiment(news: list) -> dict:
    c = get_client()
    if not c or not news:
        return {"sentiment": "NEUTRAL", "score": 0, "summary": "No data"}

    headlines = "\n".join([f"- {n.get('title','')}" for n in news[:8]])
    prompt = f"""Analyze these stock news headlines and return ONLY valid JSON (no markdown):
{headlines}

Return: {{"sentiment": "BULLISH"|"BEARISH"|"NEUTRAL", "score": -1.0 to 1.0, "summary": "one line", "key_themes": ["theme1", "theme2"]}}"""

    try:
        response = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return {"sentiment": "NEUTRAL", "score": 0, "summary": "Analysis unavailable"}
