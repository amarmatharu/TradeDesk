"""
Benzinga real-time news feed.
Polls Benzinga API every 20s for breaking news, scores each story with Claude,
and pushes high-conviction alerts to connected SSE clients.
"""

import os
import asyncio
import time
import json
import hashlib
import re
from datetime import datetime, timedelta
from typing import Callable, Optional
import httpx

# ─── Benzinga REST client ──────────────────────────────────────────────────────

BENZINGA_BASE = "https://api.benzinga.com/api/v2"
BENZINGA_BASE_V1 = "https://api.benzinga.com/api/v1"

_seen_ids: set = set()          # deduplicate articles across polls
_subscribers: list = []         # SSE subscriber queues
_recent: list = []              # replay buffer for new SSE connections
_MAX_RECENT = 100
_feed_running = False


def get_bz_key() -> str:
    return os.environ.get("BENZINGA_API_KEY", "").strip()


async def fetch_news(tickers: Optional[list] = None, limit: int = 20) -> list:
    key = get_bz_key()
    if not key:
        return []

    params = {
        "token": key,
        "pageSize": limit,
        "displayOutput": "full",
        "sort": "created:desc",
    }
    if tickers:
        params["tickers"] = ",".join(tickers)

    headers = {"Accept": "application/json", "Accept-Encoding": "gzip"}
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        try:
            r = await client.get(f"{BENZINGA_BASE}/news", params=params)
            r.raise_for_status()
            text = r.text.strip()
            if not text:
                print("[Benzinga] Empty response from news endpoint")
                return []
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("news", data.get("result", []))
        except Exception as e:
            print(f"[Benzinga] fetch_news error: {e}")
            return []


async def fetch_calendar_earnings(days_ahead: int = 7) -> list:
    key = get_bz_key()
    if not key:
        return []
    date_from = datetime.now().strftime("%Y-%m-%d")
    date_to = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    params = {"token": key, "dateFrom": date_from, "dateTo": date_to, "pageSize": 50}
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(f"{BENZINGA_BASE}/calendar/earnings", params=params)
            r.raise_for_status()
            data = r.json()
            return data.get("earnings", [])
        except Exception as e:
            print(f"[Benzinga] fetch_earnings error: {e}")
            return []


async def fetch_calendar_fda(days_ahead: int = 14) -> list:
    key = get_bz_key()
    if not key:
        return []
    date_from = datetime.now().strftime("%Y-%m-%d")
    date_to = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    params = {"token": key, "dateFrom": date_from, "dateTo": date_to, "pageSize": 50}
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(f"{BENZINGA_BASE}/calendar/fda", params=params)
            r.raise_for_status()
            data = r.json()
            return data.get("fda", [])
        except Exception as e:
            print(f"[Benzinga] fetch_fda error: {e}")
            return []


# ─── Article scoring ──────────────────────────────────────────────────────────

IMPACT_KEYWORDS = {
    "critical": ["merger", "acquisition", "takeover", "buyout", "fda approval", "fda rejection",
                 "bankruptcy", "sec investigation", "ceo resign", "ceo fired", "going private",
                 "delisted", "fraud", "restatement", "clinical trial", "breakthrough"],
    "high": ["earnings beat", "earnings miss", "raised guidance", "lowered guidance",
             "analyst upgrade", "analyst downgrade", "price target", "short squeeze",
             "insider buying", "buyback", "dividend", "partnership", "contract won",
             "layoffs", "revenue beat", "revenue miss"],
    "medium": ["product launch", "expansion", "hiring", "regulatory", "patent", "lawsuit"],
}

def quick_score(article: dict) -> dict:
    """Fast keyword-based scoring before AI scoring."""
    title = (article.get("title") or "").lower()
    body = (article.get("body") or article.get("text") or "").lower()[:500]
    combined = title + " " + body

    impact = "LOW"
    score = 3
    for kw in IMPACT_KEYWORDS["critical"]:
        if kw in combined:
            impact = "CRITICAL"
            score = 9
            break
    if impact == "LOW":
        for kw in IMPACT_KEYWORDS["high"]:
            if kw in combined:
                impact = "HIGH"
                score = 7
                break
    if impact == "LOW":
        for kw in IMPACT_KEYWORDS["medium"]:
            if kw in combined:
                impact = "MEDIUM"
                score = 5
                break

    # Extract tickers from article
    tickers = []
    if article.get("stocks"):
        tickers = [s.get("name", "") for s in article["stocks"] if s.get("name")]
    elif article.get("tickers"):
        tickers = article["tickers"] if isinstance(article["tickers"], list) else [article["tickers"]]

    return {
        "id": article.get("id") or hashlib.md5((article.get("title","") + str(article.get("created",""))).encode()).hexdigest()[:12],
        "title": article.get("title", ""),
        "body": (article.get("body") or article.get("text") or "")[:400],
        "url": article.get("url") or article.get("link") or "",
        "source": article.get("author") or article.get("source") or "Benzinga",
        "published": article.get("created") or article.get("publishedDate") or datetime.utcnow().isoformat(),
        "tickers": tickers,
        "impact": impact,
        "score": score,
        "ai_score": None,
        "ai_action": None,
        "ai_summary": None,
    }


async def ai_score_article(article: dict) -> dict:
    """Use Claude Haiku to score tradability of a news article."""
    try:
        from ai_brain import get_client
        client = get_client()
        if not client:
            return article

        prompt = f"""You are a trading news analyst. Score this news item for trading edge.

TITLE: {article['title']}
BODY: {article['body'][:300]}
TICKERS: {', '.join(article['tickers']) or 'General market'}

Respond ONLY with JSON (no markdown):
{{
  "score": 1-10,
  "action": "BUY" | "SELL" | "WATCH" | "IGNORE",
  "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
  "urgency": "IMMEDIATE" | "TODAY" | "THIS_WEEK" | "LOW",
  "summary": "one line — what this means for traders",
  "why": "one line — why this moves the stock"
}}"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        scored = json.loads(text)
        article["ai_score"] = scored.get("score")
        article["ai_action"] = scored.get("action")
        article["ai_direction"] = scored.get("direction")
        article["ai_urgency"] = scored.get("urgency")
        article["ai_summary"] = scored.get("summary")
        article["ai_why"] = scored.get("why")
        # Upgrade impact if AI scored high
        if scored.get("score", 0) >= 8:
            article["impact"] = "CRITICAL"
        elif scored.get("score", 0) >= 6:
            article["impact"] = max(article["impact"], "HIGH")
    except Exception as e:
        print(f"[Benzinga] AI score error: {e}")
    return article


# ─── SSE broadcast ────────────────────────────────────────────────────────────

def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    # Replay recent articles to new subscriber immediately
    for event in _recent:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            break
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    if q in _subscribers:
        _subscribers.remove(q)


async def broadcast(event: dict):
    global _recent
    _recent.append(event)
    if len(_recent) > _MAX_RECENT:
        _recent = _recent[-_MAX_RECENT:]
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)

    # Publish to central event bus for agent processing
    try:
        from event_bus import publish as bus_publish
        data = event.get("data", {})
        await bus_publish(
            source="benzinga",
            type="news",
            data=data,
            tickers=data.get("tickers", []),
            title=data.get("title", "")[:300],
            impact=data.get("impact", "MEDIUM"),
        )
    except Exception as e:
        print(f"[Benzinga] Bus publish error: {e}")


# ─── Background polling loop ──────────────────────────────────────────────────

async def _poll_loop(watchlist_fn: Callable, interval: int = 20):
    global _seen_ids, _feed_running
    _feed_running = True
    print("[Benzinga] Feed started — polling whole market every", interval, "seconds")

    while _feed_running:
        try:
            # MARKET-WIDE: pull all market news, not just watchlist tickers.
            # Scout will triage; Research only runs on high-conviction events.
            # Watchlist tickers will get bonus weight in Scout scoring via context.
            articles = await fetch_news(tickers=None, limit=50)

            new_articles = []
            for raw in articles:
                scored = quick_score(raw)
                if scored["id"] in _seen_ids:
                    continue
                _seen_ids.add(scored["id"])
                new_articles.append(scored)

            # AI score anything that passed keyword filter (score ≥ 5)
            for article in new_articles:
                if article["score"] >= 5:
                    article = await ai_score_article(article)

                # Broadcast to SSE listeners
                final_score = article.get("ai_score") or article["score"]
                await broadcast({
                    "type": "news",
                    "data": article,
                    "ts": time.time(),
                })
                print(f"[Benzinga] [{article['impact']}] {article['title'][:70]} — score {final_score}")

        except Exception as e:
            print(f"[Benzinga] Poll error: {e}")

        await asyncio.sleep(interval)


_poll_task = None

def start_feed(watchlist_fn: Callable, interval: int = 20):
    global _poll_task
    import asyncio
    loop = asyncio.get_event_loop()
    _poll_task = loop.create_task(_poll_loop(watchlist_fn, interval))
    return _poll_task


def stop_feed():
    global _feed_running, _poll_task
    _feed_running = False
    if _poll_task:
        _poll_task.cancel()
