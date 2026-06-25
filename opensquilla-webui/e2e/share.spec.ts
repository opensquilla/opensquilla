import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const SESSION_KEY = 'agent:main:webchat:e2eshare'
const SYSTEM_ONLY_SESSION_KEY = 'agent:main:webchat:e2esharesysonly'

// Seed a settled turn through the real WS pipeline: the page talks to the
// real gateway, but chat.history responses are rewritten in flight so a
// user + assistant exchange renders without a live agent run. With
// withMessages=false the thread holds a single system message: the header
// renders but no bubble is shareable.
async function seedHistory(page: Page, withMessages: boolean) {
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
            messages: withMessages
              ? [
                {
                  role: 'user',
                  text: 'Summarize the launch checklist.',
                  id: 'msg-share-user',
                  timestamp: Math.floor(Date.now() / 1000) - 120,
                },
                {
                  role: 'assistant',
                  text: 'The checklist has three open items.',
                  id: 'msg-share-assistant',
                  timestamp: Math.floor(Date.now() / 1000) - 60,
                },
              ]
              : [
                {
                  role: 'system',
                  text: 'Session restored.',
                  id: 'msg-share-system',
                  timestamp: Math.floor(Date.now() / 1000) - 60,
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

async function openSeededSession(page: Page, key: string, withMessages: boolean) {
  await seedHistory(page, withMessages)
  await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(key))
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await page.waitForSelector('.chat-header', { timeout: 10000 })
}

async function enterShareMode(page: Page) {
  await expect(page.locator('.msg-ai-main').last()).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: 'Share' }).click()
  await expect(page.getByTestId('share-banner')).toBeVisible()
}

test.describe('Share mode interaction shell', () => {
  test('entering share mode opens the banner; the header keeps no share controls', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)
    await enterShareMode(page)

    const banner = page.getByTestId('share-banner')
    await expect(banner).toContainText('Select bubbles to share')
    await expect(banner).toContainText('0 selected')
    await expect(banner.locator('[role="status"]')).toHaveAttribute('aria-live', 'polite')

    // The banner owns the mode: save/cancel live there, not in the header.
    await expect(banner.getByRole('button', { name: 'Save PNG' })).toBeVisible()
    await expect(banner.getByRole('button', { name: 'Cancel' })).toBeVisible()
    const header = page.locator('.chat-header')
    await expect(header.getByRole('button', { name: 'Save PNG' })).toHaveCount(0)
    await expect(header.getByRole('button', { name: 'Cancel' })).toHaveCount(0)
    await expect(header.getByRole('button', { name: 'Share' })).toHaveCount(0)

    // The banner sits below the header band, clear of the floating topbar.
    const headerBox = await header.boundingBox()
    const bannerBox = await banner.boundingBox()
    expect(bannerBox!.y).toBeGreaterThanOrEqual(headerBox!.y + headerBox!.height - 1)

    // Entering share mode moves focus to the banner.
    const bannerFocused = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="share-banner"]')
      return !!el && !!document.activeElement && el.contains(document.activeElement)
    })
    expect(bannerFocused).toBe(true)
  })

  test('checkbox indicators are always visible and selection drives the count', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)
    await enterShareMode(page)

    const pickers = page.locator('.chat-share-picker')
    await expect(pickers).toHaveCount(2)
    await expect(pickers.first()).toBeVisible()
    await expect(pickers.last()).toBeVisible()
    await expect(pickers.first()).toHaveAttribute('aria-pressed', 'false')

    // Clicking anywhere on a bubble toggles it; selecting two updates the count.
    await page.locator('.msg-user-bubble').first().click()
    await expect(page.getByTestId('share-banner')).toContainText('1 selected')
    await pickers.last().click()
    await expect(page.getByTestId('share-banner')).toContainText('2 selected')

    await expect(page.locator('.msg-user--share-selected')).toHaveCount(1)
    await expect(page.locator('.msg-ai--share-selected')).toHaveCount(1)
    await expect(pickers.first()).toHaveAttribute('aria-pressed', 'true')
    await expect(pickers.last()).toHaveAttribute('aria-pressed', 'true')

    // Keyboard path: the indicator is a real button, Enter toggles it off.
    await pickers.first().focus()
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('share-banner')).toContainText('1 selected')
    await expect(pickers.first()).toHaveAttribute('aria-pressed', 'false')
  })

  test('save is visibly disabled at zero selected and Escape exits the mode', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)
    await enterShareMode(page)

    const save = page.getByTestId('share-banner').getByRole('button', { name: 'Save PNG' })
    await expect(save).toBeDisabled()
    const saveOpacity = await save.evaluate(el => parseFloat(getComputedStyle(el).opacity))
    expect(saveOpacity).toBeGreaterThanOrEqual(0.6)

    await page.keyboard.press('Escape')
    await expect(page.getByTestId('share-banner')).toHaveCount(0)
    await expect(page.locator('.chat-share-picker')).toHaveCount(0)
    await expect(page.locator('.chat-header').getByRole('button', { name: 'Share' })).toBeVisible()
  })

  test('banner Cancel ends the mode', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)
    await enterShareMode(page)

    await page.getByTestId('share-banner').getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByTestId('share-banner')).toHaveCount(0)
    await expect(page.locator('.chat-header').getByRole('button', { name: 'Share' })).toBeVisible()
  })

  test('at 700px the entry button collapses to an icon that stays visible', async ({ page }) => {
    await page.setViewportSize({ width: 700, height: 900 })
    await openSeededSession(page, SESSION_KEY, true)
    await expect(page.locator('.msg-ai-main').last()).toBeVisible({ timeout: 10000 })

    const entry = page.locator('.chat-header').getByRole('button', { name: 'Share' })
    await expect(entry).toBeVisible()
    await expect(entry.locator('.chat-share-btn__label')).toBeHidden()

    const iconBox = await entry.locator('svg').boundingBox()
    expect(iconBox).not.toBeNull()
    expect(iconBox!.width).toBeGreaterThan(0)
    expect(iconBox!.height).toBeGreaterThan(0)

    // Icon-only buttons keep a mobile-adequate tap target.
    const entryBox = await entry.boundingBox()
    expect(entryBox!.width).toBeGreaterThanOrEqual(43)
    expect(entryBox!.height).toBeGreaterThanOrEqual(43)
  })

  test('at 375px the entry stays clear of the floating topbar cluster and opens share mode', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await openSeededSession(page, SESSION_KEY, true)
    await expect(page.locator('.msg-ai-main').last()).toBeVisible({ timeout: 10000 })

    const entry = page.locator('.chat-header').getByRole('button', { name: 'Share' })
    await expect(entry).toBeVisible()

    // Reproduce the occlusion probe: a tap at the button center must land on
    // the button, not on the floating conn pill that overlays the header band.
    const probe = await page.evaluate(() => {
      const btn = document.querySelector<HTMLElement>('.chat-header .chat-share-btn[aria-label="Share"]')
      const pill = document.querySelector<HTMLElement>('.conn-pill')
      if (!btn || !pill) return null
      const r = btn.getBoundingClientRect()
      const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
      // Worst-case cluster intrusion: the fixed chrome right of the pill plus
      // the pill rendered with its longest state label. The pill text varies
      // (CONNECTED/CONNECTING/DISCONNECTED), so asserting against the current
      // state alone would under-test.
      const cs = getComputedStyle(pill)
      const ctx = document.createElement('canvas').getContext('2d')!
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
      const text = 'DISCONNECTED'
      const letterSpacing = parseFloat(cs.letterSpacing) || 0
      const chrome = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight)
        + parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth)
      const worstPill = ctx.measureText(text).width + letterSpacing * text.length + chrome
      const worstIntrusion = (window.innerWidth - pill.getBoundingClientRect().right) + worstPill
      return {
        hitIsButton: hit === btn || btn.contains(hit),
        btnRight: r.right,
        clearance: window.innerWidth - worstIntrusion - r.right,
      }
    })
    expect(probe).not.toBeNull()
    expect(probe!.hitIsButton).toBe(true)
    // Clear of the cluster even in its widest (disconnected) state.
    expect(probe!.clearance).toBeGreaterThanOrEqual(0)

    await entry.click()
    await expect(page.getByTestId('share-banner')).toBeVisible()
  })

  test('a thread without shareable bubbles keeps the entry visible-disabled with an explanation', async ({ page }) => {
    await openSeededSession(page, SYSTEM_ONLY_SESSION_KEY, false)
    await expect(page.locator('.msg-system')).toBeVisible({ timeout: 10000 })

    const entry = page.locator('.chat-header').getByRole('button', { name: 'Send a message first to share' })
    await expect(entry).toBeVisible()
    await expect(entry).toBeDisabled()
    await expect(entry).toHaveAttribute('title', 'Send a message first to share')
    const opacity = await entry.evaluate(el => parseFloat(getComputedStyle(el).opacity))
    expect(opacity).toBeGreaterThanOrEqual(0.6)
  })

  test('Save opens the preview modal; Escape closes only the modal and keeps share mode', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)
    await enterShareMode(page)

    // Select both bubbles, then Save renders the PNG and opens the preview.
    await page.locator('.msg-user-bubble').first().click()
    await page.locator('.chat-share-picker').last().click()
    await expect(page.getByTestId('share-banner')).toContainText('2 selected')
    await page.getByTestId('share-banner').getByRole('button', { name: 'Save PNG' }).click()

    const dialog = page.getByRole('dialog', { name: 'Share preview' })
    await expect(dialog).toBeVisible({ timeout: 15000 })
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    await expect(dialog.getByRole('img', { name: 'Share preview' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Download image' })).toBeVisible()

    // Escape closes the preview but leaves share mode active (the banner stays),
    // and focus returns to the share banner — the header Share button is
    // unmounted while share mode is on, so the banner is the mode's anchor.
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(page.getByTestId('share-banner')).toBeVisible()
    const bannerFocusedAfterEscape = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="share-banner"]')
      return !!el && document.activeElement === el
    })
    expect(bannerFocusedAfterEscape).toBe(true)
  })

  test('the modal close button dismisses the preview and returns focus to the Share entry', async ({ page }) => {
    await openSeededSession(page, SESSION_KEY, true)
    await enterShareMode(page)

    await page.locator('.msg-user-bubble').first().click()
    await page.locator('.chat-share-picker').last().click()
    await page.getByTestId('share-banner').getByRole('button', { name: 'Save PNG' }).click()

    const dialog = page.getByRole('dialog', { name: 'Share preview' })
    await expect(dialog).toBeVisible({ timeout: 15000 })

    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByTestId('share-banner')).toBeVisible()
    const bannerFocusedAfterClose = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="share-banner"]')
      return !!el && document.activeElement === el
    })
    expect(bannerFocusedAfterClose).toBe(true)
  })
})
