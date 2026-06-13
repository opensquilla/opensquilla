import type { Ref } from 'vue'
import { toCanvas } from 'html-to-image'
import { downloadBlob } from '@/utils/browser'

export type ShareExportTheme = 'light' | 'dark'

interface ChatShareExportOptions {
  threadRef: Ref<HTMLElement | null>
  /** Raw conversation title. The composable does all slugging and filename
      composition (CJK-safe) — callers must NOT pre-sanitize or pre-compose. */
  title: () => string
}

export interface ShareImageResult {
  blob: Blob
  filename: string
  width: number
  height: number
}

const EXPORT_WIDTH = 704
const CAPTURE_STAGE_GUTTER = 48
const CAPTURE_STAGE_MIN_WIDTH = 640
const CAPTURE_STAGE_MAX_WIDTH = 1040
const MAX_EXPORT_HEIGHT = 24000
const SHARE_TEMPLATE_WIDTH = 760
const SHARE_TEMPLATE_MARGIN = 28
const SHARE_TEMPLATE_TOP = 24
const SHARE_TEMPLATE_BRAND_HEIGHT = 24
const SHARE_TEMPLATE_BRAND_GAP = 14
const SHARE_TEMPLATE_FOOTER_HEIGHT = 96
const SHARE_TEMPLATE_QR_SIZE = 64
const CAPTURE_SCALE_LIMIT = 2

const SHARE_FILENAME_PREFIX = 'opensquilla'
const SHARE_FILENAME_FALLBACK = 'chat'
const SHARE_SLUG_MAX_LENGTH = 40
const SHARE_FOOTER_CAPTION = 'opensquilla.ai'

const SHARE_STAGE_ID = 'opensquilla-share-export-stage'

// Interactive UI remnants that must never appear in the static share image.
// Keep this list class-based and specific: generic selectors (e.g. bare
// input[type=checkbox]) would also strip rendered markdown task lists.
const SHARE_CLONE_STRIP_SELECTORS = [
  '.chat-share-picker',
  '.msg-user-actions',
  '.msg-ai-actions',
  '.share-select-check',
  '.share-select-checkbox',
  '.chat-share-checkbox',
  '[data-share-checkbox]',
  '[data-share-control]',
  '.msg-meta__more',
  '.msg-meta__cost',
  '.step-view-btn',
  '.msg-artifact-actions',
  '.msg-artifact-download',
  '[data-tooltip]',
  '[role="tooltip"]',
]

export function useChatShareExport(options: ChatShareExportOptions) {
  // Build the share PNG without delivering it: callers get the blob (plus the
  // composed filename and pixel size) and decide whether to preview, copy, or
  // download. `theme` forces the export's token theme independently of the live
  // app theme, defaulting to light for legibility on social surfaces.
  async function buildShareImage(
    selectedIds: Set<string>,
    opts: { theme?: ShareExportTheme } = {},
  ): Promise<ShareImageResult | null> {
    const theme: ShareExportTheme = opts.theme ?? 'light'
    if (selectedIds.size === 0) {
      console.warn('Share export skipped: no messages selected')
      return null
    }
    const sourceElements = selectedShareElements(options.threadRef.value, selectedIds)
    if (sourceElements.length === 0) {
      console.warn('Share export skipped: selected messages not found in thread')
      return null
    }

    await document.fonts?.ready
    const stage = buildShareDom(sourceElements, theme)

    try {
      document.body.appendChild(stage)
      await waitForStablePaint()
      const contentCanvas = await captureStageWithDom(stage)
      const { blob, width, height } = await composeShareTemplate(contentCanvas, stage)
      const filename = shareExportFilename(options.title())
      return { blob, filename, width, height }
    } finally {
      stage.remove()
    }
  }

  // Thin build + immediate download, kept for non-preview callers.
  async function exportSelectedMessages(
    selectedIds: Set<string>,
    opts: { theme?: ShareExportTheme } = {},
  ): Promise<string | null> {
    const result = await buildShareImage(selectedIds, opts)
    if (!result) return null
    downloadBlob(result.blob, result.filename)
    return result.filename
  }

  return {
    buildShareImage,
    exportSelectedMessages,
  }
}

export function shareExportFilename(rawName: string, now: Date = new Date()): string {
  const date = now.toISOString().slice(0, 10)
  const slug = shareTitleSlug(rawName) || SHARE_FILENAME_FALLBACK
  return `${SHARE_FILENAME_PREFIX}-${slug}-${date}.png`
}

function shareTitleSlug(rawName: string): string {
  let value = (rawName || '').trim()
  // Unwrap values that are already composed filenames (the previous template
  // produced "opensquilla-chat-<title|chat>-<date>.png", which duplicated
  // "chat" whenever the title fell back).
  const looksComposed = /\.png$/i.test(value) || /^opensquilla-/i.test(value)
  if (looksComposed) {
    value = value
      .replace(/\.png$/i, '')
      .replace(/^opensquilla-/i, '')
      .replace(/-\d{4}-\d{2}-\d{2}$/, '')
      .replace(/^chat-(?=.)/i, '')
  }

  const slug = value
    .toLowerCase()
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f<>:"/\\|?*]+/g, '-')
    .replace(/\s+/g, '-')
    .replace(/\.+$/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
  const capped = Array.from(slug).slice(0, SHARE_SLUG_MAX_LENGTH).join('').replace(/^-+|-+$/g, '')
  return dedupeAdjacentSegments(capped)
}

function dedupeAdjacentSegments(slug: string): string {
  const segments = slug.split('-').filter(Boolean)
  const result: string[] = []
  for (const segment of segments) {
    if (result[result.length - 1] !== segment) result.push(segment)
  }
  return result.join('-')
}

function selectedShareElements(thread: HTMLElement | null, selectedIds: Set<string>): HTMLElement[] {
  if (!thread) return []
  const elements = Array.from(thread.querySelectorAll<HTMLElement>('[data-share-message-id]'))
  return elements.filter(element => selectedIds.has(element.dataset.shareMessageId || ''))
}

export function buildShareDom(sourceElements: HTMLElement[], theme: ShareExportTheme = 'light'): HTMLElement {
  const stageWidth = captureStageWidth(sourceElements)
  const stage = document.createElement('section')
  stage.id = SHARE_STAGE_ID
  // Forcing data-theme on the stage root re-resolves the token custom
  // properties for the whole cloned subtree, decoupling the export from the
  // live app theme. shareThemeTokens() reads getComputedStyle of THIS element,
  // and html-to-image inlines those computed styles into the raster.
  stage.dataset.theme = theme
  stage.setAttribute('aria-hidden', 'true')
  stage.className = 'chat-share-export-stage'
  stage.dataset.shareTemplateMetrics = JSON.stringify(shareTemplateMetrics())
  const tokens = shareThemeTokens(stage)
  stage.style.cssText = [
    'position:fixed',
    'left:16px',
    'top:16px',
    `width:${stageWidth}px`,
    `max-width:${stageWidth}px`,
    'padding:0 0 8px',
    'box-sizing:border-box',
    `background:${tokens.card}`,
    `color:${tokens.text}`,
    'z-index:-1',
    'pointer-events:none',
    'overflow:visible',
    'opacity:1',
  ].join(';')

  const style = document.createElement('style')
  style.textContent = shareExportCss()
  stage.appendChild(style)

  const stack = document.createElement('div')
  stack.className = 'chat-share-export-stack'
  sourceElements.forEach((element) => {
    stack.appendChild(cleanupShareClone(element.cloneNode(true) as HTMLElement))
  })
  stage.appendChild(stack)

  return stage
}

function shareTemplateMetrics() {
  return {
    width: SHARE_TEMPLATE_WIDTH,
    contentWidth: EXPORT_WIDTH,
    top: SHARE_TEMPLATE_TOP,
    brandHeight: SHARE_TEMPLATE_BRAND_HEIGHT,
    brandGap: SHARE_TEMPLATE_BRAND_GAP,
    footerHeight: SHARE_TEMPLATE_FOOTER_HEIGHT,
    qrSize: SHARE_TEMPLATE_QR_SIZE,
    caption: SHARE_FOOTER_CAPTION,
  }
}

function shareThemeTokens(themeEl: HTMLElement) {
  // Read the forced-theme custom properties off the export stage (not
  // document.documentElement), so the rasterized template follows the stage's
  // data-theme rather than the live app theme.
  const styles = getComputedStyle(themeEl)
  const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback
  return {
    page: token('--bg', '#f4f4f3'),
    card: token('--bg-surface', '#ffffff'),
    border: token('--border', 'rgba(32, 39, 34, 0.08)'),
    text: token('--text', '#18181b'),
    muted: token('--text-muted', '#4f5550'),
    fontSans: token('--font-sans', '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'),
  }
}

function captureStageWidth(sourceElements: HTMLElement[]): number {
  const sourceWidth = Math.max(
    ...sourceElements.map(element => element.getBoundingClientRect().width),
    0,
  )
  const naturalWidth = Math.ceil(sourceWidth + CAPTURE_STAGE_GUTTER)
  return Math.max(CAPTURE_STAGE_MIN_WIDTH, Math.min(CAPTURE_STAGE_MAX_WIDTH, naturalWidth))
}

function cleanupShareClone(clone: HTMLElement): HTMLElement {
  clone.classList.remove(
    'msg-user--share-mode',
    'msg-user--share-selected',
    'msg-ai--share-mode',
    'msg-ai--share-selected',
  )
  clone.removeAttribute('data-share-selected')

  // Thinking fold: an expanded fold means the user deliberately opened the
  // reasoning and is sharing it — keep the text, but swap the interactive
  // <details> chrome for a quiet static label. A collapsed fold is just a
  // dead button in a static image and is dropped entirely.
  clone.querySelectorAll<HTMLElement>('.thinking-fold').forEach((fold) => {
    const body = fold.querySelector<HTMLElement>('.thinking-fold__body')
    const text = body?.textContent?.trim() || ''
    if (!fold.hasAttribute('open') || !text) {
      fold.remove()
      return
    }
    const block = document.createElement('div')
    block.className = 'chat-share-export-thinking'
    const label = document.createElement('div')
    label.className = 'chat-share-export-thinking__label'
    label.textContent = 'Thinking'
    const bodyText = document.createElement('div')
    bodyText.className = 'chat-share-export-thinking__body'
    bodyText.textContent = text
    block.append(label, bodyText)
    fold.replaceWith(block)
  })

  clone.querySelectorAll<HTMLElement>('[data-share-selected]').forEach((element) => {
    element.removeAttribute('data-share-selected')
  })
  clone.querySelectorAll<HTMLElement>(SHARE_CLONE_STRIP_SELECTORS.join(','))
    .forEach(element => element.remove())

  clone.querySelectorAll<HTMLElement>('*').forEach((element) => {
    element.classList.remove(
      'msg-user--share-mode',
      'msg-user--share-selected',
      'msg-ai--share-mode',
      'msg-ai--share-selected',
    )
  })

  clone.style.transform = 'none'
  return clone
}

function shareExportCss(): string {
  return `
    #${SHARE_STAGE_ID},
    #${SHARE_STAGE_ID} * {
      animation: none !important;
      transition: none !important;
      caret-color: transparent !important;
    }

    #${SHARE_STAGE_ID} .chat-share-export-stack {
      display: flex;
      flex-direction: column;
      gap: 0;
      width: 100%;
    }

    #${SHARE_STAGE_ID} button,
    #${SHARE_STAGE_ID} input,
    #${SHARE_STAGE_ID} textarea,
    #${SHARE_STAGE_ID} select {
      pointer-events: none !important;
    }

    #${SHARE_STAGE_ID} .chat-share-export-thinking {
      margin: 0 0 10px;
      padding: 6px 10px;
      border-left: 2px solid color-mix(in srgb, currentColor 22%, transparent);
    }

    #${SHARE_STAGE_ID} .chat-share-export-thinking__label {
      font-size: 11px;
      letter-spacing: 0.04em;
      opacity: 0.55;
      margin-bottom: 3px;
    }

    #${SHARE_STAGE_ID} .chat-share-export-thinking__body {
      font-size: 12px;
      line-height: 1.55;
      opacity: 0.75;
      white-space: pre-wrap;
    }

    /* The live meta line is hover-dimmed; the static image has no hover. */
    #${SHARE_STAGE_ID} .msg-ai-meta > span {
      opacity: 1 !important;
    }
  `
}

async function captureStageWithDom(stage: HTMLElement): Promise<HTMLCanvasElement> {
  const rect = stage.getBoundingClientRect()
  const height = assertShareStageHeight(stage, rect)
  const canvas = await toCanvas(stage, {
    backgroundColor: shareThemeTokens(stage).card,
    cacheBust: true,
    pixelRatio: captureScale(),
    width: Math.ceil(rect.width),
    height,
    style: {
      transform: 'none',
      margin: '0',
    },
  })
  canvas.style.width = `${EXPORT_WIDTH}px`
  canvas.style.height = `${Math.round((canvas.height * EXPORT_WIDTH) / canvas.width)}px`
  return canvas
}

async function composeShareTemplate(
  contentCanvas: HTMLCanvasElement,
  stage: HTMLElement,
): Promise<{ blob: Blob; width: number; height: number }> {
  const tokens = shareThemeTokens(stage)
  const contentHeight = Math.ceil((contentCanvas.height * EXPORT_WIDTH) / contentCanvas.width)
  const height = SHARE_TEMPLATE_TOP
    + SHARE_TEMPLATE_BRAND_HEIGHT
    + SHARE_TEMPLATE_BRAND_GAP
    + contentHeight
    + SHARE_TEMPLATE_FOOTER_HEIGHT

  if (height > MAX_EXPORT_HEIGHT) {
    throw new Error(`Share image is too tall (${height}px). Select fewer bubbles.`)
  }

  const scale = captureScale()
  const canvas = document.createElement('canvas')
  canvas.width = Math.ceil(SHARE_TEMPLATE_WIDTH * scale)
  canvas.height = Math.ceil(height * scale)
  canvas.style.width = `${SHARE_TEMPLATE_WIDTH}px`
  canvas.style.height = `${height}px`

  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas is unavailable')
  context.scale(scale, scale)

  context.fillStyle = tokens.page
  context.fillRect(0, 0, SHARE_TEMPLATE_WIDTH, height)

  await drawTemplateBrand(context, SHARE_TEMPLATE_TOP, tokens)

  const cardX = SHARE_TEMPLATE_MARGIN
  const cardY = SHARE_TEMPLATE_TOP + SHARE_TEMPLATE_BRAND_HEIGHT + SHARE_TEMPLATE_BRAND_GAP
  roundRect(context, cardX, cardY, EXPORT_WIDTH, contentHeight, 8)
  context.fillStyle = tokens.card
  context.fill()
  context.save()
  roundRect(context, cardX, cardY, EXPORT_WIDTH, contentHeight, 8)
  context.clip()
  context.drawImage(contentCanvas, cardX, cardY, EXPORT_WIDTH, contentHeight)
  context.restore()
  roundRect(context, cardX, cardY, EXPORT_WIDTH, contentHeight, 8)
  context.strokeStyle = tokens.border
  context.stroke()

  await drawTemplateFooter(context, cardY + contentHeight, tokens)

  const blob = await blobFromCanvas(canvas)
  return { blob, width: SHARE_TEMPLATE_WIDTH, height }
}

async function drawTemplateBrand(
  context: CanvasRenderingContext2D,
  y: number,
  tokens: ReturnType<typeof shareThemeTokens>,
) {
  const markSize = 22
  const markGap = 8
  const mark = await loadOptionalImage(staticAssetUrl('img/opensquilla-mark.png'))

  // Measure with the wordmark font already set so the centered group is exact.
  context.font = `600 18px ${tokens.fontSans}`
  const wordWidth = context.measureText('OpenSquilla').width
  const groupWidth = (mark ? markSize + markGap : 0) + wordWidth
  let cursorX = Math.round((SHARE_TEMPLATE_WIDTH - groupWidth) / 2)

  if (mark) {
    const markY = y + Math.round((SHARE_TEMPLATE_BRAND_HEIGHT - markSize) / 2)
    context.drawImage(mark, cursorX, markY, markSize, markSize)
    cursorX += markSize + markGap
  }

  context.fillStyle = tokens.text
  context.textAlign = 'left'
  context.textBaseline = 'middle'
  context.fillText('OpenSquilla', cursorX, y + SHARE_TEMPLATE_BRAND_HEIGHT / 2)
  context.textBaseline = 'alphabetic'
}

async function drawTemplateFooter(
  context: CanvasRenderingContext2D,
  startY: number,
  tokens: ReturnType<typeof shareThemeTokens>,
) {
  const qr = await loadOptionalImage(staticAssetUrl('img/QRcode.png'))

  // One cohesive, centered footer band: [QR][gap][caption], the whole group
  // centered on the template width rather than pinned to opposite corners.
  const captionGap = 12
  context.font = `500 12px ${tokens.fontSans}`
  const captionWidth = context.measureText(SHARE_FOOTER_CAPTION).width
  const groupWidth = (qr ? SHARE_TEMPLATE_QR_SIZE + captionGap : 0) + captionWidth
  const groupX = Math.round((SHARE_TEMPLATE_WIDTH - groupWidth) / 2)
  const qrY = startY + 16
  const centerY = qrY + SHARE_TEMPLATE_QR_SIZE / 2

  let captionX = groupX
  if (qr) {
    const qrX = groupX
    // White backing keeps the QR scannable on the dark theme page fill.
    roundRect(context, qrX, qrY, SHARE_TEMPLATE_QR_SIZE, SHARE_TEMPLATE_QR_SIZE, 6)
    context.fillStyle = '#ffffff'
    context.fill()
    context.drawImage(qr, qrX, qrY, SHARE_TEMPLATE_QR_SIZE, SHARE_TEMPLATE_QR_SIZE)
    captionX = qrX + SHARE_TEMPLATE_QR_SIZE + captionGap
  }

  context.fillStyle = tokens.muted
  context.textAlign = 'left'
  context.textBaseline = 'middle'
  context.fillText(SHARE_FOOTER_CAPTION, captionX, centerY)
  context.textBaseline = 'alphabetic'
}

function assertShareStageHeight(stage: HTMLElement, rect: DOMRect): number {
  const height = Math.ceil(Math.max(rect.height, stage.offsetHeight, stage.scrollHeight))
  if (height > MAX_EXPORT_HEIGHT) {
    throw new Error(`Share image is too tall (${height}px). Select fewer bubbles.`)
  }
  return height
}

async function waitForStablePaint(): Promise<void> {
  await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
  await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
}

function captureScale(): number {
  return Math.min(window.devicePixelRatio || 1, CAPTURE_SCALE_LIMIT)
}

function blobFromCanvas(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('Failed to create PNG'))
    }, 'image/png')
  })
}

function loadOptionalImage(src: string): Promise<HTMLImageElement | null> {
  if (!src) return Promise.resolve(null)
  return new Promise((resolve) => {
    const image = new Image()
    image.decoding = 'async'
    image.onload = () => resolve(image)
    image.onerror = () => resolve(null)
    image.src = src
  })
}

function staticAssetUrl(path: string): string {
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base}/static/${path.replace(/^\/+/, '')}`
}

function roundRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const r = Math.min(radius, width / 2, height / 2)
  context.beginPath()
  context.moveTo(x + r, y)
  context.lineTo(x + width - r, y)
  context.quadraticCurveTo(x + width, y, x + width, y + r)
  context.lineTo(x + width, y + height - r)
  context.quadraticCurveTo(x + width, y + height, x + width - r, y + height)
  context.lineTo(x + r, y + height)
  context.quadraticCurveTo(x, y + height, x, y + height - r)
  context.lineTo(x, y + r)
  context.quadraticCurveTo(x, y, x + r, y)
  context.closePath()
}
