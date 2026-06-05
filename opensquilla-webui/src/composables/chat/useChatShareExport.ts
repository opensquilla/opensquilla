import type { Ref } from 'vue'
import { toCanvas } from 'html-to-image'
import { downloadBlob } from '@/utils/browser'

interface ChatShareExportOptions {
  threadRef: Ref<HTMLElement | null>
  filename: () => string
}

const EXPORT_WIDTH = 704
const CAPTURE_STAGE_GUTTER = 48
const CAPTURE_STAGE_MIN_WIDTH = 640
const CAPTURE_STAGE_MAX_WIDTH = 1040
const MAX_EXPORT_HEIGHT = 24000
const SHARE_TEMPLATE_WIDTH = 760
const SHARE_TEMPLATE_MARGIN = 28
const SHARE_TEMPLATE_TOP = 28
const SHARE_TEMPLATE_BRAND_HEIGHT = 64
const SHARE_TEMPLATE_FOOTER_HEIGHT = 188
const SHARE_TEMPLATE_QR_SIZE = 84
const CAPTURE_SCALE_LIMIT = 2

const SHARE_STAGE_ID = 'opensquilla-share-export-stage'

export function useChatShareExport(options: ChatShareExportOptions) {
  async function exportSelectedMessages(selectedIds: Set<string>): Promise<void> {
    if (selectedIds.size === 0) return
    const sourceElements = selectedShareElements(options.threadRef.value, selectedIds)
    if (sourceElements.length === 0) return

    await document.fonts?.ready
    const stage = buildShareExportStage(sourceElements)

    try {
      document.body.appendChild(stage)
      await waitForStablePaint()
      const contentCanvas = await captureStageWithDom(stage)
      const blob = await composeShareTemplate(contentCanvas)
      downloadBlob(blob, options.filename())
    } finally {
      stage.remove()
    }
  }

  return {
    exportSelectedMessages,
  }
}

function selectedShareElements(thread: HTMLElement | null, selectedIds: Set<string>): HTMLElement[] {
  if (!thread) return []
  const elements = Array.from(thread.querySelectorAll<HTMLElement>('[data-share-message-id]'))
  return elements.filter(element => selectedIds.has(element.dataset.shareMessageId || ''))
}

function buildShareExportStage(sourceElements: HTMLElement[]): HTMLElement {
  const stageWidth = captureStageWidth(sourceElements)
  const stage = document.createElement('section')
  stage.id = SHARE_STAGE_ID
  stage.setAttribute('aria-hidden', 'true')
  stage.className = 'chat-share-export-stage'
  stage.style.cssText = [
    'position:fixed',
    'left:16px',
    'top:16px',
    `width:${stageWidth}px`,
    `max-width:${stageWidth}px`,
    'padding:0 0 8px',
    'box-sizing:border-box',
    'background:#ffffff',
    'color:#18181b',
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

  clone.querySelectorAll<HTMLElement>('[data-share-selected]').forEach((element) => {
    element.removeAttribute('data-share-selected')
  })
  clone.querySelectorAll<HTMLElement>([
    '.chat-share-picker',
    '.msg-user-actions',
    '.msg-ai-actions',
    '.share-select-check',
    '[data-share-control]',
    '[data-tooltip]',
    '[role="tooltip"]',
  ].join(',')).forEach(element => element.remove())

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
  `
}

async function captureStageWithDom(stage: HTMLElement): Promise<HTMLCanvasElement> {
  const rect = stage.getBoundingClientRect()
  const height = assertShareStageHeight(stage, rect)
  const canvas = await toCanvas(stage, {
    backgroundColor: '#ffffff',
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

async function composeShareTemplate(contentCanvas: HTMLCanvasElement): Promise<Blob> {
  const contentHeight = Math.ceil((contentCanvas.height * EXPORT_WIDTH) / contentCanvas.width)
  const height = SHARE_TEMPLATE_TOP
    + SHARE_TEMPLATE_BRAND_HEIGHT
    + SHARE_TEMPLATE_MARGIN
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

  context.fillStyle = '#f4f4f3'
  context.fillRect(0, 0, SHARE_TEMPLATE_WIDTH, height)

  await drawTemplateBrand(context, SHARE_TEMPLATE_TOP)

  const cardX = SHARE_TEMPLATE_MARGIN
  const cardY = SHARE_TEMPLATE_TOP + SHARE_TEMPLATE_BRAND_HEIGHT + SHARE_TEMPLATE_MARGIN
  roundRect(context, cardX, cardY, EXPORT_WIDTH, contentHeight, 8)
  context.fillStyle = '#ffffff'
  context.fill()
  context.save()
  roundRect(context, cardX, cardY, EXPORT_WIDTH, contentHeight, 8)
  context.clip()
  context.drawImage(contentCanvas, cardX, cardY, EXPORT_WIDTH, contentHeight)
  context.restore()
  roundRect(context, cardX, cardY, EXPORT_WIDTH, contentHeight, 8)
  context.strokeStyle = 'rgba(32, 39, 34, 0.08)'
  context.stroke()

  await drawTemplateFooter(context, cardY + contentHeight)

  return await blobFromCanvas(canvas)
}

async function drawTemplateBrand(context: CanvasRenderingContext2D, y: number) {
  const logo = await loadOptionalImage(staticAssetUrl('img/opensquilla-long-logo.png'))
  if (logo) {
    const logoWidth = 260
    const logoHeight = Math.round(logoWidth * (logo.naturalHeight / logo.naturalWidth))
    const logoX = (SHARE_TEMPLATE_WIDTH - logoWidth) / 2
    const logoY = y + Math.round((SHARE_TEMPLATE_BRAND_HEIGHT - logoHeight) / 2)
    context.drawImage(logo, logoX, logoY, logoWidth, logoHeight)
    return
  }

  context.font = '800 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  context.fillStyle = '#141414'
  context.textAlign = 'center'
  context.textBaseline = 'top'
  context.fillText('OpenSquilla', SHARE_TEMPLATE_WIDTH / 2, y)
  context.textAlign = 'left'
}

async function drawTemplateFooter(context: CanvasRenderingContext2D, startY: number) {
  const asset = await loadOptionalImage(staticAssetUrl('img/QRcode.png'))
  const assetX = (SHARE_TEMPLATE_WIDTH - SHARE_TEMPLATE_QR_SIZE) / 2
  const assetY = startY + 24

  if (asset) {
    roundRect(context, assetX, assetY, SHARE_TEMPLATE_QR_SIZE, SHARE_TEMPLATE_QR_SIZE, 8)
    context.fillStyle = '#ffffff'
    context.fill()
    context.drawImage(asset, assetX, assetY, SHARE_TEMPLATE_QR_SIZE, SHARE_TEMPLATE_QR_SIZE)
  }

  context.font = '700 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  context.fillStyle = '#4f5550'
  context.textAlign = 'center'
  context.textBaseline = 'top'
  context.fillText('Scan the QR code to visit OpenSquilla', SHARE_TEMPLATE_WIDTH / 2, assetY + SHARE_TEMPLATE_QR_SIZE + 14)

  context.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  context.fillStyle = 'rgba(82, 88, 81, 0.62)'
  context.fillText('Token-Efficient · Meta-Skills · AI Agent', SHARE_TEMPLATE_WIDTH / 2, assetY + SHARE_TEMPLATE_QR_SIZE + 32)
  context.textAlign = 'left'
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
