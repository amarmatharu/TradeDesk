import { useState, useEffect } from 'react'
import axios from 'axios'

const CONV_COLOR  = { HIGH: '#3fb950', MEDIUM: '#e3b341', LOW: '#8b949e' }
const DIR_COLOR   = { LONG: '#3fb950', SHORT: '#f85149' }
const URG_COLOR   = { TODAY: '#f85149', TOMORROW: '#f78166', THIS_WEEK: '#e3b341' }
const IMP_COLOR   = { CRITICAL: '#f85149', HIGH: '#f78166', MEDIUM: '#e3b341', LOW: '#8b949e' }
const MEDALS      = ['🥇', '🥈', '🥉']

export default function ScannerPanel({ onTrade, onSelectTicker }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [lastRun, setLastRun] = useState(null)

  // Auto-load latest scan on mount + every 60s refresh
  useEffect(() => {
    loadLatestScan()
    const interval = setInterval(loadLatestScan, 60000)
    return () => clearInterval(interval)
  }, [])

  const loadLatestScan = async () => {
    try {
      const r = await axios.get('http://localhost:8765/api/scan/latest', { timeout: 5000 })
      if (r.data && r.data.scanned_at) {
        // Convert auto-scanner shape to scanner shape
        setData({
          setups: r.data.setups || [],
          market_regime: r.data.market_regime || '',
          catalysts: r.data.catalysts || [],
          market: r.data.market || {},
        })
        setLastRun(new Date(r.data.scanned_at + 'Z'))
      }
    } catch {}
  }

  const runScan = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await axios.get('http://localhost:8765/api/scan', { timeout: 60000 })
      setData(r.data)
      setLastRun(new Date())
    } catch (e) {
      setError(e.response?.data?.detail || 'Scan failed — is the backend running?')
    }
    setLoading(false)
  }

  if (loading) return <LoadingScreen />

  if (!data) return (
    <EmptyAutoState onScan={runScan} />
  )

  const { setups = [], market = {}, catalysts = [], market_regime } = data

  return (
    <div style={s.wrap}>
      {/* Header */}
      <div style={s.header}>
        <div style={s.headerLeft}>
          <div style={s.headerTitle}>
            🎯 AI Scanner
            <span style={{ fontSize: 9, fontWeight: 800, background: '#3fb95022', color: '#3fb950', padding: '2px 6px', borderRadius: 4, marginLeft: 8, letterSpacing: 0.5 }}>AUTO</span>
          </div>
          {lastRun && <div style={s.lastRun}>Last scan: {lastRun.toLocaleTimeString()} · auto-refreshes every 30 min</div>}
        </div>
        <button style={s.scanBtn} onClick={runScan}>⟳ Re-scan</button>
      </div>

      {/* Market regime */}
      {market_regime && (
        <div style={s.regimeBanner}>
          <span style={s.regimeIcon}>📊</span>
          {market_regime}
        </div>
      )}

      <div style={s.body}>
        {/* Left: Setups */}
        <div style={s.setupsCol}>
          <div style={s.colTitle}>TRADE SETUPS ({setups.length})</div>

          {setups.length === 0 && (
            <div style={s.noSetups}>No high-conviction setups found right now. Market conditions may not be favorable.</div>
          )}

          {setups.map((setup, i) => (
            <SetupCard
              key={setup.ticker + i}
              setup={setup}
              medal={MEDALS[i]}
              onTrade={onTrade}
              onSelectTicker={onSelectTicker}
            />
          ))}
        </div>

        {/* Right: Market + Catalysts */}
        <div style={s.sideCol}>
          {/* Market Overview */}
          <div style={s.sideSection}>
            <div style={s.colTitle}>MARKET</div>
            {Object.entries(market).map(([sym, d]) => {
              const chg = d.change_pct || 0
              const up  = chg >= 0
              return (
                <div key={sym} style={s.marketRow}>
                  <div>
                    <div style={s.marketSym}>{sym}</div>
                    <div style={s.marketName}>{d.name}</div>
                  </div>
                  <div style={s.marketRight}>
                    <div style={s.marketPrice}>${d.price?.toLocaleString()}</div>
                    <div style={{ ...s.marketChg, color: up ? '#3fb950' : '#f85149' }}>
                      {up ? '▲' : '▼'} {Math.abs(chg)}%
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Benzinga Catalysts */}
          {catalysts.length > 0 && (
            <div style={s.sideSection}>
              <div style={s.colTitle}>CATALYSTS ({catalysts.length})</div>
              {catalysts.map((c, i) => (
                <div key={i} style={{ ...s.catalystCard, borderLeft: `3px solid ${IMP_COLOR[c.impact] || '#8b949e'}` }}>
                  <div style={s.catalystTop}>
                    <span style={{ ...s.impactBadge, color: IMP_COLOR[c.impact], background: IMP_COLOR[c.impact] + '22' }}>
                      {c.impact}
                    </span>
                    <span style={s.catalystTime}>{c.time?.slice(11,16)}</span>
                  </div>
                  <div style={s.catalystTitle}>{c.title.slice(0, 90)}{c.title.length > 90 ? '…' : ''}</div>
                  <div style={s.catalystTickers}>
                    {c.tickers?.slice(0, 5).map(t => (
                      <button key={t} style={s.tickerChip} onClick={() => onSelectTicker?.(t)}>{t}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SetupCard({ setup, medal, onTrade, onSelectTicker }) {
  const [expanded, setExpanded] = useState(true)
  const rr   = setup.risk_reward
  const rrOk = rr >= 2

  return (
    <div style={s.setupCard}>
      {/* Card header */}
      <div style={s.setupHeader} onClick={() => setExpanded(e => !e)}>
        <div style={s.setupHeaderLeft}>
          <span style={s.medal}>{medal}</span>
          <span style={s.setupTicker}>{setup.ticker}</span>
          <span style={{ ...s.dirBadge, background: DIR_COLOR[setup.direction] + '22', color: DIR_COLOR[setup.direction] }}>
            {setup.direction === 'LONG' ? '▲ LONG' : '▼ SHORT'}
          </span>
          <span style={{ ...s.convBadge, color: CONV_COLOR[setup.conviction] }}>
            {setup.conviction}
          </span>
        </div>
        <div style={s.setupHeaderRight}>
          <div style={s.scoreCircle}>{setup.score}<span style={s.scoreMax}>/10</span></div>
          <span style={{ ...s.urgBadge, color: URG_COLOR[setup.urgency] }}>{setup.urgency}</span>
          <span style={s.expandIcon}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Catalyst line */}
      <div style={s.catalystLine}>⚡ {setup.catalyst}</div>

      {expanded && (
        <>
          {/* Thesis */}
          <div style={s.thesis}>{setup.thesis}</div>

          {/* Price grid */}
          <div style={s.priceGrid}>
            <PriceBox label="Entry"    value={`$${setup.entry}`}    highlight />
            <PriceBox label="Stop"     value={`$${setup.stop}`}     color="#f85149" />
            <PriceBox label="Target 1" value={`$${setup.target1}`}  color="#3fb950" />
            <PriceBox label="Target 2" value={`$${setup.target2}`}  color="#3fb950" />
            <PriceBox label="R:R"      value={`${rr}:1`}            color={rrOk ? '#3fb950' : '#f85149'} highlight />
            <PriceBox label="Horizon"  value={setup.time_horizon} />
            <PriceBox label="Shares"   value={setup.shares} />
            <PriceBox label="Risk"     value={`$${setup.risk_dollars}`} color="#f78166" />
            <PriceBox label="Position" value={`$${setup.position_value?.toLocaleString()}`} />
          </div>

          {/* Entry trigger */}
          <div style={s.triggerBox}>
            <span style={s.triggerLabel}>ENTER WHEN: </span>
            {setup.entry_trigger}
          </div>

          {/* Invalidation */}
          <div style={s.invalidBox}>
            <span style={s.invalidLabel}>KILL IF: </span>
            {setup.invalidation}
          </div>

          {/* Actions */}
          <div style={s.cardActions}>
            <button style={s.analyzeBtn} onClick={() => onSelectTicker?.(setup.ticker)}>
              View Chart →
            </button>
            <button style={s.enterBtn} onClick={() => onTrade?.({
              ticker: setup.ticker,
              analysis: {
                entry_price: setup.entry,
                stop_loss: setup.stop,
                target1: setup.target1,
                target2: setup.target2,
                position_size_shares: setup.shares,
                strategy: setup.catalyst?.slice(0, 50),
              }
            })}>
              Enter Trade
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function PriceBox({ label, value, color, highlight }) {
  return (
    <div style={{ ...s.priceBox, background: highlight ? '#1f6feb11' : '#0d1117' }}>
      <div style={s.priceBoxLabel}>{label}</div>
      <div style={{ ...s.priceBoxVal, color: color || '#e6edf3' }}>{value}</div>
    </div>
  )
}

function EmptyState({ onScan }) {
  return (
    <div style={s.empty}>
      <div style={s.emptyIcon}>🎯</div>
      <div style={s.emptyTitle}>AI Trade Scanner</div>
      <div style={s.emptyDesc}>
        Pulls live Benzinga catalysts + Alpaca prices + market conditions,
        then surfaces the top trade setups with entry, stop, target and risk sizing.
      </div>
      <button style={s.emptyBtn} onClick={onScan}>Run Scanner</button>
    </div>
  )
}

function EmptyAutoState({ onScan }) {
  return (
    <div style={s.empty}>
      <div style={s.emptyIcon}>⚡</div>
      <div style={s.emptyTitle}>Auto-Scanner Active</div>
      <div style={s.emptyDesc}>
        Scanner runs automatically every 30 minutes during market hours.
        Setups will appear here as soon as the first scan completes.
        <br/><br/>
        <strong>Schedule:</strong> 9:30am · 10am · 12pm · 3pm · 4pm ET<br/>
        Currently outside market hours? Click below to force a scan now.
      </div>
      <button style={s.emptyBtn} onClick={onScan}>Force Scan Now</button>
    </div>
  )
}

function LoadingScreen() {
  const [step, setStep] = useState(0)
  const steps = ['Pulling Benzinga catalysts...', 'Fetching live prices...', 'Calculating technicals...', 'Running AI synthesis...']
  useEffect(() => {
    const t = setInterval(() => setStep(s => (s + 1) % steps.length), 1200)
    return () => clearInterval(t)
  }, [])
  return (
    <div style={s.empty}>
      <div style={{ fontSize: 36, marginBottom: 16 }}>⚡</div>
      <div style={s.emptyTitle}>Scanning markets...</div>
      <div style={{ color: '#58a6ff', fontSize: 13, marginTop: 8 }}>{steps[step]}</div>
      <div style={s.progressBar}><div style={s.progressFill} /></div>
    </div>
  )
}

const s = {
  wrap: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0d1117' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: '#161b22', borderBottom: '1px solid #21262d', flexShrink: 0 },
  headerLeft: {},
  headerTitle: { fontWeight: 800, fontSize: 15, color: '#e6edf3' },
  lastRun: { fontSize: 11, color: '#8b949e', marginTop: 2 },
  scanBtn: { background: 'linear-gradient(135deg,#1f6feb,#388bfd)', border: 'none', color: '#fff', padding: '8px 20px', borderRadius: 7, cursor: 'pointer', fontWeight: 700, fontSize: 13 },
  regimeBanner: { padding: '10px 16px', background: '#161b22', borderBottom: '1px solid #21262d', fontSize: 12, color: '#c9d1d9', display: 'flex', gap: 8, alignItems: 'flex-start', flexShrink: 0 },
  regimeIcon: { flexShrink: 0 },
  body: { display: 'flex', flex: 1, overflow: 'hidden' },
  setupsCol: { flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12, borderRight: '1px solid #21262d' },
  sideCol: { width: 260, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 16, flexShrink: 0 },
  colTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, marginBottom: 10 },
  noSetups: { color: '#8b949e', fontSize: 13, padding: 20, background: '#161b22', borderRadius: 8, textAlign: 'center', lineHeight: 1.6 },

  setupCard: { background: '#161b22', border: '1px solid #21262d', borderRadius: 10, overflow: 'hidden' },
  setupHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 14px', cursor: 'pointer', borderBottom: '1px solid #21262d' },
  setupHeaderLeft: { display: 'flex', alignItems: 'center', gap: 8 },
  setupHeaderRight: { display: 'flex', alignItems: 'center', gap: 8 },
  medal: { fontSize: 18 },
  setupTicker: { fontWeight: 800, fontSize: 16, color: '#e6edf3' },
  dirBadge: { fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 5 },
  convBadge: { fontSize: 11, fontWeight: 700 },
  scoreCircle: { fontWeight: 800, fontSize: 18, color: '#e6edf3', lineHeight: 1 },
  scoreMax: { fontSize: 11, color: '#8b949e', fontWeight: 400 },
  urgBadge: { fontSize: 10, fontWeight: 700 },
  expandIcon: { fontSize: 10, color: '#8b949e', marginLeft: 4 },
  catalystLine: { padding: '8px 14px', fontSize: 12, color: '#e3b341', background: '#e3b34108', borderBottom: '1px solid #21262d' },
  thesis: { padding: '10px 14px', fontSize: 12, color: '#c9d1d9', lineHeight: 1.7, borderBottom: '1px solid #21262d' },
  priceGrid: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, padding: '8px 14px', borderBottom: '1px solid #21262d' },
  priceBox: { padding: '7px 8px', borderRadius: 5 },
  priceBoxLabel: { fontSize: 9, color: '#8b949e', fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase' },
  priceBoxVal: { fontWeight: 700, fontSize: 13, marginTop: 3 },
  triggerBox: { padding: '8px 14px', fontSize: 11, color: '#c9d1d9', borderBottom: '1px solid #21262d', lineHeight: 1.5 },
  triggerLabel: { fontWeight: 700, color: '#3fb950' },
  invalidBox: { padding: '8px 14px', fontSize: 11, color: '#c9d1d9', borderBottom: '1px solid #21262d', lineHeight: 1.5 },
  invalidLabel: { fontWeight: 700, color: '#f85149' },
  cardActions: { display: 'flex', gap: 8, padding: '10px 14px' },
  analyzeBtn: { background: '#21262d', border: 'none', color: '#e6edf3', padding: '8px 14px', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 600 },
  enterBtn: { background: 'linear-gradient(135deg,#1f6feb,#388bfd)', border: 'none', color: '#fff', padding: '8px 18px', borderRadius: 6, cursor: 'pointer', fontSize: 12, fontWeight: 700 },

  sideSection: {},
  marketRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 4px', borderBottom: '1px solid #21262d' },
  marketSym: { fontWeight: 700, fontSize: 12, color: '#e6edf3' },
  marketName: { fontSize: 10, color: '#8b949e' },
  marketRight: { textAlign: 'right' },
  marketPrice: { fontSize: 12, fontWeight: 600, color: '#e6edf3' },
  marketChg: { fontSize: 11, fontWeight: 700 },
  catalystCard: { background: '#0d1117', borderRadius: 6, padding: '8px 10px', marginBottom: 6 },
  catalystTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  impactBadge: { fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, letterSpacing: 0.5 },
  catalystTime: { fontSize: 10, color: '#8b949e' },
  catalystTitle: { fontSize: 11, color: '#c9d1d9', lineHeight: 1.5, marginBottom: 5 },
  catalystTickers: { display: 'flex', gap: 3, flexWrap: 'wrap' },
  tickerChip: { background: '#1f6feb22', border: '1px solid #1f6feb44', color: '#58a6ff', fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3, cursor: 'pointer' },

  empty: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, gap: 14, padding: 48 },
  emptyIcon: { fontSize: 52 },
  emptyTitle: { fontSize: 20, fontWeight: 800, color: '#e6edf3' },
  emptyDesc: { fontSize: 13, color: '#8b949e', textAlign: 'center', maxWidth: 420, lineHeight: 1.7 },
  emptyBtn: { background: 'linear-gradient(135deg,#1f6feb,#388bfd)', border: 'none', color: '#fff', padding: '13px 36px', borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: 14 },
  progressBar: { width: 200, height: 3, background: '#21262d', borderRadius: 2, marginTop: 16, overflow: 'hidden' },
  progressFill: { height: '100%', width: '60%', background: '#388bfd', borderRadius: 2, animation: 'slide 1.5s infinite' },
}
