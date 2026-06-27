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

  // Build a stash entry with the raw text, its math type, and the content
  // with delimiters stripped.
  function _makeMathEntry(m) {
    if (m.startsWith('$$') && m.endsWith('$$')) {
      return { type: 'display', content: m.slice(2, -2).trim() };
    }
    if (m.startsWith('\\[') && m.endsWith('\\]')) {
      return { type: 'display', content: m.slice(2, -2).trim() };
    }
    if (m.startsWith('\\(') && m.endsWith('\\)')) {
      return { type: 'inline', content: m.slice(2, -2).trim() };
    }
    if (m.startsWith('$') && m.endsWith('$')) {
      return { type: 'inline', content: m.slice(1, -1).trim() };
    }
    return null; // not a recognized math expression
  }

  function _stashMath(text) {
    const stash = [];
    const out = text.replace(_MATH_SCAN, (m) => {
      // Code fences/inline code: keep verbatim, do not stash.
      if (m.startsWith('```') || (m.startsWith('`') && !m.startsWith('$'))) return m;
      const idx = stash.length;
      stash.push(_makeMathEntry(m));
      return `M${idx}`;
    });
    return { text: out, stash };
  }

  function _renderMathWithKatex(raw, type) {
    if (typeof katex === 'undefined' || !katex.renderToString) {
      // KaTeX not loaded: fall back to raw code display
      return `<code class="math-raw" title="LaTeX formula">${_escape(raw)}</code>`;
    }
    try {
      const html = katex.renderToString(raw, {
        displayMode: type === 'display',
        throwOnError: false,
        output: 'html',
        trust: true,
      });
      if (type === 'display') {
        return html;
      }
      return html;
    } catch (_e) {
      return `<code class="math-raw" title="LaTeX formula (parse error)">${_escape(raw)}</code>`;
    }
  }

  function _restoreMath(html, stash) {
    if (stash.length === 0) return html;
    return html.replace(_MATH_SENTINEL, (_, i) => {
      const entry = stash[Number(i)];
      if (!entry || !entry.type) return '';
      return _renderMathWithKatex(entry.content, entry.type);
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
