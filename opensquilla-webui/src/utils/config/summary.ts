const SECRET_KEY_RE = /key|token|secret|password/i
const STR_TRUNC = 40

export function formatPreviewValue(key: string, value: unknown): string {
  if (SECRET_KEY_RE.test(key)) return '"***"'
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (typeof value === 'boolean' || typeof value === 'number') return String(value)
  if (typeof value === 'string') {
    const trimmed = value.length > STR_TRUNC ? value.slice(0, STR_TRUNC - 1) + '…' : value
    return JSON.stringify(trimmed)
  }
  if (Array.isArray(value)) return `[${value.length}]`
  if (typeof value === 'object') return `{${Object.keys(value as object).length}}`
  return JSON.stringify(value)
}

export function objectSummary(value: unknown): string {
  if (Array.isArray(value)) {
    const len = value.length
    if (len === 0) return 'JSON · empty list'
    const preview = value.slice(0, 2).map(v => formatPreviewValue('item', v)).join(', ')
    const more = len > 2 ? ', …' : ''
    return `JSON · ${len} ${len === 1 ? 'item' : 'items'} · [${preview}${more}]`
  }
  if (value && typeof value === 'object') {
    const keys = Object.keys(value)
    if (keys.length === 0) return 'JSON · empty object'
    const previewKeys = keys.slice(0, 2)
    const parts = previewKeys.map(k => `${k}: ${formatPreviewValue(k, (value as Record<string, unknown>)[k])}`)
    const more = keys.length > previewKeys.length ? ', …' : ''
    return `JSON · ${keys.length} ${keys.length === 1 ? 'key' : 'keys'} · {${parts.join(', ')}${more}}`
  }
  return 'JSON · value'
}

export function searchBlob(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') {
    try { return JSON.stringify(value).toLowerCase() }
    catch { return '' }
  }
  return String(value).toLowerCase()
}
