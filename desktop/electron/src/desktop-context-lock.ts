import { AsyncLocalStorage } from 'node:async_hooks'

/**
 * Process-local keyed lock for Desktop-owned context files.
 *
 * The Electron main process owns the application single-instance lock before
 * it activates profile writes. Every cooperative context writer must also use
 * this lock, so a read/check/publish transaction cannot be interleaved by a
 * second Desktop code path inside the owning process.
 */
export class DesktopContextLock {
  private readonly ownership = new AsyncLocalStorage<ReadonlySet<string>>()
  private readonly tails = new Map<string, Promise<void>>()

  async runExclusive<T>(key: string, operation: () => T | Promise<T>): Promise<T> {
    if (!key) throw new Error('Desktop context lock requires a non-empty key.')
    if (this.ownership.getStore()?.has(key)) {
      throw new Error('Desktop context lock cannot be re-entered for the same key.')
    }

    const previous = this.tails.get(key) ?? Promise.resolve()
    const queued = previous.catch(() => undefined).then(async () => {
      const held = new Set(this.ownership.getStore() ?? [])
      held.add(key)
      return this.ownership.run(held, operation)
    })
    const tail = queued.then(() => undefined, () => undefined)
    this.tails.set(key, tail)
    try {
      return await queued
    } finally {
      if (this.tails.get(key) === tail) this.tails.delete(key)
    }
  }
}
