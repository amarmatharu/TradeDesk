#!/bin/bash
# TradeDesk — Dev launcher (Electron + Vite + Python backend)
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  ████████╗██████╗  █████╗ ██████╗ ███████╗"
echo "  ╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██╔════╝"
echo "     ██║   ██████╔╝███████║██║  ██║█████╗  "
echo "     ██║   ██╔══██╗██╔══██║██║  ██║██╔══╝  "
echo "     ██║   ██║  ██║██║  ██║██████╔╝███████╗"
echo "     ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝"
echo "              AI Trading Platform"
echo ""

# ── 1. Backend ────────────────────────────────────────────────────────────────
echo "🐍 Starting Python backend on port 8765..."
cd "$ROOT/backend"
PYTHON=$(which python3 || which python)
$PYTHON -m pip install -r requirements.txt -q --disable-pip-version-check 2>/dev/null || true
$PYTHON -m uvicorn main:app --host 127.0.0.1 --port 8765 --no-access-log > /tmp/tradedesk-backend.log 2>&1 &
BACKEND_PID=$!
echo "   Backend PID: $BACKEND_PID"

# Wait for backend
echo "   Waiting for backend..."
for i in $(seq 1 20); do
  if curl -sf http://localhost:8765/api/market/overview >/dev/null 2>&1; then
    echo "   ✅ Backend ready"
    break
  fi
  sleep 1
done

# ── 2. Frontend (Vite dev server) ─────────────────────────────────────────────
echo ""
echo "⚛️  Starting Vite frontend on port 5173..."
cd "$ROOT/frontend"
npm install -q 2>/dev/null || true
npm run dev > /tmp/tradedesk-frontend.log 2>&1 &
FRONTEND_PID=$!
echo "   Frontend PID: $FRONTEND_PID"

# Wait for Vite
for i in $(seq 1 15); do
  if curl -sf http://localhost:5173 >/dev/null 2>&1; then
    echo "   ✅ Frontend ready"
    break
  fi
  sleep 1
done

# ── 3. Set API key in backend .env if provided ────────────────────────────────
if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" > "$ROOT/backend/.env"
  echo "✅ Anthropic API key set"
fi

# ── 4. Launch Electron ────────────────────────────────────────────────────────
echo ""
echo "🚀 Launching TradeDesk..."
cd "$ROOT/electron"
ELECTRON_DEV=true node_modules/.bin/electron .

# ── Cleanup on exit ───────────────────────────────────────────────────────────
echo ""
echo "Shutting down..."
kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
echo "Done."
