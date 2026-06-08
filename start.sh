#!/bin/bash
set -e

echo "🚀 Starting TradeDesk AI Trading Platform..."

# Start backend
echo "📡 Starting backend (port 8000)..."
cd "$(dirname "$0")/backend"
pip3 install -r requirements.txt -q
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# Wait for backend
sleep 2
echo "✅ Backend running (PID $BACKEND_PID)"

# Start frontend
echo "🖥  Starting frontend (port 5173)..."
cd "$(dirname "$0")/frontend"
npm install -q
npm run dev &
FRONTEND_PID=$!

echo ""
echo "================================================"
echo "  TradeDesk is running!"
echo "  Frontend: http://localhost:5173"
echo "  Backend API: http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo "================================================"
echo ""
echo "⚠️  To enable AI analysis, add your Anthropic API key:"
echo "   echo 'ANTHROPIC_API_KEY=sk-ant-...' > backend/.env"
echo ""
echo "Press Ctrl+C to stop all services"

wait $BACKEND_PID $FRONTEND_PID
