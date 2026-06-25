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

// Syntax highlighting is the heaviest part of the render and re-runs over the
// whole code block on every flush during streaming. While a turn is streaming
// we render code as plain (escaped) monospace and defer highlighting to the
// committed message — a one-time recolor at the end, no reflow. renderMarkdown
// toggles this around each parse; it is synchronous so the flag never leaks.
let codeHighlightEnabled = true

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
        codeHighlightEnabled && language.length > 0 && text.length <= HIGHLIGHT_MAX_CHARS && Boolean(hljs.getLanguage(language))
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

// Markdown only ever emits <input> as a disabled task-list checkbox. Drop any
// other raw <input> outright so assistant text cannot render editable fields.
DOMPurify.addHook('uponSanitizeElement', (node, data) => {
  if (data.tagName !== 'input') return
  if ((node as Element).getAttribute('type') !== 'checkbox') {
    node.parentNode?.removeChild(node)
  }
})

// GFM table `align` and the task-list checkbox `type` are allow-listed and
// marked URI-safe (see ADD_URI_SAFE_ATTR below) so the sanitizer keeps them
// through its normal pipeline; here they are additionally constrained to the
// exact tags and values markdown emits, so nothing else can ride in on those
// attribute names. `class` is only allowed where the code renderer above emits
// it; markdown cannot smuggle arbitrary classes onto other elements.
DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
  const tag = node.nodeName.toLowerCase()

  // Table column alignment — only the enum values, and only on table cells.
  if (data.attrName === 'align') {
    const ok = (tag === 'th' || tag === 'td')
      && (data.attrValue === 'left' || data.attrValue === 'center' || data.attrValue === 'right')
    if (!ok) data.keepAttr = false
    return
  }

  // The only inputs markdown emits are disabled task-list checkboxes.
  if (data.attrName === 'type') {
    if (!(tag === 'input' && data.attrValue === 'checkbox')) data.keepAttr = false
    return
  }

  if (data.attrName !== 'class') return
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

// External links open in a new tab without leaking the opener (only http(s)
// anchors become cross-document). Task-list checkboxes are forced inert so a
// raw `<input type="checkbox">` cannot render as an interactive control.
DOMPurify.addHook('afterSanitizeAttributes', node => {
  if (node.nodeName === 'A') {
    const href = node.getAttribute('href') || ''
    if (/^https?:/i.test(href)) {
      node.setAttribute('target', '_blank')
      node.setAttribute('rel', 'noopener noreferrer')
    }
    return
  }
  if (node.nodeName === 'INPUT') {
    node.setAttribute('disabled', '')
  }
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

  function renderMarkdown(text: string, opts?: { highlight?: boolean }): string {
    text = stripProtocolTextLeak(stripDirectiveTags(stripGeneratedArtifactMarkers(text)))
    if (!text) return ''

    // Cache key is namespaced by highlight mode so a plain streaming render is
    // never served where a highlighted one is expected (and vice versa).
    const highlight = opts?.highlight !== false
    const cacheKey = (highlight ? 'H\n' : 'P\n') + text
    const cached = markdownCache.get(cacheKey)
    if (cached !== undefined) return cached

    // Toggle the shared code-highlight flag only across the synchronous parse;
    // try/finally guarantees it is restored even if marked.parse throws, so a
    // later highlighted render can never inherit a stale "plain" flag.
    let rawHtml: string
    codeHighlightEnabled = highlight
    try {
      rawHtml = marked.parse(text, { async: false, breaks: true }) as string
    } finally {
      codeHighlightEnabled = true
    }
    const html = DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: [
        'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
        'strong', 'em', 'del', 'a', 'table', 'thead',
        'tbody', 'tr', 'th', 'td', 'div', 'span', 'sup', 'input',
      ],
      // `align` carries GFM table column alignment; `type`/`checked`/`disabled`
      // are the (disabled) task-list checkbox attributes. No script vectors.
      ALLOWED_ATTR: ['href', 'title', 'alt', 'target', 'rel', 'class', 'align', 'type', 'checked', 'disabled'],
      // `align`/`type` carry inert presentational values, not URIs; mark them
      // safe so the value gate keeps them (the hook above constrains the values).
      ADD_URI_SAFE_ATTR: ['align', 'type'],
      ALLOWED_URI_REGEXP: /^(?:https?|mailto|#):/i,
    })

    if (markdownCache.size >= MARKDOWN_CACHE_MAX) {
      const firstKey = markdownCache.keys().next().value
      if (firstKey !== undefined) markdownCache.delete(firstKey)
    }
    markdownCache.set(cacheKey, html)
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
