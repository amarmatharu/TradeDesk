import yfinance as yf
import pandas as pd
import numpy as np
from ta import trend, momentum, volatility, volume as vol_indicators
from datetime import datetime, timedelta
import warnings
import time
import functools
from mock_data import get_demo_stock_info, get_demo_ohlcv, get_demo_news, get_demo_technicals
warnings.filterwarnings("ignore")

# Simple in-memory cache to avoid hammering Yahoo Finance
_cache = {}
CACHE_TTL = 300  # 5 minutes

def _cached(key, fn, ttl=CACHE_TTL):
    now = time.time()
    if key in _cache and now - _cache[key]['ts'] < ttl:
        return _cache[key]['data']
    data = fn()
    _cache[key] = {'data': data, 'ts': now}
    return data


def get_stock_info(ticker: str) -> dict:
    return _cached(f'info:{ticker}', lambda: _fetch_stock_info_with_fallback(ticker))

def _fetch_stock_info_with_fallback(ticker: str) -> dict:
    result = _fetch_stock_info(ticker)
    if result.get("error") or not result.get("current_price"):
        return get_demo_stock_info(ticker)
    return result

def _fetch_stock_info(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        current_price = float(hist["Close"].iloc[-1]) if not hist.empty else 0
        info = t.fast_info
        basic = {
            "ticker": ticker.upper(),
            "name": getattr(info, 'name', ticker) or ticker,
            "current_price": round(current_price, 2),
            "market_cap": getattr(info, 'market_cap', None),
            "52w_high": getattr(info, 'fifty_two_week_high', None),
            "52w_low": getattr(info, 'fifty_two_week_low', None),
            "avg_volume": getattr(info, 'three_month_average_volume', None),
        }
        # Try full info (may fail due to rate limits)
        try:
            full = t.info
            basic.update({
                "name": full.get("longName", basic["name"]),
                "sector": full.get("sector", "N/A"),
                "industry": full.get("industry", "N/A"),
                "pe_ratio": full.get("trailingPE"),
                "forward_pe": full.get("forwardPE"),
                "peg_ratio": full.get("pegRatio"),
                "price_to_book": full.get("priceToBook"),
                "ev_to_ebitda": full.get("enterpriseToEbitda"),
                "revenue_growth": full.get("revenueGrowth"),
                "earnings_growth": full.get("earningsGrowth"),
                "profit_margins": full.get("profitMargins"),
                "operating_margins": full.get("operatingMargins"),
                "return_on_equity": full.get("returnOnEquity"),
                "debt_to_equity": full.get("debtToEquity"),
                "free_cashflow": full.get("freeCashflow"),
                "dividend_yield": full.get("dividendYield"),
                "beta": full.get("beta"),
                "shares_short": full.get("sharesShort"),
                "short_ratio": full.get("shortRatio"),
                "institutional_pct": full.get("institutionsPercentHeld"),
                "analyst_target": full.get("targetMeanPrice"),
                "analyst_rating": full.get("recommendationMean"),
                "num_analysts": full.get("numberOfAnalystOpinions"),
                "description": (full.get("longBusinessSummary") or "")[:500],
            })
        except Exception:
            basic.setdefault("sector", "N/A")
            basic.setdefault("industry", "N/A")
        return basic
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> list:
    return _cached(f'ohlcv:{ticker}:{period}:{interval}', lambda: _fetch_ohlcv_with_fallback(ticker, period, interval), ttl=60)

def _fetch_ohlcv_with_fallback(ticker: str, period: str, interval: str) -> list:
    result = _fetch_ohlcv(ticker, period, interval)
    if not result:
        return get_demo_ohlcv(ticker, period, interval)
    return result

def _fetch_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> list:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, interval=interval)
        if hist.empty:
            return []

        records = []
        is_daily = interval in ("1d", "1wk", "1mo")
        for idx, row in hist.iterrows():
            if is_daily:
                time_val = f"{idx.year:04d}-{idx.month:02d}-{idx.day:02d}"
            else:
                time_val = int(idx.timestamp())
            records.append({
                "time": time_val,
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return records
    except Exception as e:
        return []


def get_technicals(ticker: str) -> dict:
    return _cached(f'tech:{ticker}', lambda: _fetch_technicals_with_fallback(ticker))

def _fetch_technicals_with_fallback(ticker: str) -> dict:
    result = _compute_technicals(ticker)
    if not result or result.get("error"):
        return get_demo_technicals(ticker)
    return result

def _compute_technicals(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="6mo")
        if hist.empty or len(hist) < 20:
            return {}

        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        vol = hist["Volume"]

        # Trend
        ema20 = trend.EMAIndicator(close, window=20).ema_indicator()
        ema50 = trend.EMAIndicator(close, window=50).ema_indicator()
        ema200 = trend.EMAIndicator(close, window=200).ema_indicator()
        macd_obj = trend.MACD(close)
        macd_line = macd_obj.macd()
        macd_signal = macd_obj.macd_signal()
        macd_hist = macd_obj.macd_diff()

        # Momentum
        rsi = momentum.RSIIndicator(close).rsi()
        stoch = momentum.StochasticOscillator(high, low, close)

        # Volatility
        bb = volatility.BollingerBands(close)
        atr = volatility.AverageTrueRange(high, low, close).average_true_range()

        # Volume
        obv = vol_indicators.OnBalanceVolumeIndicator(close, vol).on_balance_volume()

        current_price = float(close.iloc[-1])

        def safe_float(series, idx=-1):
            try:
                v = series.iloc[idx]
                return round(float(v), 4) if not np.isnan(v) else None
            except Exception:
                return None

        # Support / resistance (simple: last 20 session highs/lows)
        recent_high = float(high.tail(20).max())
        recent_low = float(low.tail(20).min())

        # Trend direction
        e20 = safe_float(ema20)
        e50 = safe_float(ema50)
        e200 = safe_float(ema200)
        trend_dir = "BULLISH" if (e20 and e50 and e200 and e20 > e50 > e200) else \
                    "BEARISH" if (e20 and e50 and e200 and e20 < e50 < e200) else "MIXED"

        rsi_val = safe_float(rsi)
        rsi_signal = "OVERBOUGHT" if rsi_val and rsi_val > 70 else \
                     "OVERSOLD" if rsi_val and rsi_val < 30 else "NEUTRAL"

        macd_val = safe_float(macd_line)
        macd_sig_val = safe_float(macd_signal)
        macd_cross = "BULLISH" if (macd_val and macd_sig_val and macd_val > macd_sig_val) else "BEARISH"

        return {
            "ema20": e20,
            "ema50": e50,
            "ema200": e200,
            "trend": trend_dir,
            "rsi": rsi_val,
            "rsi_signal": rsi_signal,
            "macd": macd_val,
            "macd_signal": macd_sig_val,
            "macd_histogram": safe_float(macd_hist),
            "macd_cross": macd_cross,
            "stoch_k": safe_float(stoch.stoch()),
            "stoch_d": safe_float(stoch.stoch_signal()),
            "bb_upper": safe_float(bb.bollinger_hband()),
            "bb_mid": safe_float(bb.bollinger_mavg()),
            "bb_lower": safe_float(bb.bollinger_lband()),
            "bb_pct": safe_float(bb.bollinger_pband()),
            "atr": safe_float(atr),
            "atr_pct": round(safe_float(atr) / current_price * 100, 2) if safe_float(atr) else None,
            "obv": safe_float(obv),
            "resistance": round(recent_high, 2),
            "support": round(recent_low, 2),
            "price_vs_ema20_pct": round((current_price - e20) / e20 * 100, 2) if e20 else None,
            "price_vs_52w_high_pct": None,
        }
    except Exception as e:
        return {"error": str(e)}


def get_news(ticker: str, limit: int = 10) -> list:
    return _cached(f'news:{ticker}', lambda: _fetch_news_with_fallback(ticker, limit), ttl=180)

def _fetch_news_with_fallback(ticker: str, limit: int) -> list:
    result = _fetch_news(ticker, limit)
    if not result:
        return get_demo_news(ticker)
    return result

def _fetch_news(ticker: str, limit: int = 10) -> list:
    try:
        t = yf.Ticker(ticker)
        news = t.news
        results = []
        for item in (news or [])[:limit]:
            content = item.get("content", {})
            results.append({
                "title": content.get("title", ""),
                "summary": content.get("summary", ""),
                "url": content.get("canonicalUrl", {}).get("url", ""),
                "source": content.get("provider", {}).get("displayName", ""),
                "published": content.get("pubDate", ""),
                "thumbnail": (content.get("thumbnail") or {}).get("resolutions", [{}])[0].get("url", "") if content.get("thumbnail") else "",
            })
        return results
    except Exception as e:
        return []


DEMO_MARKET = {
    "SPY": {"name": "S&P 500", "price": 7609.78, "change_pct": 0.26},
    "QQQ": {"name": "Nasdaq", "price": 533.42, "change_pct": 0.61},
    "DIA": {"name": "Dow Jones", "price": 427.85, "change_pct": -0.12},
    "IWM": {"name": "Russell 2000", "price": 208.14, "change_pct": 0.34},
    "GLD": {"name": "Gold", "price": 312.50, "change_pct": 0.18},
    "USO": {"name": "Oil", "price": 74.22, "change_pct": 1.89},
    "TLT": {"name": "Bonds (20Y)", "price": 88.15, "change_pct": -0.22},
    "VIX": {"name": "VIX", "price": 13.82, "change_pct": -3.4},
}

def get_market_overview() -> dict:
    tickers = {"SPY": "S&P 500", "QQQ": "Nasdaq", "DIA": "Dow Jones", "IWM": "Russell 2000",
               "GLD": "Gold", "USO": "Oil", "TLT": "Bonds (20Y)", "VIX": "VIX"}
    result = {}
    for sym, name in tickers.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if hist.empty:
                result[sym] = DEMO_MARKET.get(sym, {"name": name, "price": 0, "change_pct": 0})
                continue
            current = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
            chg = round((current - prev) / prev * 100, 2)
            result[sym] = {"name": name, "price": round(current, 2), "change_pct": chg}
        except Exception:
            result[sym] = DEMO_MARKET.get(sym, {"name": name, "price": 0, "change_pct": 0})
    return result


def calculate_position_size(portfolio: float, risk_pct: float, entry: float, stop: float) -> dict:
    risk_dollars = portfolio * (risk_pct / 100)
    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        return {"shares": 0, "risk_dollars": 0, "position_value": 0}
    shares = int(risk_dollars / risk_per_share)
    position_value = shares * entry
    position_pct = (position_value / portfolio) * 100
    return {
        "shares": shares,
        "risk_dollars": round(risk_dollars, 2),
        "risk_per_share": round(risk_per_share, 2),
        "position_value": round(position_value, 2),
        "position_pct_of_portfolio": round(position_pct, 2),
    }
