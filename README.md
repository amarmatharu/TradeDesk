# TradeDesk — AI Trading Platform

A personalized desktop trading platform powered by Claude AI. Runs as a native Mac app.

## Quick Start

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
