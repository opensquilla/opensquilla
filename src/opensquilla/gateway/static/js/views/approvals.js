/** OpenSquilla Web UI — Approvals view. */

const ApprovalsView = (() => {
  const ELEVATED_MODE_KEY = 'opensquilla.elevatedMode';
  const ELEVATED_MODE_VERSION_KEY = 'opensquilla.elevatedMode.version';
  const ELEVATED_MODE_STORAGE_VERSION = '2';
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];

  function _ensureCss() {
    if (document.querySelector('link[data-view-css="approvals"]')) return;
    const data = document.getElementById('opensquilla-data');
    const base = data?.dataset.basePath || '';
    const cssVersion = data?.dataset.version || '';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${base}/static/css/views/approvals.css${cssVersion ? '?v=' + encodeURIComponent(cssVersion) : ''}`;
    link.dataset.viewCss = 'approvals';
    document.head.appendChild(link);
  }

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _ensureCss();
    _el.innerHTML = `
      <div class="ap-stage">
        <header class="ap-stage__header">
          <div class="ap-stage__title-block">
            <span class="ap-stage__eyebrow">Control · Approvals</span>
            <h2 class="ap-stage__title">Approvals</h2>
            <p class="ap-stage__subtitle">Tool execution gate — keep risky actions paused until you say go.</p>
          </div>
          <div class="ap-stage__actions">
            <button class="btn btn--ghost" id="appr-refresh" title="Refresh">
              ${icons.refresh()}<span>Refresh</span>
            </button>
          </div>
        </header>

        <div id="appr-content"></div>
      </div>`;

    _el.querySelector('#appr-refresh').addEventListener('click', _loadData);
    _loadData();

    const id = setInterval(_loadData, 5000);
    _intervals.push(id);
  }

  function destroy() {
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    _el = null;
    _rpc = null;
  }

  function _authHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    const token = (App.getAuthToken && App.getAuthToken()) || '';
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return headers;
  }

  function _loadData() {
    Promise.all([
      fetch('/api/approvals', { headers: _authHeaders() })
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }),
      _loadExecutionModeSummary(),
    ])
      .then(([data, executionMode]) => {
        const container = _el && _el.querySelector('#appr-content');
        if (!container) return;

        const pending = data.pending || [];
        const mode = data.mode || 'auto-approve';

        const modeOptions = [
          { value: 'prompt', label: 'Ask every time', desc: 'Every risky tool execution opens an approval prompt.' },
          { value: 'auto-approve', label: 'Auto approve', desc: 'All tool executions are automatically approved.' },
          { value: 'auto-deny', label: 'Auto deny', desc: 'All tool executions are automatically denied.' },
        ];
        const activeOpt = modeOptions.find(m => m.value === mode) || modeOptions[0];

        let html = `
          <section class="stat-row">
            <div class="stat stat--hero">
              <div class="stat-label">Pending</div>
              <div class="stat-value">${pending.length}</div>
              <div class="stat-hint">${pending.length ? 'awaiting decision' : 'all clear'}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Strategy</div>
              <div class="stat-value">${_esc(activeOpt.label)}</div>
              <div class="stat-hint">${_esc(activeOpt.desc)}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Effective execution mode</div>
              <div class="stat-value mono">${_esc(executionMode.label)}</div>
              <div class="stat-hint">${_esc(executionMode.desc)}</div>
            </div>
          </section>

          <section class="ap-strategy">
            <div class="ap-strategy__head">
              <span class="ap-panel__eyebrow">Strategy</span>
              <h3 class="ap-panel__title">How approvals are handled</h3>
            </div>
            <div class="ap-strategy__options" role="radiogroup" aria-label="Approval strategy">
              ${modeOptions.map(opt => `
                <label class="ap-radio${opt.value === mode ? ' is-active' : ''}">
                  <input type="radio" name="ap-mode" value="${opt.value}" ${opt.value === mode ? 'checked' : ''} />
                  <span class="ap-radio__indicator"></span>
                  <span class="ap-radio__body">
                    <span class="ap-radio__label">${_esc(opt.label)}</span>
                    <span class="ap-radio__desc">${_esc(opt.desc)}</span>
                  </span>
                </label>
              `).join('')}
            </div>
          </section>`;

        if (pending.length === 0) {
          html += `<section class="state">
            <div class="state-icon">${icons.check()}</div>
            <div class="state-title">No pending approvals.</div>
            <p class="state-text">When an agent reaches a risky tool call, it will appear here for your sign-off.</p>
          </section>`;
        } else {
          html += `<section class="ap-pending">
            <div class="ap-list-head">
              <h3 class="ap-list__title">Pending requests <span class="ap-list__count">${pending.length}</span></h3>
            </div>
            <div class="ap-pending__list">
              ${pending.map(_renderApproval).join('')}
            </div>
          </section>`;
        }

        container.innerHTML = html;

        _bindModeSave(container, mode);

        container.querySelectorAll('[data-decision]').forEach(btn => {
          btn.addEventListener('click', () => {
            const id = btn.dataset.apprId;
            const namespace = btn.dataset.apprNs || 'exec';
            const decision = btn.dataset.decision;
            const approved = decision === 'approve' || decision === 'always' || decision === 'bypass';
            const allowAlways = btn.dataset.decision === 'always';
            const rememberIntent = btn.dataset.decision === 'always';
            const elevatedMode = decision === 'bypass' ? 'bypass' : '';
            const body = { id, namespace, approved, allowAlways, rememberIntent };
            if (elevatedMode) body.elevatedMode = elevatedMode;
            fetch('/api/approvals/resolve', {
              method: 'POST',
              headers: _authHeaders({ 'Content-Type': 'application/json' }),
              body: JSON.stringify(body)
            }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
              .then(() => {
                if (elevatedMode) _setBrowserElevated(elevatedMode);
                UI.toast((elevatedMode ? 'Approval bypass enabled' : (approved ? 'Approved' : 'Denied')) + ': ' + id, 'info');
                _loadData();
              })
              .catch(err => UI.toast('Failed: ' + err.message, 'err'));
          });
        });
      })
      .catch(err => UI.toast('Failed to load approvals: ' + err.message, 'err'));
  }

  async function _loadExecutionModeSummary() {
    const sessionMode = _browserElevatedMode();
    if (sessionMode) return _executionModeSummary('Session', sessionMode);
    let globalMode = '';
    try {
      if (_rpc?.waitForConnection && _rpc.state !== 'connected') {
        await _withTimeout(_rpc.waitForConnection(), 1000);
      }
      const cfg = _rpc?.call ? await _rpc.call('config.get') : null;
      globalMode = _normalizeElevatedMode(cfg?.permissions?.default_mode);
    } catch {}
    if (globalMode) return _executionModeSummary('Global', globalMode);
    return {
      label: 'Approval prompts',
      desc: 'Risky tool calls will open approval prompts.',
    };
  }

  function _executionModeSummary(scope, mode) {
    const label = `${scope} ${String(mode).toUpperCase()}`;
    if (mode === 'bypass') {
      return {
        label,
        desc: scope === 'Session'
          ? 'Approval prompts are currently bypassed for this browser chat session.'
          : 'Approval prompts are currently bypassed by the global permission mode.',
      };
    }
    if (mode === 'full') {
      return {
        label,
        desc: scope === 'Session'
          ? 'Approval and sensitive-path prompts are bypassed for this browser chat session.'
          : 'Approval and sensitive-path prompts are bypassed by the global permission mode.',
      };
    }
    return {
      label,
      desc: 'Host execution is enabled; risky tool calls still use approval prompts.',
    };
  }

  function _withTimeout(promise, timeoutMs) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('timeout')), timeoutMs);
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

  function _browserElevatedMode() {
    let mode = '';
    let version = '';
    try {
      mode = localStorage.getItem(ELEVATED_MODE_KEY) || '';
      version = localStorage.getItem(ELEVATED_MODE_VERSION_KEY) || '';
    } catch {}
    if (mode === 'full' && version !== ELEVATED_MODE_STORAGE_VERSION) return 'bypass';
    return _normalizeElevatedMode(mode);
  }

  function _normalizeElevatedMode(mode) {
    return mode === 'on' || mode === 'bypass' || mode === 'full' ? mode : '';
  }

  function _renderApproval(item) {
    const toolName = item.toolName || item.pluginId || item.actionKind || 'Unknown';
    const command = _approvalCommand(item);
    const detail = _approvalDetail(item);
    const canAlways = item.namespace === 'exec' && !!command;
    return `<article class="ap-card">
      <header class="ap-card__head">
        <div class="ap-card__title-row">
          <span class="ap-card__name">${_esc(toolName)}</span>
          ${item.namespace ? `<span class="ap-pill ap-pill--ns">${_esc(item.namespace)}</span>` : ''}
        </div>
        <span class="ap-card__time">awaiting decision</span>
      </header>
      <div class="ap-card__meta">
        ${item.agent ? `<span><em>Agent</em> ${_esc(item.agent)}</span>` : ''}
        ${item.sessionKey ? `<span><em>Session</em> <code>${_esc(item.sessionKey)}</code></span>` : ''}
      </div>
      ${command ? `<div class="ap-card__block">
        <div class="ap-card__block-label">Command</div>
        <pre class="ap-card__pre ap-card__pre--cmd">${_esc(command)}</pre>
      </div>` : ''}
      ${detail ? `<div class="ap-card__block">
        <div class="ap-card__block-label">Details</div>
        <pre class="ap-card__pre">${_esc(detail)}</pre>
      </div>` : ''}
      <div class="ap-card__actions">
        <button class="btn btn--primary" data-appr-id="${_esc(item.id || '')}" data-appr-ns="${_esc(item.namespace || 'exec')}" data-decision="approve">${icons.check()}<span>Approve once</span></button>
        ${canAlways ? `<button class="btn btn--ghost" data-appr-id="${_esc(item.id || '')}" data-appr-ns="${_esc(item.namespace || 'exec')}" data-decision="always">Always allow this type</button>` : ''}
        <button class="btn btn--warn" data-appr-id="${_esc(item.id || '')}" data-appr-ns="${_esc(item.namespace || 'exec')}" data-decision="bypass" title="Bypass approval prompts while keeping sensitive-path checks">Bypass approvals</button>
        <button class="btn btn--danger" data-appr-id="${_esc(item.id || '')}" data-appr-ns="${_esc(item.namespace || 'exec')}" data-decision="deny">${icons.x()}<span>Deny</span></button>
      </div>
    </article>`;
  }

  function _bindModeSave(container, currentMode) {
    container.querySelectorAll('input[name="ap-mode"]').forEach(input => {
      input.addEventListener('change', () => {
        const mode = input.value;
        if (mode === currentMode) return;
        // Optimistically style
        container.querySelectorAll('.ap-radio').forEach(r => r.classList.remove('is-active'));
        input.closest('.ap-radio')?.classList.add('is-active');
        fetch('/api/approvals/settings', {
          method: 'POST',
          headers: _authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ mode }),
        }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(() => {
            UI.toast('Approval strategy: ' + mode, mode === 'auto-approve' ? 'warn' : 'info');
            _loadData();
            if (window.ApprovalMonitor) ApprovalMonitor.pollNow();
          })
          .catch(err => UI.toast('Failed to save strategy: ' + err.message, 'err'));
      });
    });
  }

  function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _modeStateClass(mode) {
    if (mode === 'auto-approve') return 'warn';
    if (mode === 'auto-deny') return 'err';
    return 'ok';
  }

  function _approvalCommand(item) {
    if (item.command) return String(item.command);
    if (Array.isArray(item.argv) && item.argv.length > 0) return item.argv.map(String).join(' ');
    if (item.args && item.args.command) return String(item.args.command);
    return '';
  }

  function _approvalDetail(item) {
    if (item.warning) return String(item.warning);
    const args = item.args || item.params || null;
    if (!args) return '';
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      return String(args);
    }
  }

  function _setBrowserElevated(mode) {
    const normalized = mode === 'full' || mode === 'bypass' || mode === 'on' ? mode : '';
    try {
      if (normalized) {
        localStorage.setItem(ELEVATED_MODE_KEY, normalized);
        localStorage.setItem(ELEVATED_MODE_VERSION_KEY, ELEVATED_MODE_STORAGE_VERSION);
      } else {
        localStorage.removeItem(ELEVATED_MODE_KEY);
        localStorage.removeItem(ELEVATED_MODE_VERSION_KEY);
      }
    } catch {}
    window.dispatchEvent(new CustomEvent('opensquilla:elevated-mode', { detail: { mode: normalized } }));
  }

  return { render, destroy };
})();

window.ApprovalsView = ApprovalsView;
