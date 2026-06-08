import { useEffect, useRef, useState } from 'react'

const IMPACT_COLOR = {
  CRITICAL: '#f85149',
  HIGH:     '#f78166',
  MEDIUM:   '#e3b341',
  LOW:      '#8b949e',
}

const ACTION_COLOR = {
  BUY:    '#3fb950',
  SELL:   '#f85149',
  WATCH:  '#e3b341',
  IGNORE: '#8b949e',
}

const URGENCY_COLOR = {
  IMMEDIATE:  '#f85149',
  TODAY:      '#f78166',
  THIS_WEEK:  '#e3b341',
  LOW:        '#8b949e',
}

export default function AlertPanel({ onSelectTicker }) {
  const [alerts, setAlerts] = useState([])
  const [connected, setConnected] = useState(false)
  const [filter, setFilter] = useState('ALL') // ALL | CRITICAL | HIGH | WATCHLIST
  const [stats, setStats] = useState({ total: 0, critical: 0, high: 0 })
  const esRef = useRef(null)
  const audioRef = useRef(null)

  useEffect(() => {
    // Load existing articles immediately via REST
    fetch('/api/feed/latest?limit=50&min_score=1')
      .then(r => r.json())
      .then(d => {
        const arts = d.articles || []
        if (arts.length) {
          setAlerts(arts)
          const critical = arts.filter(a => a.impact === 'CRITICAL').length
          const high = arts.filter(a => a.impact === 'HIGH').length
          setStats({ total: arts.length, critical, high })
        }
      })
      .catch(() => {})

    connect()
    return () => esRef.current?.close()
  }, [])

  const connect = () => {
    if (esRef.current) esRef.current.close()

    const es = new EventSource('/api/feed/stream')
    esRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => { setConnected(false); setTimeout(connect, 5000) }

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        if (event.type === 'news') {
          const article = event.data
          setAlerts(prev => {
            // deduplicate
            if (prev.some(a => a.id === article.id)) return prev
            const next = [article, ...prev].slice(0, 100)
            return next
          })
          setStats(prev => ({
            total: prev.total + 1,
            critical: prev.critical + (article.impact === 'CRITICAL' ? 1 : 0),
            high: prev.high + (article.impact === 'HIGH' ? 1 : 0),
          }))
          // Flash notification for high-impact
          if (article.impact === 'CRITICAL' || article.impact === 'HIGH') {
            if (Notification.permission === 'granted') {
              new Notification(`TradeDesk Alert — ${article.impact}`, {
                body: article.ai_summary || article.title,
                icon: '/favicon.svg',
              })
            }
          }
        }
      } catch (err) {}
    }
  }

  const filtered = alerts.filter(a => {
    if (filter === 'CRITICAL') return a.impact === 'CRITICAL'
    if (filter === 'HIGH') return ['CRITICAL', 'HIGH'].includes(a.impact)
    if (filter === 'ACTIONABLE') return a.ai_action && ['BUY', 'SELL'].includes(a.ai_action)
    return true
  })

  const requestNotifications = () => {
    if (Notification.permission !== 'granted') Notification.requestPermission()
  }

  return (
    <div style={s.panel}>
      {/* Header */}
      <div style={s.header}>
        <div style={s.headerLeft}>
          <div style={s.title}>
            <span style={{ ...s.dot, background: connected ? '#3fb950' : '#f85149', boxShadow: connected ? '0 0 6px #3fb950' : 'none' }} />
            Live Feed
          </div>
          <div style={s.statsRow}>
            <span style={s.stat}>{stats.total} alerts</span>
            {stats.critical > 0 && <span style={{ ...s.stat, color: '#f85149' }}>⚡ {stats.critical} critical</span>}
            {stats.high > 0 && <span style={{ ...s.stat, color: '#f78166' }}>↑ {stats.high} high</span>}
          </div>
        </div>
        <button style={s.notifBtn} onClick={requestNotifications} title="Enable desktop notifications">🔔</button>
      </div>

      {/* Filter tabs */}
      <div style={s.filterRow}>
        {['ALL', 'CRITICAL', 'HIGH', 'ACTIONABLE'].map(f => (
          <button key={f} style={{ ...s.filterBtn, ...(filter === f ? s.filterBtnActive : {}) }} onClick={() => setFilter(f)}>
            {f}
          </button>
        ))}
      </div>

      {/* Feed */}
      <div style={s.feed}>
        {!connected && alerts.length === 0 && (
          <div style={s.empty}>
            <div style={s.emptyIcon}>📡</div>
            {connected ? 'Waiting for alerts...' : 'Connecting to Benzinga feed...'}
            <div style={s.emptyHint}>Add your Benzinga API key in ⚙ Settings to activate the live feed</div>
          </div>
        )}

        {filtered.map(alert => (
          <AlertCard key={alert.id} alert={alert} onSelectTicker={onSelectTicker} />
        ))}

        {filtered.length === 0 && alerts.length > 0 && (
          <div style={s.empty}>No {filter.toLowerCase()} alerts yet</div>
        )}
      </div>
    </div>
  )
}

function AlertCard({ alert, onSelectTicker }) {
  const [expanded, setExpanded] = useState(alert.impact === 'CRITICAL')
  const impactColor = IMPACT_COLOR[alert.impact] || '#8b949e'
  const aiScore = alert.ai_score || alert.score
  const scoreColor = aiScore >= 8 ? '#f85149' : aiScore >= 6 ? '#e3b341' : '#8b949e'

  const timeAgo = (ts) => {
    const d = new Date(ts * 1000 || ts)
    const diff = Math.floor((Date.now() - d.getTime()) / 1000)
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div
      style={{ ...s.card, borderLeft: `3px solid ${impactColor}`, ...(alert.impact === 'CRITICAL' ? s.cardCritical : {}) }}
      onClick={() => setExpanded(e => !e)}
    >
      {/* Top row */}
      <div style={s.cardTop}>
        <div style={s.cardLeft}>
          <span style={{ ...s.impactBadge, background: impactColor + '22', color: impactColor }}>
            {alert.impact}
          </span>
          {alert.ai_action && alert.ai_action !== 'IGNORE' && (
            <span style={{ ...s.actionBadge, color: ACTION_COLOR[alert.ai_action] || '#8b949e' }}>
              {alert.ai_action}
            </span>
          )}
          {alert.ai_urgency && alert.ai_urgency !== 'LOW' && (
            <span style={{ ...s.urgencyBadge, color: URGENCY_COLOR[alert.ai_urgency] }}>
              {alert.ai_urgency}
            </span>
          )}
        </div>
        <div style={s.cardRight}>
          {aiScore && <span style={{ ...s.scoreBadge, color: scoreColor }}>{aiScore}/10</span>}
          <span style={s.timeAgo}>{timeAgo(alert.ts || alert.published)}</span>
        </div>
      </div>

      {/* Title */}
      <div style={s.cardTitle}>{alert.title}</div>

      {/* Tickers */}
      {alert.tickers?.length > 0 && (
        <div style={s.tickerRow}>
          {alert.tickers.slice(0, 5).map(t => (
            <button key={t} style={s.tickerChip} onClick={(e) => { e.stopPropagation(); onSelectTicker?.(t) }}>
              {t}
            </button>
          ))}
        </div>
      )}

      {/* AI Summary */}
      {alert.ai_summary && (
        <div style={s.aiSummary}>
          🧠 {alert.ai_summary}
        </div>
      )}

      {/* Expanded body */}
      {expanded && alert.body && (
        <div style={s.cardBody}>{alert.body.substring(0, 300)}...</div>
      )}

      {/* Why it moves */}
      {expanded && alert.ai_why && (
        <div style={s.aiWhy}>📈 {alert.ai_why}</div>
      )}

      {/* Actions */}
      {expanded && (
        <div style={s.cardActions}>
          {alert.tickers?.slice(0, 3).map(t => (
            <button key={t} style={s.analyzeBtn} onClick={(e) => { e.stopPropagation(); onSelectTicker?.(t) }}>
              Analyze {t} →
            </button>
          ))}
          {alert.url && (
            <a href={alert.url} target="_blank" rel="noopener noreferrer" style={s.sourceLink} onClick={e => e.stopPropagation()}>
              {alert.source} ↗
            </a>
          )}
        </div>
      )}
    </div>
  )
}

const s = {
  panel: { display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117', overflow: 'hidden' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '12px 14px 8px', borderBottom: '1px solid #21262d', flexShrink: 0 },
  headerLeft: {},
  title: { display: 'flex', alignItems: 'center', gap: 7, fontWeight: 800, fontSize: 13, color: '#e6edf3', marginBottom: 4 },
  dot: { width: 8, height: 8, borderRadius: '50%', display: 'inline-block', transition: 'all .3s' },
  statsRow: { display: 'flex', gap: 10 },
  stat: { fontSize: 10, color: '#8b949e', fontWeight: 600 },
  notifBtn: { background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: '#8b949e' },
  filterRow: { display: 'flex', gap: 2, padding: '6px 10px', borderBottom: '1px solid #21262d', flexShrink: 0 },
  filterBtn: { background: 'none', border: 'none', color: '#8b949e', padding: '3px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 10, fontWeight: 700, letterSpacing: 0.5 },
  filterBtnActive: { background: '#21262d', color: '#e6edf3' },
  feed: { flex: 1, overflowY: 'auto', padding: 8, display: 'flex', flexDirection: 'column', gap: 6 },
  empty: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, padding: 32, color: '#8b949e', fontSize: 12, textAlign: 'center' },
  emptyIcon: { fontSize: 32 },
  emptyHint: { fontSize: 11, color: '#8b949e', maxWidth: 200, lineHeight: 1.5 },

  card: { background: '#161b22', border: '1px solid #21262d', borderRadius: 7, padding: '10px 12px', cursor: 'pointer', transition: 'border-color .15s' },
  cardCritical: { background: '#1a0f0f', borderColor: '#f8514944' },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  cardLeft: { display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' },
  cardRight: { display: 'flex', gap: 8, alignItems: 'center' },
  impactBadge: { fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, letterSpacing: 0.5 },
  actionBadge: { fontSize: 10, fontWeight: 800 },
  urgencyBadge: { fontSize: 9, fontWeight: 700 },
  scoreBadge: { fontSize: 11, fontWeight: 800 },
  timeAgo: { fontSize: 10, color: '#8b949e' },
  cardTitle: { fontSize: 12, fontWeight: 600, color: '#e6edf3', lineHeight: 1.5, marginBottom: 5 },
  tickerRow: { display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 5 },
  tickerChip: { background: '#1f6feb22', border: '1px solid #1f6feb44', color: '#58a6ff', fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, cursor: 'pointer' },
  aiSummary: { fontSize: 11, color: '#c9d1d9', background: '#0d1117', borderRadius: 4, padding: '5px 8px', marginBottom: 4, lineHeight: 1.5 },
  cardBody: { fontSize: 11, color: '#8b949e', lineHeight: 1.6, marginTop: 5 },
  aiWhy: { fontSize: 11, color: '#3fb950', marginTop: 5, lineHeight: 1.5 },
  cardActions: { display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' },
  analyzeBtn: { background: '#1f6feb', border: 'none', color: '#fff', fontSize: 10, fontWeight: 700, padding: '4px 10px', borderRadius: 4, cursor: 'pointer' },
  sourceLink: { fontSize: 10, color: '#8b949e', textDecoration: 'none', marginLeft: 'auto' },
}
