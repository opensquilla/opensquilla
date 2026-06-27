// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest'

import { useChatTextRendering } from './useChatTextRendering'

describe('useChatTextRendering math', () => {
  it('renders inline and display LaTeX with KaTeX', () => {
    const { renderMarkdown } = useChatTextRendering()

    const inline = renderMarkdown('Inline $x^2$ formula')
    const display = renderMarkdown('Block:\n\n$$\\frac{a}{b}$$')

    expect(inline).toContain('class="katex"')
    expect(inline).not.toContain('$x^2$')
    expect(display).toContain('class="katex-display"')
    expect(display).not.toContain('$$\\frac{a}{b}$$')
  })
})
