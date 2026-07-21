import { chromium } from 'playwright'

const prefix = process.argv[2] || 'before'
const base = 'http://127.0.0.1:18981/control/'
const channel = encodeURIComponent('飞书')
const outDir = '/tmp/polish-shots'

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

async function go(query) {
  await page.goto(`${base}channels?${query}`, { waitUntil: 'networkidle' })
  // Give the SPA + async channel facts time to settle.
  await page.waitForTimeout(1800)
}

// 1) Overview: header + top of the document
await go(`channel=${channel}&tab=overview`)
await page.screenshot({ path: `${outDir}/${prefix}-overview.png` })
// Full page too (captures the whole document flow)
await page.screenshot({ path: `${outDir}/${prefix}-overview-full.png`, fullPage: true })

// 2) Members section (pairings)
await go(`channel=${channel}&tab=pairings`)
await page.screenshot({ path: `${outDir}/${prefix}-members.png` })

// 3) Configuration read mode
await go(`channel=${channel}&tab=configuration`)
await page.screenshot({ path: `${outDir}/${prefix}-config.png` })
await page.screenshot({ path: `${outDir}/${prefix}-config-full.png`, fullPage: true })

// 4) Diagnostics
await go(`channel=${channel}&tab=diagnostics`)
await page.screenshot({ path: `${outDir}/${prefix}-diagnostics.png` })

await browser.close()
console.log(`${prefix} screenshots written to ${outDir}`)
