import os
import json
from dotenv import load_dotenv, set_key, dotenv_values

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
_PLACEHOLDER = "your_key_here"

def _load_env():
    """Read .env and set os.environ, stripping quotes and placeholders."""
    load_dotenv(ENV_PATH, override=True)
    # Fallback: parse .env manually in case dotenv misses it
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, _, v = line.partition('=')
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                if v and v != _PLACEHOLDER:
                    os.environ[k] = v
                elif v == _PLACEHOLDER and k in os.environ:
                    del os.environ[k]

_load_env()

# Global network timeout — no socket read can hang forever (today's freeze cause)
import socket as _socket
_socket.setdefaulttimeout(20)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Any, Dict
import sqlite3
import asyncio
import time
from datetime import datetime

from database import init_db, get_connection
from alpaca_data import (
    get_stock_info, get_ohlcv, get_technicals,
    get_market_overview, get_snapshot,
)
from market_data import get_news, calculate_position_size
from ai_brain import analyze_trade, score_news_sentiment, reset_client
import benzinga_feed
import edgar_feed
import event_bus
from agents import orchestrator as agent_orchestrator
from agents import monitor as agent_monitor
import auto_scanner

app = FastAPI(title="Trading Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# ─── Benzinga feed startup ─────────────────────────────────────────────────────
def _get_watchlist_tickers():
    try:
        conn = get_connection()
        rows = conn.execute("SELECT ticker FROM watchlist").fetchall()
        conn.close()
        return [{"ticker": r["ticker"]} for r in rows]
    except Exception:
        return []

@app.on_event("startup")
async def startup_event():
    if os.environ.get("BENZINGA_API_KEY", "").strip():
        benzinga_feed.start_feed(_get_watchlist_tickers, interval=20)
        print("[TradeDesk] Benzinga feed started")
    else:
        print("[TradeDesk] No Benzinga key — news feed not started")
    # SEC EDGAR feed — always on, no key required
    edgar_feed.start_feed(interval=60)
    print("[TradeDesk] SEC EDGAR feed started")
    # Register agent orchestrator with event bus
    event_bus.register_agent_handler(agent_orchestrator.handle_event)
    print(f"[TradeDesk] Agent orchestrator registered (mode: {agent_orchestrator.get_mode()})")
    # Position monitor — runs every 60s, watches open positions
    agent_monitor.start_monitor(interval=60)
    print("[TradeDesk] Position Monitor started")
    # Auto-scanner — runs full market scan every 30 min during market hours
    auto_scanner.start_auto_scanner(interval_minutes=30)
    print("[TradeDesk] Auto-Scanner started")
    # Restore persisted agent mode (survives restarts — important for paper runs)
    try:
        saved_mode = _load_persisted_mode()
        agent_orchestrator.set_mode(saved_mode)
        print(f"[TradeDesk] Restored agent mode: {saved_mode}")
    except Exception as e:
        print(f"[TradeDesk] Mode restore skipped: {e}")
    # Paper-trading equity snapshots (hourly)
    try:
        import paper_trader
        paper_trader.init_paper_tables()
        paper_trader.start_snapshots(interval_sec=3600)
        print("[TradeDesk] Paper snapshot loop started")
    except Exception as e:
        print(f"[TradeDesk] Snapshot loop skipped: {e}")
    # Heartbeat — writes a liveness timestamp every 20s for the watchdog
    asyncio.create_task(_heartbeat_loop())
    print("[TradeDesk] Heartbeat started")


HEARTBEAT_FILE = "/tmp/tradedesk-heartbeat"
_START_TIME = time.time()

async def _heartbeat_loop():
    while True:
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass
        await asyncio.sleep(20)

@app.on_event("shutdown")
async def shutdown_event():
    benzinga_feed.stop_feed()
    edgar_feed.stop_feed()
    agent_monitor.stop_monitor()
    auto_scanner.stop_auto_scanner()

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

def load_settings() -> dict:
    defaults = {
        "portfolio_size": 25000.0,
        "risk_pct": 1.5,
        "min_rr": 2.0,
        "max_positions": 5,
        "max_sector_pct": 30,
        "default_period": "3mo",
        "default_interval": "1d",
        "news_limit": 10,
        "refresh_interval": 60,
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    # Merge sensitive keys from .env
    defaults["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    defaults["alpaca_api_key"] = os.environ.get("ALPACA_API_KEY", "")
    defaults["alpaca_secret_key"] = os.environ.get("ALPACA_SECRET_KEY", "")
    defaults["benzinga_api_key"] = os.environ.get("BENZINGA_API_KEY", "")
    defaults["alpha_vantage_key"] = os.environ.get("ALPHA_VANTAGE_KEY", "")
    defaults["news_api_key"] = os.environ.get("NEWS_API_KEY", "")
    return defaults

def save_settings(data: dict):
    # Split: API keys → .env, rest → settings.json
    env_keys = {
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "alpaca_api_key": "ALPACA_API_KEY",
        "alpaca_secret_key": "ALPACA_SECRET_KEY",
        "benzinga_api_key": "BENZINGA_API_KEY",
        "alpha_vantage_key": "ALPHA_VANTAGE_KEY",
        "news_api_key": "NEWS_API_KEY",
    }
    non_secret = {}
    for k, v in data.items():
        if k in env_keys:
            env_var = env_keys[k]
            if v:
                clean = str(v).strip()  # strip any accidental whitespace/newlines
                set_key(ENV_PATH, env_var, clean)
                os.environ[env_var] = clean
        else:
            non_secret[k] = v
    with open(SETTINGS_FILE, "w") as f:
        json.dump(non_secret, f, indent=2)

_settings = load_settings()

def get_setting(key, default=None):
    return _settings.get(key, default)

PORTFOLIO_SIZE = float(_settings.get("portfolio_size", 25000))
RISK_PCT = float(_settings.get("risk_pct", 1.5))


# ─── Models ────────────────────────────────────────────────────────────────────

class TradeEntry(BaseModel):
    ticker: str
    direction: str = "LONG"
    entry_price: float
    quantity: float
    stop_loss: Optional[float] = None
    target1: Optional[float] = None
    target2: Optional[float] = None
    target3: Optional[float] = None
    notes: Optional[str] = None
    strategy: Optional[str] = None


class TradeClose(BaseModel):
    exit_price: float


class WatchlistAdd(BaseModel):
    ticker: str
    alert_price: Optional[float] = None
    notes: Optional[str] = None


# ─── Market Data ───────────────────────────────────────────────────────────────

@app.get("/api/market/overview")
def market_overview():
    return get_market_overview()


@app.get("/api/stock/{ticker}")
def stock_info(ticker: str):
    info = get_stock_info(ticker.upper())
    if "error" in info:
        raise HTTPException(status_code=404, detail=info["error"])
    return info


@app.get("/api/stock/{ticker}/history")
def stock_history(ticker: str, period: str = "3mo", interval: str = "1d"):
    data = get_ohlcv(ticker.upper(), period, interval)
    return {"ticker": ticker.upper(), "period": period, "interval": interval, "data": data}


@app.get("/api/stock/{ticker}/quote")
def stock_quote(ticker: str):
    """Real-time snapshot — price, change, volume. Fast."""
    return get_snapshot(ticker.upper())

@app.get("/api/stock/{ticker}/technicals")
def stock_technicals(ticker: str):
    return get_technicals(ticker.upper())


@app.get("/api/stock/{ticker}/news")
def stock_news(ticker: str):
    news = get_news(ticker.upper())
    sentiment = score_news_sentiment(news)
    return {"ticker": ticker.upper(), "news": news, "sentiment": sentiment}


@app.get("/api/stock/{ticker}/analyze")
def full_analysis(ticker: str):
    t = ticker.upper()
    info = get_stock_info(t)
    technicals = get_technicals(t)
    news = get_news(t)
    analysis = analyze_trade(t, info, technicals, news, PORTFOLIO_SIZE)
    sentiment = score_news_sentiment(news)
    return {
        "ticker": t,
        "info": info,
        "technicals": technicals,
        "news": news[:6],
        "sentiment": sentiment,
        "analysis": analysis,
    }


@app.get("/api/risk/size")
def position_size(entry: float, stop: float, portfolio: float = PORTFOLIO_SIZE, risk_pct: float = RISK_PCT):
    return calculate_position_size(portfolio, risk_pct, entry, stop)


# ─── Portfolio / Positions ─────────────────────────────────────────────────────

@app.get("/api/portfolio")
def get_portfolio():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM positions ORDER BY created_at DESC").fetchall()
    conn.close()

    positions = []
    total_pnl = 0
    open_value = 0

    for row in rows:
        p = dict(row)
        # Fetch current price for open positions
        if p["status"] == "OPEN":
            try:
                info = get_stock_info(p["ticker"])
                current = info.get("current_price", p["entry_price"])
                p["current_price"] = current
                multiplier = 1 if p["direction"] == "LONG" else -1
                p["unrealized_pnl"] = round((current - p["entry_price"]) * p["quantity"] * multiplier, 2)
                p["unrealized_pnl_pct"] = round((current - p["entry_price"]) / p["entry_price"] * 100 * multiplier, 2)
                open_value += current * p["quantity"]
                total_pnl += p["unrealized_pnl"]
            except Exception:
                p["current_price"] = p["entry_price"]
                p["unrealized_pnl"] = 0
                p["unrealized_pnl_pct"] = 0
        else:
            p["current_price"] = p.get("exit_price", p["entry_price"])
            p["unrealized_pnl"] = 0
            p["unrealized_pnl_pct"] = 0
            if p["pnl"]:
                total_pnl += p["pnl"]

        positions.append(p)

    closed = [p for p in positions if p["status"] == "CLOSED"]
    realized_pnl = sum(p.get("pnl", 0) or 0 for p in closed)
    winners = [p for p in closed if (p.get("pnl") or 0) > 0]
    win_rate = round(len(winners) / len(closed) * 100, 1) if closed else 0

    return {
        "positions": positions,
        "summary": {
            "portfolio_size": PORTFOLIO_SIZE,
            "open_position_value": round(open_value, 2),
            "total_unrealized_pnl": round(sum(p.get("unrealized_pnl", 0) for p in positions if p["status"] == "OPEN"), 2),
            "realized_pnl": round(realized_pnl, 2),
            "total_trades": len(closed),
            "win_rate": win_rate,
            "open_positions": len([p for p in positions if p["status"] == "OPEN"]),
        }
    }


@app.post("/api/portfolio/trade")
def add_trade(trade: TradeEntry):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO positions (ticker, direction, entry_price, quantity, stop_loss,
            target1, target2, target3, notes, strategy)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.ticker.upper(), trade.direction, trade.entry_price, trade.quantity,
        trade.stop_loss, trade.target1, trade.target2, trade.target3,
        trade.notes, trade.strategy
    ))
    conn.commit()
    trade_id = c.lastrowid
    conn.close()
    return {"id": trade_id, "status": "created"}


@app.put("/api/portfolio/trade/{trade_id}/close")
async def close_trade(trade_id: int, body: TradeClose):
    conn = get_connection()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (trade_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trade not found")
    p = dict(row)
    multiplier = 1 if p["direction"] == "LONG" else -1
    pnl = round((body.exit_price - p["entry_price"]) * p["quantity"] * multiplier, 2)
    conn.execute("""
        UPDATE positions SET status='CLOSED', exit_price=?, exit_date=?, pnl=? WHERE id=?
    """, (body.exit_price, datetime.utcnow().isoformat(), pnl, trade_id))
    conn.commit()
    conn.close()

    # Trigger Journal post-mortem
    try:
        from agents.journal import analyze_closed_trade
        journal_result = await analyze_closed_trade(trade_id)
        return {"id": trade_id, "pnl": pnl, "status": "closed", "journal": journal_result}
    except Exception as e:
        return {"id": trade_id, "pnl": pnl, "status": "closed", "journal_error": str(e)}


@app.delete("/api/portfolio/trade/{trade_id}")
def delete_trade(trade_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM positions WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


# ─── Watchlist ─────────────────────────────────────────────────────────────────

@app.get("/api/watchlist")
def get_watchlist():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    conn.close()
    tickers = [dict(r) for r in rows]

    result = []
    for item in tickers:
        try:
            info = get_stock_info(item["ticker"])
            item["current_price"] = info.get("current_price")
            item["name"] = info.get("name", item["ticker"])
            item["change_pct"] = None  # Could calculate from history
        except Exception:
            item["current_price"] = None
            item["name"] = item["ticker"]
        result.append(item)

    return result


@app.post("/api/watchlist")
def add_to_watchlist(body: WatchlistAdd):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, alert_price, notes) VALUES (?, ?, ?)",
            (body.ticker.upper(), body.alert_price, body.notes)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return {"status": "added", "ticker": body.ticker.upper()}


@app.delete("/api/watchlist/{ticker}")
def remove_from_watchlist(ticker: str):
    conn = get_connection()
    conn.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))
    conn.commit()
    conn.close()
    return {"status": "removed"}


# ─── Settings ──────────────────────────────────────────────────────────────────

class SettingsBody(BaseModel):
    anthropic_api_key: Optional[str] = None
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    benzinga_api_key: Optional[str] = None
    alpha_vantage_key: Optional[str] = None
    news_api_key: Optional[str] = None
    portfolio_size: Optional[float] = None
    risk_pct: Optional[float] = None
    min_rr: Optional[float] = None
    max_positions: Optional[int] = None
    max_sector_pct: Optional[int] = None
    default_period: Optional[str] = None
    default_interval: Optional[str] = None
    news_limit: Optional[int] = None
    refresh_interval: Optional[int] = None

class TestBody(BaseModel):
    provider: str

@app.get("/api/settings")
def get_settings_endpoint():
    s = load_settings()
    # Mask keys for display — show only first 8 chars
    for key in ("anthropic_api_key", "alpha_vantage_key", "news_api_key"):
        val = s.get(key, "")
        if val and len(val) > 8:
            s[key] = val  # send full value so UI can show it
    return s

@app.post("/api/settings")
async def save_settings_endpoint(body: SettingsBody):
    global _settings, PORTFOLIO_SIZE, RISK_PCT
    data = {k: v for k, v in body.dict().items() if v is not None}
    save_settings(data)
    _load_env()
    _settings = load_settings()
    PORTFOLIO_SIZE = float(_settings.get("portfolio_size", 25000))
    RISK_PCT = float(_settings.get("risk_pct", 1.5))
    reset_client()
    # Auto-start Benzinga feed if key just added
    if "benzinga_api_key" in data and data["benzinga_api_key"]:
        benzinga_feed.stop_feed()
        await asyncio.sleep(0.3)
        benzinga_feed.start_feed(_get_watchlist_tickers, interval=20)
    return {"status": "saved"}

@app.post("/api/settings/test")
def test_connection(body: TestBody):
    if body.provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key or key == _PLACEHOLDER:
            raise HTTPException(status_code=400, detail="No Anthropic API key set. Paste your key and hit Save first.")
        if not key.startswith("sk-ant-"):
            raise HTTPException(status_code=400, detail=f"Key looks wrong — should start with 'sk-ant-' (got: '{key[:10]}...')")
        if len(key) < 40:
            raise HTTPException(status_code=400, detail=f"Key too short ({len(key)} chars) — may have been truncated during paste")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return {"message": f"Connected — model: {resp.model}"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif body.provider == "benzinga":
        key = os.environ.get("BENZINGA_API_KEY", "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="No Benzinga API key set — paste it and hit Save first")
        try:
            import httpx
            r = httpx.get(
                "https://api.benzinga.com/api/v2/news",
                params={"token": key, "pageSize": 1, "displayOutput": "full"},
                timeout=10,
                headers={"Accept": "application/json"},
            )
            if r.status_code in (401, 403):
                raise HTTPException(status_code=400, detail="Invalid Benzinga key or subscription not active")
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Benzinga returned HTTP {r.status_code}")
            # Response may be JSON list or object
            try:
                data = r.json()
            except Exception:
                raise HTTPException(status_code=400, detail=f"Unexpected response from Benzinga (not JSON). Key may be invalid.")
            count = len(data) if isinstance(data, list) else len(data.get("news", data.get("result", [])))
            return {"message": f"✓ Connected — Benzinga feed live ({count} article fetched)"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif body.provider == "alpaca":
        try:
            from alpaca_data import test_connection
            result = test_connection()
            return result
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif body.provider == "alphavantage":
        key = os.environ.get("ALPHA_VANTAGE_KEY", "")
        if not key:
            raise HTTPException(status_code=400, detail="No Alpha Vantage key set")
        try:
            import urllib.request
            url = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol=IBM&interval=5min&apikey={key}"
            urllib.request.urlopen(url, timeout=5)
            return {"message": "Alpha Vantage connection successful"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail="Unknown provider")


# ─── Benzinga Live Feed ────────────────────────────────────────────────────────

@app.get("/api/feed/stream")
async def news_stream(request: Request):
    """SSE endpoint — frontend connects once and receives real-time alerts."""
    q = benzinga_feed.subscribe()

    async def event_generator():
        # Send heartbeat on connect
        yield f"data: {json.dumps({'type': 'connected', 'ts': time.time()})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat', 'ts': time.time()})}\n\n"
        finally:
            benzinga_feed.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/feed/latest")
async def feed_latest(limit: int = 30, min_score: int = 1):
    """REST fallback — get latest scored articles."""
    articles = await benzinga_feed.fetch_news(limit=limit)
    scored = [benzinga_feed.quick_score(a) for a in articles]
    scored = [a for a in scored if a["score"] >= min_score]
    return {"articles": scored, "count": len(scored), "source": "benzinga"}


@app.get("/api/feed/earnings")
async def feed_earnings(days: int = 7):
    earnings = await benzinga_feed.fetch_calendar_earnings(days_ahead=days)
    return {"earnings": earnings, "count": len(earnings)}


@app.get("/api/feed/fda")
async def feed_fda(days: int = 14):
    fda = await benzinga_feed.fetch_calendar_fda(days_ahead=days)
    return {"fda": fda, "count": len(fda)}


@app.post("/api/feed/restart")
async def restart_feed():
    """Restart the Benzinga feed (call after saving API key)."""
    benzinga_feed.stop_feed()
    await asyncio.sleep(0.5)
    if os.environ.get("BENZINGA_API_KEY", "").strip():
        benzinga_feed.start_feed(_get_watchlist_tickers, interval=20)
        return {"status": "started"}
    return {"status": "no_key", "message": "Add Benzinga API key in Settings first"}


# ─── AI Scanner ────────────────────────────────────────────────────────────────

@app.get("/api/scan")
async def run_scan():
    """Full pipeline: market + Benzinga + AI → ranked trade setups."""
    import httpx, re, html as htmllib

    # 1. Market overview
    market = get_market_overview()

    # 2. Benzinga feed
    bz_key = os.environ.get("BENZINGA_API_KEY", "").strip()
    catalysts = []
    if bz_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.benzinga.com/api/v2/news",
                    params={"token": bz_key, "pageSize": 100, "displayOutput": "full"},
                    headers={"Accept": "application/json"},
                )
                arts = r.json()

            def strip_html(s):
                return re.sub('<[^>]+>', ' ', s or '').replace('&amp;','&').replace('&#39;',"'").strip()

            CRITICAL = ['fda approv','fda reject','fda clear','merger','acquisition','buyout',
                        'takeover','going private','bankruptcy','sec invest','ceo resign',
                        'ceo fired','fraud','clinical trial','phase 3','spinoff','spin-off','breakthrough']
            HIGH = ['earnings beat','earnings miss','raised guidance','lowers guidance','cuts guidance',
                    'analyst upgrade','analyst downgrade','raises price target','lowers price target',
                    'increases price target','insider buy','insider purchas','insider sell',
                    'short squeeze','buyback','revenue beat','revenue miss','beat estimates',
                    'missed estimates','misses estimates','tops estimates','major contract','restructur']

            for a in arts:
                title = strip_html(a.get('title',''))
                body  = strip_html(a.get('body') or a.get('teaser') or '')[:300]
                tickers = [s.get('name','') for s in a.get('stocks',[]) if s.get('name')]
                t_lower = (title+' '+body).lower()
                impact, matched = 'LOW', ''
                for k in CRITICAL:
                    if k in t_lower: impact='CRITICAL'; matched=k; break
                if impact=='LOW':
                    for k in HIGH:
                        if k in t_lower: impact='HIGH'; matched=k; break
                if impact in ('CRITICAL','HIGH'):
                    catalysts.append({
                        'impact': impact, 'title': title,
                        'tickers': tickers[:6], 'body': body[:200],
                        'signal': matched, 'time': a.get('created','')[:19]
                    })
        except Exception as e:
            print(f"[Scanner] Benzinga error: {e}")

    # 3. Live prices for catalyst tickers + watchlist
    all_tickers = list({t for c in catalysts for t in c['tickers']})
    try:
        conn = get_connection()
        wl = [r["ticker"] for r in conn.execute("SELECT ticker FROM watchlist").fetchall()]
        conn.close()
        all_tickers = list(set(all_tickers + wl))[:15]
    except Exception:
        pass

    price_data = {}
    for ticker in all_tickers:
        try:
            snap = get_snapshot(ticker)
            tech = get_technicals(ticker)
            if snap.get('price'):
                price_data[ticker] = {**snap, **tech}
        except Exception:
            pass

    # 4. AI synthesis
    from ai_brain import get_client
    ai_client = get_client()
    setups = []

    if ai_client:
        market_lines = "\n".join(
            f"  {sym}: ${d['price']}  {d.get('change_pct',0):+.2f}%"
            for sym,d in market.items() if d.get('price')
        )
        catalyst_lines = "\n".join(
            f"  [{c['impact']}] {c['tickers']} — {c['title'][:100]}  signal={c['signal']}"
            for c in catalysts[:8]
        )
        price_lines = "\n".join(
            f"  {t}: ${d.get('price',0):.2f}  {d.get('change_pct',0):+.2f}%  RSI:{d.get('rsi',0):.1f}  Trend:{d.get('trend','?')}  EMA20:${d.get('ema20',0):.2f}  Support:${d.get('support',0):.2f}  ATR:{d.get('atr_pct',0):.1f}%"
            for t,d in price_data.items() if d.get('price')
        )

        prompt = f"""You are a professional swing trader managing a $25,000 account.
Surface the 3 best trade setups RIGHT NOW based on this live data.

MARKET (live):
{market_lines}

BENZINGA CATALYSTS (live):
{catalyst_lines if catalyst_lines else "No high-impact catalysts right now"}

LIVE PRICES + TECHNICALS:
{price_lines if price_lines else "No price data"}

RULES:
- Portfolio $25,000 | Max risk per trade: 1.5% = $375 | Min R:R: 2:1
- Swing trades 3-15 days
- In a broad selloff: prefer shorts, or longs only with hard catalyst
- No setup if R:R < 2:1

Respond ONLY with valid JSON, no markdown:
{{
  "market_regime": "one line",
  "scanned_at": "now",
  "setups": [
    {{
      "rank": 1,
      "ticker": "XXX",
      "direction": "LONG or SHORT",
      "catalyst": "one line",
      "thesis": "2-3 sentences",
      "entry": number,
      "stop": number,
      "target1": number,
      "target2": number,
      "risk_reward": number,
      "shares": number,
      "risk_dollars": number,
      "position_value": number,
      "time_horizon": "X-Y days",
      "urgency": "TODAY or TOMORROW or THIS_WEEK",
      "conviction": "HIGH or MEDIUM or LOW",
      "entry_trigger": "exact trigger",
      "invalidation": "what kills the trade",
      "score": 1-10
    }}
  ]
}}"""

        try:
            resp = ai_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2500,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"): text = text[4:]
            result = json.loads(text)
            setups = result.get("setups", [])
            market_regime = result.get("market_regime", "")
        except Exception as e:
            market_regime = f"AI error: {e}"
    else:
        market_regime = "Add Anthropic API key in Settings to enable AI setups"

    return {
        "market": market,
        "catalysts": catalysts,
        "setups": setups,
        "market_regime": market_regime,
        "scanned_at": datetime.utcnow().isoformat(),
        "price_data": price_data,
    }


# ─── Serve built frontend (for packaged Electron app) ─────────────────────────
import os as _os
_DIST = _os.path.join(_os.path.dirname(__file__), '..', 'frontend', 'dist')
if _os.path.exists(_DIST):
    # Serve static assets
    app.mount("/assets", StaticFiles(directory=_os.path.join(_DIST, "assets")), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(_os.path.join(_DIST, "index.html"))

    @app.get("/favicon.svg")
    async def serve_favicon():
        return FileResponse(_os.path.join(_DIST, "favicon.svg"))

    @app.get("/icons.svg")
    async def serve_icons():
        return FileResponse(_os.path.join(_DIST, "icons.svg"))


# ─── SEC EDGAR ─────────────────────────────────────────────────────────────────

@app.get("/api/edgar/stream")
async def edgar_stream(request: Request):
    """SSE endpoint for real-time SEC EDGAR filings."""
    q = edgar_feed.subscribe()

    async def generator():
        yield f"data: {json.dumps({'type': 'connected', 'source': 'edgar', 'ts': time.time()})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'ts': time.time()})}\n\n"
        finally:
            edgar_feed.unsubscribe(q)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/edgar/search")
async def edgar_search(ticker: str, form_type: str = "8-K", limit: int = 5):
    results = await edgar_feed.search_filings(ticker.upper(), form_type, limit)
    return {"ticker": ticker.upper(), "form_type": form_type, "results": results}


@app.get("/api/edgar/summarize")
async def edgar_summarize(acc_no: str, cik: str, form_type: str = "8-K", ticker: str = ""):
    """Fetch and AI-summarize an SEC filing."""
    from ai_brain import get_client

    text = await edgar_feed.fetch_filing_text(acc_no, cik)
    if not text:
        raise HTTPException(status_code=404, detail="Could not fetch filing text")

    client = get_client()
    if not client:
        return {"summary": text[:2000], "ai": False}

    prompt = f"""You are a financial analyst. Summarize this SEC {form_type} filing for {ticker or 'this company'}.

FILING TEXT (first 15,000 chars):
{text[:15000]}

Respond with JSON only (no markdown):
{{
  "headline": "one sentence — the most important thing this filing reveals",
  "impact": "BULLISH" | "BEARISH" | "NEUTRAL",
  "key_points": ["point 1", "point 2", "point 3", "point 4"],
  "numbers": ["key financial metric 1", "key financial metric 2", "key financial metric 3"],
  "risks": ["risk 1", "risk 2"],
  "action": "BUY" | "SELL" | "WATCH" | "NEUTRAL",
  "reasoning": "2-3 sentences on what this means for the stock price"
}}"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        txt = resp.content[0].text.strip()
        if "```" in txt:
            txt = txt.split("```")[1]
            if txt.startswith("json"): txt = txt[4:]
        return {"summary": json.loads(txt), "ai": True, "form_type": form_type}
    except Exception as e:
        return {"summary": {"headline": text[:300], "key_points": []}, "ai": False, "error": str(e)}


@app.get("/api/edgar/insider/{ticker}")
async def edgar_insider(ticker: str):
    """Get recent Form 4 insider transactions for a ticker."""
    results = await edgar_feed.search_filings(ticker.upper(), "4", limit=10)
    return {"ticker": ticker.upper(), "filings": results}


# ─── Earnings ─────────────────────────────────────────────────────────────────

@app.get("/api/earnings/calendar")
async def earnings_calendar(days: int = 14):
    """Upcoming earnings via EDGAR 10-Q/10-K recent filings + watchlist tickers."""
    try:
        conn = get_connection()
        tickers = [r["ticker"] for r in conn.execute("SELECT ticker FROM watchlist").fetchall()]
        conn.close()
    except Exception:
        tickers = []

    results = []
    for ticker in tickers[:8]:
        try:
            filings = await edgar_feed.search_filings(ticker, "10-Q", limit=1)
            if filings:
                f = filings[0]
                snap = get_snapshot(ticker)
                results.append({
                    "ticker": ticker,
                    "form_type": "10-Q",
                    "last_filed": f.get("filed", ""),
                    "company": f.get("company", ticker),
                    "acc_no": f.get("acc_no", ""),
                    "cik": f.get("cik", ""),
                    "url": f.get("url", ""),
                    "current_price": snap.get("price"),
                    "change_pct": snap.get("change_pct"),
                })
        except Exception:
            pass

    return {"earnings": results, "source": "edgar_10q", "note": "Shows last 10-Q filing per ticker"}


@app.get("/api/earnings/watchlist")
async def earnings_watchlist(days: int = 14):
    return await earnings_calendar(days)

@app.get("/api/earnings/upcoming")
async def earnings_upcoming(days: int = 14):
    """Upcoming earnings calendar (Alpha Vantage + Benzinga), with your
    watchlist/holdings flagged and surfaced first."""
    import earnings
    try:
        return earnings.get_upcoming(days)
    except Exception as e:
        return {"error": str(e)[:200], "mine": [], "all": []}

@app.get("/api/earnings/expectation/{ticker}")
async def earnings_expectation(ticker: str):
    """Honest earnings preview for one ticker: consensus, beat/miss track record,
    and the historical TYPICAL MOVE (risk, not a direction prediction)."""
    import earnings
    t = ticker.upper()
    try:
        return {"ticker": t, "track_record": earnings.get_track_record(t),
                "expected_move": earnings.get_expected_move(t)}
    except Exception as e:
        return {"ticker": t, "error": str(e)[:200]}


@app.get("/api/earnings/history/{ticker}")
async def earnings_history(ticker: str):
    """Historical earnings beats/misses from yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        hist = t.earnings_history
        if hist is None or hist.empty:
            return {"ticker": ticker.upper(), "history": []}

        records = []
        for idx, row in hist.iterrows():
            try:
                eps_est = float(row.get("epsEstimate", 0) or 0)
                eps_act = float(row.get("epsActual", 0) or 0)
                surprise = round(((eps_act - eps_est) / abs(eps_est) * 100), 1) if eps_est else 0
                records.append({
                    "date": str(idx.date()) if hasattr(idx, 'date') else str(idx),
                    "eps_estimate": round(eps_est, 4),
                    "eps_actual": round(eps_act, 4),
                    "surprise_pct": surprise,
                    "beat": eps_act > eps_est,
                })
            except Exception:
                pass
        records.sort(key=lambda x: x["date"], reverse=True)
        return {"ticker": ticker.upper(), "history": records[:8]}
    except Exception as e:
        return {"ticker": ticker.upper(), "history": [], "error": str(e)}


# ─── Multi-Agent System ───────────────────────────────────────────────────────

@app.get("/api/agents/stream")
async def agents_stream(request: Request):
    """SSE stream of all events going through the bus."""
    q = event_bus.subscribe()

    async def generator():
        yield f"data: {json.dumps({'type': 'connected', 'source': 'agents', 'ts': time.time()})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'ts': time.time()})}\n\n"
        finally:
            event_bus.unsubscribe(q)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/agents/events")
async def list_events(limit: int = 50):
    """Recent events from the bus."""
    return {"events": event_bus.get_recent_events(limit)}


@app.get("/api/agents/runs")
async def list_agent_runs(limit: int = 100, agent: str = None, event_id: int = None):
    """Recent agent runs with input/output."""
    return {"runs": event_bus.get_agent_runs(limit, agent, event_id)}


@app.get("/api/agents/pending-trades")
async def list_pending_trades(status: str = "pending"):
    """Pending trades awaiting user decision."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM pending_trades WHERE status=? ORDER BY id DESC",
        (status,)
    ).fetchall()
    conn.close()
    trades = []
    for r in rows:
        d = dict(r)
        # Parse JSON output fields
        for k in ("scout_output", "research_output", "risk_output", "trader_output"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        trades.append(d)
    return {"trades": trades, "count": len(trades)}


class PendingTradeAction(BaseModel):
    action: str   # "approve" | "reject"
    reason: str = ""


@app.post("/api/agents/pending-trades/{trade_id}/decision")
async def decide_pending_trade(trade_id: int, body: PendingTradeAction):
    """User approves or rejects a pending trade."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM pending_trades WHERE id=?", (trade_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Pending trade not found")

    p = dict(row)

    if body.action == "approve":
        # Create an actual open position
        conn.execute("""
            INSERT INTO positions (ticker, direction, entry_price, quantity,
                stop_loss, target1, target2, strategy, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p["ticker"], p["direction"], p["entry"], p["shares"],
            p["stop"], p["target1"], p["target2"],
            "AI Agent", f"Auto-generated by agent pipeline. Confidence: {p['confidence']}/10. {p.get('thesis','')}"
        ))
        conn.execute(
            "UPDATE pending_trades SET status='approved', status_reason=?, decided_at=datetime('now') WHERE id=?",
            (body.reason or "User approved", trade_id)
        )
        conn.commit()
        conn.close()
        return {"status": "approved", "trade_id": trade_id}

    elif body.action == "reject":
        conn.execute(
            "UPDATE pending_trades SET status='rejected', status_reason=?, decided_at=datetime('now') WHERE id=?",
            (body.reason or "User rejected", trade_id)
        )
        conn.commit()
        conn.close()
        return {"status": "rejected", "trade_id": trade_id}

    else:
        conn.close()
        raise HTTPException(400, f"Unknown action: {body.action}")


@app.get("/api/agents/mode")
async def get_agent_mode():
    return {"mode": agent_orchestrator.get_mode(), "available": agent_orchestrator.MODES}


class ModeBody(BaseModel):
    mode: str


@app.post("/api/agents/mode")
async def set_agent_mode(body: ModeBody):
    if body.mode not in agent_orchestrator.MODES:
        raise HTTPException(400, f"Invalid mode. Available: {agent_orchestrator.MODES}")
    agent_orchestrator.set_mode(body.mode)
    return {"mode": body.mode, "status": "set"}


@app.get("/api/agents/stats")
async def agent_stats():
    """Aggregated stats: total events, runs by agent, pending trades, total cost."""
    conn = get_connection()
    events_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    runs_count = conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
    pending_count = conn.execute(
        "SELECT COUNT(*) FROM pending_trades WHERE status='pending'"
    ).fetchone()[0]
    approved_count = conn.execute(
        "SELECT COUNT(*) FROM pending_trades WHERE status='approved'"
    ).fetchone()[0]

    by_agent = {}
    for row in conn.execute(
        "SELECT agent, COUNT(*) as c, SUM(cost_usd) as cost FROM agent_runs GROUP BY agent"
    ).fetchall():
        by_agent[row["agent"]] = {"count": row["c"], "cost_usd": round(row["cost"] or 0, 4)}

    total_cost = sum(a["cost_usd"] for a in by_agent.values())
    conn.close()

    return {
        "events_total": events_count,
        "agent_runs_total": runs_count,
        "pending_trades": pending_count,
        "approved_trades": approved_count,
        "by_agent": by_agent,
        "total_cost_usd": round(total_cost, 4),
        "current_mode": agent_orchestrator.get_mode(),
    }


# ─── Position Monitor ─────────────────────────────────────────────────────────

@app.get("/api/agents/monitor/checks")
async def monitor_checks(position_id: int = None, limit: int = 50):
    """Recent position monitor checks."""
    return {"checks": agent_monitor.get_position_checks(position_id, limit)}


@app.post("/api/agents/monitor/check-now/{position_id}")
async def monitor_check_now(position_id: int):
    """Force a monitor check on a specific position."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Position not found")
    position = dict(row)
    if position.get("status") != "OPEN":
        raise HTTPException(400, "Position not open")
    result = await agent_monitor.monitor_position(position)
    return result


@app.get("/api/agents/monitor/status")
async def monitor_status():
    """Aggregated monitor stats."""
    conn = get_connection()
    total_checks = conn.execute("SELECT COUNT(*) FROM position_checks").fetchone()[0]
    exits_today = conn.execute("""
        SELECT COUNT(*) FROM position_checks
        WHERE action_taken IN ('closed', 'trimmed')
        AND date(created_at) = date('now')
    """).fetchone()[0]
    open_positions = conn.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    conn.close()
    return {
        "total_checks": total_checks,
        "exits_today": exits_today,
        "open_positions": open_positions,
        "running": True,
    }


# ─── Trade Journal (Phase 4: Learning Loop) ─────────────────────────────────

@app.get("/api/agents/journal/entries")
async def journal_entries(limit: int = 50):
    """All journal entries (post-mortems)."""
    from agents.journal import list_journal_entries
    return {"entries": list_journal_entries(limit)}


@app.get("/api/agents/journal/stats")
async def journal_stats():
    """Aggregated trade stats."""
    from agents.journal import get_journal_stats
    return get_journal_stats()


@app.get("/api/agents/journal/learnings")
async def journal_learnings():
    """All accumulated pattern learnings."""
    from agents.journal import list_learnings, get_playbook
    return {
        "learnings": list_learnings(),
        "playbook": get_playbook(),
    }


@app.post("/api/agents/journal/analyze/{position_id}")
async def journal_analyze(position_id: int):
    """Force a journal post-mortem on a specific closed trade."""
    from agents.journal import analyze_closed_trade
    result = await analyze_closed_trade(position_id)
    return result


@app.post("/api/agents/journal/backfill")
async def journal_backfill():
    """Run journal on every closed position that doesn't have a journal entry yet."""
    from agents.journal import analyze_closed_trade
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.id FROM positions p
        WHERE p.status='CLOSED'
        AND NOT EXISTS (SELECT 1 FROM trade_journal j WHERE j.position_id = p.id)
        ORDER BY p.id DESC
    """).fetchall()
    conn.close()

    results = []
    for r in rows[:20]:  # Cap at 20 to avoid runaway cost
        try:
            res = await analyze_closed_trade(r["id"])
            results.append({"position_id": r["id"], "outcome": res.get("outcome"), "ok": "error" not in res})
        except Exception as e:
            results.append({"position_id": r["id"], "error": str(e)})

    return {"processed": len(results), "results": results}


# ─── Auto-scanner endpoint ────────────────────────────────────────────────────

@app.get("/api/scan/latest")
async def get_latest_scan():
    """Return the most recent auto-scan result from the event bus."""
    conn = get_connection()
    row = conn.execute("""
        SELECT data, created_at FROM events
        WHERE source='auto_scanner' AND type='scan_complete'
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    conn.close()
    if not row:
        return {"setups": [], "market_regime": "Waiting for first scan...", "scanned_at": None}
    try:
        data = json.loads(row["data"])
        data["scanned_at"] = row["created_at"]
        return data
    except Exception:
        return {"setups": [], "scanned_at": row["created_at"]}


# ─── Paper Trading Experiment ─────────────────────────────────────────────────

class PaperSessionBody(BaseModel):
    starting_capital: float = 25000
    notes: str = ""

@app.post("/api/paper/start")
async def paper_start(body: PaperSessionBody):
    """Start a paper trading experiment: switch to AUTO_PAPER, open a session."""
    import paper_trader
    sid = paper_trader.start_session(body.starting_capital, body.notes)
    agent_orchestrator.set_mode("AUTO_PAPER")
    # Persist mode so it survives restart
    _save_persisted_mode("AUTO_PAPER")
    await event_bus.publish(
        source="paper_trader", type="session_started",
        data={"session_id": sid, "starting_capital": body.starting_capital},
        title=f"🚀 Paper trading session #{sid} started — ${body.starting_capital:,.0f} · AUTO_PAPER",
        impact="HIGH",
    )
    return {"session_id": sid, "mode": "AUTO_PAPER", "status": "started"}

@app.post("/api/paper/stop")
async def paper_stop():
    import paper_trader
    paper_trader.end_session()
    agent_orchestrator.set_mode("SUGGEST")
    _save_persisted_mode("SUGGEST")
    return {"status": "stopped", "mode": "SUGGEST"}

@app.get("/api/paper/report")
async def paper_report():
    import paper_trader
    return paper_trader.session_report()


def _save_persisted_mode(mode: str):
    try:
        conn = get_connection()
        conn.execute("INSERT OR REPLACE INTO agent_settings (key, value) VALUES ('mode', ?)", (mode,))
        conn.commit()
        conn.close()
    except Exception:
        pass

def _load_persisted_mode() -> str:
    try:
        conn = get_connection()
        row = conn.execute("SELECT value FROM agent_settings WHERE key='mode'").fetchone()
        conn.close()
        return row["value"] if row else "SUGGEST"
    except Exception:
        return "SUGGEST"


@app.get("/api/paper/snapshots")
async def paper_snapshots(limit: int = 200):
    """Equity curve points for the active paper session."""
    import paper_trader
    return {"snapshots": paper_trader.get_snapshots(limit)}


# ─── Risk Guard (circuit breakers) ────────────────────────────────────────────

@app.get("/api/risk/guard")
async def risk_guard_status():
    import risk_guard
    return risk_guard.check()

class GuardConfig(BaseModel):
    daily_loss_limit_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    max_consecutive_losses: Optional[int] = None
    max_trades_per_day: Optional[int] = None

@app.post("/api/risk/guard/config")
async def risk_guard_config(body: GuardConfig):
    import risk_guard
    updates = {k: v for k, v in body.dict().items() if v is not None}
    return {"config": risk_guard.set_config(updates)}

@app.post("/api/risk/guard/reset")
async def risk_guard_reset():
    import risk_guard
    return risk_guard.reset_breakers()

@app.post("/api/risk/guard/halt")
async def risk_guard_halt(on: bool = True):
    import risk_guard
    risk_guard.manual_halt(on)
    return {"halted": on}


# ─── Broker (real Alpaca paper account) ───────────────────────────────────────

@app.get("/api/broker/account")
async def broker_account():
    import broker
    return {"available": broker.is_available(), "account": broker.get_account()}

@app.get("/api/broker/positions")
async def broker_positions():
    import broker
    return {"positions": broker.get_positions()}

# ─── Phase 0: metrics, reconciliation, validation ─────────────────────────────

@app.get("/api/metrics")
async def performance_metrics():
    """Honest performance metrics over all closed trades (expectancy, Sharpe,
    Deflated Sharpe, max drawdown, per-pattern/strategy breakdown)."""
    import metrics
    try:
        return metrics.compute_metrics()
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/recon")
async def reconciliation_check():
    """Diff the internal ledger against the active broker account."""
    import reconciliation
    try:
        return reconciliation.reconcile()
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}

@app.get("/api/validation")
async def validation_report():
    """Pipeline edge + confidence calibration + snapshot count (Phase 0 harness)."""
    import replay
    try:
        return replay.validation_report()
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/risk/portfolio")
async def portfolio_risk():
    """Quantitative portfolio risk — correlation matrix, beta, VaR, concentration."""
    import risk_model
    try:
        return risk_model.portfolio_risk()
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/signals/{ticker}")
async def factor_signals(ticker: str):
    """Systematic factor signals (momentum/trend/mean-reversion/RSI) + composite."""
    import signals
    try:
        return signals.compute(ticker.upper())
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/memory/similar")
async def memory_similar(ticker: str = "", direction: str = "", thesis: str = ""):
    """Retrieve the most analogous past trades to a candidate setup."""
    import memory
    try:
        return memory.recall_similar(ticker.upper(), direction.upper(), thesis)
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/tca")
async def tca_report():
    """Post-trade execution quality (realized slippage vs decision price)."""
    import tca
    try:
        return tca.report()
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/tca/estimate")
async def tca_estimate(ticker: str, shares: float, price: float):
    """Pre-trade round-trip cost estimate (spread + market impact) in bps."""
    import tca
    try:
        return tca.estimate_cost(ticker.upper(), shares, price)
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/regime")
async def market_regime():
    """Current market regime (trend + volatility) and suggested risk posture."""
    import regime
    try:
        return regime.detect()
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/promotion")
async def promotion_gate():
    """Live-promotion gate — is the strategy statistically ready for real money?"""
    import promotion
    try:
        return promotion.evaluate()
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/tactical/allocation")
async def tactical_allocation():
    """Current target allocation from the tactical strategy (vol-targeted equity
    with a GEM crash overlay) — the one system that cleared out-of-sample testing.
    Recommendation only; places no orders."""
    import tactical_strategy
    try:
        return tactical_strategy.current_allocation()
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}

@app.get("/api/volscaled/allocation")
async def volscaled_allocation():
    """Current target equity exposure from the volatility-scaled strategy — the
    project's best/most-robust system (Sharpe 0.95 vs SPY 0.67, ~1/3 the drawdown).
    Recommendation only; places no orders."""
    import vol_scaled_strategy
    try:
        return vol_scaled_strategy.current_allocation()
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}

@app.get("/api/crypto/signal")
async def crypto_signal():
    """Crypto trend signal (BTC/ETH above/below 50-day average → HOLD/CASH) — the
    stress-tested crypto strategy. Speculative satellite. Recommendation only."""
    import crypto_strategy
    try:
        return crypto_strategy.current_signal()
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}

@app.get("/api/plan")
async def master_plan():
    """The unified daily/weekly plan: validated core (vol-scaling + GEM crash
    protection) + a strictly-capped speculative satellite (agent signals).
    Recommendation only; places no orders."""
    import master_allocator
    try:
        return master_allocator.current_plan()
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}

@app.get("/api/broker/webull/holdings")
async def webull_holdings():
    """Read-only WeBull account + positions, independent of the active broker.
    Never places orders — used purely to display WeBull holdings in the UI."""
    try:
        from brokers import webull_broker
        if not webull_broker.is_available():
            return {"available": False, "account": {}, "positions": []}
        return {
            "available": True,
            "account": webull_broker.get_account(),
            "positions": webull_broker.get_positions(),
        }
    except Exception as e:
        return {"available": False, "error": str(e)[:200], "account": {}, "positions": []}


# ─── Strategy A/B comparison ──────────────────────────────────────────────────

@app.get("/api/strategies/compare")
async def strategies_compare():
    import strategies
    return strategies.compare()

@app.get("/api/strategies/list")
async def strategies_list():
    import strategies
    return {"strategies": strategies.STRATEGIES}


# ─── Health / liveness ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Liveness + key subsystem status. Used by the watchdog and status.sh."""
    import os as _os, time as _t
    hb_age = None
    try:
        if _os.path.exists(HEARTBEAT_FILE):
            hb_age = round(_t.time() - float(open(HEARTBEAT_FILE).read().strip()), 1)
    except Exception:
        pass
    # Quick broker reachability (cheap, timeout-bounded)
    broker_ok = False
    broker_name = "alpaca"
    broker_env = "paper"
    webull_live = False
    try:
        import broker
        broker_ok = broker.is_available()
        broker_name = broker.active_broker_name()
        broker_env = broker.broker_env()
        webull_live = (broker_name == "webull"
                       and _os.environ.get("WEBULL_LIVE_TRADING", "").strip().lower()
                       in ("1", "true", "yes", "on"))
    except Exception:
        pass
    return {
        "status": "ok",
        "uptime_sec": round(_t.time() - _START_TIME, 0),
        "heartbeat_age_sec": hb_age,
        "mode": agent_orchestrator.get_mode(),
        "broker_available": broker_ok,
        "broker": broker_name,
        "broker_env": broker_env,
        "webull_live_trading": webull_live,
        "ts": _t.time(),
    }


# ─── Self-update ──────────────────────────────────────────────────────────────

import subprocess as _sp

_PROJ_DIR = _os.path.join(_os.path.dirname(__file__), "..")

def _git(*args):
    try:
        return _sp.check_output(["git", "-C", _PROJ_DIR, *args],
                                stderr=_sp.DEVNULL, timeout=15).decode().strip()
    except Exception:
        return ""

@app.get("/api/version")
async def version():
    """Current code version + whether an update is available on the remote."""
    current = _git("rev-parse", "--short", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    subject = _git("log", "-1", "--pretty=%s")
    has_remote = bool(_git("remote", "get-url", "origin"))
    update_available, behind = False, 0
    if has_remote:
        _git("fetch", "origin", branch or "main")
        local = _git("rev-parse", "HEAD")
        remote = _git("rev-parse", f"origin/{branch}")
        if local and remote and local != remote:
            update_available = True
            try:
                behind = int(_git("rev-list", "--count", f"{local}..{remote}") or 0)
            except Exception:
                behind = 0
    return {
        "version": current, "branch": branch, "subject": subject,
        "has_remote": has_remote, "update_available": update_available,
        "commits_behind": behind,
    }

@app.post("/api/update")
async def do_update():
    """Run the self-update script (pull, rebuild, restart) in the background."""
    script = _os.path.join(_PROJ_DIR, "update.sh")
    if not _os.path.exists(script):
        raise HTTPException(404, "update.sh not found")
    # Fire-and-forget; backend will be restarted by the script
    _sp.Popen(["/bin/bash", script], cwd=_PROJ_DIR,
              stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
    return {"status": "update_started", "note": "Backend will restart; the app reloads automatically."}
