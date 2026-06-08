import { useState, useEffect } from 'react'
import { analyzeStock } from '../api.js'

export default function AnalysisPanel({ ticker, onTrade }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setData(null)
    setError(null)
  }, [ticker])

  const runAnalysis = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await analyzeStock(ticker)
      setData(result)
    } catch (e) {
      setError('Failed to fetch analysis. Is the backend running?')
    }
    setLoading(false)
  }

  if (loading) return <LoadingScreen ticker={ticker} />
  if (!data) return <EmptyState ticker={ticker} onAnalyze={runAnalysis} />
  if (error) return <div style={s.error}>{error}</div>

  const { info, technicals, analysis, sentiment } = data

  return (
    <div style={s.wrap}>
      {/* AI Verdict Banner */}
      {analysis && !analysis.error && (
        <div style={{ ...s.verdict, borderLeft: `4px solid ${actionColor(analysis.action)}` }}>
          <div style={s.verdictLeft}>
            <span style={{ ...s.actionBadge, background: actionColor(analysis.action) }}>{analysis.action}</span>
            <span style={{ ...s.convictionBadge, color: convictionColor(analysis.conviction) }}>{analysis.conviction} CONVICTION</span>
            <span style={s.strategyLabel}>{analysis.strategy}</span>
          </div>
          <div style={s.scores}>
            <Score label="Overall" value={analysis.overall_score} />
            <Score label="Technical" value={analysis.technical_score} />
            <Score label="Fundamental" value={analysis.fundamental_score} />
          </div>
        </div>
      )}

      <div style={s.panels}>
        {/* Left: Fundamentals + Trade Plan */}
        <div style={s.leftCol}>
          {/* Trade Plan */}
          {analysis && !analysis.error && (
            <Section title="⚡ TRADE PLAN">
              <div style={s.thesisBox}>{analysis.thesis}</div>
              <div style={s.tradeGrid}>
                <PriceRow label="Entry" value={`$${analysis.entry_price}`} sub={analysis.entry_condition} highlight />
                <PriceRow label="Stop Loss" value={`$${analysis.stop_loss}`} color="#f85149" />
                <PriceRow label="Target 1" value={`$${analysis.target1}`} color="#3fb950" />
                <PriceRow label="Target 2" value={analysis.target2 ? `$${analysis.target2}` : '—'} color="#3fb950" />
                <PriceRow label="Target 3" value={analysis.target3 ? `$${analysis.target3}` : '—'} color="#3fb950" />
                <PriceRow label="R:R" value={`${analysis.risk_reward?.toFixed(1)}:1`} highlight />
                <PriceRow label="Horizon" value={analysis.time_horizon} />
                <PriceRow label="Position" value={`${analysis.position_size_shares} shares`} sub={`$${analysis.position_value?.toFixed(0)}`} />
                <PriceRow label="Risk $" value={`$${analysis.risk_dollars?.toFixed(0)}`} color="#f78166" />
              </div>

              <div style={s.catRisks}>
                <div style={s.catBlock}>
                  <div style={s.catTitle}>Catalysts</div>
                  {(analysis.catalysts || []).map((c, i) => <div key={i} style={s.catItem}>+ {c}</div>)}
                </div>
                <div style={s.catBlock}>
                  <div style={s.catTitle}>Risks</div>
                  {(analysis.risks || []).map((r, i) => <div key={i} style={{ ...s.catItem, color: '#f85149' }}>⚠ {r}</div>)}
                </div>
              </div>

              <button
                style={s.tradeBtn}
                onClick={() => onTrade({ ticker, analysis })}
              >
                Enter Trade →
              </button>
            </Section>
          )}

          {/* Fundamentals */}
          {info && (
            <Section title="FUNDAMENTALS">
              <div style={s.fundGrid}>
                <FundItem label="P/E (TTM)" value={info.pe_ratio?.toFixed(1)} />
                <FundItem label="Forward P/E" value={info.forward_pe?.toFixed(1)} />
                <FundItem label="PEG" value={info.peg_ratio?.toFixed(2)} />
                <FundItem label="P/B" value={info.price_to_book?.toFixed(2)} />
                <FundItem label="EV/EBITDA" value={info.ev_to_ebitda?.toFixed(1)} />
                <FundItem label="Rev Growth" value={info.revenue_growth ? `${(info.revenue_growth * 100).toFixed(1)}%` : '—'} />
                <FundItem label="EPS Growth" value={info.earnings_growth ? `${(info.earnings_growth * 100).toFixed(1)}%` : '—'} />
                <FundItem label="Profit Margin" value={info.profit_margins ? `${(info.profit_margins * 100).toFixed(1)}%` : '—'} />
                <FundItem label="ROE" value={info.return_on_equity ? `${(info.return_on_equity * 100).toFixed(1)}%` : '—'} />
                <FundItem label="Debt/Equity" value={info.debt_to_equity?.toFixed(2)} />
                <FundItem label="Beta" value={info.beta?.toFixed(2)} />
                <FundItem label="Analyst Target" value={info.analyst_target ? `$${info.analyst_target}` : '—'} />
                <FundItem label="Short Ratio" value={info.short_ratio?.toFixed(1)} />
                <FundItem label="Inst. Owned" value={info.institutional_pct ? `${(info.institutional_pct * 100).toFixed(0)}%` : '—'} />
              </div>
              {info.description && <div style={s.description}>{info.description}</div>}
            </Section>
          )}
        </div>

        {/* Right: Sentiment */}
        <div style={s.rightCol}>
          <div style={s.sentimentPanel}>
            <div style={s.sentTitle}>NEWS SENTIMENT</div>
            {sentiment && (
              <>
                <div style={{ ...s.sentScore, color: sentimentColor(sentiment.sentiment) }}>
                  {sentiment.sentiment}
                </div>
                <div style={s.sentBar}>
                  <div style={{ ...s.sentFill, width: `${((sentiment.score + 1) / 2) * 100}%`, background: sentimentColor(sentiment.sentiment) }} />
                </div>
                <div style={s.sentSummary}>{sentiment.summary}</div>
                {sentiment.key_themes?.map((t, i) => (
                  <span key={i} style={s.theme}>{t}</span>
                ))}
              </>
            )}
          </div>

          <button style={s.rerunBtn} onClick={runAnalysis}>↻ Re-run Analysis</button>
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div style={s.section}>
      <div style={s.sectionTitle}>{title}</div>
      {children}
    </div>
  )
}

function Score({ label, value }) {
  const color = value >= 7 ? '#3fb950' : value >= 5 ? '#e3b341' : '#f85149'
  return (
    <div style={s.scoreItem}>
      <div style={{ ...s.scoreVal, color }}>{value}/10</div>
      <div style={s.scoreLabel}>{label}</div>
    </div>
  )
}

function PriceRow({ label, value, color, sub, highlight }) {
  return (
    <div style={{ ...s.priceRow, background: highlight ? '#1f6feb11' : 'transparent' }}>
      <span style={s.priceLabel}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ ...s.priceVal, color: color || '#e6edf3' }}>{value}</span>
        {sub && <div style={s.priceSub}>{sub}</div>}
      </div>
    </div>
  )
}

function FundItem({ label, value }) {
  return (
    <div style={s.fundItem}>
      <div style={s.fundLabel}>{label}</div>
      <div style={s.fundVal}>{value ?? '—'}</div>
    </div>
  )
}

function EmptyState({ ticker, onAnalyze }) {
  return (
    <div style={s.empty}>
      <div style={s.emptyIcon}>🧠</div>
      <div style={s.emptyTitle}>AI Analysis for {ticker}</div>
      <div style={s.emptyDesc}>Get a full fundamental + technical + sentiment breakdown with a concrete trade plan.</div>
      <button style={s.emptyBtn} onClick={onAnalyze}>Run Full Analysis</button>
    </div>
  )
}

function LoadingScreen({ ticker }) {
  return (
    <div style={s.empty}>
      <div style={{ fontSize: 32, animation: 'spin 1s linear infinite' }}>⚙</div>
      <div style={s.emptyTitle}>Analyzing {ticker}...</div>
      <div style={s.emptyDesc}>Fetching fundamentals, technicals, news, and running AI synthesis.</div>
    </div>
  )
}

const actionColor = a => ({ BUY: '#3fb950', SELL_SHORT: '#f85149', WATCH: '#e3b341', AVOID: '#8b949e' })[a] || '#8b949e'
const convictionColor = c => ({ HIGH: '#3fb950', MEDIUM: '#e3b341', LOW: '#8b949e' })[c] || '#8b949e'
const sentimentColor = s => ({ BULLISH: '#3fb950', BEARISH: '#f85149', NEUTRAL: '#e3b341' })[s] || '#e3b341'

const s = {
  wrap: { flex: 1, overflow: 'auto', background: '#0d1117' },
  verdict: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: '#161b22', borderBottom: '1px solid #21262d' },
  verdictLeft: { display: 'flex', alignItems: 'center', gap: 10 },
  actionBadge: { fontWeight: 800, fontSize: 14, color: '#fff', padding: '4px 12px', borderRadius: 6 },
  convictionBadge: { fontWeight: 700, fontSize: 11 },
  strategyLabel: { color: '#8b949e', fontSize: 12 },
  scores: { display: 'flex', gap: 20 },
  scoreItem: { textAlign: 'center' },
  scoreVal: { fontWeight: 800, fontSize: 18 },
  scoreLabel: { fontSize: 10, color: '#8b949e', marginTop: 2 },
  panels: { display: 'flex', gap: 0, height: 'calc(100% - 60px)', overflow: 'hidden' },
  leftCol: { flex: 1, overflow: 'auto', borderRight: '1px solid #21262d' },
  rightCol: { width: 200, overflow: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 12 },
  section: { borderBottom: '1px solid #21262d', padding: 16 },
  sectionTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, marginBottom: 12 },
  thesisBox: { background: '#161b22', borderRadius: 6, padding: 12, fontSize: 12, color: '#c9d1d9', lineHeight: 1.6, marginBottom: 12 },
  tradeGrid: { display: 'flex', flexDirection: 'column', gap: 1, marginBottom: 12 },
  priceRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '5px 8px', borderRadius: 4 },
  priceLabel: { color: '#8b949e', fontSize: 11, paddingTop: 2 },
  priceVal: { fontWeight: 700, fontSize: 13 },
  priceSub: { fontSize: 10, color: '#8b949e', textAlign: 'right' },
  catRisks: { display: 'flex', gap: 12, marginBottom: 12 },
  catBlock: { flex: 1 },
  catTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4, letterSpacing: 0.5 },
  catItem: { fontSize: 11, color: '#3fb950', marginBottom: 3, lineHeight: 1.4 },
  tradeBtn: { width: '100%', background: 'linear-gradient(135deg, #1f6feb, #388bfd)', border: 'none', color: '#fff', padding: '10px', borderRadius: 6, cursor: 'pointer', fontWeight: 700, fontSize: 13 },
  fundGrid: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 },
  fundItem: { background: '#161b22', borderRadius: 5, padding: '7px 10px' },
  fundLabel: { fontSize: 10, color: '#8b949e' },
  fundVal: { fontWeight: 700, fontSize: 12, color: '#e6edf3', marginTop: 2 },
  description: { fontSize: 11, color: '#8b949e', marginTop: 12, lineHeight: 1.6 },
  sentimentPanel: { background: '#161b22', borderRadius: 8, padding: 12 },
  sentTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, marginBottom: 8 },
  sentScore: { fontWeight: 800, fontSize: 18, marginBottom: 8 },
  sentBar: { height: 4, background: '#21262d', borderRadius: 2, marginBottom: 8 },
  sentFill: { height: '100%', borderRadius: 2 },
  sentSummary: { fontSize: 11, color: '#c9d1d9', lineHeight: 1.5, marginBottom: 8 },
  theme: { display: 'inline-block', background: '#21262d', color: '#8b949e', fontSize: 10, padding: '2px 6px', borderRadius: 4, margin: '2px 2px 0 0' },
  rerunBtn: { background: '#21262d', border: 'none', color: '#8b949e', padding: '8px', borderRadius: 6, cursor: 'pointer', width: '100%', fontSize: 12 },
  error: { color: '#f85149', padding: 24 },
  empty: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 16, padding: 40 },
  emptyIcon: { fontSize: 48 },
  emptyTitle: { fontSize: 18, fontWeight: 700, color: '#e6edf3' },
  emptyDesc: { fontSize: 13, color: '#8b949e', textAlign: 'center', maxWidth: 400, lineHeight: 1.6 },
  emptyBtn: { background: 'linear-gradient(135deg, #1f6feb, #388bfd)', border: 'none', color: '#fff', padding: '12px 32px', borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: 14 },
}
