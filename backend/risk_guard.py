"""
Risk Guard — portfolio-level circuit breakers.

Checked before EVERY new position. If any breaker is tripped, new trades are
blocked (existing positions still managed by Monitor) until the condition clears
or is manually reset.

Breakers:
  1. Daily loss limit   — halt new trades if today's P&L ≤ -X% of equity
  2. Max drawdown       — halt if equity falls X% below the session peak
  3. Consecutive losses — halt after N losing trades in a row (tilt protection)
  4. Daily trade cap    — max new positions opened per day (over-trading guard)

State persisted in `risk_guard_state` so it survives restarts.
"""

import json
from datetime import datetime, timezone
from database import get_connection

# ─── Config (defaults; overridable via settings) ───────────────────────────────
DEFAULTS = {
    "daily_loss_limit_pct": 4.0,      # halt if down 4% on the day
    "max_drawdown_pct": 10.0,         # halt if down 10% from session peak
    "max_consecutive_losses": 4,      # halt after 4 losses in a row
    "max_trades_per_day": 8,          # max new positions per day
}


def init_tables():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS risk_guard_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


def _get(key, default=None):
    conn = get_connection()
    row = conn.execute("SELECT value FROM risk_guard_state WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def _set(key, value):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO risk_guard_state (key, value) VALUES (?, ?)",
        (key, json.dumps(value))
    )
    conn.commit()
    conn.close()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_config() -> dict:
    cfg = dict(DEFAULTS)
    saved = _get("config")
    if saved:
        cfg.update(saved)
    return cfg


def set_config(updates: dict):
    cfg = get_config()
    cfg.update({k: v for k, v in updates.items() if k in DEFAULTS})
    _set("config", cfg)
    return cfg


# ─── Daily / peak equity tracking ──────────────────────────────────────────────

def _current_equity() -> float:
    """Equity = starting capital + realized + unrealized (from paper session)."""
    try:
        import paper_trader
        rep = paper_trader.session_report()
        return rep.get("current_equity", 25000)
    except Exception:
        return 25000


def _record_equity_marks(equity: float):
    """Track day-start equity and session peak."""
    today = _today()
    day_start = _get("day_start")
    if not day_start or day_start.get("date") != today:
        _set("day_start", {"date": today, "equity": equity})
    peak = _get("peak_equity", {"equity": equity})
    if equity > peak.get("equity", 0):
        _set("peak_equity", {"equity": equity})


# ─── Trade outcome tracking (for consecutive-loss + daily-count) ───────────────

def record_trade_opened():
    today = _today()
    count = _get("trades_today", {"date": today, "count": 0})
    if count.get("date") != today:
        count = {"date": today, "count": 0}
    count["count"] += 1
    _set("trades_today", count)


def record_trade_closed(pnl: float):
    """Update consecutive-loss streak when a trade closes."""
    streak = _get("loss_streak", 0)
    if pnl < 0:
        streak = (streak or 0) + 1
    else:
        streak = 0
    _set("loss_streak", streak)


# ─── The check ──────────────────────────────────────────────────────────────────

def check() -> dict:
    """
    Returns { allowed: bool, reason, breakers: {...}, metrics: {...} }.
    Call before opening any new position.
    """
    init_tables()
    cfg = get_config()

    # Manual halt override
    if _get("manual_halt", False):
        return {"allowed": False, "reason": "Manually halted", "breakers": {"manual": True}}

    equity = _current_equity()
    _record_equity_marks(equity)

    day_start = _get("day_start", {"equity": equity}).get("equity", equity)
    peak = _get("peak_equity", {"equity": equity}).get("equity", equity)
    loss_streak = _get("loss_streak", 0) or 0
    today = _today()
    trades_today = _get("trades_today", {"date": today, "count": 0})
    trades_count = trades_today["count"] if trades_today.get("date") == today else 0

    daily_pnl_pct = (equity - day_start) / day_start * 100 if day_start else 0
    drawdown_pct = (equity - peak) / peak * 100 if peak else 0

    breakers = {}
    reasons = []

    if daily_pnl_pct <= -cfg["daily_loss_limit_pct"]:
        breakers["daily_loss"] = True
        reasons.append(f"Daily loss {daily_pnl_pct:.1f}% ≤ -{cfg['daily_loss_limit_pct']}%")

    if drawdown_pct <= -cfg["max_drawdown_pct"]:
        breakers["max_drawdown"] = True
        reasons.append(f"Drawdown {drawdown_pct:.1f}% ≤ -{cfg['max_drawdown_pct']}%")

    if loss_streak >= cfg["max_consecutive_losses"]:
        breakers["consecutive_losses"] = True
        reasons.append(f"{loss_streak} losses in a row ≥ {cfg['max_consecutive_losses']}")

    if trades_count >= cfg["max_trades_per_day"]:
        breakers["daily_trade_cap"] = True
        reasons.append(f"{trades_count} trades today ≥ {cfg['max_trades_per_day']}")

    allowed = len(breakers) == 0
    return {
        "allowed": allowed,
        "reason": "; ".join(reasons) if reasons else "All clear",
        "breakers": breakers,
        "metrics": {
            "equity": round(equity, 2),
            "day_start_equity": round(day_start, 2),
            "peak_equity": round(peak, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "loss_streak": loss_streak,
            "trades_today": trades_count,
        },
        "config": cfg,
    }


def manual_halt(on: bool):
    _set("manual_halt", on)


def reset_breakers():
    """Clear streak + manual halt + reset day marks to current equity."""
    eq = _current_equity()
    _set("loss_streak", 0)
    _set("manual_halt", False)
    _set("day_start", {"date": _today(), "equity": eq})
    _set("peak_equity", {"equity": eq})
    _set("trades_today", {"date": _today(), "count": 0})
    return check()
