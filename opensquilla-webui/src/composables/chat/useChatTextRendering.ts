import { marked, type Tokens } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'

const DIRECTIVE_TAG_RE = /\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*/g
const GENERATED_ARTIFACT_MARKER_RE = /(?:^|\s*)\[generated artifact omitted:\s*[^\]\n]+?\]\s*/gi
const PROTOCOL_TEXT_MARKER_RE = /<\s*(?:minimax:tool_call|tool_calls?|tvoe_calls|invoke\b|parameter\b|effect_calls\b|details\b|angle\s+brackets\b)/i
const TIME_PREFIX_RE = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+\-]\d{2}:\d{2} (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Za-z0-9_+\-/]+\]\n/

const MARKDOWN_CACHE_MAX = 500
// Highlighting is synchronous inside the streaming render path; past this
// size a block renders as plain mono text so it cannot stall a flush.
const HIGHLIGHT_MAX_CHARS = 30_000
// The only class names allowed through sanitization: highlighter token
// classes (incl. sub-scope suffixes like `function_`) and the code chrome.
const CODE_CLASS_RE = /^(?:hljs|hljs-[\w-]+|language-[\w#+.-]+|code-lang|function_|class_|inherited__)$/

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

marked.use({
  renderer: {
    code({ text, lang }: Tokens.Code): string {
      const language = (lang || '').trim().split(/\s+/)[0].toLowerCase()
      const canHighlight =
        language.length > 0 && text.length <= HIGHLIGHT_MAX_CHARS && Boolean(hljs.getLanguage(language))
      let body = ''
      if (canHighlight) {
        try {
          body = hljs.highlight(text, { language, ignoreIllegals: true }).value
        } catch {
          body = ''
        }
      }
      if (!body) body = escapeHtml(text)
      const label = language ? `<span class="code-lang">${escapeHtml(language)}</span>` : ''
      const langClass = canHighlight ? ` language-${language}` : ''
      return `<pre>${label}<code class="hljs${langClass}">${body}</code></pre>\n`
    },
  },
})

// `class` is only allowed where the code renderer above emits it; markdown
// cannot smuggle arbitrary classes onto other elements or unknown values in.
DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
  if (data.attrName !== 'class') return
  const tag = node.nodeName.toLowerCase()
  if (tag !== 'code' && tag !== 'span') {
    data.keepAttr = false
    return
  }
  const safe = String(data.attrValue || '')
    .split(/\s+/)
    .filter(cls => CODE_CLASS_RE.test(cls))
  if (safe.length === 0) {
    data.keepAttr = false
    return
  }
  data.attrValue = safe.join(' ')
})

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
      ALLOWED_ATTR: ['href', 'title', 'alt', 'target', 'rel', 'class'],
      ALLOWED_URI_REGEXP: /^(?:https?|mailto|#):/i,
    })

    if (markdownCache.size >= MARKDOWN_CACHE_MAX) {
      const firstKey = markdownCache.keys().next().value
      if (firstKey !== undefined) markdownCache.delete(firstKey)
    }
    markdownCache.set(text, html)
    return html
  }

  function sanitizeCopyText(text: string): string {
    return stripProtocolTextLeak(
      stripDirectiveTags(stripGeneratedArtifactMarkers(stripTimePrefix(String(text || '')))),
    ).trim()
  }

  return {
    renderMarkdown,
    sanitizeCopyText,
    stripDirectiveTags,
    stripGeneratedArtifactMarkers,
    stripProtocolTextLeak,
    stripTimePrefix,
  }
}
