/** OpenSquilla Web UI - Config view (FE-005). */

const ConfigView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];

  let _configData = {};   // raw object from config.get
  let _yamlText = '';     // current YAML text in textarea
  let _yamlDraft = '';
  let _yamlDirty = false;
  let _dirty = {};        // form mode: { key: { old, new } }
  let _invalidJson = {};  // form mode: { key: true }
  let _jsonDrafts = {};   // form mode JSON textarea text preserved across rerenders
  let _mode = 'form';     // 'form' | 'yaml'
  let _activeTab = 'core';
  let _searchText = '';
  let _diffOpen = false;  // sticky bar inline-diff expansion state
  let _activeTooltip = null;

  const _TABS = [
    { id: 'core',           label: 'Core',           prefixes: ['general', 'auth', 'host', 'port', 'version', 'debug', 'control_ui', 'diagnostics'] },
    { id: 'ai',             label: 'AI & Agents',    prefixes: ['provider', 'model', 'agent', 'llm', 'skills', 'squilla_router', 'prompt_cache', 'thinking'] },
    { id: 'memory',         label: 'Memory',         prefixes: ['memory'] },
    { id: 'communication',  label: 'Communication',  prefixes: ['channel', 'telegram', 'slack', 'discord', 'email', 'messaging'] },
    { id: 'automation',     label: 'Automation',     prefixes: ['cron', 'scheduler'] },
    { id: 'infrastructure', label: 'Infrastructure', prefixes: ['log', 'storage', 'db', 'cache', 'search'] },
  ];

  // Per-field help, keyed by config path. Falls back to a generic message.
  const _HELP = {
    'host':
      'Network interface the gateway binds to. Defaults to 127.0.0.1 (loopback). Use 0.0.0.0 to expose on all interfaces — opt-in only, never on an untrusted network.',
    'port':
      'TCP port for the ASGI gateway. Default 18791. Pick a free port; the WebSocket and REST endpoints share it.',
    'debug':
      'Security-sensitive developer mode. Auth scope expansion can take effect immediately for new connections; Starlette debug, uvicorn log level, and some startup wiring need a gateway restart. Keep it off in shared deployments.',
    'diagnostics_enabled':
      'Default standard diagnostics mode at gateway startup. Raw turn-call capture stays off unless OPENSQUILLA_TURN_CALL_LOG=1 or the running gateway is switched with opensquilla diagnostics on --raw.',
    'log_file_enabled':
      'Writes gateway debug.log records for operator troubleshooting. This is separate from raw turn-call capture, which requires OPENSQUILLA_TURN_CALL_LOG=1 or opensquilla diagnostics on --raw.',
    'log_level':
      'Minimum gateway file log level. OPENSQUILLA_LOG_LEVEL can override this at runtime.',
    'log_file_max_bytes':
      'Maximum debug.log size before rotation. Set to 0 to disable rotation in the stdlib handler.',
    'log_file_backup_count':
      'Number of rotated debug.log backups to retain.',
    'agent_token_saving.tool_result_projection_max_inline_chars':
      'Maximum inline size for canonical tokenjuice tool-result projections. Raw tool output is transient and is not stored.',
    'squilla_router.enabled':
      'Turn the ML-powered tier router on or off. When off, every request uses the default model regardless of complexity.',
    'squilla_router.rollout_phase':
      'Rollout stage for new router model versions. Higher phases enable more aggressive routing decisions.',
    'squilla_router.require_router_runtime':
      'When true, the gateway fails fast on startup if the router cannot initialize (missing ONNX runtime, model files, etc.). Set false to fall back silently.',
    'memory.embedding':
      'Long-term memory embedding provider. Defaults to local bundled BGE in auto mode when available; remote embeddings require explicit memory embedding configuration.',
    'memory.embedding.provider':
      'Canonical memory embedding provider: auto, none, local, openai/openai-compatible, or ollama. This is independent from the chat LLM provider.',
    'memory.embedding.remote.api_key':
      'API key for the memory embedding endpoint. This does not inherit the chat/OpenRouter key in auto mode.',
    'memory.embedding.remote.base_url':
      'OpenAI-compatible API root for memory indexing, for example https://api.openai.com/v1. The provider appends /embeddings.',
    'memory.embedding.local.onnx_dir':
      'Optional ONNX directory for a custom local embedding model. Leave empty to use the bundled BGE-small model.',
    'memory.retrieval_mode':
      'Memory retrieval mode. "hybrid" uses vectors when an embedding provider is available; "fts_only" disables vectors.',
    'sandbox.sandbox':
      'Runtime sandbox switch. The out-of-box posture keeps this false; use opensquilla sandbox on|bypass|full to change sandbox and permission defaults together.',
    'sandbox.security_grading':
      'Risk grading and approval gate for tool actions. Keep this paired with sandbox.sandbox unless using the sandbox CLI posture commands.',
    'permissions.default_mode':
      'Default owner/operator permission mode: bypass is the out-of-box local posture, off keeps sandboxed execution, on uses host execution with approvals, and full bypasses sensitive-path gates too.',
    'prompt_cache.mode':
      'Anthropic prompt cache control. "auto" (default) lets the provider decide; "on" forces caching; "off" disables it entirely.',
    'context_budget_tokens':
      'Soft cap on the assembled prompt size. When exceeded, the configured overflow policy kicks in (summarize, truncate, or refuse).',
    'context_overflow_policy':
      '"auto_summarize" compacts older history via a small LLM; "hard_truncate" drops oldest turns; "refuse" rejects the turn with a stable error.',
    'auth_mode':
      'Gateway auth scheme. "token" requires a static bearer token; "none" is open (loopback only); other modes per deployment.',
  };

  function _helpFor(key) {
    if (key in _HELP) return _HELP[key];
    return 'No description yet — see the docs.';
  }

  // ---- render / destroy ------------------------------------------------

  function _ensureCss() {
    if (document.querySelector('link[data-view-css="config-stage"]')) return;
    const data = document.getElementById('opensquilla-data');
    const base = data?.dataset.basePath || '';
    const cssVersion = data?.dataset.version || '';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${base}/static/css/views/config.css${cssVersion ? '?v=' + encodeURIComponent(cssVersion) : ''}`;
    link.dataset.viewCss = 'config-stage';
    document.head.appendChild(link);
  }

  // Inline icons local to config view (do not edit shared icons.js).
  const _HELP_ICON_SVG = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-width="1.25"/><path d="M5.9 6.1c.2-1.1 1.1-1.85 2.2-1.85 1.2 0 2.05.8 2.05 1.85 0 .85-.45 1.3-1.3 1.85-.65.4-1 .8-1 1.55v.35" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round"/><circle cx="8" cy="11.6" r="0.7" fill="currentColor"/></svg>';
  const _CHEVRON_SVG = '<svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" focusable="false"><path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _ensureCss();

    _el.innerHTML = `
      <div class="cfg-stage">
        <header class="cfg-stage__header">
          <div class="cfg-stage__title-block">
            <span class="cfg-stage__eyebrow">Settings</span>
            <h2 class="cfg-stage__title">Config</h2>
            <p class="cfg-stage__subtitle">Advanced gateway configuration. Use guided setup for provider, router, channels, and extras.</p>
          </div>
          <div class="cfg-stage__actions mobile-action-strip">
            <div class="cfg-mode-toggle mobile-action-strip__item" role="group" aria-label="Editor mode">
              <button class="cfg-mode-btn ${_mode === 'form' ? 'is-active' : ''}" type="button" data-cfg-mode="form">Form</button>
              <button class="cfg-mode-btn ${_mode === 'yaml' ? 'is-active' : ''}" type="button" data-cfg-mode="yaml">YAML</button>
            </div>
            <button class="cfg-btn cfg-btn--ghost mobile-action-strip__button" id="cfg-guided-setup" type="button" title="Open guided setup">${icons.config()}<span class="mobile-action-strip__label">Guided setup</span></button>
            <button class="cfg-btn cfg-btn--ghost mobile-action-strip__button" id="cfg-reload" type="button" title="Reload config">${icons.refresh()}<span class="mobile-action-strip__label">Reload</span></button>
            <button class="cfg-btn cfg-btn--ghost mobile-action-strip__button" id="cfg-save" type="button" title="Save config">${icons.check()}<span class="mobile-action-strip__label">Save</span></button>
          </div>
        </header>

        <!-- Form view -->
        <div id="cfg-form-view">
          <div class="cfg-toolbar">
            <div class="cfg-tabs" id="cfg-tab-bar" role="tablist" aria-label="Config sections">
              ${_TABS.map(t => `<button class="cfg-tab${t.id === _activeTab ? ' is-active' : ''}" type="button" role="tab" aria-selected="${t.id === _activeTab ? 'true' : 'false'}" aria-controls="cfg-tab-${t.id}" data-tab="${t.id}">${_esc(t.label)}</button>`).join('')}
            </div>
            <label class="cfg-search-wrap" for="cfg-search">
              <span class="cfg-search-icon" aria-hidden="true">${icons.search()}</span>
              <input class="cfg-search-input" id="cfg-search" type="search" placeholder="Search keys & values…" value="${_esc(_searchText)}" autocomplete="off">
            </label>
          </div>
          ${_TABS.map(t => `<div id="cfg-tab-${t.id}" class="tab-panel" role="tabpanel" style="${t.id === _activeTab ? '' : 'display:none'}"></div>`).join('')}
        </div>

        <!-- YAML view -->
        <div id="cfg-yaml-view" style="display:none">
          <div class="cfg-yaml-shell">
            <textarea id="cfg-yaml-area" class="input cfg-yaml-area" spellcheck="false"></textarea>
          </div>
        </div>

        <!-- Sticky save bar (shown only when dirty) -->
        <div id="cfg-stickybar" class="cfg-stickybar" hidden aria-live="polite">
          <div class="cfg-stickybar__row">
            <span class="cfg-stickybar__pulse" aria-hidden="true"></span>
            <span class="cfg-stickybar__count"><strong id="cfg-stickybar-count">0</strong> changes pending</span>
            <span class="cfg-stickybar__sep" aria-hidden="true">·</span>
            <button class="cfg-stickybar__diff-toggle" id="cfg-stickybar-toggle" type="button" aria-expanded="false" aria-controls="cfg-stickybar-diff">
              <span>View diff</span>
              <span class="cfg-stickybar__chevron" aria-hidden="true">${_CHEVRON_SVG}</span>
            </button>
            <span class="cfg-stickybar__spacer"></span>
            <button class="cfg-btn cfg-btn--ghost cfg-stickybar__btn" id="cfg-stickybar-discard" type="button">Discard</button>
            <button class="cfg-btn cfg-btn--primary cfg-stickybar__btn" id="cfg-stickybar-save" type="button">${icons.check()}<span>Save</span></button>
          </div>
          <div class="cfg-stickybar__diff" id="cfg-stickybar-diff" hidden></div>
        </div>
      </div>`;

    // mode buttons
    _el.querySelectorAll('[data-cfg-mode]').forEach(btn => {
      btn.addEventListener('click', () => _setMode(btn.dataset.cfgMode));
    });

    // tab buttons
    _el.querySelectorAll('#cfg-tab-bar .cfg-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        _activeTab = btn.dataset.tab;
        _el.querySelectorAll('.cfg-tab').forEach(b => {
          const active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        _el.querySelectorAll('.tab-panel').forEach(p => { p.style.display = 'none'; });
        const panel = _el.querySelector('#cfg-tab-' + _activeTab);
        if (panel) panel.style.display = '';
      });
    });

    _el.querySelector('#cfg-reload').addEventListener('click', () => {
      _dirty = {};
      _invalidJson = {};
      _jsonDrafts = {};
      _yamlDraft = '';
      _yamlDirty = false;
      _loadData();
    });
    _el.querySelector('#cfg-guided-setup')?.addEventListener('click', () => Router.navigate('/setup'));
    _el.querySelector('#cfg-save').addEventListener('click', _save);
    _el.querySelector('#cfg-search').addEventListener('input', (e) => {
      _searchText = e.target.value.toLowerCase();
      _renderFormTabs();
    });
    _bindYamlDraftTracking();

    // sticky save bar wiring
    _el.querySelector('#cfg-stickybar-save').addEventListener('click', _save);
    _el.querySelector('#cfg-stickybar-discard').addEventListener('click', () => {
      if (Object.keys(_dirty).length === 0 && !_yamlDirty) return;
      _dirty = {};
      _invalidJson = {};
      _jsonDrafts = {};
      _yamlDraft = '';
      _yamlDirty = false;
      _diffOpen = false;
      _loadData();
    });
    _el.querySelector('#cfg-stickybar-toggle').addEventListener('click', () => {
      _diffOpen = !_diffOpen;
      _renderStickybar();
    });

    // global tooltip dismissers
    document.addEventListener('click', _onDocClickForTooltip, true);
    document.addEventListener('keydown', _onDocKeyForTooltip, true);
    _unsubs.push(() => document.removeEventListener('click', _onDocClickForTooltip, true));
    _unsubs.push(() => document.removeEventListener('keydown', _onDocKeyForTooltip, true));

    _setMode(_mode);
    _loadData();
  }

  function destroy() {
    _hideTooltip();
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    _configData = {};
    _yamlText = '';
    _yamlDraft = '';
    _yamlDirty = false;
    _dirty = {};
    _invalidJson = {};
    _jsonDrafts = {};
    _mode = 'form';
    _activeTab = 'core';
    _searchText = '';
    _diffOpen = false;
    _el = null;
    _rpc = null;
  }

  // ---- data loading ----------------------------------------------------

  async function _loadData() {
    const rpc = _rpc;
    if (!_el || !rpc) return;
    await rpc.waitForConnection();
    if (!_el || _rpc !== rpc) return;
    rpc.call('config.get').then(data => {
      if (!_el || _rpc !== rpc) return;
      _configData = data || {};
      _yamlText = _objToYaml(_configData);
      if (!_yamlDirty) _yamlDraft = _yamlText;
      _invalidJson = {};
      _jsonDrafts = {};
      _renderFormTabs();
      _renderYaml();
      _renderStickybar();
    }).catch(err => UI.toast('Failed to load config: ' + err.message, 'err'));
  }

  // ---- mode toggle -----------------------------------------------------

  function _setMode(m) {
    _mode = m;
    if (!_el) return;
    // sync yaml textarea when switching to yaml
    if (m === 'yaml') {
      _el.querySelector('#cfg-yaml-area').value = _yamlDirty ? _yamlDraft : _yamlText;
    }
    _el.querySelector('#cfg-form-view').style.display = m === 'form' ? '' : 'none';
    _el.querySelector('#cfg-yaml-view').style.display = m === 'yaml' ? '' : 'none';
    _el.querySelectorAll('[data-cfg-mode]').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.cfgMode === m);
    });
    _renderStickybar();
  }

  function _bindYamlDraftTracking() {
    const area = _el && _el.querySelector('#cfg-yaml-area');
    if (!area) return;
    area.addEventListener('input', (e) => {
      _yamlDraft = e.target.value;
      _yamlDirty = _yamlDraft !== _yamlText;
      _renderStickybar();
    });
  }

  // ---- form rendering --------------------------------------------------

  function _renderFormTabs() {
    if (!_el) return;
    _hideTooltip();
    _TABS.forEach(tab => {
      const panel = _el.querySelector('#cfg-tab-' + tab.id);
      if (!panel) return;
      const entries = _entriesForTab(tab);
      if (entries.length === 0) {
        panel.innerHTML = '<div class="cfg-empty-state">No matching fields</div>';
        return;
      }
      panel.innerHTML = _groupsHtml(entries);

      panel.querySelectorAll('[data-cfg-key]').forEach(input => {
        input.addEventListener('change', (e) => _onFieldChange(e.target));
        input.addEventListener('input', (e) => _onFieldChange(e.target));
      });
      panel.querySelectorAll('[data-cfg-show]').forEach(btn => {
        btn.addEventListener('click', () => {
          const key = btn.dataset.cfgShow;
          const inp = panel.querySelector(`[data-cfg-key="${CSS.escape(key)}"]`);
          if (!inp) return;
          inp.type = inp.type === 'password' ? 'text' : 'password';
          btn.textContent = inp.type === 'password' ? 'Show' : 'Hide';
        });
      });
      panel.querySelectorAll('[data-cfg-help]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          _toggleTooltip(btn);
        });
        btn.addEventListener('focus', () => _showTooltip(btn));
        btn.addEventListener('blur', () => {
          // blur fires before document click handler runs in some browsers; defer
          setTimeout(() => {
            if (_activeTooltip && _activeTooltip.anchor === btn && document.activeElement !== btn) {
              _hideTooltip();
            }
          }, 0);
        });
        btn.addEventListener('mouseenter', () => _showTooltip(btn));
        btn.addEventListener('mouseleave', () => {
          // small delay so the user can move into the tooltip if needed
          setTimeout(() => {
            if (_activeTooltip && _activeTooltip.anchor === btn && !_activeTooltip.locked) {
              _hideTooltip();
            }
          }, 80);
        });
      });
    });
    _renderStickybar();
  }

  function _entriesForTab(tab) {
    return Object.entries(_configData).filter(([k, v]) => {
      const lk = k.toLowerCase();
      const matchesTab = tab.prefixes.some(p => lk.startsWith(p + '.') || lk === p || lk.startsWith(p + '_'));
      const matchesSearch = !_searchText || lk.includes(_searchText) || _searchBlob(v).includes(_searchText);
      return matchesTab && matchesSearch;
    });
  }

  function _groupsHtml(entries) {
    return _groupEntries(entries).map(group => {
      const fieldCount = group.entries.length;
      return `
        <section class="cfg-settings-group" aria-label="${_esc(group.title)}">
          <header class="cfg-settings-group-header">
            <div>
              <h3 class="cfg-settings-group-title">${_esc(group.title)}</h3>
              <div class="cfg-settings-group-meta">${fieldCount} ${fieldCount === 1 ? 'field' : 'fields'}</div>
            </div>
          </header>
          <div class="cfg-settings-fields">
            ${group.entries.map(([k, v]) => _fieldHtml(k, v)).join('')}
          </div>
        </section>`;
    }).join('');
  }

  function _groupEntries(entries) {
    const groups = new Map();
    entries.forEach(([k, v]) => {
      const id = _groupIdForKey(k, v);
      if (!groups.has(id)) groups.set(id, { id, title: _groupTitle(id), entries: [] });
      groups.get(id).entries.push([k, v]);
    });
    return Array.from(groups.values());
  }

  function _groupIdForKey(k, v) {
    if (k.includes('.')) return k.split('.')[0];
    if (v && typeof v === 'object') return k;
    return 'general';
  }

  function _groupTitle(id) {
    if (id === 'general') return 'General';
    return id.replace(/[_-]/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
  }

  function _fieldHtml(k, v) {
    const isSensitive = /key|token|secret|password|api_key/i.test(k);
    const isDirty = k in _dirty;
    const isInvalid = k in _invalidJson;
    const isObject = typeof v === 'object' && v !== null;
    const isLongKey = k.length > 24;
    const ek = _esc(k);
    const curVal = isDirty ? _dirty[k].new : v;
    const inputId = `cfg-input-${_safeId(k)}`;

    let inputHtml;
    if (typeof v === 'boolean') {
      inputHtml = `<label class="cfg-switch">
        <input id="${inputId}" type="checkbox" data-cfg-key="${ek}" data-cfg-type="boolean"${curVal ? ' checked' : ''} aria-label="${ek}">
        <span class="cfg-switch-track" aria-hidden="true"><span class="cfg-switch-thumb"></span></span>
        <span class="cfg-switch-text">${curVal ? 'Enabled' : 'Disabled'}</span>
      </label>`;
    } else if (typeof v === 'number') {
      inputHtml = `<input id="${inputId}" class="input cfg-input-number" type="number" data-cfg-key="${ek}" data-cfg-type="number" value="${_esc(String(curVal))}">`;
    } else if (isObject) {
      const jsonStr = k in _jsonDrafts ? _jsonDrafts[k] : JSON.stringify(curVal, null, 2);
      const lines = jsonStr.split('\n').length;
      const openAttr = isDirty || isInvalid ? ' open' : '';
      inputHtml = `<details class="cfg-object-field"${openAttr}>
        <summary>
          <span class="cfg-object-summary">${_esc(_objectSummary(curVal))}</span>
          <span class="cfg-object-action">Edit</span>
        </summary>
        <textarea id="${inputId}" class="input cfg-input-json" data-cfg-key="${ek}" data-cfg-type="json" rows="${Math.min(Math.max(lines + 1, 4), 12)}" aria-describedby="${inputId}-error">${_esc(jsonStr)}</textarea>
        <div id="${inputId}-error" class="cfg-json-error${isInvalid ? '' : ' hidden'}">Invalid JSON</div>
      </details>`;
    } else {
      const type = isSensitive ? 'password' : 'text';
      const showBtn = isSensitive
        ? `<button class="btn btn--sm" data-cfg-show="${ek}" type="button">Show</button>`
        : '';
      inputHtml = `<div class="cfg-input-row">
        <input id="${inputId}" class="input cfg-input-text" type="${type}" data-cfg-key="${ek}" data-cfg-type="string" value="${_esc(String(curVal ?? ''))}">
        ${showBtn}
      </div>`;
    }

    const fieldClasses = [
      'config-field',
      isObject ? 'config-field--object' : '',
      isDirty ? 'field-dirty' : '',
      isInvalid ? 'config-field--invalid' : '',
      isLongKey ? 'config-field--stacked' : '',
    ].filter(Boolean).join(' ');
    const helpBtn = `<button type="button" class="cfg-help-btn" data-cfg-help="${ek}" aria-label="Help for ${ek}" tabindex="0">${_HELP_ICON_SVG}</button>`;
    return `
      <div class="${fieldClasses}">
        <div class="config-field__label-row">
          <label class="form-label" for="${inputId}">${ek}</label>
          ${helpBtn}
        </div>
        ${inputHtml}
      </div>`;
  }

  function _onFieldChange(target) {
    const key = target.dataset.cfgKey;
    const type = target.dataset.cfgType;
    let newVal;
    if (type === 'boolean') {
      newVal = target.checked;
      _updateSwitchText(target, newVal);
    } else if (type === 'number') newVal = Number(target.value);
    else if (type === 'json') {
      _jsonDrafts[key] = target.value;
      try {
        newVal = JSON.parse(target.value);
        _setJsonInvalid(target, false);
      } catch {
        _setJsonInvalid(target, true);
        _renderStickybar();
        return;
      }
    } else {
      newVal = target.value;
    }
    const oldVal = _configData[key];
    if (newVal === oldVal || JSON.stringify(newVal) === JSON.stringify(oldVal)) {
      delete _dirty[key];
      if (type === 'json') delete _jsonDrafts[key];
    } else {
      _dirty[key] = { old: oldVal, new: newVal };
    }
    _syncDirtyClass(target, key);
    _refreshObjectSummary(key);
    _renderStickybar();
  }

  function _refreshObjectSummary(key) {
    if (!_el) return;
    const det = _el.querySelector(`details.cfg-object-field [data-cfg-key="${CSS.escape(key)}"]`);
    if (!det) return;
    const summary = det.closest('details')?.querySelector('.cfg-object-summary');
    if (!summary) return;
    const cur = key in _dirty ? _dirty[key].new : _configData[key];
    summary.textContent = _objectSummary(cur);
  }

  function _setJsonInvalid(target, invalid) {
    const key = target.dataset.cfgKey;
    const field = target.closest('.config-field');
    const error = field && field.querySelector('.cfg-json-error');
    const details = target.closest('details');
    if (invalid) {
      _invalidJson[key] = true;
      if (details) details.open = true;
    } else {
      delete _invalidJson[key];
    }
    if (field) field.classList.toggle('config-field--invalid', invalid);
    if (error) error.classList.toggle('hidden', !invalid);
  }

  function _syncDirtyClass(target, key) {
    const field = target.closest('.config-field');
    if (field) field.classList.toggle('field-dirty', key in _dirty);
  }

  function _updateSwitchText(target, enabled) {
    const label = target.closest('.cfg-switch');
    const text = label && label.querySelector('.cfg-switch-text');
    if (text) text.textContent = enabled ? 'Enabled' : 'Disabled';
  }

  // ---- sticky save bar -------------------------------------------------

  function _renderStickybar() {
    if (!_el) return;
    const bar = _el.querySelector('#cfg-stickybar');
    if (!bar) return;
    const keys = Object.keys(_dirty);
    const yamlDirtyVisible = _mode === 'yaml' && _yamlDirty;
    if (keys.length === 0 && !yamlDirtyVisible) {
      bar.hidden = true;
      _diffOpen = false;
      return;
    }
    bar.hidden = false;
    _el.querySelector('#cfg-stickybar-count').textContent = String(yamlDirtyVisible ? 1 : keys.length);
    const toggle = _el.querySelector('#cfg-stickybar-toggle');
    toggle.setAttribute('aria-expanded', _diffOpen ? 'true' : 'false');
    toggle.classList.toggle('is-open', _diffOpen);
    const diff = _el.querySelector('#cfg-stickybar-diff');
    if (_diffOpen) {
      diff.hidden = false;
      diff.innerHTML = yamlDirtyVisible ? `
        <div class="cfg-diff-row">
          <span class="cfg-diff-key">YAML</span>
          <span class="cfg-diff-old">loaded config</span>
          <span class="cfg-diff-arrow">-&gt;</span>
          <span class="cfg-diff-new">unsaved draft</span>
        </div>` : keys.map(k => {
        const { old: oldV, new: newV } = _dirty[k];
        return `<div class="cfg-diff-row">
          <span class="cfg-diff-key">${_esc(k)}</span>
          <span class="cfg-diff-old">${_esc(_summariseDiffValue(oldV))}</span>
          <span class="cfg-diff-arrow">-&gt;</span>
          <span class="cfg-diff-new">${_esc(_summariseDiffValue(newV))}</span>
        </div>`;
      }).join('');
    } else {
      diff.hidden = true;
      diff.innerHTML = '';
    }
  }

  function _summariseDiffValue(v) {
    const s = JSON.stringify(v);
    if (s === undefined) return String(v);
    return s.length > 120 ? s.slice(0, 117) + '…' : s;
  }

  // ---- yaml rendering -------------------------------------------------

  function _renderYaml() {
    const area = _el && _el.querySelector('#cfg-yaml-area');
    if (area && _mode === 'yaml') area.value = _yamlDirty ? _yamlDraft : _yamlText;
  }

  // ---- save -----------------------------------------------------------

  function _save() {
    if (_mode === 'yaml') {
      const text = _el.querySelector('#cfg-yaml-area').value;
      _rpc.call('config.apply', { config_yaml: text })
        .then(res => { UI.toast(res && res.restartRequired ? 'Config applied. Gateway restart required for the change to take effect.' : 'Config applied', res && res.restartRequired ? 'info' : 'ok'); _dirty = {}; _invalidJson = {}; _jsonDrafts = {}; _yamlDirty = false; _yamlDraft = ''; _loadData(); })
        .catch(err => UI.toast('Apply failed: ' + err.message, 'err'));
    } else {
      if (Object.keys(_invalidJson).length > 0) {
        UI.toast('Fix invalid JSON before saving', 'err');
        return;
      }
      const patches = Object.fromEntries(Object.entries(_dirty).map(([k, v]) => [k, v.new]));
      if (Object.keys(patches).length === 0) { UI.toast('No changes to save', 'info'); return; }
      _rpc.call('config.patch', { patches })
        .then(res => { UI.toast(res && res.restartRequired ? 'Config saved. Gateway restart required for the change to take effect.' : 'Config saved', res && res.restartRequired ? 'info' : 'ok'); _dirty = {}; _invalidJson = {}; _jsonDrafts = {}; _loadData(); })
        .catch(err => UI.toast('Save failed: ' + err.message, 'err'));
    }
  }

  // ---- tooltips --------------------------------------------------------

  function _ensureTooltipNode() {
    let tip = document.getElementById('cfg-tooltip');
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'cfg-tooltip';
      tip.className = 'cfg-tooltip';
      tip.setAttribute('role', 'tooltip');
      tip.hidden = true;
      tip.innerHTML = '<div class="cfg-tooltip__body"></div><span class="cfg-tooltip__arrow" aria-hidden="true"></span>';
      document.body.appendChild(tip);
    }
    return tip;
  }

  function _showTooltip(anchor) {
    if (!anchor) return;
    const key = anchor.dataset.cfgHelp;
    const tip = _ensureTooltipNode();
    tip.querySelector('.cfg-tooltip__body').textContent = _helpFor(key);
    tip.hidden = false;
    _activeTooltip = { anchor, key, locked: false };
    _positionTooltip(tip, anchor);
  }

  function _toggleTooltip(anchor) {
    if (_activeTooltip && _activeTooltip.anchor === anchor) {
      _hideTooltip();
      return;
    }
    _showTooltip(anchor);
    if (_activeTooltip) _activeTooltip.locked = true;
  }

  function _hideTooltip() {
    const tip = document.getElementById('cfg-tooltip');
    if (tip) tip.hidden = true;
    _activeTooltip = null;
  }

  function _positionTooltip(tip, anchor) {
    const rect = anchor.getBoundingClientRect();
    // Use viewport coords; tooltip is position: fixed.
    const tipRect = tip.getBoundingClientRect();
    const margin = 8;
    let left = rect.left + rect.width / 2 - tipRect.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin));
    let top = rect.bottom + 8;
    let placement = 'bottom';
    if (top + tipRect.height + margin > window.innerHeight) {
      top = rect.top - tipRect.height - 8;
      placement = 'top';
    }
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;
    tip.dataset.placement = placement;
    // arrow position
    const arrow = tip.querySelector('.cfg-tooltip__arrow');
    if (arrow) {
      const cx = rect.left + rect.width / 2 - left;
      arrow.style.left = `${Math.max(12, Math.min(cx, tipRect.width - 12))}px`;
    }
  }

  function _onDocClickForTooltip(e) {
    if (!_activeTooltip) return;
    const tip = document.getElementById('cfg-tooltip');
    if (tip && tip.contains(e.target)) return;
    if (_activeTooltip.anchor && _activeTooltip.anchor.contains(e.target)) return;
    _hideTooltip();
  }

  function _onDocKeyForTooltip(e) {
    if (e.key === 'Escape' && _activeTooltip) {
      _hideTooltip();
    }
  }

  // ---- helpers --------------------------------------------------------

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _safeId(s) {
    return String(s).replace(/[^a-zA-Z0-9_-]+/g, '-');
  }

  const _SECRET_KEY_RE = /token|key|secret|password/i;
  const _STR_TRUNC = 40;

  function _formatPreviewValue(key, value) {
    if (_SECRET_KEY_RE.test(key)) return '"***"';
    if (value === null) return 'null';
    if (value === undefined) return 'undefined';
    if (typeof value === 'boolean' || typeof value === 'number') return String(value);
    if (typeof value === 'string') {
      const trimmed = value.length > _STR_TRUNC ? value.slice(0, _STR_TRUNC - 1) + '…' : value;
      return JSON.stringify(trimmed);
    }
    if (Array.isArray(value)) return `[${value.length}]`;
    if (typeof value === 'object') return `{${Object.keys(value).length}}`;
    return JSON.stringify(value);
  }

  function _objectSummary(value) {
    if (Array.isArray(value)) {
      const len = value.length;
      if (len === 0) return 'JSON · empty list';
      const preview = value.slice(0, 2).map(v => _formatPreviewValue('item', v)).join(', ');
      const more = len > 2 ? ', …' : '';
      return `JSON · ${len} ${len === 1 ? 'item' : 'items'} · [${preview}${more}]`;
    }
    if (value && typeof value === 'object') {
      const keys = Object.keys(value);
      if (keys.length === 0) return 'JSON · empty object';
      const previewKeys = keys.slice(0, 2);
      const parts = previewKeys.map(k => `${k}: ${_formatPreviewValue(k, value[k])}`);
      const more = keys.length > previewKeys.length ? ', …' : '';
      return `JSON · ${keys.length} ${keys.length === 1 ? 'key' : 'keys'} · {${parts.join(', ')}${more}}`;
    }
    return 'JSON · value';
  }

  function _searchBlob(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') {
      try { return JSON.stringify(value).toLowerCase(); }
      catch { return ''; }
    }
    return String(value).toLowerCase();
  }

  /** Minimal object-to-YAML serialiser (no dependencies). */
  function _objToYaml(obj, indent = 0) {
    const pad = '  '.repeat(indent);
    if (obj === null || obj === undefined) return 'null';
    if (typeof obj === 'boolean') return String(obj);
    if (typeof obj === 'number') return String(obj);
    if (typeof obj === 'string') {
      if (/[\n:#\[\]{}&*!|>'"%@`]/.test(obj) || obj.trim() !== obj) {
        return JSON.stringify(obj);
      }
      return obj;
    }
    if (Array.isArray(obj)) {
      if (obj.length === 0) return '[]';
      return '\n' + obj.map(item => pad + '- ' + _objToYaml(item, indent + 1)).join('\n');
    }
    if (typeof obj === 'object') {
      const keys = Object.keys(obj);
      if (keys.length === 0) return '{}';
      return '\n' + keys.map(k => {
        const val = obj[k];
        const rendered = _objToYaml(val, indent + 1);
        const inline = typeof val !== 'object' || val === null;
        return pad + k + ': ' + (inline ? rendered : rendered.trimStart());
      }).join('\n');
    }
    return String(obj);
  }

  return { render, destroy };
})();

window.ConfigView = ConfigView;
