/** OpenSquilla Web UI - Sandbox control view. */

const SandboxView = (() => {
  let _el = null;
  let _rpc = null;
  let _generation = 0;
  let _pendingApprovalCount = 0;
  let _lastData = null;

  const _RUN_MODES = [
    [
      'standard',
      'Standard-Sandbox',
      'Sandboxed execution with managed network allowlist and normal safety prompts.',
    ],
    [
      'trusted',
      'Trusted-Sandbox',
      'Sandbox stays active, with fewer prompts for trusted workspace operations.',
    ],
    [
      'full',
      'Full Host Access',
      'Host execution without sandbox mounts, domain grants, or per-command sandbox limits.',
    ],
  ];

  function render(el) {
    _generation += 1;
    _el = el;
    _rpc = App.getRpc();
    _lastData = null;
    _el.innerHTML = `
      <div class="sandbox-stage">
        <header class="sandbox-stage__header">
          <div class="sandbox-stage__title-block">
            <span class="sandbox-stage__eyebrow">Control / Sandbox</span>
            <h2 class="sandbox-stage__title">Sandbox</h2>
            <p class="sandbox-stage__subtitle" id="sandbox-summary">Checking sandbox settings</p>
          </div>
          <button class="btn btn--ghost" id="sandbox-refresh" title="Refresh sandbox settings">
            ${icons.refresh()}<span>Refresh</span>
          </button>
        </header>

        <div class="sandbox-notice" id="sandbox-notice" hidden></div>

        <section class="sandbox-panel" aria-labelledby="sandbox-run-mode-title">
          <div class="sandbox-panel__head">
            <div>
              <span class="sandbox-panel__eyebrow">Execution</span>
              <h3 class="sandbox-panel__title" id="sandbox-run-mode-title">Run Mode</h3>
            </div>
            <span class="sandbox-panel__meta" id="sandbox-session-label">Session</span>
          </div>
          <div id="sandbox-run-mode">${_renderEmpty('Loading run mode')}</div>
          <div class="sandbox-approval-activity" id="sandbox-approval-activity" hidden>
            <span>Approvals pending</span>
            <strong id="sandbox-approval-count">0</strong>
          </div>
        </section>

        <div id="sandbox-controls">${_renderEmpty('Loading sandbox controls')}</div>
      </div>`;

    _el.querySelector('#sandbox-refresh')?.addEventListener('click', _load);
    _el.addEventListener('submit', _onSubmit);
    _el.addEventListener('click', _onClick);
    window.addEventListener('opensquilla:approvals-pending', _onApprovalsPending);
    _load();
  }

  function destroy() {
    _generation += 1;
    if (_el) {
      _el.removeEventListener('submit', _onSubmit);
      _el.removeEventListener('click', _onClick);
    }
    window.removeEventListener('opensquilla:approvals-pending', _onApprovalsPending);
    _el = null;
    _rpc = null;
    _lastData = null;
    _pendingApprovalCount = 0;
  }

  async function _load() {
    const root = _el;
    const rpc = _rpc;
    const generation = _generation;
    if (!root || !rpc) return;

    _setLoading(root);
    try {
      await _withTimeout(rpc.waitForConnection(), 2500);
      const sessionKey = _activeSessionKey();
      const status = await rpc.call('sandbox.status', {});
      let runContext = null;

      if (sessionKey) {
        try {
          runContext = await rpc.call('sandbox.run_context.get', { sessionKey });
        } catch {}
      }

      if (!_isCurrent(root, rpc, generation)) return;
      _renderLoaded(root, { status, runContext, sessionKey });
    } catch (err) {
      if (!_isCurrent(root, rpc, generation)) return;
      _renderError(root, err);
    }
  }

  function _setLoading(root) {
    _setNotice(root, '', '');
    const summary = root.querySelector('#sandbox-summary');
    if (summary) summary.textContent = 'Checking sandbox settings';
    const runMode = root.querySelector('#sandbox-run-mode');
    if (runMode) runMode.innerHTML = _renderEmpty('Loading run mode');
    const controls = root.querySelector('#sandbox-controls');
    if (controls) controls.innerHTML = _renderEmpty('Loading sandbox controls');
    _updateApprovalActivity(_pendingApprovalCount);
  }

  function _renderLoaded(root, data) {
    const status = data.status || {};
    const runContext = _normalizeRunContext(status, data.runContext || {});
    _lastData = { ...data, runContext };

    const summary = root.querySelector('#sandbox-summary');
    if (summary) summary.textContent = _summary(runContext, data.sessionKey);

    const sessionLabel = root.querySelector('#sandbox-session-label');
    if (sessionLabel) sessionLabel.textContent = data.sessionKey ? 'Current session' : 'No active session';

    const runMode = root.querySelector('#sandbox-run-mode');
    if (runMode) runMode.innerHTML = _renderRunMode(runContext, data.sessionKey);

    const controls = root.querySelector('#sandbox-controls');
    if (controls) {
      controls.innerHTML = _isFullHostAccess(status, runContext)
        ? _renderFullHostAccessEmpty(runContext)
        : _renderSandboxControls(status, runContext, data.sessionKey);
    }
    _updateApprovalActivity(_pendingApprovalCount);
  }

  function _renderError(root, err) {
    const message = err?.message || String(err);
    const summary = root.querySelector('#sandbox-summary');
    if (summary) summary.textContent = 'Sandbox settings unavailable';
    const runMode = root.querySelector('#sandbox-run-mode');
    if (runMode) runMode.innerHTML = _renderEmpty('Connect to the gateway to load run mode');
    const controls = root.querySelector('#sandbox-controls');
    if (controls) controls.innerHTML = _renderEmpty(message);
  }

  function _renderRunMode(runContext, sessionKey) {
    const active = _normalizeRunMode(runContext.runMode);
    const disabled = sessionKey ? '' : 'disabled';
    return `
      <div class="sandbox-run-mode-grid">
        ${_RUN_MODES.map(([value, label, help]) => `
          <button
            class="sandbox-run-mode-option ${active === value ? 'is-active' : ''}"
            type="button"
            data-sandbox-action="run-mode-set"
            data-run-mode="${_esc(value)}"
            data-help="${_esc(help)}"
            aria-pressed="${active === value ? 'true' : 'false'}"
            ${disabled}
          >
            <span>${_esc(label)}</span>
          </button>`).join('')}
      </div>
      ${sessionKey ? '' : _renderEmpty('Open a chat session before changing run mode')}`;
  }

  function _renderSandboxControls(status, runContext, sessionKey) {
    return `
      <div class="sandbox-grid">
        <section class="sandbox-panel sandbox-panel--wide" aria-labelledby="sandbox-workspace-title">
          <div class="sandbox-panel__head">
            <div>
              <span class="sandbox-panel__eyebrow">Scope</span>
              <h3 class="sandbox-panel__title" id="sandbox-workspace-title">Workspace & Mounts</h3>
            </div>
          </div>
          <div id="sandbox-workspace">${_renderWorkspace(runContext, sessionKey)}</div>
        </section>

        <section class="sandbox-panel" aria-labelledby="sandbox-network-title">
          <div class="sandbox-panel__head">
            <div>
              <span class="sandbox-panel__eyebrow">Allowlist</span>
              <h3 class="sandbox-panel__title" id="sandbox-network-title">Managed Network</h3>
            </div>
          </div>
          <div id="sandbox-network">${_renderNetwork(status, runContext, sessionKey)}</div>
        </section>
      </div>`;
  }

  function _renderFullHostAccessEmpty(runContext) {
    const label = runContext.runModeLabel || 'Full Host Access';
    return `
      <section class="sandbox-panel sandbox-full-host" aria-label="Full Host Access">
        <div class="sandbox-full-host__inner">
          <strong>${_esc(label)}</strong>
          <span>No sandbox mounts, domains, or bundles are applied in this mode.</span>
        </div>
      </section>`;
  }

  function _renderWorkspace(runContext, sessionKey) {
    if (!sessionKey) {
      return _renderEmpty('Open a chat session to edit workspace and mounts');
    }
    const workspaceValue = runContext.workspace || '';
    const mounts = Array.isArray(runContext.mounts) ? runContext.mounts : [];
    return `
      <form class="sandbox-inline-form" data-sandbox-action="workspace-save">
        <label class="sandbox-field sandbox-field--span">
          <span>Workspace</span>
          <div class="sandbox-path-field">
            <input class="sandbox-input" name="workspace" autocomplete="off" value="${_esc(workspaceValue)}" placeholder="/path/to/workspace" />
            <button class="sandbox-path-btn" type="button" data-sandbox-action="workspace-browse" aria-label="Browse workspace directory">
              ${icons.search()}<span>Browse</span>
            </button>
          </div>
        </label>
        <button class="sandbox-icon-btn sandbox-icon-btn--primary" type="submit" title="Save workspace" aria-label="Save workspace">
          ${icons.check()}
        </button>
      </form>
      <div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Mounts</div>
        ${mounts.length ? `<div class="sandbox-list">${mounts.map(m => _renderMount(m, true)).join('')}</div>` : _renderEmpty('No extra mounts')}
      </div>
      <form class="sandbox-inline-form sandbox-inline-form--mount" data-sandbox-action="mount-add">
        <label class="sandbox-field sandbox-field--span">
          <span>Mount path</span>
          <div class="sandbox-path-field">
            <input class="sandbox-input" name="path" autocomplete="off" placeholder="/path/to/folder" />
            <button class="sandbox-path-btn" type="button" data-sandbox-action="mount-browse" aria-label="Browse mount directory">
              ${icons.search()}<span>Browse</span>
            </button>
          </div>
        </label>
        ${_select('access', [['ro', 'Read only'], ['rw', 'Read/write']], 'ro')}
        ${_select('scope', [['chat', 'This chat'], ['workspace', 'Workspace']], 'chat')}
        <button class="sandbox-icon-btn sandbox-icon-btn--primary" type="submit" title="Add mount" aria-label="Add mount">
          ${icons.plus()}
        </button>
      </form>`;
  }

  function _renderMount(mount, canRemove) {
    const path = mount.path || mount.source || mount.target || 'Unknown path';
    const access = mount.access || mount.mode || 'ro';
    const scope = mount.scope || '';
    const source = mount.source && mount.source !== path ? mount.source : (mount.created_by || mount.createdBy || '');
    return `<div class="sandbox-list__row sandbox-list__row--action">
      <span class="sandbox-list__main">${_esc(path)}</span>
      <span class="sandbox-chip">${_esc(access)}</span>
      ${canRemove ? `<button class="sandbox-icon-btn sandbox-icon-btn--danger" type="button" data-sandbox-action="mount-remove" data-path="${_esc(path)}" title="Remove mount" aria-label="Remove mount">${icons.trash()}</button>` : ''}
      ${scope || source ? `<span class="sandbox-list__sub">${_esc([scope, source].filter(Boolean).join(' / '))}</span>` : ''}
    </div>`;
  }

  function _renderNetwork(status, runContext, sessionKey) {
    const domains = Array.isArray(runContext.domains) ? runContext.domains : [];
    const bundles = Array.isArray(runContext.bundles) ? runContext.bundles : [];
    const catalog = _bundleCatalog(status);
    if (!sessionKey) {
      return _renderEmpty('Open a chat session to edit domains and bundles');
    }
    return `
      <div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Domains</div>
        ${domains.length ? `<div class="sandbox-list">${domains.map(d => _renderDomain(d, true)).join('')}</div>` : _renderEmpty('No custom domains')}
      </div>
      <form class="sandbox-inline-form" data-sandbox-action="domain-add">
        <label class="sandbox-field sandbox-field--span">
          <span>Domain</span>
          <input class="sandbox-input" name="domain" autocomplete="off" placeholder="pypi.org" />
        </label>
        ${_select('scope', [['chat', 'This chat'], ['workspace', 'Workspace']], 'chat')}
        <button class="sandbox-icon-btn sandbox-icon-btn--primary" type="submit" title="Add domain" aria-label="Add domain">
          ${icons.plus()}
        </button>
      </form>
      <div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Bundles</div>
        ${catalog.length ? `<div class="sandbox-list">${catalog.map(b => _renderBundleOption(b, bundles)).join('')}</div>` : _renderEmpty('No package bundle catalog')}
      </div>`;
  }

  function _renderDomain(domain, canRemove) {
    const value = domain.domain || domain.value || domain.pattern || 'Unknown domain';
    const access = domain.access || domain.scope || 'allow';
    return `<div class="sandbox-list__row sandbox-list__row--action">
      <span class="sandbox-list__main">${_esc(value)}</span>
      <span class="sandbox-chip">${_esc(access)}</span>
      ${canRemove ? `<button class="sandbox-icon-btn sandbox-icon-btn--danger" type="button" data-sandbox-action="domain-remove" data-domain="${_esc(value)}" title="Remove domain" aria-label="Remove domain">${icons.trash()}</button>` : ''}
    </div>`;
  }

  function _renderBundleOption(bundle, enabledBundles) {
    const id = bundle.bundle_id || bundle.bundleId || bundle.id || '';
    const enabled = enabledBundles.some(item => (item.bundle_id || item.bundleId || item.id) === id);
    const domains = Array.isArray(bundle.domains) ? bundle.domains.join(', ') : '';
    return `<div class="sandbox-list__row sandbox-list__row--action sandbox-list__row--bundle">
      <span class="sandbox-list__main">${_esc(id || 'Unknown bundle')}</span>
      <span class="sandbox-chip">${enabled ? 'On' : 'Off'}</span>
      <button class="sandbox-icon-btn ${enabled ? 'sandbox-icon-btn--danger' : 'sandbox-icon-btn--primary'}" type="button" data-sandbox-action="bundle-toggle" data-bundle-id="${_esc(id)}" data-enabled="${enabled ? '1' : '0'}" title="${enabled ? 'Disable bundle' : 'Enable bundle'}" aria-label="${enabled ? 'Disable bundle' : 'Enable bundle'}">
        ${enabled ? icons.x() : icons.plus()}
      </button>
      ${domains ? `<span class="sandbox-list__sub">${_esc(domains)}</span>` : ''}
    </div>`;
  }

  async function _onSubmit(event) {
    const form = event.target?.closest?.('form[data-sandbox-action]');
    if (!form || !_el?.contains(form)) return;
    event.preventDefault();
    const action = form.dataset.sandboxAction;
    const values = Object.fromEntries(new FormData(form).entries());
    if (action === 'workspace-save') {
      await _mutate('sandbox.workspace.set', { workspace: values.workspace });
    } else if (action === 'mount-add') {
      await _mutate('sandbox.mount.add', {
        path: values.path,
        access: values.access || 'ro',
        scope: values.scope || 'chat',
      });
      form.reset();
    } else if (action === 'domain-add') {
      await _mutate('sandbox.domain.add', {
        domain: values.domain,
        scope: values.scope || 'chat',
      });
      form.reset();
    }
  }

  async function _onClick(event) {
    const btn = event.target?.closest?.('button[data-sandbox-action]');
    if (!btn || !_el?.contains(btn)) return;
    const action = btn.dataset.sandboxAction;
    if (action === 'run-mode-set') {
      await _mutate('sandbox.run_context.set', { runMode: btn.dataset.runMode || 'standard' });
    } else if (action === 'workspace-browse') {
      await _browsePath('workspace');
    } else if (action === 'mount-browse') {
      await _browsePath('mount');
    } else if (action === 'mount-remove') {
      await _mutate('sandbox.mount.remove', { path: btn.dataset.path || '' });
    } else if (action === 'domain-remove') {
      await _mutate('sandbox.domain.remove', { domain: btn.dataset.domain || '' });
    } else if (action === 'bundle-toggle') {
      const method = btn.dataset.enabled === '1' ? 'sandbox.bundle.disable' : 'sandbox.bundle.enable';
      await _mutate(method, { bundleId: btn.dataset.bundleId || '' });
    }
  }

  async function _browsePath(kind) {
    const root = _el;
    const rpc = _rpc;
    const sessionKey = _lastData?.sessionKey || _activeSessionKey();
    if (!root || !rpc || !sessionKey) {
      _setNotice(root, 'Open a chat session before choosing directories.', 'warn');
      return;
    }
    const input = root.querySelector(kind === 'workspace' ? 'input[name="workspace"]' : 'input[name="path"]');
    const mountAccess = root.querySelector('form[data-sandbox-action="mount-add"] select[name="access"]')?.value || 'ro';
    try {
      _setNotice(root, 'Opening directory picker...', 'info');
      const result = await rpc.call('sandbox.path.pick', {
        sessionKey,
        kind,
        access: kind === 'mount' ? mountAccess : 'ro',
        initialPath: input?.value || _lastData?.runContext?.workspace || '',
      });
      if (input && result?.path) input.value = result.path;
      _setNotice(root, 'Directory selected. Review and save.', 'ok');
    } catch (err) {
      _setNotice(root, err?.message || String(err), 'warn');
      input?.focus?.();
    }
  }

  async function _mutate(method, payload) {
    const root = _el;
    const rpc = _rpc;
    const sessionKey = _lastData?.sessionKey || _activeSessionKey();
    if (!root || !rpc || !sessionKey) {
      _setNotice(root, 'Open a chat session before editing sandbox settings.', 'warn');
      return;
    }
    try {
      _setNotice(root, 'Saving sandbox settings...', 'info');
      const runContext = await rpc.call(method, { sessionKey, ...payload });
      if (!_lastData || root !== _el) return;
      _renderLoaded(root, { ..._lastData, runContext, sessionKey });
      _setNotice(root, 'Sandbox settings updated.', 'ok');
    } catch (err) {
      _setNotice(root, err?.message || String(err), 'err');
    }
  }

  function _onApprovalsPending(event) {
    const pending = Array.isArray(event?.detail?.pending) ? event.detail.pending : null;
    const detailCount = Number(event?.detail?.count);
    const count = Number.isFinite(detailCount) ? detailCount : (pending ? pending.length : 0);
    _pendingApprovalCount = Math.max(0, count);
    _updateApprovalActivity(_pendingApprovalCount);
  }

  function _updateApprovalActivity(count) {
    const root = _el;
    if (!root) return;
    const safeCount = Math.max(0, Number(count) || 0);
    const countEl = root.querySelector('#sandbox-approval-count');
    if (countEl) countEl.textContent = `${safeCount}`;
    const activityEl = root.querySelector('#sandbox-approval-activity');
    if (!activityEl) return;
    activityEl.hidden = safeCount <= 0;
    const activity = `
      <span>Approvals pending</span>
      <strong id="sandbox-approval-count">${safeCount}</strong>`;
    activityEl.innerHTML = activity;
  }

  function _setNotice(root, text, tone) {
    const notice = root?.querySelector?.('#sandbox-notice');
    if (!notice) return;
    const value = String(text || '').trim();
    notice.hidden = !value;
    notice.textContent = value;
    notice.className = `sandbox-notice ${tone ? 'sandbox-notice--' + tone : ''}`;
  }

  function _select(name, options, selected) {
    return `<label class="sandbox-field">
      <span>${_esc(_label(name))}</span>
      <select class="sandbox-select" name="${_esc(name)}">
        ${options.map(([value, label]) => `<option value="${_esc(value)}" ${value === selected ? 'selected' : ''}>${_esc(label)}</option>`).join('')}
      </select>
    </label>`;
  }

  function _renderEmpty(text) {
    return `<div class="sandbox-empty">${_esc(text)}</div>`;
  }

  function _bundleCatalog(status) {
    const catalog = status.bundle_catalog || status.bundleCatalog || [];
    return Array.isArray(catalog) ? catalog : [];
  }

  function _activeSessionKey() {
    try {
      return localStorage.getItem('opensquilla_active_session') || '';
    } catch {
      return '';
    }
  }

  function _normalizeRunContext(status, runContext) {
    return {
      ...runContext,
      runMode: runContext.runMode || status.run_mode || 'standard',
      runModeLabel: runContext.runModeLabel || status.run_mode_label || _runModeLabel(status.run_mode || 'standard'),
      mounts: Array.isArray(runContext.mounts) ? runContext.mounts : [],
      domains: Array.isArray(runContext.domains) ? runContext.domains : [],
      bundles: Array.isArray(runContext.bundles) ? runContext.bundles : [],
    };
  }

  function _isFullHostAccess(status, runContext) {
    return _normalizeRunMode(runContext.runMode || status.run_mode) === 'full';
  }

  function _summary(runContext, sessionKey) {
    const label = runContext.runModeLabel || _runModeLabel(runContext.runMode);
    return sessionKey ? `${label} for current chat` : `${label} from gateway default`;
  }

  function _normalizeRunMode(value) {
    const raw = String(value || '').toLowerCase().replace(/[_\s]+/g, '-');
    if (raw === 'trusted' || raw === 'trusted-sandbox') return 'trusted';
    if (raw === 'full' || raw === 'full-host-access') return 'full';
    return 'standard';
  }

  function _runModeLabel(value) {
    const mode = _normalizeRunMode(value);
    const found = _RUN_MODES.find(([candidate]) => candidate === mode);
    return found ? found[1] : 'Standard-Sandbox';
  }

  function _withTimeout(promise, timeoutMs) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Gateway connection timed out')), timeoutMs);
      Promise.resolve(promise).then(
        (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        (err) => {
          clearTimeout(timer);
          reject(err);
        },
      );
    });
  }

  function _isCurrent(root, rpc, generation) {
    return root === _el && rpc === _rpc && generation === _generation;
  }

  function _label(value) {
    return String(value || '')
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, ch => ch.toUpperCase());
  }

  function _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  return { render, destroy };
})();
