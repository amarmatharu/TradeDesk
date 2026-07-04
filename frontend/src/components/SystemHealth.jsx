import { useState, useEffect } from 'react'
import { getMetrics, getRecon, getRegime, getPromotion, getValidation, getPortfolioRisk } from '../api.js'

const GREEN = '#3fb950', RED = '#f85149', AMBER = '#f0a500', DIM = '#8b949e'

export default function SystemHealth() {
  const [d, setD] = useState({})
  const [loading, setLoading] = useState(true)
  const [updated, setUpdated] = useState(null)

  const load = async () => {
    const [metrics, recon, regime, promotion, validation, risk] = await Promise.all([
      getMetrics().catch(() => ({})), getRecon().catch(() => ({})),
      getRegime().catch(() => ({})), getPromotion().catch(() => ({})),
      getValidation().catch(() => ({})), getPortfolioRisk().catch(() => ({})),
    ])
    setD({ metrics, recon, regime, promotion, validation, risk })
    setUpdated(new Date())
    setLoading(false)
  }

  useEffect(() => {
    load()
    const iv = setInterval(load, 30000)
    return () => clearInterval(iv)
  }, [])

  if (loading) return <div style={s.wrap}><div style={s.dim}>Loading system health…</div></div>

  const m = d.metrics?.overall || {}
  const promo = d.promotion || {}
  const regime = d.regime || {}
  const recon = d.recon || {}
  const risk = d.risk || {}
  const val = d.validation || {}
  const money = (v) => (v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`)

  return (
    <div style={s.wrap}>
      <div style={s.headerRow}>
        <div style={s.h1}>SYSTEM HEALTH</div>
        <div style={s.dim}>{updated ? `updated ${updated.toLocaleTimeString()} · auto-refresh 30s` : ''}</div>
      </div>

      {/* Promotion gate — the headline verdict */}
      <div style={{ ...s.banner, borderColor: promo.promotable ? GREEN : RED }}>
        <div style={{ ...s.bannerTitle, color: promo.promotable ? GREEN : RED }}>
          {promo.promotable ? '✅ READY FOR LIVE' : '⛔ NOT READY FOR REAL MONEY'}
        </div>
        <div style={s.dim}>{promo.verdict}</div>
        {promo.checks && (
          <div style={s.checkRow}>
            {promo.checks.map(c => (
              <span key={c.name} style={{ ...s.chip, color: c.pass ? GREEN : RED, borderColor: c.pass ? '#238636' : '#5a1e1e' }}>
                {c.pass ? '✓' : '✗'} {c.name.replace(/_/g, ' ')} <span style={{ color: DIM }}>({c.actual})</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Performance metrics */}
      <Section title="PERFORMANCE (closed trades)">
        <div style={s.cards}>
          <Card label="Trades" value={m.trades ?? '—'} />
          <Card label="Win Rate" value={m.win_rate != null ? `${m.win_rate}%` : '—'} />
          <Card label="Expectancy / trade" value={money(m.expectancy_usd)} color={m.expectancy_usd >= 0 ? GREEN : RED} />
          <Card label="Net P&L" value={money(m.net_pnl)} color={m.net_pnl >= 0 ? GREEN : RED} />
          <Card label="Profit Factor" value={m.profit_factor ?? '—'} color={(m.profit_factor || 0) >= 1.3 ? GREEN : RED} />
          <Card label="Deflated Sharpe" value={m.deflated_sharpe ?? '—'} color={(m.deflated_sharpe || 0) >= 0.9 ? GREEN : AMBER} hint="prob edge is real" />
          <Card label="Sharpe (ann)" value={m.sharpe_annualized ?? '—'} color={(m.sharpe_annualized || 0) >= 0 ? GREEN : RED} />
          <Card label="Max Drawdown" value={m.max_drawdown_pct != null ? `${m.max_drawdown_pct}%` : '—'} />
        </div>
        {d.metrics?.caveat && <div style={s.caveat}>⚠ {d.metrics.caveat}</div>}
      </Section>

      <div style={s.twoCol}>
        {/* Market regime */}
        <Section title="MARKET REGIME" grow>
          <div style={s.cards}>
            <Card label="Trend" value={regime.trend || '—'} color={regime.trend === 'bull' ? GREEN : regime.trend === 'bear' ? RED : AMBER} />
            <Card label="Volatility" value={regime.volatility || '—'} color={regime.volatility === 'high' ? RED : regime.volatility === 'calm' ? GREEN : AMBER} />
            <Card label="Ann. Vol" value={regime.annualized_vol_pct != null ? `${regime.annualized_vol_pct}%` : '—'} />
            <Card label="Risk Multiplier" value={regime.risk_multiplier ?? '—'} color={regime.risk_multiplier >= 1 ? GREEN : AMBER} />
          </div>
          {regime.posture && <div style={s.note}>{regime.posture}</div>}
        </Section>

        {/* Portfolio risk */}
        <Section title="PORTFOLIO RISK" grow>
          <div style={s.cards}>
            <Card label="Positions" value={risk.positions ?? '—'} />
            <Card label="Beta" value={risk.portfolio_beta ?? '—'} />
            <Card label="VaR 95% 1d" value={money(risk.VaR_95_1d_usd)} color={RED} />
            <Card label="Avg Corr" value={risk.avg_pairwise_corr ?? '—'} color={(risk.avg_pairwise_corr || 0) > 0.6 ? RED : GREEN} />
            <Card label="Concentration" value={risk.largest_weight != null ? `${Math.round(risk.largest_weight * 100)}%` : '—'} />
          </div>
          {(risk.flags || []).map((f, i) => <div key={i} style={s.flag}>⚠ {f}</div>)}
        </Section>
      </div>

      {/* Reconciliation */}
      <Section title="RECONCILIATION (ledger ↔ broker)">
        <div style={{ ...s.banner, borderColor: recon.clean ? GREEN : AMBER, padding: 10 }}>
          <span style={{ color: recon.clean ? GREEN : AMBER, fontWeight: 700 }}>
            {recon.clean ? '✓ In sync' : '⚠ Drift detected'}
          </span>
          <span style={{ color: DIM, marginLeft: 10 }}>
            broker: {recon.broker} · {recon.summary && `${recon.summary.matched} matched, ${recon.summary.mismatched} mismatched, ${recon.summary.ledger_only} ledger-only, ${recon.summary.broker_only} broker-only`}
          </span>
        </div>
        {!recon.clean && (
          <div style={{ marginTop: 8 }}>
            {[['ledger_only', 'Phantom (ledger says held, broker doesn’t)'],
              ['broker_only', 'Untracked (broker holds, ledger missed)'],
              ['mismatched', 'Size disagreement']].map(([k, label]) =>
              (recon[k] || []).length > 0 && (
                <div key={k} style={s.reconRow}>
                  <span style={{ color: AMBER }}>{label}:</span>{' '}
                  {recon[k].map(r => `${r.ticker} (ledger ${r.ledger_qty} / broker ${r.broker_qty})`).join(', ')}
                </div>
              )
            )}
          </div>
        )}
      </Section>

      {/* Pipeline validation */}
      <Section title="PIPELINE VALIDATION">
        <div style={s.note}>
          Decisions captured: <b>{val.snapshots_captured ?? 0}</b> ·{' '}
          Pipeline edge: {val.pipeline_edge?.n ? `${val.pipeline_edge.win_rate}% win, ${money(val.pipeline_edge.expectancy_usd)}/trade (n=${val.pipeline_edge.n})` : 'no closed pipeline trades yet'}
        </div>
        <div style={{ ...s.note, color: val.confidence_calibration?.calibrated ? GREEN : AMBER }}>
          {val.confidence_calibration?.note}
        </div>
      </Section>
    </div>
  )
}

function Section({ title, children, grow }) {
  return (
    <div style={grow ? { ...s.section, ...s.grow } : s.section}>
      <div style={s.sectionTitle}>{title}</div>
      {children}
    </div>
  )
}

function Card({ label, value, color, hint }) {
  return (
    <div style={s.card}>
      <div style={s.cardLabel}>{label}{hint && <span style={s.hint}> · {hint}</span>}</div>
      <div style={{ ...s.cardVal, color: color || '#e6edf3' }}>{value}</div>
    </div>
  )
}

const s = {
  wrap: { flex: 1, overflow: 'auto', background: '#0d1117', padding: 16, display: 'flex', flexDirection: 'column', gap: 14 },
  headerRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' },
  h1: { fontSize: 14, fontWeight: 800, color: '#e6edf3', letterSpacing: 1 },
  dim: { fontSize: 11, color: DIM },
  banner: { background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 6 },
  bannerTitle: { fontSize: 16, fontWeight: 800 },
  checkRow: { display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 },
  chip: { fontSize: 11, fontWeight: 600, border: '1px solid #30363d', borderRadius: 6, padding: '2px 8px' },
  section: { background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 8 },
  sectionTitle: { fontSize: 10, fontWeight: 700, color: DIM, letterSpacing: 1 },
  cards: { display: 'flex', flexWrap: 'wrap', gap: 8 },
  card: { background: '#0d1117', border: '1px solid #21262d', borderRadius: 8, padding: '10px 14px', minWidth: 120 },
  cardLabel: { fontSize: 10, color: DIM, fontWeight: 600 },
  cardVal: { fontSize: 18, fontWeight: 800, marginTop: 3 },
  hint: { color: '#586069', fontWeight: 400, fontStyle: 'italic' },
  caveat: { fontSize: 12, color: AMBER, background: '#1c1a0e', border: '1px solid #3a3410', borderRadius: 6, padding: 8 },
  note: { fontSize: 12, color: '#c9d1d9' },
  flag: { fontSize: 12, color: AMBER },
  reconRow: { fontSize: 12, color: '#c9d1d9', marginBottom: 4 },
  twoCol: { display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-start' },
  grow: { flex: 1, minWidth: 300 },
}
