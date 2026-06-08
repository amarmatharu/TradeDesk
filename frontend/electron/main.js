const { app, BrowserWindow, Menu, shell } = require('electron')
const path = require('path')
const { spawn, execSync } = require('child_process')
const http = require('http')

// Fix GPU crash on macOS 15+ / Tahoe
app.disableHardwareAcceleration()
app.commandLine.appendSwitch('disable-gpu')
app.commandLine.appendSwitch('no-sandbox')

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged
const BACKEND_PORT = 8765
const FRONTEND_PORT = 5173

let mainWindow = null
let backendProcess = null

// ─── Check if backend already running ────────────────────────────────────────
function isBackendRunning() {
  return new Promise(resolve => {
    const req = http.get(`http://127.0.0.1:${BACKEND_PORT}/api/market/overview`, () => resolve(true))
    req.setTimeout(1000, () => { req.destroy(); resolve(false) })
    req.on('error', () => resolve(false))
  })
}

// ─── Start Python backend ─────────────────────────────────────────────────────
async function startBackend() {
  // Don't start if already running (e.g. from dev session)
  const already = await isBackendRunning()
  if (already) {
    console.log('[Electron] Backend already running on', BACKEND_PORT)
    return
  }

  const backendDir = app.isPackaged
    ? path.join(process.resourcesPath, 'backend')
    : path.join(__dirname, '../../backend')

  // Find python3 with our packages
  let python = '/usr/bin/python3'
  try {
    const found = execSync('which python3').toString().trim()
    if (found) python = found
  } catch (e) {}

  console.log('[Electron] Starting backend:', python, 'in', backendDir)

  backendProcess = spawn(python, [
    '-m', 'uvicorn', 'main:app',
    '--host', '127.0.0.1',
    '--port', String(BACKEND_PORT),
    '--no-access-log',
  ], {
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: '1', PATH: process.env.PATH + ':/usr/local/bin:/opt/homebrew/bin' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  backendProcess.stdout.on('data', d => console.log('[Backend]', d.toString().trim()))
  backendProcess.stderr.on('data', d => {
    const msg = d.toString().trim()
    if (msg) console.log('[Backend ERR]', msg)
  })
  backendProcess.on('exit', code => console.log('[Backend] exited', code))
}

// ─── Create window immediately — don't block on backend ──────────────────────
async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: '#0d1117',
    show: true,   // show immediately — don't wait for ready-to-show
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (isDev) {
    // Dev: Vite dev server
    mainWindow.loadURL(`http://localhost:${FRONTEND_PORT}`)
  } else {
    // Production: backend serves the built frontend at http://localhost:8765
    // This avoids file:// protocol issues entirely
    console.log('[Electron] Loading from backend:', `http://localhost:${BACKEND_PORT}`)
    mainWindow.loadURL(`http://localhost:${BACKEND_PORT}`)
  }

  mainWindow.webContents.on('did-fail-load', (_, code, desc, url) => {
    console.error('[Electron] Load failed:', code, desc, url)
    // Fallback: show error so window is visible
    mainWindow.webContents.loadURL(`data:text/html,<body style="background:#0d1117;color:#e6edf3;font-family:sans-serif;padding:40px"><h2>Loading failed</h2><p>${code}: ${desc}</p><p>${url}</p></body>`)
  })

  mainWindow.on('ready-to-show', () => mainWindow.focus())

  mainWindow.on('closed', () => { mainWindow = null })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
}

// ─── Menu ─────────────────────────────────────────────────────────────────────
function buildMenu() {
  const template = [
    {
      label: 'TradeDesk',
      submenu: [
        { label: 'About TradeDesk', role: 'about' },
        { type: 'separator' },
        { label: 'Settings (⌘,)', accelerator: 'Cmd+,',
          click: () => mainWindow?.webContents.send('open-settings') },
        { type: 'separator' },
        { label: 'Hide', role: 'hide' },
        { label: 'Quit', accelerator: 'Cmd+Q', role: 'quit' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { label: 'Chart',     accelerator: 'Cmd+1', click: () => mainWindow?.webContents.send('switch-tab', 'Chart') },
        { label: 'Analysis',  accelerator: 'Cmd+2', click: () => mainWindow?.webContents.send('switch-tab', 'Analysis') },
        { label: 'News',      accelerator: 'Cmd+3', click: () => mainWindow?.webContents.send('switch-tab', 'News') },
        { label: 'Portfolio', accelerator: 'Cmd+4', click: () => mainWindow?.webContents.send('switch-tab', 'Portfolio') },
        { label: 'Scanner',   accelerator: 'Cmd+5', click: () => mainWindow?.webContents.send('switch-tab', 'Scanner') },
        { label: 'Live Feed', accelerator: 'Cmd+6', click: () => mainWindow?.webContents.send('switch-tab', 'Alerts') },
        { type: 'separator' },
        { label: 'Reload', role: 'reload' },
        { label: 'Toggle DevTools', role: 'toggleDevTools' },
        { type: 'separator' },
        { label: 'Zoom In', role: 'zoomIn' },
        { label: 'Zoom Out', role: 'zoomOut' },
        { label: 'Reset Zoom', role: 'resetZoom' },
        { type: 'separator' },
        { label: 'Fullscreen', role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
      ],
    },
    {
      label: 'Window',
      submenu: [{ role: 'minimize' }, { role: 'zoom' }, { type: 'separator' }, { role: 'front' }],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// ─── Lifecycle ────────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  buildMenu()

  // Start backend + open window in parallel — window never blocks on backend
  startBackend()   // async, don't await
  await createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
})
