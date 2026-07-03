"""
Broker — switchable execution façade.

Historically this module WAS the Alpaca paper-trading client. It is now a thin
dispatcher that forwards to whichever broker backend is selected by the `BROKER`
env var:

    BROKER=alpaca   -> brokers/alpaca_broker.py   (default; paper trading)
    BROKER=webull   -> brokers/webull_broker.py   (WeBull OpenAPI; real account)

Every call site (`import broker; broker.place_bracket_order(...)`) keeps working
unchanged — the public surface is identical to the old Alpaca-only module:
    is_available, get_account, get_positions,
    place_bracket_order, close_position, get_order_activity

Selection is resolved on every call (cheap) so flipping BROKER in .env and
restarting the backend is all it takes to switch — no code change.
"""

import os
import importlib

_MODULES = {
    "alpaca": "brokers.alpaca_broker",
    "webull": "brokers.webull_broker",
}

_cache = {}


def active_broker_name() -> str:
    """Currently selected broker id (defaults to alpaca)."""
    name = os.environ.get("BROKER", "alpaca").strip().lower()
    return name if name in _MODULES else "alpaca"


def _active():
    name = active_broker_name()
    mod = _cache.get(name)
    if mod is None:
        mod = importlib.import_module(_MODULES[name])
        _cache[name] = mod
    return mod


def broker_env() -> str:
    """Environment label for the active broker (e.g. sandbox/live/paper)."""
    name = active_broker_name()
    if name == "webull":
        return os.environ.get("WEBULL_ENV", "sandbox").strip().lower()
    return "paper"  # Alpaca is always paper here


# ─── Public surface — forwards to the active broker ───────────────────────────

def is_available() -> bool:
    return _active().is_available()


def get_account() -> dict:
    return _active().get_account()


def get_positions() -> list:
    return _active().get_positions()


def place_bracket_order(symbol: str, qty: int, direction: str,
                        stop: float, target: float,
                        wait_for_fill: bool = True, timeout: int = 12) -> dict:
    return _active().place_bracket_order(
        symbol, qty, direction, stop, target,
        wait_for_fill=wait_for_fill, timeout=timeout,
    )


def close_position(symbol: str) -> dict:
    return _active().close_position(symbol)


def get_order_activity(limit: int = 50) -> list:
    return _active().get_order_activity(limit=limit)
