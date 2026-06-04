import type { ArtifactPayload } from '@/types/rpc'
import type { IconName } from '@/utils/icons'

const ARTIFACT_MIME_CATEGORIES: Record<string, string> = {
  'application/json': 'data', 'application/ndjson': 'data', 'application/pdf': 'document',
  'application/x-ndjson': 'data', 'text/csv': 'data', 'text/html': 'document',
  'text/markdown': 'document', 'text/plain': 'document', 'text/tab-separated-values': 'data',
}

const ARTIFACT_EXTENSION_CATEGORIES: Record<string, string> = {
  csv: 'data', htm: 'document', html: 'document', ipynb: 'data', json: 'data',
  jsonl: 'data', log: 'document', markdown: 'document', md: 'document',
  ndjson: 'data', pdf: 'document', sql: 'code', tsv: 'data', txt: 'document',
}

export function artifactMime(artifact: ArtifactPayload): string {
  return artifact?.mime ? String(artifact.mime).toLowerCase() : ''
}

export function artifactName(artifact: ArtifactPayload): string {
  return artifact?.name ? String(artifact.name) : 'artifact'
}

export function artifactExtension(name: string): string {
  const trimmed = String(name || '').trim().toLowerCase()
  const idx = trimmed.lastIndexOf('.')
  if (idx < 0 || idx === trimmed.length - 1) return ''
  return trimmed.slice(idx + 1)
}

export function artifactCategory(artifact: ArtifactPayload): string {
  const mime = artifactMime(artifact)
  if (mime.startsWith('image/')) return 'visual'
  if (ARTIFACT_MIME_CATEGORIES[mime]) return ARTIFACT_MIME_CATEGORIES[mime]
  if (!mime || mime === 'application/octet-stream') {
    const ext = artifactExtension(artifactName(artifact))
    if (ARTIFACT_EXTENSION_CATEGORIES[ext]) return ARTIFACT_EXTENSION_CATEGORIES[ext]
  }
  return 'file'
}

export function artifactCategoryLabel(artifact: ArtifactPayload): string {
  const cat = artifactCategory(artifact)
  switch (cat) {
    case 'data': return 'data'
    case 'document': return 'doc'
    case 'code': return 'code'
    default: return 'file'
  }
}

export function artifactIconName(artifact: ArtifactPayload): IconName {
  const cat = artifactCategory(artifact)
  if (cat === 'visual') return 'image'
  if (cat === 'data') return 'table'
  if (cat === 'code') return 'fileCode'
  return 'fileText'
}

export function artifactFileTitle(artifact: ArtifactPayload): string {
  return artifactName(artifact)
}

export function artifactFileSubtitle(artifact: ArtifactPayload): string {
  const label = artifactCategoryLabel(artifact)
  const meta = artifactMeta(artifact)
  const action = artifactActionLabel(artifact) === '预览' ? '预览文件' : '下载文件'
  return [action, label.toUpperCase(), meta].filter(Boolean).join(' · ')
}

export function artifactActionLabel(artifact: ArtifactPayload): string {
  const cat = artifactCategory(artifact)
  return cat === 'visual' || cat === 'document' ? '预览' : '下载'
}

export function artifactMeta(artifact: ArtifactPayload): string {
  const mime = artifact?.mime ? String(artifact.mime) : ''
  const size = artifact?.size ? `${Math.max(1, Math.round(Number(artifact.size) / 1024))} KB` : ''
  return [mime, size].filter(Boolean).join(' · ')
}

export function artifactDownloadUrl(artifact: ArtifactPayload, baseOrigin: string): string {
  let raw = artifact?.download_url ? String(artifact.download_url) : ''
  if (!raw && artifact?.id) raw = `/api/v1/artifacts/${encodeURIComponent(artifact.id)}`
  if (!raw) return ''
  try {
    const url = new URL(raw, baseOrigin)
    url.searchParams.delete('sessionKey')
    url.searchParams.delete('session_key')
    return url.pathname + url.search + url.hash
  } catch { return raw }
}
