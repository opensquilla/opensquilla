import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const LIVE = process.env.OPENSQUILLA_E2E_LIVE === '1'
const SESSION_KEY = 'agent:main:webchat:e2eapproval'

interface MockApproval {
  id: string
  namespace: string
  toolName: string
  command?: string
  argv?: string[]
  args?: Record<string, unknown>
  warning?: string
  agent?: string
  sessionKey: string
  created_at?: number
}

const execApproval: MockApproval = {
  id: 'ap-e2e-1',
  namespace: 'exec',
  toolName: 'shell',
  command: 'rm -rf build/cache',
  args: { command: 'rm -rf build/cache' },
  agent: 'main',
  sessionKey: SESSION_KEY,
  created_at: Date.now() / 1000,
}

const genericApproval: MockApproval = {
  id: 'ap-e2e-2',
  namespace: 'exec',
  toolName: 'browser_navigate',
  args: { url: 'https://example.com/admin', reason: 'inspect dashboard' },
  sessionKey: SESSION_KEY,
}

function snapshot(pending: MockApproval[]) {
  return { pending, mode: 'prompt', allowPatterns: [], denyPatterns: [] }
}

async function mockApprovalsRoute(page: Page, getPending: () => MockApproval[]) {
  await page.route('**/api/approvals', route =>
    route.fulfill({ json: snapshot(getPending()) }))
}

async function openMockedChat(page: Page) {
  await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(SESSION_KEY))
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
}

test.describe('In-thread approval card (mocked snapshot)', () => {
  test('exec approval renders the command in a mono block with all three actions', async ({ page }) => {
    await mockApprovalsRoute(page, () => [execApproval])
    await openMockedChat(page)

    const card = page.getByTestId('approval-card')
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.locator('.approval-card__pre--cmd')).toContainText('rm -rf build/cache')
    await expect(card.getByText('Approval required')).toBeVisible()
    await expect(card.getByRole('button', { name: 'Allow once' })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Always allow this' })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Deny' })).toBeVisible()
    await expect(card.locator('.approval-card__note')).toBeVisible()
  })

  test('generic approval falls back to tool name plus formatted args', async ({ page }) => {
    await mockApprovalsRoute(page, () => [genericApproval])
    await openMockedChat(page)

    const card = page.getByTestId('approval-card')
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.locator('.approval-card__tool')).toHaveText('browser_navigate')
    await expect(card.locator('.approval-card__pre')).toContainText('https://example.com/admin')
    // No command — the "always allow" rule shortcut is exec-command-only.
    await expect(card.getByRole('button', { name: 'Always allow this' })).toHaveCount(0)
  })

  test('Allow once resolves and collapses into an approved outcome row', async ({ page }) => {
    let resolved = false
    await mockApprovalsRoute(page, () => (resolved ? [] : [execApproval]))
    await page.route('**/api/approvals/resolve', async route => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      expect(body.id).toBe('ap-e2e-1')
      expect(body.approved).toBe(true)
      expect(body.allowAlways).toBe(false)
      resolved = true
      await route.fulfill({ json: { ok: true } })
    })
    await openMockedChat(page)

    const card = page.getByTestId('approval-card')
    await expect(card).toBeVisible({ timeout: 10000 })
    await card.getByRole('button', { name: 'Allow once' }).click()

    const outcome = page.getByTestId('approval-outcome')
    await expect(outcome).toBeVisible()
    await expect(outcome).toContainText('Approved · run resumed')
    await expect(page.getByTestId('approval-card')).toHaveCount(0)
  })

  test('Always allow resolves with the allow-rule flags set', async ({ page }) => {
    let resolved = false
    await mockApprovalsRoute(page, () => (resolved ? [] : [execApproval]))
    await page.route('**/api/approvals/resolve', async route => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      expect(body.approved).toBe(true)
      expect(body.allowAlways).toBe(true)
      expect(body.rememberIntent).toBe(true)
      resolved = true
      await route.fulfill({ json: { ok: true } })
    })
    await openMockedChat(page)

    const card = page.getByTestId('approval-card')
    await expect(card).toBeVisible({ timeout: 10000 })
    await card.getByRole('button', { name: 'Always allow this' }).click()

    await expect(page.getByTestId('approval-outcome')).toContainText('Approved · always allowed')
  })

  test('Deny sends approved=false and queues the optional note for the agent', async ({ page }) => {
    let resolved = false
    await mockApprovalsRoute(page, () => (resolved ? [] : [execApproval]))
    await page.route('**/api/approvals/resolve', async route => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      expect(body.id).toBe('ap-e2e-1')
      expect(body.approved).toBe(false)
      resolved = true
      await route.fulfill({ json: { ok: true } })
    })
    await openMockedChat(page)

    const card = page.getByTestId('approval-card')
    await expect(card).toBeVisible({ timeout: 10000 })
    await card.locator('.approval-card__note').fill('use the staging directory instead')
    await card.getByRole('button', { name: 'Deny' }).click()

    await expect(page.getByTestId('approval-outcome')).toContainText('Denied')
    // The note rides the normal send path; with no live turn it lands in the
    // visible message flow (user bubble) or the pending queue chip.
    await expect(
      page.locator('.chat-pending-chip, .msg-user').filter({ hasText: 'staging directory' }).first(),
    ).toBeVisible()
  })

  test('topbar pill deep-links to the blocked session chat, not the Approvals page', async ({ page }) => {
    await mockApprovalsRoute(page, () => [execApproval])
    await openMockedChat(page)

    const pill = page.locator('.approval-inline')
    await expect(pill).toBeVisible({ timeout: 10000 })
    await pill.click()

    await expect(page).toHaveURL(new RegExp('/chat\\?session='))
    expect(page.url()).not.toContain('/approvals')
    await expect(page.getByTestId('approval-card')).toBeVisible()
  })
})

test.describe('Approval flow (live gateway, Ask-every-time strategy)', () => {
  test.skip(!LIVE, 'Live gateway test; set OPENSQUILLA_E2E_LIVE=1 to run.')

  test.beforeEach(async ({ request }) => {
    const res = await request.post('/api/approvals/settings', {
      data: { mode: 'prompt' },
    })
    expect(res.ok()).toBeTruthy()
  })

  test.afterEach(async ({ request }) => {
    await request.post('/api/approvals/settings', { data: { mode: 'prompt' } })
  })

  test('blocked shell command surfaces a card; Allow once resumes the run', async ({ page }) => {
    test.slow()
    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill.connected', { timeout: 15000 })

    const textarea = page.locator('.chat-textarea')
    // `rm` is on the shell warnlist, so this command blocks on approval; the
    // file does not exist and -f makes the command a harmless no-op once allowed.
    await textarea.fill('Run this exact shell command with your shell tool, then repeat the exact command you ran and its exit code: rm -f approval-e2e-ok.txt')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    const card = page.getByTestId('approval-card')
    await expect(card).toBeVisible({ timeout: 90000 })
    await expect(card.locator('.approval-card__pre--cmd')).toContainText('approval-e2e-ok')

    await card.getByRole('button', { name: 'Allow once' }).click()
    await expect(page.getByTestId('approval-outcome')).toContainText('Approved · run resumed')
    await expect(page.locator('.msg-ai').last()).toContainText('approval-e2e-ok', { timeout: 120000 })
  })

  test('Deny terminates the command and the note reaches the agent', async ({ page }) => {
    test.slow()
    await page.goto(CONTROL_URL + 'chat/new')
    await page.waitForSelector('.conn-pill.connected', { timeout: 15000 })

    const textarea = page.locator('.chat-textarea')
    // Warnlisted command (see the Allow-once test): guaranteed to raise an approval.
    await textarea.fill('Run this exact shell command with your shell tool, then repeat the exact command you ran and its exit code: rm -f approval-e2e-deny.txt')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    const card = page.getByTestId('approval-card')
    await expect(card).toBeVisible({ timeout: 90000 })

    await card.locator('.approval-card__note').fill('do not run shell commands in this session')
    await card.getByRole('button', { name: 'Deny' }).click()
    await expect(page.getByTestId('approval-outcome')).toContainText('Denied')

    // The note is delivered through the queue once the denied turn settles.
    await expect(
      page.locator('.msg-user').filter({ hasText: 'do not run shell commands' }).first(),
    ).toBeVisible({ timeout: 120000 })
  })
})
