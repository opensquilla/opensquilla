import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('opensquillaDesktop', {
  getOsLocale: () => ipcRenderer.invoke('desktop:os-locale'),
  isAutoUpdateEnabled: () => ipcRenderer.invoke('desktop:update:supported'),
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
  getRecoveryState: () => ipcRenderer.invoke('desktop:recovery:state'),
  chooseRecoveryWorkspace: (payload: unknown) => ipcRenderer.invoke('desktop:recovery:choose-workspace', payload),
  recoverProfileTransaction: () => ipcRenderer.invoke('desktop:recovery:recover-transaction'),
  launchSafeProfile: (payload: unknown) => ipcRenderer.invoke('desktop:recovery:launch-safe', payload),
  retryPrimaryProfile: () => ipcRenderer.invoke('desktop:recovery:retry-primary'),
  returnPrimaryProfile: () => ipcRenderer.invoke('desktop:recovery:return-primary'),
  revealRecoveryPath: (payload: unknown) => ipcRenderer.invoke('desktop:recovery:reveal-path', payload),
  copyRecoveryDiagnostics: () => ipcRenderer.invoke('desktop:recovery:copy-diagnostics'),
  uninstallSummary: () => ipcRenderer.invoke('desktop:uninstall:summary'),
  uninstallRun: (payload: unknown) => ipcRenderer.invoke('desktop:uninstall:run', payload),
  migrationSummary: (payload?: unknown) => ipcRenderer.invoke('desktop:migration:summary', payload),
  migrationBrowseSource: (payload: unknown) => ipcRenderer.invoke('desktop:migration:browse-source', payload),
  migrationRun: (payload: unknown) => ipcRenderer.invoke('desktop:migration:run', payload),
  migrationTakeLastResult: () => ipcRenderer.invoke('desktop:migration:last-result'),
  migrationPeekLastResult: () => ipcRenderer.invoke('desktop:migration:peek-last-result'),
  migrationDismissLastResult: () => ipcRenderer.invoke('desktop:migration:dismiss-last-result'),
  selectOnboardingMigration: (payload: unknown) => ipcRenderer.invoke('desktop:onboarding:migrate:select', payload),
  browseOnboardingMigration: (payload: unknown) => ipcRenderer.invoke('desktop:onboarding:migrate:browse', payload),
  previewOnboardingMigration: () => ipcRenderer.invoke('desktop:onboarding:migrate:preview'),
  applyOnboardingMigration: () => ipcRenderer.invoke('desktop:onboarding:migrate:apply'),
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
  onRecoveryState: (callback: (payload: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('desktop:recovery:state-changed', listener)
    return () => ipcRenderer.removeListener('desktop:recovery:state-changed', listener)
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
