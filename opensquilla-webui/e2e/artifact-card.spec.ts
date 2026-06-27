import { test, expect, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const SESSION_KEY = 'agent:main:webchat:e2eartifactcard'

// 1x1 transparent PNG, used as both the full image and the thumbnail bytes.
const PNG_1x1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
)

// Seed a finished assistant turn carrying one image, one previewable document,
// and one download-only data file, rewriting chat.history in flight.
async function seedHistory(page: Page) {
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
                text: 'Produce a few deliverables.',
                id: 'msg-artcard-user',
                timestamp: Math.floor(Date.now() / 1000) - 120,
              },
              {
                role: 'assistant',
                text: 'Here you go.',
                id: 'msg-artcard-assistant',
                timestamp: Math.floor(Date.now() / 1000) - 60,
                artifacts: [
                  {
                    id: 'art-card-img',
                    name: 'generated-image.png',
                    mime: 'image/png',
                    size: 744448,
                    download_url: '/api/v1/artifacts/art-card-img',
                    thumbnail_url: '/api/v1/artifacts/art-card-img?variant=thumb',
                  },
                  { id: 'art-card-pdf', name: 'report-q2.pdf', mime: 'application/pdf', size: 188416 },
                  { id: 'art-card-csv', name: 'pricing.csv', mime: 'text/csv', size: 12288 },
                ],
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

async function openSeeded(page: Page) {
  await page.route('**/api/v1/artifacts/**', route =>
    route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1x1 }))
  await seedHistory(page)
  await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(SESSION_KEY))
  await page.waitForSelector('.conn-pill', { timeout: 10000 })
  await page.waitForSelector('.chat-header', { timeout: 10000 })
}

test.describe('Artifact deliverable cards', () => {
  test('image renders one media card and no duplicate file chip', async ({ page }) => {
    await openSeeded(page)

    const media = page.locator('.msg-media-card')
    await expect(media).toHaveCount(1)
    await expect(media.locator('.msg-media-card__name')).toHaveText('generated-image.png')
    // Clean meta: TYPE · size, never "FILE" or a "Preview file" prefix.
    await expect(media.locator('.msg-media-card__meta')).toHaveText('PNG · 727 KB')

    // The image is NOT also rendered as a file chip.
    const chipNames = await page.locator('.msg-artifact-chip .msg-artifact-name').allTextContents()
    expect(chipNames).not.toContain('generated-image.png')

    // Non-image artifacts are the only file chips: pdf + csv.
    await expect(page.locator('.msg-artifact-chip')).toHaveCount(2)
  })

  test('the media card thumbnail uses the variant=thumb URL', async ({ page }) => {
    const requested: string[] = []
    await page.route('**/api/v1/artifacts/**', route => {
      requested.push(route.request().url())
      route.fulfill({ status: 200, contentType: 'image/png', body: PNG_1x1 })
    })
    await seedHistory(page)
    await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(SESSION_KEY))
    await page.waitForSelector('.msg-media-card__img img', { timeout: 10000 })

    expect(requested.some(url => url.includes('art-card-img') && url.includes('variant=thumb'))).toBe(true)
  })

  test('previewable file card splits Open from Download', async ({ page }) => {
    await openSeeded(page)

    const pdfCard = page.locator('.msg-artifact-chip', { hasText: 'report-q2.pdf' })
    await expect(pdfCard).toBeVisible()
    // Clean meta uses the type pill and size, no doubled category.
    await expect(pdfCard.locator('.msg-artifact-kind')).toHaveText('PDF')
    await expect(pdfCard.locator('.msg-artifact-size')).toHaveText('184 KB')

    // Open and Download are separate, separately labelled controls.
    const openBtn = pdfCard.getByRole('button', { name: 'Open report-q2.pdf' })
    const downloadBtn = pdfCard.getByRole('button', { name: 'Download report-q2.pdf' })
    await expect(openBtn).toBeVisible()
    await expect(downloadBtn).toBeVisible()

    // Open opens a new tab; it never downloads.
    const popupPromise = page.waitForEvent('popup')
    await openBtn.click()
    const popup = await popupPromise
    expect(popup).toBeTruthy()
    await popup.close()
  })

  test('download-only file card has a Download control and no Open', async ({ page }) => {
    await openSeeded(page)

    const csvCard = page.locator('.msg-artifact-chip', { hasText: 'pricing.csv' })
    await expect(csvCard).toBeVisible()
    await expect(csvCard.locator('.msg-artifact-kind')).toHaveText('CSV')

    // No Open affordance for non-previewable data.
    await expect(csvCard.getByRole('button', { name: 'Open pricing.csv' })).toHaveCount(0)
    await expect(csvCard.getByRole('button', { name: 'Download pricing.csv' })).toBeVisible()
  })
})
