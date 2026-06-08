import { useState, useEffect, useCallback } from 'react'
import Topbar from './components/Topbar.jsx'
import Sidebar from './components/Sidebar.jsx'
import ChartPanel from './components/ChartPanel.jsx'
import AnalysisPanel from './components/AnalysisPanel.jsx'
import NewsPanel from './components/NewsPanel.jsx'
import Portfolio from './components/Portfolio.jsx'
import AlertPanel from './components/AlertPanel.jsx'
import ScannerPanel from './components/ScannerPanel.jsx'
import EdgarPanel from './components/EdgarPanel.jsx'
import AgentsPanel from './components/AgentsPanel.jsx'
import TradeModal from './components/TradeModal.jsx'
import Settings from './components/Settings.jsx'
import { getMarketOverview, getWatchlist, getPortfolio } from './api.js'

const TABS = ['Chart', 'Analysis', 'News', 'Portfolio', 'Scanner', 'SEC', 'Agents']

export default function App() {
  const [activeTicker, setActiveTicker] = useState('NVDA')
  const [activeTab, setActiveTab] = useState('Chart')
  const [marketData, setMarketData] = useState({})
  const [watchlist, setWatchlist] = useState([])
  const [portfolio, setPortfolio] = useState({ positions: [], summary: {} })
  const [tradeModal, setTradeModal] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [alertCount, setAlertCount] = useState(0)    // unread critical/high alerts
  const [feedActive, setFeedActive] = useState(false)

  const refreshMarket = useCallback(async () => {
    try { setMarketData(await getMarketOverview()) } catch (e) {}
  }, [])

  const refreshWatchlist = useCallback(async () => {
    try { setWatchlist(await getWatchlist()) } catch (e) {}
  }, [])

  const refreshPortfolio = useCallback(async () => {
    try { setPortfolio(await getPortfolio()) } catch (e) {}
  }, [])

  useEffect(() => {
    refreshMarket()
    refreshWatchlist()
    refreshPortfolio()
    const interval = setInterval(() => {
      refreshMarket()
      refreshPortfolio()
    }, 60000)

    if (window.electron?.onSwitchTab) window.electron.onSwitchTab((tab) => setActiveTab(tab))
    if (window.electron?.onOpenSettings) window.electron.onOpenSettings(() => setShowSettings(true))

    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') { e.preventDefault(); setShowSettings(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => { clearInterval(interval); window.removeEventListener('keydown', onKey) }
  }, [])

  const handleSelectTicker = (ticker) => {
    setActiveTicker(ticker.toUpperCase())
    if (activeTab === 'Portfolio' || activeTab === 'News') setActiveTab('Chart')
  }

  const handleAlertTicker = (ticker) => {
    setActiveTicker(ticker.toUpperCase())
    setActiveTab('Analysis')
  }

  const handleNewAlert = (impact) => {
    if (activeTab !== 'Alerts' && ['CRITICAL', 'HIGH'].includes(impact)) {
      setAlertCount(n => n + 1)
    }
  }

  const openAlerts = () => {
    setActiveTab('Alerts')
    setAlertCount(0)
  }

  return (
    <div style={S.app}>
      <Topbar
        marketData={marketData}
        activeTicker={activeTicker}
        onOpenSettings={() => setShowSettings(true)}
        alertCount={alertCount}
        onOpenAlerts={openAlerts}
        feedActive={feedActive}
      />

      <div style={S.body}>
        <Sidebar
          watchlist={watchlist}
          activeTicker={activeTicker}
          onSelect={handleSelectTicker}
          onRefresh={refreshWatchlist}
          portfolio={portfolio}
        />

        <div style={S.main}>
          {/* Tab bar */}
          <div style={S.tabBar}>
            <div style={S.tickerBadge}>{activeTicker}</div>
            {TABS.map(t => (
              <button
                key={t}
                style={{ ...S.tab, ...(activeTab === t ? S.tabActive : {}) }}
                onClick={() => setActiveTab(t)}
              >
                {t}
                {t === 'Portfolio' && portfolio.summary.open_positions > 0 && (
                  <span style={S.badge}>{portfolio.summary.open_positions}</span>
                )}
              </button>
            ))}

            {/* Live Feed tab — always visible */}
            <button
              style={{ ...S.tab, ...(activeTab === 'Alerts' ? S.tabActive : {}), ...S.feedTab }}
              onClick={openAlerts}
            >
              <span style={{ ...S.feedDot, background: feedActive ? '#3fb950' : '#8b949e' }} />
              Live Feed
              {alertCount > 0 && <span style={S.alertBadge}>{alertCount}</span>}
            </button>

            <div style={S.rightActions}>
              <button style={S.analyzeBtn} onClick={() => setTradeModal({ ticker: activeTicker })}>
                ⚡ AI Analyze
              </button>
              <button style={S.settingsBtn} onClick={() => setShowSettings(true)} title="Settings (⌘,)">
                ⚙
              </button>
            </div>
          </div>

          {/* Main content + Alert panel side by side */}
          <div style={S.contentRow}>
            {/* Full-width tabs: Scanner and Alerts take everything */}
            {activeTab === 'Scanner' && (
              <div style={S.alertsFull}>
                <ScannerPanel onTrade={(d) => setTradeModal(d)} onSelectTicker={handleSelectTicker} />
              </div>
            )}
            {activeTab === 'SEC' && (
              <div style={S.alertsFull}>
                <EdgarPanel watchlistTickers={watchlist.map(w => w.ticker)} onSelectTicker={handleSelectTicker} />
              </div>
            )}
            {activeTab === 'Agents' && (
              <div style={S.alertsFull}>
                <AgentsPanel onSelectTicker={handleSelectTicker} />
              </div>
            )}
            {activeTab === 'Alerts' && (
              <div style={S.alertsFull}>
                <AlertPanel onSelectTicker={handleAlertTicker} onFeedStatus={setFeedActive} onNewAlert={handleNewAlert} />
              </div>
            )}

            {/* Standard tabs: main content + alert sidebar */}
            {activeTab !== 'Scanner' && activeTab !== 'Alerts' && (
              <>
                <div style={S.content}>
                  {activeTab === 'Chart'     && <ChartPanel ticker={activeTicker} />}
                  {activeTab === 'Analysis'  && <AnalysisPanel ticker={activeTicker} onTrade={(data) => setTradeModal(data)} />}
                  {activeTab === 'News'      && <NewsPanel ticker={activeTicker} />}
                  {activeTab === 'Portfolio' && <Portfolio portfolio={portfolio} onRefresh={refreshPortfolio} />}
                </div>
                <div style={S.alertsSidebar}>
                  <AlertPanel
                    onSelectTicker={handleAlertTicker}
                    onFeedStatus={setFeedActive}
                    onNewAlert={handleNewAlert}
                    compact
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {tradeModal && (
        <TradeModal
          ticker={tradeModal.ticker}
          prefill={tradeModal.analysis}
          onClose={() => setTradeModal(null)}
          onSubmit={() => { setTradeModal(null); refreshPortfolio() }}
        />
      )}

      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
    </div>
  )
}

const S = {
  app: { display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: '#0d1117' },
  body: { display: 'flex', flex: 1, overflow: 'hidden' },
  main: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' },
  tabBar: { display: 'flex', alignItems: 'center', gap: 2, padding: '6px 10px', background: '#161b22', borderBottom: '1px solid #21262d', flexShrink: 0, overflowX: 'auto' },
  tickerBadge: { fontWeight: 700, fontSize: 13, color: '#58a6ff', marginRight: 4, minWidth: 48, flexShrink: 0 },
  tab: { background: 'none', border: 'none', color: '#8b949e', padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontWeight: 500, fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap', flexShrink: 0 },
  tabActive: { background: '#1f6feb22', color: '#58a6ff', borderBottom: '2px solid #58a6ff' },
  badge: { background: '#f78166', color: '#fff', borderRadius: 10, padding: '1px 6px', fontSize: 10 },
  feedTab: { borderLeft: '1px solid #21262d', marginLeft: 4, paddingLeft: 12 },
  feedDot: { width: 6, height: 6, borderRadius: '50%', display: 'inline-block', flexShrink: 0 },
  alertBadge: { background: '#f85149', color: '#fff', borderRadius: 10, padding: '1px 6px', fontSize: 10, fontWeight: 800 },
  rightActions: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 },
  analyzeBtn: { background: 'linear-gradient(135deg, #1f6feb, #388bfd)', border: 'none', color: '#fff', padding: '6px 14px', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: 12 },
  settingsBtn: { background: '#21262d', border: 'none', color: '#8b949e', padding: '6px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 15 },
  contentRow: { display: 'flex', flex: 1, overflow: 'hidden' },
  content: { flex: 1, overflow: 'hidden' },
  alertsFull: { flex: 1, overflow: 'hidden', borderLeft: '1px solid #21262d' },
  alertsSidebar: { width: 300, flexShrink: 0, borderLeft: '1px solid #21262d', overflow: 'hidden' },
}
