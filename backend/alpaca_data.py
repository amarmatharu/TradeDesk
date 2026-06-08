"""
Alpaca market data layer — replaces yfinance for all price/OHLCV data.
Falls back to yfinance for fundamentals only (P/E, margins, etc.)
"""

import os
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import warnings
warnings.filterwarnings("ignore")

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest, StockLatestQuoteRequest,
    StockSnapshotRequest, StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from ta import trend, momentum, volatility, volume as vol_indicators

# ─── Cache ────────────────────────────────────────────────────────────────────
_cache = {}
CACHE_TTL = 60   # 1 min for prices
FUND_TTL  = 3600 # 1 hour for fundamentals

def _cached(key, fn, ttl=CACHE_TTL):
    now = time.time()
    if key in _cache and now - _cache[key]['ts'] < ttl:
        return _cache[key]['data']
    data = fn()
    _cache[key] = {'data': data, 'ts': now}
    return data


# ─── Client ───────────────────────────────────────────────────────────────────
def get_client() -> Optional[StockHistoricalDataClient]:
    key    = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        return None
    return StockHistoricalDataClient(api_key=key, secret_key=secret)


# ─── Timeframe mapping ────────────────────────────────────────────────────────
def _resolve_timeframe(interval: str) -> TimeFrame:
    mapping = {
        "1m":  TimeFrame(1,  TimeFrameUnit.Minute),
        "5m":  TimeFrame(5,  TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "30m": TimeFrame(30, TimeFrameUnit.Minute),
        "1h":  TimeFrame(1,  TimeFrameUnit.Hour),
        "1d":  TimeFrame.Day,
        "1wk": TimeFrame.Week,
        "1mo": TimeFrame.Month,
    }
    return mapping.get(interval, TimeFrame.Day)

def _period_to_dates(period: str):
    end = datetime.utcnow()
    offsets = {
        "1d": timedelta(days=2),    "5d": timedelta(days=7),
        "1mo": timedelta(days=35),  "3mo": timedelta(days=95),
        "6mo": timedelta(days=185), "1y": timedelta(days=370),
        "2y": timedelta(days=740),  "5y": timedelta(days=1830),
    }
    start = end - offsets.get(period, timedelta(days=95))
    return start, end


# ─── OHLCV ───────────────────────────────────────────────────────────────────
def get_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> list:
    return _cached(f'ohlcv:{ticker}:{period}:{interval}',
                   lambda: _fetch_ohlcv(ticker, period, interval), ttl=60)

def _fetch_ohlcv(ticker: str, period: str, interval: str) -> list:
    client = get_client()
    if not client:
        return _yf_ohlcv(ticker, period, interval)

    try:
        start, end = _period_to_dates(period)
        tf = _resolve_timeframe(interval)
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=tf,
            start=start,
            end=end,
            feed="iex",
        )
        bars = client.get_stock_bars(req)
        df = bars.df

        if df.empty:
            return _yf_ohlcv(ticker, period, interval)

        # Flatten multi-index if present
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level=0)

        records = []
        for ts, row in df.iterrows():
            t = int(pd.Timestamp(ts).timestamp())
            records.append({
                "time":   t,
                "open":   round(float(row["open"]),   4),
                "high":   round(float(row["high"]),   4),
                "low":    round(float(row["low"]),    4),
                "close":  round(float(row["close"]),  4),
                "volume": int(row["volume"]),
            })
        return records
    except Exception as e:
        print(f"[Alpaca] OHLCV error for {ticker}: {e}")
        return _yf_ohlcv(ticker, period, interval)


def _yf_ohlcv(ticker, period, interval):
    """yfinance fallback"""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty:
            return []
        return [{
            "time":   int(idx.timestamp()),
            "open":   round(float(r["Open"]),  4),
            "high":   round(float(r["High"]),  4),
            "low":    round(float(r["Low"]),   4),
            "close":  round(float(r["Close"]), 4),
            "volume": int(r["Volume"]),
        } for idx, r in hist.iterrows()]
    except Exception:
        return []


# ─── Snapshot (current price + daily bar) ────────────────────────────────────
def get_snapshot(ticker: str) -> dict:
    return _cached(f'snap:{ticker}', lambda: _fetch_snapshot(ticker), ttl=30)

def _fetch_snapshot(ticker: str) -> dict:
    client = get_client()
    if not client:
        return {}
    try:
        req = StockSnapshotRequest(symbol_or_symbols=[ticker], feed="iex")
        snaps = client.get_stock_snapshot(req)
        snap = snaps.get(ticker)
        if not snap:
            return {}

        latest = snap.latest_trade
        daily  = snap.daily_bar
        prev   = snap.previous_daily_bar

        price    = float(latest.price) if latest else None
        prev_cls = float(prev.close)   if prev   else None
        chg_pct  = round((price - prev_cls) / prev_cls * 100, 2) if price and prev_cls else None

        return {
            "price":      price,
            "change_pct": chg_pct,
            "open":       float(daily.open)   if daily else None,
            "high":       float(daily.high)   if daily else None,
            "low":        float(daily.low)    if daily else None,
            "volume":     int(daily.volume)   if daily else None,
            "vwap":       float(daily.vwap)   if daily and hasattr(daily,'vwap') else None,
        }
    except Exception as e:
        print(f"[Alpaca] Snapshot error for {ticker}: {e}")
        return {}


# ─── Stock info (price from Alpaca + fundamentals from yfinance) ──────────────
def get_stock_info(ticker: str) -> dict:
    return _cached(f'info:{ticker}', lambda: _fetch_stock_info(ticker), ttl=CACHE_TTL)

def _fetch_stock_info(ticker: str) -> dict:
    result = {
        "ticker":  ticker.upper(),
        "name":    ticker,
        "sector":  "N/A",
        "industry":"N/A",
    }

    # 1. Live price from Alpaca
    snap = get_snapshot(ticker)
    if snap.get("price"):
        result["current_price"] = round(snap["price"], 2)
        result["change_pct"]    = snap.get("change_pct")
        result["day_high"]      = snap.get("high")
        result["day_low"]       = snap.get("low")
        result["volume"]        = snap.get("volume")

    # 2. Fundamentals from yfinance (cached 1hr — called rarely)
    try:
        fund = _cached(f'fund:{ticker}', lambda: _yf_fundamentals(ticker), ttl=FUND_TTL)
        result.update(fund)
        # Override price with Alpaca if we got it
        if snap.get("price"):
            result["current_price"] = round(snap["price"], 2)
    except Exception:
        pass

    if "current_price" not in result:
        result["current_price"] = 0.0

    return result


def _yf_fundamentals(ticker: str) -> dict:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
        return {
            "name":               info.get("longName", ticker),
            "sector":             info.get("sector", "N/A"),
            "industry":           info.get("industry", "N/A"),
            "market_cap":         info.get("marketCap"),
            "pe_ratio":           info.get("trailingPE"),
            "forward_pe":         info.get("forwardPE"),
            "peg_ratio":          info.get("pegRatio"),
            "price_to_book":      info.get("priceToBook"),
            "ev_to_ebitda":       info.get("enterpriseToEbitda"),
            "revenue_growth":     info.get("revenueGrowth"),
            "earnings_growth":    info.get("earningsGrowth"),
            "profit_margins":     info.get("profitMargins"),
            "operating_margins":  info.get("operatingMargins"),
            "return_on_equity":   info.get("returnOnEquity"),
            "debt_to_equity":     info.get("debtToEquity"),
            "free_cashflow":      info.get("freeCashflow"),
            "dividend_yield":     info.get("dividendYield"),
            "beta":               info.get("beta"),
            "52w_high":           info.get("fiftyTwoWeekHigh"),
            "52w_low":            info.get("fiftyTwoWeekLow"),
            "avg_volume":         info.get("averageVolume"),
            "short_ratio":        info.get("shortRatio"),
            "institutional_pct":  info.get("institutionsPercentHeld"),
            "analyst_target":     info.get("targetMeanPrice"),
            "analyst_rating":     info.get("recommendationMean"),
            "num_analysts":       info.get("numberOfAnalystOpinions"),
            "description":        (info.get("longBusinessSummary") or "")[:500],
        }
    except Exception:
        return {}


# ─── Technical indicators ─────────────────────────────────────────────────────
def get_technicals(ticker: str) -> dict:
    return _cached(f'tech:{ticker}', lambda: _calc_technicals(ticker), ttl=CACHE_TTL)

def _calc_technicals(ticker: str) -> dict:
    bars = _fetch_ohlcv(ticker, "6mo", "1d")
    if len(bars) < 20:
        return {"error": "Not enough data"}

    df = pd.DataFrame(bars)
    close = pd.Series(df["close"].values, dtype=float)
    high  = pd.Series(df["high"].values,  dtype=float)
    low   = pd.Series(df["low"].values,   dtype=float)
    vol   = pd.Series(df["volume"].values, dtype=float)

    def safe(series, idx=-1):
        try:
            v = series.iloc[idx]
            return round(float(v), 4) if not np.isnan(v) else None
        except Exception:
            return None

    ema20 = trend.EMAIndicator(close, 20).ema_indicator()
    ema50 = trend.EMAIndicator(close, 50).ema_indicator()
    ema200= trend.EMAIndicator(close, 200).ema_indicator()
    macd  = trend.MACD(close)
    rsi   = momentum.RSIIndicator(close).rsi()
    stoch = momentum.StochasticOscillator(high, low, close)
    bb    = volatility.BollingerBands(close)
    atr   = volatility.AverageTrueRange(high, low, close).average_true_range()
    obv   = vol_indicators.OnBalanceVolumeIndicator(close, vol).on_balance_volume()

    e20, e50, e200 = safe(ema20), safe(ema50), safe(ema200)
    price = float(close.iloc[-1])

    trend_dir = (
        "BULLISH" if e20 and e50 and e200 and e20 > e50 > e200 else
        "BEARISH" if e20 and e50 and e200 and e20 < e50 < e200 else "MIXED"
    )

    rsi_val = safe(rsi)
    rsi_sig = "OVERBOUGHT" if rsi_val and rsi_val > 70 else "OVERSOLD" if rsi_val and rsi_val < 30 else "NEUTRAL"

    macd_val  = safe(macd.macd())
    macd_sig  = safe(macd.macd_signal())
    macd_cross= "BULLISH" if macd_val and macd_sig and macd_val > macd_sig else "BEARISH"

    return {
        "ema20": e20, "ema50": e50, "ema200": e200,
        "trend": trend_dir,
        "rsi": rsi_val, "rsi_signal": rsi_sig,
        "macd": macd_val, "macd_signal": macd_sig,
        "macd_histogram": safe(macd.macd_diff()),
        "macd_cross": macd_cross,
        "stoch_k": safe(stoch.stoch()),
        "stoch_d": safe(stoch.stoch_signal()),
        "bb_upper": safe(bb.bollinger_hband()),
        "bb_mid":   safe(bb.bollinger_mavg()),
        "bb_lower": safe(bb.bollinger_lband()),
        "bb_pct":   safe(bb.bollinger_pband()),
        "atr":      safe(atr),
        "atr_pct":  round(safe(atr) / price * 100, 2) if safe(atr) else None,
        "obv":      safe(obv),
        "support":  round(float(low.tail(20).min()),  2),
        "resistance":round(float(high.tail(20).max()), 2),
        "price_vs_ema20_pct": round((price - e20) / e20 * 100, 2) if e20 else None,
    }


# ─── Market overview ─────────────────────────────────────────────────────────
def get_market_overview() -> dict:
    symbols = {
        "SPY": "S&P 500", "QQQ": "Nasdaq",
        "DIA": "Dow Jones", "IWM": "Russell 2000",
        "GLD": "Gold",     "USO": "Oil",
        "TLT": "Bonds 20Y","VIX": "VIX",
    }
    client = get_client()
    result = {}

    if client:
        try:
            req = StockSnapshotRequest(
                symbol_or_symbols=list(symbols.keys()), feed="iex"
            )
            snaps = client.get_stock_snapshot(req)
            for sym, name in symbols.items():
                snap = snaps.get(sym)
                if not snap:
                    continue
                price    = float(snap.latest_trade.price) if snap.latest_trade else None
                prev_cls = float(snap.previous_daily_bar.close) if snap.previous_daily_bar else None
                chg      = round((price - prev_cls) / prev_cls * 100, 2) if price and prev_cls else None
                result[sym] = {"name": name, "price": round(price, 2) if price else None, "change_pct": chg}
            if result:
                return result
        except Exception as e:
            print(f"[Alpaca] Market overview error: {e}")

    # yfinance fallback
    import yfinance as yf
    for sym, name in symbols.items():
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            result[sym] = {"name": name, "price": round(price, 2),
                           "change_pct": round((price-prev)/prev*100, 2)}
        except Exception:
            pass
    return result


# ─── Test connection ─────────────────────────────────────────────────────────
def test_connection() -> dict:
    client = get_client()
    if not client:
        raise ValueError("Alpaca API key or secret not set")
    try:
        req = StockLatestTradeRequest(symbol_or_symbols=["AAPL"], feed="iex")
        trades = client.get_stock_latest_trade(req)
        price = float(trades["AAPL"].price)
        return {"message": f"✓ Connected — AAPL last trade: ${price:.2f}"}
    except Exception as e:
        raise ValueError(str(e))
