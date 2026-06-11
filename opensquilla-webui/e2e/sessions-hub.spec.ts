import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const RAW_KEY_PATTERN = /agent:[a-z0-9_-]+:[a-z0-9_-]+:/i
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

async function openHub(page: Page) {
  await page.goto(CONTROL_URL + 'sessions')
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await page.waitForSelector('.conn-pill.connected', { timeout: 10000 }).catch(() => {})
  // Let the session ledger settle before inspecting it.
  await page.waitForTimeout(800)
  await expect(page.locator('.hub-ledger, .hub-state').first()).toBeVisible()
}

test.describe('Sessions Hub', () => {
  test('desktop / redirects to the Sessions Hub', async ({ page }) => {
    await page.goto(CONTROL_URL)
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await expect(page).toHaveURL(/\/sessions$/)
    await expect(page.locator('.hub-task__input')).toBeVisible()
  })

  test('mobile / still lands on chat', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await page.goto(CONTROL_URL)
    await page.waitForSelector('.conn-pill', { timeout: 10000 })
    await expect(page).toHaveURL(/\/chat/)
  })

  test('ledger rows show human titles, never raw keys or UUIDs', async ({ page }) => {
    await openHub(page)

    const rows = page.locator('.hub-row')
    test.skip((await rows.count()) === 0, 'No sessions on this gateway; seed sessions to exercise the ledger')

    const ledgerText = await page.locator('.hub-ledger').innerText()
    expect(ledgerText).not.toMatch(RAW_KEY_PATTERN)
    expect(ledgerText).not.toMatch(UUID_PATTERN)

    // Every row carries a non-empty title, an agent chip, and a time-ago cell.
    const firstRow = rows.first()
    expect((await firstRow.locator('.hub-row__title').innerText()).trim().length).toBeGreaterThan(0)
    await expect(firstRow.locator('.hub-row__agent')).toBeAttached()
    expect((await firstRow.locator('.hub-row__time').innerText()).trim().length).toBeGreaterThan(0)
  })

  test('filter chips narrow the ledger by session kind', async ({ page }) => {
    await openHub(page)

    const rows = page.locator('.hub-row')
    const total = await rows.count()
    test.skip(total === 0, 'No sessions on this gateway; seed sessions to exercise filters')

    // The sidebar has its own filter chips; scope to the hub's group.
    const chips = page.locator('.hub-filters')
    const chatsChip = chips.getByRole('button', { name: 'Chats', exact: true })
    await chatsChip.click()
    await expect(chatsChip).toHaveAttribute('aria-pressed', 'true')

    const filteredCount = await rows.count()
    if (filteredCount === 0) {
      // Honest filter-empty state with a way back.
      await expect(page.locator('.hub-state')).toContainText('No matches')
      await page.getByRole('button', { name: 'Clear filters' }).click()
    } else {
      for (const kind of await rows.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-kind')))) {
        expect(kind).toBe('chat')
      }
      await chips.getByRole('button', { name: 'All', exact: true }).click()
    }
    await expect(page.locator('.hub-row')).toHaveCount(total)
  })

  test('task input prefills the chat draft without sending', async ({ page }) => {
    await openHub(page)

    const taskText = 'Summarize the latest gateway logs'
    await page.locator('.hub-task__input').fill(taskText)
    await page.getByRole('button', { name: 'Start task' }).click()

    await expect(page).toHaveURL(/\/chat\/new\?agent=main$/)
    await expect(page.locator('.chat-textarea')).toHaveValue(taskText)
    // Draft only: nothing was sent.
    await expect(page.locator('.msg-user, .msg-ai')).toHaveCount(0)
  })

  test('row click opens the inspect drawer instead of navigating', async ({ page }) => {
    await openHub(page)

    const rows = page.locator('.hub-row')
    test.skip((await rows.count()) === 0, 'No sessions on this gateway; seed sessions to exercise row inspection')

    await rows.first().locator('.hub-row__main').click()
    await expect(page.locator('.inspect-drawer')).toBeVisible()
    await expect(page).toHaveURL(/\/sessions$/)
  })
})
