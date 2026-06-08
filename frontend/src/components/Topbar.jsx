export default function Topbar({ marketData, activeTicker, onOpenSettings }) {
  const indices = ['SPY', 'QQQ', 'DIA', 'VIX', 'GLD', 'USO']

  return (
    <div style={s.bar}>
      <div style={s.logo}>
        <span style={s.logoIcon}>📈</span>
        <span style={s.logoText}>TradeDesk</span>
        <span style={s.logoSub}>AI</span>
      </div>
      <div style={s.indices}>
        {indices.map(sym => {
          const d = marketData[sym]
          if (!d) return null
          const up = d.change_pct >= 0
          return (
            <div key={sym} style={s.indexItem}>
              <span style={s.indexName}>{d.name}</span>
              <span style={s.indexPrice}>${d.price?.toLocaleString()}</span>
              <span style={{ ...s.indexChg, color: up ? '#3fb950' : '#f85149' }}>
                {up ? '▲' : '▼'} {Math.abs(d.change_pct)}%
              </span>
            </div>
          )
        })}
      </div>
      <div style={s.right}>
        <div style={s.portfolioChip}>
          <span style={s.portfolioLabel}>Portfolio</span>
          <span style={s.portfolioVal}>$25,000</span>
        </div>
        <div style={s.statusDot} title="Live data" />
        <button style={s.gearBtn} onClick={onOpenSettings} title="Settings (⌘,)">⚙</button>
      </div>
    </div>
  )
}

const s = {
  bar: { display: 'flex', alignItems: 'center', gap: 16, padding: '0 16px', height: 44, background: '#161b22', borderBottom: '1px solid #21262d', flexShrink: 0 },
  logo: { display: 'flex', alignItems: 'baseline', gap: 4, marginRight: 8 },
  logoIcon: { fontSize: 16 },
  logoText: { fontWeight: 800, fontSize: 15, color: '#e6edf3', letterSpacing: -0.5 },
  logoSub: { fontSize: 9, fontWeight: 700, color: '#388bfd', background: '#1f6feb22', padding: '1px 5px', borderRadius: 4, letterSpacing: 1 },
  indices: { display: 'flex', gap: 20, flex: 1, overflowX: 'auto' },
  indexItem: { display: 'flex', gap: 6, alignItems: 'baseline', whiteSpace: 'nowrap' },
  indexName: { color: '#8b949e', fontSize: 11, fontWeight: 600 },
  indexPrice: { color: '#e6edf3', fontWeight: 600 },
  indexChg: { fontSize: 11, fontWeight: 700 },
  right: { display: 'flex', alignItems: 'center', gap: 12, marginLeft: 'auto' },
  portfolioChip: { display: 'flex', gap: 6, alignItems: 'center', background: '#21262d', padding: '4px 10px', borderRadius: 6 },
  portfolioLabel: { color: '#8b949e', fontSize: 11 },
  portfolioVal: { color: '#3fb950', fontWeight: 700 },
  statusDot: { width: 8, height: 8, borderRadius: '50%', background: '#3fb950', boxShadow: '0 0 6px #3fb950' },
  gearBtn: { background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 16, padding: '0 4px', lineHeight: 1 },
}
