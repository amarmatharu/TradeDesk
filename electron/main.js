const { app, BrowserWindow, shell, ipcMain, Menu, Tray, nativeImage } = require('electron')
const path = require('path')
const { spawn, execSync } = require('child_process')
const http = require('http')
const fs = require('fs')

const isDev = process.env.ELECTRON_DEV === 'true'
const BACKEND_PORT = 8765
const FRONTEND_PORT = 5173

let mainWindow = null
let backendProcess = null
let tray = null

// ─── Logging ──────────────────────────────────────────────────────────────────
function log(msg) {
  console.log(`[TradeDesk] ${msg}`)
}

// ─── Backend ──────────────────────────────────────────────────────────────────
function getBackendDir() {
  if (isDev) return path.join(__dirname, '..', 'backend')
  return path.join(process.resourcesPath, 'backend')
}

function findPython() {
  const candidates = ['python3', 'python', '/usr/bin/python3', '/usr/local/bin/python3',
    '/opt/homebrew/bin/python3', `${process.env.HOME}/Library/Python/3.9/bin/python3`]
  for (const p of candidates) {
    try { execSync(`${p} --version`, { stdio: 'ignore' }); return p } catch {}
  }
  return 'python3'
}

async function waitForBackend(timeout = 20000) {
  const start = Date.now()
  return new Promise((resolve) => {
    const check = () => {
      http.get(`http://localhost:${BACKEND_PORT}/api/market/overview`, (res) => {
        if (res.statusCode === 200) return resolve(true)
        retry()
      }).on('error', retry)
    }
    const retry = () => {
      if (Date.now() - start > timeout) return resolve(false)
      setTimeout(check, 500)
    }
    check()
  })
}

async function isBackendAlreadyRunning() {
  return new Promise(resolve => {
    http.get(`http://localhost:${BACKEND_PORT}/api/market/overview`, res => {
      resolve(res.statusCode === 200)
    }).on('error', () => resolve(false))
  })
}

async function startBackend() {
  if (await isBackendAlreadyRunning()) {
    log('Backend already running — skipping spawn')
    return
  }
  const backendDir = getBackendDir()
  const python = findPython()

  log(`Starting backend with ${python} in ${backendDir}`)

  // Install deps silently if needed
  try {
    execSync(`${python} -m pip install -r "${path.join(backendDir, 'requirements.txt')}" -q --disable-pip-version-check`, {
      stdio: 'ignore', timeout: 60000
    })
  } catch (e) {
    log('Pip install warning: ' + e.message)
  }

  backendProcess = spawn(python, [
    '-m', 'uvicorn', 'main:app',
    '--host', '127.0.0.1',
    '--port', String(BACKEND_PORT),
    '--no-access-log'
  ], {
    cwd: backendDir,
    env: { ...process.env },
    stdio: ['ignore', 'pipe', 'pipe']
  })

  backendProcess.stdout.on('data', d => log('Backend: ' + d.toString().trim()))
  backendProcess.stderr.on('data', d => {
    const msg = d.toString().trim()
    if (msg && !msg.includes('INFO')) log('Backend err: ' + msg)
  })

  backendProcess.on('exit', (code) => {
    log(`Backend exited with code ${code}`)
    backendProcess = null
  })
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill('SIGTERM')
    backendProcess = null
  }
}

// ─── Window ───────────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#0d1117',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,  // allow localhost API calls
    },
    show: false,
    title: 'TradeDesk',
  })

  // Show splash while loading
  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    if (isDev) mainWindow.webContents.openDevTools({ mode: 'detach' })
  })

  mainWindow.on('closed', () => { mainWindow = null })

  // Open external links in browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  return mainWindow
}

function loadApp(win) {
  if (isDev) {
    win.loadURL(`http://localhost:${FRONTEND_PORT}`)
  } else {
    const distPath = path.join(process.resourcesPath, 'frontend_dist', 'index.html')
    win.loadFile(distPath)
  }
}

function showLoadingPage(win, message) {
  win.loadURL(`data:text/html,${encodeURIComponent(`
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          background: #0d1117;
          color: #e6edf3;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100vh;
          gap: 20px;
        }
        .logo { font-size: 48px; }
        .title { font-size: 28px; font-weight: 800; letter-spacing: -1px; }
        .title span { color: #388bfd; font-size: 14px; font-weight: 700; vertical-align: super; margin-left: 4px; }
        .msg { color: #8b949e; font-size: 14px; }
        .spinner {
          width: 32px; height: 32px;
          border: 3px solid #21262d;
          border-top: 3px solid #388bfd;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .dots { display: flex; gap: 6px; margin-top: 8px; }
        .dot { width: 6px; height: 6px; background: #388bfd; border-radius: 50%; animation: blink 1.2s infinite; }
        .dot:nth-child(2) { animation-delay: 0.4s; }
        .dot:nth-child(3) { animation-delay: 0.8s; }
        @keyframes blink { 0%,80%,100% { opacity: 0.2; } 40% { opacity: 1; } }
      </style>
    </head>
    <body>
      <div class="logo">📈</div>
      <div class="title">TradeDesk<span>AI</span></div>
      <div class="msg">${message}</div>
      <div class="spinner"></div>
      <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
    </body>
    </html>
  `)}`)
}

// ─── Menu ─────────────────────────────────────────────────────────────────────
function buildMenu() {
  const template = [
    {
      label: 'TradeDesk',
      submenu: [
        { label: 'About TradeDesk', role: 'about' },
        { type: 'separator' },
        { label: 'Preferences...', accelerator: 'Cmd+,', click: () => mainWindow?.webContents.send('open-settings') },
        { type: 'separator' },
        { label: 'Quit', accelerator: 'Cmd+Q', role: 'quit' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { label: 'Chart', accelerator: 'Cmd+1', click: () => mainWindow?.webContents.send('switch-tab', 'Chart') },
        { label: 'Analysis', accelerator: 'Cmd+2', click: () => mainWindow?.webContents.send('switch-tab', 'Analysis') },
        { label: 'News', accelerator: 'Cmd+3', click: () => mainWindow?.webContents.send('switch-tab', 'News') },
        { label: 'Portfolio', accelerator: 'Cmd+4', click: () => mainWindow?.webContents.send('switch-tab', 'Portfolio') },
        { type: 'separator' },
        { label: 'Reload', accelerator: 'Cmd+R', click: () => mainWindow?.reload() },
        { label: 'Toggle DevTools', accelerator: 'Cmd+Option+I', click: () => mainWindow?.webContents.toggleDevTools() },
        { label: 'Actual Size', role: 'resetZoom' },
        { label: 'Zoom In', role: 'zoomIn' },
        { label: 'Zoom Out', role: 'zoomOut' },
        { type: 'separator' },
        { label: 'Toggle Fullscreen', role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' }, { role: 'zoom' }, { role: 'close' }
      ]
    }
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// ─── IPC handlers ─────────────────────────────────────────────────────────────
ipcMain.handle('get-backend-port', () => BACKEND_PORT)
ipcMain.handle('get-version', () => app.getVersion())
ipcMain.handle('open-external', (_, url) => shell.openExternal(url))

// ─── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  buildMenu()
  const win = createWindow()

  // Show splash
  showLoadingPage(win, 'Starting AI Trading Engine...')

  // Start backend (skips if already running)
  await startBackend()

  // Wait for backend to be ready
  const ready = await waitForBackend()
  if (!ready) {
    log('Backend did not start in time — loading anyway')
  } else {
    log('Backend ready')
  }

  // Load the React app
  if (isDev) {
    // In dev: also start Vite, wait for it
    showLoadingPage(win, 'Loading interface...')
    await new Promise(r => setTimeout(r, 1500))
  }

  loadApp(win)
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})

app.on('before-quit', () => stopBackend())
