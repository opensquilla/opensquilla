export const SESSION_NAVIGATION_DIAG_STORAGE_KEY = 'opensquilla.chat.sessionNavigationDiag'
export const SESSION_NAVIGATION_DIAG_LIMIT = 200

export interface SessionNavigationDiagStorage {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
}

export interface SessionNavigationDiagEntry {
  t: number
  iso: string
  source: string
  from?: string
  to?: string
  current?: string
  routeSession?: string
  requestSession?: string
  responseSession?: string
  reason?: string
}

export type SessionNavigationDiagData = Omit<SessionNavigationDiagEntry, 't' | 'iso' | 'source'>

let storageOverride: SessionNavigationDiagStorage | null = null

export function setSessionNavigationDiagStorageForTest(storage: SessionNavigationDiagStorage | null) {
  storageOverride = storage
}

function storage(): SessionNavigationDiagStorage | null {
  if (storageOverride) return storageOverride
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function readSessionNavigationDiag(): SessionNavigationDiagEntry[] {
  const store = storage()
  if (!store) return []
  try {
    const raw = store.getItem(SESSION_NAVIGATION_DIAG_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(Boolean) : []
  } catch {
    return []
  }
}

export function clearSessionNavigationDiag() {
  const store = storage()
  if (!store) return
  try {
    store.removeItem(SESSION_NAVIGATION_DIAG_STORAGE_KEY)
  } catch {
    // Ignore diagnostics storage failures.
  }
}

export function recordSessionNavigationDiag(
  source: string,
  data: SessionNavigationDiagData = {},
): SessionNavigationDiagEntry | null {
  const store = storage()
  if (!store) return null
  const now = Date.now()
  const entry: SessionNavigationDiagEntry = {
    t: now,
    iso: new Date(now).toISOString(),
    source,
    ...data,
  }
  try {
    const next = [entry, ...readSessionNavigationDiag()].slice(0, SESSION_NAVIGATION_DIAG_LIMIT)
    store.setItem(SESSION_NAVIGATION_DIAG_STORAGE_KEY, JSON.stringify(next))
    return entry
  } catch {
    return null
  }
}

export function installSessionNavigationDiagConsole() {
  if (typeof window === 'undefined') return
  window.OpenSquillaSessionDiag = {
    read: readSessionNavigationDiag,
    clear: clearSessionNavigationDiag,
  }
}

declare global {
  interface Window {
    OpenSquillaSessionDiag?: {
      read: () => SessionNavigationDiagEntry[]
      clear: () => void
    }
  }
}
