import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('opensquillaDesktop', {
  getOsLocale: () => ipcRenderer.invoke('desktop:os-locale'),
  isAutoUpdateEnabled: () => ipcRenderer.invoke('desktop:update:supported'),
  isDesktopUpdateManaged: () => ipcRenderer.invoke('desktop:update:managed'),
  getUpdateState: () => ipcRenderer.invoke('desktop:update:state'),
  checkForUpdates: () => ipcRenderer.invoke('desktop:update:check'),
  downloadUpdate: () => ipcRenderer.invoke('desktop:update:download'),
  relaunchToUpdate: () => ipcRenderer.invoke('desktop:update:relaunch'),
  dismissUpdate: () => ipcRenderer.invoke('desktop:update:dismiss'),
  getGatewayStatus: () => ipcRenderer.invoke('gateway:status'),
  getCliInvocation: () => ipcRenderer.invoke('gateway:cli-invocation'),
  revealGatewayLog: () => ipcRenderer.invoke('gateway:reveal-log'),
  getDesktopSettings: () => ipcRenderer.invoke('desktop:settings:get'),
  saveDesktopSettings: (payload: unknown) => ipcRenderer.invoke('desktop:settings:save', payload),
  resetDesktopSettings: () => ipcRenderer.invoke('desktop:settings:reset'),
  setNativeTheme: (payload: unknown) => ipcRenderer.invoke('desktop:theme:set', payload),
  openArtifact: (payload: unknown) => ipcRenderer.invoke('desktop:artifact:open', payload),
  getOnboardingDefaults: () => ipcRenderer.invoke('desktop:onboarding:defaults'),
  saveOnboarding: (payload: unknown) => ipcRenderer.invoke('desktop:onboarding:save', payload),
  cancelOnboarding: () => ipcRenderer.invoke('desktop:onboarding:cancel'),
  getBootState: () => ipcRenderer.invoke('desktop:boot:state'),
  retryStartup: () => ipcRenderer.invoke('desktop:boot:retry'),
  quitApp: () => ipcRenderer.invoke('desktop:boot:quit'),
  getDesktopProfileKind: async () => 'primary',
  chooseLegacyAgentDataLocation: (payload: unknown) => ipcRenderer.invoke(
    'desktop:migration:choose-legacy-agent-data',
    payload,
  ),
  revealRecoveryPath: (payload: unknown) => ipcRenderer.invoke('desktop:data:reveal-path', payload),
  inspectDesktopCleanup: (payload: unknown) => ipcRenderer.invoke('desktop:cleanup:inspect', payload),
  discardDesktopCleanup: (payload: unknown) => ipcRenderer.invoke('desktop:cleanup:discard', payload),
  applyDesktopCleanup: (payload: unknown) => ipcRenderer.invoke('desktop:cleanup:apply', payload),
  revealDesktopUserData: () => ipcRenderer.invoke('desktop:cleanup:reveal-user-data'),
  migrationSummary: (payload?: unknown) => ipcRenderer.invoke('desktop:migration:summary', payload),
  getMigrationInspection: () => ipcRenderer.invoke('desktop:migration:inspection'),
  migrationBrowseSource: (payload: unknown) => ipcRenderer.invoke('desktop:migration:browse-source', payload),
  migrationRun: (payload: unknown) => ipcRenderer.invoke('desktop:migration:run', payload),
  migrationTakeLastResult: () => ipcRenderer.invoke('desktop:migration:last-result'),
  migrationPeekLastResult: () => ipcRenderer.invoke('desktop:migration:peek-last-result'),
  migrationDismissLastResult: () => ipcRenderer.invoke('desktop:migration:dismiss-last-result'),
  onBootStatus: (callback: (payload: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('desktop:boot:status', listener)
    return () => ipcRenderer.removeListener('desktop:boot:status', listener)
  },
  onBootError: (callback: (payload: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('desktop:boot:error', listener)
    return () => ipcRenderer.removeListener('desktop:boot:error', listener)
  },
  onUpdateState: (callback: (payload: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('desktop:update:state-changed', listener)
    return () => ipcRenderer.removeListener('desktop:update:state-changed', listener)
  },
  onMigrationProgress: (callback: (payload: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('desktop:migration:progress', listener)
    return () => ipcRenderer.removeListener('desktop:migration:progress', listener)
  },
})
