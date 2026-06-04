/** OpenSquilla Web UI - Sandbox control view. */

const SandboxView = (() => {
  let _el = null;
  let _rpc = null;
  let _generation = 0;
  let _pendingApprovalCount = 0;
  let _lastData = null;
  let _pathBrowserLoadIds = { workspace: 0, mount: 0 };

  const _PATH_BROWSER_KINDS = ['workspace', 'mount'];

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

        <section class="sandbox-panel sandbox-panel--run-mode" aria-labelledby="sandbox-run-mode-title">
          <div class="sandbox-panel__head">
            <div>
              <span class="sandbox-panel__eyebrow">Run Mode</span>
              <h3 class="sandbox-panel__title" id="sandbox-run-mode-title">Status</h3>
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
    _el.addEventListener('focusin', _onFocusIn);
    document.removeEventListener('keydown', _onDocumentKeydown);
    document.removeEventListener('click', _onDocumentClick, true);
    document.addEventListener('keydown', _onDocumentKeydown);
    document.addEventListener('click', _onDocumentClick, true);
    window.addEventListener('opensquilla:approvals-pending', _onApprovalsPending);
    _load();
  }

  function destroy() {
    _generation += 1;
    if (_el) {
      _el.removeEventListener('submit', _onSubmit);
      _el.removeEventListener('click', _onClick);
      _el.removeEventListener('focusin', _onFocusIn);
    }
    document.removeEventListener('keydown', _onDocumentKeydown);
    document.removeEventListener('click', _onDocumentClick, true);
    window.removeEventListener('opensquilla:approvals-pending', _onApprovalsPending);
    _el = null;
    _rpc = null;
    _lastData = null;
    _pendingApprovalCount = 0;
    _pathBrowserLoadIds = { workspace: 0, mount: 0 };
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
      let explanation = null;
      let runContext = null;

      try {
        explanation = await rpc.call('sandbox.explain', sessionKey ? { sessionKey } : {});
      } catch {}

      if (sessionKey) {
        try {
          runContext = await rpc.call('sandbox.run_context.get', { sessionKey });
        } catch {}
      }

      if (!_isCurrent(root, rpc, generation)) return;
      _renderLoaded(root, {
        status: explanation?.status || status,
        runContext: runContext || explanation?.runContext,
        sessionKey,
        explanation,
      });
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
    const openDetails = _captureOpenNetworkDetails(root);
    const status = data.status || {};
    const runContext = _normalizeRunContext(status, data.runContext || {});
    _lastData = { ...data, runContext };

    _renderExplanation(root, data.explanation);

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
      _restoreOpenNetworkDetails(controls, openDetails);
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

  function _renderExplanation(root, explanation) {
    const messages = Array.isArray(explanation?.messages) ? explanation.messages : [];
    const text = messages.map(item => item?.message).filter(Boolean).join(' ');
    if (!text) {
      _setNotice(root, '', '');
      return;
    }
    const hasBlocked = messages.some(item => String(item?.message || '').toLowerCase().includes('blocked'));
    _setNotice(root, text, hasBlocked ? 'warn' : 'ok');
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

        <section class="sandbox-panel" aria-labelledby="sandbox-rules-title">
          <div class="sandbox-panel__head">
            <div>
              <span class="sandbox-panel__eyebrow">Policy</span>
              <h3 class="sandbox-panel__title" id="sandbox-rules-title">Sandbox Rules</h3>
            </div>
          </div>
          ${_renderRules(status, runContext)}
        </section>
      </div>`;
  }

  function _renderRules(status, runContext) {
    const managedNetwork = status.managed_network || status.managedNetwork || 'blocked';
    const executionTarget = runContext.executionTarget || status.execution_target || status.executionTarget || 'sandbox';
    return `
      <div class="sandbox-rule-list">
        <div class="sandbox-rule-list__row">
          <span>Execution target</span>
          <strong>${_esc(executionTarget)}</strong>
        </div>
        <div class="sandbox-rule-list__row">
          <span>Run mode</span>
          <strong>${_esc(runContext.runModeLabel || _runModeLabel(runContext.runMode))}</strong>
        </div>
        <div class="sandbox-rule-list__row">
          <span>Managed network</span>
          <strong>${_esc(managedNetwork)}</strong>
        </div>
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
        <div class="sandbox-field sandbox-field--span">
          <span>Workspace</span>
          <div class="sandbox-path-field" data-path-kind="workspace">
            <input class="sandbox-input" name="workspace" autocomplete="off" value="${_esc(workspaceValue)}" placeholder="/path/to/workspace" aria-label="Workspace path" data-path-browser-kind="workspace" />
            <button class="sandbox-path-btn" type="button" data-sandbox-action="workspace-browse" aria-label="Browse workspace directory">
              ${icons.search()}<span>Browse</span>
            </button>
            <div class="sandbox-path-browser-slot" data-path-browser-kind="workspace"></div>
          </div>
        </div>
        <button class="sandbox-icon-btn sandbox-icon-btn--primary" type="submit" title="Save workspace" aria-label="Save workspace">
          ${icons.check()}
        </button>
      </form>
      <div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Mounts</div>
        ${mounts.length ? `<div class="sandbox-list">${mounts.map(m => _renderMount(m, true)).join('')}</div>` : _renderEmpty('No extra mounts')}
      </div>
      <form class="sandbox-inline-form sandbox-inline-form--mount" data-sandbox-action="mount-add">
        <div class="sandbox-field sandbox-field--span">
          <span>Mount path</span>
          <div class="sandbox-path-field" data-path-kind="mount">
            <input class="sandbox-input" name="path" autocomplete="off" placeholder="/path/to/folder" aria-label="Mount path" data-path-browser-kind="mount" />
            <button class="sandbox-path-btn" type="button" data-sandbox-action="mount-browse" aria-label="Browse mount directory">
              ${icons.search()}<span>Browse</span>
            </button>
            <div class="sandbox-path-browser-slot" data-path-browser-kind="mount"></div>
          </div>
        </div>
        ${_select('access', [['ro', 'Read only'], ['rw', 'Read/write']], 'ro')}
        ${_select('scope', [['chat', 'This chat'], ['workspace', 'This user']], 'chat')}
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
    const details = [
      scope ? _networkScopeLabel(scope) : '',
      source,
    ].filter(Boolean);
    return `<div class="sandbox-list__row sandbox-list__row--mount">
      <span class="sandbox-list__content">
        <span class="sandbox-list__main sandbox-list__main--path">${_esc(path)}</span>
        ${details.length ? `<span class="sandbox-list__sub">${_esc(details.join(' / '))}</span>` : ''}
      </span>
      <span class="sandbox-list__meta">
        <span class="sandbox-chip">${_esc(_mountAccessLabel(access))}</span>
        ${canRemove ? `<button class="sandbox-icon-btn sandbox-icon-btn--danger" type="button" data-sandbox-action="mount-remove" data-path="${_esc(path)}" data-scope="${_esc(scope || 'chat')}" title="Remove mount" aria-label="Remove mount">${icons.trash()}</button>` : ''}
      </span>
    </div>`;
  }

  function _mountAccessLabel(access) {
    return String(access || '').toLowerCase() === 'rw' ? 'Read/write' : 'Read only';
  }

  function _renderNetwork(status, runContext, sessionKey) {
    const domains = Array.isArray(runContext.domains) ? runContext.domains : [];
    const bundles = Array.isArray(runContext.bundles) ? runContext.bundles : [];
    const publicNetwork = Array.isArray(runContext.publicNetwork) ? runContext.publicNetwork : [];
    const catalog = _bundleCatalog(status);
    const defaultAllowlist = _defaultAllowlist(status);
    if (!sessionKey) {
      return _renderEmpty('Open a chat session to edit domains and bundles');
    }
    const { chatDomains, userDomains } = _partitionNetworkDomains(domains);
    const enabledBundleCount = catalog.reduce((count, bundle) => count + (_bundleState(bundle, bundles).enabled ? 1 : 0), 0);
    return `
      <div class="sandbox-network-stack">
        ${_renderNetworkDetails(
          'sandbox-network-summary--default',
          `Default Access · ${_defaultAllowlistDomainCount(defaultAllowlist)} domains`,
          _renderDefaultAllowlist(defaultAllowlist),
        )}
        ${_renderNetworkDetails(
          'sandbox-network-summary--bundles',
          `Bundles · ${enabledBundleCount} enabled`,
          _renderBundles(catalog, bundles),
        )}
        ${publicNetwork.length ? _renderNetworkSection(
          'sandbox-network-summary--public',
          `Normal public network · ${_publicNetworkScopeSummary(publicNetwork)}`,
          _renderPublicNetworkGrants(publicNetwork),
        ) : ''}
        ${_renderNetworkSection(
          'sandbox-network-summary--chat',
          `This chat · ${chatDomains.length} added`,
          chatDomains.length ? `<div class="sandbox-network-list">${chatDomains.map(d => _renderDomain(d, true)).join('')}</div>` : _renderNetworkEmpty('No domains added for this chat. Default public access is still active.'),
        )}
        ${_renderNetworkSection(
          'sandbox-network-summary--user',
          `This user · ${userDomains.length} custom`,
          userDomains.length ? `<div class="sandbox-network-list">${userDomains.map(d => _renderDomain(d, true)).join('')}</div>` : _renderNetworkEmpty('No domains added for this user. Default public access is still active.'),
        )}
      </div>
      <form class="sandbox-inline-form" data-sandbox-action="domain-add">
        <label class="sandbox-field sandbox-field--span">
          <span>Domain</span>
          <input class="sandbox-input" name="domain" autocomplete="off" placeholder="pypi.org" />
        </label>
        ${_select('scope', [['chat', 'This chat'], ['workspace', 'This user']], 'chat')}
        <button class="sandbox-icon-btn sandbox-icon-btn--primary" type="submit" title="Add domain" aria-label="Add domain">
          ${icons.plus()}
        </button>
      </form>`;
  }

  function _renderNetworkDetails(summaryClass, summaryText, body) {
    return `
      <details class="sandbox-network-group" data-details-key="${_esc(summaryClass)}">
        <summary class="sandbox-network-summary ${summaryClass}">${_esc(summaryText)}</summary>
        <div class="sandbox-network-body">${body}</div>
      </details>`;
  }

  function _captureOpenNetworkDetails(root) {
    const keys = new Set();
    root?.querySelectorAll?.('details.sandbox-network-group[data-details-key][open]').forEach(details => {
      if (details.dataset.detailsKey) keys.add(details.dataset.detailsKey);
    });
    return keys;
  }

  function _restoreOpenNetworkDetails(root, keys) {
    if (!keys?.size) return;
    root?.querySelectorAll?.('details.sandbox-network-group[data-details-key]').forEach(details => {
      if (keys.has(details.dataset.detailsKey)) details.open = true;
    });
  }

  function _renderNetworkSection(summaryClass, summaryText, body) {
    return `
      <section class="sandbox-network-group sandbox-network-group--section">
        <div class="sandbox-network-summary ${summaryClass}">${_esc(summaryText)}</div>
        <div class="sandbox-network-body">${body}</div>
      </section>`;
  }

  function _renderPublicNetworkGrants(publicNetwork) {
    return `<div class="sandbox-network-row sandbox-network-row--bundle">
      <div>
        <div class="sandbox-network-row__main">Normal public network</div>
        <div class="sandbox-network-row__sub">Blocked, private, and unsafe hosts stay blocked.</div>
      </div>
      <span class="sandbox-chip">${_esc(_publicNetworkScopeSummary(publicNetwork))}</span>
    </div>`;
  }

  function _publicNetworkScopeSummary(publicNetwork) {
    const active = new Set(publicNetwork.map(grant => _networkScopeKey(grant?.scope)));
    return [['chat', 'This chat'], ['workspace', 'This user']]
      .filter(([scope]) => active.has(_networkScopeKey(scope)))
      .map(([, label]) => label)
      .join(' / ') || 'Active';
  }

  function _renderBundles(catalog, enabledBundles) {
    if (!catalog.length) return _renderNetworkEmpty('No package bundle catalog');
    return `<div class="sandbox-network-bundle-grid">${catalog.map(b => _renderBundleOption(b, enabledBundles)).join('')}</div>`;
  }

  function _renderBundleOption(bundle, enabledBundles) {
    const id = bundle.bundle_id || bundle.bundleId || bundle.id || '';
    const { enabled } = _bundleState(bundle, enabledBundles);
    return `<button class="sandbox-network-bundle" type="button" data-sandbox-action="bundle-toggle" data-bundle-id="${_esc(id)}" data-enabled="${enabled ? '1' : '0'}" title="${enabled ? 'Disable bundle' : 'Enable bundle'}" aria-label="${enabled ? 'Disable bundle' : 'Enable bundle'}">
      <span class="sandbox-network-bundle__name">${_esc(id || 'Unknown bundle')}</span>
      <span class="sandbox-chip">${enabled ? 'On' : 'Off'}</span>
    </button>`;
  }

  function _bundleState(bundle, enabledBundles) {
    const matchingBundle = enabledBundles.find(item => (item.bundle_id || item.bundleId || item.id) === (bundle.bundle_id || bundle.bundleId || bundle.id));
    const source = matchingBundle?.source || '';
    const enabledByDefault = Boolean(bundle.enabled_by_default || bundle.enabledByDefault);
    return {
      enabled: source === 'disabled' ? false : (enabledByDefault || Boolean(matchingBundle)),
    };
  }

  function _renderDefaultAllowlist(defaultAllowlist) {
    if (!defaultAllowlist.length) return _renderNetworkEmpty('No default access entries');
    return `<div class="sandbox-network-list">
      ${defaultAllowlist.map(group => _renderDefaultAllowlistGroup(group)).join('')}
    </div>`;
  }

  function _renderDefaultAllowlistGroup(group) {
    const label = group.group || group.name || 'default';
    const domains = Array.isArray(group.domains) ? group.domains.join(', ') : '';
    return `<div class="sandbox-network-row sandbox-network-row--bundle">
      <div>
        <div class="sandbox-network-row__main">${_esc(label)}</div>
        ${domains ? `<div class="sandbox-network-row__sub">${_esc(domains)}</div>` : ''}
      </div>
      <span class="sandbox-chip">Read only</span>
    </div>`;
  }

  function _defaultAllowlistDomainCount(defaultAllowlist) {
    return defaultAllowlist.reduce((count, group) => count + (Array.isArray(group.domains) ? group.domains.length : 0), 0);
  }

  function _partitionNetworkDomains(domains) {
    return domains.reduce((acc, domain) => {
      const key = _networkScopeKey(domain.scope);
      acc[key === 'user' ? 'userDomains' : 'chatDomains'].push(domain);
      return acc;
    }, { chatDomains: [], userDomains: [] });
  }

  function _networkScopeKey(scope) {
    const value = String(scope || 'chat').trim().toLowerCase();
    if (value === 'workspace' || value === 'user') return 'user';
    return 'chat';
  }

  function _networkScopeLabel(scope) {
    return _networkScopeKey(scope) === 'user' ? 'This user' : 'This chat';
  }

  function _networkScopePayload(scope) {
    return _networkScopeKey(scope) === 'user' ? 'workspace' : 'chat';
  }

  function _renderNetworkEmpty(text) {
    return `<div class="sandbox-network-empty">${_esc(text)}</div>`;
  }

  function _renderDomain(domain, canRemove) {
    const value = domain.domain || domain.value || domain.pattern || 'Unknown domain';
    const rawScope = domain.scope || 'chat';
    const scope = _networkScopeLabel(rawScope);
    return `<div class="sandbox-network-row sandbox-network-row--action">
      <div class="sandbox-network-row__main">${_esc(value)}</div>
      <span class="sandbox-chip">${_esc(scope)}</span>
      ${canRemove ? `<button class="sandbox-icon-btn sandbox-icon-btn--danger" type="button" data-sandbox-action="domain-remove" data-domain="${_esc(value)}" data-scope="${_esc(domain.scope || 'chat')}" title="Remove domain" aria-label="Remove domain">${icons.trash()}</button>` : ''}
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
        scope: _networkScopePayload(values.scope || 'chat'),
      });
      form.reset();
    }
  }

  async function _onClick(event) {
    const pathInput = event.target?.closest?.('input[data-path-browser-kind]');
    if (pathInput && _el?.contains(pathInput)) {
      await _openPathBrowserFromInput(pathInput);
      return;
    }
    const btn = event.target?.closest?.('button[data-sandbox-action]');
    if (!btn || !_el?.contains(btn)) return;
    const action = btn.dataset.sandboxAction;
    if (action === 'run-mode-set') {
      await _mutate('sandbox.run_context.set', { runMode: btn.dataset.runMode || 'standard' });
    } else if (action === 'workspace-browse') {
      await _loadPathBrowser('workspace');
    } else if (action === 'mount-browse') {
      await _loadPathBrowser('mount');
    } else if (action === 'path-browser-select') {
      await _selectPathBrowserEntry(btn);
    } else if (action === 'path-browser-ok') {
      _commitPathBrowser(btn.dataset.kind || 'workspace');
    } else if (action === 'path-browser-cancel') {
      _closePathBrowser(btn.dataset.kind || 'workspace', { restore: true });
    } else if (action === 'mount-remove') {
      await _mutate('sandbox.mount.remove', {
        path: btn.dataset.path || '',
        scope: btn.dataset.scope || 'chat',
      });
    } else if (action === 'domain-remove') {
      await _mutate('sandbox.domain.remove', {
        domain: btn.dataset.domain || '',
        scope: btn.dataset.scope || 'chat',
      });
    } else if (action === 'bundle-toggle') {
      const method = btn.dataset.enabled === '1' ? 'sandbox.bundle.disable' : 'sandbox.bundle.enable';
      await _mutate(method, { bundleId: btn.dataset.bundleId || '' });
    }
  }

  async function _onFocusIn(event) {
    const input = event.target?.closest?.('input[data-path-browser-kind]');
    if (!input || !_el?.contains(input)) return;
    await _openPathBrowserFromInput(input);
  }

  async function _openPathBrowserFromInput(input) {
    const kind = input?.dataset?.pathBrowserKind || '';
    if (!kind || _hasOpenPathBrowser(kind)) return;
    await _loadPathBrowser(kind);
  }

  async function _loadPathBrowser(kind, requestedPath, options = {}) {
    const root = _el;
    const rpc = _rpc;
    const sessionKey = _lastData?.sessionKey || _activeSessionKey();
    if (!root || !rpc || !sessionKey) {
      _setNotice(root, 'Open a chat session before choosing directories.', 'warn');
      return;
    }
    const input = _pathInput(root, kind);
    const slot = _pathBrowserSlot(root, kind);
    const path = _pathBrowserRequestPath(input, requestedPath);
    if (input && input.dataset.committedValue === undefined) {
      input.dataset.committedValue = input.value || '';
    }
    _closeAllPathBrowsers({ restore: true, except: kind });
    _setPathBrowserLayer(root, kind, true);
    const loadId = _nextPathBrowserLoadId(kind);
    if (slot) slot.innerHTML = _renderPathBrowser(kind, { path, parentPath: path, entries: [], loading: true });
    try {
      _setNotice(root, 'Loading paths...', 'info');
      const result = await rpc.call('sandbox.path.list', {
        sessionKey,
        kind,
        path,
        browseChildren: options.browseChildren === true,
      });
      if (!_isPathBrowserLoadCurrent(kind, loadId) || root !== _el) return;
      if (slot) slot.innerHTML = _renderPathBrowser(kind, result);
      _setNotice(root, 'Choose a path from the list or keep typing.', 'ok');
    } catch (err) {
      if (!_isPathBrowserLoadCurrent(kind, loadId) || root !== _el) return;
      _setNotice(root, err?.message || String(err), 'warn');
      if (slot) slot.innerHTML = '';
      input?.focus?.();
    }
  }

  function _renderPathBrowser(kind, result) {
    const entries = Array.isArray(result?.entries) ? result.entries : [];
    const loading = Boolean(result?.loading);
    return `
      <div class="sandbox-path-browser" role="listbox" data-kind="${_esc(kind)}">
        ${loading ? _renderEmpty('Loading paths') : ''}
        ${!loading && entries.length ? `<div class="sandbox-path-browser__list">
          ${entries.map(entry => _renderPathBrowserEntry(kind, entry)).join('')}
        </div>` : ''}
        ${!loading && !entries.length ? _renderEmpty('No entries found') : ''}
        <div class="sandbox-path-browser__actions">
          <button class="btn btn--primary btn--sm" type="button" data-sandbox-action="path-browser-ok" data-kind="${_esc(kind)}">OK</button>
          <button class="btn btn--ghost btn--sm" type="button" data-sandbox-action="path-browser-cancel" data-kind="${_esc(kind)}">Cancel</button>
        </div>
      </div>`;
  }

  function _renderPathBrowserEntry(kind, entry) {
    const name = entry.name || entry.path || 'Unknown path';
    const path = entry.path || '';
    const entryKind = entry.kind === 'directory' ? 'directory' : 'file';
    const hidden = entry.hidden ? ' sandbox-path-browser__row--hidden' : '';
    const selectable = entry.selectable !== false;
    return `
      <button
        class="sandbox-path-browser__row${hidden}"
        type="button"
        data-sandbox-action="path-browser-select"
        data-kind="${_esc(kind)}"
        data-path="${_esc(path)}"
        data-entry-kind="${_esc(entryKind)}"
        ${selectable ? '' : 'disabled'}
      >
        <span class="sandbox-path-browser__kind">${entryKind === 'directory' ? 'Dir' : 'File'}</span>
        <span class="sandbox-path-browser__name">${_esc(name)}</span>
      </button>`;
  }

  async function _selectPathBrowserEntry(btn) {
    const root = _el;
    if (!root) return;
    const kind = btn.dataset.kind || 'workspace';
    const path = btn.dataset.path || '';
    const input = _pathInput(root, kind);
    if (input) {
      input.value = path;
      input.focus();
    }
    if (btn.dataset.entryKind === 'directory') {
      await _loadPathBrowser(kind, path, { browseChildren: true });
      return;
    }
    _setNotice(root, 'Path selected. Press OK to commit or keep browsing.', 'ok');
  }

  function _onDocumentKeydown(event) {
    if (!_el) return;
    if (event.key === 'Escape') {
      if (_hasOpenPathBrowser()) {
        event.preventDefault();
        _closeAllPathBrowsers({ restore: true });
      }
      return;
    }
    if (event.key !== 'Enter') return;
    const kind = _pathBrowserKindFromNode(document.activeElement);
    if (!kind || !_hasOpenPathBrowser(kind)) return;
    event.preventDefault();
    _commitPathBrowser(kind);
  }

  function _onDocumentClick(event) {
    if (!_el || !_hasOpenPathBrowser()) return;
    const targetKind = _pathBrowserKindFromNode(event.target);
    if (targetKind && _hasOpenPathBrowser(targetKind)) return;
    _closeAllPathBrowsers({ restore: true });
  }

  function _closeAllPathBrowsers(options = {}) {
    _PATH_BROWSER_KINDS.forEach(kind => {
      if (kind !== options.except) _closePathBrowser(kind, options);
    });
  }

  function _commitPathBrowser(kind) {
    const root = _el;
    if (!root) return;
    const input = _pathInput(root, kind);
    if (input) input.dataset.committedValue = input.value || '';
    _closePathBrowser(kind, { restore: false });
    _setNotice(root, 'Path selected. Review and save.', 'ok');
  }

  function _closePathBrowser(kind, options = {}) {
    const root = _el;
    if (!root) return;
    const slot = _pathBrowserSlot(root, kind);
    const wasOpen = Boolean(slot?.querySelector('.sandbox-path-browser'));
    if (wasOpen) _nextPathBrowserLoadId(kind);
    const input = _pathInput(root, kind);
    if (options.restore && wasOpen && input && input.dataset.committedValue !== undefined) {
      input.value = input.dataset.committedValue;
    }
    if (slot) slot.innerHTML = '';
    _setPathBrowserLayer(root, kind, false);
  }

  function _setPathBrowserLayer(root, kind, active) {
    const input = _pathInput(root, kind);
    const field = input?.closest?.('.sandbox-field--span');
    const form = input?.closest?.('.sandbox-inline-form');
    field?.classList?.toggle('is-path-browser-open', active);
    form?.classList?.toggle('is-path-browser-open', active);
  }

  function _hasOpenPathBrowser(kind) {
    const root = _el;
    if (!root) return false;
    if (kind) return Boolean(_pathBrowserSlot(root, kind)?.querySelector('.sandbox-path-browser'));
    return Boolean(root.querySelector('.sandbox-path-browser'));
  }

  function _pathBrowserKindFromNode(node) {
    const fieldKind = node?.closest?.('.sandbox-path-field')?.dataset?.pathKind;
    if (fieldKind) return fieldKind;
    const browserKind = node?.closest?.('.sandbox-path-browser')?.dataset?.kind;
    if (browserKind) return browserKind;
    return node?.dataset?.pathBrowserKind || '';
  }

  function _nextPathBrowserLoadId(kind) {
    _pathBrowserLoadIds[kind] = (_pathBrowserLoadIds[kind] || 0) + 1;
    return _pathBrowserLoadIds[kind];
  }

  function _isPathBrowserLoadCurrent(kind, loadId) {
    return _pathBrowserLoadIds[kind] === loadId;
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

  function _pathInput(root, kind) {
    return root.querySelector(kind === 'workspace' ? 'input[name="workspace"]' : 'input[name="path"]');
  }

  function _pathBrowserSlot(root, kind) {
    return root.querySelector(`.sandbox-path-browser-slot[data-path-browser-kind="${kind}"]`);
  }

  function _pathBrowserRequestPath(input, requestedPath) {
    if (requestedPath !== undefined && requestedPath !== null) return requestedPath;
    const value = String(input?.value || '').trim();
    return value || '/';
  }

  function _renderEmpty(text) {
    return `<div class="sandbox-empty">${_esc(text)}</div>`;
  }

  function _bundleCatalog(status) {
    const catalog = status.bundle_catalog || status.bundleCatalog || [];
    return Array.isArray(catalog) ? catalog : [];
  }

  function _defaultAllowlist(status) {
    const allowlist = status.default_allowlist || status.defaultAllowlist || [];
    return Array.isArray(allowlist) ? allowlist : [];
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
      runMode: runContext.runMode || status.run_mode || 'full',
      runModeLabel: runContext.runModeLabel || status.run_mode_label || _runModeLabel(status.run_mode || 'full'),
      mounts: Array.isArray(runContext.mounts) ? runContext.mounts : [],
      domains: Array.isArray(runContext.domains) ? runContext.domains : [],
      bundles: Array.isArray(runContext.bundles) ? runContext.bundles : [],
      publicNetwork: Array.isArray(runContext.publicNetwork)
        ? runContext.publicNetwork
        : (Array.isArray(runContext.public_network) ? runContext.public_network : []),
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
