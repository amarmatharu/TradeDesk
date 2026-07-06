"""
Crypto paper-trading engine — forward-test the validated trend strategy.

Runs the multi-coin trend rule (hold each coin above its 50-day average, else
cash) on a PAPER portfolio, 24/7, recording every trade + equity so we build a
real forward track record. Promotion-gate discipline: prove it holds live before
any real money.

Basket = the coins where the edge tested positive (crypto_strategy.ASSETS). Each
coin's target = 1/N of equity when HOLD, 0 when CASH (so max ~10% per coin, fully
invested only if every coin is in trend). Rebalances when a target drifts >2% of
equity. Flexible positions schema — works for any basket size. Persists in SQLite.
"""

import time
from datetime import datetime
from database import get_connection
import crypto_strategy

STARTING_CAPITAL = 10000.0
REBAL_THRESHOLD = 0.02


def ensure_tables():
    conn = get_connection()
    # migrate off the old 2-coin schema (btc_qty/eth_qty columns) if present
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(crypto_paper)").fetchall()]
        eq_cols = [r[1] for r in conn.execute("PRAGMA table_info(crypto_paper_equity)").fetchall()]
        if "btc_qty" in cols or "btc_sig" in eq_cols:
            conn.execute("DROP TABLE IF EXISTS crypto_paper")
            conn.execute("DROP TABLE IF EXISTS crypto_paper_positions")
            conn.execute("DROP TABLE IF EXISTS crypto_paper_equity")
            conn.execute("DROP TABLE IF EXISTS crypto_paper_trades")
            conn.commit()
    except Exception:
        pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS crypto_paper (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL, start_capital REAL, started_at TEXT, last_step TEXT
        );
        CREATE TABLE IF NOT EXISTS crypto_paper_positions (
            symbol TEXT PRIMARY KEY, qty REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS crypto_paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, symbol TEXT, side TEXT,
            qty REAL, price REAL, value REAL, reason TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS crypto_paper_equity (
            ts REAL, equity REAL, n_holding INTEGER, created_at TEXT DEFAULT (datetime('now'))
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
    pos = {r["symbol"]: r["qty"] for r in conn.execute("SELECT symbol, qty FROM crypto_paper_positions").fetchall()}
    conn.close()
    return dict(row), pos


def _market():
    sig = crypto_strategy.current_signal()
    price, signal = {}, {}
    for a in sig.get("assets", []):
        if a.get("ok"):
            price[a["symbol"]] = a["price"]
            signal[a["symbol"]] = a["signal"]
    return price, signal


def step() -> dict:
    price, signal = _market()
    if not price:
        return {"ok": False, "reason": "no crypto prices"}
    st, pos = _load()
    cash = st["cash"]
    symbols = list(price.keys())
    n = len(crypto_strategy.ASSETS) or len(symbols)
    for s in symbols:
        pos.setdefault(s, 0.0)

    equity = cash + sum(pos.get(s, 0) * price[s] for s in symbols)
    conn = get_connection()
    trades = []
    for s in symbols:
        target_val = (equity / n) if signal.get(s) == "HOLD" else 0.0
        cur_val = pos.get(s, 0) * price[s]
        diff = target_val - cur_val
        if abs(diff) > equity * REBAL_THRESHOLD and price[s] > 0:
            dqty = diff / price[s]
            side = "BUY" if dqty > 0 else "SELL"
            cash -= dqty * price[s]
            pos[s] = pos.get(s, 0) + dqty
            conn.execute("INSERT INTO crypto_paper_trades (ts,symbol,side,qty,price,value,reason) VALUES (?,?,?,?,?,?,?)",
                         (time.time(), s, side, round(abs(dqty), 8), round(price[s], 4),
                          round(abs(diff), 2), f"signal {signal.get(s)}"))
            conn.execute("INSERT INTO crypto_paper_positions (symbol, qty) VALUES (?,?) "
                         "ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty", (s, pos[s]))
            trades.append({"symbol": s, "side": side, "value": round(abs(diff), 2)})

    equity = cash + sum(pos.get(s, 0) * price[s] for s in symbols)
    n_hold = sum(1 for s in symbols if signal.get(s) == "HOLD")
    conn.execute("UPDATE crypto_paper SET cash=?, last_step=? WHERE id=1",
                 (cash, datetime.now().isoformat(timespec="seconds")))
    conn.execute("INSERT INTO crypto_paper_equity (ts, equity, n_holding) VALUES (?,?,?)",
                 (time.time(), round(equity, 2), n_hold))
    conn.commit()
    conn.close()
    return {"ok": True, "trades": trades, "equity": round(equity, 2), "holding": n_hold}


def status() -> dict:
    st, pos = _load()
    price, signal = _market()
    symbols = [lbl for _, lbl, _ in crypto_strategy.ASSETS]
    equity = st["cash"] + sum(pos.get(s, 0) * price.get(s, 0) for s in symbols)
    start = st["start_capital"] or STARTING_CAPITAL

    conn = get_connection()
    eq = [r["equity"] for r in conn.execute("SELECT equity FROM crypto_paper_equity ORDER BY ts").fetchall()]
    trades = [dict(r) for r in conn.execute(
        "SELECT symbol, side, qty, price, value, created_at FROM crypto_paper_trades ORDER BY id DESC LIMIT 15").fetchall()]
    n_trades = conn.execute("SELECT COUNT(*) FROM crypto_paper_trades").fetchone()[0]
    conn.close()

    mdd = 0.0
    if eq:
        peak = eq[0]
        for v in eq:
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)

    positions = {}
    for s in symbols:
        val = pos.get(s, 0) * price.get(s, 0)
        if val > 1 or signal.get(s):
            positions[s] = {"value": round(val, 2), "signal": signal.get(s, "?"),
                            "price": round(price.get(s, 0), 2)}

    return {
        "ok": True, "started_at": st["started_at"], "last_step": st["last_step"],
        "start_capital": round(start, 2), "equity": round(equity, 2),
        "return_pct": round((equity / start - 1) * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2), "cash": round(st["cash"], 2),
        "invested_pct": round((equity - st["cash"]) / equity * 100, 1) if equity else 0,
        "positions": positions, "n_trades": n_trades, "recent_trades": trades,
        "note": ("Paper only. Forward-testing the multi-coin crypto trend rule before any real "
                 "money. Extreme-risk strategy; equal-weight the coins currently in trend."),
    }
