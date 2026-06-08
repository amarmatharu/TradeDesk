#!/bin/bash
# TradeDesk — one-shot setup for a fresh machine.
#
#   git clone git@github.com:amarmatharu/TradeDesk.git
#   cd TradeDesk
#   ./setup.sh
#
# Installs deps, builds the frontend, sets up your .env, installs the
# launchd services (backend + watchdog + auto-update), and starts everything.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
LA="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

echo ""
echo "═══════════════════════════════════════════════"
echo "  TradeDesk Setup"
echo "═══════════════════════════════════════════════"
echo "  Project: $DIR"

# ── 1. Python ──────────────────────────────────────────────
PYTHON="$(command -v python3 || echo /usr/bin/python3)"
echo ""
echo "1. Python deps ($PYTHON)..."
"$PYTHON" -m pip install -r backend/requirements.txt --quiet || {
  echo "   ⚠ pip install hit issues — you may need: $PYTHON -m pip install --user -r backend/requirements.txt"
}
echo "   ✓ backend deps installed"

# ── 2. Node / frontend ─────────────────────────────────────
echo ""
echo "2. Frontend deps + build..."
if command -v npm >/dev/null 2>&1; then
  ( cd frontend && npm install --silent && npm run build >/dev/null 2>&1 ) \
    && echo "   ✓ frontend built" || echo "   ⚠ frontend build had issues (run manually: cd frontend && npm install && npm run build)"
else
  echo "   ⚠ npm not found — install Node.js, then: cd frontend && npm install && npm run build"
fi

# ── 3. .env ────────────────────────────────────────────────
echo ""
echo "3. API keys (.env)..."
if [ -f backend/.env ]; then
  echo "   ✓ backend/.env already exists — keeping it"
else
  cp backend/.env.example backend/.env
  echo "   → Created backend/.env from template."
  echo "   → EDIT IT with your keys before trading:  nano backend/.env"
fi

# ── 4. launchd services (from templates) ───────────────────
echo ""
echo "4. Installing launchd services..."
mkdir -p "$LA"
for name in backend watchdog autoupdate; do
  tpl="deploy/com.tradedesk.${name}.plist.template"
  out="$LA/com.tradedesk.${name}.plist"
  sed -e "s|__PROJECT_DIR__|$DIR|g" -e "s|__PYTHON__|$PYTHON|g" "$tpl" > "$out"
  launchctl unload "$out" 2>/dev/null || true
  launchctl load "$out"
  echo "   ✓ com.tradedesk.${name} installed + loaded"
done

# ── 5. Wait for backend ────────────────────────────────────
echo ""
echo "5. Waiting for backend to come up..."
for i in $(seq 1 20); do
  if curl -sf --max-time 4 http://localhost:8765/api/health >/dev/null 2>&1; then
    echo "   ✓ Backend healthy"
    break
  fi
  sleep 2
done

echo ""
echo "═══════════════════════════════════════════════"
echo "  Setup complete."
echo ""
echo "  Next steps:"
echo "   1. Add your API keys:   nano backend/.env"
echo "      then restart:        launchctl kickstart -k gui/$UID_NUM/com.tradedesk.backend"
echo "   2. Build the desktop app (optional):"
echo "      cd frontend && npm run electron:build"
echo "      open dist-electron/*.dmg  → drag to Applications"
echo "   3. Check status anytime:  ./status.sh"
echo "═══════════════════════════════════════════════"
echo ""
