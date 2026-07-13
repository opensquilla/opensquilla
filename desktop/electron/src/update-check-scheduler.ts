// Pure scheduling for desktop update checks. Keeping Electron and updater
// state out of this module lets the timing and single-flight contracts run
// against a deterministic fake clock.

export interface UpdateCheckActivity {
  downloading: boolean
  applying: boolean
  downloaded: boolean
}

export function isUpdateCheckAllowed(activity: UpdateCheckActivity): boolean {
  return !activity.downloading && !activity.applying && !activity.downloaded
}

export interface UpdateCheckTimer {
  setTimeout(callback: () => void, delayMs: number): unknown
  clearTimeout(handle: unknown): void
}

export interface UpdateCheckSchedulerOptions {
  runCheck: () => Promise<void>
  canCheck: () => boolean
  repeatDelayMs: number
  timer?: UpdateCheckTimer
}

const systemTimer: UpdateCheckTimer = {
  setTimeout(callback, delayMs) {
    const handle = setTimeout(callback, delayMs)
    handle.unref?.()
    return handle
  },
  clearTimeout(handle) {
    clearTimeout(handle as ReturnType<typeof setTimeout>)
  },
}

/**
 * Runs update checks as a recursive timeout, measured from completion rather
 * than start. Manual callers join the current request and can promote a silent
 * automatic request to manual notification semantics without a second fetch.
 */
export class UpdateCheckScheduler {
  private readonly runCheck: () => Promise<void>
  private readonly canCheck: () => boolean
  private readonly repeatDelayMs: number
  private readonly timer: UpdateCheckTimer

  private timerHandle: unknown | null = null
  private inFlight: Promise<void> | null = null
  private started = false
  private stopped = false
  private manualRequested = false

  constructor(options: UpdateCheckSchedulerOptions) {
    this.runCheck = options.runCheck
    this.canCheck = options.canCheck
    this.repeatDelayMs = options.repeatDelayMs
    this.timer = options.timer ?? systemTimer
  }

  get manualRequestPending(): boolean {
    return this.manualRequested
  }

  consumeManualRequest(): boolean {
    const requested = this.manualRequested
    this.manualRequested = false
    return requested
  }

  start(initialDelayMs: number): void {
    if (this.started || this.stopped) return
    this.started = true
    if (!this.inFlight) this.schedule(initialDelayMs)
  }

  stop(): void {
    this.stopped = true
    this.clearScheduledCheck()
  }

  request(manual: boolean): Promise<void> {
    if (this.stopped) return Promise.resolve()

    if (this.inFlight) {
      if (manual) this.promoteToManual()
      return this.inFlight
    }

    if (!this.canCheck()) {
      // An automatic timer has already removed its handle before it reaches
      // this branch. Keep the recursive schedule alive while downloads or an
      // install are in progress, but do not disturb a pending timer when a
      // manual request is skipped.
      if (this.started && this.timerHandle === null) this.schedule(this.repeatDelayMs)
      return Promise.resolve()
    }

    this.clearScheduledCheck()
    if (manual) this.promoteToManual()

    let check: Promise<void>
    try {
      check = Promise.resolve(this.runCheck())
    } catch (error) {
      check = Promise.reject(error)
    }

    let tracked!: Promise<void>
    tracked = check.finally(() => {
      if (this.inFlight !== tracked) return
      this.inFlight = null
      this.manualRequested = false
      if (this.started && !this.stopped) this.schedule(this.repeatDelayMs)
    })
    this.inFlight = tracked
    return tracked
  }

  private promoteToManual(): void {
    if (this.manualRequested) return
    this.manualRequested = true
  }

  private schedule(delayMs: number): void {
    if (this.stopped) return
    this.clearScheduledCheck()
    this.timerHandle = this.timer.setTimeout(() => {
      this.timerHandle = null
      // The Electron-bound check reports its own errors. Keep the scheduler
      // alive if a future implementation unexpectedly rejects.
      void this.request(false).catch(() => {})
    }, delayMs)
  }

  private clearScheduledCheck(): void {
    if (this.timerHandle === null) return
    this.timer.clearTimeout(this.timerHandle)
    this.timerHandle = null
  }
}
