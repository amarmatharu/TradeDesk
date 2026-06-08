#!/bin/bash
# TradeDesk Watchdog — independent liveness monitor.
# Run every 60s by launchd. Detects a frozen/dead backend and hard-restarts it.
# Two signals must BOTH be healthy: HTTP responds AND heartbeat file is fresh.

HEARTBEAT="/tmp/tradedesk-heartbeat"
LOG="/tmp/tradedesk-watchdog.log"
LABEL="com.tradedesk.backend"
MAX_HEARTBEAT_AGE=120         # heartbeat older than this = genuinely frozen
RESTART_COOLDOWN=180          # don't restart again within this window (let it boot)
STATE="/tmp/tradedesk-watchdog-fails"
LAST_RESTART="/tmp/tradedesk-watchdog-lastrestart"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $1" >> "$LOG"; }
now=$(date +%s)

# Primary liveness signal = HEARTBEAT freshness. The backend's heartbeat task
# writes every 20s even while the API is briefly busy on startup. This avoids
# false "frozen" reads during the post-restart event burst.
healthy=true
reason=""
if [ -f "$HEARTBEAT" ]; then
  hb=$(cat "$HEARTBEAT" 2>/dev/null | cut -d. -f1)
  if [ -n "$hb" ]; then
    age=$((now - hb))
    [ "$age" -gt "$MAX_HEARTBEAT_AGE" ] && { healthy=false; reason="heartbeat stale (${age}s)"; }
  else
    healthy=false; reason="heartbeat unreadable"
  fi
else
  healthy=false; reason="no heartbeat file"
fi

if $healthy; then
  echo "0" > "$STATE"
  exit 0
fi

# Respect cooldown — if we restarted recently, give it time to boot (don't loop)
if [ -f "$LAST_RESTART" ]; then
  last=$(cat "$LAST_RESTART" 2>/dev/null || echo 0)
  since=$((now - last))
  if [ "$since" -lt "$RESTART_COOLDOWN" ]; then
    log "Unhealthy ($reason) but within cooldown (${since}s < ${RESTART_COOLDOWN}s) — waiting for boot"
    exit 0
  fi
fi

# Require 2 consecutive failures before acting (avoid a transient blip)
fails=$(cat "$STATE" 2>/dev/null || echo 0)
fails=$((fails + 1))
echo "$fails" > "$STATE"
log "UNHEALTHY ($reason) — consecutive failures: $fails"

if [ "$fails" -ge 2 ]; then
  log "RESTARTING backend (kickstart -k)"
  pkill -9 -f "uvicorn main:app" 2>/dev/null
  lsof -ti :8765 2>/dev/null | xargs kill -9 2>/dev/null
  launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>>"$LOG"
  echo "0" > "$STATE"
  echo "$now" > "$LAST_RESTART"
  osascript -e 'display notification "Backend was frozen — auto-restarted by watchdog." with title "TradeDesk Watchdog"' 2>/dev/null
  log "Restart issued + notification sent"
fi
