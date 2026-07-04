"""
Metrics engine (Phase 0 — ground truth).

Turns the closed-trade record into the numbers that actually tell you whether
the system has an edge — computed honestly, with the small-sample caveats made
explicit rather than hidden.

Everything here is read-only over the `positions` / `trade_journal` tables.

Key outputs:
  - expectancy (per-trade, in R and in $)
  - win rate, profit factor, avg win / avg loss
  - equity curve → annualized Sharpe, Sortino, max drawdown
  - Deflated Sharpe Ratio (Bailey & López de Prado 2014) — corrects the naive
    Sharpe for the number of strategy variations tried + non-normal returns.
    This is the number that stops you fooling yourself.
  - per-pattern and per-strategy breakdown
"""

import math
from database import get_connection


def _closed_trades():
    """Closed trades with realized pnl + R-multiple, oldest first."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.id, p.ticker, p.direction, p.entry_price, p.exit_price,
               p.pnl, p.exit_date, p.strategy, p.strategy_tag,
               j.r_multiple, j.pattern_tags, j.outcome
        FROM positions p
        LEFT JOIN trade_journal j ON j.position_id = p.id
        WHERE p.status = 'CLOSED' AND p.pnl IS NOT NULL
        ORDER BY COALESCE(p.exit_date, p.created_at) ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _basic(pnls):
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = (len(wins) / n * 100) if n else 0.0
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    expectancy = (sum(pnls) / n) if n else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss else (float("inf") if gross_win else 0.0)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy_usd": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "gross_profit": round(gross_win, 2),
        "gross_loss": round(-gross_loss, 2),
        "net_pnl": round(sum(pnls), 2),
    }


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs, ddof=1):
    n = len(xs)
    if n <= ddof:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def _skew(xs):
    n = len(xs); s = _std(xs)
    if n < 3 or s == 0:
        return 0.0
    m = _mean(xs)
    return (n / ((n - 1) * (n - 2))) * sum(((x - m) / s) ** 3 for x in xs)


def _kurtosis(xs):
    """Non-excess (Pearson) kurtosis; 3.0 == normal."""
    n = len(xs); s = _std(xs)
    if n < 4 or s == 0:
        return 3.0
    m = _mean(xs)
    return (sum(((x - m) / s) ** 4 for x in xs) / n)


def _max_drawdown(equity):
    """Max peak-to-trough drop of a cumulative equity curve (in the curve's units)."""
    peak = equity[0] if equity else 0.0
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    return mdd


def _sharpe(returns, periods_per_year):
    s = _std(returns)
    if s == 0:
        return 0.0
    return (_mean(returns) / s) * math.sqrt(periods_per_year)


def _sortino(returns, periods_per_year):
    downside = [r for r in returns if r < 0]
    dd = _std(downside) if len(downside) > 1 else 0.0
    if dd == 0:
        return 0.0
    return (_mean(returns) / dd) * math.sqrt(periods_per_year)


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def deflated_sharpe(returns, n_trials):
    """Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

    Returns the probability that the observed (non-annualized, per-trade) Sharpe
    exceeds what you'd expect from `n_trials` random strategy variations, given
    the sample's length, skew and kurtosis. > ~0.95 is the bar to take a strategy
    seriously; anything on a tiny sample is unreliable by construction.
    """
    T = len(returns)
    if T < 5:
        return None
    sr = _sharpe(returns, 1)  # per-trade (non-annualized) Sharpe
    sk = _skew(returns)
    ku = _kurtosis(returns)
    n = max(int(n_trials), 1)

    # Expected max Sharpe under the null of n independent trials (variance 1).
    euler = 0.5772156649
    e_inv = math.e ** -1
    z1 = _inv_norm(1 - 1.0 / n)
    z2 = _inv_norm(1 - 1.0 / n * e_inv)
    sr0 = z1 * (1 - euler) + z2 * euler  # expected max Sharpe (std of trials ~1)

    denom = math.sqrt(1 - sk * sr + (ku - 1) / 4.0 * sr ** 2)
    if denom <= 0:
        return None
    dsr = _norm_cdf(((sr - sr0) * math.sqrt(T - 1)) / denom)
    return round(dsr, 4)


def _inv_norm(p):
    """Inverse standard-normal CDF (Acklam's rational approximation)."""
    if p <= 0:
        return -1e9
    if p >= 1:
        return 1e9
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5; r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def compute_metrics(portfolio_size: float = 100000.0, n_strategy_trials: int = 8) -> dict:
    """Full metrics bundle over all closed trades. `n_strategy_trials` is the
    number of strategy variations tried (feeds the Deflated Sharpe penalty)."""
    trades = _closed_trades()
    pnls = [t["pnl"] for t in trades]
    out = {"overall": _basic(pnls), "reliable": None, "caveat": None}

    if not trades:
        out["caveat"] = "No closed trades yet."
        return out

    # Per-trade returns as a fraction of portfolio → equity curve
    rets = [(t["pnl"] / portfolio_size) for t in trades]
    equity = []
    cum = 0.0
    for r in rets:
        cum += r
        equity.append(cum)

    # Trades/year annualization factor from actual cadence (fallback 100/yr)
    ppy = _trades_per_year(trades) or 100

    out["overall"].update({
        "sharpe_annualized": round(_sharpe(rets, ppy), 2),
        "sortino_annualized": round(_sortino(rets, ppy), 2),
        "max_drawdown_pct": round(_max_drawdown(equity) * 100, 2),
        "sharpe_per_trade": round(_sharpe(rets, 1), 3),
        "deflated_sharpe": deflated_sharpe(rets, n_strategy_trials),
        "r_expectancy": _r_expectancy(trades),
    })

    n = len(trades)
    out["reliable"] = n >= 30
    if n < 30:
        out["caveat"] = (f"Only {n} closed trades — statistically UNRELIABLE. "
                         f"Deflated Sharpe and Sharpe need ~30+ trades to mean anything. "
                         f"Treat these as directional, not conclusive.")

    out["by_pattern"] = _breakdown(trades, key="pattern")
    out["by_strategy"] = _breakdown(trades, key="strategy_tag")
    return out


def _r_expectancy(trades):
    rs = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    return round(_mean(rs), 3) if rs else None


def _trades_per_year(trades):
    dates = [t.get("exit_date") for t in trades if t.get("exit_date")]
    if len(dates) < 2:
        return None
    try:
        from datetime import datetime
        def pd(s):
            return datetime.fromisoformat(str(s)[:19].replace("T", " ").split(".")[0])
        span_days = (pd(dates[-1]) - pd(dates[0])).days or 1
        return max(1, round(len(trades) / span_days * 365))
    except Exception:
        return None


def _breakdown(trades, key="pattern"):
    import json
    buckets = {}
    for t in trades:
        keys = []
        if key == "pattern":
            try:
                keys = json.loads(t.get("pattern_tags") or "[]")
            except Exception:
                keys = []
        else:
            keys = [t.get(key) or "unknown"]
        for k in keys:
            b = buckets.setdefault(k, [])
            b.append(t["pnl"])
    out = []
    for k, pnls in buckets.items():
        wins = len([p for p in pnls if p > 0])
        out.append({
            "key": k, "n": len(pnls),
            "win_rate": round(wins / len(pnls) * 100, 1),
            "net_pnl": round(sum(pnls), 2),
            "expectancy": round(_mean(pnls), 2),
        })
    return sorted(out, key=lambda x: -x["n"])
