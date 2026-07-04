import { useState, useEffect } from 'react'
import { closeTrade, deleteTrade, getWebullHoldings } from '../api.js'

export default function Portfolio({ portfolio, onRefresh }) {
  const [closingId, setClosingId] = useState(null)
  const [exitPrice, setExitPrice] = useState('')
  const [showAlpaca, setShowAlpaca] = useState(false)
  const { positions = [], summary = {} } = portfolio

  const open = positions.filter(p => p.status === 'OPEN')
  const closed = positions.filter(p => p.status === 'CLOSED')

  const handleClose = async (id) => {
    if (!exitPrice || isNaN(exitPrice)) return
    try {
      await closeTrade(id, parseFloat(exitPrice))
      setClosingId(null)
      setExitPrice('')
      onRefresh()
    } catch (e) {}
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this trade?')) return
    await deleteTrade(id)
    onRefresh()
  }

  return (
    <div style={s.wrap}>
      {/* WeBull live brokerage holdings (read-only) */}
      <WebullHoldings />

      {/* Alpaca paper portfolio — collapsed by default */}
      <button style={s.toggle} onClick={() => setShowAlpaca(v => !v)}>
        <span style={{ transform: showAlpaca ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform .15s' }}>▶</span>
        {showAlpaca ? 'Hide' : 'Show'} Alpaca paper portfolio
        {summary.open_positions > 0 && <span style={s.togglePill}>{summary.open_positions} open</span>}
      </button>

      {showAlpaca && (<>
      {/* Summary cards */}
      <div style={s.summaryRow}>
        <SummaryCard label="Portfolio" value={`$${summary.portfolio_size?.toLocaleString()}`} />
        <SummaryCard label="Open P&L" value={`${summary.total_unrealized_pnl >= 0 ? '+' : ''}$${summary.total_unrealized_pnl?.toFixed(2)}`} color={summary.total_unrealized_pnl >= 0 ? '#3fb950' : '#f85149'} />
        <SummaryCard label="Realized P&L" value={`${summary.realized_pnl >= 0 ? '+' : ''}$${summary.realized_pnl?.toFixed(2)}`} color={summary.realized_pnl >= 0 ? '#3fb950' : '#f85149'} />
        <SummaryCard label="Win Rate" value={`${summary.win_rate}%`} />
        <SummaryCard label="Total Trades" value={summary.total_trades} />
        <SummaryCard label="Open Positions" value={summary.open_positions} />
      </div>

      {/* Open positions */}
      <div style={s.tableSection}>
        <div style={s.sectionTitle}>OPEN POSITIONS ({open.length})</div>
        {open.length === 0 ? (
          <div style={s.empty}>No open positions. Use "Enter Trade" after AI analysis.</div>
        ) : (
          <table style={s.table}>
            <thead>
              <tr style={s.thead}>
                {['Ticker', 'Dir', 'Qty', 'Entry', 'Current', 'Stop', 'T1', 'Unrealized P&L', 'Strategy', 'Actions'].map(h => (
                  <th key={h} style={s.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {open.map(p => (
                <>
                  <tr key={p.id} style={s.tr}>
                    <td style={s.td}><strong style={{ color: '#58a6ff' }}>{p.ticker}</strong></td>
                    <td style={s.td}><span style={{ color: p.direction === 'LONG' ? '#3fb950' : '#f85149' }}>{p.direction}</span></td>
                    <td style={s.td}>{p.quantity}</td>
                    <td style={s.td}>${p.entry_price?.toFixed(2)}</td>
                    <td style={s.td}>${p.current_price?.toFixed(2)}</td>
                    <td style={s.td}>{p.stop_loss ? <span style={{ color: '#f85149' }}>${p.stop_loss?.toFixed(2)}</span> : '—'}</td>
                    <td style={s.td}>{p.target1 ? <span style={{ color: '#3fb950' }}>${p.target1?.toFixed(2)}</span> : '—'}</td>
                    <td style={s.td}>
                      <span style={{ color: p.unrealized_pnl >= 0 ? '#3fb950' : '#f85149', fontWeight: 700 }}>
                        {p.unrealized_pnl >= 0 ? '+' : ''}${p.unrealized_pnl?.toFixed(2)} ({p.unrealized_pnl_pct?.toFixed(1)}%)
                      </span>
                    </td>
                    <td style={s.td}>{p.strategy || '—'}</td>
                    <td style={s.td}>
                      {closingId === p.id ? (
                        <div style={{ display: 'flex', gap: 4 }}>
                          <input
                            style={s.exitInput}
                            placeholder="Exit price"
                            value={exitPrice}
                            onChange={e => setExitPrice(e.target.value)}
                            autoFocus
                          />
                          <button style={s.confirmBtn} onClick={() => handleClose(p.id)}>✓</button>
                          <button style={s.cancelBtn} onClick={() => setClosingId(null)}>✕</button>
                        </div>
                      ) : (
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button style={s.closeBtn} onClick={() => setClosingId(p.id)}>Close</button>
                          <button style={s.deleteBtn} onClick={() => handleDelete(p.id)}>✕</button>
                        </div>
                      )}
                    </td>
                  </tr>
                  {p.notes && (
                    <tr key={`note-${p.id}`} style={{ background: '#0d1117' }}>
                      <td colSpan={10} style={{ ...s.td, color: '#8b949e', fontSize: 11, paddingLeft: 16 }}>📝 {p.notes}</td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Closed trades */}
      {closed.length > 0 && (
        <div style={s.tableSection}>
          <div style={s.sectionTitle}>TRADE HISTORY ({closed.length})</div>
          <table style={s.table}>
            <thead>
              <tr style={s.thead}>
                {['Ticker', 'Dir', 'Qty', 'Entry', 'Exit', 'P&L', 'P&L%', 'Date', 'Strategy'].map(h => (
                  <th key={h} style={s.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {closed.map(p => {
                const pct = ((p.exit_price - p.entry_price) / p.entry_price * 100 * (p.direction === 'LONG' ? 1 : -1)).toFixed(1)
                return (
                  <tr key={p.id} style={s.tr}>
                    <td style={s.td}><strong style={{ color: '#c9d1d9' }}>{p.ticker}</strong></td>
                    <td style={s.td}><span style={{ color: p.direction === 'LONG' ? '#3fb950' : '#f85149' }}>{p.direction}</span></td>
                    <td style={s.td}>{p.quantity}</td>
                    <td style={s.td}>${p.entry_price?.toFixed(2)}</td>
                    <td style={s.td}>${p.exit_price?.toFixed(2)}</td>
                    <td style={s.td}><span style={{ color: p.pnl >= 0 ? '#3fb950' : '#f85149', fontWeight: 700 }}>{p.pnl >= 0 ? '+' : ''}${p.pnl?.toFixed(2)}</span></td>
                    <td style={s.td}><span style={{ color: parseFloat(pct) >= 0 ? '#3fb950' : '#f85149' }}>{pct}%</span></td>
                    <td style={s.td}>{p.exit_date?.substring(0, 10) || '—'}</td>
                    <td style={s.td}>{p.strategy || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      </>)}
    </div>
  )
}

function WebullHoldings() {
  const [data, setData] = useState({ available: false, account: {}, positions: [] })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try { const d = await getWebullHoldings(); if (alive) setData(d) } catch (e) {}
      if (alive) setLoading(false)
    }
    load()
    const iv = setInterval(load, 30000)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  const acct = data.account || {}
  const positions = data.positions || []
  const totMV = positions.reduce((a, p) => a + (p.market_value || 0), 0)
  const totPL = positions.reduce((a, p) => a + (p.unrealized_pl || 0), 0)
  const money = (v) => `${v < 0 ? '-' : ''}$${Math.abs(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

  return (
    <div style={wb.section}>
      <div style={wb.header}>
        <span style={wb.title}>WEBULL — LIVE ACCOUNT</span>
        <span style={wb.readonly}>READ-ONLY</span>
        {loading && <span style={wb.dim}>loading…</span>}
      </div>

      {!loading && !data.available ? (
        <div style={s.empty}>
          WeBull not connected — the access token may need re-approval in the WeBull phone app.
        </div>
      ) : (
        <>
          <div style={s.summaryRow}>
            <SummaryCard label="Equity" value={money(acct.equity)} />
            <SummaryCard label="Cash" value={money(acct.cash)} color={acct.cash < 0 ? '#f0a500' : '#e6edf3'} />
            <SummaryCard label="Buying Power" value={money(acct.buying_power)} />
            <SummaryCard label="Open P&L" value={`${totPL >= 0 ? '+' : ''}${money(totPL)}`} color={totPL >= 0 ? '#3fb950' : '#f85149'} />
            <SummaryCard label="Positions" value={positions.length} />
          </div>

          {positions.length > 0 && (
            <table style={{ ...s.table, marginTop: 10 }}>
              <thead>
                <tr style={s.thead}>
                  {['Ticker', 'Side', 'Qty', 'Avg Cost', 'Last', 'Market Value', 'Unrealized P&L'].map(h => (
                    <th key={h} style={s.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map(p => (
                  <tr key={p.ticker} style={s.tr}>
                    <td style={s.td}><strong style={{ color: '#f0a500' }}>{p.ticker}</strong></td>
                    <td style={s.td}><span style={{ color: p.side === 'LONG' ? '#3fb950' : '#f85149' }}>{p.side}</span></td>
                    <td style={s.td}>{p.qty}</td>
                    <td style={s.td}>${p.avg_entry?.toFixed(2)}</td>
                    <td style={s.td}>${p.current_price?.toFixed(2)}</td>
                    <td style={s.td}>{money(p.market_value)}</td>
                    <td style={s.td}>
                      <span style={{ color: p.unrealized_pl >= 0 ? '#3fb950' : '#f85149', fontWeight: 700 }}>
                        {p.unrealized_pl >= 0 ? '+' : ''}{money(p.unrealized_pl)} ({p.unrealized_plpc?.toFixed(1)}%)
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  )
}

function SummaryCard({ label, value, color }) {
  return (
    <div style={s.card}>
      <div style={s.cardLabel}>{label}</div>
      <div style={{ ...s.cardVal, color: color || '#e6edf3' }}>{value}</div>
    </div>
  )
}

const s = {
  wrap: { flex: 1, overflow: 'auto', background: '#0d1117', padding: 16, display: 'flex', flexDirection: 'column', gap: 16 },
  summaryRow: { display: 'flex', gap: 10, flexWrap: 'wrap' },
  card: { background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: '12px 16px', minWidth: 130 },
  cardLabel: { fontSize: 11, color: '#8b949e', fontWeight: 600 },
  cardVal: { fontSize: 18, fontWeight: 800, marginTop: 4 },
  tableSection: {},
  sectionTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, marginBottom: 8 },
  table: { width: '100%', borderCollapse: 'collapse', background: '#161b22', borderRadius: 8, overflow: 'hidden' },
  thead: { background: '#21262d' },
  th: { padding: '8px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 0.5, whiteSpace: 'nowrap' },
  tr: { borderBottom: '1px solid #21262d' },
  td: { padding: '8px 12px', fontSize: 12, color: '#c9d1d9', whiteSpace: 'nowrap' },
  empty: { color: '#8b949e', fontSize: 13, padding: 20, background: '#161b22', borderRadius: 8, textAlign: 'center' },
  exitInput: { background: '#0d1117', border: '1px solid #388bfd', borderRadius: 4, padding: '3px 6px', color: '#e6edf3', width: 90, outline: 'none', fontSize: 12 },
  confirmBtn: { background: '#3fb950', border: 'none', color: '#fff', borderRadius: 4, padding: '3px 8px', cursor: 'pointer' },
  cancelBtn: { background: '#f85149', border: 'none', color: '#fff', borderRadius: 4, padding: '3px 8px', cursor: 'pointer' },
  closeBtn: { background: '#21262d', border: 'none', color: '#e6edf3', borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontSize: 11 },
  deleteBtn: { background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 13 },
  toggle: { display: 'flex', alignItems: 'center', gap: 8, background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: '8px 14px', color: '#8b949e', fontSize: 12, fontWeight: 600, cursor: 'pointer', alignSelf: 'flex-start' },
  togglePill: { fontSize: 10, fontWeight: 700, color: '#c9d1d9', background: '#21262d', borderRadius: 10, padding: '1px 8px', marginLeft: 4 },
}

const wb = {
  section: { background: '#161b22', border: '1px solid #f0a50033', borderRadius: 8, padding: 14, display: 'flex', flexDirection: 'column', gap: 10 },
  header: { display: 'flex', alignItems: 'center', gap: 10 },
  title: { fontSize: 11, fontWeight: 800, color: '#f0a500', letterSpacing: 1 },
  readonly: { fontSize: 9, fontWeight: 700, color: '#8b949e', border: '1px solid #30363d', borderRadius: 4, padding: '1px 6px', letterSpacing: 0.5 },
  dim: { fontSize: 10, color: '#8b949e' },
}
