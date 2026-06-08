"""
Universe filter — qualifies tickers for the Insider Edge strategy.

The retail edge is in under-covered small/micro caps where institutions can't go.
But small caps carry real risks: illiquidity, wide spreads, pump-and-dumps.
This module screens FOR the edge while screening OUT the traps.
"""

from alpaca_data import get_snapshot, get_stock_info

# Strategy B target band
MIN_CAP = 50_000_000        # $50M — below this is too risky/illiquid
MAX_CAP = 2_000_000_000     # $2B — above this institutions already cover it
MIN_PRICE = 2.0             # avoid sub-$2 penny stocks (pump/fraud risk)
MIN_AVG_VOLUME = 100_000    # need enough liquidity to enter/exit


def qualify_smallcap(ticker: str) -> dict:
    """
    Returns { qualified: bool, reason, cap, price, avg_volume }.
    A ticker qualifies for Insider Edge if it's a liquid-enough small/micro cap.
    """
    ticker = ticker.upper()
    snap = get_snapshot(ticker)
    price = snap.get("price")
    if not price:
        return {"qualified": False, "reason": "no price", "ticker": ticker}

    if price < MIN_PRICE:
        return {"qualified": False, "reason": f"price ${price:.2f} < ${MIN_PRICE} (penny risk)",
                "ticker": ticker, "price": price}

    # Fundamentals (cap, volume) — best-effort from yfinance via get_stock_info
    info = get_stock_info(ticker)
    cap = info.get("market_cap")
    avg_vol = info.get("avg_volume") or snap.get("volume")

    if cap:
        if cap < MIN_CAP:
            return {"qualified": False, "reason": f"cap ${cap/1e6:.0f}M < ${MIN_CAP/1e6:.0f}M (too small)",
                    "ticker": ticker, "cap": cap, "price": price}
        if cap > MAX_CAP:
            return {"qualified": False, "reason": f"cap ${cap/1e9:.1f}B > ${MAX_CAP/1e9:.0f}B (too big — institutions cover it)",
                    "ticker": ticker, "cap": cap, "price": price}

    if avg_vol and avg_vol < MIN_AVG_VOLUME:
        return {"qualified": False, "reason": f"avg vol {avg_vol:,} < {MIN_AVG_VOLUME:,} (illiquid)",
                "ticker": ticker, "avg_volume": avg_vol, "price": price}

    return {
        "qualified": True,
        "reason": "small-cap, liquid enough, not a penny stock",
        "ticker": ticker,
        "cap": cap,
        "price": price,
        "avg_volume": avg_vol,
        "coverage": "low" if (cap and cap < 1e9) else "moderate",
    }
