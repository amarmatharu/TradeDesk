import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "trading.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'LONG',
            entry_price REAL NOT NULL,
            quantity REAL NOT NULL,
            stop_loss REAL,
            target1 REAL,
            target2 REAL,
            target3 REAL,
            status TEXT DEFAULT 'OPEN',
            exit_price REAL,
            exit_date TEXT,
            pnl REAL,
            notes TEXT,
            strategy TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT UNIQUE NOT NULL,
            added_at TEXT DEFAULT (datetime('now')),
            alert_price REAL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS analysis_cache (
            ticker TEXT PRIMARY KEY,
            analysis TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- ─── Multi-Agent System Tables ────────────────────────────

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            type TEXT NOT NULL,
            tickers TEXT,
            title TEXT,
            impact TEXT,
            data TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);

        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            agent TEXT NOT NULL,
            model TEXT,
            input TEXT,
            output TEXT,
            duration_ms INTEGER,
            tokens_in INTEGER,
            tokens_out INTEGER,
            cost_usd REAL,
            status TEXT DEFAULT 'success',
            error TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (event_id) REFERENCES events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_runs_event ON agent_runs(event_id);

        CREATE TABLE IF NOT EXISTS pending_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry REAL,
            stop REAL,
            target1 REAL,
            target2 REAL,
            shares INTEGER,
            risk_dollars REAL,
            position_value REAL,
            thesis TEXT,
            confidence INTEGER,
            scout_output TEXT,
            research_output TEXT,
            risk_output TEXT,
            trader_output TEXT,
            status TEXT DEFAULT 'pending',
            status_reason TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            decided_at TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_trades(status);

        CREATE TABLE IF NOT EXISTS agent_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- Position monitoring & exit decisions
        CREATE TABLE IF NOT EXISTS position_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            current_price REAL,
            unrealized_pnl REAL,
            unrealized_pnl_pct REAL,
            stop_distance_pct REAL,
            t1_distance_pct REAL,
            verdict TEXT,
            reason TEXT,
            action_taken TEXT,
            data TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (position_id) REFERENCES positions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_position_checks_position ON position_checks(position_id);

        -- Position-level metadata for monitor
        CREATE TABLE IF NOT EXISTS position_meta (
            position_id INTEGER PRIMARY KEY,
            t1_hit INTEGER DEFAULT 0,
            t2_hit INTEGER DEFAULT 0,
            be_moved INTEGER DEFAULT 0,
            trim_count INTEGER DEFAULT 0,
            last_check_at TEXT,
            FOREIGN KEY (position_id) REFERENCES positions(id)
        );

        -- Per-trade post-mortem (Phase 4: Learning Loop)
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            pnl_pct REAL,
            r_multiple REAL,           -- profit / initial risk
            days_held INTEGER,
            outcome TEXT,              -- WIN | LOSS | BREAKEVEN
            thesis_original TEXT,
            what_worked TEXT,
            what_failed TEXT,
            lessons TEXT,              -- JSON array of takeaways
            pattern_tags TEXT,         -- JSON array — e.g. ["earnings_beat", "oversold_bounce"]
            quality_score INTEGER,     -- 1-10, how well-executed regardless of outcome
            analysis_full TEXT,        -- complete AI analysis text
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (position_id) REFERENCES positions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_journal_ticker ON trade_journal(ticker);
        CREATE INDEX IF NOT EXISTS idx_journal_outcome ON trade_journal(outcome);

        -- Aggregated pattern learnings (Phase 4)
        CREATE TABLE IF NOT EXISTS learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT UNIQUE NOT NULL,
            description TEXT,
            sample_size INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            avg_r REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            confidence TEXT,           -- HIGH | MEDIUM | LOW (based on sample size)
            recommendation TEXT,       -- AVOID | NEUTRAL | FAVOR
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()

    # Migration: add strategy_tag columns (A/B test) if missing
    for table in ("positions", "pending_trades"):
        try:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
            if "strategy_tag" not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN strategy_tag TEXT DEFAULT 'momentum'")
                conn.commit()
        except Exception:
            pass

    # Seed watchlist with default tickers
    try:
        c.executemany(
            "INSERT OR IGNORE INTO watchlist (ticker) VALUES (?)",
            [("NVDA",), ("AAPL",), ("MSFT",), ("CAT",), ("XOM",), ("LLY",)]
        )
        conn.commit()
    except Exception:
        pass

    conn.close()
