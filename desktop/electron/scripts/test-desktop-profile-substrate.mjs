import assert from 'node:assert/strict'

import { DesktopContextLock } from '../dist/desktop-context-lock.js'
import { DesktopWriterAdmission } from '../dist/desktop-writer-admission.js'

const writers = new DesktopWriterAdmission()
const finishExistingWriter = writers.begin('existing recovery writer')
const lifecycleOwner = writers.close('apply downloaded update')
assert.equal(writers.closed, true)
assert.equal(writers.hasOwner(lifecycleOwner), true)
assert.throws(
  () => writers.begin('late context writer'),
  /writer admission is closed/,
)

let drained = false
const drain = writers.waitForAtMost(0).then(() => {
  drained = true
})
await Promise.resolve()
assert.equal(drained, false, 'lifecycle operation must wait for the active writer')
finishExistingWriter()
finishExistingWriter()
await drain
assert.equal(writers.activeCount, 0, 'writer completion must be idempotent')
assert.equal(writers.reopen(Symbol('unrelated owner')), false)
assert.equal(writers.closed, true, 'an unrelated owner must not reopen admission')
assert.equal(writers.reopen(lifecycleOwner), true)
assert.equal(writers.closed, false)
assert.throws(() => writers.waitForAtMost(-1), /non-negative integer/)

const exclusive = writers.tryBeginExclusive('recovery selection')
assert(exclusive, 'exclusive admission must atomically close and reserve a writer')
assert.equal(writers.closed, true)
assert.equal(writers.activeCount, 1)
assert.equal(writers.tryBeginExclusive('second recovery selection'), null)
exclusive.finish()
writers.reopen(exclusive.admissionToken)
assert.equal(writers.closed, false)
assert.equal(writers.activeCount, 0)

const contextLock = new DesktopContextLock()
let releaseFirst = () => {}
let markFirstStarted = () => {}
const firstMayFinish = new Promise((resolve) => {
  releaseFirst = resolve
})
const firstStarted = new Promise((resolve) => {
  markFirstStarted = resolve
})
const order = []
const first = contextLock.runExclusive('profile-context', async () => {
  order.push('first-start')
  markFirstStarted()
  await firstMayFinish
  order.push('first-end')
})
const second = contextLock.runExclusive('profile-context', () => {
  order.push('second')
})
await firstStarted
assert.deepEqual(order, ['first-start'], 'same-key operations must not overlap')
releaseFirst()
await Promise.all([first, second])
assert.deepEqual(order, ['first-start', 'first-end', 'second'])

await assert.rejects(
  contextLock.runExclusive('reentrant', () => contextLock.runExclusive('reentrant', () => {})),
  /cannot be re-entered/,
)
await assert.rejects(
  contextLock.runExclusive('failure-recovery', () => {
    throw new Error('synthetic failure')
  }),
  /synthetic failure/,
)
await contextLock.runExclusive('failure-recovery', () => {
  order.push('recovered')
})
assert.equal(order.at(-1), 'recovered', 'a rejected operation must not poison the queue')

console.log('desktop profile substrate checks passed')
