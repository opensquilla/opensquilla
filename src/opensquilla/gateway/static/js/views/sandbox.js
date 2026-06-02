/** OpenSquilla Web UI - Sandbox control view. */

const SandboxView = (() => {
  let _el = null;
  let _rpc = null;
  let _generation = 0;
  let _pendingApprovalCount = 0;
  let _lastRuleCount = 0;

  function render(el) {
    _generation += 1;
    _el = el;
    _rpc = App.getRpc();
    _el.innerHTML = `
      <div class="sandbox-stage">
        <header class="sandbox-stage__header">
          <div class="sandbox-stage__title-block">
            <span class="sandbox-stage__eyebrow">Control / Sandbox</span>
            <h2 class="sandbox-stage__title">Sandbox</h2>
            <p class="sandbox-stage__subtitle" id="sandbox-summary">Checking sandbox state</p>
          </div>
          <button class="btn btn--ghost" id="sandbox-refresh" title="Refresh sandbox state">
            ${icons.refresh()}<span>Refresh</span>
          </button>
        </header>

        <section class="sandbox-strip" id="sandbox-status" aria-label="Status">
          ${_renderLoadingStatus()}
        </section>

        <div class="sandbox-grid">
          <section class="sandbox-panel sandbox-panel--wide" aria-labelledby="sandbox-workspace-title">
            <div class="sandbox-panel__head">
              <div>
                <span class="sandbox-panel__eyebrow">Scope</span>
                <h3 class="sandbox-panel__title" id="sandbox-workspace-title">Workspace & Mounts</h3>
              </div>
              <span class="sandbox-panel__meta" id="sandbox-session-label">Session</span>
            </div>
            <div id="sandbox-workspace">${_renderEmpty('Loading workspace')}</div>
          </section>

          <section class="sandbox-panel" aria-labelledby="sandbox-network-title">
            <div class="sandbox-panel__head">
              <div>
                <span class="sandbox-panel__eyebrow">Access</span>
                <h3 class="sandbox-panel__title" id="sandbox-network-title">Managed Network</h3>
              </div>
              <span class="conn-pill" id="sandbox-network-pill">Checking</span>
            </div>
            <div id="sandbox-network">${_renderEmpty('Loading network policy')}</div>
          </section>

          <section class="sandbox-panel sandbox-panel--span" aria-labelledby="sandbox-rules-title">
            <div class="sandbox-panel__head">
              <div>
                <span class="sandbox-panel__eyebrow">Policy</span>
                <h3 class="sandbox-panel__title" id="sandbox-rules-title">Sandbox Rules</h3>
              </div>
              <span class="sandbox-panel__meta" id="sandbox-rules-count">0 rules</span>
            </div>
            <div id="sandbox-rules">${_renderEmpty('Loading rules')}</div>
          </section>
        </div>
      </div>`;

    _el.querySelector('#sandbox-refresh')?.addEventListener('click', _load);
    window.addEventListener('opensquilla:approvals-pending', _onApprovalsPending);
    _load();
  }

  function destroy() {
    _generation += 1;
    window.removeEventListener('opensquilla:approvals-pending', _onApprovalsPending);
    _el = null;
    _rpc = null;
    _pendingApprovalCount = 0;
    _lastRuleCount = 0;
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
        runContext = explanation?.runContext || null;
      } catch {}

      if (!runContext && sessionKey) {
        try {
          runContext = await rpc.call('sandbox.run_context.get', { sessionKey });
        } catch {}
      }

      if (!_isCurrent(root, rpc, generation)) return;
      _renderLoaded(root, { status, explanation, runContext, sessionKey });
    } catch (err) {
      if (!_isCurrent(root, rpc, generation)) return;
      _renderError(root, err);
    }
  }

  function _setLoading(root) {
    const summary = root.querySelector('#sandbox-summary');
    if (summary) summary.textContent = 'Checking sandbox state';
    const status = root.querySelector('#sandbox-status');
    if (status) status.innerHTML = _renderLoadingStatus();
    const workspace = root.querySelector('#sandbox-workspace');
    if (workspace) workspace.innerHTML = _renderEmpty('Loading workspace');
    const network = root.querySelector('#sandbox-network');
    if (network) network.innerHTML = _renderEmpty('Loading network policy');
    const rules = root.querySelector('#sandbox-rules');
    if (rules) rules.innerHTML = _renderEmpty('Loading rules');
    _lastRuleCount = 0;
    _updateApprovalActivity(_pendingApprovalCount);
  }

  function _renderLoaded(root, data) {
    const status = data.status || {};
    const runContext = data.runContext || {};
    const summary = root.querySelector('#sandbox-summary');
    if (summary) summary.textContent = _statusSummary(status, runContext);

    const statusEl = root.querySelector('#sandbox-status');
    if (statusEl) statusEl.innerHTML = _renderStatus(status, runContext);

    const sessionLabel = root.querySelector('#sandbox-session-label');
    if (sessionLabel) sessionLabel.textContent = data.sessionKey ? 'Current session' : 'No active session';

    const workspace = root.querySelector('#sandbox-workspace');
    if (workspace) workspace.innerHTML = _renderWorkspace(runContext, data.sessionKey);

    const network = root.querySelector('#sandbox-network');
    if (network) network.innerHTML = _renderNetwork(status, runContext);

    const networkPill = root.querySelector('#sandbox-network-pill');
    if (networkPill) {
      const variant = status.managed_network === 'ready' ? 'ok' : 'warn';
      networkPill.className = `conn-pill ${variant}`;
      networkPill.textContent = _label(status.managed_network || 'unknown');
      networkPill.title = 'Managed network';
    }

    const rules = _rules(status, runContext, data.explanation);
    _lastRuleCount = rules.length;
    const rulesCount = root.querySelector('#sandbox-rules-count');
    if (rulesCount) rulesCount.textContent = `${rules.length} ${rules.length === 1 ? 'rule' : 'rules'}`;
    const rulesEl = root.querySelector('#sandbox-rules');
    if (rulesEl) rulesEl.innerHTML = _renderRules(rules);
    _updateApprovalActivity(_pendingApprovalCount);
  }

  function _renderError(root, err) {
    const message = err?.message || String(err);
    const summary = root.querySelector('#sandbox-summary');
    if (summary) summary.textContent = 'Sandbox state unavailable';
    const status = root.querySelector('#sandbox-status');
    if (status) {
      status.innerHTML = `
        <article class="sandbox-status-card sandbox-status-card--error">
          <span class="sandbox-status-card__label">Status</span>
          <strong>Unavailable</strong>
          <span class="sandbox-status-card__hint">${_esc(message)}</span>
        </article>`;
    }
    const workspace = root.querySelector('#sandbox-workspace');
    if (workspace) workspace.innerHTML = _renderEmpty('Connect to the gateway to load workspace scope');
    const network = root.querySelector('#sandbox-network');
    if (network) network.innerHTML = _renderEmpty('Managed network state is unavailable');
    const rules = root.querySelector('#sandbox-rules');
    if (rules) rules.innerHTML = _renderEmpty('Sandbox rules are unavailable');
    _lastRuleCount = 0;
    _updateApprovalActivity(_pendingApprovalCount);
    const pill = root.querySelector('#sandbox-network-pill');
    if (pill) {
      pill.className = 'conn-pill err';
      pill.textContent = 'Unavailable';
    }
  }

  function _renderLoadingStatus() {
    return `
      <article class="sandbox-status-card">
        <span class="sandbox-status-card__label">Status</span>
        <strong>Checking</strong>
        <span class="sandbox-status-card__hint">Waiting for sandbox.status</span>
      </article>
      <article class="sandbox-status-card">
        <span class="sandbox-status-card__label">Run mode</span>
        <strong>-</strong>
        <span class="sandbox-status-card__hint">Session context</span>
      </article>
      <article class="sandbox-status-card">
        <span class="sandbox-status-card__label">Target</span>
        <strong>-</strong>
        <span class="sandbox-status-card__hint">Execution boundary</span>
      </article>`;
  }

  function _renderStatus(status, runContext) {
    const mode = runContext.runModeLabel || status.run_mode_label || _label(status.run_mode || runContext.runMode || 'unknown');
    const target = runContext.executionTarget || status.execution_target || 'unknown';
    const backend = status.backend || 'unknown';
    return `
      <article class="sandbox-status-card sandbox-status-card--accent">
        <span class="sandbox-status-card__label">Status</span>
        <strong>${_esc(_label(status.posture || status.run_mode || 'Sandbox'))}</strong>
        <span class="sandbox-status-card__hint">Backend: ${_esc(backend)}</span>
      </article>
      <article class="sandbox-status-card">
        <span class="sandbox-status-card__label">Run mode</span>
        <strong>${_esc(mode)}</strong>
        <span class="sandbox-status-card__hint">${_esc(runContext.source || 'gateway policy')}</span>
      </article>
      <article class="sandbox-status-card">
        <span class="sandbox-status-card__label">Target</span>
        <strong>${_esc(_label(target))}</strong>
        <span class="sandbox-status-card__hint">${_esc(status.permissions?.default_mode ? 'Permissions: ' + status.permissions.default_mode : 'Execution boundary')}</span>
      </article>`;
  }

  function _renderWorkspace(runContext, sessionKey) {
    if (!sessionKey) {
      return _renderEmpty('Open a chat session to see session workspace and mounts');
    }
    const rows = [
      _detailRow('Workspace', runContext.workspace || 'Not set', true),
      _detailRow('Run mode', runContext.runModeLabel || _label(runContext.runMode || 'unknown'), false),
    ];
    const mounts = Array.isArray(runContext.mounts) ? runContext.mounts : [];
    return `
      <div class="sandbox-detail-list">${rows.join('')}</div>
      <div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Mounts</div>
        ${mounts.length ? `<div class="sandbox-list">${mounts.map(_renderMount).join('')}</div>` : _renderEmpty('No extra mounts')}
      </div>`;
  }

  function _renderMount(mount) {
    const path = mount.path || mount.source || mount.target || 'Unknown path';
    const access = mount.access || mount.mode || 'ro';
    const source = mount.source && mount.source !== path ? mount.source : (mount.created_by || mount.createdBy || '');
    return `<div class="sandbox-list__row">
      <span class="sandbox-list__main">${_esc(path)}</span>
      <span class="sandbox-chip">${_esc(access)}</span>
      ${source ? `<span class="sandbox-list__sub">${_esc(source)}</span>` : ''}
    </div>`;
  }

  function _renderNetwork(status, runContext) {
    const domains = Array.isArray(runContext.domains) ? runContext.domains : [];
    const bundles = Array.isArray(runContext.bundles) ? runContext.bundles : [];
    const grants = Array.isArray(runContext.temporaryGrants) ? runContext.temporaryGrants : [];
    const networkDefault = status.sandbox?.network_default || 'not reported';
    return `
      <div class="sandbox-detail-list">
        ${_detailRow('Default', networkDefault, false)}
        ${_detailRow('Managed network', _label(status.managed_network || 'unknown'), false)}
      </div>
      <div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Domains</div>
        ${domains.length ? `<div class="sandbox-list">${domains.map(_renderDomain).join('')}</div>` : _renderEmpty('No session domains')}
      </div>
      <div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Bundles</div>
        ${bundles.length ? `<div class="sandbox-list">${bundles.map(_renderBundle).join('')}</div>` : _renderEmpty('No package bundles')}
      </div>
      ${grants.length ? `<div class="sandbox-list-block">
        <div class="sandbox-list-block__label">Recent Decisions</div>
        <div class="sandbox-list">${grants.map(_renderTemporaryGrant).join('')}</div>
      </div>` : ''}`;
  }

  function _renderDomain(domain) {
    const value = domain.domain || domain.value || domain.pattern || 'Unknown domain';
    const access = domain.access || domain.scope || 'allow';
    return `<div class="sandbox-list__row">
      <span class="sandbox-list__main">${_esc(value)}</span>
      <span class="sandbox-chip">${_esc(access)}</span>
    </div>`;
  }

  function _renderBundle(bundle) {
    const id = bundle.bundle_id || bundle.bundleId || bundle.id || 'Unknown bundle';
    const scope = bundle.scope || 'workspace';
    return `<div class="sandbox-list__row">
      <span class="sandbox-list__main">${_esc(id)}</span>
      <span class="sandbox-chip">${_esc(scope)}</span>
    </div>`;
  }

  function _renderTemporaryGrant(grant) {
    const value = grant.value || grant.domain || grant.path || 'Temporary grant';
    const kind = grant.kind || 'grant';
    return `<div class="sandbox-list__row">
      <span class="sandbox-list__main">${_esc(value)}</span>
      <span class="sandbox-chip">${_esc(kind)}</span>
    </div>`;
  }

  function _rules(status, runContext, explanation) {
    const result = [];
    if (status.sandbox) {
      result.push(['Sandbox', status.sandbox.sandbox ? 'Enabled' : 'Disabled']);
      result.push(['Security grading', status.sandbox.security_grading ? 'Enabled' : 'Disabled']);
      if (status.sandbox.network_default) result.push(['Network default', status.sandbox.network_default]);
    }
    if (status.permissions?.default_mode) result.push(['Permission default', status.permissions.default_mode]);
    if (runContext.executionTarget) result.push(['Execution target', runContext.executionTarget]);
    const messages = Array.isArray(explanation?.messages) ? explanation.messages : [];
    messages.forEach(item => {
      if (item?.message) result.push([_label(item.kind || 'status'), item.message]);
    });
    return result;
  }

  function _renderRules(rules) {
    if (!rules.length) return _renderEmpty('No sandbox rules reported');
    return `<div class="sandbox-rule-list">
      ${rules.map(([label, value]) => `
        <div class="sandbox-rule-list__row">
          <span>${_esc(label)}</span>
          <strong>${_esc(value)}</strong>
        </div>`).join('')}
    </div>`;
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
    const rulesCount = root.querySelector('#sandbox-rules-count');
    if (rulesCount) {
      rulesCount.textContent = safeCount > 0
        ? `${safeCount} pending ${safeCount === 1 ? 'approval' : 'approvals'}`
        : `${_lastRuleCount} ${_lastRuleCount === 1 ? 'rule' : 'rules'}`;
    }

    const rulesEl = root.querySelector('#sandbox-rules');
    if (!rulesEl) return;

    const existing = rulesEl.querySelector('[data-sandbox-approval-activity]');
    if (safeCount <= 0) {
      if (existing) existing.remove();
      const list = rulesEl.querySelector('.sandbox-rule-list');
      if (list && !list.querySelector('.sandbox-rule-list__row')) {
        rulesEl.innerHTML = _renderEmpty('No sandbox rules reported');
      }
      return;
    }

    const row = `
      <div class="sandbox-rule-list__row" data-sandbox-approval-activity>
        <span>Approvals pending</span>
        <strong>${safeCount}</strong>
      </div>`;
    let list = rulesEl.querySelector('.sandbox-rule-list');
    if (!list) {
      rulesEl.innerHTML = `<div class="sandbox-rule-list">${row}</div>`;
      return;
    }
    if (existing) {
      existing.outerHTML = row;
    } else {
      list.insertAdjacentHTML('afterbegin', row);
    }
  }

  function _detailRow(label, value, mono) {
    return `<div class="sandbox-detail-list__row">
      <span>${_esc(label)}</span>
      <strong class="${mono ? 'is-mono' : ''}">${_esc(value || '-')}</strong>
    </div>`;
  }

  function _renderEmpty(text) {
    return `<div class="sandbox-empty">${_esc(text)}</div>`;
  }

  function _activeSessionKey() {
    try {
      return localStorage.getItem('opensquilla_active_session') || '';
    } catch {
      return '';
    }
  }

  function _statusSummary(status, runContext) {
    const mode = runContext.runModeLabel || status.run_mode_label || _label(status.run_mode || 'unknown');
    const network = _label(status.managed_network || 'unknown');
    return `${mode} / Managed network ${network}`;
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
