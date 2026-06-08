"""Demo data used when Yahoo Finance is unreachable (rate-limited in dev)."""

STOCKS = {
    "NVDA": {"name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors",
             "current_price": 222.82, "market_cap": 5440000000000, "pe_ratio": 47.2, "forward_pe": 32.1,
             "peg_ratio": 1.8, "revenue_growth": 0.78, "earnings_growth": 1.47, "profit_margins": 0.558,
             "return_on_equity": 1.25, "debt_to_equity": 17.0, "beta": 1.71, "52w_high": 232.28, "52w_low": 86.22,
             "analyst_target": 298.32, "analyst_rating": 1.4, "short_ratio": 1.2,
             "institutional_pct": 0.67, "description": "NVIDIA designs graphics processing units for gaming and professional markets, as well as system-on-chip units for mobile computing and automotive markets. The company is the dominant supplier of AI training chips."},
    "AAPL": {"name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics",
             "current_price": 201.50, "market_cap": 3050000000000, "pe_ratio": 32.4, "forward_pe": 28.9,
             "revenue_growth": 0.04, "earnings_growth": 0.08, "profit_margins": 0.264,
             "return_on_equity": 1.47, "beta": 1.25, "52w_high": 237.23, "52w_low": 164.08,
             "analyst_target": 230.0, "analyst_rating": 1.9, "description": "Apple designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide."},
    "MSFT": {"name": "Microsoft Corporation", "sector": "Technology", "industry": "Software—Infrastructure",
             "current_price": 452.10, "market_cap": 3360000000000, "pe_ratio": 37.2, "forward_pe": 30.8,
             "revenue_growth": 0.17, "earnings_growth": 0.22, "profit_margins": 0.357,
             "return_on_equity": 0.36, "beta": 0.90, "52w_high": 468.35, "52w_low": 344.79,
             "analyst_target": 490.0, "analyst_rating": 1.3, "description": "Microsoft develops and supports software, services, devices, and solutions worldwide. Key products include Azure cloud, Office 365, and Windows."},
    "CAT": {"name": "Caterpillar Inc.", "sector": "Industrials", "industry": "Farm & Heavy Construction Machinery",
            "current_price": 907.25, "market_cap": 152000000000, "pe_ratio": 18.4, "forward_pe": 16.2,
            "revenue_growth": 0.03, "earnings_growth": 0.12, "profit_margins": 0.162,
            "return_on_equity": 0.72, "beta": 1.02, "52w_high": 912.14, "52w_low": 315.22,
            "analyst_target": 960.0, "analyst_rating": 2.1, "description": "Caterpillar manufactures and sells construction, mining, and other heavy equipment worldwide. Major beneficiary of infrastructure spending and data center buildout."},
    "XOM": {"name": "Exxon Mobil Corporation", "sector": "Energy", "industry": "Oil & Gas Integrated",
            "current_price": 108.45, "market_cap": 465000000000, "pe_ratio": 13.8, "forward_pe": 12.4,
            "revenue_growth": 0.02, "earnings_growth": -0.05, "profit_margins": 0.088,
            "return_on_equity": 0.147, "beta": 0.84, "52w_high": 130.09, "52w_low": 95.77,
            "analyst_target": 120.0, "analyst_rating": 2.3, "description": "Exxon Mobil is the world's largest publicly traded oil and gas company."},
    "LLY": {"name": "Eli Lilly and Company", "sector": "Healthcare", "industry": "Drug Manufacturers",
            "current_price": 812.40, "market_cap": 770000000000, "pe_ratio": 62.1, "forward_pe": 38.4,
            "revenue_growth": 0.45, "earnings_growth": 0.98, "profit_margins": 0.228,
            "return_on_equity": 1.62, "beta": 0.40, "52w_high": 972.53, "52w_low": 681.29,
            "analyst_target": 1050.0, "analyst_rating": 1.5, "description": "Eli Lilly manufactures pharmaceutical products. Leading producer of GLP-1 obesity and diabetes drugs Mounjaro and Zepbound with explosive demand growth."},
}

def get_demo_stock_info(ticker: str) -> dict:
    data = STOCKS.get(ticker.upper(), {
        "name": ticker, "sector": "N/A", "industry": "N/A",
        "current_price": 100.0, "beta": 1.0,
    })
    return {"ticker": ticker.upper(), **data}


import random
import math
from datetime import datetime, timedelta

def get_demo_ohlcv(ticker: str, period: str = "3mo", interval: str = "1d") -> list:
    info = STOCKS.get(ticker.upper(), {})
    base = info.get("current_price", 100.0)
    volatility = 0.015

    days_map = {"1d": 1, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 132, "1y": 252}
    n_bars = days_map.get(period, 66)

    random.seed(hash(ticker) % 1000)
    records = []
    price = base * 0.85
    now = datetime.now()

    for i in range(n_bars):
        dt = now - timedelta(days=n_bars - i)
        # Normalize to midnight UTC for lightweight-charts daily format
        midnight_ts = int(datetime(dt.year, dt.month, dt.day).timestamp())
        change = random.gauss(0.0003, volatility)
        open_p = price
        close_p = price * (1 + change)
        high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, volatility / 2)))
        low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, volatility / 2)))
        vol = int(random.uniform(20_000_000, 80_000_000))

        records.append({
            "time": f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}",
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": vol,
        })
        price = close_p

    return records


def get_demo_news(ticker: str) -> list:
    templates = {
        "NVDA": [
            {"title": "NVIDIA Launches New Blackwell Ultra Chip for AI Workloads", "summary": "NVIDIA unveils next-gen GPU architecture targeting enterprise AI training with 2x performance gains over previous generation.", "source": "Reuters"},
            {"title": "Analyst Raises NVDA Price Target to $320 on AI Demand", "summary": "Cantor Fitzgerald reiterates NVDA as top pick citing accelerating hyperscaler orders.", "source": "Bloomberg"},
            {"title": "NVIDIA Revenue Forecast Raised Amid Strong Data Center Demand", "summary": "Wall Street upgrades revenue estimates for FY2026 on continued AI infrastructure buildout.", "source": "CNBC"},
        ],
        "AAPL": [
            {"title": "Apple Intelligence Features Drive iPhone 17 Pre-Orders Higher", "summary": "Early data shows 18% pre-order increase vs prior cycle on AI-enhanced camera and Siri updates.", "source": "9to5Mac"},
            {"title": "Apple Reports Strong Services Revenue Growth in Q2 2026", "summary": "App Store, iCloud, and Apple TV+ segment revenues beat estimates by $800M.", "source": "MarketWatch"},
        ],
        "LLY": [
            {"title": "Eli Lilly's Mounjaro Gains FDA Approval for Cardiovascular Risk Reduction", "summary": "Label expansion dramatically widens eligible patient population beyond diabetes.", "source": "FDA"},
            {"title": "GLP-1 Drug Market Expected to Reach $150B by 2030", "summary": "Analysts project Lilly maintains 45% market share through patent protection.", "source": "Bloomberg"},
        ],
    }
    default = [
        {"title": f"{ticker} Reports Quarterly Earnings Beat", "summary": "Company exceeds analyst expectations on both revenue and EPS.", "source": "Bloomberg"},
        {"title": f"Institutional Investors Increase {ticker} Holdings", "summary": "13F filings show major funds adding to positions in recent quarter.", "source": "SEC"},
    ]
    items = templates.get(ticker.upper(), default)
    return [{"title": n["title"], "summary": n["summary"], "source": n["source"], "url": "#", "published": datetime.now().isoformat()} for n in items]


def get_demo_technicals(ticker: str) -> dict:
    info = STOCKS.get(ticker.upper(), {})
    price = info.get("current_price", 100.0)
    return {
        "ema20": round(price * 0.972, 2),
        "ema50": round(price * 0.940, 2),
        "ema200": round(price * 0.835, 2),
        "trend": "BULLISH",
        "rsi": 62.4,
        "rsi_signal": "NEUTRAL",
        "macd": 3.21,
        "macd_signal": 2.87,
        "macd_histogram": 0.34,
        "macd_cross": "BULLISH",
        "stoch_k": 68.2,
        "stoch_d": 61.5,
        "bb_upper": round(price * 1.048, 2),
        "bb_mid": round(price * 0.998, 2),
        "bb_lower": round(price * 0.952, 2),
        "bb_pct": 0.62,
        "atr": round(price * 0.022, 2),
        "atr_pct": 2.2,
        "support": round(price * 0.924, 2),
        "resistance": round(price * 1.044, 2),
        "price_vs_ema20_pct": 2.9,
    }
