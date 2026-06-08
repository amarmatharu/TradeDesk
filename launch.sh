#!/bin/bash
# TradeDesk — Launch Script
# Starts backend + opens Electron window

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  📈 TradeDesk AI — Starting..."
echo ""

# Kill any old instances
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "TradeDesk" 2>/dev/null || true
sleep 1

# Start Python backend
echo "  ⚙  Starting backend..."
cd "$DIR/backend"
PYTHONUNBUFFERED=1 python3 -m uvicorn main:app \
  --host 127.0.0.1 \
  --port 8765 \
  --no-access-log \
  > /tmp/tradedesk-backend.log 2>&1 &

BACKEND_PID=$!
echo "  ✓  Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo "  ⏳ Waiting for backend..."
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8765/api/market/overview > /dev/null 2>&1; then
    echo "  ✓  Backend ready"
    break
  fi
  sleep 1
done

# Launch Electron app
echo "  🖥  Launching TradeDesk..."
cd "$DIR/frontend"
NODE_ENV=development ./node_modules/.bin/electron . 2>/dev/null &

echo ""
echo "  ✅ TradeDesk is running!"
echo "  📋 Backend logs: tail -f /tmp/tradedesk-backend.log"
echo ""

# Keep script alive — kill backend when Electron closes
wait
