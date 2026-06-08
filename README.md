# TradeDesk — AI Trading Platform

A personalized, multi-agent desktop trading platform powered by Claude AI. Runs as a native Mac app.

## Fresh-machine setup (one command)

```bash
git clone git@github.com:amarmatharu/TradeDesk.git
cd TradeDesk
./setup.sh            # installs deps, builds UI, sets up services
nano backend/.env     # paste your API keys (see backend/.env.example)
launchctl kickstart -k gui/$(id -u)/com.tradedesk.backend
```

`setup.sh` installs Python + Node deps, builds the frontend, installs the
launchd services (backend + watchdog + auto-update), and starts everything.
Required keys: **Anthropic** (AI) and **Alpaca paper** (prices + execution).
Optional: **Benzinga** (news).

Build the desktop app:
```bash
cd frontend && npm run electron:build
open dist-electron/*.dmg   # drag TradeDesk to Applications
```

## Self-update

Once a git remote is set, the app auto-pulls pushes every 15 min (or via
menu → *Check for Updates…*). `update.sh` rebuilds only what changed and the
app reloads itself. Only changes to `frontend/electron/main.js` / `preload.js`
need a manual `.dmg` rebuild.

## Operations

- `./status.sh` — full live status (P&L, positions, strategies, breakers, heartbeat)
- `./watchdog.sh` — liveness monitor (runs via launchd)
- `./update.sh` — pull + rebuild + restart
- Services: `com.tradedesk.{backend,watchdog,autoupdate}` (in `~/Library/LaunchAgents`)

---

## Legacy quick start (dev)

### 1. Add your Anthropic API key
```bash
echo 'ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE' > ~/trading-platform/backend/.env
```
Get a key at https://console.anthropic.com

### 2. Launch
```bash
~/trading-platform/dev.sh
```

That's it. The script starts everything and opens the desktop app.

---

## Features

| Feature | Details |
|---|---|
| **Live Charts** | TradingView candlestick charts with volume, 1D–1Y timeframes |
| **Technical Indicators** | EMA 20/50/200, RSI, MACD, Bollinger Bands, ATR, Stochastics |
| **AI Trade Analysis** | Full fundamental + technical + sentiment breakdown via Claude |
| **News Sentiment** | Per-ticker news feed with AI sentiment scoring |
| **Risk Management** | Automatic position sizing (1.5% rule), R:R calculator |
| **Portfolio Tracker** | Open/closed positions, unrealized P&L, win rate |
| **Watchlist** | Persistent watchlist with live prices |
| **Keyboard Shortcuts** | ⌘1–4 for tabs, ⌘, for preferences |

## Architecture

```
trading-platform/
├── backend/          Python FastAPI (port 8765)
│   ├── main.py       API routes
│   ├── market_data.py  yfinance + technical indicators
│   ├── ai_brain.py   Claude API integration
│   ├── mock_data.py  Fallback data when Yahoo Finance rate-limits
│   └── database.py   SQLite (positions, watchlist)
│
├── frontend/         React + Vite
│   └── src/
│       ├── App.jsx
│       └── components/
│           ├── ChartPanel.jsx    TradingView Lightweight Charts
│           ├── AnalysisPanel.jsx  AI trade analysis
│           ├── NewsPanel.jsx      News + sentiment
│           ├── Portfolio.jsx      Position tracker
│           ├── Sidebar.jsx        Watchlist
│           ├── Topbar.jsx         Market indices
│           └── TradeModal.jsx     Trade entry
│
└── electron/         Electron wrapper
    └── main.js       Window + backend lifecycle management
```

## Data Sources

- **Market data**: Yahoo Finance via `yfinance` (free, no key needed)
- **AI analysis**: Anthropic Claude API (key required for AI features)
- **Charts**: TradingView Lightweight Charts (free, open source)
- **Storage**: Local SQLite database

## Portfolio Settings

Edit `backend/main.py` to change:
```python
PORTFOLIO_SIZE = 25000.0   # Your portfolio size
RISK_PCT = 1.5             # % risked per trade
```
