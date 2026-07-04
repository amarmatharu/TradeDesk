import axios from 'axios'

// In Electron (file:// protocol) we must use the full URL.
// In Vite dev server, the proxy handles /api → 8765, so '' works too.
// Using the explicit URL works in both cases since CORS allows all origins.
const BASE = 'http://localhost:8765'

const api = axios.create({ baseURL: BASE, timeout: 30000 })

export const getMarketOverview = () => api.get('/api/market/overview').then(r => r.data)
export const getStockInfo = (ticker) => api.get(`/api/stock/${ticker}`).then(r => r.data)
export const getStockHistory = (ticker, period = '3mo', interval = '1d') =>
  api.get(`/api/stock/${ticker}/history`, { params: { period, interval } }).then(r => r.data)
export const getStockTechnicals = (ticker) => api.get(`/api/stock/${ticker}/technicals`).then(r => r.data)
export const getStockNews = (ticker) => api.get(`/api/stock/${ticker}/news`).then(r => r.data)
export const analyzeStock = (ticker) => api.get(`/api/stock/${ticker}/analyze`).then(r => r.data)
export const getPositionSize = (entry, stop) =>
  api.get('/api/risk/size', { params: { entry, stop } }).then(r => r.data)

export const getPortfolio = () => api.get('/api/portfolio').then(r => r.data)
export const addTrade = (trade) => api.post('/api/portfolio/trade', trade).then(r => r.data)
export const closeTrade = (id, exit_price) =>
  api.put(`/api/portfolio/trade/${id}/close`, { exit_price }).then(r => r.data)
export const deleteTrade = (id) => api.delete(`/api/portfolio/trade/${id}`).then(r => r.data)

export const getWebullHoldings = () => api.get('/api/broker/webull/holdings').then(r => r.data)

// System Health (Phase 0-4 pro-grade endpoints)
export const getMetrics = () => api.get('/api/metrics').then(r => r.data)
export const getRecon = () => api.get('/api/recon').then(r => r.data)
export const getRegime = () => api.get('/api/regime').then(r => r.data)
export const getPromotion = () => api.get('/api/promotion').then(r => r.data)
export const getValidation = () => api.get('/api/validation').then(r => r.data)
export const getPortfolioRisk = () => api.get('/api/risk/portfolio').then(r => r.data)
export const getTacticalAllocation = () => api.get('/api/tactical/allocation').then(r => r.data)

export const getWatchlist = () => api.get('/api/watchlist').then(r => r.data)
export const addToWatchlist = (ticker) => api.post('/api/watchlist', { ticker }).then(r => r.data)
export const removeFromWatchlist = (ticker) => api.delete(`/api/watchlist/${ticker}`).then(r => r.data)
