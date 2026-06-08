#!/bin/bash
# TradeDesk Self-Update
# Pulls latest code from the git remote, rebuilds only what changed,
# restarts the backend, and signals the app to reload.
#
# Architecture note: the Electron app loads its UI from the backend
# (localhost:8765). So updating frontend = rebuild dist/ + reload window;
# updating backend = restart. Neither needs a new .dmg. Only changes to
# the Electron shell (electron/main.js, preload.js) need a .dmg rebuild.
#
# Usage:  ~/trading-platform/update.sh            (pull + apply)
#         ~/trading-platform/update.sh --check    (just report if updates exist)

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
LOG="/tmp/tradedesk-update.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $1" | tee -a "$LOG"; }

# No remote configured? Tell the user how to add one.
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "No git remote configured. Add one first:"
  echo "  cd $DIR"
  echo "  git remote add origin https://github.com/<you>/tradedesk.git"
  echo "  git push -u origin main"
  exit 2
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git fetch origin "$BRANCH" --quiet

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "UP_TO_DATE $LOCAL"
  exit 0
fi

# --check mode: just report
if [ "$1" = "--check" ]; then
  COUNT=$(git rev-list --count "$LOCAL..$REMOTE")
  echo "UPDATE_AVAILABLE $COUNT commits ($LOCAL -> $REMOTE)"
  exit 0
fi

log "Updating $LOCAL -> $REMOTE on $BRANCH"

# What changed? (decide what to rebuild)
CHANGED="$(git diff --name-only "$LOCAL" "$REMOTE")"

# Pull (local secrets/db/settings are gitignored, so they're untouched)
git merge --ff-only "origin/$BRANCH" >>"$LOG" 2>&1 || {
  log "Fast-forward failed — local commits present. Stashing & retrying."
  git stash push -u -m "auto-update-stash" >>"$LOG" 2>&1 || true
  git merge --ff-only "origin/$BRANCH" >>"$LOG" 2>&1
}
log "Code updated to $(git rev-parse --short HEAD)"

# Backend deps changed?
if echo "$CHANGED" | grep -q "backend/requirements.txt"; then
  log "requirements.txt changed — installing backend deps"
  /usr/bin/python3 -m pip install -r backend/requirements.txt --quiet >>"$LOG" 2>&1 || log "pip install had issues"
fi

# Frontend changed? rebuild dist/
if echo "$CHANGED" | grep -qE "frontend/(src|index.html|vite.config|package.json)"; then
  log "Frontend changed — rebuilding"
  cd frontend
  if echo "$CHANGED" | grep -q "frontend/package.json"; then
    npm install --silent >>"$LOG" 2>&1 || log "npm install had issues"
  fi
  npm run build >>"$LOG" 2>&1 && log "Frontend rebuilt" || log "Frontend build FAILED"
  cd "$DIR"
fi

# Electron shell changed? (needs a .dmg rebuild — can't hot-update)
if echo "$CHANGED" | grep -qE "frontend/electron/(main|preload)\.js"; then
  log "⚠ Electron shell changed — a full .dmg rebuild is needed:"
  log "    cd frontend && npm run electron:build, then reinstall the .dmg"
fi

# Restart backend to load new Python code
log "Restarting backend"
launchctl kickstart -k "gui/$(id -u)/com.tradedesk.backend" >>"$LOG" 2>&1 || \
  { pkill -9 -f "uvicorn main:app"; lsof -ti :8765 | xargs kill -9 2>/dev/null; \
    launchctl kickstart "gui/$(id -u)/com.tradedesk.backend" >>"$LOG" 2>&1; }

# Signal the app to reload (it loads UI from localhost, so a reload picks up new build)
touch /tmp/tradedesk-reload-signal

log "Update complete -> $(git rev-parse --short HEAD)"
osascript -e 'display notification "Updated to latest and restarted." with title "TradeDesk Updated"' 2>/dev/null || true
echo "UPDATED $(git rev-parse --short HEAD)"
