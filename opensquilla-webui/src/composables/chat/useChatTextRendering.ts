import { marked } from 'marked'
import DOMPurify from 'dompurify'

const DIRECTIVE_TAG_RE = /\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*/g
const GENERATED_ARTIFACT_MARKER_RE = /(?:^|\s*)\[generated artifact omitted:\s*[^\]\n]+?\]\s*/gi
const PROTOCOL_TEXT_MARKER_RE = /<\s*(?:minimax:tool_call|tool_calls?|tvoe_calls|invoke\b|parameter\b|effect_calls\b|details\b|angle\s+brackets\b)/i
const TIME_PREFIX_RE = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+\-]\d{2}:\d{2} (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Za-z0-9_+\-/]+\]\n/

const MARKDOWN_CACHE_MAX = 500

export function useChatTextRendering() {
  const markdownCache = new Map<string, string>()

  function stripDirectiveTags(text: string): string {
    return text.replace(DIRECTIVE_TAG_RE, '').replace(/^\n+/, '')
  }

  function stripGeneratedArtifactMarkers(text: string): string {
    text = String(text || '')
    if (!text.includes('[generated artifact omitted:')) return text
    return text.replace(/\r\n/g, '\n').replace(GENERATED_ARTIFACT_MARKER_RE, '').replace(/[ \t]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim()
  }

  function stripProtocolTextLeak(text: string): string {
    text = String(text || '')
    if (!text) return text
    const match = PROTOCOL_TEXT_MARKER_RE.exec(text)
    if (!match) return text
    return text.slice(0, match.index).trimEnd()
  }

  function stripTimePrefix(text: string): string {
    return typeof text === 'string' ? text.replace(TIME_PREFIX_RE, '') : text
  }

  function renderMarkdown(text: string): string {
    text = stripProtocolTextLeak(stripDirectiveTags(stripGeneratedArtifactMarkers(text)))
    if (!text) return ''

    const cached = markdownCache.get(text)
    if (cached !== undefined) return cached

    const rawHtml = marked.parse(text, { async: false, breaks: true }) as string
    const html = DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: [
        'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
        'strong', 'em', 'del', 'a', 'table', 'thead',
        'tbody', 'tr', 'th', 'td', 'div', 'span', 'sup',
      ],
      ALLOWED_ATTR: ['href', 'title', 'alt', 'target', 'rel'],
      ALLOWED_URI_REGEXP: /^(?:https?|mailto|#):/i,
    })

    if (markdownCache.size >= MARKDOWN_CACHE_MAX) {
      const firstKey = markdownCache.keys().next().value
      if (firstKey !== undefined) markdownCache.delete(firstKey)
    }
    markdownCache.set(text, html)
    return html
  }

  return {
    renderMarkdown,
    stripDirectiveTags,
    stripGeneratedArtifactMarkers,
    stripProtocolTextLeak,
    stripTimePrefix,
  }
}
