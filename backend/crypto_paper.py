"""
Crypto paper-trading engine — forward-test the validated trend strategy.

Runs the stress-tested crypto trend rule (hold BTC/ETH above their 50-day
average, else cash) on a PAPER portfolio, 24/7, recording every trade and
snapshotting equity so we build a real FORWARD track record. This is the
promotion-gate discipline: prove the backtested edge holds live before any real
money — not "learning to trade better" (the rule is fixed & validated), but
learning WHETHER it works going forward.

Target: 50% of equity in each asset when its signal is HOLD, 0% when CASH; the
rest sits in cash. Rebalances only when a target drifts >2% of equity (avoids
churn). Everything persists in SQLite, so it survives restarts.
"""

import time
from datetime import datetime
from database import get_connection
import crypto_strategy

STARTING_CAPITAL = 10000.0
TARGET_WEIGHT = 0.5          # per asset when HOLD
REBAL_THRESHOLD = 0.02       # only trade if target drifts >2% of equity


def ensure_tables():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS crypto_paper (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL, btc_qty REAL DEFAULT 0, eth_qty REAL DEFAULT 0,
            start_capital REAL, started_at TEXT, last_step TEXT
        );
        CREATE TABLE IF NOT EXISTS crypto_paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, symbol TEXT, side TEXT, qty REAL, price REAL, value REAL,
            reason TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS crypto_paper_equity (
            ts REAL, equity REAL, btc_sig TEXT, eth_sig TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def _load():
    ensure_tables()
    conn = get_connection()
    row = conn.execute("SELECT * FROM crypto_paper WHERE id=1").fetchone()
    if row is None:
        conn.execute("INSERT INTO crypto_paper (id, cash, start_capital, started_at) VALUES (1,?,?,?)",
                     (STARTING_CAPITAL, STARTING_CAPITAL, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        row = conn.execute("SELECT * FROM crypto_paper WHERE id=1").fetchone()
    conn.close()
    return dict(row)


def _prices_and_signals():
    sig = crypto_strategy.current_signal()
    out = {}
    for a in sig.get("assets", []):
        if a.get("ok"):
            out[a["symbol"]] = (a["price"], a["signal"], a.get("pct_vs_ma50"))
    return out


def step() -> dict:
    """Run one rebalance step. Safe to call repeatedly (idempotent-ish)."""
    ps = _prices_and_signals()
    if "BTC" not in ps or "ETH" not in ps:
        return {"ok": False, "reason": "no crypto price/signal"}
    st = _load()
    cash = st["cash"]; qty = {"BTC": st["btc_qty"], "ETH": st["eth_qty"]}
    price = {k: ps[k][0] for k in ("BTC", "ETH")}
    signal = {k: ps[k][1] for k in ("BTC", "ETH")}

    equity = cash + sum(qty[k] * price[k] for k in qty)
    conn = get_connection()
    trades = []
    for k in ("BTC", "ETH"):
        target_val = TARGET_WEIGHT * equity if signal[k] == "HOLD" else 0.0
        cur_val = qty[k] * price[k]
        diff = target_val - cur_val
        if abs(diff) > equity * REBAL_THRESHOLD and price[k] > 0:
            dqty = diff / price[k]
            side = "BUY" if dqty > 0 else "SELL"
            cash -= dqty * price[k]
            qty[k] += dqty
            reason = f"signal {signal[k]} → target {int(TARGET_WEIGHT*100) if signal[k]=='HOLD' else 0}%"
            conn.execute("INSERT INTO crypto_paper_trades (ts, symbol, side, qty, price, value, reason) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (time.time(), k, side, round(abs(dqty), 8), round(price[k], 2),
                          round(abs(diff), 2), reason))
            trades.append({"symbol": k, "side": side, "qty": round(abs(dqty), 6),
                           "price": round(price[k], 2), "value": round(abs(diff), 2)})

    equity = cash + sum(qty[k] * price[k] for k in qty)
    conn.execute("UPDATE crypto_paper SET cash=?, btc_qty=?, eth_qty=?, last_step=? WHERE id=1",
                 (cash, qty["BTC"], qty["ETH"], datetime.now().isoformat(timespec="seconds")))
    conn.execute("INSERT INTO crypto_paper_equity (ts, equity, btc_sig, eth_sig) VALUES (?,?,?,?)",
                 (time.time(), round(equity, 2), signal["BTC"], signal["ETH"]))
    conn.commit()
    conn.close()
    return {"ok": True, "trades": trades, "equity": round(equity, 2)}


def status() -> dict:
    st = _load()
    ps = _prices_and_signals()
    price = {k: ps.get(k, (0, "?", None))[0] for k in ("BTC", "ETH")}
    signal = {k: ps.get(k, (0, "?", None))[1] for k in ("BTC", "ETH")}
    qty = {"BTC": st["btc_qty"], "ETH": st["eth_qty"]}
    equity = st["cash"] + sum(qty[k] * price[k] for k in qty)
    start = st["start_capital"] or STARTING_CAPITAL

    conn = get_connection()
    eq_rows = conn.execute("SELECT equity FROM crypto_paper_equity ORDER BY ts").fetchall()
    trades = [dict(r) for r in conn.execute(
        "SELECT symbol, side, qty, price, value, created_at FROM crypto_paper_trades "
        "ORDER BY id DESC LIMIT 15").fetchall()]
    n_trades = conn.execute("SELECT COUNT(*) FROM crypto_paper_trades").fetchone()[0]
    conn.close()

    # max drawdown from equity history
    mdd = 0.0
    if eq_rows:
        curve = [r["equity"] for r in eq_rows]
        peak = curve[0]
        for v in curve:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)

    return {
        "ok": True,
        "started_at": st["started_at"],
        "last_step": st["last_step"],
        "start_capital": round(start, 2),
        "equity": round(equity, 2),
        "return_pct": round((equity / start - 1) * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "cash": round(st["cash"], 2),
        "positions": {
            "BTC": {"qty": round(qty["BTC"], 6), "value": round(qty["BTC"] * price["BTC"], 2),
                    "signal": signal["BTC"], "price": round(price["BTC"], 2)},
            "ETH": {"qty": round(qty["ETH"], 6), "value": round(qty["ETH"] * price["ETH"], 2),
                    "signal": signal["ETH"], "price": round(price["ETH"], 2)},
        },
        "n_trades": n_trades,
        "recent_trades": trades,
        "note": ("Paper only. Forward-testing the validated crypto trend rule to see if the "
                 "backtested edge holds live before any real money. Extreme-risk strategy."),
    }
