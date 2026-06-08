#!/bin/bash
# TradeDesk Paper Trading — Status Report
# Run anytime:  ~/trading-platform/status.sh

API="http://localhost:8765"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  📝 TRADEDESK PAPER TRADING — STATUS"
echo "  $(date '+%A, %B %d %Y · %I:%M %p')"
echo "════════════════════════════════════════════════════════════════"

# Service alive?
if ! curl -sf --max-time 4 "$API/api/agents/mode" >/dev/null 2>&1; then
  echo ""
  echo "  ⚠  Backend NOT responding. Check service:"
  echo "     launchctl list | grep tradedesk"
  echo "     tail /tmp/tradedesk-backend.err.log"
  echo ""
  exit 1
fi

HEALTH=$(curl -s --max-time 5 "${API%/api/*}/api/health" 2>/dev/null)
echo "$HEALTH" | python3 -c "import json,sys
try:
    d=json.load(sys.stdin)
    print(f'  Heartbeat: {d.get(\"heartbeat_age_sec\")}s ago | Uptime: {int(d.get(\"uptime_sec\",0))}s | Broker: {\"ok\" if d.get(\"broker_available\") else \"DOWN\"}')
except: pass" 2>/dev/null
MODE=$(curl -s "$API/api/agents/mode" | python3 -c "import json,sys; print(json.load(sys.stdin)['mode'])")
echo ""
echo "  Service: ✓ RUNNING   |   Mode: $MODE"

# Performance
curl -s "$API/api/paper/report" | python3 -c "
import json,sys
d=json.load(sys.stdin)
sess=d.get('session') or {}
print()
print('  ── PERFORMANCE ───────────────────────────────────────────')
print(f'  Starting capital : \${d[\"starting_capital\"]:,.2f}')
print(f'  Current equity   : \${d[\"current_equity\"]:,.2f}')
pnl=d['total_pnl']; ret=d['total_return_pct']
sign='+' if pnl>=0 else ''
print(f'  Total P&L        : {sign}\${pnl:,.2f}  ({sign}{ret}%)')
print(f'    Realized       : \${d[\"realized_pnl\"]:,.2f}')
print(f'    Unrealized     : \${d[\"unrealized_pnl\"]:,.2f}')
print()
print('  ── ACTIVITY ──────────────────────────────────────────────')
print(f'  Open positions   : {d[\"open_count\"]}')
print(f'  Closed trades    : {d[\"closed_count\"]}')
print(f'  Win rate         : {d[\"win_rate\"]}%')
print(f'  Patterns learned : {d[\"patterns_learned\"]}')

op=d.get('open_positions',[])
if op:
    print()
    print('  ── OPEN POSITIONS ────────────────────────────────────────')
    for p in op:
        s='+' if p['unrealized_pnl']>=0 else ''
        print(f'    {p[\"direction\"]:5} {int(p[\"shares\"]):>4} {p[\"ticker\"]:6} @ \${p[\"entry\"]:<8.2f} now \${p[\"current\"]:<8.2f}  {s}\${p[\"unrealized_pnl\"]:.2f}')

tp=d.get('top_patterns',[])
favor=[p for p in tp if p['recommendation']=='FAVOR']
avoid=[p for p in tp if p['recommendation']=='AVOID']
if favor or avoid:
    print()
    print('  ── PLAYBOOK (what the system has learned) ────────────────')
    for p in favor[:5]:
        print(f'    ✓ {p[\"pattern\"]:30} win {p[\"win_rate\"]}%  R {p[\"avg_r\"]}  (n={p[\"sample_size\"]})')
    for p in avoid[:5]:
        print(f'    ✗ {p[\"pattern\"]:30} win {p[\"win_rate\"]}%  R {p[\"avg_r\"]}  (n={p[\"sample_size\"]})')
elif tp:
    print()
    print('  ── PATTERNS TRACKED (need n≥4 for FAVOR/AVOID) ───────────')
    for p in tp[:8]:
        print(f'    · {p[\"pattern\"]:30} win {p[\"win_rate\"]}%  R {p[\"avg_r\"]}  (n={p[\"sample_size\"]})')
"

# Strategy A/B comparison
echo ""
echo "  ── STRATEGY A/B (head-to-head, equal \$25k each) ──────────"
curl -s "$API/api/strategies/compare" | python3 -c "
import json,sys
d=json.load(sys.stdin)
bench=d.get('_benchmark',{})
rows=[(sid,s) for sid,s in d.items() if sid!='_benchmark']
for sid,s in rows:
    ret=s['return_pct']; sign='+' if ret>=0 else ''
    bar='🟢' if ret>0 else '🔴' if ret<0 else '⚪'
    print(f'  {bar} {s[\"name\"]:18} {sign}{ret:.2f}%  (\${s[\"total_pnl\"]:+,.0f})  open {s[\"open_positions\"]} · closed {s[\"closed_trades\"]} · win {s[\"win_rate\"]}%')
if bench:
    print(f'  📊 {bench.get(\"name\",\"SPY\")}:  {bench.get(\"return_pct\",0):+.2f}%  ← beat this to have edge')
# Verdict
if rows:
    best=max(rows,key=lambda x:x[1]['return_pct'])
    bret=bench.get('return_pct',0)
    if best[1]['closed_trades']>=5:
        winner=best[1]['name'] if best[1]['return_pct']>bret else 'SPY (just hold)'
        print(f'  → Leading: {winner}')
    else:
        print(f'  → Too few closed trades to judge (need ≥5 each)')
"

# Circuit breakers
echo ""
echo "  ── CIRCUIT BREAKERS ──────────────────────────────────────"
curl -s "$API/api/risk/guard" | python3 -c "
import json,sys
d=json.load(sys.stdin)
m=d.get('metrics',{}); c=d.get('config',{})
status='🟢 TRADING ENABLED' if d['allowed'] else '🛑 HALTED — '+d['reason']
print(f'  {status}')
print(f'  Daily P&L  : {m.get(\"daily_pnl_pct\",0):+.2f}%  (limit -{c.get(\"daily_loss_limit_pct\")}%)')
print(f'  Drawdown   : {m.get(\"drawdown_pct\",0):+.2f}%  (limit -{c.get(\"max_drawdown_pct\")}%)')
print(f'  Loss streak: {m.get(\"loss_streak\",0)}  (limit {c.get(\"max_consecutive_losses\")})')
print(f'  Trades today: {m.get(\"trades_today\",0)}  (cap {c.get(\"max_trades_per_day\")})')
"

# Real broker
echo ""
echo "  ── ALPACA PAPER BROKER ───────────────────────────────────"
curl -s "$API/api/broker/account" | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d.get('available'):
    a=d['account']
    print(f'  ✓ Connected   Equity \${a.get(\"equity\",0):,.0f}   BP \${a.get(\"buying_power\",0):,.0f}')
else:
    print('  ⚠ Broker not available')
"

# Agent stats
echo ""
echo "  ── AGENT ACTIVITY ────────────────────────────────────────"
curl -s "$API/api/agents/stats" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'  Events processed : {d[\"events_total\"]}')
print(f'  Agent runs       : {d[\"agent_runs_total\"]}')
print(f'  AI spend (total) : \${d[\"total_cost_usd\"]:.4f}')
"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""
