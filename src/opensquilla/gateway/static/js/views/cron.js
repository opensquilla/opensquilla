/** OpenSquilla Web UI — Cron jobs view (FE-004). */

const CronView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];
  let _jobs = [];
  let _selectedId = null;
  let _searchText = '';
  let _panelOpen = false;
  let _editingJob = null; // null = new, object = existing
  let _viewMode = 'cards'; // 'cards' | 'table'
  let _previewTimer = null;
  let _reloadTimer = null;

  // Sort state
  let _sortCol = 'next_run';
  let _sortAsc = true;

  // ---- render / destroy ------------------------------------------------

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _el.innerHTML = `
      <div class="cron-stage">
        <header class="cron-stage__header">
          <div class="cron-stage__title-block">
            <span class="cron-stage__eyebrow">Control · Schedule</span>
            <h2 class="cron-stage__title">Cron Jobs</h2>
            <p class="cron-stage__subtitle">Time-driven tasks — orchestrate reminders, agent turns, and recurring work.</p>
          </div>
          <div class="cron-stage__actions">
            <div class="cron-search-wrap">
              <span class="cron-search-icon">${icons.search()}</span>
              <input class="cron-search-input" id="cron-search" type="search" placeholder="Search jobs…" autocomplete="off">
            </div>
            <button class="btn btn--ghost" id="cron-refresh" title="Refresh">
              ${icons.refresh()}<span>Refresh</span>
            </button>
            <button class="btn btn--primary" id="cron-add">
              ${icons.plus()}<span>New job</span>
            </button>
          </div>
        </header>

        <section class="cron-summary" id="cron-summary"></section>

        <section class="cron-horizon" id="cron-horizon" hidden>
          <div class="cron-horizon__head">
            <span class="cron-horizon__title">Next 12 hours</span>
            <span class="cron-horizon__legend"><span class="cron-horizon__dot"></span>upcoming run</span>
          </div>
          <div class="cron-horizon__rail" id="cron-horizon-rail"></div>
          <div class="cron-horizon__axis" id="cron-horizon-axis"></div>
        </section>

        <section class="cron-jobs">
          <div class="cron-jobs__head">
            <h3 class="cron-jobs__title" id="cron-jobs-title">All schedules</h3>
            <div class="cron-view-toggle" role="group" aria-label="View mode">
              <button class="cron-view-toggle__btn is-active" data-view="cards" aria-pressed="true">Cards</button>
              <button class="cron-view-toggle__btn" data-view="table" aria-pressed="false">Table</button>
            </div>
          </div>
          <div id="cron-content"></div>
        </section>
      </div>

      <!-- slide-in edit/add panel -->
      <div id="cron-panel" class="cron-panel" hidden>
        <div class="cron-panel__head">
          <div>
            <span class="cron-panel__eyebrow" id="cron-panel-eyebrow">Schedule</span>
            <h3 class="cron-panel__title" id="cron-panel-title">New Job</h3>
          </div>
          <button class="cron-iconbtn" id="cron-panel-close" aria-label="Close">${icons.x()}</button>
        </div>
        <div class="cron-panel__body">
          <div class="cron-field">
            <label class="cron-field__label" for="cp-name">Name</label>
            <input class="cron-field__input" id="cp-name" type="text" placeholder="my-job" autocomplete="off">
          </div>

          <div class="cron-field">
            <label class="cron-field__label" for="cp-type">Schedule type</label>
            <select class="cron-field__input" id="cp-type">
              <option value="cron">Cron expression</option>
              <option value="every">Fixed interval</option>
              <option value="at">One-time ISO time</option>
            </select>
          </div>

          <div class="cron-field" id="cp-cron-row">
            <label class="cron-field__label" for="cp-cron">Cron expression</label>
            <input class="cron-field__input cron-field__input--mono" id="cp-cron" type="text" placeholder="0 9 * * 1-5" autocomplete="off" spellcheck="false">
            <div class="cron-explain" id="cp-explain">
              <div class="cron-explain__human" id="cp-explain-human">Enter a 5-field cron expression to preview</div>
              <div class="cron-explain__hint" id="cp-explain-hint">e.g. <code>*/15 * * * *</code>, <code>0 9 * * 1-5</code>, <code>0 0 1 * *</code></div>
              <ul class="cron-explain__upcoming" id="cp-explain-upcoming" hidden></ul>
            </div>
            <div class="cron-presets" id="cp-presets">
              <span class="cron-presets__label">Presets:</span>
              <button type="button" class="cron-preset" data-cron="*/5 * * * *">Every 5m</button>
              <button type="button" class="cron-preset" data-cron="0 * * * *">Hourly</button>
              <button type="button" class="cron-preset" data-cron="0 9 * * 1-5">Weekdays 09:00</button>
              <button type="button" class="cron-preset" data-cron="0 0 * * 0">Sundays midnight</button>
            </div>
          </div>

          <div class="cron-field" id="cp-every-row" hidden>
            <label class="cron-field__label" for="cp-every">Interval (seconds)</label>
            <input class="cron-field__input" id="cp-every" type="number" min="1" placeholder="60">
          </div>

          <div class="cron-field" id="cp-at-row" hidden>
            <label class="cron-field__label" for="cp-at">ISO time</label>
            <input class="cron-field__input cron-field__input--mono" id="cp-at" type="text" placeholder="2026-05-18T09:00:00+08:00">
          </div>

          <div class="cron-field" id="cp-tz-row">
            <label class="cron-field__label" for="cp-tz">Timezone (IANA)</label>
            <input class="cron-field__input cron-field__input--mono" id="cp-tz" type="text" placeholder="America/Los_Angeles" autocomplete="off" spellcheck="false">
            <div class="cron-field__hint">Leave empty to evaluate the cron expression in UTC. Example: <code>Asia/Shanghai</code>, <code>Europe/London</code>.</div>
          </div>

          <div class="cron-field">
            <label class="cron-field__label" for="cp-payload-kind">Job mode</label>
            <select class="cron-field__input" id="cp-payload-kind">
              <option value="reminder">Static Reminder (no model)</option>
              <option value="agent_turn">Background Agent Task (choose session)</option>
              <option value="system_event">System Event (Main)</option>
            </select>
            <div class="cron-field__hint" id="cp-job-mode-hint">Static reminders deliver text directly. Agent tasks run the model in current, isolated, or named sessions.</div>
          </div>

          <div class="cron-field">
            <label class="cron-field__label" for="cp-agent-id">Agent ID</label>
            <input class="cron-field__input" id="cp-agent-id" type="text" placeholder="main">
          </div>

          <div class="cron-field" id="cp-session-target-row">
            <label class="cron-field__label" for="cp-session-target">Session target</label>
            <select class="cron-field__input" id="cp-session-target">
              <option value="main">Agent main session</option>
              <option value="current">Current chat session</option>
              <option value="isolated">Isolated cron session</option>
              <option value="session">Named session</option>
            </select>
            <div class="cron-field__hint" id="cp-session-target-hint">Choose where this scheduled run keeps its conversation context.</div>
          </div>

          <div class="cron-field" id="cp-target-session-row" hidden>
            <label class="cron-field__label" for="cp-target-session-key">Named session key</label>
            <input class="cron-field__input" id="cp-target-session-key" type="text" placeholder="agent:main:webchat:abc123">
            <div class="cron-field__hint" id="cp-target-session-hint">Use a full session key from the chat header.</div>
          </div>

          <div class="cron-field">
            <label class="cron-field__label" for="cp-message" id="cp-message-label">Message / Prompt</label>
            <textarea class="cron-field__input cron-field__input--textarea" id="cp-message" rows="4" placeholder="Run daily report…"></textarea>
          </div>

          <details class="cron-advanced" id="cp-advanced">
            <summary class="cron-advanced__summary">Advanced delivery &amp; wake</summary>
            <div class="cron-advanced__body">
              <div class="cron-field">
                <label class="cron-field__label" for="cp-wake-mode">Wake mode</label>
                <select class="cron-field__input" id="cp-wake-mode">
                  <option value="now">Now (fire immediately on schedule)</option>
                  <option value="next-heartbeat">Next heartbeat (defer to main loop)</option>
                </select>
                <div class="cron-field__hint">Use <code>next-heartbeat</code> for main-session jobs that should ride the existing turn queue.</div>
              </div>

              <div class="cron-field">
                <label class="cron-field__label" for="cp-delivery-mode">Delivery mode</label>
                <select class="cron-field__input" id="cp-delivery-mode">
                  <option value="">Default (inferred from session)</option>
                  <option value="none">None (run silently)</option>
                  <option value="announce">Announce to channel</option>
                  <option value="webhook">Post to webhook</option>
                </select>
              </div>

              <div class="cron-field" id="cp-delivery-channel-row" hidden>
                <label class="cron-field__label" for="cp-delivery-channel">Channel</label>
                <input class="cron-field__input" id="cp-delivery-channel" type="text" placeholder="slack" autocomplete="off">
              </div>
              <div class="cron-field" id="cp-delivery-to-row" hidden>
                <label class="cron-field__label" for="cp-delivery-to">Recipient</label>
                <input class="cron-field__input" id="cp-delivery-to" type="text" placeholder="C-team-alerts" autocomplete="off">
              </div>
              <div class="cron-field" id="cp-delivery-account-row" hidden>
                <label class="cron-field__label" for="cp-delivery-account">Account id</label>
                <input class="cron-field__input" id="cp-delivery-account" type="text" placeholder="" autocomplete="off">
              </div>

              <div class="cron-field" id="cp-delivery-webhook-url-row" hidden>
                <label class="cron-field__label" for="cp-delivery-webhook-url">Webhook URL</label>
                <input class="cron-field__input cron-field__input--mono" id="cp-delivery-webhook-url" type="url" placeholder="https://hooks.example/cron" autocomplete="off">
              </div>
              <div class="cron-field" id="cp-delivery-webhook-token-row" hidden>
                <label class="cron-field__label" for="cp-delivery-webhook-token">Webhook bearer token</label>
                <input class="cron-field__input" id="cp-delivery-webhook-token" type="password" placeholder="optional bearer token" autocomplete="off">
              </div>

              <label class="cron-toggle" id="cp-delivery-best-effort-row" hidden>
                <input type="checkbox" id="cp-delivery-best-effort">
                <span class="cron-toggle__track"><span class="cron-toggle__thumb"></span></span>
                <span class="cron-toggle__label">Best-effort delivery (do not fail the job when delivery fails)</span>
              </label>

              <details class="cron-advanced cron-advanced--nested" id="cp-fd-fold">
                <summary class="cron-advanced__summary">Failure destination</summary>
                <div class="cron-advanced__body">
                  <div class="cron-field">
                    <label class="cron-field__label" for="cp-fd-mode">Route failures to</label>
                    <select class="cron-field__input" id="cp-fd-mode">
                      <option value="">Disabled (no separate failure alert)</option>
                      <option value="channel">A channel</option>
                      <option value="webhook">A webhook</option>
                    </select>
                  </div>
                  <div class="cron-field" id="cp-fd-channel-row" hidden>
                    <label class="cron-field__label" for="cp-fd-channel">Channel</label>
                    <input class="cron-field__input" id="cp-fd-channel" type="text" placeholder="slack" autocomplete="off">
                  </div>
                  <div class="cron-field" id="cp-fd-to-row" hidden>
                    <label class="cron-field__label" for="cp-fd-to">Recipient</label>
                    <input class="cron-field__input" id="cp-fd-to" type="text" placeholder="C-ops-alerts" autocomplete="off">
                  </div>
                  <div class="cron-field" id="cp-fd-account-row" hidden>
                    <label class="cron-field__label" for="cp-fd-account">Account id</label>
                    <input class="cron-field__input" id="cp-fd-account" type="text" placeholder="" autocomplete="off">
                  </div>
                  <div class="cron-field" id="cp-fd-webhook-url-row" hidden>
                    <label class="cron-field__label" for="cp-fd-webhook-url">Webhook URL</label>
                    <input class="cron-field__input cron-field__input--mono" id="cp-fd-webhook-url" type="url" placeholder="https://hooks.example/alert" autocomplete="off">
                  </div>
                  <div class="cron-field" id="cp-fd-webhook-token-row" hidden>
                    <label class="cron-field__label" for="cp-fd-webhook-token">Webhook bearer token</label>
                    <input class="cron-field__input" id="cp-fd-webhook-token" type="password" placeholder="optional bearer token" autocomplete="off">
                  </div>
                </div>
              </details>
            </div>
          </details>

          <label class="cron-toggle">
            <input type="checkbox" id="cp-enabled" checked>
            <span class="cron-toggle__track"><span class="cron-toggle__thumb"></span></span>
            <span class="cron-toggle__label">Enabled</span>
          </label>

          <div class="cron-panel__actions">
            <button class="btn btn--primary" id="cp-save">Save schedule</button>
            <button class="btn btn--ghost" id="cp-cancel">Cancel</button>
          </div>
        </div>
      </div>
      <div class="cron-panel__scrim" id="cron-panel-scrim" hidden></div>`;

    _el.querySelector('#cron-refresh').addEventListener('click', _loadData);
    _el.querySelector('#cron-add').addEventListener('click', () => _openPanel(null));
    _el.querySelector('#cron-panel-close').addEventListener('click', _closePanel);
    _el.querySelector('#cron-panel-scrim').addEventListener('click', _closePanel);
    _el.querySelector('#cp-cancel').addEventListener('click', _closePanel);
    _el.querySelector('#cp-save').addEventListener('click', _saveJob);
    _el.querySelector('#cp-type').addEventListener('change', _onTypeChange);
    _el.querySelector('#cp-payload-kind').addEventListener('change', _onTypeChange);
    _el.querySelector('#cp-session-target').addEventListener('change', _onTypeChange);
    _el.querySelector('#cp-cron').addEventListener('input', (e) => _renderCronExplain(e.target.value));
    _el.querySelectorAll('.cron-preset').forEach(btn => {
      btn.addEventListener('click', () => {
        const inp = _el.querySelector('#cp-cron');
        inp.value = btn.dataset.cron;
        _renderCronExplain(btn.dataset.cron);
        inp.focus();
      });
    });
    _el.querySelector('#cp-delivery-mode').addEventListener('change', _onDeliveryModeChange);
    _el.querySelector('#cp-fd-mode').addEventListener('change', _onFailureDestModeChange);
    _el.querySelector('#cron-search').addEventListener('input', (e) => {
      _searchText = e.target.value.toLowerCase();
      _renderTable();
    });
    _el.querySelectorAll('.cron-view-toggle__btn').forEach(btn => {
      btn.addEventListener('click', () => {
        _viewMode = btn.dataset.view;
        _el.querySelectorAll('.cron-view-toggle__btn').forEach(b => {
          const active = b.dataset.view === _viewMode;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        _renderTable();
      });
    });

    _loadData();

    // 1Hz tick: live countdowns + horizon position
    _intervals.push(setInterval(_tick, 1000));

    // Subscribe to cron events for real-time updates. Wait for the WS
    // handshake first; calling before connection rejects with "Not connected"
    // and a bare try/catch can't catch the promise rejection.
    _rpc.waitForConnection()
      .then(() => _rpc.call('cron.subscribe', {}))
      .catch(() => { /* subscription is best-effort */ });

    _unsubs.push(_rpc.on('cron.run.finished', () => {
        _scheduleCronReload();
    }));
  }

  function destroy() {
    // Unsubscribe from cron events (best-effort; ignore disconnected state)
    const rpc = App.getRpc();
    if (rpc) rpc.call('cron.unsubscribe', {}).catch(() => {});

    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    if (_previewTimer) { clearTimeout(_previewTimer); _previewTimer = null; }
    if (_reloadTimer) { clearTimeout(_reloadTimer); _reloadTimer = null; }
    _jobs = [];
    _selectedId = null;
    _panelOpen = false;
    _editingJob = null;
    _el = null;
    _rpc = null;
  }

  // ---- data loading ----------------------------------------------------

  async function _loadData() {
    await _rpc.waitForConnection();
    _rpc.call('cron.list').then(data => {
      _jobs = Array.isArray(data) ? data : (data.jobs || []);
      _renderSummary();
      _renderHorizon();
      _renderTable();
    }).catch(err => UI.toast('Failed to load cron jobs: ' + err.message, 'err'));
  }

  function _scheduleCronReload() {
    _loadData();
    if (_reloadTimer) clearTimeout(_reloadTimer);
    _reloadTimer = setTimeout(_loadData, 750);
  }

  function _isUpcomingRun(j, now = Date.now()) {
    if (!j || !j.enabled || !j.next_run) return false;
    if (j.status === 'running') return false;
    const ts = new Date(j.next_run);
    return !isNaN(ts) && ts.getTime() > now;
  }

  function _nextRunText(j) {
    if (!j || !j.enabled) return '—';
    if (j.status === 'running') return 'running';
    if (!j.next_run) return '—';
    const ts = new Date(j.next_run);
    if (isNaN(ts)) return '—';
    if (ts.getTime() <= Date.now()) return 'awaiting update';
    return _humanCountdown(ts);
  }

  function _nextRunAbs(j) {
    if (!j || !j.enabled || j.status === 'running' || !j.next_run) return '';
    const ts = new Date(j.next_run);
    if (isNaN(ts) || ts.getTime() <= Date.now()) return '';
    return _humanTime(ts);
  }

  // ---- summary stats ---------------------------------------------------

  function _renderSummary() {
    const bar = _el && _el.querySelector('#cron-summary');
    if (!bar) return;
    const total = _jobs.length;
    const enabled = _jobs.filter(j => j.enabled).length;
    const paused = total - enabled;
    const reminders = _jobs.filter(j => (j.payloadKind || j.payload_kind) === 'reminder').length;
    const agentTasks = _jobs.filter(j => (j.payloadKind || j.payload_kind) === 'agent_turn').length;

    const next = _jobs
      .filter(j => _isUpcomingRun(j))
      .map(j => ({ job: j, ts: new Date(j.next_run) }))
      .sort((a, b) => a.ts - b.ts)[0];

    // Last 24h aggregate from in-memory job snapshots is best-effort —
    // we surface the latest per-job last_run / status if exposed.
    const last24h = _jobs.reduce((acc, j) => {
      const ts = j.last_run ? new Date(j.last_run) : null;
      if (ts && !isNaN(ts) && Date.now() - ts.getTime() < 24 * 3600 * 1000) {
        acc.runs += 1;
        if (j.last_status === 'ok' || j.last_status === 'success') acc.ok += 1;
        if (j.last_status === 'error' || j.last_status === 'fail') acc.err += 1;
      }
      return acc;
    }, { runs: 0, ok: 0, err: 0 });

    bar.innerHTML = `
      <div class="stat stat--hero">
        <div class="stat-label">Active schedules</div>
        <div class="stat-value">${enabled}<span class="stat-total"> / ${total}</span></div>
        <div class="stat-hint">${paused ? `${paused} paused` : 'all enabled'}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Next run</div>
        <div class="stat-value mono" id="cron-next-countdown">${next ? _humanCountdown(next.ts) : '—'}</div>
        <div class="stat-hint" id="cron-next-name">${next ? _esc(next.job.name || next.job.id) + ' · ' + _humanTime(next.ts) : 'no upcoming runs'}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Last 24h runs</div>
        <div class="stat-value">${last24h.runs}</div>
        <div class="stat-hint">${last24h.ok ? `<span class="cron-pos">${last24h.ok} ok</span>` : ''}${last24h.ok && last24h.err ? ' · ' : ''}${last24h.err ? `<span class="cron-neg">${last24h.err} fail</span>` : ''}${!last24h.ok && !last24h.err ? 'awaiting first run' : ''}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Mix</div>
        <div class="stat-value">
          <span title="Reminders"><span class="stat__chip stat__chip--info">${reminders}</span></span>
          <span>/</span>
          <span title="Agent tasks"><span class="stat__chip stat__chip--accent">${agentTasks}</span></span>
        </div>
        <div class="stat-hint">reminders · agent tasks</div>
      </div>`;
  }

  function _tick() {
    if (!_el) return;
    const next = _jobs
      .filter(j => _isUpcomingRun(j))
      .map(j => ({ job: j, ts: new Date(j.next_run) }))
      .sort((a, b) => a.ts - b.ts)[0];

    const cd = _el.querySelector('#cron-next-countdown');
    if (cd) cd.textContent = next ? _humanCountdown(next.ts) : '—';

    // Mark imminent rows (<60s) with a pulsing glow.
    const now = Date.now();
    _el.querySelectorAll('[data-imminent-id]').forEach(node => {
      const id = node.dataset.imminentId;
      const j = _jobs.find(x => x.id === id);
      if (!j || !j.next_run) { node.classList.remove('is-imminent'); return; }
      const left = new Date(j.next_run).getTime() - now;
      node.classList.toggle('is-imminent', left > 0 && left < 60_000);
    });

    // Update horizon marker positions live so they drift left over time.
    _updateHorizonPositions();
  }

  // ---- horizon ribbon (next 12h) ---------------------------------------

  function _renderHorizon() {
    const root = _el && _el.querySelector('#cron-horizon');
    const rail = _el && _el.querySelector('#cron-horizon-rail');
    const axis = _el && _el.querySelector('#cron-horizon-axis');
    if (!root || !rail || !axis) return;

    const upcoming = _jobs
      .filter(j => _isUpcomingRun(j))
      .map(j => ({ job: j, ts: new Date(j.next_run).getTime() }))
      .filter(o => o.ts > Date.now() && (o.ts - Date.now()) < 12 * 3600 * 1000);

    if (upcoming.length === 0) {
      root.hidden = true;
      return;
    }
    root.hidden = false;

    rail.innerHTML = upcoming.map((o, i) => {
      const safeId = _esc(o.job.id);
      const safeName = _esc(o.job.name || o.job.id);
      return `<button class="cron-horizon__marker" data-cron-marker="${safeId}" data-ts="${o.ts}" style="--i:${i}">
        <span class="cron-horizon__marker-dot"></span>
        <span class="cron-horizon__marker-tip">
          <strong>${safeName}</strong>
          <em data-cron-marker-ts="${o.ts}">${_humanCountdown(new Date(o.ts))}</em>
        </span>
      </button>`;
    }).join('');

    // Hour ticks: now, +3h, +6h, +9h, +12h
    const start = Date.now();
    axis.innerHTML = [0, 3, 6, 9, 12].map(h => {
      const ts = start + h * 3600 * 1000;
      const d = new Date(ts);
      const label = h === 0 ? 'now' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const pct = (h / 12) * 100;
      return `<span class="cron-horizon__tick" style="left:${pct}%"><span class="cron-horizon__tick-line"></span><span class="cron-horizon__tick-label">${label}</span></span>`;
    }).join('');

    rail.querySelectorAll('[data-cron-marker]').forEach(b => {
      b.addEventListener('click', () => {
        _selectedId = b.dataset.cronMarker;
        _renderTable();
        const card = _el.querySelector(`[data-cron-row="${b.dataset.cronMarker}"]`);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });

    _updateHorizonPositions();
  }

  function _updateHorizonPositions() {
    const rail = _el && _el.querySelector('#cron-horizon-rail');
    if (!rail) return;
    const now = Date.now();
    const span = 12 * 3600 * 1000;
    let visible = 0;
    rail.querySelectorAll('[data-cron-marker]').forEach(node => {
      const ts = Number(node.dataset.ts);
      const left = ((ts - now) / span) * 100;
      if (left < 0 || left > 101) {
        node.style.display = 'none';
      } else {
        node.style.display = '';
        node.style.left = Math.max(0, Math.min(100, left)) + '%';
        visible += 1;
      }
      const tipTs = node.querySelector('[data-cron-marker-ts]');
      if (tipTs) tipTs.textContent = _humanCountdown(new Date(ts));
    });
    const root = _el && _el.querySelector('#cron-horizon');
    if (root && visible === 0 && rail.children.length > 0) {
      // All upcoming runs slipped into the past → re-render to recompute upcoming list.
      _renderHorizon();
    }
  }

  // ---- sort ------------------------------------------------------------

  function _sortData(list) {
    return [...list].sort((a, b) => {
      let va = a[_sortCol] ?? '';
      let vb = b[_sortCol] ?? '';
      if (_sortCol === 'next_run' || _sortCol === 'last_run') {
        va = va ? new Date(va).getTime() : (_sortAsc ? Infinity : -Infinity);
        vb = vb ? new Date(vb).getTime() : (_sortAsc ? Infinity : -Infinity);
      } else {
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
      }
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return _sortAsc ? cmp : -cmp;
    });
  }

  // ---- jobs list (cards or table) -------------------------------------

  function _renderTable() {
    const content = _el && _el.querySelector('#cron-content');
    const titleEl = _el && _el.querySelector('#cron-jobs-title');
    if (!content) return;

    const filtered = _jobs.filter(j => {
      if (!_searchText) return true;
      return (j.name || '').toLowerCase().includes(_searchText) ||
        (j.message || j.prompt || '').toLowerCase().includes(_searchText) ||
        (j.payloadKind || '').toLowerCase().includes(_searchText) ||
        ((j.sessionTarget || j.session_target || '') + '').toLowerCase().includes(_searchText) ||
        (j.expression || j.schedule || '').toLowerCase().includes(_searchText);
    });
    const sorted = _sortData(filtered);

    if (titleEl) {
      const count = sorted.length;
      const totalCount = _jobs.length;
      titleEl.innerHTML = _searchText
        ? `Matching schedules <span class="cron-jobs__count">${count} of ${totalCount}</span>`
        : `All schedules <span class="cron-jobs__count">${count}</span>`;
    }

    if (sorted.length === 0) {
      content.innerHTML = _emptyStateHtml(_jobs.length === 0);
      _bindEmptyState(content);
      return;
    }

    if (_viewMode === 'table') {
      content.innerHTML = `<div class="cron-table-wrap">${_tableHtml(sorted)}</div>`;
    } else {
      content.innerHTML = `<div class="cron-card-grid">${sorted.map((j, i) => _cardHtml(j, i)).join('')}</div>`;
    }

    if (_selectedId) {
      const job = _jobs.find(j => j.id === _selectedId);
      if (job) _appendDetailPanel(content, job);
    }

    _bindRowEvents(content);
  }

  function _jobKindLabel(job) {
    const kind = job.payloadKind || job.payload_kind;
    if (kind === 'reminder') return 'Reminder';
    if (kind === 'system_event') return 'System event';
    return 'Agent task';
  }

  function _jobKindClass(job) {
    const kind = job.payloadKind || job.payload_kind;
    return kind === 'reminder' ? 'is-reminder' : 'is-agent';
  }

  function _cardHtml(j, i) {
    const enabled = !!j.enabled;
    const lastStatus = j.last_status || (j.last_run ? 'ok' : null);
    const lastRun = j.last_run ? _humanCountdownPast(new Date(j.last_run)) : '—';
    const nextRun = _nextRunText(j);
    const nextAbs = _nextRunAbs(j);
    const schedule = _esc(j.expression || j.schedule || '—');
    const human = _explainCron(j.expression || '') || '';
    const kind = _jobKindLabel(j);
    const kindClass = _jobKindClass(j);
    const target = j.sessionTarget || j.session_target || '—';
    const selected = _selectedId === j.id ? ' is-selected' : '';
    const dotClass = !enabled ? 'is-off' : (lastStatus === 'error' || lastStatus === 'fail') ? 'is-error' : 'is-on';
    const message = (j.message || j.prompt || '').trim();
    return `
      <article class="cron-card${selected}" data-cron-row="${_esc(j.id)}" data-imminent-id="${_esc(j.id)}" style="--stagger:${i}">
        <header class="cron-card__head">
          <span class="cron-card__dot ${dotClass}"></span>
          <button type="button" class="cron-card__name" data-cron-open="${_esc(j.id)}" title="Show run history">${_esc(j.name || j.id)}</button>
          <span class="cron-pill cron-pill--${kindClass}">${kind}</span>
        </header>
        <div class="cron-card__schedule">
          <code class="cron-expr">${schedule}</code>
          ${human ? `<span class="cron-card__human">${_esc(human)}</span>` : ''}
        </div>
        <dl class="cron-card__meta">
          <div><dt>Target</dt><dd>${_esc(target)}</dd></div>
          <div><dt>Last run</dt><dd>${lastRun}${lastStatus ? ` · <span class="status status--${lastStatus === 'ok' || lastStatus === 'success' ? 'ok' : 'err'}">${_esc(lastStatus)}</span>` : ''}</dd></div>
          <div><dt>Next run</dt><dd>${enabled ? `<span class="cron-mono">${nextRun}</span>${nextAbs ? `<span class="cron-card__abs"> · ${nextAbs}</span>` : ''}` : '<span class="cron-muted">paused</span>'}</dd></div>
          ${message ? `<div class="cron-card__message"><dt>Prompt</dt><dd>${_esc(message.length > 140 ? message.slice(0, 140) + '…' : message)}</dd></div>` : ''}
        </dl>
        <footer class="cron-card__actions">
          <button class="cron-iconbtn cron-iconbtn--accent" data-cron-run="${_esc(j.id)}" title="Run now" aria-label="Run ${_esc(j.name || j.id)} now">${icons.send()}<span>Run</span></button>
          <button class="cron-iconbtn" data-cron-toggle="${_esc(j.id)}" title="${enabled ? 'Pause' : 'Resume'}" aria-label="${enabled ? 'Pause' : 'Resume'} ${_esc(j.name || j.id)}">${enabled ? icons.stop() : icons.send()}<span>${enabled ? 'Pause' : 'Resume'}</span></button>
          <button class="cron-iconbtn" data-cron-edit="${_esc(j.id)}" title="Edit" aria-label="Edit ${_esc(j.name || j.id)}">${icons.edit()}<span>Edit</span></button>
          <button class="cron-iconbtn cron-iconbtn--danger" data-cron-delete="${_esc(j.id)}" title="Delete" aria-label="Delete ${_esc(j.name || j.id)}">${icons.trash()}</button>
        </footer>
      </article>`;
  }

  function _tableHtml(sorted) {
    const cols = [
      { key: 'name', label: 'Name' },
      { key: 'payloadKind', label: 'Kind' },
      { key: 'sessionTarget', label: 'Target' },
      { key: 'expression', label: 'Schedule' },
      { key: 'enabled', label: 'Status' },
      { key: 'last_run', label: 'Last Run' },
      { key: 'next_run', label: 'Next Run' },
      { key: '_actions', label: '' },
    ];
    const sortable = ['name', 'payloadKind', 'sessionTarget', 'expression', 'last_run', 'next_run'];

    let html = '<table class="cron-table"><thead><tr>';
    cols.forEach(col => {
      if (sortable.includes(col.key)) {
        const arrow = _sortCol === col.key ? (_sortAsc ? ' ▲' : ' ▼') : '';
        const ariaSort = _sortCol === col.key ? (_sortAsc ? 'ascending' : 'descending') : 'none';
        html += `<th class="cron-th-sort" aria-sort="${ariaSort}"><button type="button" class="cron-th-sort__btn" data-sort="${col.key}">${col.label}<span class="cron-table__arrow" aria-hidden="true">${arrow}</span></button></th>`;
      } else {
        html += `<th>${col.label}</th>`;
      }
    });
    html += '</tr></thead><tbody>';

    sorted.forEach(j => {
      const enabled = !!j.enabled;
      const lastStatus = j.last_status;
      const lastRun = j.last_run ? _humanCountdownPast(new Date(j.last_run)) : '—';
      const nextRun = _nextRunText(j);
      const schedule = _esc(j.expression || j.schedule || '—');
      const kind = _jobKindLabel(j);
      const kindClass = _jobKindClass(j);
      const target = j.sessionTarget || j.session_target || '—';
      const dotClass = !enabled ? 'is-off' : (lastStatus === 'error' || lastStatus === 'fail') ? 'is-error' : 'is-on';
      const sel = _selectedId === j.id ? ' is-selected' : '';
      html += `<tr class="cron-tr${sel}" data-cron-row="${_esc(j.id)}" data-imminent-id="${_esc(j.id)}">
        <td><span class="cron-card__dot ${dotClass}"></span><button class="cron-link" data-cron-open="${_esc(j.id)}">${_esc(j.name || j.id)}</button></td>
        <td><span class="cron-pill cron-pill--${kindClass}">${_esc(kind)}</span></td>
        <td>${_esc(target)}</td>
        <td><code class="cron-expr cron-expr--inline">${schedule}</code></td>
        <td>${enabled ? '<span class="status status--ok">enabled</span>' : '<span class="status status--off">paused</span>'}</td>
        <td class="cron-mono">${lastRun}</td>
        <td class="cron-mono">${enabled ? nextRun : '—'}</td>
        <td class="cron-table__actions">
          <button class="cron-iconbtn cron-iconbtn--sm" data-cron-run="${_esc(j.id)}" title="Run now" aria-label="Run ${_esc(j.name || j.id)} now">${icons.send()}</button>
          <button class="cron-iconbtn cron-iconbtn--sm" data-cron-toggle="${_esc(j.id)}" title="${enabled ? 'Pause' : 'Resume'}" aria-label="${enabled ? 'Pause' : 'Resume'} ${_esc(j.name || j.id)}">${enabled ? icons.stop() : icons.send()}</button>
          <button class="cron-iconbtn cron-iconbtn--sm" data-cron-edit="${_esc(j.id)}" title="Edit" aria-label="Edit ${_esc(j.name || j.id)}">${icons.edit()}</button>
          <button class="cron-iconbtn cron-iconbtn--sm cron-iconbtn--danger" data-cron-delete="${_esc(j.id)}" title="Delete" aria-label="Delete ${_esc(j.name || j.id)}">${icons.trash()}</button>
        </td>
      </tr>`;
    });
    html += '</tbody></table>';
    return html;
  }

  function _bindRowEvents(content) {
    content.querySelectorAll('[data-sort]').forEach(btn => {
      btn.addEventListener('click', () => {
        const col = btn.dataset.sort;
        if (_sortCol === col) _sortAsc = !_sortAsc;
        else { _sortCol = col; _sortAsc = true; }
        _renderTable();
      });
    });

    content.querySelectorAll('[data-cron-open]').forEach(node => {
      node.addEventListener('click', (e) => {
        e.preventDefault();
        const id = node.dataset.cronOpen;
        _selectedId = _selectedId === id ? null : id;
        _renderTable();
      });
    });

    content.querySelectorAll('[data-cron-edit]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const job = _jobs.find(j => j.id === btn.dataset.cronEdit);
        if (job) _openPanel(job);
      });
    });

    content.querySelectorAll('[data-cron-toggle]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const job = _jobs.find(j => j.id === btn.dataset.cronToggle);
        if (!job) return;
        _rpc.call('cron.update', { id: job.id, enabled: !job.enabled })
          .then(() => { UI.toast(`Job ${job.enabled ? 'paused' : 'resumed'}`, 'info'); _loadData(); })
          .catch(err => UI.toast('Update failed: ' + err.message, 'err'));
      });
    });

    content.querySelectorAll('[data-cron-run]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.dataset.cronRun;
        const orig = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="cron-spinner"></span><span>Running…</span>`;
        _rpc.call('cron.run', { id })
          .then(res => {
            if (res && res.reply) {
              UI.toast(`Run complete: ${res.reply.substring(0, 120)}`, 'ok');
            } else if (res && res.error) {
              UI.toast(`Run failed: ${res.error}`, 'warn');
            } else {
              UI.toast('Job triggered', 'ok');
            }
          })
          .catch(err => UI.toast('Run failed: ' + err.message, 'err'))
          .finally(() => { btn.disabled = false; btn.innerHTML = orig; });
      });
    });

    content.querySelectorAll('[data-cron-delete]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const job = _jobs.find(j => j.id === btn.dataset.cronDelete);
        if (!job) return;
        UI.modal(
          'Delete schedule',
          `<p>Delete <strong>${_esc(job.name || job.id)}</strong>? This cannot be undone.</p>`,
          [
            {
              label: 'Delete', cls: 'btn--danger', onClick: () => {
                _rpc.call('cron.remove', { id: job.id })
                  .then(() => { UI.toast('Job deleted', 'info'); if (_selectedId === job.id) _selectedId = null; _loadData(); })
                  .catch(err => UI.toast('Delete failed: ' + err.message, 'err'));
              }
            },
            { label: 'Cancel', cls: '' }
          ]
        );
      });
    });
  }

  // ---- empty state ----------------------------------------------------

  function _emptyStateHtml(noJobsAtAll) {
    if (!noJobsAtAll) {
      return `<div class="state">
        <div class="state-icon">${icons.search()}</div>
        <div class="state-title">No matches</div>
        <p class="state-text">No schedules match your search. Try a different query, or clear it to see everything.</p>
      </div>`;
    }
    return `<div class="cron-empty">
      <div class="cron-empty__clock" aria-hidden="true">
        <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <radialGradient id="cg" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="rgba(240,160,48,0.20)"/>
              <stop offset="60%" stop-color="rgba(240,160,48,0.05)"/>
              <stop offset="100%" stop-color="rgba(240,160,48,0)"/>
            </radialGradient>
          </defs>
          <circle cx="60" cy="60" r="58" fill="url(#cg)"/>
          <circle cx="60" cy="60" r="44" fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1"/>
          <circle cx="60" cy="60" r="44" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="2 6" class="cron-empty__ring"/>
          ${[0,30,60,90,120,150,180,210,240,270,300,330].map(deg => {
            const r = deg * Math.PI / 180;
            const x1 = 60 + Math.cos(r) * 40;
            const y1 = 60 + Math.sin(r) * 40;
            const x2 = 60 + Math.cos(r) * (deg % 90 === 0 ? 32 : 36);
            const y2 = 60 + Math.sin(r) * (deg % 90 === 0 ? 32 : 36);
            return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="currentColor" stroke-opacity="${deg % 90 === 0 ? 0.5 : 0.25}" stroke-width="${deg % 90 === 0 ? 1.5 : 1}"/>`;
          }).join('')}
          <line x1="60" y1="60" x2="60" y2="28" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" class="cron-empty__hand"/>
          <line x1="60" y1="60" x2="84" y2="60" stroke="currentColor" stroke-opacity="0.6" stroke-width="2" stroke-linecap="round"/>
          <circle cx="60" cy="60" r="3" fill="var(--accent)"/>
        </svg>
      </div>
      <div class="cron-empty__title">Set the rhythm.</div>
      <p class="cron-empty__msg">No schedules yet. Create your first cron job to wake an agent, fire a reminder,<br/>or kick off recurring work — all on time, all on your terms.</p>
      <button class="btn btn--primary cron-empty__cta" data-cron-empty-create>${icons.plus()}<span>Create your first schedule</span></button>
      <div class="cron-empty__hints">
        <span class="cron-empty__hints-label">Try a preset</span>
        <button class="cron-empty-hint" data-cron-empty-template='{"name":"Daily standup nudge","expression":"0 9 * * 1-5","payloadKind":"reminder","message":"Good morning! Time for standup."}'>
          <code>0 9 * * 1-5</code>
          <span>Weekday morning reminder</span>
        </button>
        <button class="cron-empty-hint" data-cron-empty-template='{"name":"Hourly health check","expression":"0 * * * *","payloadKind":"agent_turn","message":"Run a quick system health check and report any anomalies."}'>
          <code>0 * * * *</code>
          <span>Hourly agent check</span>
        </button>
        <button class="cron-empty-hint" data-cron-empty-template='{"name":"Friday wrap-up","expression":"0 17 * * 5","payloadKind":"agent_turn","message":"Summarize this week’s work and propose next week’s priorities."}'>
          <code>0 17 * * 5</code>
          <span>Friday agent wrap-up</span>
        </button>
      </div>
    </div>`;
  }

  function _bindEmptyState(content) {
    const btn = content.querySelector('[data-cron-empty-create]');
    if (btn) btn.addEventListener('click', () => _openPanel(null));
    content.querySelectorAll('[data-cron-empty-template]').forEach(b => {
      b.addEventListener('click', () => {
        try {
          const tpl = JSON.parse(b.dataset.cronEmptyTemplate);
          _openPanel(null, tpl);
        } catch { _openPanel(null); }
      });
    });
  }

  // ---- detail panel (run history) ------------------------------------

  function _appendDetailPanel(content, job) {
    const panel = document.createElement('div');
    panel.id = 'cron-detail';
    panel.className = 'cron-detail';
    panel.innerHTML = `
      <div class="cron-detail__head">
        <div>
          <span class="cron-detail__eyebrow">Run history</span>
          <strong class="cron-detail__name">${_esc(job.name || job.id)}</strong>
        </div>
        <button class="cron-iconbtn" id="cron-detail-close" aria-label="Close">${icons.x()}</button>
      </div>
      <div id="cron-runs-table" class="cron-detail__runs">${UI.skeleton('100%', '6em')}</div>`;
    content.appendChild(panel);

    panel.querySelector('#cron-detail-close').addEventListener('click', () => {
      _selectedId = null;
      _renderTable();
    });

    _rpc.call('cron.runs', { id: job.id, limit: 10 }).then(data => {
      const runs = Array.isArray(data) ? data : (data.runs || []);
      const table = panel.querySelector('#cron-runs-table');
      if (!table) return;
      if (runs.length === 0) {
        table.innerHTML = '<p class="cron-muted">No run history yet.</p>';
        return;
      }
      table.innerHTML = `
        <table class="cron-runs">
          <thead><tr><th>Time</th><th>Status</th><th>Duration</th><th>Delivery</th><th>Reply</th><th></th></tr></thead>
          <tbody>${runs.map(r => {
            const ds = r.deliveryStatus || r.delivery_status;
            const statusText = (ds && typeof ds === 'object')
              ? `ch: ${ds.channel || '-'}, ws: ${ds.ws || '-'}`
              : (ds || '—');
            const status = r.status || 'unknown';
            const statusCls = status === 'ok' ? 'ok' : 'err';
            return `
            <tr>
              <td class="cron-mono">${r.started_at ? UI.relTime(r.started_at) : '—'}</td>
              <td><span class="status status--${statusCls}">${_esc(status)}</span></td>
              <td class="cron-mono">${r.duration_ms != null ? r.duration_ms + 'ms' : '—'}</td>
              <td>${_esc(statusText)}</td>
              <td class="cron-runs__reply">${r.summary ? _esc(r.summary.substring(0, 120)) : '—'}</td>
              <td>${r.sessionKey ? '<button class="cron-link cron-run-chat-link" data-session="' + _esc(r.sessionKey) + '">→ Chat</button>' : ''}</td>
            </tr>`;
          }).join('')}
          </tbody>
        </table>`;
      table.querySelectorAll('.cron-run-chat-link').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          Router.navigate('/chat?session=' + encodeURIComponent(a.dataset.session));
        });
      });
    }).catch(() => {
      const table = panel.querySelector('#cron-runs-table');
      if (table) table.innerHTML = '<p class="cron-muted">Failed to load run history.</p>';
    });
  }

  // ---- add/edit panel -------------------------------------------------

  function _openPanel(job, template) {
    _editingJob = job;
    _panelOpen = true;
    const panel = _el.querySelector('#cron-panel');
    const scrim = _el.querySelector('#cron-panel-scrim');
    const eyebrow = _el.querySelector('#cron-panel-eyebrow');
    const title = _el.querySelector('#cron-panel-title');
    eyebrow.textContent = job ? 'Edit schedule' : 'New schedule';
    title.textContent = job ? 'Edit Schedule' : 'Create a job';

    const tpl = template || {};
    const name = job ? (job.name || '') : (tpl.name || '');
    const message = job ? (job.message || job.prompt || '') : (tpl.message || '');
    const scheduleKind = job ? (job.scheduleKind || job.schedule_kind || 'cron')
      : (tpl.scheduleKind || tpl.schedule_kind || 'cron');
    const expression = job ? (job.expression || '') : (tpl.expression || '');
    const activeSessionKey = _activeChatSessionKey();
    const payloadKind = job ? (job.payloadKind || 'agent_turn')
      : (tpl.payloadKind || 'reminder');
    const sessionTarget = job ? (job.sessionTarget || job.session_target || 'isolated')
      : (tpl.sessionTarget || (payloadKind === 'system_event' ? 'main' : 'isolated'));
    const targetSessionKey = job ? _jobSessionKey(job) : (tpl.targetSessionKey || activeSessionKey || '');

    _el.querySelector('#cp-name').value = name;
    _el.querySelector('#cp-message').value = message;
    _el.querySelector('#cp-enabled').checked = job ? !!job.enabled : true;
    _el.querySelector('#cp-agent-id').value = job ? (job.agentId || 'main') : (tpl.agentId || 'main');
    _el.querySelector('#cp-payload-kind').value = payloadKind;
    _el.querySelector('#cp-session-target').value = sessionTarget;
    _el.querySelector('#cp-target-session-key').value = targetSessionKey;
    _el.querySelector('#cp-type').value = scheduleKind;
    _el.querySelector('#cp-cron').value = expression;
    _el.querySelector('#cp-every').value = scheduleKind === 'every'
      ? (job ? (job.scheduleRaw || job.schedule_raw || '') : (tpl.every_seconds || ''))
      : '';
    _el.querySelector('#cp-at').value = scheduleKind === 'at'
      ? (job ? (job.scheduleRaw || job.schedule_raw || '') : (tpl.at || ''))
      : '';
    _el.querySelector('#cp-tz').value = job ? (job.tz || '') : (tpl.tz || '');
    _el.querySelector('#cp-wake-mode').value = job ? (job.wakeMode || job.wake_mode || 'now') : (tpl.wakeMode || 'now');
    _populateDeliveryFields(job);
    _onTypeChange();
    _onDeliveryModeChange();
    _onFailureDestModeChange();
    _renderCronExplain(expression);

    panel.hidden = false;
    scrim.hidden = false;
    requestAnimationFrame(() => {
      panel.classList.add('is-open');
      scrim.classList.add('is-open');
    });
    setTimeout(() => _el.querySelector('#cp-name').focus(), 80);
  }

  function _closePanel() {
    _panelOpen = false;
    _editingJob = null;
    const panel = _el && _el.querySelector('#cron-panel');
    const scrim = _el && _el.querySelector('#cron-panel-scrim');
    if (panel) {
      panel.classList.remove('is-open');
      setTimeout(() => { if (panel) panel.hidden = true; }, 220);
    }
    if (scrim) {
      scrim.classList.remove('is-open');
      setTimeout(() => { if (scrim) scrim.hidden = true; }, 220);
    }
  }

  function _onTypeChange() {
    const type = _el.querySelector('#cp-type').value;
    const payloadKind = _el.querySelector('#cp-payload-kind').value;
    const targetSelect = _el.querySelector('#cp-session-target');
    const targetInput = _el.querySelector('#cp-target-session-key');
    const modeHint = _el.querySelector('#cp-job-mode-hint');
    const targetHint = _el.querySelector('#cp-session-target-hint');
    const targetSessionHint = _el.querySelector('#cp-target-session-hint');
    let target = targetSelect.value;
    _el.querySelector('#cp-cron-row').hidden = type !== 'cron';
    _el.querySelector('#cp-every-row').hidden = type !== 'every';
    _el.querySelector('#cp-at-row').hidden = type !== 'at';
    if (payloadKind === 'system_event') {
      targetSelect.value = 'main';
      targetSelect.disabled = true;
      targetSelect.title = 'System events always write to the agent main session.';
      if (modeHint) modeHint.textContent = 'System events append text to the agent main session and wake the heartbeat.';
      if (targetHint) targetHint.textContent = 'Main is locked for system events. Use Static Reminder for direct reminders.';
      if (targetSessionHint) targetSessionHint.textContent = 'Session keys are only used by Static Reminder and Background Agent Task jobs.';
      _el.querySelector('#cp-message-label').textContent = 'Event text';
      _el.querySelector('#cp-target-session-row').hidden = true;
    } else if (payloadKind === 'reminder') {
      targetSelect.value = 'isolated';
      targetSelect.disabled = true;
      targetSelect.title = 'Static reminders deliver text directly without creating a scheduled model turn.';
      if (modeHint) modeHint.textContent = 'Static reminders deliver this message directly; no model call or scheduled agent turn is created.';
      if (targetHint) targetHint.textContent = 'Static reminders run isolated and deliver back to the originating chat when one is available.';
      if (targetSessionHint) targetSessionHint.textContent = 'Origin session is bound automatically from the active chat when saved.';
      _el.querySelector('#cp-message-label').textContent = 'Reminder text';
      _el.querySelector('#cp-target-session-row').hidden = true;
    } else {
      targetSelect.disabled = false;
      targetSelect.title = 'Choose where this background agent task keeps its conversation context.';
      if (modeHint) modeHint.textContent = 'Agent tasks run as scheduled turns and use the selected session target.';
      if (target === 'main') {
        const activeSessionKey = _activeChatSessionKey() || _jobSessionKey(_editingJob);
        target = activeSessionKey ? 'current' : 'isolated';
        targetSelect.value = target;
        if (activeSessionKey && !targetInput.value.trim()) targetInput.value = activeSessionKey;
      }
      if (target === 'current' && !targetInput.value.trim()) {
        targetInput.value = _activeChatSessionKey() || _jobSessionKey(_editingJob);
      }
      _el.querySelector('#cp-message-label').textContent = 'Task prompt';
      _el.querySelector('#cp-target-session-row').hidden = !(target === 'current' || target === 'session');
      const lbl = _el.querySelector('#cp-target-session-row .cron-field__label');
      if (lbl) lbl.textContent = target === 'current' ? 'Current session key' : 'Named session key';
      if (targetHint) {
        targetHint.textContent = target === 'current'
          ? 'The scheduled agent task continues in the active chat session.'
          : target === 'isolated'
            ? 'The scheduled agent task runs in its own cron session, separate from Main.'
            : 'The scheduled agent task continues in the named session key.';
      }
      if (targetSessionHint) {
        targetSessionHint.textContent = target === 'current'
          ? 'Current is bound to the active WebChat session key when the job is saved.'
          : 'Use a full session key from the chat header.';
      }
    }
  }

  function _onDeliveryModeChange() {
    const mode = _el.querySelector('#cp-delivery-mode').value;
    const isAnnounce = mode === 'announce';
    const isWebhook = mode === 'webhook';
    const showAny = isAnnounce || isWebhook;
    _el.querySelector('#cp-delivery-channel-row').hidden = !isAnnounce;
    _el.querySelector('#cp-delivery-to-row').hidden = !isAnnounce;
    _el.querySelector('#cp-delivery-account-row').hidden = !isAnnounce;
    _el.querySelector('#cp-delivery-webhook-url-row').hidden = !isWebhook;
    _el.querySelector('#cp-delivery-webhook-token-row').hidden = !isWebhook;
    _el.querySelector('#cp-delivery-best-effort-row').hidden = !showAny;
  }

  function _onFailureDestModeChange() {
    const mode = _el.querySelector('#cp-fd-mode').value;
    const isChannel = mode === 'channel';
    const isWebhook = mode === 'webhook';
    _el.querySelector('#cp-fd-channel-row').hidden = !isChannel;
    _el.querySelector('#cp-fd-to-row').hidden = !isChannel;
    _el.querySelector('#cp-fd-account-row').hidden = !isChannel;
    _el.querySelector('#cp-fd-webhook-url-row').hidden = !isWebhook;
    _el.querySelector('#cp-fd-webhook-token-row').hidden = !isWebhook;
  }

  function _populateDeliveryFields(job) {
    const d = (job && job.delivery) || {};
    const mode = (d.mode || '').toLowerCase();
    // 'none' from the wire is a real user choice; '' / null means "inferred".
    const uiMode =
      mode === 'webhook' ? 'webhook'
      : mode === 'announce' || mode === 'channel' ? 'announce'
      : mode === 'none' ? 'none'
      : '';
    _el.querySelector('#cp-delivery-mode').value = uiMode;
    _el.querySelector('#cp-delivery-channel').value = d.channelName || '';
    _el.querySelector('#cp-delivery-to').value = d.to || d.channelId || '';
    _el.querySelector('#cp-delivery-account').value = d.accountId || '';
    _el.querySelector('#cp-delivery-webhook-url').value = d.webhookUrl || '';
    _el.querySelector('#cp-delivery-webhook-token').value = '';
    _el.querySelector('#cp-delivery-best-effort').checked = !!d.bestEffort;

    const fd = d.failureDestination || {};
    const fdMode = (fd.mode || '').toLowerCase();
    const uiFdMode =
      fdMode === 'webhook' ? 'webhook'
      : fdMode === 'channel' || fdMode === 'announce' ? 'channel'
      : '';
    _el.querySelector('#cp-fd-mode').value = uiFdMode;
    _el.querySelector('#cp-fd-channel').value = fd.channelName || '';
    _el.querySelector('#cp-fd-to').value = fd.to || fd.channelId || '';
    _el.querySelector('#cp-fd-account').value = fd.accountId || '';
    _el.querySelector('#cp-fd-webhook-url').value = fd.webhookUrl || '';
    _el.querySelector('#cp-fd-webhook-token').value = '';
  }

  function _buildDeliveryFromForm() {
    const mode = _el.querySelector('#cp-delivery-mode').value;
    const fdMode = _el.querySelector('#cp-fd-mode').value;
    const bestEffort = _el.querySelector('#cp-delivery-best-effort').checked;
    if (!mode && !fdMode) return null;

    const fd = _buildFailureDestinationFromForm();

    if (mode === 'none') {
      const out = { mode: 'none' };
      if (fd) out.failureDestination = fd;
      return out;
    }
    if (mode === 'webhook') {
      const url = _el.querySelector('#cp-delivery-webhook-url').value.trim();
      if (!url) { UI.toast('Webhook URL is required for webhook delivery', 'warn'); return undefined; }
      const out = { mode: 'webhook', webhookUrl: url };
      const tok = _el.querySelector('#cp-delivery-webhook-token').value.trim();
      if (tok) out.webhookToken = tok;
      if (bestEffort) out.bestEffort = true;
      if (fd) out.failureDestination = fd;
      return out;
    }
    if (mode === 'announce') {
      const out = { mode: 'announce' };
      const ch = _el.querySelector('#cp-delivery-channel').value.trim();
      const to = _el.querySelector('#cp-delivery-to').value.trim();
      const acct = _el.querySelector('#cp-delivery-account').value.trim();
      if (ch) out.channelName = ch.toLowerCase();
      if (to) out.to = to;
      if (acct) out.accountId = acct;
      if (bestEffort) out.bestEffort = true;
      if (fd) out.failureDestination = fd;
      return out;
    }
    // mode is empty but fd is set → standalone failure-destination patch.
    if (fd) return { failureDestination: fd };
    return null;
  }

  function _buildFailureDestinationFromForm() {
    const mode = _el.querySelector('#cp-fd-mode').value;
    if (!mode) return null;
    if (mode === 'webhook') {
      const url = _el.querySelector('#cp-fd-webhook-url').value.trim();
      if (!url) { UI.toast('Failure-destination webhook URL is required', 'warn'); return undefined; }
      const out = { mode: 'webhook', webhookUrl: url };
      const tok = _el.querySelector('#cp-fd-webhook-token').value.trim();
      if (tok) out.webhookToken = tok;
      return out;
    }
    // channel mode
    const ch = _el.querySelector('#cp-fd-channel').value.trim();
    const to = _el.querySelector('#cp-fd-to').value.trim();
    const acct = _el.querySelector('#cp-fd-account').value.trim();
    if (!ch && !to) {
      UI.toast('Failure destination channel needs a channel or recipient', 'warn');
      return undefined;
    }
    const out = { mode: 'channel' };
    if (ch) out.channelName = ch.toLowerCase();
    if (to) out.to = to;
    if (acct) out.accountId = acct;
    return out;
  }

  function _saveJob() {
    const name = _el.querySelector('#cp-name').value.trim();
    if (!name) { UI.toast('Name is required', 'warn'); return; }
    const type = _el.querySelector('#cp-type').value;
    const message = _el.querySelector('#cp-message').value.trim();
    const enabled = _el.querySelector('#cp-enabled').checked;
    const payloadKind = _el.querySelector('#cp-payload-kind').value;
    const agentId = _el.querySelector('#cp-agent-id').value.trim() || 'main';
    const sessionTarget = payloadKind === 'system_event'
      ? 'main'
      : payloadKind === 'reminder'
        ? 'isolated'
        : _el.querySelector('#cp-session-target').value;
    const targetSessionKey = _el.querySelector('#cp-target-session-key').value.trim();

    const payload = { name, enabled, payloadKind, agentId, sessionTarget, text: message };
    if (type === 'cron') {
      payload.schedule = { kind: 'cron', expr: _el.querySelector('#cp-cron').value.trim() };
    } else if (type === 'every') {
      const everySeconds = Number(_el.querySelector('#cp-every').value);
      if (!Number.isInteger(everySeconds) || everySeconds < 1) {
        UI.toast('Interval must be an integer number of seconds', 'warn');
        return;
      }
      payload.schedule = { kind: 'every', every_seconds: everySeconds };
    } else if (type === 'at') {
      const at = _el.querySelector('#cp-at').value.trim();
      if (!at) { UI.toast('ISO time is required', 'warn'); return; }
      payload.schedule = { kind: 'at', at };
    }

    const tz = _el.querySelector('#cp-tz').value.trim();
    if (tz) {
      payload.tz = tz;
      if (payload.schedule && payload.schedule.kind === 'cron') payload.schedule.tz = tz;
    }

    const wakeMode = _el.querySelector('#cp-wake-mode').value;
    if (wakeMode && wakeMode !== 'now') payload.wakeMode = wakeMode;

    const delivery = _buildDeliveryFromForm();
    if (delivery === undefined) return; // validation toast already emitted
    if (delivery !== null) payload.delivery = delivery;

    if (sessionTarget === 'current') {
      const boundSessionKey =
        targetSessionKey || _activeChatSessionKey() || _jobSessionKey(_editingJob);
      if (!boundSessionKey) { UI.toast('Current session key is required', 'warn'); return; }
      payload.sessionKey = boundSessionKey;
      payload.targetSessionKey = boundSessionKey;
      payload.originSessionKey = boundSessionKey;
    }
    if (payloadKind === 'reminder' && _activeChatSessionKey()) {
      payload.originSessionKey = _activeChatSessionKey();
    }
    if (sessionTarget === 'session') {
      if (!targetSessionKey) { UI.toast('Named session key is required', 'warn'); return; }
      payload.targetSessionKey = targetSessionKey;
    }

    const isEdit = !!_editingJob;
    if (isEdit) payload.id = _editingJob.id;

    const method = isEdit ? 'cron.update' : 'cron.create';
    _rpc.call(method, payload)
      .then(() => {
        UI.toast(isEdit ? 'Schedule updated' : 'Schedule created', 'ok');
        _closePanel();
        _loadData();
      })
      .catch(err => UI.toast('Save failed: ' + err.message, 'err'));
  }

  // ---- cron parsing & humanizer (local, best-effort) ------------------

  function _parseField(field, min, max, names) {
    if (field === '*' || field === '?') return { all: true };
    const out = new Set();
    field.split(',').forEach(part => {
      let stepStr = '1';
      let core = part;
      const slash = part.indexOf('/');
      if (slash >= 0) { core = part.slice(0, slash); stepStr = part.slice(slash + 1); }
      const step = Math.max(1, parseInt(stepStr, 10) || 1);
      let lo = min, hi = max;
      if (core === '*' || core === '') { lo = min; hi = max; }
      else if (core.includes('-')) {
        const [a, b] = core.split('-');
        lo = _toNum(a, names, min, max);
        hi = _toNum(b, names, min, max);
      } else {
        const n = _toNum(core, names, min, max);
        lo = hi = n;
      }
      if (lo === null || hi === null || lo > max || hi < min) return;
      lo = Math.max(min, lo); hi = Math.min(max, hi);
      for (let v = lo; v <= hi; v += step) out.add(v);
    });
    return { all: false, set: out };
  }

  function _toNum(token, names, min, max) {
    if (token == null) return null;
    const t = String(token).trim().toLowerCase();
    if (t === '') return null;
    if (names && names[t] !== undefined) return names[t];
    const n = parseInt(t, 10);
    if (Number.isNaN(n)) return null;
    return n;
  }

  function _parseCron(expr) {
    if (!expr) return null;
    const parts = expr.trim().split(/\s+/);
    if (parts.length !== 5) return null;
    const monthNames = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
    const dowNames = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
    try {
      const minute = _parseField(parts[0], 0, 59);
      const hour = _parseField(parts[1], 0, 23);
      const dom = _parseField(parts[2], 1, 31);
      const month = _parseField(parts[3], 1, 12, monthNames);
      let dow = _parseField(parts[4], 0, 6, dowNames);
      // 7 → 0 (Sunday)
      if (!dow.all && dow.set.has(7)) { dow.set.delete(7); dow.set.add(0); }
      return { minute, hour, dom, month, dow, raw: expr };
    } catch { return null; }
  }

  function _matches(field, v) { return field.all || field.set.has(v); }

  function _nextRuns(parsed, count, fromTs) {
    if (!parsed) return [];
    const results = [];
    const start = new Date(fromTs || Date.now());
    start.setSeconds(0, 0);
    start.setMinutes(start.getMinutes() + 1);
    let d = new Date(start);
    const endLimit = Date.now() + 365 * 24 * 3600 * 1000;
    while (results.length < count && d.getTime() < endLimit) {
      const m = d.getMinutes();
      const h = d.getHours();
      const dom = d.getDate();
      const mon = d.getMonth() + 1;
      const dow = d.getDay();
      // Vixie semantics: when both DOM and DOW are restricted (not all), match either.
      const domAll = parsed.dom.all;
      const dowAll = parsed.dow.all;
      const dayOk = (domAll && dowAll) ? true
        : (domAll ? _matches(parsed.dow, dow)
          : (dowAll ? _matches(parsed.dom, dom)
            : (_matches(parsed.dom, dom) || _matches(parsed.dow, dow))));
      if (
        _matches(parsed.minute, m) &&
        _matches(parsed.hour, h) &&
        _matches(parsed.month, mon) &&
        dayOk
      ) {
        results.push(new Date(d));
      }
      d = new Date(d.getTime() + 60_000);
    }
    return results;
  }

  function _humanizeFieldList(field, all_label, names) {
    if (field.all) return all_label;
    const arr = [...field.set].sort((a, b) => a - b);
    if (arr.length === 0) return '—';
    const display = arr.map(v => names ? names[v] : String(v).padStart(2, '0'));
    if (display.length === 1) return display[0];
    if (display.length <= 4) return display.join(', ');
    return display.slice(0, 3).join(', ') + ` & ${display.length - 3} more`;
  }

  function _explainCron(expr) {
    const p = _parseCron(expr);
    if (!p) return '';
    const dowNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const monNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    // Common patterns
    if (p.minute.all && p.hour.all) return 'Every minute';
    if (!p.minute.all && p.minute.set.size === 1 && p.hour.all) {
      const m = [...p.minute.set][0];
      return `Every hour at :${String(m).padStart(2, '0')}`;
    }
    if (p.minute.all === false && p.minute.set.size === 1 && p.hour.all === false && p.hour.set.size === 1) {
      const m = [...p.minute.set][0], h = [...p.hour.set][0];
      const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
      if (p.dom.all && p.dow.all && p.month.all) return `Every day at ${time}`;
      if (p.dow.all === false && p.dom.all && p.month.all) {
        const days = [...p.dow.set].sort((a, b) => a - b).map(v => dowNames[v]);
        if (days.length === 5 && days[0] === 'Mon' && days[4] === 'Fri') return `Weekdays at ${time}`;
        if (days.length === 2 && days.includes('Sat') && days.includes('Sun')) return `Weekends at ${time}`;
        return `${days.join(', ')} at ${time}`;
      }
      if (p.dom.all === false && p.dow.all && p.month.all) {
        const days = [...p.dom.set].sort((a, b) => a - b).join(', ');
        return `Day ${days} of every month at ${time}`;
      }
      if (p.dom.all === false && p.dow.all && p.month.all === false) {
        const months = [...p.month.set].sort((a, b) => a - b).map(v => monNames[v]).join(', ');
        const days = [...p.dom.set].sort((a, b) => a - b).join(', ');
        return `${months} ${days} at ${time}`;
      }
    }
    // Step minute case: */N
    if (!p.minute.all && p.minute.set.size > 1 && p.hour.all) {
      const arr = [...p.minute.set].sort((a, b) => a - b);
      const diffs = arr.slice(1).map((v, i) => v - arr[i]);
      if (diffs.length && diffs.every(d => d === diffs[0]) && arr[0] % diffs[0] === 0) {
        return `Every ${diffs[0]} minutes`;
      }
    }

    const minPart = _humanizeFieldList(p.minute, 'every minute');
    const hourPart = _humanizeFieldList(p.hour, 'every hour');
    return `at minute ${minPart}, hour ${hourPart}`;
  }

  function _renderCronExplain(expr) {
    if (!_el) return;
    const human = _el.querySelector('#cp-explain-human');
    const hint = _el.querySelector('#cp-explain-hint');
    const upcoming = _el.querySelector('#cp-explain-upcoming');
    const wrap = _el.querySelector('#cp-explain');
    if (!human || !hint || !upcoming || !wrap) return;
    const trimmed = (expr || '').trim();
    if (!trimmed) {
      wrap.classList.remove('is-valid', 'is-invalid');
      human.textContent = 'Enter a 5-field cron expression to preview';
      hint.style.display = '';
      upcoming.hidden = true;
      return;
    }
    const parsed = _parseCron(trimmed);
    if (!parsed) {
      wrap.classList.remove('is-valid');
      wrap.classList.add('is-invalid');
      human.textContent = 'Could not parse expression — expected 5 fields (m h dom mon dow).';
      hint.style.display = '';
      upcoming.hidden = true;
      return;
    }
    const summary = _explainCron(trimmed) || 'matches a custom cadence';
    wrap.classList.remove('is-invalid');
    wrap.classList.add('is-valid');
    human.textContent = summary;
    hint.style.display = 'none';
    if (_previewTimer) clearTimeout(_previewTimer);
    _previewTimer = setTimeout(() => {
      const next = _nextRuns(parsed, 3);
      if (next.length === 0) {
        upcoming.hidden = true;
        return;
      }
      upcoming.hidden = false;
      upcoming.innerHTML = next.map((d, i) => `
        <li><span class="cron-explain__num">${i + 1}.</span><span class="cron-mono">${_humanCountdown(d)}</span><span class="cron-explain__abs">${_humanTime(d)}</span></li>
      `).join('');
    }, 60);
  }

  // ---- helpers ---------------------------------------------------------

  function _humanCountdown(date) {
    const diff = date.getTime() - Date.now();
    if (diff < 0) {
      const past = -diff;
      return _formatDuration(past) + ' ago';
    }
    if (diff < 1000) return 'now';
    return 'in ' + _formatDuration(diff);
  }

  function _humanCountdownPast(date) {
    const diff = Date.now() - date.getTime();
    if (diff < 0) return 'in ' + _formatDuration(-diff);
    if (diff < 1000) return 'just now';
    return _formatDuration(diff) + ' ago';
  }

  function _formatDuration(ms) {
    const s = Math.floor(ms / 1000);
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60);
    if (m < 60) return m + 'm ' + (s % 60) + 's';
    const h = Math.floor(m / 60);
    if (h < 24) return h + 'h ' + (m % 60) + 'm';
    const d = Math.floor(h / 24);
    return d + 'd ' + (h % 24) + 'h';
  }

  function _humanTime(date) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const tomorrow = new Date(today.getTime() + 86400000);
    const dayAfter = new Date(today.getTime() + 2 * 86400000);
    const t = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (date >= today && date < tomorrow) return `today ${t}`;
    if (date >= tomorrow && date < dayAfter) return `tomorrow ${t}`;
    return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ' ' + t;
  }

  function _activeChatSessionKey() {
    try {
      const params = new URLSearchParams(window.location.search);
      const urlSession = _canonicalSessionKey(params.get('session') || '');
      if (urlSession) return urlSession;
    } catch {}
    try {
      return _canonicalSessionKey(localStorage.getItem('opensquilla_active_session') || '');
    } catch { return ''; }
  }

  function _canonicalSessionKey(key) {
    const value = (key || '').trim();
    if (!value) return '';
    if (value === 'default' || value === 'webchat:default') {
      return 'agent:main:webchat:default';
    }
    if (value.startsWith('agent:default:')) {
      return 'agent:main:' + value.slice('agent:default:'.length);
    }
    if (value.startsWith('sess-')) return 'agent:main:webchat:' + value.slice('sess-'.length);
    return value;
  }

  function _jobSessionKey(job) {
    if (!job) return '';
    return (
      job.originSessionKey ||
      job.origin_session_key ||
      job.targetSessionKey ||
      job.target_session_key ||
      job.sessionKey ||
      job.session_key ||
      ''
    );
  }

  function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  return { render, destroy };
})();

window.CronView = CronView;
