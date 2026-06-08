const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electron', {
  onSwitchTab:    (cb) => ipcRenderer.on('switch-tab',    (_, tab) => cb(tab)),
  onOpenSettings: (cb) => ipcRenderer.on('open-settings', (_) => cb()),
  platform: process.platform,
})
