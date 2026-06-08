"""
Auto-Scanner — runs the full /api/scan logic on a schedule.
Surfaces top setups even when no specific news event triggered the agents.

Schedule:
- Market open (9:30am ET): Capture overnight setups
- Mid-morning (10:30am ET): Post-open reaction
- Lunch (12:30pm ET): Mid-day check
- Pre-close (3:00pm ET): End-of-day setups for tomorrow
- After-hours (4:30pm ET): React to earnings
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from event_bus import publish

_running = False
_task = None

# Hours to run (UTC). Adjust if needed.
# 9:30am ET = 13:30 UTC (during DST) — using a window approach instead
SCAN_HOURS_UTC = [13, 14, 16, 19, 20]   # 9am, 10am, 12pm, 3pm, 4pm ET (DST)
SCAN_MINUTES = [0, 30]                   # Run at top and bottom of hour


def is_market_hours() -> bool:
    """Rough check — weekday between 9am-5pm ET."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    # 13:00 UTC = 9am ET (DST) — 21:00 UTC = 5pm ET (DST)
    return 13 <= now.hour < 21


async def run_scan_internal():
    """Run the scan and publish results as bus event."""
    from main import run_scan  # imported lazily to avoid circular
    try:
        result = await run_scan()
        setups = result.get("setups", [])
        market_regime = result.get("market_regime", "")
        catalysts_count = len(result.get("catalysts", []))

        # Publish scan results as a bus event
        await publish(
            source="auto_scanner",
            type="scan_complete",
            data={
                "setups": setups,
                "market_regime": market_regime,
                "catalysts_count": catalysts_count,
                "setup_count": len(setups),
            },
            title=f"📊 Auto-scan: {len(setups)} setups found · {catalysts_count} catalysts",
            impact="HIGH" if setups else "MEDIUM",
            tickers=[s.get("ticker") for s in setups if s.get("ticker")],
        )

        # Check current mode for auto-execution
        from agents.orchestrator import get_mode
        mode = get_mode()

        # For each high-conviction setup, publish + optionally auto-execute
        for setup in setups:
            is_high = setup.get("conviction") == "HIGH" or setup.get("score", 0) >= 8
            if not is_high:
                continue

            await publish(
                source="auto_scanner",
                type="high_conviction_setup",
                data=setup,
                title=f"🎯 {setup.get('ticker')} {setup.get('direction')} @ ${setup.get('entry')} — {setup.get('catalyst', '')[:60]}",
                impact="CRITICAL",
                tickers=[setup.get("ticker")],
            )

            # AUTO_PAPER: execute high-conviction scanner setups too
            if mode in ("AUTO_PAPER", "AUTO_LIVE") and setup.get("direction") in ("LONG", "SHORT"):
                try:
                    from paper_trader import execute_paper_trade
                    await execute_paper_trade(
                        ticker=setup.get("ticker"),
                        direction=setup.get("direction"),
                        entry=setup.get("entry"),
                        stop=setup.get("stop"),
                        target1=setup.get("target1"),
                        target2=setup.get("target2"),
                        shares=setup.get("shares") or 0,
                        thesis=setup.get("thesis", setup.get("catalyst", "")),
                        confidence=setup.get("score", 7),
                        source="scanner",
                        strategy_tag="momentum",   # scanner = momentum strategy
                    )
                except Exception as e:
                    print(f"[AutoScanner] Paper exec error: {e}")

        print(f"[AutoScanner] Scan complete: {len(setups)} setups, {catalysts_count} catalysts (mode={mode})")
        return result
    except Exception as e:
        print(f"[AutoScanner] Scan error: {e}")
        return None


async def _loop(interval_minutes: int = 30):
    global _running
    _running = True
    print(f"[AutoScanner] Started — scanning every {interval_minutes} minutes during market hours")

    last_scan_minute = -1
    # Run one scan immediately so user sees results on startup
    print("[AutoScanner] Running initial scan...")
    await run_scan_internal()

    while _running:
        try:
            now = datetime.now(timezone.utc)
            current_minute = now.hour * 60 + now.minute

            # Run on schedule during market hours
            if is_market_hours() and (current_minute % interval_minutes == 0) and current_minute != last_scan_minute:
                print(f"[AutoScanner] Scheduled scan at {now.strftime('%H:%M UTC')}")
                await run_scan_internal()
                last_scan_minute = current_minute

        except Exception as e:
            print(f"[AutoScanner] Loop error: {e}")

        await asyncio.sleep(30)  # Check every 30s for schedule alignment


def start_auto_scanner(interval_minutes: int = 30):
    global _task
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_loop(interval_minutes))
    return _task


def stop_auto_scanner():
    global _running, _task
    _running = False
    if _task:
        _task.cancel()
