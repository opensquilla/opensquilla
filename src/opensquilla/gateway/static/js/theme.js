/** OpenSquilla Web UI — Theme manager (dark / light toggle). */

const Theme = (() => {
  const STORAGE_KEY = 'opensquilla-theme';

  // Resolve the default from `prefers-color-scheme` so users with dark-mode
  // OS settings see dark on first load instead of flashing through light.
  function _systemDefault() {
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch {
      return 'light';
    }
  }

  let _current = _systemDefault();

  function _apply(mode) {
    document.documentElement.setAttribute('data-theme', mode);
  }

  function set(mode) {
    if (mode !== 'dark' && mode !== 'light') return;
    _current = mode;
    localStorage.setItem(STORAGE_KEY, mode);
    _apply(mode);
    _updateToggle();
  }

  function toggle() {
    set(_current === 'dark' ? 'light' : 'dark');
  }

  function init() {
    _current = localStorage.getItem(STORAGE_KEY) || _systemDefault();
    _apply(_current);
    // Sync toggle icon with saved preference (runs after DOM is ready)
    requestAnimationFrame(() => _updateToggle());
  }

  function _updateToggle() {
    const el = document.getElementById('theme-toggle');
    if (!el) return;
    // icons.moon/sun are internal SVG helpers, not user content
    el.innerHTML = _current === 'dark' ? icons.moon() : icons.sun();
    el.title = 'Theme: ' + _current;
    el.setAttribute('aria-label', 'Theme: ' + _current + '. Toggle theme');
    el.setAttribute('aria-pressed', _current === 'dark' ? 'true' : 'false');
  }

  function currentMode() { return _current; }

  return { init, set, toggle, cycle: toggle, currentMode };
})();

window.Theme = Theme;
