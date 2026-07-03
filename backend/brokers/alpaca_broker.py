"""
Broker — real Alpaca paper-trading execution.

Replaces the fantasy local-fill simulation with actual paper orders:
- Real fills (Alpaca's simulator models spread/slippage)
- HARD stops + take-profits via bracket orders (live at the broker, not soft timer checks)
- Real position + account state

Bracket order = entry + OCO (stop-loss leg + take-profit leg). When either leg
fills, the other cancels automatically. This means stops are enforced server-side
even if our backend is down.

Falls back gracefully if Alpaca trading isn't available.
"""

import os
import time
import socket
from typing import Optional

# Hard cap on ANY network read — prevents the "read timeout=None" hang that
# froze the whole system. No socket call can block longer than this.
socket.setdefaulttimeout(20)

_client = None


def get_trading_client():
    global _client
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    sec = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key or not sec:
        return None
    if _client is None:
        try:
            from alpaca.trading.client import TradingClient
            _client = TradingClient(key, sec, paper=True)
        except Exception as e:
            print(f"[Broker] Client init error: {e}")
            return None
    return _client


def is_available() -> bool:
    return get_trading_client() is not None


def get_account() -> dict:
    tc = get_trading_client()
    if not tc:
        return {}
    try:
        a = tc.get_account()
        return {
            "equity": float(a.equity),
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "last_equity": float(a.last_equity),
            "status": str(a.status),
        }
    except Exception as e:
        print(f"[Broker] get_account error: {e}")
        return {}


def get_positions() -> list:
    tc = get_trading_client()
    if not tc:
        return []
    try:
        positions = tc.get_all_positions()
        out = []
        for p in positions:
            out.append({
                "ticker": p.symbol,
                "qty": float(p.qty),
                "side": "LONG" if float(p.qty) > 0 else "SHORT",
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.market_value) if p.market_value else None,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl else 0,
                "unrealized_plpc": float(p.unrealized_plpc) * 100 if p.unrealized_plpc else 0,
            })
        return out
    except Exception as e:
        print(f"[Broker] get_positions error: {e}")
        return []


def place_bracket_order(symbol: str, qty: int, direction: str,
                        stop: float, target: float,
                        wait_for_fill: bool = True, timeout: int = 12) -> dict:
    """
    Place a bracket market order: entry + hard stop + take-profit.
    Returns { ok, order_id, fill_price, status, ... } or { ok: False, reason }.
    """
    tc = get_trading_client()
    if not tc:
        return {"ok": False, "reason": "Broker not available"}

    try:
        from alpaca.trading.requests import (
            MarketOrderRequest, StopLossRequest, TakeProfitRequest
        )
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL

        # Round bracket legs to 2dp; ensure they're on the correct side of entry
        req_kwargs = dict(
            symbol=symbol,
            qty=abs(int(qty)),
            side=side,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
        )
        if stop:
            req_kwargs["stop_loss"] = StopLossRequest(stop_price=round(float(stop), 2))
        if target:
            req_kwargs["take_profit"] = TakeProfitRequest(limit_price=round(float(target), 2))

        order = tc.submit_order(MarketOrderRequest(**req_kwargs))
        order_id = str(order.id)

        result = {"ok": True, "order_id": order_id, "status": str(order.status)}

        if wait_for_fill:
            fill = _poll_fill(tc, order_id, timeout)
            result.update(fill)

        return result
    except Exception as e:
        msg = str(e)
        # Bracket orders rejected outside market hours — fall back to plain market order
        if "market" in msg.lower() or "bracket" in msg.lower() or "tradable" in msg.lower():
            return _place_simple_order(symbol, qty, direction, wait_for_fill, timeout, note=msg[:120])
        return {"ok": False, "reason": msg[:200]}


def _place_simple_order(symbol, qty, direction, wait_for_fill, timeout, note=""):
    """Fallback: plain market order (no bracket) — used when brackets are rejected."""
    tc = get_trading_client()
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
        order = tc.submit_order(MarketOrderRequest(
            symbol=symbol, qty=abs(int(qty)), side=side, time_in_force=TimeInForce.DAY
        ))
        result = {"ok": True, "order_id": str(order.id), "status": str(order.status),
                  "bracket": False, "note": f"Simple order (bracket fallback): {note}"}
        if wait_for_fill:
            result.update(_poll_fill(tc, str(order.id), timeout))
        return result
    except Exception as e:
        return {"ok": False, "reason": f"Simple order failed: {str(e)[:160]}"}


def _poll_fill(tc, order_id: str, timeout: int) -> dict:
    """Poll until order fills or timeout. Returns fill_price + status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            o = tc.get_order_by_id(order_id)
            status = str(o.status)
            if o.filled_avg_price:
                return {
                    "fill_price": float(o.filled_avg_price),
                    "filled_qty": float(o.filled_qty or 0),
                    "status": status,
                    "filled": True,
                }
            if status in ("canceled", "rejected", "expired"):
                return {"status": status, "filled": False}
        except Exception:
            pass
        time.sleep(1)
    return {"status": "pending_fill", "filled": False}


def close_position(symbol: str) -> dict:
    """Flatten a position at market (cancels any open bracket legs first)."""
    tc = get_trading_client()
    if not tc:
        return {"ok": False, "reason": "Broker not available"}
    try:
        # Cancel any open orders for this symbol (bracket legs)
        try:
            for o in tc.get_orders():
                if o.symbol == symbol and str(o.status) in ("new", "accepted", "held", "open"):
                    tc.cancel_order_by_id(o.id)
        except Exception:
            pass
        resp = tc.close_position(symbol)
        order_id = str(resp.id) if hasattr(resp, "id") else None
        fill = _poll_fill(tc, order_id, 10) if order_id else {}
        return {"ok": True, "order_id": order_id, **fill}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


def get_order_activity(limit: int = 50) -> list:
    """Recent closed/filled orders — used to detect broker-side stop/target fills."""
    tc = get_trading_client()
    if not tc:
        return []
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=limit)
        orders = tc.get_orders(req)
        out = []
        for o in orders:
            if o.filled_avg_price:
                out.append({
                    "symbol": o.symbol,
                    "side": str(o.side),
                    "qty": float(o.filled_qty or 0),
                    "fill_price": float(o.filled_avg_price),
                    "filled_at": str(o.filled_at) if o.filled_at else "",
                    "order_type": str(o.type),
                })
        return out
    except Exception as e:
        print(f"[Broker] get_order_activity error: {e}")
        return []
