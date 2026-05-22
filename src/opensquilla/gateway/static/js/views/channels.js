/** OpenSquilla Web UI — read-only configured channels view. */

const ChannelsView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];
  let _channels = [];

  function _ensureCss() {
    if (document.querySelector('link[data-view-css="channels"]')) return;
    const data = document.getElementById('opensquilla-data');
    const base = data?.dataset.basePath || '';
    const cssVersion = data?.dataset.version || '';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${base}/static/css/views/channels.css${cssVersion ? '?v=' + encodeURIComponent(cssVersion) : ''}`;
    link.dataset.viewCss = 'channels';
    document.head.appendChild(link);
  }

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _ensureCss();

    _el.innerHTML = `
      <div class="ch-stage">
        <header class="ch-stage__header">
          <div class="ch-stage__title-block">
            <span class="ch-stage__eyebrow">Control · Channels</span>
            <h2 class="ch-stage__title">Channels</h2>
            <p class="ch-stage__subtitle">Runtime status for configured channels. Use guided setup or CLI to add and change channel configuration.</p>
          </div>
          <div class="ch-stage__actions">
            <button class="btn btn--ghost" id="ch-refresh" title="Refresh">
              ${icons.refresh()}<span>Refresh</span>
            </button>
          </div>
        </header>

        <section class="stat-row" id="stat-row"></section>

        <section class="ch-list">
          <div class="ch-list__head">
            <h3 class="ch-list__title" id="ch-list-title">Configured channels</h3>
          </div>
          <div id="ch-cards" class="ch-cards"></div>
        </section>
      </div>`;

    _el.querySelector('#ch-refresh').addEventListener('click', _loadData);

    // Subscribe to real-time channel status events
    const unsub = _rpc.on('channel.status', () => _loadData());
    _unsubs.push(unsub);

    _loadData();

    const id = setInterval(_loadData, 30000);
    _intervals.push(id);
  }

  function destroy() {
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    _channels = [];
    _el = null;
    _rpc = null;
  }

  async function _loadData() {
    if (!_el) return;
    const rpc = _rpc;
    if (!rpc) return;
    await rpc.waitForConnection();
    if (!_el || _rpc !== rpc) return;

    rpc.call('channels.status').then(data => {
      if (!_el) return;
      const raw = (data.channels || []).filter(c => c && c.configured !== false);

      // Sort by operator urgency while keeping the UI read-only.
      const order = { running: 0, connected: 0, restarting: 1, exhausted: 1, dead: 1, stopped: 2, disabled: 3 };
      _channels = [...raw].sort((a, b) => {
        const oa = order[a.status] ?? 1;
        const ob = order[b.status] ?? 1;
        return oa - ob;
      });

      _renderStats();
      _renderCards();
    }).catch(err => UI.toast('Failed to load channels: ' + err.message, 'err'));
  }

  function _renderStats() {
    const wrap = _el && _el.querySelector('#stat-row');
    if (!wrap) return;
    const total = _channels.length;
    const connected = _channels.filter(c => c.status === 'running' || c.status === 'connected').length;
    const attention = _channels.filter(c => _needsAttention(c.status)).length;
    const inactive = total - connected - attention;
    const disabled = _channels.filter(c => c.status === 'disabled').length;
    const restarts = _channels.reduce((acc, c) => acc + (Number(c.restart_attempts) || 0), 0);
    const types = new Set();
    _channels.forEach(c => { if (c.type) types.add(c.type); });

    wrap.innerHTML = `
      <div class="stat stat--hero">
        <div class="stat-label">Total channels</div>
        <div class="stat-value">${total}</div>
        <div class="stat-hint">${types.size} type${types.size === 1 ? '' : 's'}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Connected</div>
        <div class="stat-value">
          ${connected}${connected ? '<span class="dot ok"></span>' : ''}
        </div>
        <div class="stat-hint">${connected ? 'live' : (attention ? `${attention} unhealthy` : 'all idle')}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Inactive</div>
        <div class="stat-value">${inactive}</div>
        <div class="stat-hint">${attention ? `<span class="ch-neg">${attention} need attention</span>` : _inactiveHint(inactive, disabled)}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Restart attempts</div>
        <div class="stat-value mono">${restarts}</div>
        <div class="stat-hint">since gateway start</div>
      </div>`;
  }

  function _renderCards() {
    const container = _el && _el.querySelector('#ch-cards');
    const titleEl = _el && _el.querySelector('#ch-list-title');
    if (!container) return;
    if (titleEl) {
      titleEl.innerHTML = _channels.length
        ? `Configured channels <span class="ch-list__count">${_channels.length}</span>`
        : 'Configured channels';
    }

    if (_channels.length === 0) {
      container.innerHTML = `<div class="ch-empty">
        <div class="ch-empty__art" aria-hidden="true">
          <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <radialGradient id="cg2" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="rgba(240,160,48,0.18)"/>
                <stop offset="60%" stop-color="rgba(240,160,48,0.04)"/>
                <stop offset="100%" stop-color="rgba(240,160,48,0)"/>
              </radialGradient>
            </defs>
            <circle cx="60" cy="60" r="58" fill="url(#cg2)"/>
            <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55">
              <rect x="20" y="40" width="36" height="40" rx="6"/>
              <line x1="28" y1="52" x2="48" y2="52"/>
              <line x1="28" y1="60" x2="44" y2="60"/>
            </g>
            <g fill="none" stroke="var(--accent)" stroke-width="1.6">
              <rect x="64" y="40" width="36" height="40" rx="6"/>
              <line x1="72" y1="52" x2="92" y2="52"/>
              <line x1="72" y1="60" x2="88" y2="60"/>
            </g>
            <g stroke="var(--accent)" stroke-width="1.4" stroke-dasharray="2 4" opacity="0.7">
              <line x1="56" y1="60" x2="64" y2="60"/>
            </g>
          </svg>
        </div>
        <div class="ch-empty__title">No configured channels.</div>
        <p class="ch-empty__msg">Channel provisioning stays in guided setup and the CLI so credentials, dependency extras, webhook URLs, and restart requirements stay explicit.</p>
        <div class="ch-empty__actions">
          <button class="btn btn--primary" id="ch-guided-setup" type="button">${icons.config()}<span>Guided setup</span></button>
        </div>
        <code class="ch-empty__code">opensquilla configure --section channels · opensquilla channels list</code>
      </div>`;
      _el.querySelector('#ch-guided-setup')?.addEventListener('click', () => Router.navigate('/setup'));
      return;
    }

    container.innerHTML = _channels.map((ch, i) => {
      const name = ch.name || ch.id || 'Unknown';
      const status = ch.status || (ch.connected ? 'connected' : 'stopped');
      const isRunning = status === 'running' || status === 'connected';
      const isDead = status === 'dead';
      const dotCls = isRunning ? 'ok' : isDead ? 'err' : 'off';
      const chipCls = isRunning ? 'chip-ok' : isDead ? 'chip-danger' : '';
      const since = ch.connected_since ? UI.relTime(ch.connected_since) : '—';
      const attempts = ch.restart_attempts != null ? String(ch.restart_attempts) : '0';

      let configJson = '';
      try {
        configJson = JSON.stringify(ch, null, 2);
      } catch {
        configJson = String(ch);
      }

      return `<article class="ch-card" style="--i:${i}">
        <header class="ch-card__head">
          <span class="dot ${dotCls}"></span>
          <span class="ch-card__name" title="${_esc(name)}">${_esc(name)}</span>
          <span class="chip mono">${_esc(ch.type || 'unknown')}</span>
        </header>
        <div class="ch-card__status">
          <span class="chip ${chipCls}">${_esc(status)}</span>
        </div>
        <dl class="ch-card__meta">
          <div><dt>Connected</dt><dd class="ch-mono">${_esc(since)}</dd></div>
          <div><dt>Restart attempts</dt><dd class="ch-mono">${_esc(attempts)}</dd></div>
        </dl>
        <details class="ch-card__config">
          <summary>Adapter config</summary>
          <pre class="ch-card__config-pre">${_esc(configJson)}</pre>
        </details>
        <footer class="ch-card__footnote">
          <span>${_esc(_statusHint({ status, isRunning, isDead, enabled: ch.enabled !== false, name }))}</span>
        </footer>
      </article>`;
    }).join('');
  }

  function _statusHint({ status, isRunning, isDead, enabled, name }) {
    const safeName = name || '<name>';
    if (!enabled) return `Disabled in config — gateway restart required after re-enabling. Run \`opensquilla configure --section channels\` to change.`;
    if (isDead) return `Adapter is dead. Inspect gateway logs, then \`opensquilla channels restart ${safeName}\`.`;
    if (isRunning) return 'Adapter is live in the current gateway process.';
    if (status === 'restarting') return 'Adapter is restarting after dispatch errors.';
    if (status === 'exhausted') return `Adapter exhausted its retry budget. Try \`opensquilla channels restart ${safeName}\`.`;
    return 'Configured on disk but not active in this gateway process — restart the gateway to load it.';
  }

  function _needsAttention(status) {
    return status === 'dead' || status === 'restarting' || status === 'exhausted';
  }

  function _inactiveHint(inactive, disabled) {
    if (!inactive) return 'no inactive channels';
    if (disabled) return `${disabled} disabled`;
    return 'configured but idle';
  }

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return { render, destroy };
})();

window.ChannelsView = ChannelsView;
