import { useState, useEffect } from 'react'
import axios from 'axios'

const SECTIONS = ['API Keys', 'Portfolio', 'Display', 'About']

export default function Settings({ onClose }) {
  const [section, setSection] = useState('API Keys')
  const [config, setConfig] = useState({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState({})
  const [testResult, setTestResult] = useState({})

  useEffect(() => {
    axios.get('/api/settings').then(r => setConfig(r.data)).catch(() => {})
  }, [])

  const set = (k, v) => setConfig(c => ({ ...c, [k]: v }))

  const save = async () => {
    setSaving(true)
    try {
      await axios.post('/api/settings', config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {}
    setSaving(false)
  }

  const testKey = async (provider) => {
    setTesting(t => ({ ...t, [provider]: true }))
    setTestResult(r => ({ ...r, [provider]: null }))
    try {
      const r = await axios.post('/api/settings/test', { provider })
      setTestResult(t => ({ ...t, [provider]: { ok: true, msg: r.data.message } }))
    } catch (e) {
      setTestResult(t => ({ ...t, [provider]: { ok: false, msg: e.response?.data?.detail || 'Connection failed' } }))
    }
    setTesting(t => ({ ...t, [provider]: false }))
  }

  return (
    <div style={s.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={s.modal}>
        {/* Header */}
        <div style={s.header}>
          <div style={s.title}>⚙ Settings</div>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div style={s.body}>
          {/* Sidebar */}
          <div style={s.nav}>
            {SECTIONS.map(sec => (
              <button key={sec} style={{ ...s.navBtn, ...(section === sec ? s.navBtnActive : {}) }} onClick={() => setSection(sec)}>
                {sectionIcon(sec)} {sec}
              </button>
            ))}
          </div>

          {/* Content */}
          <div style={s.content}>

            {section === 'API Keys' && (
              <div style={s.section}>
                <div style={s.sectionTitle}>API Keys & Connections</div>
                <div style={s.sectionDesc}>Keys are stored locally in <code style={s.code}>backend/.env</code> — never sent anywhere except the respective API.</div>

                <ApiKeyField
                  label="Anthropic API Key"
                  sublabel="Powers AI trade analysis, sentiment scoring, and trade recommendations"
                  link="https://console.anthropic.com"
                  linkLabel="Get key →"
                  value={config.anthropic_api_key || ''}
                  onChange={v => set('anthropic_api_key', v)}
                  testResult={testResult.anthropic}
                  testing={testing.anthropic}
                  onTest={() => testKey('anthropic')}
                  placeholder="sk-ant-..."
                  expectedPrefix="sk-ant-"
                />

                <ApiKeyField
                  label="Alpaca API Key ID"
                  sublabel="Real-time stock prices, OHLCV bars — replaces yfinance. Use Paper Trading keys from alpaca.markets."
                  link="https://app.alpaca.markets/paper/dashboard/overview"
                  linkLabel="Get keys →"
                  value={config.alpaca_api_key || ''}
                  onChange={v => set('alpaca_api_key', v)}
                  testResult={testResult.alpaca}
                  testing={testing.alpaca}
                  onTest={() => testKey('alpaca')}
                  placeholder="PK..."
                  expectedPrefix="PK"
                  highlight
                />

                <ApiKeyField
                  label="Alpaca Secret Key"
                  sublabel="Secret key paired with the API Key ID above"
                  value={config.alpaca_secret_key || ''}
                  onChange={v => set('alpaca_secret_key', v)}
                  placeholder="Paste secret key..."
                />

                <ApiKeyField
                  label="Benzinga Pro API Key"
                  sublabel="Real-time breaking news stream — the backbone of the trading feed. Alerts before price moves."
                  link="https://cloud.benzinga.com"
                  linkLabel="Get key →"
                  value={config.benzinga_api_key || ''}
                  onChange={v => set('benzinga_api_key', v)}
                  testResult={testResult.benzinga}
                  testing={testing.benzinga}
                  onTest={() => testKey('benzinga')}
                  placeholder="Paste Benzinga API key..."
                  highlight
                />

                <ApiKeyField
                  label="Alpha Vantage API Key"
                  sublabel="Optional: provides additional fundamental data and earnings calendars"
                  link="https://www.alphavantage.co/support/#api-key"
                  linkLabel="Free key →"
                  value={config.alpha_vantage_key || ''}
                  onChange={v => set('alpha_vantage_key', v)}
                  testResult={testResult.alphavantage}
                  testing={testing.alphavantage}
                  onTest={() => testKey('alphavantage')}
                  placeholder="Paste key..."
                  optional
                />

                <ApiKeyField
                  label="News API Key"
                  sublabel="Optional: fetches broader financial news beyond Yahoo Finance"
                  link="https://newsapi.org/register"
                  linkLabel="Free key →"
                  value={config.news_api_key || ''}
                  onChange={v => set('news_api_key', v)}
                  placeholder="Paste key..."
                  optional
                />
              </div>
            )}

            {section === 'Portfolio' && (
              <div style={s.section}>
                <div style={s.sectionTitle}>Portfolio & Risk Settings</div>
                <div style={s.sectionDesc}>These values drive position sizing and risk calculations across all trade analyses.</div>

                <div style={s.fieldGroup}>
                  <Field label="Portfolio Size ($)" sublabel="Total capital available for trading">
                    <div style={s.inputRow}>
                      <span style={s.prefix}>$</span>
                      <input style={s.input} type="number" value={config.portfolio_size || 25000}
                        onChange={e => set('portfolio_size', parseFloat(e.target.value))} />
                    </div>
                  </Field>

                  <Field label="Risk Per Trade (%)" sublabel="Max % of portfolio risked on a single trade (1–3% recommended)">
                    <div style={s.inputRow}>
                      <input style={s.input} type="number" step="0.1" min="0.5" max="5"
                        value={config.risk_pct || 1.5} onChange={e => set('risk_pct', parseFloat(e.target.value))} />
                      <span style={s.suffix}>%</span>
                    </div>
                    <div style={s.riskCalc}>
                      Max loss per trade: <strong style={{ color: '#f85149' }}>
                        ${((config.portfolio_size || 25000) * (config.risk_pct || 1.5) / 100).toFixed(0)}
                      </strong>
                    </div>
                  </Field>

                  <Field label="Min Risk:Reward Ratio" sublabel="Trades below this R:R will be flagged">
                    <div style={s.inputRow}>
                      <input style={s.input} type="number" step="0.5" min="1" max="10"
                        value={config.min_rr || 2.0} onChange={e => set('min_rr', parseFloat(e.target.value))} />
                      <span style={s.suffix}>:1</span>
                    </div>
                  </Field>

                  <Field label="Max Open Positions" sublabel="Alert when this many trades are open simultaneously">
                    <input style={{ ...s.input, width: 80 }} type="number" min="1" max="20"
                      value={config.max_positions || 5} onChange={e => set('max_positions', parseInt(e.target.value))} />
                  </Field>

                  <Field label="Max Sector Exposure (%)" sublabel="Warn when one sector exceeds this % of portfolio">
                    <div style={s.inputRow}>
                      <input style={s.input} type="number" min="10" max="100"
                        value={config.max_sector_pct || 30} onChange={e => set('max_sector_pct', parseInt(e.target.value))} />
                      <span style={s.suffix}>%</span>
                    </div>
                  </Field>
                </div>
              </div>
            )}

            {section === 'Display' && (
              <div style={s.section}>
                <div style={s.sectionTitle}>Display Preferences</div>

                <div style={s.fieldGroup}>
                  <Field label="Default Chart Period" sublabel="Time period shown when switching to a new ticker">
                    <select style={s.input} value={config.default_period || '3mo'} onChange={e => set('default_period', e.target.value)}>
                      {[['1d','1 Day'],['5d','1 Week'],['1mo','1 Month'],['3mo','3 Months'],['6mo','6 Months'],['1y','1 Year']].map(([v,l]) => (
                        <option key={v} value={v}>{l}</option>
                      ))}
                    </select>
                  </Field>

                  <Field label="Default Chart Interval" sublabel="Candle size for daily+ charts">
                    <select style={s.input} value={config.default_interval || '1d'} onChange={e => set('default_interval', e.target.value)}>
                      {[['5m','5 Min'],['15m','15 Min'],['1h','1 Hour'],['1d','Daily'],['1wk','Weekly']].map(([v,l]) => (
                        <option key={v} value={v}>{l}</option>
                      ))}
                    </select>
                  </Field>

                  <Field label="News Articles per Ticker">
                    <div style={s.inputRow}>
                      <input style={{ ...s.input, width: 80 }} type="number" min="3" max="25"
                        value={config.news_limit || 10} onChange={e => set('news_limit', parseInt(e.target.value))} />
                    </div>
                  </Field>

                  <Field label="Auto-refresh Interval" sublabel="How often prices and positions refresh (seconds)">
                    <div style={s.inputRow}>
                      <input style={{ ...s.input, width: 80 }} type="number" min="15" max="3600" step="15"
                        value={config.refresh_interval || 60} onChange={e => set('refresh_interval', parseInt(e.target.value))} />
                      <span style={s.suffix}>sec</span>
                    </div>
                  </Field>
                </div>
              </div>
            )}

            {section === 'About' && (
              <div style={s.section}>
                <div style={s.sectionTitle}>About TradeDesk</div>
                <div style={s.aboutCard}>
                  <div style={s.aboutLogo}>📈</div>
                  <div style={s.aboutName}>TradeDesk <span style={s.aboutAI}>AI</span></div>
                  <div style={s.aboutVersion}>Version 1.0.0</div>
                  <div style={s.aboutDesc}>
                    A personalized AI trading platform — full fundamental + technical + sentiment analysis,
                    automated position sizing, and Claude-powered trade recommendations.
                  </div>
                </div>

                <div style={s.stackList}>
                  <div style={s.stackTitle}>BUILT WITH</div>
                  {[
                    ['⚡ Electron', 'Native desktop shell'],
                    ['⚛️ React + Vite', 'Frontend UI'],
                    ['📊 TradingView LW Charts', 'Candlestick charting'],
                    ['🐍 Python FastAPI', 'Backend API'],
                    ['📈 yfinance', 'Market data'],
                    ['🧠 Claude Sonnet', 'AI trade brain'],
                    ['🗄 SQLite', 'Local trade history'],
                  ].map(([name, desc]) => (
                    <div key={name} style={s.stackRow}>
                      <span style={s.stackName}>{name}</span>
                      <span style={s.stackDesc}>{desc}</span>
                    </div>
                  ))}
                </div>

                <div style={s.disclaimer}>
                  ⚠️ TradeDesk is for informational and educational purposes only. Nothing here constitutes financial advice. Always do your own research.
                </div>
              </div>
            )}

            {/* Save button */}
            {section !== 'About' && (
              <div style={s.footer}>
                <button style={{ ...s.saveBtn, ...(saved ? s.saveBtnDone : {}) }} onClick={save} disabled={saving}>
                  {saving ? 'Saving...' : saved ? '✓ Saved' : 'Save Settings'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function ApiKeyField({ label, sublabel, link, linkLabel, value, onChange, testResult, testing, onTest, placeholder, optional, highlight, expectedPrefix }) {
  const [show, setShow] = useState(false)
  const masked = value ? value.slice(0, 8) + '•'.repeat(Math.max(0, value.length - 8)) : ''

  return (
    <div style={{ ...s.apiKeyField, ...(highlight ? s.apiKeyFieldHighlight : {}) }}>
      <div style={s.apiKeyHeader}>
        <div>
          <div style={s.apiKeyLabel}>{label} {optional && <span style={s.optionalTag}>optional</span>}</div>
          <div style={s.apiKeySub}>{sublabel}</div>
        </div>
        {link && <a href={link} target="_blank" rel="noopener noreferrer" style={s.getKeyLink}>{linkLabel}</a>}
      </div>
      <div style={s.apiKeyInputRow}>
        <input
          style={{ ...s.input, flex: 1, fontFamily: 'monospace', fontSize: 12 }}
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value.trim())}
          placeholder={placeholder}
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
        />
        <button style={s.showBtn} onClick={() => setShow(v => !v)}>{show ? '🙈' : '👁'}</button>
        {onTest && (
          <button style={s.testBtn} onClick={onTest} disabled={!value || testing}>
            {testing ? '...' : 'Test'}
          </button>
        )}
      </div>
      {value && (
        <div style={s.keyMeta}>
          {value.length} chars
          {expectedPrefix && (
            value.startsWith(expectedPrefix)
              ? <span style={{color:'#3fb950', marginLeft: 6}}>✓ correct prefix</span>
              : <span style={{color:'#f85149', marginLeft: 6}}>⚠ should start with {expectedPrefix}</span>
          )}
        </div>
      )}
      {testResult && (
        <div style={{ ...s.testResult, color: testResult.ok ? '#3fb950' : '#f85149' }}>
          {testResult.ok ? '✓' : '✕'} {testResult.msg}
        </div>
      )}
    </div>
  )
}

function Field({ label, sublabel, children }) {
  return (
    <div style={s.field}>
      <div>
        <div style={s.fieldLabel}>{label}</div>
        {sublabel && <div style={s.fieldSub}>{sublabel}</div>}
      </div>
      <div style={s.fieldInput}>{children}</div>
    </div>
  )
}

const sectionIcon = s => ({ 'API Keys': '🔑', Portfolio: '💼', Display: '🖥', About: 'ℹ️' })[s]

const s = {
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000 },
  modal: { background: '#161b22', border: '1px solid #30363d', borderRadius: 12, width: 720, maxHeight: '88vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', borderBottom: '1px solid #21262d', flexShrink: 0 },
  title: { fontWeight: 800, fontSize: 16, color: '#e6edf3' },
  closeBtn: { background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18, padding: '0 4px' },
  body: { display: 'flex', flex: 1, overflow: 'hidden' },
  nav: { width: 160, borderRight: '1px solid #21262d', padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 2, flexShrink: 0 },
  navBtn: { background: 'none', border: 'none', color: '#8b949e', padding: '8px 12px', borderRadius: 6, cursor: 'pointer', textAlign: 'left', fontSize: 13, fontWeight: 500 },
  navBtnActive: { background: '#1f6feb22', color: '#58a6ff', fontWeight: 700 },
  content: { flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' },
  section: { padding: 24, flex: 1 },
  sectionTitle: { fontSize: 14, fontWeight: 800, color: '#e6edf3', marginBottom: 6 },
  sectionDesc: { fontSize: 12, color: '#8b949e', marginBottom: 20, lineHeight: 1.6 },
  code: { background: '#21262d', padding: '1px 6px', borderRadius: 4, fontFamily: 'monospace', fontSize: 11 },

  apiKeyField: { background: '#0d1117', border: '1px solid #21262d', borderRadius: 8, padding: 14, marginBottom: 12 },
  apiKeyFieldHighlight: { border: '1px solid #388bfd44', background: '#0d111f' },
  apiKeyHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 },
  apiKeyLabel: { fontSize: 13, fontWeight: 700, color: '#e6edf3', marginBottom: 3 },
  apiKeySub: { fontSize: 11, color: '#8b949e', lineHeight: 1.5 },
  optionalTag: { fontSize: 10, color: '#8b949e', background: '#21262d', padding: '1px 6px', borderRadius: 10, marginLeft: 6, fontWeight: 400 },
  getKeyLink: { fontSize: 11, color: '#388bfd', textDecoration: 'none', whiteSpace: 'nowrap', marginLeft: 12, flexShrink: 0 },
  apiKeyInputRow: { display: 'flex', gap: 6, alignItems: 'center' },
  showBtn: { background: '#21262d', border: 'none', borderRadius: 5, padding: '6px 8px', cursor: 'pointer', fontSize: 14 },
  testBtn: { background: '#1f6feb', border: 'none', color: '#fff', borderRadius: 5, padding: '6px 12px', cursor: 'pointer', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' },
  testResult: { fontSize: 11, marginTop: 6, fontWeight: 600 },
  keyMeta: { fontSize: 10, color: '#8b949e', marginTop: 4 },

  fieldGroup: { display: 'flex', flexDirection: 'column', gap: 0 },
  field: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '14px 0', borderBottom: '1px solid #21262d' },
  fieldLabel: { fontSize: 13, fontWeight: 600, color: '#e6edf3', marginBottom: 3 },
  fieldSub: { fontSize: 11, color: '#8b949e', maxWidth: 320, lineHeight: 1.5 },
  fieldInput: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 },
  inputRow: { display: 'flex', alignItems: 'center', gap: 4 },
  input: { background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, padding: '7px 10px', color: '#e6edf3', outline: 'none', fontSize: 13, minWidth: 140 },
  prefix: { color: '#8b949e', fontSize: 14, marginRight: 2 },
  suffix: { color: '#8b949e', fontSize: 12, marginLeft: 4 },
  riskCalc: { fontSize: 11, color: '#8b949e', marginTop: 4 },

  aboutCard: { background: '#0d1117', border: '1px solid #21262d', borderRadius: 10, padding: 24, textAlign: 'center', marginBottom: 20 },
  aboutLogo: { fontSize: 40, marginBottom: 8 },
  aboutName: { fontSize: 22, fontWeight: 800, color: '#e6edf3' },
  aboutAI: { fontSize: 12, fontWeight: 700, color: '#388bfd', background: '#1f6feb22', padding: '2px 6px', borderRadius: 4, marginLeft: 4, verticalAlign: 'super' },
  aboutVersion: { fontSize: 12, color: '#8b949e', marginTop: 4, marginBottom: 12 },
  aboutDesc: { fontSize: 12, color: '#8b949e', lineHeight: 1.7, maxWidth: 400, margin: '0 auto' },
  stackList: { marginBottom: 20 },
  stackTitle: { fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 1, marginBottom: 8 },
  stackRow: { display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid #21262d', fontSize: 12 },
  stackName: { color: '#e6edf3', fontWeight: 600 },
  stackDesc: { color: '#8b949e' },
  disclaimer: { fontSize: 11, color: '#8b949e', background: '#161b22', border: '1px solid #21262d', borderRadius: 6, padding: '10px 14px', lineHeight: 1.6 },

  footer: { padding: '14px 24px', borderTop: '1px solid #21262d', flexShrink: 0, background: '#161b22' },
  saveBtn: { background: 'linear-gradient(135deg, #1f6feb, #388bfd)', border: 'none', color: '#fff', padding: '10px 28px', borderRadius: 7, cursor: 'pointer', fontWeight: 700, fontSize: 13 },
  saveBtnDone: { background: '#3fb950' },
}
