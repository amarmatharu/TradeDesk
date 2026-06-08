# TradeDesk — Complete System Architecture

> AI-powered personal trading platform. Multi-agent system that ingests market data + news,
> autonomously surfaces trade setups, manages open positions, and learns from every closed trade.

---

## 1. High-Level System Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         ELECTRON DESKTOP APP (macOS)                            │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  React Frontend (Vite)                                                     │ │
│  │  Chart · Analysis · News · Portfolio · Scanner · SEC · Agents · Settings  │ │
│  └────────────────────────────────┬─────────────────────────────────────────┘ │
│         loads from localhost:8765  │  REST + SSE (EventSource)                  │
└────────────────────────────────────┼──────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────▼──────────────────────────────────────────┐
│                      PYTHON BACKEND  (FastAPI, port 8765)                         │
│                                                                                  │
│  ┌────────────── DATA FEEDS (background async loops) ─────────────────────────┐ │
│  │  benzinga_feed   → market-wide news, every 20s                             │ │
│  │  edgar_feed      → SEC 8-K + Form 4 filings, every 60s                     │ │
│  │  alpaca_data     → real-time prices/OHLCV/technicals (on demand + cache)   │ │
│  └────────────────────────────────┬───────────────────────────────────────────┘ │
│                                    │ publish()                                    │
│  ┌─────────────────────────────────▼──────────────────────────────────────────┐ │
│  │                         EVENT BUS  (event_bus.py)                           │ │
│  │   - persists every event to SQLite                                         │ │
│  │   - broadcasts to UI (SSE) + agent handlers                                │ │
│  └────────────────────────────────┬───────────────────────────────────────────┘ │
│                                    │ handle_event()                               │
│  ┌─────────────────────────────────▼──────────────────────────────────────────┐ │
│  │                    AGENT ORCHESTRATOR  (orchestrator.py)                    │ │
│  │                                                                            │ │
│  │   SCOUT ──►(≥7)──► RESEARCH ──► RISK ──► TRADER ──► PENDING TRADE          │ │
│  │   Haiku           Sonnet       Sonnet    Sonnet     (user approves)        │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌──────────── BACKGROUND WORKERS ───────────────────────────────────────────┐ │
│  │  MONITOR (60s)   → watches open positions, auto-trim/exit                  │ │
│  │  AUTO-SCANNER    → full market scan every 30 min (market hours)            │ │
│  │  JOURNAL         → post-mortem on every closed trade → learnings           │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌──────────── SQLite (trading.db) ──────────────────────────────────────────┐ │
│  │  positions · watchlist · events · agent_runs · pending_trades             │ │
│  │  position_checks · position_meta · trade_journal · learnings              │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
            │              │               │                │
       ┌────▼───┐    ┌─────▼────┐    ┌─────▼─────┐    ┌─────▼──────┐
       │ Alpaca │    │ Benzinga │    │ SEC EDGAR │    │  Anthropic │
       │ (price)│    │  (news)  │    │ (filings) │    │  (Claude)  │
       └────────┘    └──────────┘    └───────────┘    └────────────┘
```

---

## 2. Component Inventory

### Backend (Python / FastAPI) — ~5,100 LOC

| File | LOC | Responsibility |
|------|-----|----------------|
| `main.py` | 1211 | FastAPI app, all 48 endpoints, startup/shutdown, settings, serves frontend |
| `event_bus.py` | 158 | Central pub/sub. Persists events, broadcasts to UI + agents |
| `alpaca_data.py` | 376 | Real-time prices, OHLCV, technical indicators, market overview |
| `benzinga_feed.py` | 319 | Market-wide news polling, keyword scoring, SSE broadcast |
| `edgar_feed.py` | 469 | SEC 8-K + Form 4 polling, XML parsing, filing summarization |
| `ai_brain.py` | 129 | Anthropic client factory, base analysis + sentiment functions |
| `auto_scanner.py` | 117 | Scheduled full-market scans (every 30 min, market hours) |
| `database.py` | 197 | SQLite schema (11 tables) + init |
| `market_data.py` | 294 | yfinance fallback for fundamentals/news |
| `mock_data.py` | 135 | Demo data fallback |

### Agents — ~1,290 LOC

| File | LOC | Model | Role |
|------|-----|-------|------|
| `agents/scout.py` | 157 | Haiku 4.5 | Triage every event 1-10. Filter noise. |
| `agents/research.py` | 186 | Sonnet 4.6 | Build full trade thesis with entry/stop/targets |
| `agents/risk.py` | 204 | Sonnet 4.6 | Portfolio rule checks. Veto power. |
| `agents/trader.py` | 177 | Sonnet 4.6 | Final BUY/WAIT/PASS decision, creates pending trade |
| `agents/monitor.py` | 420 | Haiku 4.5 | Watch open positions, auto-trim/exit |
| `agents/journal.py` | 390 | Sonnet 4.6 | Post-mortem each closed trade, build learnings |
| `agents/orchestrator.py` | 144 | — | Wires pipeline together, mode control |

### Frontend (React / Vite) — ~3,600 LOC

| File | LOC | Responsibility |
|------|-----|----------------|
| `App.jsx` | 218 | Tab routing, layout, SSE wiring, global state |
| `components/AgentsPanel.jsx` | 684 | Pending trades · Monitor · Journal · Activity · Stats |
| `components/Settings.jsx` | 410 | API keys, portfolio config, display prefs |
| `components/ScannerPanel.jsx` | 359 | Auto-scan results, top setups |
| `components/EdgarPanel.jsx` | 331 | SEC live filings, earnings, filing search + AI summary |
| `components/AlertPanel.jsx` | 278 | Real-time Benzinga + EDGAR alert stream |
| `components/AnalysisPanel.jsx` | 251 | Per-ticker AI deep analysis |
| `components/TradeModal.jsx` | 191 | Manual trade entry + risk calculator |
| `components/ChartPanel.jsx` | 189 | TradingView Lightweight Charts + technicals |
| `components/Portfolio.jsx` | 169 | Open/closed positions, P&L |
| `components/Sidebar.jsx` | 140 | Watchlist + portfolio summary |
| `components/NewsPanel.jsx` | 96 | Per-ticker news + sentiment |
| `components/Topbar.jsx` | 56 | Market indices ticker, settings gear |
| `api.js` | 28 | Axios client (baseURL localhost:8765) |

### Electron Shell

| File | Responsibility |
|------|----------------|
| `electron/main.js` | Spawns Python backend, creates window, loads from localhost:8765, app menu |
| `electron/preload.js` | Secure IPC bridge (switch-tab, open-settings) |

---

## 3. The Agent Pipeline (Heart of the System)

```
EVENT (news / 8-K / Form 4)
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ SCOUT  (Haiku, ~$0.0002/call, ~300 calls/day)               │
│   Input:  raw event + watchlist context + learnings playbook │
│   Output: { tradable_score, direction, tickers, urgency,    │
│             category, one_liner }                            │
│   Gate:   score ≥ 7 → advance, else FILTERED_OUT            │
└──────────────────────┬──────────────────────────────────────┘
                       │ ~5% pass
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ RESEARCH  (Sonnet, ~$0.02/call, ~15 calls/day)              │
│   Pulls:  live price, technicals, fundamentals (Alpaca)     │
│   Output: full plan { direction, thesis, entry, stop,       │
│             target1/2, risk_reward, shares, confidence,      │
│             catalysts, risks, invalidation }                │
│   Gate:   direction≠NO_TRADE && confidence≥5               │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ RISK  (hard rules + Sonnet)                                  │
│   Hard checks (free): already holding? risk>1.5%? R:R<2?    │
│             >5 positions? not enough cash?                   │
│   AI checks: sector correlation, concentration, timing      │
│   Output: { approved, reason, warnings, risk_score,         │
│             adjustments }                                    │
│   Gate:   approved == true                                   │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ TRADER  (Sonnet — final decision)                           │
│   Synthesizes all 3 prior outputs                           │
│   Output: { action: BUY|WAIT|PASS, confidence, reasoning,  │
│             final_shares/entry/stop/targets }              │
│   If BUY && mode≠SHADOW → create pending_trade             │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
              PENDING TRADE (status=pending)
                       │
            user clicks Approve / Reject
                       │
         ┌─────────────┴─────────────┐
       Approve                     Reject
         │                           │
   creates OPEN position      status=rejected
         │
         ▼
   MONITOR takes over
```

**Funnel math:** ~1000 events/day → ~300 Scout → ~15 Research → ~3 Risk-pass → ~1-2 BUYs/day.
Total AI cost: ~$0.30-0.50/day.

---

## 4. Position Lifecycle (Monitor + Journal)

```
OPEN position
   │
   ▼  every 60s
MONITOR  (monitor.py)
   │
   ├─ Hard rules (free, instant):
   │    price ≤ stop      → EXIT_STOP (close 100%)
   │    price ≥ target1   → TRIM_HALF (sell 50%, stop→breakeven)
   │    price ≥ target2   → EXIT_TARGET (close remainder)
   │    15+ days flat      → EXIT_THESIS_BROKEN (time stop)
   │
   ├─ AI check (Haiku, every 5 min/position):
   │    thesis still valid? → HOLD | EXIT_THESIS_BROKEN | MOVE_STOP_TO_BE
   │
   ▼ on any EXIT
CLOSED position  ──►  publishes CRITICAL bus event
   │
   ▼  auto-triggered
JOURNAL  (journal.py, Sonnet)
   │
   ├─ Analyzes: what worked, what failed, lessons, quality score 1-10
   ├─ Tags patterns: e.g. earnings_chaser, ema_pullback_catalyst
   ├─ Computes R-multiple, days held, outcome
   │
   ▼
LEARNINGS table  (per-pattern win-rate + avg-R)
   │
   ▼  format_playbook_for_prompt()
INJECTED back into SCOUT + RESEARCH prompts
   │
   └──────► THE LEARNING LOOP (system improves with every trade)
```

---

## 5. Data Sources

| Source | Auth | Used For | Cadence |
|--------|------|----------|---------|
| **Alpaca** (Paper keys) | API key + secret | Real-time prices, OHLCV, technicals, market overview | On-demand, 60s cache |
| **Benzinga Pro** | API token | Market-wide breaking news | Poll 20s |
| **SEC EDGAR** | None (public) | 8-K material events, Form 4 insider txns | Poll 60s |
| **Anthropic** | API key | All agent reasoning (Haiku + Sonnet) | Per agent call |
| **yfinance** | None | Fallback for fundamentals when Alpaca lacks | On-demand |

Keys stored in `backend/.env`, editable via Settings tab.

---

## 6. Database Schema (SQLite — 11 tables)

```
positions          open/closed trades (entry, stop, targets, pnl, status)
watchlist          tracked tickers
analysis_cache     cached per-ticker AI analysis

events             every event published to bus (source, type, impact, data)
agent_runs         every agent invocation (input, output, tokens, cost, duration)
pending_trades     BUY decisions awaiting user approval (full agent chain)
agent_settings     k/v config

position_checks     monitor audit log (verdict, reason, pnl at each check)
position_meta       per-position state (t1_hit, be_moved, trim_count)

trade_journal       post-mortems (what worked/failed, lessons, quality, R)
learnings           aggregated pattern stats (win_rate, avg_r, recommendation)
```

---

## 7. Operating Modes (Safety Ladder)

| Mode | Behavior |
|------|----------|
| `SHADOW` | Agents run + log, but never create trades. For prompt testing. |
| `SUGGEST` ★ default | Agents create pending trades. User approves each one. |
| `AUTO_PAPER` | Auto-execute against Alpaca paper account. (wired, not enabled) |
| `AUTO_LIVE` | Real broker execution. Locked — requires explicit unlock. |

Switchable live from Agents tab dropdown.

---

## 8. Real-Time Streams (SSE)

| Endpoint | Pushes |
|----------|--------|
| `/api/feed/stream` | Benzinga news alerts |
| `/api/edgar/stream` | SEC 8-K + Form 4 filings |
| `/api/agents/stream` | All bus events: pipeline results, pending trades, exits, journal entries |

Each has a replay buffer (last 50-100 events) so a fresh UI connection immediately sees recent activity.

---

## 9. API Surface (48 endpoints)

```
MARKET DATA
  GET  /api/market/overview
  GET  /api/stock/{t}              /history /quote /technicals /news /analyze
  GET  /api/risk/size

PORTFOLIO
  GET  /api/portfolio
  POST /api/portfolio/trade
  PUT  /api/portfolio/trade/{id}/close      → auto-triggers Journal
  DEL  /api/portfolio/trade/{id}

WATCHLIST            GET/POST/DEL /api/watchlist
SETTINGS             GET/POST /api/settings  · POST /api/settings/test

FEEDS
  GET  /api/feed/stream (SSE) /latest /earnings /fda   · POST /feed/restart

SCANNER
  GET  /api/scan          (force full scan)
  GET  /api/scan/latest   (last auto-scan result)

SEC EDGAR
  GET  /api/edgar/stream (SSE) /search /summarize /insider/{t}

EARNINGS            GET /api/earnings/calendar /watchlist /history/{t}

AGENTS
  GET  /api/agents/stream (SSE) /events /runs /stats
  GET/POST /api/agents/mode
  GET  /api/agents/pending-trades
  POST /api/agents/pending-trades/{id}/decision
  GET  /api/agents/monitor/checks /status   · POST /monitor/check-now/{id}
  GET  /api/agents/journal/entries /stats /learnings
  POST /api/agents/journal/analyze/{id} /backfill
```

---

## 10. Tech Stack

| Layer | Tech |
|-------|------|
| Desktop shell | Electron 42 (GPU accel disabled for macOS Tahoe) |
| Frontend | React 18 + Vite 5, inline styles, Lightweight Charts |
| Backend | FastAPI + Uvicorn, async throughout |
| AI | Anthropic Claude — Haiku 4.5 (cheap/fast) + Sonnet 4.6 (reasoning) |
| Market data | Alpaca SDK (alpaca-py) |
| News | Benzinga REST + SEC EDGAR (httpx) |
| Storage | SQLite (zero-config, local) |
| Packaging | electron-builder → .dmg (arm64 + x64) |

---

## 11. Build / Run

```bash
# Dev
~/trading-platform/launch.sh           # backend + electron window

# Package as installable .dmg
cd frontend && npm run electron:build  # → dist-electron/TradeDesk-1.0.0-arm64.dmg

# Backend only
cd backend && PYTHONUNBUFFERED=1 python3 -m uvicorn main:app --port 8765
```

---

## 12. What's Built vs. Roadmap

**Built (Phases 1-4 complete):**
- ✅ All 5 agents + orchestrator + event bus
- ✅ Auto-scanner (scheduled, no manual click)
- ✅ Market-wide news (not just watchlist)
- ✅ Position monitor with auto-trim/exit
- ✅ Trade journal + learning loop feeding back into prompts
- ✅ Packaged macOS desktop app

**Roadmap (see AGENT_PLAN.md):**
- Unusual Whales options flow integration
- AUTO_PAPER live trading via Alpaca
- Pre-trade checklist enforcement
- Backtest mode
- Broker position sync (Plaid/SnapTrade for Robinhood/Webull)
- Desktop push notifications
- Correlation matrix / sector heatmap
