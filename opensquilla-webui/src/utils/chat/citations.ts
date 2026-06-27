import type { SourcePart } from '@/types/parts'

// Single-integer markers only: `[2]`. One to three digits keeps the matched
// number sane (and the source list is capped at 12) without any unbounded
// backtracking. Ranges (`[2-4]`), lists (`[2, 3]`), and footnotes (`[^2]`) are
// intentionally out of scope.
const CITATION_RE = /\[(\d{1,3})\]/g

// Never pill a `[n]` that lives inside code samples, an existing link, or an
// already-built pill. CODE covers inline code and `<pre><code>` blocks.
const SKIP_ANCESTORS = new Set(['PRE', 'CODE', 'A', 'BUTTON'])

export interface CitationDecorateOptions {
  /** Called when a pill is activated (click / Enter / Space). */
  onActivate: (sourceId: number) => void
  /** Accessible label fragment for a source, keyed by sourceId (title or domain). */
  labelFor: (sourceId: number) => string
}

/**
 * Walk TEXT nodes under `root` and wrap every `[n]` that maps to a real source
 * (1 ≤ n ≤ sources.length) in a focusable `<button.citation-pill>`. Pure DOM:
 * pills are built with `document.createElement` / `textContent` / `setAttribute`
 * only — the function never parses HTML, never reads or writes innerHTML, and
 * never touches attributes on existing nodes. Markers with no matching source
 * are left as untouched text.
 *
 * Idempotent: text already inside a decorated pill (or any skip ancestor) is
 * passed over, so re-running on the same subtree creates no duplicates. Returns
 * the number of pills created.
 */
export function decorateCitations(
  root: HTMLElement,
  sources: readonly SourcePart[],
  opts: CitationDecorateOptions,
): number {
  if (!root || sources.length === 0) return 0

  // Collect candidate text nodes first; mutating the tree mid-walk would
  // invalidate the live TreeWalker cursor.
  const candidates: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue
    if (!text || !text.includes('[')) continue
    if (isInSkippedAncestor(node.parentNode)) continue
    candidates.push(node as Text)
  }

  let created = 0
  for (const node of candidates) {
    created += decorateTextNode(node, sources, opts)
  }
  return created
}

function isInSkippedAncestor(node: Node | null): boolean {
  let current: Node | null = node
  while (current && current instanceof HTMLElement) {
    if (SKIP_ANCESTORS.has(current.nodeName)) return true
    if (current.hasAttribute('data-citation')) return true
    current = current.parentNode
  }
  return false
}

function decorateTextNode(
  node: Text,
  sources: readonly SourcePart[],
  opts: CitationDecorateOptions,
): number {
  const text = node.nodeValue ?? ''
  CITATION_RE.lastIndex = 0
  let match = CITATION_RE.exec(text)
  if (!match) return 0

  const frag = document.createDocumentFragment()
  let lastIndex = 0
  let created = 0
  let changed = false

  while (match) {
    const n = Number(match[1])
    const start = match.index
    const end = start + match[0].length
    if (n >= 1 && n <= sources.length) {
      if (start > lastIndex) {
        frag.appendChild(document.createTextNode(text.slice(lastIndex, start)))
      }
      frag.appendChild(buildPill(n, opts))
      lastIndex = end
      created += 1
      changed = true
    }
    match = CITATION_RE.exec(text)
  }

  if (!changed) return 0
  if (lastIndex < text.length) {
    frag.appendChild(document.createTextNode(text.slice(lastIndex)))
  }
  node.replaceWith(frag)
  return created
}

function buildPill(n: number, opts: CitationDecorateOptions): HTMLButtonElement {
  const pill = document.createElement('button')
  pill.type = 'button'
  pill.className = 'citation-pill'
  pill.textContent = `[${n}]`
  pill.setAttribute('data-citation', String(n))
  pill.setAttribute('aria-label', `Jump to source ${n}: ${opts.labelFor(n)}`)
  pill.addEventListener('click', () => opts.onActivate(n))
  return pill
}
