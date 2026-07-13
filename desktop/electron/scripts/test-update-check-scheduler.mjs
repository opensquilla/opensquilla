import assert from 'node:assert/strict'

import {
  isUpdateCheckAllowed,
  UpdateCheckScheduler,
} from '../dist/update-check-scheduler.js'

const DAY_MS = 24 * 60 * 60 * 1000

class FakeClock {
  now = 0
  nextId = 1
  tasks = new Map()

  timer = {
    setTimeout: (callback, delayMs) => {
      const id = this.nextId++
      this.tasks.set(id, { callback, dueAt: this.now + delayMs })
      return id
    },
    clearTimeout: (id) => {
      this.tasks.delete(id)
    },
  }

  get pendingCount() {
    return this.tasks.size
  }

  nextDueAt() {
    return Math.min(...[...this.tasks.values()].map((task) => task.dueAt))
  }

  async advanceBy(durationMs) {
    const target = this.now + durationMs
    for (;;) {
      const next = [...this.tasks.entries()]
        .filter(([, task]) => task.dueAt <= target)
        .sort((left, right) => left[1].dueAt - right[1].dueAt)[0]
      if (!next) break
      const [id, task] = next
      this.tasks.delete(id)
      this.now = task.dueAt
      task.callback()
      await flushPromises()
    }
    this.now = target
    await flushPromises()
  }
}

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

function deferred() {
  let resolve
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

// Download, apply, and already-downloaded states all suppress network checks.
assert.equal(isUpdateCheckAllowed({ downloading: false, applying: false, downloaded: false }), true)
assert.equal(isUpdateCheckAllowed({ downloading: true, applying: false, downloaded: false }), false)
assert.equal(isUpdateCheckAllowed({ downloading: false, applying: true, downloaded: false }), false)
assert.equal(isUpdateCheckAllowed({ downloading: false, applying: false, downloaded: true }), false)

// Startup waits 12 seconds. The recurring delay begins only after completion.
{
  const clock = new FakeClock()
  const first = deferred()
  const second = deferred()
  let runs = 0
  const scheduler = new UpdateCheckScheduler({
    timer: clock.timer,
    repeatDelayMs: DAY_MS,
    canCheck: () => true,
    runCheck: () => {
      runs += 1
      return runs === 1 ? first.promise : second.promise
    },
  })

  scheduler.start(12_000)
  await clock.advanceBy(11_999)
  assert.equal(runs, 0)
  await clock.advanceBy(1)
  assert.equal(runs, 1)
  assert.equal(clock.pendingCount, 0, 'no next timer while a check is in flight')

  await clock.advanceBy(5_000)
  first.resolve()
  await first.promise
  await flushPromises()
  assert.equal(clock.nextDueAt(), clock.now + DAY_MS, 'repeat delay starts at completion')

  await clock.advanceBy(DAY_MS - 1)
  assert.equal(runs, 1)
  await clock.advanceBy(1)
  assert.equal(runs, 2)
  second.resolve()
  await second.promise
  await flushPromises()
  scheduler.stop()
}

// A manual request joins an automatic check, promotes its notification mode,
// and shares exactly the same promise/network operation.
{
  const clock = new FakeClock()
  const active = deferred()
  let runs = 0
  const scheduler = new UpdateCheckScheduler({
    timer: clock.timer,
    repeatDelayMs: DAY_MS,
    canCheck: () => true,
    runCheck: () => {
      runs += 1
      return active.promise
    },
  })

  scheduler.start(12_000)
  const automatic = scheduler.request(false)
  const manual = scheduler.request(true)
  assert.equal(automatic, manual, 'manual caller must join the active promise')
  assert.equal(runs, 1)
  assert.equal(scheduler.manualRequestPending, true)

  // Repeated manual callers do not start another check.
  assert.equal(scheduler.request(true), automatic)
  assert.equal(runs, 1)

  active.resolve()
  await automatic
  assert.equal(scheduler.manualRequestPending, false)
  assert.equal(clock.nextDueAt(), clock.now + DAY_MS)
  scheduler.stop()
}

// The notification consumer handles a manual result once. A later manual join
// can promote the same still-running request again if needed.
{
  const active = deferred()
  let runs = 0
  const scheduler = new UpdateCheckScheduler({
    repeatDelayMs: DAY_MS,
    canCheck: () => true,
    runCheck: () => {
      runs += 1
      return active.promise
    },
  })
  const automatic = scheduler.request(false)
  assert.equal(scheduler.request(true), automatic)
  assert.equal(scheduler.consumeManualRequest(), true)
  assert.equal(scheduler.consumeManualRequest(), false)
  assert.equal(scheduler.request(true), automatic)
  assert.equal(scheduler.manualRequestPending, true)
  assert.equal(runs, 1)
  active.resolve()
  await automatic
}

// A busy updater skips the network and retains the daily recursive schedule.
{
  const clock = new FakeClock()
  let busy = true
  let runs = 0
  const scheduler = new UpdateCheckScheduler({
    timer: clock.timer,
    repeatDelayMs: DAY_MS,
    canCheck: () => !busy,
    runCheck: async () => {
      runs += 1
    },
  })

  scheduler.start(12_000)
  await clock.advanceBy(12_000)
  assert.equal(runs, 0)
  assert.equal(clock.nextDueAt(), clock.now + DAY_MS)
  busy = false
  await clock.advanceBy(DAY_MS)
  assert.equal(runs, 1)
  scheduler.stop()
}

// Failure still rearms after completion, while stop clears startup and repeat
// timers and prevents an in-flight check from rearming during app teardown.
{
  const clock = new FakeClock()
  let runs = 0
  const scheduler = new UpdateCheckScheduler({
    timer: clock.timer,
    repeatDelayMs: DAY_MS,
    canCheck: () => true,
    runCheck: async () => {
      runs += 1
      throw new Error('synthetic failure')
    },
  })
  scheduler.start(12_000)
  await clock.advanceBy(12_000)
  assert.equal(runs, 1)
  assert.equal(clock.nextDueAt(), clock.now + DAY_MS)
  scheduler.stop()
  assert.equal(clock.pendingCount, 0)
  await clock.advanceBy(DAY_MS * 2)
  assert.equal(runs, 1)
}

{
  const clock = new FakeClock()
  const active = deferred()
  const scheduler = new UpdateCheckScheduler({
    timer: clock.timer,
    repeatDelayMs: DAY_MS,
    canCheck: () => true,
    runCheck: () => active.promise,
  })
  scheduler.start(12_000)
  const check = scheduler.request(false)
  scheduler.stop()
  active.resolve()
  await check
  assert.equal(clock.pendingCount, 0, 'quit must prevent post-check rearming')
}

console.log('Update check scheduler tests passed.')
