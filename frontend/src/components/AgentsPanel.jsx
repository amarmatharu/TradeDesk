import { useEffect, useState, useRef } from 'react'
import axios from 'axios'

const BASE = 'http://localhost:8765'
const IMP = { CRITICAL: '#f85149', HIGH: '#f78166', MEDIUM: '#e3b341', LOW: '#8b949e' }
const ACTION_COLOR = { BUY: '#3fb950', WAIT: '#e3b341', PASS: '#8b949e', FILTERED_OUT: '#30363d', RESEARCH_DECLINED: '#8b949e', RISK_BLOCKED: '#f85149' }

export default function AgentsPanel({ onSelectTicker }) {
  const [tab, setTab] = useState('pending')
  const [pending, setPending] = useState([])
  const [activity, setActivity] = useState([])
  const [stats, setStats] = useState(null)
  const [monitorChecks, setMonitorChecks] = useState([])
  const [monitorStatus, setMonitorStatus] = useState(null)
  const [journalEntries, setJournalEntries] = useState([])
  const [journalStats, setJournalStats] = useState(null)
  const [learnings, setLearnings] = useState({ learnings: [], playbook: { favor: [], avoid: [] } })
  const [mode, setMode] = useState('SUGGEST')
  const [availableModes, setAvailableModes] = useState([])
  const esRef = useRef(null)

  // ── Initial load + SSE subscription ──────────────────────────────────────
  useEffect(() => {
    loadAll()
    connectStream()
    const interval = setInterval(loadAll, 30000)
    return () => { clearInterval(interval); esRef.current?.close() }
  }, [])

  const loadAll = async () => {
    try {
      const [p, s, m, mc, ms, je, js, le] = await Promise.all([
        axios.get(`${BASE}/api/agents/pending-trades`),
        axios.get(`${BASE}/api/agents/stats`),
        axios.get(`${BASE}/api/agents/mode`),
        axios.get(`${BASE}/api/agents/monitor/checks?limit=30`),
        axios.get(`${BASE}/api/agents/monitor/status`),
        axios.get(`${BASE}/api/agents/journal/entries?limit=20`),
        axios.get(`${BASE}/api/agents/journal/stats`),
        axios.get(`${BASE}/api/agents/journal/learnings`),
      ])
      setPending(p.data.trades || [])
      setStats(s.data)
      setMode(m.data.mode)
      setAvailableModes(m.data.available || [])
      setMonitorChecks(mc.data.checks || [])
      setMonitorStatus(ms.data)
      setJournalEntries(je.data.entries || [])
      setJournalStats(js.data)
      setLearnings(le.data || { learnings: [], playbook: { favor: [], avoid: [] } })
    } catch {}
  }

  const backfillJournal = async () => {
    try {
      const r = await axios.post(`${BASE}/api/agents/journal/backfill`)
      alert(`Analyzed ${r.data.processed} closed trades`)
      loadAll()
    } catch (e) { alert('Backfill failed: ' + e.message) }
  }

  const connectStream = () => {
    const es = new EventSource(`${BASE}/api/agents/stream`)
    esRef.current = es
    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        if (event.type === 'heartbeat' || event.type === 'connected') return
        setActivity(prev => [event, ...prev].slice(0, 100))
        // If new pending trade, refresh
        if (event.type === 'new_pending_trade') loadAll()
      } catch {}
    }
    es.onerror = () => setTimeout(connectStream, 5000)
  }

  const changeMode = async (newMode) => {
    try {
      await axios.post(`${BASE}/api/agents/mode`, { mode: newMode })
      setMode(newMode)
    } catch {}
  }

  const decideTrade = async (id, action) => {
    try {
      await axios.post(`${BASE}/api/agents/pending-trades/${id}/decision`, { action })
      setPending(prev => prev.filter(p => p.id !== id))
      loadAll()
    } catch (e) { alert('Decision failed: ' + e.message) }
  }

  return (
    <div style={s.wrap}>
      {/* ── Header ─────────────────────────────────────────────── */}
      <div style={s.header}>
        <div>
          <div style={s.title}>🤖 Agent System</div>
          <div style={s.subtitle}>
            Multi-agent pipeline: Scout → Research → Risk → Trader
          </div>
        </div>
        <div style={s.headerRight}>
          <ModeBadge mode={mode} options={availableModes} onChange={changeMode} />
        </div>
      </div>

      {/* ── Tabs ───────────────────────────────────────────────── */}
      <div style={s.tabs}>
        {[
          ['pending',  `Pending${pending.length ? ` (${pending.length})` : ''}`],
          ['monitor',  `Monitor${monitorStatus?.open_positions ? ` (${monitorStatus.open_positions})` : ''}`],
          ['journal',  `Journal${journalEntries.length ? ` (${journalEntries.length})` : ''}`],
          ['activity', 'Activity'],
          ['stats',    'Stats'],
        ].map(([k, l]) => (
          <button key={k} style={{ ...s.tab, ...(tab === k ? s.tabActive : {}) }} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {/* ── Body ───────────────────────────────────────────────── */}
      <div style={s.body}>
        {tab === 'pending' && <PendingPanel trades={pending} onDecide={decideTrade} onSelectTicker={onSelectTicker} />}
        {tab === 'monitor' && <MonitorPanel checks={monitorChecks} status={monitorStatus} onSelectTicker={onSelectTicker} />}
        {tab === 'journal' && <JournalPanel entries={journalEntries} stats={journalStats} learnings={learnings} onSelectTicker={onSelectTicker} onBackfill={backfillJournal} />}
        {tab === 'activity' && <ActivityPanel activity={activity} />}
        {tab === 'stats' && <StatsPanel stats={stats} />}
      </div>
    </div>
  )
}

// ── Sub-components ──────────────────────────────────────────────────────────

function ModeBadge({ mode, options, onChange }) {
  return (
    <select style={s.modeSelect} value={mode} onChange={e => onChange(e.target.value)}>
      {options.map(m => <option key={m} value={m}>{m}</option>)}
    </select>
  )
}

function PendingPanel({ trades, onDecide, onSelectTicker }) {
  if (!trades.length) {
    return (
      <div style={s.empty}>
        <div style={s.emptyIcon}>🤖</div>
        <div style={{ fontWeight: 700, color: '#e6edf3' }}>No pending trades</div>
        <div style={{ color: '#8b949e', maxWidth: 300, textAlign: 'center', lineHeight: 1.6, fontSize: 12, marginTop: 4 }}>
          The agent pipeline is watching all events. When Scout finds a high-conviction setup, you'll see a pending trade here for review.
        </div>
      </div>
    )
  }
  return (
    <div style={s.list}>
      {trades.map(t => <PendingTradeCard key={t.id} trade={t} onDecide={onDecide} onSelectTicker={onSelectTicker} />)}
    </div>
  )
}

function PendingTradeCard({ trade, onDecide, onSelectTicker }) {
  const [expanded, setExpanded] = useState(false)
  const confColor = trade.confidence >= 8 ? '#3fb950' : trade.confidence >= 6 ? '#e3b341' : '#f78166'
  const dirColor = trade.direction === 'LONG' ? '#3fb950' : '#f85149'

  return (
    <div style={s.card}>
      <div style={s.cardHeader} onClick={() => setExpanded(e => !e)}>
        <div style={s.cardHeaderLeft}>
          <button style={s.tickerChip} onClick={(e) => { e.stopPropagation(); onSelectTicker?.(trade.ticker) }}>
            {trade.ticker}
          </button>
          <span style={{ ...s.dirBadge, background: dirColor + '22', color: dirColor }}>
            {trade.direction === 'LONG' ? '▲ LONG' : '▼ SHORT'}
          </span>
          <span style={{ ...s.confChip, color: confColor }}>
            {trade.confidence}/10
          </span>
        </div>
        <div style={s.cardHeaderRight}>
          <span style={s.pendingChip}>PENDING</span>
        </div>
      </div>

      <div style={s.thesis}>{trade.thesis}</div>

      <div style={s.priceGrid}>
        <PriceBox label="Entry"    value={`$${trade.entry}`} highlight />
        <PriceBox label="Stop"     value={`$${trade.stop}`} color="#f85149" />
        <PriceBox label="Target 1" value={`$${trade.target1}`} color="#3fb950" />
        <PriceBox label="Target 2" value={`$${trade.target2}`} color="#3fb950" />
        <PriceBox label="Shares"   value={trade.shares} />
        <PriceBox label="Risk"     value={`$${(trade.risk_dollars || 0).toFixed(0)}`} color="#f78166" />
        <PriceBox label="Position" value={`$${(trade.position_value || 0).toFixed(0)}`} />
      </div>

      {expanded && (
        <div style={s.agentChain}>
          <AgentStage name="🕵 Scout"    data={trade.scout_output} />
          <AgentStage name="🔬 Research" data={trade.research_output} />
          <AgentStage name="🛡 Risk"     data={trade.risk_output} />
          <AgentStage name="💼 Trader"   data={trade.trader_output} />
        </div>
      )}

      <div style={s.actions}>
        <button style={s.expandBtn} onClick={() => setExpanded(e => !e)}>
          {expanded ? '↑ Hide reasoning' : '↓ See full agent reasoning'}
        </button>
        <div style={s.actionsRight}>
          <button style={s.rejectBtn} onClick={() => onDecide(trade.id, 'reject')}>✕ Reject</button>
          <button style={s.approveBtn} onClick={() => onDecide(trade.id, 'approve')}>✓ Approve & Enter</button>
        </div>
      </div>
    </div>
  )
}

function AgentStage({ name, data }) {
  if (!data) return null
  return (
    <div style={s.stage}>
      <div style={s.stageHeader}>{name}</div>
      <div style={s.stageBody}>
        {Object.entries(data).slice(0, 8).map(([k, v]) => {
          if (typeof v === 'object') v = JSON.stringify(v).slice(0, 80)
          return (
            <div key={k} style={s.stageRow}>
              <span style={s.stageKey}>{k}:</span>
              <span style={s.stageVal}>{String(v).slice(0, 200)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function PriceBox({ label, value, color, highlight }) {
  return (
    <div style={{ ...s.priceBox, background: highlight ? '#1f6feb11' : '#0d1117' }}>
      <div style={s.priceLabel}>{label}</div>
      <div style={{ ...s.priceVal, color: color || '#e6edf3' }}>{value}</div>
    </div>
  )
}

function MonitorPanel({ checks, status, onSelectTicker }) {
  if (!checks?.length) {
    return (
      <div style={s.empty}>
        <div style={s.emptyIcon}>👁</div>
        <div style={{ fontWeight: 700, color: '#e6edf3' }}>No checks yet</div>
        <div style={{ color: '#8b949e', maxWidth: 320, textAlign: 'center', lineHeight: 1.6, fontSize: 12, marginTop: 4 }}>
          The Monitor agent runs every 60 seconds against every open position.
          When a stop is hit, target reached, or thesis broken — it acts automatically.
        </div>
      </div>
    )
  }

  // Group by position
  const byTicker = {}
  checks.forEach(c => {
    if (!byTicker[c.ticker]) byTicker[c.ticker] = []
    byTicker[c.ticker].push(c)
  })

  return (
    <div style={s.list}>
      {status && (
        <div style={s.monitorHeader}>
          <span>{status.open_positions} positions monitored</span>
          <span style={{ color: '#8b949e' }}>·</span>
          <span>{status.total_checks} total checks</span>
          {status.exits_today > 0 && (
            <>
              <span style={{ color: '#8b949e' }}>·</span>
              <span style={{ color: '#f85149', fontWeight: 700 }}>{status.exits_today} exits today</span>
            </>
          )}
        </div>
      )}
      {Object.entries(byTicker).map(([ticker, list]) => (
        <MonitorTicker key={ticker} ticker={ticker} checks={list} onSelectTicker={onSelectTicker} />
      ))}
    </div>
  )
}

function MonitorTicker({ ticker, checks, onSelectTicker }) {
  const latest = checks[0]
  const pnl = latest.unrealized_pnl || 0
  const pnlPct = latest.unrealized_pnl_pct || 0
  const pnlColor = pnl >= 0 ? '#3fb950' : '#f85149'
  const verdictColor = latest.verdict?.startsWith('EXIT') ? '#f85149'
                     : latest.verdict === 'TRIM_HALF' ? '#e3b341'
                     : latest.verdict === 'MOVE_STOP_TO_BE' ? '#58a6ff'
                     : '#8b949e'

  return (
    <div style={s.card}>
      <div style={s.cardHeader}>
        <div style={s.cardHeaderLeft}>
          <button style={s.tickerChip} onClick={() => onSelectTicker?.(ticker)}>{ticker}</button>
          <span style={{ ...s.dirBadge, color: pnlColor }}>
            ${latest.current_price?.toFixed(2)}
          </span>
          <span style={{ color: pnlColor, fontWeight: 700, fontSize: 12 }}>
            {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} ({pnlPct.toFixed(1)}%)
          </span>
        </div>
        <div style={s.cardHeaderRight}>
          <span style={{ ...s.pendingChip, color: verdictColor, background: verdictColor + '22' }}>
            {latest.verdict}
          </span>
        </div>
      </div>

      <div style={{ fontSize: 11, color: '#c9d1d9', padding: '6px 10px', background: '#0d1117', borderRadius: 5, marginBottom: 8 }}>
        {latest.reason}
      </div>

      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: '#8b949e' }}>
        {latest.stop_distance_pct != null && <span>Stop: <strong style={{ color: '#f85149' }}>{latest.stop_distance_pct.toFixed(1)}% away</strong></span>}
        {latest.t1_distance_pct != null && <span>T1: <strong style={{ color: '#3fb950' }}>{latest.t1_distance_pct.toFixed(1)}% away</strong></span>}
        <span style={{ marginLeft: 'auto' }}>{new Date(latest.created_at).toLocaleTimeString()}</span>
      </div>

      {/* Recent decisions */}
      {checks.length > 1 && (
        <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid #21262d' }}>
          <div style={{ fontSize: 9, color: '#8b949e', marginBottom: 4, fontWeight: 700, letterSpacing: 0.5 }}>RECENT CHECKS</div>
          {checks.slice(1, 5).map(c => (
            <div key={c.id} style={{ display: 'flex', gap: 8, fontSize: 10, color: '#8b949e', padding: '2px 0' }}>
              <span style={{ minWidth: 70 }}>{new Date(c.created_at).toLocaleTimeString()}</span>
              <span style={{ color: c.verdict?.startsWith('EXIT') ? '#f85149' : '#c9d1d9', minWidth: 90, fontWeight: 600 }}>{c.verdict}</span>
              <span style={{ flex: 1 }}>{c.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function JournalPanel({ entries, stats, learnings, onSelectTicker, onBackfill }) {
  const playbook = learnings?.playbook || { favor: [], avoid: [] }
  const hasData = entries.length > 0 || (stats?.total_trades || 0) > 0

  return (
    <div style={s.list}>
      {/* Top stats */}
      {hasData && stats && (
        <div style={s.journalStatsRow}>
          <JournalStat label="Trades"     value={stats.total_trades} />
          <JournalStat label="Win rate"   value={`${stats.win_rate}%`} color={stats.win_rate >= 50 ? '#3fb950' : '#f78166'} />
          <JournalStat label="Avg R"      value={`${stats.avg_r_multiple}R`} color={stats.avg_r_multiple >= 1 ? '#3fb950' : '#f78166'} />
          <JournalStat label="Total P&L"  value={`$${(stats.total_pnl||0).toFixed(0)}`} color={stats.total_pnl >= 0 ? '#3fb950' : '#f85149'} />
          <JournalStat label="Avg quality" value={`${stats.avg_quality_score}/10`} color="#58a6ff" />
        </div>
      )}

      {/* Playbook (Learnings) */}
      {(playbook.favor.length > 0 || playbook.avoid.length > 0) && (
        <div style={s.playbookBox}>
          <div style={s.playbookTitle}>📓 SYSTEM PLAYBOOK</div>
          <div style={s.playbookCols}>
            <div style={s.playbookCol}>
              <div style={s.playbookColHeader}>✓ PATTERNS THAT WORK</div>
              {playbook.favor.length ? playbook.favor.map(p => (
                <div key={p.pattern} style={s.patternRow}>
                  <span style={{ ...s.patternName, color: '#3fb950' }}>{p.pattern}</span>
                  <span style={s.patternMeta}>{p.win_rate}%  ·  {p.avg_r}R  ·  n={p.sample_size}</span>
                </div>
              )) : <div style={s.empty1}>None yet</div>}
            </div>
            <div style={s.playbookCol}>
              <div style={s.playbookColHeader}>✗ PATTERNS TO AVOID</div>
              {playbook.avoid.length ? playbook.avoid.map(p => (
                <div key={p.pattern} style={s.patternRow}>
                  <span style={{ ...s.patternName, color: '#f85149' }}>{p.pattern}</span>
                  <span style={s.patternMeta}>{p.win_rate}%  ·  {p.avg_r}R  ·  n={p.sample_size}</span>
                </div>
              )) : <div style={s.empty1}>None yet</div>}
            </div>
          </div>
          <div style={s.playbookFooter}>
            These patterns are injected into Scout + Research prompts.
            The system learns from every trade.
          </div>
        </div>
      )}

      {/* Backfill action */}
      {!hasData && (
        <div style={s.empty}>
          <div style={s.emptyIcon}>📔</div>
          <div style={{ fontWeight: 700, color: '#e6edf3' }}>No journal entries yet</div>
          <div style={{ color: '#8b949e', maxWidth: 320, textAlign: 'center', lineHeight: 1.6, fontSize: 12, marginTop: 4 }}>
            The Journal agent analyzes every closed trade — what worked, what failed, and what patterns are profitable.
            Insights feed back into Scout and Research prompts to make the system smarter.
          </div>
          <button style={s.backfillBtn} onClick={onBackfill}>
            📔 Analyze existing closed trades
          </button>
        </div>
      )}

      {/* Journal entries */}
      {entries.map(e => <JournalEntryCard key={e.id} entry={e} onSelectTicker={onSelectTicker} />)}
    </div>
  )
}

function JournalStat({ label, value, color }) {
  return (
    <div style={s.journalStatCard}>
      <div style={s.statLabel}>{label}</div>
      <div style={{ ...s.statValue, color: color || '#e6edf3', fontSize: 16 }}>{value}</div>
    </div>
  )
}

function JournalEntryCard({ entry, onSelectTicker }) {
  const [expanded, setExpanded] = useState(false)
  const outcomeColor = entry.outcome === 'WIN' ? '#3fb950' : entry.outcome === 'LOSS' ? '#f85149' : '#8b949e'
  const rColor = entry.r_multiple >= 1 ? '#3fb950' : entry.r_multiple >= 0 ? '#e3b341' : '#f85149'
  const qualityColor = entry.quality_score >= 7 ? '#3fb950' : entry.quality_score >= 5 ? '#e3b341' : '#f85149'
  const af = entry.analysis_full || {}

  return (
    <div style={s.journalCard}>
      <div style={s.cardHeader} onClick={() => setExpanded(e => !e)}>
        <div style={s.cardHeaderLeft}>
          <button style={s.tickerChip} onClick={(e) => { e.stopPropagation(); onSelectTicker?.(entry.ticker) }}>{entry.ticker}</button>
          <span style={{ ...s.outcomeChip, color: outcomeColor, background: outcomeColor + '22' }}>{entry.outcome}</span>
          <span style={{ ...s.rChip, color: rColor }}>{entry.r_multiple}R</span>
          <span style={{ fontSize: 11, color: '#8b949e' }}>${entry.pnl}</span>
        </div>
        <div style={s.cardHeaderRight}>
          <span style={{ ...s.qualityChip, color: qualityColor }}>quality {entry.quality_score}/10</span>
        </div>
      </div>

      {/* Pattern tags */}
      {entry.pattern_tags?.length > 0 && (
        <div style={s.tagRow}>
          {entry.pattern_tags.map(t => <span key={t} style={s.patternTag}>{t}</span>)}
        </div>
      )}

      {/* Key takeaway */}
      {af.key_takeaway && (
        <div style={s.takeaway}>💡 {af.key_takeaway}</div>
      )}

      {expanded && (
        <div style={s.journalDetail}>
          {entry.what_worked && (
            <div style={s.journalSection}>
              <div style={{ ...s.journalSectionHeader, color: '#3fb950' }}>✓ What worked</div>
              <div style={s.journalSectionBody}>{entry.what_worked}</div>
            </div>
          )}
          {entry.what_failed && (
            <div style={s.journalSection}>
              <div style={{ ...s.journalSectionHeader, color: '#f85149' }}>✗ What failed</div>
              <div style={s.journalSectionBody}>{entry.what_failed}</div>
            </div>
          )}
          {entry.lessons?.length > 0 && (
            <div style={s.journalSection}>
              <div style={{ ...s.journalSectionHeader, color: '#e3b341' }}>📓 Lessons</div>
              <ul style={s.lessonsList}>
                {entry.lessons.map((l, i) => <li key={i} style={s.lessonItem}>{l}</li>)}
              </ul>
            </div>
          )}
          <div style={s.journalMeta}>
            {af.thesis_validity && <span>Thesis: <strong>{af.thesis_validity}</strong></span>}
            {af.exit_timing && <span>Exit timing: <strong>{af.exit_timing}</strong></span>}
            <span>Held: <strong>{entry.days_held}d</strong></span>
          </div>
        </div>
      )}

      <button style={s.expandBtn} onClick={() => setExpanded(e => !e)}>
        {expanded ? '↑ Hide' : '↓ Full post-mortem'}
      </button>
    </div>
  )
}

function ActivityPanel({ activity }) {
  if (!activity.length) {
    return <div style={s.empty}>Waiting for events from the bus...</div>
  }
  return (
    <div style={s.list}>
      {activity.map((e, i) => <ActivityCard key={i} event={e} />)}
    </div>
  )
}

function ActivityCard({ event }) {
  const isPipeline = event.type === 'pipeline_complete'
  const isNewTrade = event.type === 'new_pending_trade'
  const impColor = IMP[event.impact] || '#8b949e'
  const actionColor = isPipeline ? (ACTION_COLOR[event.data?.pipeline?.final_action] || '#8b949e') : impColor

  if (isNewTrade) {
    return (
      <div style={{ ...s.activityCard, borderLeft: '3px solid #3fb950', background: '#3fb95011' }}>
        <div style={s.activityTop}>
          <span style={{ ...s.activityBadge, color: '#3fb950', background: '#3fb95022' }}>🤖 NEW TRADE</span>
          <span style={s.activityTime}>{new Date((event.ts || Date.now()/1000) * 1000).toLocaleTimeString()}</span>
        </div>
        <div style={s.activityTitle}>{event.title}</div>
        <div style={s.activityDesc}>{event.data?.thesis}</div>
      </div>
    )
  }

  return (
    <div style={{ ...s.activityCard, borderLeft: `3px solid ${actionColor}` }}>
      <div style={s.activityTop}>
        <span style={{ ...s.activityBadge, color: actionColor, background: actionColor + '22' }}>
          {event.source}/{event.type}
        </span>
        {event.impact && <span style={{ ...s.activityImpact, color: impColor }}>{event.impact}</span>}
        <span style={s.activityTime}>{new Date((event.ts || Date.now()/1000) * 1000).toLocaleTimeString()}</span>
      </div>
      <div style={s.activityTitle}>{event.title?.slice(0, 100)}</div>
      {event.tickers?.length > 0 && (
        <div style={s.tickerRow}>
          {event.tickers.slice(0, 5).map(t => <span key={t} style={s.tickerChipSmall}>{t}</span>)}
        </div>
      )}
    </div>
  )
}

function StatsPanel({ stats }) {
  if (!stats) return <div style={s.empty}>Loading stats...</div>
  return (
    <div style={s.statsWrap}>
      <div style={s.statsGrid}>
        <StatCard label="Events processed"  value={stats.events_total} />
        <StatCard label="Agent runs"        value={stats.agent_runs_total} />
        <StatCard label="Pending trades"    value={stats.pending_trades} color="#e3b341" />
        <StatCard label="Approved trades"   value={stats.approved_trades} color="#3fb950" />
        <StatCard label="Total AI cost"     value={`$${(stats.total_cost_usd || 0).toFixed(4)}`} color="#f78166" />
        <StatCard label="Mode"              value={stats.current_mode} color="#58a6ff" />
      </div>

      <div style={s.statsSection}>
        <div style={s.statsSectionTitle}>Per Agent</div>
        {Object.entries(stats.by_agent || {}).map(([agent, data]) => (
          <div key={agent} style={s.agentRow}>
            <div style={s.agentRowLeft}>
              <span style={s.agentRowName}>{agent}</span>
            </div>
            <div style={s.agentRowRight}>
              <span style={s.agentRowMetric}>{data.count} runs</span>
              <span style={s.agentRowMetric}>${data.cost_usd?.toFixed(4)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function StatCard({ label, value, color }) {
  return (
    <div style={s.statCard}>
      <div style={s.statLabel}>{label}</div>
      <div style={{ ...s.statValue, color: color || '#e6edf3' }}>{value}</div>
    </div>
  )
}

const s = {
  wrap: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0d1117' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '12px 16px', background: '#161b22', borderBottom: '1px solid #21262d', flexShrink: 0 },
  title: { fontWeight: 800, fontSize: 14, color: '#e6edf3' },
  subtitle: { fontSize: 11, color: '#8b949e', marginTop: 2 },
  headerRight: { display: 'flex', gap: 8 },
  modeSelect: { background: '#161b22', border: '1px solid #30363d', color: '#58a6ff', fontWeight: 700, fontSize: 11, padding: '6px 10px', borderRadius: 6, cursor: 'pointer' },
  tabs: { display: 'flex', gap: 2, padding: '6px 12px', background: '#161b22', borderBottom: '1px solid #21262d', flexShrink: 0 },
  tab: { background: 'none', border: 'none', color: '#8b949e', padding: '5px 10px', borderRadius: 5, cursor: 'pointer', fontSize: 12, fontWeight: 600 },
  tabActive: { background: '#1f6feb22', color: '#58a6ff' },
  body: { flex: 1, overflow: 'hidden', display: 'flex' },
  list: { flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 10 },
  monitorHeader: { display: 'flex', gap: 10, alignItems: 'center', fontSize: 11, color: '#e6edf3', padding: '6px 10px', background: '#161b22', borderRadius: 5 },

  // Journal styles
  journalStatsRow: { display: 'flex', gap: 6, marginBottom: 4 },
  journalStatCard: { flex: 1, background: '#161b22', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px' },

  playbookBox: { background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: 12, marginBottom: 4 },
  playbookTitle: { fontWeight: 800, fontSize: 11, color: '#e6edf3', marginBottom: 10, letterSpacing: 0.5 },
  playbookCols: { display: 'flex', gap: 12 },
  playbookCol: { flex: 1 },
  playbookColHeader: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 0.5, marginBottom: 5 },
  patternRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', fontSize: 11 },
  patternName: { fontWeight: 700 },
  patternMeta: { fontSize: 10, color: '#8b949e' },
  empty1: { fontSize: 11, color: '#8b949e' },
  playbookFooter: { fontSize: 10, color: '#8b949e', fontStyle: 'italic', marginTop: 10, borderTop: '1px solid #21262d', paddingTop: 8 },
  backfillBtn: { background: 'linear-gradient(135deg,#1f6feb,#388bfd)', border: 'none', color: '#fff', padding: '10px 22px', borderRadius: 7, fontWeight: 700, fontSize: 13, cursor: 'pointer', marginTop: 16 },

  journalCard: { background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: 12 },
  outcomeChip: { fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 4, letterSpacing: 0.5 },
  rChip: { fontSize: 12, fontWeight: 800 },
  qualityChip: { fontSize: 10, fontWeight: 700 },
  tagRow: { display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 },
  patternTag: { background: '#21262d', color: '#c9d1d9', fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3, letterSpacing: 0.3 },
  takeaway: { fontSize: 11, color: '#e3b341', marginTop: 8, fontStyle: 'italic', padding: '6px 8px', background: '#0d1117', borderRadius: 5 },
  journalDetail: { marginTop: 10, padding: 10, background: '#0d1117', borderRadius: 6, display: 'flex', flexDirection: 'column', gap: 10 },
  journalSection: {},
  journalSectionHeader: { fontSize: 10, fontWeight: 700, marginBottom: 3, letterSpacing: 0.3 },
  journalSectionBody: { fontSize: 11, color: '#c9d1d9', lineHeight: 1.6 },
  lessonsList: { paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 3 },
  lessonItem: { fontSize: 11, color: '#c9d1d9', lineHeight: 1.6 },
  journalMeta: { display: 'flex', gap: 14, fontSize: 10, color: '#8b949e', marginTop: 4, borderTop: '1px solid #21262d', paddingTop: 8 },
  empty: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, gap: 6, padding: 40, color: '#8b949e', fontSize: 12 },
  emptyIcon: { fontSize: 42, marginBottom: 8 },

  card: { background: '#161b22', border: '1px solid #21262d', borderRadius: 9, padding: 14 },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', marginBottom: 8 },
  cardHeaderLeft: { display: 'flex', gap: 8, alignItems: 'center' },
  cardHeaderRight: {},
  tickerChip: { background: '#1f6feb22', border: '1px solid #1f6feb44', color: '#58a6ff', fontWeight: 800, fontSize: 13, padding: '3px 9px', borderRadius: 5, cursor: 'pointer' },
  dirBadge: { fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 5 },
  confChip: { fontSize: 12, fontWeight: 800 },
  pendingChip: { background: '#e3b34122', color: '#e3b341', fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, letterSpacing: 0.5 },

  thesis: { fontSize: 12, color: '#c9d1d9', lineHeight: 1.6, marginBottom: 10, background: '#0d1117', padding: '8px 10px', borderRadius: 5 },

  priceGrid: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 5, marginBottom: 10 },
  priceBox: { padding: '6px 8px', borderRadius: 5 },
  priceLabel: { fontSize: 9, color: '#8b949e', fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase' },
  priceVal: { fontWeight: 700, fontSize: 12, marginTop: 2 },

  agentChain: { display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10, padding: 10, background: '#0d1117', borderRadius: 6 },
  stage: { borderBottom: '1px solid #21262d', paddingBottom: 6 },
  stageHeader: { fontWeight: 700, fontSize: 11, color: '#58a6ff', marginBottom: 4 },
  stageBody: { display: 'flex', flexDirection: 'column', gap: 2 },
  stageRow: { display: 'flex', gap: 6, fontSize: 11 },
  stageKey: { color: '#8b949e', minWidth: 100, fontWeight: 600 },
  stageVal: { color: '#c9d1d9', flex: 1, wordBreak: 'break-word' },

  actions: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginTop: 4 },
  actionsRight: { display: 'flex', gap: 6 },
  expandBtn: { background: 'none', border: 'none', color: '#8b949e', fontSize: 11, cursor: 'pointer' },
  rejectBtn: { background: '#21262d', border: '1px solid #30363d', color: '#f85149', padding: '7px 14px', borderRadius: 6, fontWeight: 700, fontSize: 12, cursor: 'pointer' },
  approveBtn: { background: 'linear-gradient(135deg,#1f6feb,#388bfd)', border: 'none', color: '#fff', padding: '7px 18px', borderRadius: 6, fontWeight: 700, fontSize: 12, cursor: 'pointer' },

  activityCard: { background: '#161b22', borderRadius: 7, padding: '8px 12px' },
  activityTop: { display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 },
  activityBadge: { fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, letterSpacing: 0.5 },
  activityImpact: { fontSize: 9, fontWeight: 700 },
  activityTime: { fontSize: 10, color: '#8b949e', marginLeft: 'auto' },
  activityTitle: { fontSize: 11, color: '#e6edf3', lineHeight: 1.5 },
  activityDesc: { fontSize: 11, color: '#8b949e', marginTop: 4, lineHeight: 1.5 },
  tickerRow: { display: 'flex', gap: 3, marginTop: 4 },
  tickerChipSmall: { background: '#1f6feb22', color: '#58a6ff', fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3 },

  statsWrap: { flex: 1, overflowY: 'auto', padding: 16 },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 20 },
  statCard: { background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: '12px 14px' },
  statLabel: { fontSize: 10, color: '#8b949e', fontWeight: 600, marginBottom: 6 },
  statValue: { fontSize: 20, fontWeight: 800 },

  statsSection: {},
  statsSectionTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, marginBottom: 8 },
  agentRow: { display: 'flex', justifyContent: 'space-between', padding: '8px 10px', background: '#161b22', borderRadius: 5, marginBottom: 3 },
  agentRowLeft: {},
  agentRowName: { fontWeight: 700, fontSize: 12, color: '#e6edf3', textTransform: 'capitalize' },
  agentRowRight: { display: 'flex', gap: 12 },
  agentRowMetric: { fontSize: 11, color: '#c9d1d9' },
}
