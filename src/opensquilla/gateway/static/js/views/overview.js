/** OpenSquilla Web UI — Overview view (FE-003). */

const OverviewView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];
  let _eventLog = [];
  let _viewGeneration = 0;

  function _ensureCss() {
    if (document.querySelector('link[data-view-css="overview"]')) return;
    const data = document.getElementById('opensquilla-data');
    const base = data?.dataset.basePath || '';
    const cssVersion = data?.dataset.version || '';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${base}/static/css/views/overview.css${cssVersion ? '?v=' + encodeURIComponent(cssVersion) : ''}`;
    link.dataset.viewCss = 'overview';
    document.head.appendChild(link);
  }

  function render(el) {
    _viewGeneration += 1;
    _el = el;
    _rpc = App.getRpc();
    _ensureCss();

    const { url, token } = App.loadConnectionSettings();

    _el.innerHTML = `
      <div class="ov-stage">
        <header class="ov-stage__header">
          <div class="ov-stage__title-block">
            <span class="ov-stage__eyebrow">Control · Overview</span>
            <h2 class="ov-stage__title">OpenSquilla</h2>
            <p class="ov-stage__subtitle">Live status, recent sessions, and the live event stream.</p>
          </div>
          <div class="ov-stage__actions">
            <button class="btn btn--ghost" id="ov-refresh" title="Refresh">
              ${icons.refresh()}<span>Refresh</span>
            </button>
            <button class="btn btn--primary" id="ov-go-chat" title="Open chat">
              ${icons.chat()}<span>Open chat</span>
            </button>
          </div>
        </header>

        <section class="ov-stats">
          <button class="ov-stat ov-stat--accent" data-nav="/usage" type="button">
            <div class="ov-stat__icon">${icons.usage()}</div>
            <div class="ov-stat__label">Total tokens</div>
            <div class="ov-stat__value" id="ov-tokens">${UI.skeleton('120px', '1.6rem')}</div>
            <div class="ov-stat__hint" id="ov-cost-line">—</div>
          </button>
          <button class="ov-stat" data-nav="/sessions" type="button" title="Total sessions across all statuses">
            <div class="ov-stat__icon">${icons.sessions()}</div>
            <div class="ov-stat__label">Total sessions</div>
            <div class="ov-stat__value" id="ov-sessions">${UI.skeleton('80px', '1.6rem')}</div>
            <div class="ov-stat__hint">view all →</div>
          </button>
          <button class="ov-stat" data-nav="/agents" type="button">
            <div class="ov-stat__icon">${icons.agents()}</div>
            <div class="ov-stat__label">Provider</div>
            <div class="ov-stat__value ov-stat__value--mono" id="ov-provider">${UI.skeleton('100px', '1.4rem')}</div>
            <div class="ov-stat__hint">manage agents →</div>
          </button>
          <button class="ov-stat" data-nav="/health" type="button" id="ov-health">
            <div class="ov-stat__icon">${icons.logs()}</div>
            <div class="ov-stat__label">Health</div>
            <div class="ov-stat__value ov-stat__value--status" id="ov-health-status">${UI.skeleton('90px', '1.4rem')}</div>
            <div class="ov-stat__hint" id="ov-health-summary">doctor.status</div>
          </button>
          <div class="ov-stat ov-stat--static">
            <div class="ov-stat__icon">${icons.cron()}</div>
            <div class="ov-stat__label">Uptime</div>
            <div class="ov-stat__value ov-stat__value--mono" id="ov-uptime">${UI.skeleton('120px', '1.6rem')}</div>
            <div class="ov-stat__hint" id="ov-version-line">—</div>
          </div>
        </section>

        <div class="ov-grid">
          <section class="ov-panel ov-panel--span2">
            <div class="ov-panel__head">
              <div>
                <span class="ov-panel__eyebrow">Recent activity</span>
                <h3 class="ov-panel__title">Sessions</h3>
              </div>
              <button class="ov-link" id="ov-sessions-all" type="button">View all →</button>
            </div>
            <div class="ov-recent" id="ov-recent-sessions">${UI.skeleton('100%', '4rem')}</div>
          </section>

          <section class="ov-panel">
            <div class="ov-panel__head">
              <div>
                <span class="ov-panel__eyebrow">Connection</span>
                <h3 class="ov-panel__title">Gateway</h3>
              </div>
              <span class="conn-pill" id="ov-conn-pill">—</span>
            </div>
            <div class="ov-form">
              <label class="ov-field">
                <span class="ov-field__label">WebSocket URL</span>
                <input id="ov-ws-url" class="ov-field__input ov-field__input--mono" type="text" placeholder="ws://…" value="${_esc(url)}" autocomplete="off" />
              </label>
              <label class="ov-field">
                <span class="ov-field__label">Token <span class="ov-field__optional">optional</span></span>
                <input id="ov-ws-token" class="ov-field__input" type="password" placeholder="—" value="${_esc(token)}" autocomplete="off" />
              </label>
              <div class="ov-form__actions">
                <button class="btn btn--primary btn--sm" id="ov-connect">Connect</button>
                <button class="btn btn--ghost btn--sm" id="ov-disconnect">Disconnect</button>
              </div>
            </div>
          </section>

          <section class="ov-panel ov-panel--span3">
            <div class="ov-panel__head">
              <div>
                <span class="ov-panel__eyebrow">Live</span>
                <h3 class="ov-panel__title">Event stream</h3>
              </div>
              <span class="ov-panel__meta" id="ov-event-count">0 events</span>
            </div>
            <div class="ov-event-log" id="ov-event-log">
              <div class="ov-event-log__empty">
                <span class="ov-event-log__pulse"></span>
                Listening for events…
              </div>
            </div>
          </section>
        </div>
      </div>`;

    // Stat card navigation
    _el.querySelectorAll('.ov-stat[data-nav]').forEach(card => {
      card.addEventListener('click', () => Router.navigate(card.dataset.nav));
    });

    // Buttons
    _el.querySelector('#ov-refresh').addEventListener('click', _loadData);
    _el.querySelector('#ov-go-chat').addEventListener('click', () => Router.navigate('/chat'));
    _el.querySelector('#ov-sessions-all').addEventListener('click', () => Router.navigate('/sessions'));

    // Connection buttons
    _el.querySelector('#ov-connect').addEventListener('click', () => {
      const wsUrl = _el.querySelector('#ov-ws-url').value.trim();
      const wsToken = _el.querySelector('#ov-ws-token').value.trim();
      App.saveConnectionSettings(wsUrl, wsToken);
      _rpc.disconnect();
      _rpc.connect(wsUrl, wsToken || undefined);
    });
    _el.querySelector('#ov-disconnect').addEventListener('click', () => {
      _rpc.disconnect();
    });

    _updateConnectionPill();
    const onState = () => _updateConnectionPill();
    if (_rpc.on) {
      const u = _rpc.on('rpc.state', onState);
      if (typeof u === 'function') _unsubs.push(u);
    }

    // Subscribe to wildcard events for event log
    const unsubEvents = _rpc.on('*', (eventName, payload) => {
      _pushEvent(eventName, payload);
    });
    _unsubs.push(unsubEvents);

    _loadData();

    const id = setInterval(_loadData, 30000);
    _intervals.push(id);

    // Update connection pill on a slow tick (cheap; updates if state flips)
    const idPill = setInterval(_updateConnectionPill, 2000);
    _intervals.push(idPill);
  }

  function destroy() {
    _viewGeneration += 1;
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    _eventLog = [];
    _el = null;
    _rpc = null;
  }

  function _updateConnectionPill() {
    if (!_el) return;
    const pill = _el.querySelector('#ov-conn-pill');
    if (!pill) return;
    let state = 'unknown';
    if (_rpc && typeof _rpc.isConnected === 'function') {
      state = _rpc.isConnected() ? 'connected' : 'disconnected';
    }
    // Mirror the topbar's authoritative conn-pill if available.
    const topbarPill = document.querySelector('.topbar #conn-pill');
    if (topbarPill) {
      if (topbarPill.classList.contains('warn')) state = 'connecting';
      else if (topbarPill.classList.contains('ok')) state = 'connected';
      else if (topbarPill.classList.contains('err')) state = 'disconnected';
    }
    const VARIANT = { connected: 'ok', connecting: 'warn', disconnected: 'err' };
    pill.className = `conn-pill ${VARIANT[state] || ''}`.trim();
    pill.textContent = state;
  }

  async function _loadData() {
    const root = _el;
    const generation = _viewGeneration;
    if (!root) return;
    const rpc = _rpc;
    if (!rpc) return;
    await rpc.waitForConnection();
    if (!_isCurrentView(root, rpc, generation)) return;

    const set = (id, val) => {
      if (!_isCurrentView(root, rpc, generation)) return;
      const el = root.querySelector('#' + id);
      if (el) el.innerHTML = val != null ? String(val) : '—';
    };
    const setText = (id, val) => {
      if (!_isCurrentView(root, rpc, generation)) return;
      const el = root.querySelector('#' + id);
      if (el) el.textContent = val != null ? String(val) : '—';
    };

    rpc.call('status').then(data => {
      if (!_isCurrentView(root, rpc, generation)) return;
      const ms = data.uptime_ms;
      if (ms != null) {
        const s = Math.floor(ms / 1000);
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        set('ov-uptime', `${h}h ${m}m ${s % 60}s`);
      } else {
        set('ov-uptime', '—');
      }
      setText('ov-version-line', data.version ? `v${data.version}` : '—');
      set('ov-provider', _esc(data.provider ?? '—'));
    }).catch(err => {
      if (!_isCurrentView(root, rpc, generation)) return;
      UI.toast('Failed to load status: ' + err.message, 'err');
    });

    rpc.call('doctor.status', { agentId: 'main', deep: false }).then(report => {
      if (!_isCurrentView(root, rpc, generation)) return;
      set('ov-health-status', _esc(_readinessStatusLabel(report.status ?? 'unknown')));
      setText('ov-health-summary', report.summary ?? 'view details');
    }).catch(() => {
      if (!_isCurrentView(root, rpc, generation)) return;
      set('ov-health-status', 'unavailable');
      setText('ov-health-summary', 'open health');
    });

    rpc.call('usage.status').then(data => {
      if (!_isCurrentView(root, rpc, generation)) return;
      const cur = localStorage.getItem('opensquilla-currency') || 'USD';
      set('ov-sessions', data.totalSessions ?? '—');
      set('ov-tokens', data.totalTokens != null ? data.totalTokens.toLocaleString() : '—');
      const costLine = root.querySelector('#ov-cost-line');
      if (costLine) {
        if (data.totalCostUsd != null) {
          // CNY rate sourced from SquillaConstants — kept in sync across
          // overview, usage, and token-widget. Disclosed as baked-in.
          const cnyRate = (window.SquillaConstants && window.SquillaConstants.CNY_RATE) || 7.25;
          const usd = '$' + Number(data.totalCostUsd).toFixed(4);
          const cny = '¥' + (Number(data.totalCostUsd) * cnyRate).toFixed(4);
          costLine.textContent = cur === 'CNY' ? `${cny} · ${usd}` : `${usd} · ${cny}`;
          costLine.title = `CNY value uses baked-in rate ${cnyRate} (see SquillaConstants).`;
        } else {
          costLine.textContent = '—';
        }
      }
    }).catch(() => {});

    rpc.call('sessions.list', { limit: 5 }).then(data => {
      if (!_isCurrentView(root, rpc, generation)) return;
      const sessions = (data.sessions || [])
        .slice()
        .sort((a, b) => {
          const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0;
          const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0;
          return tb - ta;
        })
        .slice(0, 6);
      const container = root.querySelector('#ov-recent-sessions');
      if (!container) return;
      if (sessions.length === 0) {
        container.innerHTML = `<div class="ov-recent__empty">
          <div class="ov-recent__empty-icon">${icons.sessions()}</div>
          <div>No sessions yet — open chat to start your first one.</div>
        </div>`;
        return;
      }
      container.innerHTML = sessions.map(s => {
        const rel = s.updated_at ? UI.relTime(s.updated_at) : '—';
        const status = (s.status || 'unknown').toLowerCase();
        const dotCls = UI.sessionStatusClass(status);
        const statusTip = UI.sessionStatusLabel(status);
        const msgs = s.message_count != null ? `${Number(s.message_count).toLocaleString()} msg` : '';
        const model = s.model ? `<span class="ov-recent__model">${_esc(s.model)}</span>` : '';
        return `<button class="ov-recent__row" data-key="${_esc(s.key)}" type="button">
          <span class="dot ${dotCls}" aria-label="${_esc(statusTip)}" title="${_esc(statusTip)}"></span>
          <span class="ov-recent__key">${_esc(s.key)}</span>
          ${model}
          <span class="ov-recent__msgs">${msgs}</span>
          <span class="ov-recent__time">${_esc(rel)}</span>
          <span class="ov-recent__arrow">→</span>
        </button>`;
      }).join('');
      container.querySelectorAll('[data-key]').forEach(b => {
        b.addEventListener('click', () => Router.navigate('/chat?session=' + encodeURIComponent(b.dataset.key)));
      });
    }).catch(() => {});
  }

  function _isCurrentView(root, rpc, generation) {
    return _el === root && _rpc === rpc && _viewGeneration === generation;
  }

  function _pushEvent(eventName, payload) {
    const now = new Date();
    const ts = now.toTimeString().slice(0, 8);
    let payloadStr = '';
    try {
      payloadStr = JSON.stringify(payload);
      if (payloadStr.length > 80) payloadStr = payloadStr.slice(0, 80) + '…';
    } catch {
      payloadStr = String(payload);
    }
    _eventLog.unshift({ ts, eventName, payloadStr });
    if (_eventLog.length > 30) _eventLog.length = 30;
    _renderEventLog();
  }

  function _renderEventLog() {
    const container = _el && _el.querySelector('#ov-event-log');
    const counter = _el && _el.querySelector('#ov-event-count');
    if (!container) return;
    if (counter) counter.textContent = `${_eventLog.length} event${_eventLog.length === 1 ? '' : 's'}`;
    if (_eventLog.length === 0) {
      container.innerHTML = `<div class="ov-event-log__empty">
        <span class="ov-event-log__pulse"></span>
        Listening for events…
      </div>`;
      return;
    }
    container.innerHTML = _eventLog.map((e, i) => `
      <div class="ov-event-log__row${i === 0 ? ' is-fresh' : ''}">
        <span class="ov-event-log__ts">${_esc(e.ts)}</span>
        <span class="ov-event-log__name">${_esc(e.eventName)}</span>
        <span class="ov-event-log__payload">${_esc(e.payloadStr)}</span>
      </div>`).join('');
  }

  function _readinessStatusLabel(status) {
    const labels = {
      ready: 'Ready',
      degraded: 'Degraded',
      action_required: 'Action required',
      unavailable: 'Unavailable',
      unknown: 'Unknown',
    };
    const key = String(status || 'unknown').toLowerCase();
    if (labels[key]) return labels[key];
    return key
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
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

window.OverviewView = OverviewView;
