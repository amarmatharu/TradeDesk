# TradeDesk Multi-Agent Trading System — Master Plan

## Vision
Convert noise (1000s of news/filings/price events per day) into trades (5–10 high-conviction setups per week).
The user becomes a manager of the system, not a manual scanner.

---

## Architecture

```
                  ┌─────────────────────────────────┐
                  │   EVENT BUS (news, prices, AI)  │
                  └────────────┬────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
   ┌────▼────┐            ┌────▼────┐            ┌────▼────┐
   │  SCOUT  │  filings   │RESEARCH │            │ MONITOR │
   │  Haiku  │──tradable?─►  Sonnet │            │  Haiku  │
   └─────────┘            └────┬────┘            └────┬────┘
                               │                      │
                          deep dive                 watches open
                          + thesis                  positions
                               │                      │
                          ┌────▼────┐            ┌────▼────┐
                          │  RISK   │            │  EXIT   │
                          │  Sonnet │            │ DECIDER │
                          └────┬────┘            └─────────┘
                               │
                          ┌────▼────┐
                          │ TRADER  │  final BUY/PASS
                          │  Opus   │  with confidence
                          └─────────┘
```

---

## The Five Agents

### 1. Scout Agent (Haiku — fast, cheap)
- **Role**: Triage every event from feeds
- **Input**: Single event (news article, 8-K filing, price move)
- **Output**: `{tradable_score: 1-10, direction: BULLISH|BEARISH, tickers: [], urgency: TODAY|THIS_WEEK|LOW, one_liner: "..."}`
- **Filter**: Only events with score ≥7 progress to Research
- **Cost**: ~$0.0001 per call. Runs on every alert (~1000/day).

### 2. Research Agent (Sonnet — deep thinker)
- **Role**: Build a complete trade thesis
- **Triggered by**: Scout score ≥7
- **Input**: Event + ticker(s) + scout summary
- **Pulls**: Live price (Alpaca), full technicals, recent earnings, sector context, fundamentals
- **Output**: Full trade plan
  ```json
  {
    "ticker": "XXX",
    "direction": "LONG|SHORT",
    "thesis": "2-3 sentences",
    "entry": number,
    "stop": number,
    "target1": number,
    "target2": number,
    "time_horizon": "X-Y days",
    "confidence": 1-10,
    "catalysts": [...],
    "risks": [...]
  }
  ```
- **Cost**: ~$0.02 per call. Runs 10–20×/day.

### 3. Risk Agent (Sonnet — gatekeeper)
- **Role**: Veto power. Validates trade against portfolio state.
- **Input**: Research thesis + current portfolio + open positions
- **Checks**:
  - Position size ≤ 1.5% of portfolio
  - R:R ≥ 2:1
  - Open positions count < max_positions (5)
  - Sector exposure < max_sector_pct (30%)
  - Cash available
  - Correlation with existing positions (don't double down)
  - Avoid trades against active opposite positions
- **Output**: `{approved: bool, reason: "...", adjustments: {...}}`

### 4. Trader Agent (Opus or Sonnet — final decision)
- **Role**: The only agent that creates trades
- **Input**: Scout score + Research thesis + Risk approval
- **Output**: `BUY | WAIT | PASS` with confidence + reasoning
- **Safety**: In "Suggest only" mode, surfaces decision to user. In "Auto" mode, executes.

### 5. Monitor Agent (Haiku — runs every minute)
- **Role**: Watch every open position
- **Triggers exit when**:
  - Stop loss hit
  - Target 1 hit → trim 50%, move stop to breakeven
  - Target 2 hit → close all
  - Time stop (held > horizon without target hit)
  - Thesis broken (e.g., expected catalyst didn't happen)
- **Output**: Exit instruction with reason

---

## Phase Plan

### ✅ Pre-phase: Already Built
- Benzinga news feed (real-time SSE)
- SEC EDGAR feed (8-K, Form 4)
- Alpaca market data
- AI brain (Claude integration)
- Scanner (manual, one-shot)
- Portfolio tracking
- Settings UI

### 🚧 Phase 1: Event Bus + Scout (TARGET: BUILD NOW)
- Central event bus (asyncio Queue, persistent log)
- All feeds dump into bus
- Scout agent processes every event
- Logs scores + reasoning per event
- UI: "Agents" tab showing real-time scout decisions

### 🚧 Phase 2: Research + Risk + Trader (TARGET: BUILD NOW)
- Wire the full pipeline
- When Scout returns ≥7 → Research → Risk → Trader
- Trades get **suggested** (not executed) automatically
- UI: "Pending Trades" panel — user reviews and approves
- Full decision log per trade (every agent's reasoning)

### ✅ Phase 3: Monitor + Exit (DONE)
- Background loop watches open positions every 60s ✓
- Hard rules for stop hit / T1 hit / T2 hit / time stop ✓
- AI nuanced check (every 5 min per position) for thesis status ✓
- Auto-trims at T1, moves stop to breakeven ✓
- Auto-exits at T2, stop, or thesis broken ✓
- All exits broadcast as bus events (CRITICAL impact) ✓
- New table: `position_checks` — full audit log ✓
- New table: `position_meta` — tracks T1 hit, BE moved per position ✓
- API: `/api/agents/monitor/checks`, `/check-now/{id}`, `/status` ✓
- UI: Monitor tab in AgentsPanel showing live positions + recent decisions ✓

### ✅ Phase 4: Trade Journal + Learning Loop (DONE)
- Journal agent runs on every closed position ✓
  - Auto-triggered by Monitor on exit ✓
  - Auto-triggered by manual close endpoint ✓
- Full post-mortem analysis: what worked, what failed, lessons, key takeaway ✓
- Quality score 1-10 (independent of outcome) ✓
- Pattern tagging: e.g. `earnings_chaser`, `ema_pullback_catalyst`, `unhedged_binary_event` ✓
- Aggregate `learnings` table tracking each pattern's win rate + avg R-multiple ✓
- Confidence levels: LOW (n<4), MEDIUM (n<10), HIGH (n≥10) ✓
- Auto-classification: FAVOR / NEUTRAL / AVOID based on stats ✓
- **Learnings injected into Scout and Research prompts** — system gets smarter every trade ✓
- New tables: `trade_journal`, `learnings` ✓
- API: `/api/agents/journal/entries`, `/stats`, `/learnings`, `/backfill`, `/analyze/{id}` ✓
- UI: Journal tab in AgentsPanel with stats, playbook, full post-mortems ✓

---

## 🧪 ACTIVE EXPERIMENT: 1-2 Week Autonomous Paper Run

Started: 2026-06-06 · Mode: AUTO_PAPER · Starting capital: $25,000

**How it works:**
- Backend runs under **launchd** (`com.tradedesk.backend`) — auto-restarts on crash, starts at login (`KeepAlive` + `RunAtLoad`)
- Mode persisted in `agent_settings` table — survives restarts
- Agents auto-execute BUY decisions as paper positions (live Alpaca fill prices)
- Both event-pipeline AND high-conviction auto-scanner setups execute
- Monitor manages exits (trim/stop/target/thesis); Journal learns from every close
- Capital guard: max 40% per position, never exceeds available cash
- Hourly equity snapshots → `paper_snapshots` table

**Monitoring:**
- `~/trading-platform/status.sh` — full status report anytime
- `GET /api/paper/report` — JSON report
- `GET /api/paper/snapshots` — equity curve
- Agents tab in the app — live view

**Controls:**
- Start:  `POST /api/paper/start  {starting_capital, notes}`
- Stop:   `POST /api/paper/stop`  (reverts to SUGGEST)
- Service: `launchctl {kickstart -k | unload | load} gui/$(id -u)/com.tradedesk.backend`

**Files added for this phase:**
- `backend/paper_trader.py` — execution, session, snapshots, reporting
- `~/Library/LaunchAgents/com.tradedesk.backend.plist` — persistent service
- `status.sh` — CLI status report

**Goal:** Accumulate enough closed trades (target n≥4 per pattern) so the `learnings`
table emits FAVOR/AVOID signals that measurably bias Scout + Research toward
profitable patterns and away from losing ones.

---

## 🔧 Hardening Upgrades (added 2026-06-06)

Three critical gaps closed before the experiment matters:

**1. Real Alpaca paper orders (`broker.py`)**
- Replaced fantasy local fills with actual Alpaca paper orders
- **Bracket orders**: entry + hard stop + take-profit, enforced server-side at the broker
  (stops are now real, not soft timer checks — survive backend downtime)
- Real fill prices from Alpaca's simulator (models spread/slippage)
- Monitor `reconcile_broker()` detects broker-side stop/target fills (fill-driven, not absence-driven → safe across weekends/queued orders)
- Falls back to simulated fill only if broker unavailable

**2. Circuit breakers (`risk_guard.py`)**
- Checked before EVERY new position. Blocks new trades when tripped:
  - Daily loss limit: -4%
  - Max drawdown from session peak: -10%
  - Consecutive losses: 4 (tilt protection)
  - Daily trade cap: 8 (over-trading guard)
- State persisted (`risk_guard_state`) — survives restarts
- API: `/api/risk/guard` · `/config` · `/reset` · `/halt`

**3. Pattern taxonomy (`agents/journal.py`)**
- Fixed 23-pattern canonical taxonomy — Journal MUST tag from it
- `normalize_patterns()` maps any raw tag → canonical key (fuzzy fallback)
- Fixes the aggregation bug: tags now converge to n≥4 for FAVOR/AVOID
  instead of fragmenting into one-off strings

---

## 🆚 STRATEGY A/B TEST (added 2026-06-06)

Run two strategies head-to-head on EQUAL capital, let data pick the winner before retiring either.

| | Strategy A: Momentum | Strategy B: Insider Edge |
|---|---|---|
| Capital | $25,000 | $25,000 |
| Signal | News (Benzinga) + scanner | Cluster insider buys (Form 4) |
| Universe | Liquid large/mid caps | Under-covered $50M–$2B small caps |
| Thesis | React to catalysts | Follow smart money where institutions can't go |
| Edge premise | Speed (weak for retail) | Structural: smallness + deep AI coverage of long tail |

**Why two:** Strategy A is the original system — likely low edge (competes with HFT on efficient
large-caps). Strategy B targets a documented retail edge (cluster insider buying on small caps).
Running both proves which—if either—actually works, vs SPY buy-and-hold.

**Implementation (additive — nothing removed):**
- `strategies.py` — registry, per-strategy capital pools, comparison report
- `universe.py` — small-cap qualifier (cap $50M–$2B, liquid, no penny/fraud)
- `edgar_feed.py` — insider-cluster detection (≥2 distinct insiders buy same ticker in 14d)
- `positions.strategy_tag` column — every trade tagged to its strategy
- Scout/orchestrator route events → strategy; per-strategy capital guard
- `/api/strategies/compare` — head-to-head + SPY benchmark

**Decision rule:** After each strategy has ≥30 closed trades, compare return + win-rate + avg-R
vs each other AND vs SPY. Retire any that doesn't beat SPY. Keep what does.

**The honest bar:** Beating SPY buy-and-hold over the window = real edge. Not beating it = the
strategy is noise, retire it regardless of how good the trades looked.

---

## Modes (Safety)

| Mode | What it does |
|---|---|
| `SHADOW` | Agents run, log decisions, but no trades created. For testing prompts. |
| `SUGGEST` (default) | Agents create pending trades. User approves each one. |
| `AUTO_PAPER` | Agents auto-execute against Alpaca paper account. |
| `AUTO_LIVE` | Agents auto-execute against real broker. **Requires explicit unlock.** |

---

## Database Schema (new tables)

```sql
CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  source TEXT,           -- benzinga | edgar | price | manual
  type TEXT,             -- news | 8-K | form4 | scan
  data JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_runs (
  id INTEGER PRIMARY KEY,
  event_id INTEGER,
  agent TEXT,            -- scout | research | risk | trader | monitor
  input JSON,
  output JSON,
  duration_ms INTEGER,
  model TEXT,
  tokens_used INTEGER,
  cost_usd REAL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE TABLE pending_trades (
  id INTEGER PRIMARY KEY,
  event_id INTEGER,
  ticker TEXT,
  direction TEXT,
  entry REAL,
  stop REAL,
  target1 REAL,
  target2 REAL,
  shares INTEGER,
  thesis TEXT,
  confidence INTEGER,
  scout_output JSON,
  research_output JSON,
  risk_output JSON,
  trader_output JSON,
  status TEXT DEFAULT 'pending',   -- pending | approved | rejected | expired
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  decided_at TIMESTAMP,
  FOREIGN KEY (event_id) REFERENCES events(id)
);
```

---

## Decisions & Rationale

- **Use SSE for real-time UI updates** — already proven working for news feeds
- **Use Claude Haiku for Scout** — needs to be fast and cheap (1000s of calls/day)
- **Use Claude Sonnet for Research/Risk** — needs deeper reasoning
- **Use Claude Opus for Trader** — final decision quality matters most
- **Keep agents stateless** — pass all context in. Persistence is in the DB, not agent memory.
- **Log everything** — every agent output, every reasoning. Build the data for Phase 4 learning loop.
- **Start in SUGGEST mode** — user approves trades. Don't auto-trade until trust is built.

---

## Open Questions (resolve later)

- Real broker integration (Alpaca Live? IBKR? Manual?)
- Multi-ticker trades (e.g., pair trades, sector rotations)
- Position-level monitoring frequency (1m? 5m? real-time?)
- Backtest mode for tuning prompts
- Options trading integration

---

## How to Resume This Plan

If we ever pause and come back, the entry point is this file and:
- `backend/agents/` — agent implementations
- `backend/event_bus.py` — event routing
- `backend/main.py` — `/api/agents/*` endpoints
- `frontend/src/components/AgentsPanel.jsx` — UI for decisions
- Tables: `events`, `agent_runs`, `pending_trades`
