import { useState } from 'react'
import { addToWatchlist, removeFromWatchlist } from '../api.js'

export default function Sidebar({ watchlist, activeTicker, onSelect, onRefresh, portfolio }) {
  const [newTicker, setNewTicker] = useState('')
  const [adding, setAdding] = useState(false)

  const handleAdd = async (e) => {
    e.preventDefault()
    if (!newTicker.trim()) return
    setAdding(true)
    try {
      await addToWatchlist(newTicker.trim().toUpperCase())
      setNewTicker('')
      onRefresh()
    } catch (e) {}
    setAdding(false)
  }

  const handleRemove = async (ticker, e) => {
    e.stopPropagation()
    try {
      await removeFromWatchlist(ticker)
      onRefresh()
    } catch (e) {}
  }

  const openPositions = portfolio?.positions?.filter(p => p.status === 'OPEN') || []
  const summary = portfolio?.summary || {}

  return (
    <div style={s.sidebar}>
      {/* Portfolio Summary */}
      <div style={s.section}>
        <div style={s.sectionTitle}>PORTFOLIO</div>
        <div style={s.summaryGrid}>
          <div style={s.summaryItem}>
            <div style={s.summaryLabel}>Open P&L</div>
            <div style={{ ...s.summaryVal, color: summary.total_unrealized_pnl >= 0 ? '#3fb950' : '#f85149' }}>
              {summary.total_unrealized_pnl >= 0 ? '+' : ''}${summary.total_unrealized_pnl?.toFixed(2) ?? '0.00'}
            </div>
          </div>
          <div style={s.summaryItem}>
            <div style={s.summaryLabel}>Realized</div>
            <div style={{ ...s.summaryVal, color: summary.realized_pnl >= 0 ? '#3fb950' : '#f85149' }}>
              {summary.realized_pnl >= 0 ? '+' : ''}${summary.realized_pnl?.toFixed(2) ?? '0.00'}
            </div>
          </div>
          <div style={s.summaryItem}>
            <div style={s.summaryLabel}>Win Rate</div>
            <div style={s.summaryVal}>{summary.win_rate ?? 0}%</div>
          </div>
          <div style={s.summaryItem}>
            <div style={s.summaryLabel}>Trades</div>
            <div style={s.summaryVal}>{summary.total_trades ?? 0}</div>
          </div>
        </div>

        {openPositions.length > 0 && (
          <div style={s.openPos}>
            {openPositions.map(p => (
              <div
                key={p.id}
                style={{ ...s.posRow, borderLeft: `3px solid ${p.unrealized_pnl >= 0 ? '#3fb950' : '#f85149'}` }}
                onClick={() => onSelect(p.ticker)}
              >
                <div>
                  <span style={s.posTicker}>{p.ticker}</span>
                  <span style={s.posDir}>{p.direction}</span>
                </div>
                <div style={{ color: p.unrealized_pnl >= 0 ? '#3fb950' : '#f85149', fontWeight: 600, fontSize: 11 }}>
                  {p.unrealized_pnl >= 0 ? '+' : ''}${p.unrealized_pnl?.toFixed(2)}
                  <span style={{ color: '#8b949e', marginLeft: 4 }}>({p.unrealized_pnl_pct?.toFixed(1)}%)</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Watchlist */}
      <div style={{ ...s.section, flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={s.sectionTitle}>WATCHLIST</div>
        <div style={s.watchlistItems}>
          {watchlist.map(item => (
            <div
              key={item.ticker}
              style={{ ...s.watchItem, background: activeTicker === item.ticker ? '#1f6feb22' : 'transparent', borderLeft: activeTicker === item.ticker ? '3px solid #388bfd' : '3px solid transparent' }}
              onClick={() => onSelect(item.ticker)}
            >
              <div>
                <div style={s.watchTicker}>{item.ticker}</div>
                <div style={s.watchName}>{item.name?.substring(0, 18) || ''}</div>
              </div>
              <div style={s.watchRight}>
                {item.current_price && <div style={s.watchPrice}>${item.current_price}</div>}
                <button style={s.removeBtn} onClick={(e) => handleRemove(item.ticker, e)}>×</button>
              </div>
            </div>
          ))}
        </div>

        <form onSubmit={handleAdd} style={s.addForm}>
          <input
            style={s.addInput}
            value={newTicker}
            onChange={e => setNewTicker(e.target.value.toUpperCase())}
            placeholder="Add ticker..."
            maxLength={10}
          />
          <button style={s.addBtn} type="submit" disabled={adding}>+</button>
        </form>
      </div>
    </div>
  )
}

const s = {
  sidebar: { width: 200, background: '#161b22', borderRight: '1px solid #21262d', display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0 },
  section: { borderBottom: '1px solid #21262d', padding: '10px 0' },
  sectionTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, padding: '0 12px 6px' },
  summaryGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, padding: '0 8px' },
  summaryItem: { padding: '6px 4px' },
  summaryLabel: { fontSize: 10, color: '#8b949e' },
  summaryVal: { fontSize: 12, fontWeight: 700, color: '#e6edf3' },
  openPos: { marginTop: 8, display: 'flex', flexDirection: 'column', gap: 2, padding: '0 8px' },
  posRow: { padding: '5px 8px', background: '#0d1117', borderRadius: 4, cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  posTicker: { fontWeight: 700, fontSize: 11, color: '#e6edf3' },
  posDir: { fontSize: 9, color: '#8b949e', marginLeft: 4 },
  watchlistItems: { flex: 1, overflowY: 'auto' },
  watchItem: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 12px', cursor: 'pointer', transition: 'background .15s' },
  watchTicker: { fontWeight: 700, fontSize: 12, color: '#e6edf3' },
  watchName: { fontSize: 10, color: '#8b949e', marginTop: 1 },
  watchRight: { display: 'flex', alignItems: 'center', gap: 6 },
  watchPrice: { fontSize: 11, fontWeight: 600, color: '#c9d1d9' },
  removeBtn: { background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: '0 2px' },
  addForm: { display: 'flex', gap: 4, padding: '8px 10px', borderTop: '1px solid #21262d' },
  addInput: { flex: 1, background: '#0d1117', border: '1px solid #30363d', borderRadius: 5, padding: '5px 8px', color: '#e6edf3', outline: 'none', fontSize: 12 },
  addBtn: { background: '#1f6feb', border: 'none', color: '#fff', borderRadius: 5, padding: '5px 10px', cursor: 'pointer', fontWeight: 700 },
}
