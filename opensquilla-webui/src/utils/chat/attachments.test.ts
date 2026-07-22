import { describe, expect, it } from 'vitest'

import {
  hasSendableModelInputImageAttachment,
  isImageDisplayAttachment,
  isModelInputImageMime,
  isSendableModelInputImageAttachment,
  normalizeDisplayAttachment,
  normalizeDisplayAttachments,
  serializeDisplayAttachment,
} from './attachments'
import type { Attachment } from '@/types/chat'

describe('model-input image detection', () => {
  it.each([
    'image/png',
    'IMAGE/JPEG',
    'image/jpg',
    'image/gif; charset=binary',
    'image/webp',
  ])('accepts the Gateway model-image MIME %s', (mime) => {
    expect(isModelInputImageMime(mime)).toBe(true)
  })

  it.each([
    'application/pdf',
    'image/svg+xml',
    'image/tiff',
    'image/avif',
    'text/plain',
  ])('does not classify %s as a model image', (mime) => {
    expect(isModelInputImageMime(mime)).toBe(false)
  })

  it('counts only ready inline and staged image attachments', () => {
    const inline: Attachment = {
      kind: 'inline',
      local_id: 1,
      name: 'inline.png',
      mime: 'image/png',
      data: 'aW1hZ2U=',
    }
    const staged: Attachment = {
      kind: 'staged',
      local_id: 2,
      name: 'staged.jpg',
      mime: 'image/jpg',
      file_uuid: 'file-ready',
    }
    const uploading: Attachment = {
      kind: 'uploading',
      local_id: 3,
      name: 'uploading.webp',
      mime: 'image/webp',
    }
    const failed: Attachment = {
      kind: 'failed',
      local_id: 4,
      name: 'failed.gif',
      mime: 'image/gif',
      error: 'failed',
    }

    expect(isSendableModelInputImageAttachment(inline)).toBe(true)
    expect(isSendableModelInputImageAttachment(staged)).toBe(true)
    expect(isSendableModelInputImageAttachment(uploading)).toBe(false)
    expect(isSendableModelInputImageAttachment(failed)).toBe(false)
    expect(hasSendableModelInputImageAttachment([uploading, failed])).toBe(false)
    expect(hasSendableModelInputImageAttachment([uploading, staged])).toBe(true)
  })
})

describe('attachment display normalization', () => {
  it('renders inline HTML history attachments as downloadable file chips without DOM data', () => {
    const attachment = normalizeDisplayAttachment(
      { type: 'text/html', name: 'preview.html', data: 'PGh0bWw+' },
      { messageId: 'm1', index: 0 },
    )

    expect(attachment).toMatchObject({
      kind: 'inline',
      displayId: 'm1:att:0',
      renderKey: 'm1:att:0',
      name: 'preview.html',
      mime: 'text/html',
    })
    expect(attachment.data).toBeUndefined()
    expect(attachment.dataUrl).toBeUndefined()
    expect(attachment.downloadData).toBe('PGh0bWw+')
    expect(isImageDisplayAttachment(attachment)).toBe(false)
  })

  it('keeps inline image data for image history attachments', () => {
    const attachment = normalizeDisplayAttachment(
      { type: 'image/png', name: 'photo.png', data: 'aW1hZ2U=' },
      { messageId: 'm1', index: 1 },
    )

    expect(attachment).toMatchObject({
      kind: 'inline',
      displayId: 'm1:att:1',
      name: 'photo.png',
      mime: 'image/png',
      data: 'aW1hZ2U=',
    })
    expect(isImageDisplayAttachment(attachment)).toBe(true)
  })

  it('preserves staged history refs without exposing file_uuid', () => {
    const attachment = normalizeDisplayAttachment(
      {
        sha256_ref: 'd'.repeat(64),
        name: 'report.pdf',
        mime: 'application/pdf',
        size: 1234,
        download_url: '/api/v1/attachments/d',
        file_uuid: 'u-secret',
      },
      { messageId: 'm2', index: 0 },
    )

    expect(attachment).toMatchObject({
      kind: 'staged',
      displayId: `sha:${'d'.repeat(64)}:0`,
      name: 'report.pdf',
      mime: 'application/pdf',
      size: 1234,
      download_url: '/api/v1/attachments/d',
      sha256_ref: 'd'.repeat(64),
    })
    expect(JSON.stringify(attachment)).not.toContain('u-secret')
    expect(attachment.data).toBeUndefined()
  })

  it('chooses the first valid MIME-like value and ignores generic type values', () => {
    expect(normalizeDisplayAttachment({ mime: 'file', mime_type: 'application/pdf', type: 'image/png' }).mime).toBe('application/pdf')
    expect(normalizeDisplayAttachment({ media_type: 'text/csv', type: 'image/png' }).mime).toBe('text/csv')
    expect(normalizeDisplayAttachment({ type: 'file' }).mime).toBe('application/octet-stream')
  })

  it('preserves data only when the inferred MIME is image/*', () => {
    const nonImage = normalizeDisplayAttachment({
      mime_type: 'application/pdf',
      type: 'image/png',
      data: 'payload',
      dataUrl: 'data:image/png;base64,payload',
    })
    const image = normalizeDisplayAttachment({
      mime: 'image/webp',
      type: 'attachment',
      data: 'payload',
      dataUrl: 'data:image/webp;base64,payload',
    })

    expect(nonImage.mime).toBe('application/pdf')
    expect(nonImage.data).toBeUndefined()
    expect(nonImage.dataUrl).toBeUndefined()
    expect(nonImage.downloadData).toBe('payload')
    expect(image.data).toBe('payload')
    expect(image.dataUrl).toBe('data:image/webp;base64,payload')
  })

  it('rejects an active or mismatched media type hidden behind an image declaration', () => {
    const svgAsPng = normalizeDisplayAttachment({
      mime: 'image/png',
      name: 'disguised.png',
      data_url: 'data:image/svg+xml;base64,PHN2Zz4=',
    })
    const htmlAsPng = normalizeDisplayAttachment({
      mime: 'image/png',
      name: 'disguised.png',
      data_url: 'data:text/html;base64,PGh0bWw+',
    })
    const nonBase64 = normalizeDisplayAttachment({
      mime: 'image/png',
      name: 'disguised.png',
      data_url: 'data:image/png,<svg onload=alert(1)>',
    })

    expect(svgAsPng.dataUrl).toBeUndefined()
    expect(htmlAsPng.dataUrl).toBeUndefined()
    expect(nonBase64.dataUrl).toBeUndefined()
  })

  it('normalizes batches with stable index-based keys for duplicate filenames', () => {
    const attachments = normalizeDisplayAttachments([
      { type: 'text/plain', name: 'same.txt', data: 'a' },
      { type: 'text/plain', name: 'same.txt', data: 'b' },
    ], { messageId: 'm3' })

    expect(attachments.map(att => att.renderKey)).toEqual(['m3:att:0', 'm3:att:1'])
  })
})

describe('attachment send display serialization', () => {
  it('serializes staged optimistic display attachments without file_uuid or local_id', () => {
    const staged: Attachment & { kind: 'staged'; file_uuid: string } = {
      kind: 'staged',
      local_id: 7,
      name: 'ready.pdf',
      mime: 'application/pdf',
      file_uuid: 'u-secret',
    }

    const display = serializeDisplayAttachment(staged)

    expect(display).toMatchObject({
      kind: 'staged',
      displayId: 'local:7',
      renderKey: 'local:7',
      name: 'ready.pdf',
      mime: 'application/pdf',
    })
    expect(JSON.stringify(display)).not.toContain('u-secret')
    expect(JSON.stringify(display)).not.toContain('local_id')
  })

  it('keeps non-image optimistic bytes download-only and image bytes previewable', () => {
    const text: Attachment & { kind: 'inline'; data: string } = {
      kind: 'inline',
      local_id: 1,
      name: 'preview.html',
      mime: 'text/html',
      data: 'PGh0bWw+',
      dataUrl: 'data:text/html;base64,PGh0bWw+',
    }
    const image: Attachment & { kind: 'inline'; data: string } = {
      kind: 'inline',
      local_id: 2,
      name: 'photo.png',
      mime: 'image/png',
      data: 'aW1hZ2U=',
      dataUrl: 'data:image/png;base64,aW1hZ2U=',
    }

    expect(serializeDisplayAttachment(text).data).toBeUndefined()
    expect(serializeDisplayAttachment(text).dataUrl).toBeUndefined()
    expect(serializeDisplayAttachment(text).downloadData).toBe('PGh0bWw+')
    expect(serializeDisplayAttachment(image).data).toBe('aW1hZ2U=')
    expect(serializeDisplayAttachment(image).dataUrl).toBe('data:image/png;base64,aW1hZ2U=')
  })

  it('retains the original local file without exposing upload credentials', () => {
    const localFile = new File(['bytes'], 'ready.pdf', { type: 'application/pdf' })
    const staged: Attachment & { kind: 'staged'; file_uuid: string } = {
      kind: 'staged',
      local_id: 9,
      name: 'ready.pdf',
      mime: 'application/pdf',
      file_uuid: 'u-secret',
      file: localFile,
    }

    const display = serializeDisplayAttachment(staged)

    expect(display.localFile).toBe(localFile)
    expect(JSON.stringify(display)).not.toContain('u-secret')
  })

  it('keeps SVG attachment markup download-only', () => {
    const attachment = normalizeDisplayAttachment({
      type: 'image/svg+xml; charset=utf-8',
      name: 'drawing.svg',
      data: 'PHN2Zz4=',
      data_url: 'data:image/svg+xml;base64,PHN2Zz4=',
    })

    expect(isImageDisplayAttachment(attachment)).toBe(false)
    expect(attachment.dataUrl).toBeUndefined()
    expect(attachment.data).toBeUndefined()
    expect(attachment.downloadData).toBe('PHN2Zz4=')
  })
})
