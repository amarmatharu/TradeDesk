"""
WeBull OpenAPI broker adapter.

Implements the same 6-function surface as brokers/alpaca_broker.py so it can be
dropped in behind the broker.py dispatcher (BROKER=webull):

    is_available, get_account, get_positions,
    place_bracket_order, close_position, get_order_activity

⚠️ REAL MONEY. WeBull US OpenAPI has no paper/sandbox — it talks to production
`api.webull.com` and operates on the caller's actual brokerage account. Two
independent guards keep execution off by default:

  1. broker.py only routes here when BROKER=webull.
  2. Even then, order placement is a DRY-RUN (preview_order only) unless
     WEBULL_LIVE_TRADING=true is explicitly set. Read calls (account/positions)
     are always safe and always live.

Auth: App Key + App Secret from the WeBull OpenAPI console. First use requires a
one-time approval in the WeBull phone app (token PENDING -> NORMAL); the token is
then cached under backend/conf/token.txt for ~15 days.
"""

import os
import time
import uuid

# Cached SDK client + resolved account id (per-process).
_client = None
_account_id = None
_init_failed = False


def _read(v, default=0.0):
    """WeBull returns numeric fields as strings — parse defensively."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _body(resp):
    """Unwrap an SDK response object to its parsed JSON body."""
    if resp is None:
        return None
    fn = getattr(resp, "json", None)
    if callable(fn):
        try:
            return fn()
        except Exception:
            return None
    return resp


def _get_client():
    """Lazily build the TradeClient. Never blocks the backend for long: if the
    cached token is missing/expired the SDK would otherwise poll for 5 minutes
    waiting for phone approval, so we cap the check window and fail fast."""
    global _client, _init_failed
    if _client is not None:
        return _client
    if _init_failed:
        return None
    key = os.environ.get("WEBULL_APP_KEY", "").strip()
    sec = os.environ.get("WEBULL_APP_SECRET", "").strip()
    if not key or not sec:
        return None
    try:
        from webull.core.client import ApiClient
        from webull.trade.trade_client import TradeClient
        region = os.environ.get("WEBULL_REGION", "us").strip() or "us"
        # Short token-check window: a valid cached token loads instantly; a
        # PENDING/expired one fails in ~12s instead of hanging for 300s. When
        # this happens, re-run the phone-approval handshake.
        api = ApiClient(key, sec, region,
                        token_check_duration_seconds=12,
                        token_check_interval_seconds=4)
        _client = TradeClient(api)
        return _client
    except Exception as e:
        print(f"[WeBull] client init failed (token may need re-approval in the "
              f"WeBull app): {str(e)[:160]}")
        _init_failed = True
        return None


def _get_account_id():
    """Resolve the trading account id. Prefers WEBULL_ACCOUNT_ID; otherwise the
    first account returned (with a funded/non-zero one preferred)."""
    global _account_id
    if _account_id:
        return _account_id
    override = os.environ.get("WEBULL_ACCOUNT_ID", "").strip()
    if override:
        _account_id = override
        return _account_id
    tc = _get_client()
    if not tc:
        return None
    try:
        accts = _body(tc.account_v2.get_account_list()) or []
        if accts:
            _account_id = accts[0].get("account_id")
        return _account_id
    except Exception as e:
        print(f"[WeBull] get_account_list error: {str(e)[:160]}")
        return None


# ─── Public surface ───────────────────────────────────────────────────────────

def is_available() -> bool:
    return _get_account_id() is not None


def get_account() -> dict:
    tc = _get_client()
    aid = _get_account_id()
    if not tc or not aid:
        return {}
    try:
        b = _body(tc.account_v2.get_account_balance(aid)) or {}
        assets = (b.get("account_currency_assets") or [{}])[0]
        # buying_power key differs by account type (margin vs cash)
        bp = assets.get("day_buying_power") or assets.get("buying_power") or 0
        return {
            "equity": _read(b.get("total_net_liquidation_value")),
            "cash": _read(b.get("total_cash_balance")),
            "buying_power": _read(bp),
            "last_equity": _read(b.get("total_net_liquidation_value")),  # WeBull has no last_equity
            "status": "ACTIVE",
        }
    except Exception as e:
        print(f"[WeBull] get_account error: {str(e)[:160]}")
        return {}


def get_positions() -> list:
    tc = _get_client()
    aid = _get_account_id()
    if not tc or not aid:
        return []
    try:
        rows = _body(tc.account_v2.get_account_position(aid)) or []
        out = []
        for p in rows:
            qty = _read(p.get("quantity"))
            out.append({
                "ticker": p.get("symbol"),
                "qty": qty,
                "side": "LONG" if qty >= 0 else "SHORT",
                "avg_entry": _read(p.get("cost_price")),
                "current_price": _read(p.get("last_price")) or None,
                "market_value": _read(p.get("market_value")) or None,
                "unrealized_pl": _read(p.get("unrealized_profit_loss")),
                "unrealized_plpc": _read(p.get("unrealized_profit_loss_rate")) * 100,
            })
        return out
    except Exception as e:
        print(f"[WeBull] get_positions error: {str(e)[:160]}")
        return []


def _live_trading_enabled() -> bool:
    return os.environ.get("WEBULL_LIVE_TRADING", "").strip().lower() in ("1", "true", "yes", "on")


def _build_order(symbol: str, qty: int, side: str, order_type: str,
                 combo_type: str = "NORMAL",
                 limit_price=None, stop_price=None, client_order_id=None) -> dict:
    """One order in WeBull v3 `new_orders` shape (US equities).

    Field names/values below were confirmed empirically against WeBull's
    preview_order endpoint — do NOT rename casually (each wrong key/value is a
    separate INVALID_PARAMETER rejection):
      instrument_type=EQUITY, market=US, entrust_type=QTY (by share count),
      time_in_force=DAY, support_trading_session=N (regular hours).
    combo_type: NORMAL (standalone) | MASTER (bracket entry) |
                STOP_PROFIT / STOP_LOSS (bracket child legs).
    """
    o = {
        "client_order_id": client_order_id or uuid.uuid4().hex,
        "symbol": symbol,
        "instrument_type": "EQUITY",
        "market": "US",
        "order_type": order_type,          # MARKET | LIMIT | STOP_LOSS | STOP_LOSS_LIMIT
        "quantity": str(abs(int(qty))),
        "side": side,                      # BUY | SELL
        "time_in_force": "DAY",
        "entrust_type": "QTY",
        "combo_type": combo_type,
        "support_trading_session": "N",
    }
    if limit_price is not None:
        o["limit_price"] = str(round(float(limit_price), 2))
    if stop_price is not None:
        o["stop_price"] = str(round(float(stop_price), 2))
    return o


def place_bracket_order(symbol: str, qty: int, direction: str,
                        stop: float, target: float,
                        wait_for_fill: bool = True, timeout: int = 12) -> dict:
    """
    Bracket = MASTER entry (market) + STOP_PROFIT (take-profit) + STOP_LOSS child
    legs, submitted as separate orders in one new_orders list tied by a shared
    client_combo_order_id (WeBull's native bracket structure).

    DRY-RUN by default: runs preview_order and returns {ok, dry_run: True, ...}
    WITHOUT executing. Set WEBULL_LIVE_TRADING=true to actually place the order.
    """
    tc = _get_client()
    aid = _get_account_id()
    if not tc or not aid:
        return {"ok": False, "reason": "WeBull not available (token not verified?)"}

    entry_side = "BUY" if direction == "LONG" else "SELL"
    exit_side = "SELL" if direction == "LONG" else "BUY"

    has_bracket = bool(stop or target)
    combo_id = uuid.uuid4().hex if has_bracket else None
    entry_combo = "MASTER" if has_bracket else "NORMAL"
    new_orders = [_build_order(symbol, qty, entry_side, "MARKET", combo_type=entry_combo)]
    if target:
        new_orders.append(_build_order(symbol, qty, exit_side, "LIMIT",
                                       combo_type="STOP_PROFIT", limit_price=target))
    if stop:
        new_orders.append(_build_order(symbol, qty, exit_side, "STOP_LOSS",
                                       combo_type="STOP_LOSS", stop_price=stop))

    try:
        # Always validate first — cheap and non-executing.
        preview = _body(tc.order_v3.preview_order(aid, new_orders, client_combo_order_id=combo_id))

        if not _live_trading_enabled():
            return {"ok": True, "dry_run": True, "executed": False,
                    "reason": "WEBULL_LIVE_TRADING is off — preview only, no real order placed.",
                    "preview": preview}

        resp = _body(tc.order_v3.place_order(aid, new_orders, client_combo_order_id=combo_id))
        order_id = (resp or {}).get("client_order_id") or (resp or {}).get("order_id") or combo_id
        result = {"ok": True, "dry_run": False, "executed": True,
                  "order_id": order_id, "response": resp}
        if wait_for_fill and order_id:
            result.update(_poll_fill(tc, aid, order_id, timeout))
        return result
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


def _poll_fill(tc, account_id: str, client_order_id: str, timeout: int) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            d = _body(tc.order_v3.get_order_detail(account_id, client_order_id)) or {}
            status = str(d.get("order_status") or d.get("status") or "")
            filled_price = d.get("filled_price") or d.get("avg_fill_price")
            if filled_price:
                return {"fill_price": _read(filled_price),
                        "filled_qty": _read(d.get("filled_quantity")),
                        "status": status, "filled": True}
            if status.upper() in ("CANCELLED", "CANCELED", "REJECTED", "FAILED", "EXPIRED"):
                return {"status": status, "filled": False}
        except Exception:
            pass
        time.sleep(1)
    return {"status": "pending_fill", "filled": False}


def close_position(symbol: str) -> dict:
    """Flatten a position at market. DRY-RUN unless WEBULL_LIVE_TRADING=true."""
    tc = _get_client()
    aid = _get_account_id()
    if not tc or not aid:
        return {"ok": False, "reason": "WeBull not available"}
    try:
        pos = next((p for p in get_positions() if p["ticker"] == symbol), None)
        if not pos or not pos["qty"]:
            return {"ok": False, "reason": f"No open position in {symbol}"}
        qty = abs(int(pos["qty"]))
        exit_side = "SELL" if pos["qty"] > 0 else "BUY"
        new_orders = [_build_order(symbol, qty, exit_side, "MARKET")]

        preview = _body(tc.order_v3.preview_order(aid, new_orders))
        if not _live_trading_enabled():
            return {"ok": True, "dry_run": True, "executed": False,
                    "reason": "WEBULL_LIVE_TRADING is off — preview only.",
                    "preview": preview}
        resp = _body(tc.order_v3.place_order(aid, new_orders))
        order_id = (resp or {}).get("client_order_id") or (resp or {}).get("order_id")
        return {"ok": True, "dry_run": False, "executed": True, "order_id": order_id, "response": resp}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


def get_order_activity(limit: int = 50) -> list:
    """Recent filled orders — best-effort mapping of get_order_history."""
    tc = _get_client()
    aid = _get_account_id()
    if not tc or not aid:
        return []
    try:
        rows = _body(tc.order_v3.get_order_history(aid, page_size=limit)) or []
        if isinstance(rows, dict):
            rows = rows.get("orders") or rows.get("data") or []
        out = []
        for o in rows:
            fp = o.get("filled_price") or o.get("avg_fill_price")
            if fp:
                out.append({
                    "symbol": o.get("symbol"),
                    "side": str(o.get("side", "")),
                    "qty": _read(o.get("filled_quantity")),
                    "fill_price": _read(fp),
                    "filled_at": str(o.get("filled_time") or o.get("updated_time") or ""),
                    "order_type": str(o.get("order_type", "")),
                })
        return out
    except Exception as e:
        print(f"[WeBull] get_order_activity error: {str(e)[:160]}")
        return []
