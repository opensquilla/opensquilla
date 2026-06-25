/** OpenSquilla Web UI — Markdown renderer powered by marked.js with code-block copy. */

const Markdown = (() => {
  if (typeof marked !== 'undefined') {
    marked.setOptions({
      gfm: true,
      breaks: true,
    });
  }

  // Protect LaTeX-ish spans from marked's emphasis/escape rules: stash
  // before parse, restore after. Left-biased alternation lets fenced code
  // and inline code win at the same position, so `$` inside code is left
  // alone. Single-$ inline rejects leading digit/space and trailing space
  // so "$x=1$" works but "price $5, total $10" is not eaten as one span.
  const _MATH_SCAN = /(```[\s\S]*?```|`[^`\n]+?`|\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([^)\n]+?\\\)|\$(?![\s\d])(?:\\\$|[^$\n])+?(?<![\s])\$)/g;
  const _MATH_SENTINEL = /M(\d+)/g;

  function _stashMath(text) {
    const stash = [];
    const out = text.replace(_MATH_SCAN, (m) => {
      // Code fences/inline code: keep verbatim, do not stash.
      if (m.startsWith('```') || (m.startsWith('`') && !m.startsWith('$'))) return m;
      const idx = stash.length;
      stash.push(m);
      return `M${idx}`;
    });
    return { text: out, stash };
  }

  // Render a single LaTeX expression to HTML using KaTeX.
  // Returns null when KaTeX is unavailable or rendering fails.
  function _renderLatex(raw) {
    if (typeof katex === 'undefined') return null;

    // Detect delimiter and strip it
    let tex, displayMode;
    if (raw.startsWith('$$') || raw.startsWith('\\[')) {
      // Display math: $$ ... $$ or \[ ... \]
      displayMode = true;
      if (raw.startsWith('$$')) {
        tex = raw.slice(2, -2);
      } else {
        tex = raw.slice(2, -2);
      }
    } else if (raw.startsWith('$') && !raw.startsWith('$$')) {
      // Inline math: $ ... $
      displayMode = false;
      tex = raw.slice(1, -1);
    } else if (raw.startsWith('\\(')) {
      // Inline math: \( ... \)
      displayMode = false;
      tex = raw.slice(2, -2);
    } else {
      return null;
    }

    try {
      const rendered = katex.renderToString(tex, {
        displayMode: displayMode,
        throwOnError: false,
        strict: false,
      });
      return rendered;
    } catch (e) {
      return null;
    }
  }

  function _restoreMath(html, stash) {
    if (stash.length === 0) return html;
    return html.replace(_MATH_SENTINEL, (_, i) => {
      const raw = stash[Number(i)];
      if (raw === undefined) return '';

      // Try KaTeX rendering first
      const rendered = _renderLatex(raw);
      if (rendered !== null) return rendered;

      // Fallback: show raw code
      const isDisplay = raw.startsWith('$$') || raw.startsWith('\\[');
      const cls = isDisplay ? 'math-raw math-block' : 'math-raw';
      return `<code class="${cls}" title="LaTeX formula (raw)">${_escape(raw)}</code>`;
    });
  }

  function render(text) {
    if (!text) return '';

    if (typeof marked !== 'undefined') {
      const { text: stashed, stash } = _stashMath(text);

      let html = typeof DOMPurify !== 'undefined'
        ? DOMPurify.sanitize(marked.parse(stashed))
        : marked.parse(stashed);

      html = html.replace(
        /<pre><code(?: class="language-(\w+)")?>([\s\S]*?)<\/code><\/pre>/g,
        (_, lang, code) => {
          const id = 'cb-' + Math.random().toString(36).slice(2, 8);
          const langLabel = lang || '';
          return `<div class="code-block"><div class="code-block-header"><span class="code-lang">${langLabel}</span><button class="btn btn--sm btn--ghost copy-btn" data-target="${id}">${typeof icons !== 'undefined' ? icons.copy() : 'Copy'} Copy</button></div><pre id="${id}"><code>${code}</code></pre></div>`;
        }
      );

      html = _restoreMath(html, stash);

      return html;
    }

    return _fallbackRender(text);
  }

  function _fallbackRender(text) {
    let html = _escape(text);
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const id = 'cb-' + Math.random().toString(36).slice(2, 8);
      return `<div class="code-block"><div class="code-block-header"><span class="code-lang">${lang}</span><button class="btn btn--sm btn--ghost copy-btn" data-target="${id}">${typeof icons !== 'undefined' ? icons.copy() : 'Copy'} Copy</button></div><pre id="${id}"><code>${code}</code></pre></div>`;
    });
    html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    html = html.replace(/\n\n/g, '<br><br>');
    return html;
  }

  function _escape(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function bindCopy(container) {
    container.querySelectorAll('.copy-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = document.getElementById(btn.dataset.target);
        if (!target) return;
        btn.disabled = true;
        _copyText(target.textContent)
          .then(() => {
            _showCopyStatus(btn, `${typeof icons !== 'undefined' ? icons.check() : '\u2713'} Copied`);
          })
          .catch((err) => {
            console.warn('Copy failed', err);
            _showCopyStatus(btn, `${typeof icons !== 'undefined' ? icons.x() : '!'} Failed`, 1800);
            if (typeof UI !== 'undefined' && UI.toast) {
              UI.toast('Copy failed. Select the code manually.', 'err', 3000);
            }
          })
          .finally(() => {
            btn.disabled = false;
          });
      });
    });
  }

  function _copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      return navigator.clipboard.writeText(text).catch(() => _copyTextFallback(text));
    }
    return _copyTextFallback(text);
  }

  function _copyTextFallback(text) {
    return new Promise((resolve, reject) => {
      if (!document.body || typeof document.execCommand !== 'function') {
        reject(new Error('Clipboard API unavailable'));
        return;
      }

      const textarea = document.createElement('textarea');
      const activeElement = document.activeElement;
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.top = '0';
      textarea.style.left = '0';
      textarea.style.width = '1px';
      textarea.style.height = '1px';
      textarea.style.opacity = '0';
      textarea.style.pointerEvents = 'none';

      document.body.appendChild(textarea);
      _focusWithoutScroll(textarea);
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);

      let copied = false;
      try {
        copied = document.execCommand('copy');
      } catch (err) {
        reject(err);
        return;
      } finally {
        document.body.removeChild(textarea);
        if (activeElement && typeof activeElement.focus === 'function') {
          _focusWithoutScroll(activeElement);
        }
      }

      if (copied) resolve();
      else reject(new Error('Copy command rejected'));
    });
  }

  function _focusWithoutScroll(el) {
    try {
      el.focus({ preventScroll: true });
    } catch (_) {
      el.focus();
    }
  }

  function _showCopyStatus(btn, html, duration = 1500) {
    if (!btn.dataset.copyOriginalHtml) {
      btn.dataset.copyOriginalHtml = btn.innerHTML;
    }
    if (btn._copyStatusTimer) clearTimeout(btn._copyStatusTimer);

    btn.innerHTML = html;
    btn._copyStatusTimer = setTimeout(() => {
      btn.innerHTML = btn.dataset.copyOriginalHtml;
      delete btn.dataset.copyOriginalHtml;
      btn._copyStatusTimer = null;
    }, duration);
  }

  function bindHighlight(container) {
    if (typeof Prism === 'undefined') return;
    container.querySelectorAll('pre code[class*="language-"]').forEach(el => {
      Prism.highlightElement(el);
    });
  }

  return { render, bindCopy, bindHighlight };
})();

window.Markdown = Markdown;