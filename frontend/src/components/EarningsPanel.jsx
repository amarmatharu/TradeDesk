import { useState, useEffect } from 'react'
import { getUpcomingEarnings } from '../api.js'

export default function EarningsPanel({ onSelectTicker }) {
  const [data, setData] = useState({ mine: [], all: [] })
  const [days, setDays] = useState(14)
  const [largeCapOnly, setLargeCapOnly] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = (d) => {
    setLoading(true)
    getUpcomingEarnings(d).then(r => { setData(r); setLoading(false) }).catch(() => setLoading(false))
  }
  useEffect(() => { load(days) }, [days])

  const mine = data.mine || []
  const all = (data.all || []).filter(e => !largeCapOnly || e.large_cap)

  return (
    <div style={s.wrap}>
      <div style={s.headerRow}>
        <div style={s.h1}>UPCOMING EARNINGS</div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {[7, 14, 30].map(d => (
            <button key={d} onClick={() => setDays(d)}
              style={{ ...s.rangeBtn, ...(days === d ? s.rangeActive : {}) }}>{d}d</button>
          ))}
          <button onClick={() => setLargeCapOnly(v => !v)}
            style={{ ...s.rangeBtn, ...(largeCapOnly ? s.rangeActive : {}), marginLeft: 6 }}>Large-cap only</button>
          <span style={s.dim}>{data.count != null ? `${data.count} reports · ${data.source || ''}` : ''}</span>
        </div>
      </div>

      {loading ? <div style={s.dim}>Loading earnings calendar…</div> : (
        <>
          {/* Your watchlist + holdings */}
          <div style={s.section}>
            <div style={s.sectionTitle}>★ YOUR WATCHLIST & HOLDINGS ({mine.length})</div>
            {mine.length === 0 ? (
              <div style={s.empty}>None of your tracked/held tickers report in the next {days} days.</div>
            ) : (
              <Table rows={mine} onSelectTicker={onSelectTicker} highlight />
            )}
          </div>

          {/* Full calendar */}
          <div style={s.section}>
            <div style={s.sectionTitle}>ALL UPCOMING ({all.length})</div>
            <Table rows={all} onSelectTicker={onSelectTicker} />
          </div>
        </>
      )}
    </div>
  )
}

function Table({ rows, onSelectTicker, highlight }) {
  return (
    <table style={s.table}>
      <thead>
        <tr style={s.thead}>
          {['When', 'Date', 'Ticker', 'Time', 'EPS est.', 'Track record', 'Company'].map(h => <th key={h} style={s.th}>{h}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((e, i) => (
          <tr key={`${e.ticker}-${e.date}-${i}`} style={{ ...s.tr, ...(highlight ? { background: '#12180f' } : {}) }}>
            <td style={s.td}>
              <span style={{ ...s.chip, ...(e.days_until <= 2 ? s.soon : {}) }}>
                {e.days_until === 0 ? 'Today' : e.days_until === 1 ? 'Tmrw' : `+${e.days_until}d`}
              </span>
            </td>
            <td style={s.td}>{e.date}</td>
            <td style={s.td}>
              <strong style={{ color: '#58a6ff', cursor: 'pointer' }} onClick={() => onSelectTicker && onSelectTicker(e.ticker)}>{e.ticker}</strong>
              {e.held && <span style={s.held}>HELD</span>}
              {!e.held && e.in_watchlist && <span style={s.watch}>WATCH</span>}
            </td>
            <td style={s.td}>{e.when ? <span style={{ color: e.when === 'BMO' ? '#f0a500' : '#8957e5' }}>{e.when}</span> : '—'}</td>
            <td style={s.td}>{e.eps_estimate != null && e.eps_estimate !== '' ? `$${e.eps_estimate}` : '—'}</td>
            <td style={s.td}>
              {e.track_record ? (
                <span style={{ color: e.track_record.beats >= e.track_record.of * 0.6 ? '#3fb950' : '#f0a500' }}>
                  beat {e.track_record.beats}/{e.track_record.of}
                  <span style={{ color: '#8b949e' }}> · {e.track_record.avg_surprise_pct > 0 ? '+' : ''}{e.track_record.avg_surprise_pct}%</span>
                </span>
              ) : '—'}
            </td>
            <td style={{ ...s.td, color: '#8b949e', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.company}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const s = {
  wrap: { flex: 1, overflow: 'auto', background: '#0d1117', padding: 16, display: 'flex', flexDirection: 'column', gap: 14 },
  headerRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  h1: { fontSize: 14, fontWeight: 800, color: '#e6edf3', letterSpacing: 1 },
  dim: { fontSize: 11, color: '#8b949e' },
  rangeBtn: { background: '#161b22', border: '1px solid #21262d', color: '#8b949e', borderRadius: 6, padding: '3px 10px', cursor: 'pointer', fontSize: 12 },
  rangeActive: { background: '#1f6feb', color: '#fff', borderColor: '#1f6feb' },
  section: { background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 },
  sectionTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1 },
  empty: { color: '#8b949e', fontSize: 13, padding: 12 },
  table: { width: '100%', borderCollapse: 'collapse' },
  thead: { background: '#0d1117' },
  th: { padding: '6px 10px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 0.5, whiteSpace: 'nowrap', position: 'sticky', top: 0 },
  tr: { borderBottom: '1px solid #21262d' },
  td: { padding: '6px 10px', fontSize: 12, color: '#c9d1d9', whiteSpace: 'nowrap' },
  chip: { fontSize: 10, fontWeight: 700, color: '#8b949e', border: '1px solid #30363d', borderRadius: 5, padding: '1px 7px' },
  soon: { color: '#f85149', borderColor: '#5a1e1e' },
  held: { fontSize: 9, fontWeight: 700, color: '#3fb950', border: '1px solid #238636', borderRadius: 4, padding: '0 5px', marginLeft: 6 },
  watch: { fontSize: 9, fontWeight: 700, color: '#f0a500', border: '1px solid #3a3410', borderRadius: 4, padding: '0 5px', marginLeft: 6 },
}
