import { useState, useEffect, useRef } from 'react'
import axios from 'axios'

const BASE = 'http://localhost:8765'
const IMP = { CRITICAL: '#f85149', HIGH: '#f78166', MEDIUM: '#e3b341', LOW: '#8b949e' }
const DIR = { BULLISH: '#3fb950', BEARISH: '#f85149', NEUTRAL: '#e3b341' }

export default function EdgarPanel({ watchlistTickers = [], onSelectTicker }) {
  const [tab, setTab]               = useState('live')   // live | earnings | search
  const [filings, setFilings]       = useState([])
  const [earnings, setEarnings]     = useState([])
  const [searchTicker, setSearch]   = useState('')
  const [searchResults, setResults] = useState([])
  const [searching, setSearching]   = useState(false)
  const [summary, setSummary]       = useState(null)
  const [summarizing, setSumm]      = useState(false)
  const esRef = useRef(null)

  // ── SSE: live EDGAR feed ──────────────────────────────────────────────────
  useEffect(() => {
    const connect = () => {
      const es = new EventSource(`${BASE}/api/edgar/stream`)
      esRef.current = es
      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          if (event.type === 'edgar_8k' || event.type === 'edgar_form4') {
            setFilings(prev => {
              if (prev.some(f => f.data?.id === event.data?.id)) return prev
              return [event, ...prev].slice(0, 100)
            })
          }
        } catch {}
      }
      es.onerror = () => setTimeout(connect, 5000)
    }
    connect()
    return () => esRef.current?.close()
  }, [])

  // ── Earnings calendar ─────────────────────────────────────────────────────
  useEffect(() => {
    if (tab === 'earnings') loadEarnings()
  }, [tab])

  const loadEarnings = async () => {
    try {
      const r = await axios.get(`${BASE}/api/earnings/watchlist?days=14`)
      setEarnings(r.data.earnings || [])
    } catch {}
  }

  // ── Search ────────────────────────────────────────────────────────────────
  const runSearch = async (formType = '8-K') => {
    if (!searchTicker.trim()) return
    setSearching(true)
    setResults([])
    setSummary(null)
    try {
      const r = await axios.get(`${BASE}/api/edgar/search`, {
        params: { ticker: searchTicker.toUpperCase(), form_type: formType, limit: 8 }
      })
      setResults(r.data.results || [])
    } catch {}
    setSearching(false)
  }

  const readFiling = async (filing) => {
    setSumm(true)
    setSummary(null)
    try {
      const r = await axios.get(`${BASE}/api/edgar/summarize`, {
        params: {
          acc_no: filing.acc_no || filing.id,
          cik: filing.cik || '',
          form_type: filing.form_type,
          ticker: searchTicker.toUpperCase()
        },
        timeout: 60000
      })
      setSummary(r.data)
    } catch (e) {
      setSummary({ error: 'Could not read filing', ai: false })
    }
    setSumm(false)
  }

  return (
    <div style={s.wrap}>
      {/* Header */}
      <div style={s.header}>
        <div style={s.title}>📋 SEC EDGAR</div>
        <div style={s.tabs}>
          {[['live','Live Filings'],['earnings','Earnings'],['search','Search']].map(([k,l]) => (
            <button key={k} style={{ ...s.tabBtn, ...(tab === k ? s.tabActive : {}) }} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
      </div>

      {/* ── LIVE FEED ─────────────────────────────────────────────── */}
      {tab === 'live' && (
        <div style={s.feed}>
          {filings.length === 0 ? (
            <div style={s.empty}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>📡</div>
              <div style={{ fontWeight: 700, color: '#e6edf3', marginBottom: 6 }}>EDGAR Live Feed</div>
              <div style={{ color: '#8b949e', fontSize: 12, lineHeight: 1.6, maxWidth: 280, textAlign: 'center' }}>
                Polling SEC EDGAR every 60s for 8-K filings and Form 4 insider transactions.
                No API key required.
              </div>
            </div>
          ) : filings.map((event, i) => (
            <FilingCard key={i} event={event} onSelectTicker={onSelectTicker} onRead={readFiling} />
          ))}
        </div>
      )}

      {/* ── EARNINGS CALENDAR ─────────────────────────────────────── */}
      {tab === 'earnings' && (
        <div style={s.feed}>
          <div style={s.sectionHead}>
            <span>Upcoming Earnings — Next 14 Days</span>
            <button style={s.refreshBtn} onClick={loadEarnings}>↻</button>
          </div>
          {earnings.length === 0 ? (
            <div style={s.empty}>No upcoming earnings found for your watchlist.</div>
          ) : earnings.map((e, i) => (
            <EarningsRow key={i} earning={e} onSelectTicker={onSelectTicker} />
          ))}
        </div>
      )}

      {/* ── SEARCH ───────────────────────────────────────────────── */}
      {tab === 'search' && (
        <div style={s.feed}>
          <div style={s.searchRow}>
            <input
              style={s.searchInput}
              placeholder="Ticker (e.g. AAPL)"
              value={searchTicker}
              onChange={e => setSearch(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && runSearch('8-K')}
            />
            <button style={s.searchBtn} onClick={() => runSearch('8-K')} disabled={searching}>8-K</button>
            <button style={s.searchBtn} onClick={() => runSearch('4')}   disabled={searching}>Form 4</button>
            <button style={s.searchBtn} onClick={() => runSearch('10-Q')} disabled={searching}>10-Q</button>
          </div>

          {searching && <div style={s.empty}>Searching EDGAR...</div>}

          {searchResults.map((r, i) => (
            <div key={i} style={s.searchResult}>
              <div style={s.searchResultTop}>
                <span style={s.formBadge}>{r.form_type}</span>
                <span style={s.filed}>{r.filed}</span>
              </div>
              <div style={s.searchCompany}>{r.company}</div>
              {r.description && <div style={s.searchDesc}>{r.description}</div>}
              <div style={s.searchActions}>
                <a href={r.url} target="_blank" rel="noopener noreferrer" style={s.viewLink}>View on SEC →</a>
                <button style={s.readBtn} onClick={() => readFiling(r)}>🧠 AI Summary</button>
              </div>
            </div>
          ))}

          {/* AI Summary panel */}
          {summarizing && (
            <div style={s.summaryBox}>
              <div style={{ color: '#58a6ff' }}>Reading filing and generating AI summary...</div>
            </div>
          )}
          {summary && !summarizing && (
            <SummaryPanel summary={summary} />
          )}
        </div>
      )}
    </div>
  )
}

function FilingCard({ event, onSelectTicker, onRead }) {
  const { type, data, ts } = event
  const isForm4 = type === 'edgar_form4'
  const impColor = IMP[data.impact] || '#8b949e'
  const timeAgo = ts ? `${Math.floor((Date.now()/1000 - ts)/60)}m ago` : ''

  return (
    <div style={{ ...s.card, borderLeft: `3px solid ${impColor}` }}>
      <div style={s.cardTop}>
        <div style={s.cardLeft}>
          <span style={{ ...s.impBadge, color: impColor, background: impColor + '22' }}>{data.impact}</span>
          <span style={s.formTag}>{isForm4 ? 'Form 4' : '8-K'}</span>
          {data.keyword && <span style={s.keyword}>{data.keyword}</span>}
        </div>
        <span style={s.timeAgo}>{timeAgo}</span>
      </div>

      <div style={s.company}>{data.company}</div>

      {isForm4 ? (
        <div style={s.form4Detail}>
          <span style={{ color: data.buys > 0 ? '#3fb950' : '#f85149', fontWeight: 700 }}>
            {data.buys > 0 ? '▲ INSIDER BUY' : '▼ INSIDER SELL'}
          </span>
          <span style={s.insider}> · {data.insider} ({data.role})</span>
          <span style={s.value}> · ${(data.total_value / 1000).toFixed(0)}K</span>
          {data.ticker && (
            <button style={s.tickerChip} onClick={() => onSelectTicker?.(data.ticker)}>{data.ticker}</button>
          )}
        </div>
      ) : (
        <div style={s.filingTitle}>{data.title?.replace(/^\d{4}-\d{2}-\d{2} /, '')?.slice(0, 100)}</div>
      )}

      <div style={s.cardActions}>
        <a href={data.url} target="_blank" rel="noopener noreferrer" style={s.viewLink}>SEC →</a>
        {!isForm4 && <button style={s.readBtn} onClick={() => onRead(data)}>🧠 AI Summary</button>}
      </div>
    </div>
  )
}

function EarningsRow({ earning, onSelectTicker }) {
  const ticker = earning.ticker || earning.symbol || ''
  const date   = earning.date || earning.reportDate || ''
  const eps_est = earning.epsEstimate || earning.eps_estimate
  const time_of = earning.time || ''

  return (
    <div style={s.earningsRow}>
      <div style={s.earningsLeft}>
        <button style={s.tickerChip} onClick={() => onSelectTicker?.(ticker)}>{ticker}</button>
        <div style={{ fontSize: 11, color: '#8b949e' }}>{earning.name || ''}</div>
      </div>
      <div style={s.earningsRight}>
        <div style={s.earningsDate}>{date} {time_of && <span style={{ color: '#8b949e' }}>({time_of})</span>}</div>
        {eps_est && <div style={s.epsEst}>EPS est: <strong>${parseFloat(eps_est).toFixed(2)}</strong></div>}
        {earning.current_price && (
          <div style={{ ...s.priceChg, color: (earning.change_pct || 0) >= 0 ? '#3fb950' : '#f85149' }}>
            ${earning.current_price} {earning.change_pct != null ? `(${earning.change_pct > 0 ? '+' : ''}${earning.change_pct}%)` : ''}
          </div>
        )}
      </div>
    </div>
  )
}

function SummaryPanel({ summary }) {
  if (summary.error) return <div style={{ ...s.summaryBox, color: '#f85149' }}>{summary.error}</div>
  const s2 = summary.summary || {}
  const impColor = DIR[s2.impact] || '#e3b341'

  return (
    <div style={s.summaryBox}>
      <div style={s.summaryHeader}>
        <span style={s.aiLabel}>🧠 AI Summary</span>
        <span style={{ ...s.impBadge, color: impColor, background: impColor + '22' }}>{s2.impact}</span>
        {s2.action && <span style={{ ...s.formTag, color: s2.action === 'BUY' ? '#3fb950' : s2.action === 'SELL' ? '#f85149' : '#e3b341' }}>{s2.action}</span>}
      </div>
      <div style={s.headline}>{s2.headline}</div>
      {s2.key_points?.length > 0 && (
        <ul style={s.points}>
          {s2.key_points.map((p, i) => <li key={i} style={s.point}>{p}</li>)}
        </ul>
      )}
      {s2.numbers?.length > 0 && (
        <div style={s.numbers}>
          {s2.numbers.map((n, i) => <span key={i} style={s.numBadge}>{n}</span>)}
        </div>
      )}
      {s2.reasoning && <div style={s.reasoning}>{s2.reasoning}</div>}
    </div>
  )
}

const s = {
  wrap: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0d1117' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: '#161b22', borderBottom: '1px solid #21262d', flexShrink: 0 },
  title: { fontWeight: 800, fontSize: 14, color: '#e6edf3' },
  tabs: { display: 'flex', gap: 2 },
  tabBtn: { background: 'none', border: 'none', color: '#8b949e', padding: '5px 10px', borderRadius: 5, cursor: 'pointer', fontSize: 12, fontWeight: 600 },
  tabActive: { background: '#1f6feb22', color: '#58a6ff' },
  feed: { flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 },
  empty: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, color: '#8b949e', fontSize: 12, padding: 32 },
  sectionHead: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, fontWeight: 700, color: '#8b949e', letterSpacing: 0.5, marginBottom: 4 },
  refreshBtn: { background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 14 },

  card: { background: '#161b22', borderRadius: 7, padding: '10px 12px', border: '1px solid #21262d' },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 },
  cardLeft: { display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' },
  impBadge: { fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, letterSpacing: 0.5 },
  formTag: { fontSize: 10, color: '#8b949e', background: '#21262d', padding: '2px 6px', borderRadius: 4, fontWeight: 700 },
  keyword: { fontSize: 10, color: '#e3b341' },
  timeAgo: { fontSize: 10, color: '#8b949e' },
  company: { fontWeight: 700, fontSize: 12, color: '#e6edf3', marginBottom: 4 },
  filingTitle: { fontSize: 11, color: '#c9d1d9', lineHeight: 1.5, marginBottom: 6 },
  form4Detail: { fontSize: 11, lineHeight: 1.8, marginBottom: 6 },
  insider: { color: '#c9d1d9' },
  value: { color: '#e3b341', fontWeight: 700 },
  cardActions: { display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 },
  viewLink: { fontSize: 10, color: '#8b949e', textDecoration: 'none' },
  readBtn: { background: '#1f6feb22', border: '1px solid #1f6feb44', color: '#58a6ff', fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 4, cursor: 'pointer' },
  tickerChip: { background: '#1f6feb22', border: '1px solid #1f6feb44', color: '#58a6ff', fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4, cursor: 'pointer', marginLeft: 4 },

  earningsRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#161b22', borderRadius: 7, padding: '10px 12px', border: '1px solid #21262d' },
  earningsLeft: { display: 'flex', gap: 8, alignItems: 'center' },
  earningsRight: { textAlign: 'right' },
  earningsDate: { fontSize: 12, fontWeight: 700, color: '#e6edf3' },
  epsEst: { fontSize: 11, color: '#8b949e', marginTop: 2 },
  priceChg: { fontSize: 11, fontWeight: 700, marginTop: 2 },

  searchRow: { display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' },
  searchInput: { flex: 1, minWidth: 100, background: '#161b22', border: '1px solid #30363d', borderRadius: 6, padding: '7px 10px', color: '#e6edf3', outline: 'none', fontSize: 13 },
  searchBtn: { background: '#21262d', border: 'none', color: '#e6edf3', padding: '7px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 700 },
  searchResult: { background: '#161b22', border: '1px solid #21262d', borderRadius: 7, padding: 12, display: 'flex', flexDirection: 'column', gap: 5 },
  searchResultTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  filed: { fontSize: 11, color: '#8b949e' },
  searchCompany: { fontWeight: 700, fontSize: 12, color: '#e6edf3' },
  searchDesc: { fontSize: 11, color: '#8b949e', lineHeight: 1.5 },
  searchActions: { display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 },

  summaryBox: { background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: 14, marginTop: 8 },
  summaryHeader: { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 },
  aiLabel: { fontWeight: 800, fontSize: 12, color: '#e6edf3' },
  headline: { fontSize: 13, fontWeight: 600, color: '#e6edf3', lineHeight: 1.6, marginBottom: 10 },
  points: { paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 10 },
  point: { fontSize: 12, color: '#c9d1d9', lineHeight: 1.5 },
  numbers: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 },
  numBadge: { background: '#21262d', color: '#e3b341', fontSize: 11, fontWeight: 600, padding: '3px 8px', borderRadius: 5 },
  reasoning: { fontSize: 12, color: '#8b949e', lineHeight: 1.6, fontStyle: 'italic', borderTop: '1px solid #21262d', paddingTop: 10, marginTop: 4 },
}
