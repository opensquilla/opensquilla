/** OpenSquilla Web UI — History API SPA router. */

const Router = (() => {
  const _routes = new Map();
  let _basePath = '/control';
  let _currentPath = '';
  let _contentEl = null;
  let _currentDestroy = null;

  function register(path, viewFn, destroyFn, meta = {}) {
    _routes.set(path, { viewFn, destroyFn: destroyFn || null, meta });
  }

  function init(basePath, contentEl) {
    _basePath = basePath.replace(/\/$/, '');
    _contentEl = contentEl;
    window.addEventListener('popstate', () => _resolve());
    _resolve();
  }

  function navigate(path) {
    const [pathPart, queryPart] = path.split('?');
    const full = _basePath + pathPart + (queryPart ? '?' + queryPart : '');
    if (window.location.pathname + window.location.search === full) return;
    history.pushState(null, '', full);
    _resolve();
  }

  function _resolve() {
    const pathname = window.location.pathname;
    let rel = pathname.startsWith(_basePath) ? pathname.slice(_basePath.length) : pathname;
    if (!rel || rel === '/') rel = window.matchMedia('(max-width: 768px)').matches ? '/chat' : '/overview';

    const fullKey = rel + window.location.search;
    if (fullKey === _currentPath) return;

    if (_currentDestroy) { _currentDestroy(); _currentDestroy = null; }

    _currentPath = fullKey;

    const route = _routes.get(rel);
    if (_contentEl) {
      _contentEl.innerHTML = '';
      if (route) {
        route.viewFn(_contentEl);
        _currentDestroy = route.destroyFn;
      } else {
        // 404 fallback: build via DOM so the URL path can never be
        // interpreted as HTML even if a browser leaves angle-brackets
        // un-encoded in `location.pathname`.
        const div = document.createElement('div');
        div.style.padding = '2rem';
        div.style.color = 'var(--text-muted)';
        div.textContent = 'Page not found: ' + rel;
        _contentEl.appendChild(div);
      }
    }

    document.querySelectorAll('.nav-item').forEach(el => {
      const isActive = el.dataset.path === rel;
      el.classList.toggle('is-active', isActive);
      // aria-current tells screen readers which nav target represents the
      // currently displayed page; matches the visual `.is-active` class.
      if (isActive) el.setAttribute('aria-current', 'page');
      else el.removeAttribute('aria-current');
    });

    const title = route?.meta?.title || 'Not Found';
    const titleEl = document.getElementById('topbar-title');
    if (titleEl) titleEl.dataset.pageTitle = title;
    document.title = title === 'OpenSquilla' ? 'OpenSquilla Control' : `${title} - OpenSquilla Control`;
  }

  function currentPath() { return _currentPath.split('?')[0]; }

  return { register, init, navigate, currentPath };
})();

window.Router = Router;
