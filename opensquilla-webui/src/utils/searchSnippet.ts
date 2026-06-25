// Render an FTS5 transcript snippet as safe highlight HTML for the command
// palette. The backend wraps matched terms in literal >>> / <<< delimiters
// (see SessionStorage.search_transcript). We HTML-escape the whole snippet
// FIRST, so the only markup in the output is the <mark> we inject — a snippet
// containing e.g. "<script>" can never become live markup.

export function highlightFtsSnippet(snippet: string, markClass = 'cmdp-mark'): string {
  const escaped = (snippet || '')
    .split('&').join('&amp;')
    .split('<').join('&lt;')
    .split('>').join('&gt;')
  return escaped
    .split('&gt;&gt;&gt;').join(`<mark class="${markClass}">`)
    .split('&lt;&lt;&lt;').join('</mark>')
}
