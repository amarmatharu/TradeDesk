import { useState, useEffect } from 'react'
import { addTrade, getPositionSize } from '../api.js'

export default function TradeModal({ ticker, prefill, onClose, onSubmit }) {
  const [form, setForm] = useState({
    ticker: ticker || '',
    direction: 'LONG',
    entry_price: '',
    quantity: '',
    stop_loss: '',
    target1: '',
    target2: '',
    target3: '',
    notes: '',
    strategy: '',
  })
  const [sizing, setSizing] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (prefill) {
      setForm(f => ({
        ...f,
        entry_price: prefill.entry_price || '',
        stop_loss: prefill.stop_loss || '',
        target1: prefill.target1 || '',
        target2: prefill.target2 || '',
        target3: prefill.target3 || '',
        quantity: prefill.position_size_shares || '',
        strategy: prefill.strategy || '',
      }))
    }
  }, [prefill])

  useEffect(() => {
    if (form.entry_price && form.stop_loss && !isNaN(form.entry_price) && !isNaN(form.stop_loss)) {
      getPositionSize(parseFloat(form.entry_price), parseFloat(form.stop_loss))
        .then(setSizing)
        .catch(() => {})
    }
  }, [form.entry_price, form.stop_loss])

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await addTrade({
        ticker: form.ticker.toUpperCase(),
        direction: form.direction,
        entry_price: parseFloat(form.entry_price),
        quantity: parseFloat(form.quantity),
        stop_loss: form.stop_loss ? parseFloat(form.stop_loss) : null,
        target1: form.target1 ? parseFloat(form.target1) : null,
        target2: form.target2 ? parseFloat(form.target2) : null,
        target3: form.target3 ? parseFloat(form.target3) : null,
        notes: form.notes || null,
        strategy: form.strategy || null,
      })
      onSubmit()
    } catch (e) {
      setError('Failed to add trade. Check backend connection.')
    }
    setSubmitting(false)
  }

  const rr = form.entry_price && form.stop_loss && form.target1
    ? (Math.abs(parseFloat(form.target1) - parseFloat(form.entry_price)) / Math.abs(parseFloat(form.entry_price) - parseFloat(form.stop_loss))).toFixed(2)
    : null

  return (
    <div style={s.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={s.modal}>
        <div style={s.header}>
          <div style={s.title}>Enter Trade — {form.ticker}</div>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        {prefill && (
          <div style={s.prefillBanner}>
            ⚡ Pre-filled from AI analysis · {prefill.strategy}
          </div>
        )}

        <form onSubmit={handleSubmit} style={s.form}>
          <div style={s.row}>
            <Field label="Ticker">
              <input style={s.input} value={form.ticker} onChange={e => set('ticker', e.target.value.toUpperCase())} required />
            </Field>
            <Field label="Direction">
              <select style={s.input} value={form.direction} onChange={e => set('direction', e.target.value)}>
                <option value="LONG">LONG</option>
                <option value="SHORT">SHORT</option>
              </select>
            </Field>
            <Field label="Strategy">
              <input style={s.input} value={form.strategy} onChange={e => set('strategy', e.target.value)} placeholder="e.g. EMA Pullback" />
            </Field>
          </div>

          <div style={s.row}>
            <Field label="Entry Price *">
              <input style={s.input} type="number" step="0.01" value={form.entry_price} onChange={e => set('entry_price', e.target.value)} required />
            </Field>
            <Field label="Stop Loss">
              <input style={{ ...s.input, borderColor: '#f8514944' }} type="number" step="0.01" value={form.stop_loss} onChange={e => set('stop_loss', e.target.value)} />
            </Field>
            <Field label="Shares *">
              <input style={s.input} type="number" step="1" value={form.quantity} onChange={e => set('quantity', e.target.value)} required />
            </Field>
          </div>

          <div style={s.row}>
            <Field label="Target 1">
              <input style={{ ...s.input, borderColor: '#3fb95044' }} type="number" step="0.01" value={form.target1} onChange={e => set('target1', e.target.value)} />
            </Field>
            <Field label="Target 2">
              <input style={{ ...s.input, borderColor: '#3fb95044' }} type="number" step="0.01" value={form.target2} onChange={e => set('target2', e.target.value)} />
            </Field>
            <Field label="Target 3">
              <input style={{ ...s.input, borderColor: '#3fb95044' }} type="number" step="0.01" value={form.target3} onChange={e => set('target3', e.target.value)} />
            </Field>
          </div>

          {/* Risk calculator */}
          {sizing && (
            <div style={s.riskBox}>
              <div style={s.riskTitle}>RISK CALCULATOR (1.5% rule)</div>
              <div style={s.riskGrid}>
                <RiskItem label="Suggested Shares" value={sizing.shares} highlight />
                <RiskItem label="Risk $" value={`$${sizing.risk_dollars}`} color="#f85149" />
                <RiskItem label="Risk/Share" value={`$${sizing.risk_per_share}`} />
                <RiskItem label="Position Value" value={`$${sizing.position_value?.toLocaleString()}`} />
                <RiskItem label="% of Portfolio" value={`${sizing.position_pct_of_portfolio}%`} />
                {rr && <RiskItem label="R:R (T1)" value={`${rr}:1`} color={parseFloat(rr) >= 2 ? '#3fb950' : '#f85149'} highlight />}
              </div>
            </div>
          )}

          <Field label="Notes">
            <textarea style={{ ...s.input, height: 56, resize: 'none' }} value={form.notes} onChange={e => set('notes', e.target.value)} placeholder="Trade notes, thesis..." />
          </Field>

          {error && <div style={s.error}>{error}</div>}

          <button type="submit" style={s.submitBtn} disabled={submitting}>
            {submitting ? 'Adding...' : '+ Add to Portfolio'}
          </button>
        </form>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
      <label style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 0.5 }}>{label}</label>
      {children}
    </div>
  )
}

function RiskItem({ label, value, color, highlight }) {
  return (
    <div style={{ background: highlight ? '#1f6feb11' : '#0d1117', borderRadius: 5, padding: '6px 10px' }}>
      <div style={{ fontSize: 10, color: '#8b949e' }}>{label}</div>
      <div style={{ fontWeight: 700, fontSize: 13, color: color || '#e6edf3', marginTop: 2 }}>{value}</div>
    </div>
  )
}

const s = {
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 },
  modal: { background: '#161b22', border: '1px solid #30363d', borderRadius: 12, width: 600, maxHeight: '90vh', overflow: 'auto' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', borderBottom: '1px solid #21262d' },
  title: { fontWeight: 800, fontSize: 16, color: '#e6edf3' },
  closeBtn: { background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18 },
  prefillBanner: { background: '#1f6feb22', borderBottom: '1px solid #1f6feb44', padding: '8px 20px', fontSize: 11, color: '#58a6ff', fontWeight: 600 },
  form: { padding: 20, display: 'flex', flexDirection: 'column', gap: 12 },
  row: { display: 'flex', gap: 12 },
  input: { background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, padding: '7px 10px', color: '#e6edf3', outline: 'none', width: '100%', fontSize: 13 },
  riskBox: { background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: 12 },
  riskTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, marginBottom: 8 },
  riskGrid: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 },
  error: { color: '#f85149', fontSize: 12 },
  submitBtn: { background: 'linear-gradient(135deg, #1f6feb, #388bfd)', border: 'none', color: '#fff', padding: '12px', borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: 14, marginTop: 4 },
}
