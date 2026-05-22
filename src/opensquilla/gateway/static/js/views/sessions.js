/** OpenSquilla Web UI — Sessions view (FE-002). */

const SessionsView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];

  // State
  let _allSessions = [];
  let _filtered = [];
  let _sortCol = 'updated_at';
  let _sortAsc = false;
  let _page = 0;
  let _pageSize = 25;
  let _selected = new Set();
  let _searchVal = '';
  // agent_id → agent entry from agents.list, used for orphan-agent detection.
  let _agentsById = new Map();
  // Set true only after a successful agents.list response. Orphan chip rendering
  // is gated on this so a transient registry failure does not flood the table
  // with false "Orphaned" badges (the map would be empty during the failure).
  let _agentsLoaded = false;

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _el.innerHTML = `
      <div class="sess-stage">
        <header class="sess-stage__header">
          <div class="sess-stage__title-block">
            <span class="sess-stage__eyebrow">Control · Sessions</span>
            <h2 class="sess-stage__title">Sessions</h2>
            <p class="sess-stage__subtitle">Session history, current task activity, and agent runs — open one to chat, or clean up old state.</p>
          </div>
          <div class="sess-stage__actions">
            <div class="sess-search-wrap">
              <span class="sess-search-icon">${icons.search()}</span>
              <input type="text" class="sess-search-input" id="sess-search" placeholder="Search session keys…" autocomplete="off" />
            </div>
            <button class="btn btn--ghost" id="sess-refresh" title="Refresh">
              ${icons.refresh()}<span>Refresh</span>
            </button>
            <button class="btn btn--primary" id="sess-new">
              ${icons.plus()}<span>New session</span>
            </button>
          </div>
        </header>

        <section class="stat-row" id="stat-row"></section>

        <div class="sess-bulk-bar" id="sess-bulk-bar" hidden>
          <span class="sess-bulk-bar__count"><strong id="sess-bulk-count">0</strong> selected</span>
          <button class="sess-iconbtn sess-iconbtn--ghost" id="sess-bulk-clear">Clear</button>
          <span class="sess-bulk-bar__spacer"></span>
          <button class="sess-iconbtn sess-iconbtn--danger" id="sess-bulk-delete">${icons.trash()}<span>Delete selected</span></button>
        </div>

        <section class="sess-list">
          <div class="sess-list__head">
            <h3 class="sess-list__title" id="sess-list-title">All sessions</h3>
            <div class="sess-list__controls">
              <label class="sess-page-size">
                <span>Show</span>
                <select id="sess-page-size">
                  <option value="10">10</option>
                  <option value="25" selected>25</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                </select>
              </label>
            </div>
          </div>
          <div id="sess-table-wrap" class="sess-table-wrap"></div>
          <div class="sess-pagination" id="sess-pagination"></div>
        </section>
      </div>`;

    _el.querySelector('#sess-refresh').addEventListener('click', _loadData);
    _el.querySelector('#sess-new').addEventListener('click', _openNewSessionModal);
    // Debounce search input so each keystroke doesn't force a full
    // _applyFilter + _renderTable on a 200+ row dataset.
    let _searchDebounceId = null;
    _el.querySelector('#sess-search').addEventListener('input', (e) => {
      const value = e.target.value.trim().toLowerCase();
      if (_searchDebounceId !== null) clearTimeout(_searchDebounceId);
      _searchDebounceId = setTimeout(() => {
        _searchDebounceId = null;
        _searchVal = value;
        _page = 0;
        _selected.clear();
        _applyFilter();
        _renderTable();
        _renderPagination();
        _renderBulkBar();
      }, 180);
    });
    _el.querySelector('#sess-page-size').addEventListener('change', (e) => {
      _pageSize = Number(e.target.value);
      _page = 0;
      _renderTable();
      _renderPagination();
    });
    _el.querySelector('#sess-bulk-delete').addEventListener('click', _bulkDelete);
    _el.querySelector('#sess-bulk-clear').addEventListener('click', () => {
      _selected.clear();
      _renderTable();
      _renderBulkBar();
    });

    _loadData();
  }

  function destroy() {
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    _allSessions = [];
    _filtered = [];
    _selected.clear();
    _el = null;
    _rpc = null;
  }

  async function _loadData() {
    const rpc = _rpc;
    if (!_el || !rpc) return;
    await rpc.waitForConnection();
    if (!_el || _rpc !== rpc) return;
    // Fetch sessions and agents in parallel so the orphan-agent badge is
    // always rendered against fresh registry state.
    // Explicit limit=200 keeps backend default (50) intact for CLI/channel
    // consumers — only this WebUI surface opts into the larger page size.
    const [sessRes, agentsRes] = await Promise.allSettled([
      rpc.call('sessions.list', { limit: 200 }),
      rpc.call('agents.list'),
    ]);
    if (!_el) return;
    if (agentsRes.status === 'fulfilled') {
      const list = agentsRes.value?.agents || [];
      _agentsById = new Map(list.map(a => [a.id, a]));
      _agentsLoaded = true;
    }
    // Note: on agentsRes rejection we deliberately DO NOT clear _agentsLoaded
    // or _agentsById — a transient registry hiccup keeps the last known map,
    // avoiding spurious orphan chips. _agentsLoaded only flips back to false
    // if the view is destroyed.
    if (sessRes.status === 'fulfilled') {
      _allSessions = sessRes.value?.sessions || [];
      _selected.clear();
      _applyFilter();
      _renderStats();
      _renderTable();
      _renderPagination();
      _renderBulkBar();
    } else {
      UI.toast('Failed to load sessions: ' + (sessRes.reason?.message || 'unknown error'), 'err');
    }
  }

  function _applyFilter() {
    if (!_searchVal) {
      _filtered = [..._allSessions];
    } else {
      // Search now also matches user-meaningful metadata (display_name,
      // subject, derived_title) so a renamed session like "Bug triage" is
      // findable by name — previously only key/model were searched.
      _filtered = _allSessions.filter(s =>
        String(s.key || '').toLowerCase().includes(_searchVal) ||
        String(s.model || '').toLowerCase().includes(_searchVal) ||
        String(s.display_name || s.displayName || '').toLowerCase().includes(_searchVal) ||
        String(s.subject || '').toLowerCase().includes(_searchVal) ||
        String(s.derived_title || s.derivedTitle || '').toLowerCase().includes(_searchVal)
      );
    }
    _sortData();
  }

  function _sortData() {
    _filtered.sort((a, b) => {
      let va = a[_sortCol] ?? '';
      let vb = b[_sortCol] ?? '';
      if (_sortCol === 'message_count' || _sortCol === 'updated_at') {
        va = Number(va) || 0;
        vb = Number(vb) || 0;
      } else {
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
      }
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return _sortAsc ? cmp : -cmp;
    });
  }

  function _renderStats() {
    const wrap = _el && _el.querySelector('#stat-row');
    if (!wrap) return;
    const total = _allSessions.length;
    const lifecycleOpen = _allSessions.filter(s => s.status === 'running').length;
    const activeRuns = _allSessions.filter(s => {
      const runStatus = _sessionRunStatus(s);
      return runStatus === 'queued' || runStatus === 'running';
    }).length;
    const done = _allSessions.filter(s => _sessionVisualStatus(s) === 'done').length;
    const failedOrTimedOut = _allSessions.filter(s => {
      const status = _sessionVisualStatus(s);
      return status === 'failed' || status === 'timeout';
    }).length;
    const aborted = _allSessions.filter(s => _sessionVisualStatus(s) === 'killed').length;
    const totalMessages = _allSessions.reduce((acc, s) => acc + (Number(s.message_count) || 0), 0);
    const totalSize = _allSessions.reduce((acc, s) => acc + (Number(s.size_bytes) || 0), 0);
    // Distinct agents derived from key prefix `agent:NAME:...` (best-effort).
    const agents = new Set();
    _allSessions.forEach(s => {
      const m = /^agent:([^:]+):/.exec(s.key || '');
      if (m) agents.add(m[1]);
    });

    wrap.innerHTML = `
      <div class="stat stat--hero">
        <div class="stat-label">Total sessions</div>
        <div class="stat-value">${total}</div>
        <div class="stat-hint">${lifecycleOpen} open · ${done} completed · ${failedOrTimedOut} failed/timed out · ${aborted} aborted</div>
      </div>
      <div class="stat" title="Sessions with queued or running tasks">
        <div class="stat-label">Executing</div>
        <div class="stat-value">
          ${activeRuns}${activeRuns ? '<span class="dot ok"></span>' : ''}
        </div>
        <div class="stat-hint">${activeRuns ? 'tasks queued/running' : 'none executing'}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Messages</div>
        <div class="stat-value mono">${totalMessages.toLocaleString()}</div>
        <div class="stat-hint">${agents.size} agent${agents.size === 1 ? '' : 's'} · across all sessions</div>
      </div>`;
    // Storage KPI removed: backend rpc_sessions.py sets size_bytes=None on every
    // row, so the aggregate was always 0 B and the card displayed dead data.
    // Agent count merged into the Messages hint to preserve that signal.
  }

  function _renderTable() {
    const wrap = _el && _el.querySelector('#sess-table-wrap');
    const titleEl = _el && _el.querySelector('#sess-list-title');
    if (!wrap) return;

    const totalPages = Math.max(1, Math.ceil(_filtered.length / _pageSize));
    _page = Math.min(_page, totalPages - 1);
    const slice = _filtered.slice(_page * _pageSize, (_page + 1) * _pageSize);

    if (titleEl) {
      const total = _allSessions.length;
      titleEl.innerHTML = _searchVal
        ? `Matching sessions <span class="sess-list__count">${_filtered.length} of ${total}</span>`
        : `All sessions <span class="sess-list__count">${total}</span>`;
    }

    if (slice.length === 0 && _allSessions.length === 0) {
      wrap.innerHTML = _emptyStateHtml(false);
      _bindEmptyState(wrap);
      return;
    }
    if (slice.length === 0) {
      wrap.innerHTML = _emptyStateHtml(true);
      _bindEmptyState(wrap);
      return;
    }

    // Note: backend RPC payload (rpc_sessions.py:623-624) still emits BOTH
    // message_count and entry_count keys for CLI compatibility — cli/sessions_cmd.py
    // and cli/chat_cmd.py read both via `or` fallback. The frontend only renders
    // one column to avoid showing identical numbers twice.
    const cols = [
      { key: 'select', label: '' },
      { key: 'key', label: 'Session key' },
      { key: 'status', label: 'Status' },
      { key: 'message_count', label: 'Msgs' },
      { key: 'updated_at', label: 'Modified' },
      { key: '_actions', label: '' },
    ];
    const sortable = ['key', 'updated_at', 'message_count'];

    const allOnPage = slice.length > 0 && slice.every(s => _selected.has(s.key));

    let html = '<table class="sess-table"><thead><tr>';
    cols.forEach(col => {
      if (col.key === 'select') {
        html += `<th class="sess-table__cell--check"><label class="sess-check"><input type="checkbox" id="sess-check-all" ${allOnPage ? 'checked' : ''} /><span></span></label></th>`;
      } else if (col.key === '_actions') {
        html += `<th class="sess-table__cell--actions"></th>`;
      } else if (sortable.includes(col.key)) {
        const arrow = _sortCol === col.key ? (_sortAsc ? ' ▲' : ' ▼') : '';
        html += `<th class="sess-th-sort" data-sort="${col.key}">${col.label}<span class="sess-table__arrow">${arrow}</span></th>`;
      } else {
        html += `<th>${col.label}</th>`;
      }
    });
    html += '</tr></thead><tbody>';

    slice.forEach(row => {
      const checked = _selected.has(row.key) ? 'checked' : '';
      const visualStatus = _sessionVisualStatus(row);
      const status = visualStatus;
      const statusCls = UI.sessionStatusClass(status);
      const statusChip = UI.sessionStatusChip(status);
      const statusTip = UI.sessionStatusLabel(status);
      const runBadge = _runStatusBadge(row);
      const modified = row.updated_at ? UI.relTime(row.updated_at) : '—';
      const isSel = _selected.has(row.key);
      const agentId = row.agent_id || row.agentId || _agentIdFromKey(row.key);
      const agentMeta = _agentSubline(agentId);
      html += `<tr class="${isSel ? 'is-selected' : ''}">
        <td class="sess-table__cell--check"><label class="sess-check"><input type="checkbox" class="sess-row-check" data-key="${_esc(row.key)}" ${checked} /><span></span></label></td>
        <td class="sess-table__cell--key">
          <div class="sess-table__key-content">
            <span class="dot ${statusCls}" title="${_esc(statusTip)}"></span>
            <button type="button" class="sess-key-link" data-open-key="${_esc(row.key)}" title="Open chat">${_esc(row.key)}</button>
            ${agentMeta}
          </div>
        </td>
        <td><div class="sess-status-stack"><span class="chip ${statusChip}">${_esc(statusTip)}</span>${runBadge}</div></td>
        <td class="sess-mono">${row.message_count != null ? Number(row.message_count).toLocaleString() : '—'}</td>
        <td class="sess-mono sess-dim">${_esc(modified)}</td>
        <td class="sess-table__cell--actions">
          <button class="sess-iconbtn" data-open-key="${_esc(row.key)}" title="Open chat">${icons.chat()}</button>
          <button class="sess-iconbtn" data-copy-key="${_esc(row.key)}" title="Copy session key">${icons.copy()}</button>
          <button class="sess-iconbtn sess-iconbtn--danger" data-del-key="${_esc(row.key)}" title="Delete">${icons.trash()}</button>
        </td>
      </tr>`;
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;

    // Bind select-all
    const checkAll = wrap.querySelector('#sess-check-all');
    if (checkAll) {
      checkAll.addEventListener('change', () => {
        if (checkAll.checked) {
          slice.forEach(s => _selected.add(s.key));
        } else {
          slice.forEach(s => _selected.delete(s.key));
        }
        _renderTable();
        _renderPagination();
        _renderBulkBar();
      });
    }

    // Bind row checkboxes
    wrap.querySelectorAll('.sess-row-check').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) _selected.add(cb.dataset.key);
        else _selected.delete(cb.dataset.key);
        _renderBulkBar();
        _updateSelectAll();
        cb.closest('tr')?.classList.toggle('is-selected', cb.checked);
      });
    });

    // Bind open buttons / key links
    wrap.querySelectorAll('[data-open-key]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const key = el.dataset.openKey;
        Router.navigate('/chat?session=' + encodeURIComponent(key));
      });
    });

    // Bind copy buttons
    wrap.querySelectorAll('[data-copy-key]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const key = btn.dataset.copyKey;
        try {
          await navigator.clipboard.writeText(key);
          UI.toast('Copied session key', 'ok');
        } catch {
          UI.toast('Copy failed', 'warn');
        }
      });
    });

    // Bind delete buttons
    wrap.querySelectorAll('[data-del-key]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        _deleteSession(btn.dataset.delKey);
      });
    });

    // Bind sort headers
    wrap.querySelectorAll('th.sess-th-sort').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.sort;
        if (_sortCol === col) {
          _sortAsc = !_sortAsc;
        } else {
          _sortCol = col;
          _sortAsc = true;
        }
        _sortData();
        _renderTable();
        _renderPagination();
      });
    });
  }

  function _emptyStateHtml(filtered) {
    if (filtered) {
      return `<div class="state">
        <div class="state-icon">${icons.search()}</div>
        <div class="state-title">No matches</div>
        <p class="state-text">No sessions match your search. Try a different query, or clear it to see everything.</p>
      </div>`;
    }
    return `<div class="sess-empty">
      <div class="sess-empty__art" aria-hidden="true">
        <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <radialGradient id="sg" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="rgba(240,160,48,0.18)"/>
              <stop offset="60%" stop-color="rgba(240,160,48,0.04)"/>
              <stop offset="100%" stop-color="rgba(240,160,48,0)"/>
            </radialGradient>
          </defs>
          <circle cx="60" cy="60" r="58" fill="url(#sg)"/>
          <g stroke="currentColor" stroke-width="1.4" fill="none" opacity="0.55">
            <rect x="22" y="34" width="50" height="38" rx="6"/>
            <line x1="32" y1="46" x2="62" y2="46"/>
            <line x1="32" y1="54" x2="56" y2="54"/>
            <line x1="32" y1="62" x2="50" y2="62"/>
          </g>
          <g stroke="var(--accent)" stroke-width="1.6" fill="none">
            <rect x="48" y="50" width="50" height="38" rx="6"/>
            <line x1="58" y1="62" x2="88" y2="62"/>
            <line x1="58" y1="70" x2="82" y2="70"/>
            <line x1="58" y1="78" x2="76" y2="78"/>
          </g>
          <circle cx="98" cy="50" r="4" fill="var(--accent)" class="sess-empty__pulse"/>
        </svg>
      </div>
      <div class="sess-empty__title">No sessions yet.</div>
      <p class="sess-empty__msg">Sessions appear here as soon as you chat with an agent or schedule a cron job.<br/>Start one and pick up the conversation any time.</p>
      <button class="btn btn--primary sess-empty__cta" data-sess-empty-create>${icons.plus()}<span>Start a new session</span></button>
    </div>`;
  }

  function _bindEmptyState(wrap) {
    const btn = wrap.querySelector('[data-sess-empty-create]');
    if (btn) btn.addEventListener('click', _openNewSessionModal);
  }

  function _renderPagination() {
    const pag = _el && _el.querySelector('#sess-pagination');
    if (!pag) return;
    const totalPages = Math.max(1, Math.ceil(_filtered.length / _pageSize));
    if (_filtered.length === 0) { pag.innerHTML = ''; return; }
    pag.innerHTML = `
      <button class="sess-page-btn" id="sess-prev" ${_page === 0 ? 'disabled' : ''} title="Previous page">‹</button>
      <span class="sess-page-info">${_page + 1} / ${totalPages} <span class="sess-dim">· ${_filtered.length} total</span></span>
      <button class="sess-page-btn" id="sess-next" ${_page >= totalPages - 1 ? 'disabled' : ''} title="Next page">›</button>`;
    pag.querySelector('#sess-prev')?.addEventListener('click', () => { _page--; _renderTable(); _renderPagination(); });
    pag.querySelector('#sess-next')?.addEventListener('click', () => { _page++; _renderTable(); _renderPagination(); });
  }

  function _renderBulkBar() {
    const bar = _el && _el.querySelector('#sess-bulk-bar');
    const count = _el && _el.querySelector('#sess-bulk-count');
    if (!bar || !count) return;
    const n = _selected.size;
    if (n > 0) {
      bar.hidden = false;
      bar.classList.add('is-on');
      count.textContent = String(n);
    } else {
      bar.classList.remove('is-on');
      bar.hidden = true;
    }
  }

  function _updateSelectAll() {
    const wrap = _el && _el.querySelector('#sess-table-wrap');
    if (!wrap) return;
    const checkAll = wrap.querySelector('#sess-check-all');
    if (!checkAll) return;
    const cbs = wrap.querySelectorAll('.sess-row-check');
    const allChecked = cbs.length > 0 && Array.from(cbs).every(cb => cb.checked);
    checkAll.checked = allChecked;
  }

  function _bulkDelete() {
    const keys = Array.from(_selected);
    if (keys.length === 0) return;
    UI.modal(
      'Delete sessions',
      `<p>Delete <strong>${keys.length}</strong> session${keys.length === 1 ? '' : 's'}? This cannot be undone.</p>
       <p class="sess-modal__warn"><small>The transcript will not be flushed to disk; use <code>/reset</code> first if you want a backup.</small></p>`,
      [
        {
          label: 'Delete all', cls: 'btn-danger', onClick: async () => {
            // Backend sessions.delete (rpc_sessions.py:1466) accepts {keys:[...]}
            // for batch deletion and returns {deleted: [...], errors: [...]}.
            // One round-trip instead of N preserves partial-failure semantics
            // via the errors[] array.
            try {
              const res = await _rpc.call('sessions.delete', { keys });
              const errCount = (res && res.errors && res.errors.length) || 0;
              const okCount = (res && res.deleted && res.deleted.length) ?? (keys.length - errCount);
              if (errCount > 0) {
                UI.toast(`Deleted ${okCount}, ${errCount} failed`, 'warn');
              } else {
                UI.toast(`Deleted ${okCount} session${okCount === 1 ? '' : 's'}`, 'info');
              }
            } catch (err) {
              UI.toast('Bulk delete failed: ' + (err?.message || 'unknown error'), 'err');
            }
            _selected.clear();
            _loadData();
          }
        },
        { label: 'Cancel', cls: '' },
      ]
    );
  }

  function _deleteSession(key) {
    UI.modal(
      'Delete session',
      `<p>Delete session <strong>${_esc(key)}</strong>? This cannot be undone.</p>
       <p class="sess-modal__warn"><small>The transcript will not be flushed to disk; use <code>/reset</code> first if you want a backup.</small></p>`,
      [
        {
          label: 'Delete', cls: 'btn-danger', onClick: async () => {
            try {
              const res = await _rpc.call('sessions.delete', { key });
              const errors = Array.isArray(res?.errors) ? res.errors : [];
              const deleted = Array.isArray(res?.deleted) ? res.deleted : [];
              if (errors.length > 0 || !deleted.includes(key)) {
                const first = errors[0];
                const reason = typeof first === 'string'
                  ? first
                  : (first?.message || first?.error || first?.reason || 'session was not deleted');
                UI.toast('Delete failed: ' + reason, 'err');
              } else {
                UI.toast('Session deleted', 'info');
              }
            } catch (err) {
              UI.toast('Delete failed: ' + (err?.message || 'unknown error'), 'err');
            }
            _loadData();
          }
        },
        { label: 'Cancel', cls: '' },
      ]
    );
  }

  async function _openNewSessionModal() {
    // Build a self-contained modal so we can keep it open on RPC failure and
    // surface inline errors instead of toast-then-reopen churn.
    const overlay = document.createElement('div');
    overlay.className = 'modal-backdrop';
    overlay.innerHTML = `
      <div class="modal sess-newchat-modal" role="dialog" aria-modal="true" aria-labelledby="ns-title">
        <div class="modal-title" id="ns-title">Start a new chat</div>
        <div class="modal-body">
          <div class="sess-form">
            <label class="sess-form__field">
              <span class="sess-form__label">Agent</span>
            <div data-ns-agent-host></div>
              <small class="sess-form__hint">Pick an agent or type a new ID to create it.</small>
            </label>
            <div class="sess-form__error" data-ns-error hidden></div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" data-ns-cancel>Cancel</button>
          <button class="btn btn--primary" data-ns-submit disabled>Start chat</button>
        </div>
      </div>`;

    const cancelBtn = overlay.querySelector('[data-ns-cancel]');
    const submitBtn = overlay.querySelector('[data-ns-submit]');
    const errorEl = overlay.querySelector('[data-ns-error]');
    const agentHost = overlay.querySelector('[data-ns-agent-host]');

    let agents = [];
    try {
      const data = await _rpc.call('agents.list');
      agents = (data?.agents || []).map(a => ({
        id: a.id,
        label: a.name || a.id,
        sublabel: a.model || (a.isBuiltin || a.type === 'builtin' ? 'built-in' : ''),
      }));
    } catch (err) {
      // Non-fatal — combobox will show an empty list but still accepts typed IDs.
      agents = [];
    }

    let selectedAgentId = '';
    let createPending = false;

    const combo = UI.combobox({
      items: agents,
      value: agents.find(a => a.id === 'main') ? 'main' : '',
      placeholder: 'Pick an agent or type a new ID',
      emptyText: agents.length ? 'No matches' : 'No agents — type to create one',
      allowCreate: true,
      createLabel: (typed) => `↵ Create new agent "${typed}"`,
      onChange: (id) => {
        selectedAgentId = id || '';
        createPending = false;
        _refreshSubmit();
      },
      onCreate: (typed) => {
        selectedAgentId = '';
        createPending = true;
        // Mirror the typed text back into the input so the user sees what's about to be created.
        combo.setValue(typed);
        _refreshSubmit();
      },
      autofocus: true,
    });
    if (combo.getValue() === 'main') {
      selectedAgentId = 'main';
    }
    agentHost.appendChild(combo.element);

    function _refreshSubmit() {
      const typed = (combo.getTyped() || '').trim();
      const ok = !!(selectedAgentId || typed);
      submitBtn.disabled = !ok;
    }

    // Re-evaluate the "create pending" state on every input. Without this, a
    // user who keeps typing past a known agent would still show the picked value.
    combo.input.addEventListener('input', () => {
      const typed = combo.getTyped();
      const exact = agents.find(a => a.id === typed || a.label === typed);
      if (exact) { selectedAgentId = exact.id; createPending = false; }
      else { selectedAgentId = ''; createPending = !!typed; }
      _refreshSubmit();
    });

    function _close() {
      combo.destroy();
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener('keydown', _onKey);
    }
    function _showError(msg) {
      errorEl.textContent = msg;
      errorEl.hidden = false;
    }
    function _clearError() { errorEl.hidden = true; errorEl.textContent = ''; }
    function _onKey(e) {
      if (e.key === 'Escape') { e.stopPropagation(); _close(); }
    }
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) _close();
    });
    cancelBtn.addEventListener('click', _close);

    async function _onSubmit() {
      if (submitBtn.disabled) return;
      _clearError();
      const params = {};
      let createdAgent = false;
      if (createPending) {
        const id = (combo.getTyped() || '').trim();
        if (!id) return;
        params.agentId = id;
      } else {
        params.agentId = selectedAgentId || (combo.getTyped() || '').trim() || 'main';
      }
      submitBtn.disabled = true;
      const prevLabel = submitBtn.textContent;
      submitBtn.textContent = createPending ? 'Creating…' : 'Starting…';
      try {
        if (createPending) {
          try {
            await _rpc.call('agents.create', { id: params.agentId, name: params.agentId });
            createdAgent = true;
          } catch (err) {
            if ((err?.code || '') !== 'agent.exists') throw err;
          }
        }
        const res = await _rpc.call('sessions.create', { agentId: params.agentId });
        UI.toast(
          createdAgent ? `Created agent "${params.agentId}" and started chat` : 'Session created',
          'ok'
        );
        _close();
        _loadData();
        if (res?.key) Router.navigate('/chat?session=' + encodeURIComponent(res.key));
      } catch (err) {
        const code = err?.code || '';
        const msg = err?.message || String(err);
        let friendly = 'Failed to start chat: ' + msg;
        if (code === 'UNAUTHORIZED' && createPending) friendly = 'This connection does not have permission to create agents.';
        if (code === 'agent.not_found') friendly = `Agent "${params.agentId}" doesn't exist. Type a new ID and pick "Create new agent" from the dropdown.`;
        if (code === 'agent.exists') friendly = `Agent "${params.agentId}" already exists — pick it from the list instead.`;
        _showError(friendly);
        submitBtn.textContent = prevLabel;
        submitBtn.disabled = false;
      }
    }
    submitBtn.addEventListener('click', _onSubmit);

    document.addEventListener('keydown', _onKey);
    document.body.appendChild(overlay);
    setTimeout(() => combo.focus(), 50);
    _refreshSubmit();
  }

  // Pull the agent_id from a session_key like "agent:<id>:<kind>:<short>" or
  // "agent:<id>:<short>". Falls back to '' if the prefix doesn't match.
  function _agentIdFromKey(key) {
    if (typeof key !== 'string') return '';
    const m = /^agent:([^:]+):/.exec(key);
    return m ? m[1] : '';
  }

  function _normalizeRunStatus(status) {
    const value = String(status || '').toLowerCase();
    if (value === 'abandoned') return 'interrupted';
    if (value === 'succeeded' || value === 'success' || value === 'complete') return 'idle';
    if (['queued', 'running', 'interrupted', 'failed', 'timeout', 'cancelled'].includes(value)) {
      return value;
    }
    return 'idle';
  }

  function _sessionRunStatus(row) {
    row = row || {};
    const active = row.active_task || row.activeTask || null;
    const activeStatus = active ? _normalizeRunStatus(active.status) : '';
    const terminalStatus = _terminalRunStatus(row);
    const rawStatus = row.run_status || row.runStatus || active?.status || terminalStatus || '';
    const runStatus = _normalizeRunStatus(rawStatus);
    if (active && (activeStatus === 'queued' || activeStatus === 'running')) return activeStatus;
    if (terminalStatus) return _normalizeRunStatus(terminalStatus);
    return runStatus;
  }

  function _terminalRunStatus(row) {
    row = row || {};
    const lastTask = row.last_task || row.lastTask || null;
    const rawStatus = lastTask?.status || row.terminal_status || row.terminalStatus || '';
    const status = _normalizeRunStatus(rawStatus);
    return ['failed', 'timeout', 'cancelled', 'interrupted'].includes(status) ? status : '';
  }

  function _sessionVisualStatus(row) {
    const runStatus = _sessionRunStatus(row);
    if (runStatus === 'failed' || runStatus === 'timeout') return runStatus;
    if (runStatus === 'cancelled' || runStatus === 'interrupted') return 'killed';
    return String(row?.status || 'unknown').toLowerCase();
  }

  function _runStatusLabel(status) {
    return {
      queued: 'Task queued',
      running: 'Task running',
      interrupted: 'Interrupted',
      failed: 'Last task failed',
      timeout: 'Last task timed out',
      cancelled: 'Last task cancelled',
    }[status] || '';
  }

  function _runStatusChipClass(status) {
    return {
      queued: 'chip-warn',
      running: 'chip-ok',
      interrupted: 'chip-warn',
      failed: 'chip-danger',
      timeout: 'chip-warn',
    }[status] || '';
  }

  function _runStatusBadge(row) {
    const runStatus = _sessionRunStatus(row);
    const label = _runStatusLabel(runStatus);
    if (!label) return '';
    const chipClass = _runStatusChipClass(runStatus);
    return `<span class="chip ${chipClass} sess-run-chip" title="${_esc(label)}">${_esc(label)}</span>`;
  }

  // Render the per-row agent subline. Shows the agent display name when known,
  // or a yellow ⚠ Orphaned chip when the session references an agent that no
  // longer exists in the registry. Returns '' for blank or built-in `main` so
  // we don't add visual noise to the default case.
  function _agentSubline(agentId) {
    if (!agentId) return '';
    const entry = _agentsById.get(agentId);
    if (entry) {
      // Don't repeat for the built-in default — the key already starts with
      // "agent:main:" and showing "main" again is noise.
      if (agentId === 'main') return '';
      const name = entry.name || agentId;
      return `<div class="sess-key__sub">
        <span class="sess-key__agent">${_esc(name)}</span>
      </div>`;
    }
    if (agentId === 'main') return '';
    // Only mark a row "Orphaned" once we have actually loaded the registry and
    // confirmed the id is missing. Before first successful agents.list (e.g.
    // during a transient RPC failure) show the agent id as plain text so a
    // network blip doesn't flood the table with false orphan warnings.
    if (!_agentsLoaded) {
      return `<div class="sess-key__sub">
        <span class="sess-key__agent">${_esc(agentId)}</span>
      </div>`;
    }
    return `<div class="sess-key__sub">
      <span class="sess-key__agent sess-key__agent--orphan" title="Agent '${_esc(agentId)}' is no longer registered">
        ${_esc(agentId)}
        <span class="chip chip-warn">⚠ Orphaned</span>
      </span>
    </div>`;
  }

  function _fmtBytes(bytes) {
    if (bytes == null) return '—';
    const n = Number(bytes);
    if (isNaN(n)) return '—';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(2) + ' MB';
    return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
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

window.SessionsView = SessionsView;
