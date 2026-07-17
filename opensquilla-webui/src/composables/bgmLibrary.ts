/**
 * IndexedDB-backed store for background-music files the user adds through the
 * player ("Add local music…"). Kept as its own thin module so useBgm can be
 * unit-tested against an in-memory mock instead of a fake IndexedDB.
 *
 * Every function degrades gracefully when IndexedDB is unavailable (private
 * mode, exotic embedders): reads resolve empty and writes resolve false, and
 * the player falls back to session-only object URLs.
 */

export interface StoredBgmTrack {
  id: string
  title: string
  blob: Blob
  /** Insertion order; the picker lists uploads oldest-first. */
  seq: number
}

const DB_NAME = 'opensquilla-bgm'
const DB_VERSION = 1
const STORE = 'tracks'

function openDb(): Promise<IDBDatabase | null> {
  return new Promise(resolve => {
    let request: IDBOpenDBRequest
    try {
      request = indexedDB.open(DB_NAME, DB_VERSION)
    } catch {
      resolve(null)
      return
    }
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => resolve(null)
    request.onblocked = () => resolve(null)
  })
}

/** All stored uploads, oldest-first. Empty on any failure. */
export async function listLocalTracks(): Promise<StoredBgmTrack[]> {
  const db = await openDb()
  if (!db) return []
  return new Promise(resolve => {
    try {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).getAll()
      request.onsuccess = () => {
        db.close()
        const rows = Array.isArray(request.result) ? (request.result as StoredBgmTrack[]) : []
        resolve(rows.filter(r => r && typeof r.id === 'string' && r.blob instanceof Blob)
          .sort((a, b) => (a.seq || 0) - (b.seq || 0)))
      }
      request.onerror = () => {
        db.close()
        resolve([])
      }
    } catch {
      db.close()
      resolve([])
    }
  })
}

/** Persist one upload. False (not a throw) when storage is unavailable/full. */
export async function saveLocalTrack(track: StoredBgmTrack): Promise<boolean> {
  const db = await openDb()
  if (!db) return false
  return new Promise(resolve => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put(track)
      tx.oncomplete = () => {
        db.close()
        resolve(true)
      }
      tx.onerror = tx.onabort = () => {
        db.close()
        resolve(false)
      }
    } catch {
      db.close()
      resolve(false)
    }
  })
}

/** Rename one upload in place. False when the row is gone or storage fails. */
export async function renameLocalTrack(id: string, title: string): Promise<boolean> {
  const db = await openDb()
  if (!db) return false
  return new Promise(resolve => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      const store = tx.objectStore(STORE)
      let found = false
      const read = store.get(id)
      read.onsuccess = () => {
        const row = read.result as StoredBgmTrack | undefined
        if (row) {
          found = true
          store.put({ ...row, title })
        }
      }
      tx.oncomplete = () => {
        db.close()
        resolve(found)
      }
      tx.onerror = tx.onabort = () => {
        db.close()
        resolve(false)
      }
    } catch {
      db.close()
      resolve(false)
    }
  })
}

/** Remove one upload by id. Best-effort; resolves regardless. */
export async function deleteLocalTrack(id: string): Promise<void> {
  const db = await openDb()
  if (!db) return
  await new Promise<void>(resolve => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(id)
      tx.oncomplete = tx.onerror = tx.onabort = () => {
        db.close()
        resolve()
      }
    } catch {
      db.close()
      resolve()
    }
  })
}
