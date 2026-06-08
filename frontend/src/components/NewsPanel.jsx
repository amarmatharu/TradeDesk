import { useState, useEffect } from 'react'
import { getStockNews } from '../api.js'

export default function NewsPanel({ ticker }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setData(null)
    load()
  }, [ticker])

  const load = async () => {
    setLoading(true)
    try {
      const result = await getStockNews(ticker)
      setData(result)
    } catch (e) {}
    setLoading(false)
  }

  if (loading) return <div style={s.center}>Loading news for {ticker}...</div>

  const sentiment = data?.sentiment
  const news = data?.news || []

  return (
    <div style={s.wrap}>
      {/* Sentiment bar */}
      {sentiment && (
        <div style={s.sentBar}>
          <div style={{ ...s.sentBadge, color: sentColor(sentiment.sentiment), borderColor: sentColor(sentiment.sentiment) }}>
            {sentiment.sentiment}
          </div>
          <div style={s.sentSummary}>{sentiment.summary}</div>
          {(sentiment.key_themes || []).map((t, i) => (
            <span key={i} style={s.theme}>{t}</span>
          ))}
          <div style={s.sentScore}>
            Score: <strong style={{ color: sentColor(sentiment.sentiment) }}>{sentiment.score?.toFixed(2)}</strong>
          </div>
        </div>
      )}

      {/* News feed */}
      <div style={s.feed}>
        {news.length === 0 ? (
          <div style={s.empty}>No news found for {ticker}</div>
        ) : news.map((item, i) => (
          <a key={i} href={item.url} target="_blank" rel="noopener noreferrer" style={s.newsCard}>
            <div style={s.newsContent}>
              <div style={s.newsSource}>{item.source} · {formatDate(item.published)}</div>
              <div style={s.newsTitle}>{item.title}</div>
              {item.summary && <div style={s.newsSummary}>{item.summary?.substring(0, 180)}...</div>}
            </div>
            {item.thumbnail && (
              <img src={item.thumbnail} alt="" style={s.newsThumbnail} onError={e => e.target.style.display = 'none'} />
            )}
          </a>
        ))}
      </div>

      <button style={s.refresh} onClick={load}>↻ Refresh</button>
    </div>
  )
}

const sentColor = s => ({ BULLISH: '#3fb950', BEARISH: '#f85149', NEUTRAL: '#e3b341' })[s] || '#e3b341'

function formatDate(str) {
  if (!str) return ''
  try {
    return new Date(str).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return str?.substring(0, 10) || ''
  }
}

const s = {
  wrap: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#0d1117' },
  center: { display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, color: '#8b949e' },
  sentBar: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', background: '#161b22', borderBottom: '1px solid #21262d', flexWrap: 'wrap', flexShrink: 0 },
  sentBadge: { fontWeight: 800, fontSize: 12, border: '1px solid', padding: '2px 10px', borderRadius: 20 },
  sentSummary: { fontSize: 12, color: '#c9d1d9', flex: 1, minWidth: 200 },
  theme: { background: '#21262d', color: '#8b949e', fontSize: 10, padding: '2px 7px', borderRadius: 20 },
  sentScore: { fontSize: 11, color: '#8b949e', marginLeft: 'auto' },
  feed: { flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 },
  newsCard: { display: 'flex', gap: 12, background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: 14, textDecoration: 'none', transition: 'border-color .15s', cursor: 'pointer' },
  newsContent: { flex: 1 },
  newsSource: { fontSize: 10, color: '#8b949e', marginBottom: 4, fontWeight: 600 },
  newsTitle: { fontSize: 13, fontWeight: 700, color: '#e6edf3', lineHeight: 1.5, marginBottom: 6 },
  newsSummary: { fontSize: 11, color: '#8b949e', lineHeight: 1.5 },
  newsThumbnail: { width: 80, height: 60, objectFit: 'cover', borderRadius: 6, flexShrink: 0 },
  empty: { color: '#8b949e', padding: 24, textAlign: 'center' },
  refresh: { margin: '8px 12px', background: '#21262d', border: 'none', color: '#8b949e', padding: '7px', borderRadius: 6, cursor: 'pointer', fontSize: 12 },
}
