import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const SESSION_KEY = 'agent:main:webchat:e2edeliverables'
const EMPTY_SESSION_KEY = 'agent:main:webchat:e2edeliverablesempty'

// Seed a finished turn through the real WS pipeline: the page talks to the
// real gateway, but chat.history responses are rewritten in flight so a
// deliverable-bearing assistant turn renders without a live agent run.
async function seedHistory(page: Page, withArtifacts: boolean) {
  await page.routeWebSocket(/\/ws$/, ws => {
    const server = ws.connectToServer()
    const historyIds = new Set<string>()
    ws.onMessage(message => {
      try {
        const frame = JSON.parse(String(message))
        if (frame?.type === 'req' && frame.method === 'chat.history') {
          historyIds.add(String(frame.id))
        }
      } catch {}
      server.send(message)
    })
    server.onMessage(message => {
      try {
        const frame = JSON.parse(String(message))
        if (frame?.type === 'res' && frame.id !== undefined && historyIds.has(String(frame.id))) {
          historyIds.delete(String(frame.id))
          frame.ok = true
          delete frame.error
          frame.payload = {
            messages: [
              {
                role: 'user',
                text: 'Save a couple of files for me.',
                id: 'msg-deliv-user',
                timestamp: Math.floor(Date.now() / 1000) - 120,
              },
              {
                role: 'assistant',
                text: withArtifacts ? 'Saved the files.' : 'Nothing to save on this turn.',
                id: 'msg-deliv-assistant',
                timestamp: Math.floor(Date.now() / 1000) - 60,
                artifacts: withArtifacts
                  ? [
                    { id: 'art-deliv-1', name: 'report.csv', mime: 'text/csv', size: 2048 },
                    { id: 'art-deliv-2', name: 'notes.txt', mime: 'text/plain', size: 512 },
                  ]
                  : [],
                tool_calls: withArtifacts
                  ? [
                    {
                      tool_use_id: 'tool-deliv-source',
                      name: 'web_search',
                      input: { query: 'OpenSquilla report source' },
                      sources: [
                        {
                          title: 'OpenSquilla report reference',
                          url: 'https://example.com/opensquilla-report',
                          domain: 'example.com',
                          fetched: true,
                        },
                      ],
                      result: '{"ok":true}',
                      status: 'success',
                    },
                  ]
                  : [],
              },
            ],
            has_more: false,
          }
          ws.send(JSON.stringify(frame))
          return
        }
      } catch {}
      ws.send(message)
    })
  })
}

async function openSeededSession(page: Page, key: string, withArtifacts: boolean) {
  await seedHistory(page, withArtifacts)
  await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(key))
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await page.waitForSelector('.chat-header', { timeout: 10000 })
}

test.describe('Per-session deliverables rail', () => {
  test('rail and trigger are absent when the session has no artifacts', async ({ page }) => {
    await openSeededSession(page, EMPTY_SESSION_KEY, false)
    await expect(page.locator('.msg-ai-main').last()).toBeVisible({ timeout: 10000 })
    await expect(page.locator('.chat-deliverables-btn')).toHaveCount(0)
    await expect(page.locator('.chat-context-rail-toggle')).toHaveCount(0)
    await expect(page.locator('.chat-context-rail')).toHaveCount(0)
  })

  test('desktop keeps artifacts visible in a collapsible complementary rail', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)

    const trigger = page.locator('.chat-deliverables-btn')
    await expect(trigger).toBeHidden({ timeout: 10000 })

    const railToggle = page.locator('.chat-context-rail-toggle')
    await expect(railToggle).toBeVisible()
    await expect(railToggle).toHaveAttribute('aria-expanded', 'true')
    await expect(railToggle.locator('svg rect')).toHaveCount(1)
    await expect(railToggle.locator('svg path')).toHaveAttribute('d', 'M16 3v18')
    await expect(railToggle.locator('svg polyline')).toHaveCount(0)
    await expect(page.locator('.chat-header .chat-context-rail-toggle')).toHaveCount(0)

    const rail = page.locator('.chat-context-rail')
    await expect(rail.locator('.deliv-head .chat-context-rail-toggle')).toHaveCount(1)
    const drawer = rail.locator('.deliv-drawer--rail')
    await expect(rail).toBeVisible()
    await expect(drawer).toHaveAttribute('role', 'complementary')
    await expect(drawer).not.toHaveAttribute('aria-modal', 'true')
    await expect(drawer).toHaveAttribute('aria-label', /Deliverables \(2\)/)

    // Both deliverables render as tiles.
    await expect(rail.locator('.deliv-tile')).toHaveCount(2)
    await expect(rail.locator('.deliv-tile__name').first()).toHaveText('report.csv')
    // Tile meta uses the clean TYPE · size copy, not a doubled category.
    await expect(rail.locator('.deliv-tile__meta').first()).toHaveText('CSV · 2 KB')
    await expect(rail.locator('.deliv-sources')).toHaveCount(0)

    // The title and count stay grouped on the left; the rail control owns the
    // far-right edge of the header.
    const headerOrder = await rail.locator('.deliv-head').evaluate(el =>
      Array.from(el.children).map(child => child.className),
    )
    expect(headerOrder).toEqual(expect.arrayContaining(['deliv-head__summary']))
    expect(headerOrder.at(-1)).toContain('deliv-head__rail-toggle')

    // The rail owns a distinct column to the right of the transcript.
    const geometry = await page.evaluate(() => {
      const body = document.querySelector('.chat-body')?.getBoundingClientRect()
      const contextRail = document.querySelector('.chat-context-rail')?.getBoundingClientRect()
      return body && contextRail
        ? { bodyRight: body.right, railLeft: contextRail.left, railWidth: contextRail.width }
        : null
    })
    expect(geometry).not.toBeNull()
    expect(geometry!.railLeft).toBeGreaterThanOrEqual(geometry!.bodyRight)
    expect(geometry!.railWidth).toBeGreaterThanOrEqual(229)

    const bodyWidthWithRail = await page.locator('.chat-body').evaluate(el => el.getBoundingClientRect().width)
    await railToggle.click()
    await expect(railToggle).toHaveAttribute('aria-expanded', 'false')
    await expect(page.locator('.chat-context-rail')).toBeVisible()
    await expect(drawer).toHaveClass(/deliv-drawer--rail-collapsed/)
    await expect(rail.locator('.deliv-body')).toHaveCount(0)
    await expect(rail.locator('.deliv-head .chat-context-rail-toggle')).toBeVisible()
    await expect(page.locator('.chat')).toHaveClass(/chat--context-rail-collapsed/)
    const bodyWidthWithoutRail = await page.locator('.chat-body').evaluate(el => el.getBoundingClientRect().width)
    expect(bodyWidthWithoutRail).toBeGreaterThan(bodyWidthWithRail)

    await railToggle.click()
    await expect(railToggle).toHaveAttribute('aria-expanded', 'true')
    await expect(page.locator('.chat-context-rail')).toBeVisible()
    await expect(drawer).not.toHaveClass(/deliv-drawer--rail-collapsed/)
  })

  test('non-image deliverable opens a metadata preview with a download action', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)

    const rail = page.locator('.chat-context-rail')
    await expect(rail).toBeVisible({ timeout: 10000 })
    await rail.locator('.deliv-tile').first().click()

    const preview = page.locator('.deliv-preview')
    await expect(preview).toBeVisible()
    await expect(preview).toHaveAttribute('aria-modal', 'true')
    await expect(preview.locator('.deliv-preview__file')).toBeVisible()
    await expect(preview.getByRole('button', { name: 'Download' })).toBeVisible()

    // Escape closes only the preview; the persistent rail remains.
    await page.keyboard.press('Escape')
    await expect(preview).toHaveCount(0)
    await expect(rail).toBeVisible()
  })

  test('mobile renders the drawer full-screen', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await openSeededSession(page, SESSION_KEY, true)

    await expect(page.locator('.chat-context-rail')).toHaveCount(0)
    await expect(page.locator('.chat-context-rail-toggle')).toBeHidden()
    const trigger = page.locator('.chat-deliverables-btn')
    await expect(trigger).toBeVisible()
    await trigger.click()
    const drawer = page.locator('.deliv-drawer:not(.deliv-drawer--rail)')
    await expect(drawer).toBeVisible()
    await expect(drawer).toHaveAttribute('role', 'dialog')
    await expect(drawer).toHaveAttribute('aria-modal', 'true')

    const width = await drawer.evaluate(el => el.getBoundingClientRect().width)
    expect(width).toBeGreaterThanOrEqual(375 - 1)
  })
})
