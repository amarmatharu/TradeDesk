const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electron', {
  getBackendPort: () => ipcRenderer.invoke('get-backend-port'),
  getVersion: () => ipcRenderer.invoke('get-version'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  onSwitchTab: (cb) => ipcRenderer.on('switch-tab', (_, tab) => cb(tab)),
  onOpenSettings: (cb) => ipcRenderer.on('open-settings', () => cb()),
})
