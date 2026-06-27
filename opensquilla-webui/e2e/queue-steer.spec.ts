import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const LIVE = process.env.OPENSQUILLA_E2E_LIVE === '1'

const LONG_TASK = 'Write a detailed essay of at least 500 words about the history of the printing press. Do not stop early.'

async function openDraft(page: Page) {
  await page.goto(CONTROL_URL + 'chat/new')
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
}

async function startLongRun(page: Page) {
  const textarea = page.locator('.chat-textarea')
  await textarea.fill(LONG_TASK)
  await page.locator('.chat-send-btn[aria-label="Send"]').click()
  // The busy-mode toggle is the streaming signal: it only renders mid-run.
  await expect(page.locator('.chat-busy-mode')).toBeVisible({ timeout: 30000 })
}

test.describe('Queue/Steer composer semantics', () => {
  test('idle composer shows no delivery-mode toggle', async ({ page }) => {
    await openDraft(page)

    await expect(page.locator('.chat-textarea')).toBeVisible()
    await expect(page.locator('.chat-send-btn[aria-label="Send"]')).toBeVisible()
    await expect(page.locator('.chat-busy-mode')).toHaveCount(0)
    await expect(page.locator('.chat-pending-mode')).toHaveCount(0)
  })

  test('queue mode holds the message and auto-sends after the turn', async ({ page }) => {
    test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')
    test.setTimeout(240000)

    await openDraft(page)
    await startLongRun(page)

    // Queue is the default mode while running.
    await expect(page.getByRole('button', { name: 'Queue', exact: true })).toHaveAttribute('aria-pressed', 'true')

    const queuedText = 'After you finish, reply with the single word: queued-done'
    await page.locator('.chat-textarea').fill(queuedText)
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    // The draft waits in the visible pending queue, labeled with its mode.
    await expect(page.locator('.chat-pending-chip')).toHaveCount(1)
    await expect(page.locator('.chat-pending-mode')).toHaveText('Queue')
    await expect(page.locator('.msg-user')).toHaveCount(1)

    // After the first turn ends the queued draft auto-sends FIFO.
    await expect(page.locator('.msg-user')).toHaveCount(2, { timeout: 180000 })
    await expect(page.locator('.msg-user').nth(1)).toContainText('queued-done')
    await expect(page.locator('.chat-pending-chip')).toHaveCount(0)
  })

  test('steer mode sends immediately into the active run', async ({ page }) => {
    test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')
    test.setTimeout(240000)

    await openDraft(page)
    await startLongRun(page)

    await page.getByRole('button', { name: 'Steer', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Steer', exact: true })).toHaveAttribute('aria-pressed', 'true')

    const steerText = 'Stop the essay. Acknowledge this steering message and reply with just: steered-ok'
    await page.locator('.chat-textarea').fill(steerText)
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    // The steer message lands in the transcript right away — nothing queues.
    await expect(page.locator('.msg-user')).toHaveCount(2, { timeout: 15000 })
    await expect(page.locator('.msg-user').nth(1)).toContainText('steered-ok')
    await expect(page.locator('.chat-pending-chip')).toHaveCount(0)

    // The run continues mid-turn and reaches a terminal state with a reply
    // produced after the steering message was injected.
    await expect(page.locator('.chat-busy-mode')).toHaveCount(0, { timeout: 180000 })
    await expect(page.locator('.msg-ai').last()).toBeVisible()
    await expect(page.locator('.msg-ai').last()).toContainText(/steer/i, { timeout: 30000 })
  })
})
