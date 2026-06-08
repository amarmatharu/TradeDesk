import { useEffect, useRef, useState } from 'react'
import { getStockHistory, getStockInfo, getStockTechnicals } from '../api.js'

const PERIODS = [
  { label: '1D', period: '1d', interval: '5m' },
  { label: '1W', period: '5d', interval: '15m' },
  { label: '1M', period: '1mo', interval: '1d' },
  { label: '3M', period: '3mo', interval: '1d' },
  { label: '6M', period: '6mo', interval: '1d' },
  { label: '1Y', period: '1y', interval: '1wk' },
]

export default function ChartPanel({ ticker }) {
  const chartRef = useRef(null)
  const chartInstance = useRef(null)
  const candleSeries = useRef(null)
  const volumeSeries = useRef(null)
  const [selectedPeriod, setSelectedPeriod] = useState(PERIODS[3])
  const [info, setInfo] = useState(null)
  const [technicals, setTechnicals] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let destroyed = false
    const init = async () => {
      if (!chartRef.current) return
      const { createChart, CandlestickSeries, HistogramSeries, ColorType } = await import('lightweight-charts')
      if (destroyed) return

      if (chartInstance.current) {
        chartInstance.current.remove()
        chartInstance.current = null
      }

      const chart = createChart(chartRef.current, {
        autoSize: true,
        layout: { background: { type: ColorType.Solid, color: '#0d1117' }, textColor: '#8b949e' },
        grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
        crosshair: { mode: 1 },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
      })

      candleSeries.current = chart.addSeries(CandlestickSeries, {
        upColor: '#3fb950', downColor: '#f85149',
        borderUpColor: '#3fb950', borderDownColor: '#f85149',
        wickUpColor: '#3fb950', wickDownColor: '#f85149',
      })

      volumeSeries.current = chart.addSeries(HistogramSeries, {
        color: '#388bfd44', priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      })
      chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

      chartInstance.current = chart
    }

    init()
    return () => { destroyed = true }
  }, [])

  useEffect(() => {
    loadData()
    loadInfo()
  }, [ticker, selectedPeriod])

  const loadData = async () => {
    if (!chartInstance.current) {
      setTimeout(loadData, 300)
      return
    }
    setLoading(true)
    try {
      const { data } = await getStockHistory(ticker, selectedPeriod.period, selectedPeriod.interval)
      if (!data?.length) return
      candleSeries.current?.setData(data)
      volumeSeries.current?.setData(data.map(d => ({ time: d.time, value: d.volume, color: d.close >= d.open ? '#3fb95044' : '#f8514944' })))
      chartInstance.current?.timeScale().fitContent()
    } catch (e) {}
    setLoading(false)
  }

  const loadInfo = async () => {
    try {
      const [i, t] = await Promise.all([getStockInfo(ticker), getStockTechnicals(ticker)])
      setInfo(i)
      setTechnicals(t)
    } catch (e) {}
  }

  const price = info?.current_price
  const high52 = info?.['52w_high']
  const low52 = info?.['52w_low']
  const pctFrom52High = high52 && price ? (((price - high52) / high52) * 100).toFixed(1) : null

  return (
    <div style={s.wrap}>
      {/* Stock header */}
      {info && (
        <div style={s.header}>
          <div style={s.headerLeft}>
            <div style={s.stockName}>{info.name}</div>
            <div style={s.stockMeta}>{info.sector} · {info.industry}</div>
          </div>
          <div style={s.priceBlock}>
            <div style={s.currentPrice}>${price?.toLocaleString()}</div>
            <div style={s.priceDetail}>
              <span style={s.label52}>52W: </span>
              <span>${low52?.toFixed(2)} – ${high52?.toFixed(2)}</span>
              {pctFrom52High && <span style={{ color: parseFloat(pctFrom52High) > -5 ? '#3fb950' : '#f78166', marginLeft: 6 }}>{pctFrom52High}% from high</span>}
            </div>
          </div>
          <div style={s.periodBar}>
            {PERIODS.map(p => (
              <button key={p.label} style={{ ...s.periodBtn, ...(selectedPeriod.label === p.label ? s.periodBtnActive : {}) }} onClick={() => setSelectedPeriod(p)}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Chart */}
      <div style={s.chartWrap}>
        {loading && <div style={s.loadOverlay}>Loading...</div>}
        <div ref={chartRef} style={{ width: '100%', height: '100%', position: 'absolute', inset: 0 }} />
      </div>

      {/* Technicals footer */}
      {technicals && !technicals.error && (
        <div style={s.technicals}>
          <TechBadge label="Trend" value={technicals.trend} type={technicals.trend === 'BULLISH' ? 'bull' : technicals.trend === 'BEARISH' ? 'bear' : 'neutral'} />
          <TechItem label="RSI" value={technicals.rsi?.toFixed(1)} sub={technicals.rsi_signal} />
          <TechItem label="MACD" value={technicals.macd_cross} sub={`${technicals.macd?.toFixed(2)} / ${technicals.macd_signal?.toFixed(2)}`} />
          <TechItem label="EMA20" value={`$${technicals.ema20?.toFixed(2)}`} />
          <TechItem label="EMA50" value={`$${technicals.ema50?.toFixed(2)}`} />
          <TechItem label="EMA200" value={`$${technicals.ema200?.toFixed(2)}`} />
          <TechItem label="Support" value={`$${technicals.support}`} sub="20-day" />
          <TechItem label="Resistance" value={`$${technicals.resistance}`} sub="20-day" />
          <TechItem label="ATR" value={`${technicals.atr_pct}%`} sub="volatility" />
          <TechItem label="BB%" value={technicals.bb_pct?.toFixed(2)} sub={technicals.bb_pct > 0.8 ? 'Near upper' : technicals.bb_pct < 0.2 ? 'Near lower' : 'Mid range'} />
        </div>
      )}
    </div>
  )
}

function TechBadge({ label, value, type }) {
  const color = type === 'bull' ? '#3fb950' : type === 'bear' ? '#f85149' : '#e3b341'
  return (
    <div style={s.techItem}>
      <div style={s.techLabel}>{label}</div>
      <div style={{ ...s.techVal, color, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

function TechItem({ label, value, sub }) {
  return (
    <div style={s.techItem}>
      <div style={s.techLabel}>{label}</div>
      <div style={s.techVal}>{value}</div>
      {sub && <div style={s.techSub}>{sub}</div>}
    </div>
  )
}

const s = {
  wrap: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0d1117' },
  header: { display: 'flex', alignItems: 'center', gap: 16, padding: '8px 16px', background: '#161b22', borderBottom: '1px solid #21262d', flexShrink: 0 },
  headerLeft: { flex: 1 },
  stockName: { fontWeight: 700, fontSize: 14, color: '#e6edf3' },
  stockMeta: { fontSize: 11, color: '#8b949e', marginTop: 2 },
  priceBlock: { textAlign: 'right' },
  currentPrice: { fontSize: 20, fontWeight: 800, color: '#e6edf3' },
  priceDetail: { fontSize: 11, color: '#8b949e', marginTop: 2 },
  label52: { color: '#8b949e' },
  periodBar: { display: 'flex', gap: 2 },
  periodBtn: { background: 'none', border: 'none', color: '#8b949e', padding: '4px 8px', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 11 },
  periodBtnActive: { background: '#21262d', color: '#58a6ff' },
  chartWrap: { flex: 1, position: 'relative', overflow: 'hidden', minHeight: 300 },
  loadOverlay: { position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', color: '#8b949e', zIndex: 10 },
  technicals: { display: 'flex', gap: 0, padding: '8px 12px', background: '#161b22', borderTop: '1px solid #21262d', overflowX: 'auto', flexShrink: 0 },
  techItem: { display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 70, padding: '0 8px', borderRight: '1px solid #21262d' },
  techLabel: { fontSize: 9, color: '#8b949e', fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase' },
  techVal: { fontSize: 12, fontWeight: 600, color: '#e6edf3', marginTop: 2 },
  techSub: { fontSize: 9, color: '#8b949e', marginTop: 1 },
}
