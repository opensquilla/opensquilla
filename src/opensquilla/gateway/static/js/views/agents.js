/** OpenSquilla Web UI — Agents view (inline create + view/edit drawer). */

const AgentsView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];
  let _agents = [];
  let _activeDrawer = null;

  function _ensureCss() {
    if (document.querySelector('link[data-view-css="agents"]')) return;
    const data = document.getElementById('opensquilla-data');
    const base = data?.dataset.basePath || '';
    const cssVersion = data?.dataset.version || '';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${base}/static/css/views/agents.css${cssVersion ? '?v=' + encodeURIComponent(cssVersion) : ''}`;
    link.dataset.viewCss = 'agents';
    document.head.appendChild(link);
  }

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _ensureCss();

    _el.innerHTML = `
      <div class="ag-stage">
        <header class="ag-stage__header">
          <div class="ag-stage__title-block">
            <span class="ag-stage__eyebrow">Control · Agents</span>
            <h2 class="ag-stage__title">Agents</h2>
            <p class="ag-stage__subtitle">Custom personalities and skill sets you can chat with.</p>
          </div>
          <div class="ag-stage__actions">
            <button class="btn btn--ghost" id="agents-refresh" title="Refresh">
              ${icons.refresh()}<span>Refresh</span>
            </button>
          </div>
        </header>

        <section class="stat-row" id="stat-row"></section>

        <section class="ag-create">
          <form id="agent-add-form" class="ag-create__form">
            <label class="ag-field">
              <span>Agent ID</span>
              <input id="agent-add-id" class="ag-input" name="id" autocomplete="off" required placeholder="e.g. data-analyst" />
            </label>
            <label class="ag-field">
              <span>Display name <span class="ag-field__optional">(optional)</span></span>
              <input id="agent-add-name" class="ag-input" name="name" autocomplete="off" placeholder="Defaults to ID" />
            </label>
            <button class="btn btn--primary" type="submit">${icons.plus()}<span>Add</span></button>
          </form>
          <p class="ag-create__hint">Created agents inherit the global default model. Click a card to view or edit details.</p>
        </section>

        <section class="ag-list">
          <div class="ag-list__head">
            <h3 class="ag-list__title" id="ag-list-title">Configured agents</h3>
          </div>
          <div id="ag-cards" class="ag-cards"></div>
        </section>
      </div>`;

    _el.querySelector('#agents-refresh').addEventListener('click', _loadData);
    _el.querySelector('#agent-add-form').addEventListener('submit', _onInlineAdd);
    _loadData();
  }

  function destroy() {
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    if (_activeDrawer) { try { _activeDrawer.close('destroy', null); } catch {} _activeDrawer = null; }
    _agents = [];
    _el = null;
    _rpc = null;
  }

  async function _loadData() {
    await _rpc.waitForConnection();
    _rpc.call('agents.list').then(data => {
      _agents = data.agents || [];
      _renderStats();
      _renderCards();
    }).catch(err => UI.toast('Failed to load agents: ' + err.message, 'err'));
  }

  function _renderStats() {
    const wrap = _el && _el.querySelector('#stat-row');
    if (!wrap) return;
    const total = _agents.length;
    const builtins = _agents.filter(a => a.type === 'builtin' || a.isBuiltin).length;
    const customs = total - builtins;
    const tools = _agents.reduce((acc, a) => acc + (Array.isArray(a.tools) ? a.tools.length : 0), 0);
    const models = new Set();
    _agents.forEach(a => { if (a.model) models.add(a.model); });

    wrap.innerHTML = `
      <div class="stat stat--hero">
        <div class="stat-label">Total agents</div>
        <div class="stat-value">${total}</div>
        <div class="stat-hint">${builtins ? `${builtins} built-in` : ''}${builtins && customs ? ' · ' : ''}${customs ? `${customs} custom` : ''}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Models in use</div>
        <div class="stat-value mono">${models.size || '—'}</div>
        <div class="stat-hint">${models.size ? 'distinct models' : 'unset'}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Tools wired</div>
        <div class="stat-value">${tools}</div>
        <div class="stat-hint">across all agents</div>
      </div>`;
  }

  function _renderCards() {
    const wrap = _el && _el.querySelector('#ag-cards');
    const titleEl = _el && _el.querySelector('#ag-list-title');
    if (!wrap) return;

    if (titleEl) {
      titleEl.innerHTML = _agents.length
        ? `Configured agents <span class="ag-list__count">${_agents.length}</span>`
        : 'Configured agents';
    }

    if (_agents.length === 0) {
      wrap.innerHTML = `<div class="state">
        <div class="state-icon">${icons.agents()}</div>
        <div class="state-title">No agents configured.</div>
        <p class="state-text">Use the form above to add one. The default <code>main</code> agent is always available.</p>
      </div>`;
      return;
    }

    wrap.innerHTML = _agents.map((a, i) => {
      const id = a.id || a.name || '—';
      const name = a.name || a.id || '—';
      const type = a.type || (a.isBuiltin ? 'builtin' : 'custom');
      const isBuiltin = a.isBuiltin || type === 'builtin';
      const desc = a.description || '';
      const model = a.model;
      const tools = Array.isArray(a.tools) ? a.tools : [];
      const skills = Array.isArray(a.skills) ? a.skills : [];

      const editBtn = isBuiltin
        ? `<button class="ag-iconbtn" data-customize-agent="${_esc(id)}" title="Use as starting point for a new agent">${icons.plus()}<span>Customize…</span></button>`
        : `<button class="ag-iconbtn" data-edit-agent="${_esc(id)}" title="Edit">${icons.edit ? icons.edit() : '✎'}<span>Edit</span></button>`;

      return `<article class="ag-card${isBuiltin ? ' is-builtin' : ''}" data-card-id="${_esc(id)}" tabindex="0" role="button" aria-label="View agent ${_esc(id)}" style="--i:${i}">
        <header class="ag-card__head">
          <div class="ag-card__id-block">
            <span class="ag-card__id">${_esc(id)}</span>
            <span class="chip ${isBuiltin ? 'chip-ok' : 'chip-info'}">${_esc(type)}</span>
          </div>
          <div class="ag-card__actions">
            <button class="ag-iconbtn" data-open-chat="${_esc(id)}" title="Open chat">${icons.chat()}<span>Chat</span></button>
            ${editBtn}
            ${isBuiltin ? '' : `<button class="ag-iconbtn ag-iconbtn--danger" data-delete-agent="${_esc(id)}" title="Delete">${icons.trash()}<span>Delete</span></button>`}
          </div>
        </header>
        <div class="ag-card__name">${_esc(name)}</div>
        ${desc ? `<p class="ag-card__desc">${_esc(desc)}</p>` : ''}
        <dl class="ag-card__meta">
          ${model ? `<div><dt>Model</dt><dd class="ag-mono">${_esc(model)}</dd></div>` : ''}
          ${tools.length ? `<div><dt>Tools</dt><dd>${tools.length}</dd></div>` : ''}
          ${skills.length ? `<div><dt>Skills</dt><dd>${skills.length}</dd></div>` : ''}
        </dl>
        ${tools.length ? `<div class="ag-card__chips">
          <span class="ag-chips-label">Tools</span>
          ${tools.slice(0, 8).map(t => `<span class="ag-chip">${_esc(t)}</span>`).join('')}
          ${tools.length > 8 ? `<span class="ag-chip ag-chip--dim">+${tools.length - 8}</span>` : ''}
        </div>` : ''}
      </article>`;
    }).join('');

    // Whole-card click → view drawer (delegated; inner buttons stopPropagation).
    wrap.querySelectorAll('.ag-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        _openAgentDrawer({ mode: 'view', agentId: card.dataset.cardId });
      });
      card.addEventListener('keydown', (e) => {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === card) {
          e.preventDefault();
          _openAgentDrawer({ mode: 'view', agentId: card.dataset.cardId });
        }
      });
    });

    wrap.querySelectorAll('[data-open-chat]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        Router.navigate('/chat?agent=' + encodeURIComponent(btn.dataset.openChat));
      });
    });
    wrap.querySelectorAll('[data-edit-agent]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        _openAgentDrawer({ mode: 'edit', agentId: btn.dataset.editAgent });
      });
    });
    wrap.querySelectorAll('[data-customize-agent]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        _customizeFromBuiltin(btn.dataset.customizeAgent);
      });
    });
    wrap.querySelectorAll('[data-delete-agent]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        _deleteAgent(btn.dataset.deleteAgent);
      });
    });
  }

  // ── Inline create flow ─────────────────────────────────────────────────

  function _onInlineAdd(event) {
    event.preventDefault();
    const id = (_el.querySelector('#agent-add-id')?.value || '').trim();
    const name = (_el.querySelector('#agent-add-name')?.value || '').trim();
    if (!id) return;
    const payload = { id };
    if (name) payload.name = name;
    _rpc.call('agents.create', payload).then(() => {
      UI.toast('Agent created: ' + id, 'ok');
      _el.querySelector('#agent-add-form')?.reset();
      _loadData();
    }).catch(err => {
      const code = err?.code || '';
      if (code === 'agent.exists') UI.toast(`Agent "${id}" already exists`, 'warn');
      else UI.toast('Failed to create agent: ' + (err?.message || err), 'err');
    });
  }

  function _customizeFromBuiltin(builtinId) {
    // Pre-fill the inline form with `<id>-copy` and focus it.
    const idInput = _el?.querySelector('#agent-add-id');
    const nameInput = _el?.querySelector('#agent-add-name');
    const seedId = (builtinId || 'main') + '-copy';
    if (idInput) {
      idInput.value = seedId;
      idInput.focus();
      idInput.select();
    }
    if (nameInput) nameInput.value = builtinId + ' (copy)';
    UI.toast('Tweak the ID, then click Add to create your copy', 'info');
    // Scroll the form into view so users on long lists see it.
    idInput?.closest('.ag-create')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // ── View / Edit drawer (Identity + Capabilities only) ─────────────────

  function _agentToForm(agent) {
    return {
      id: agent.id || '',
      name: agent.name || '',
      description: agent.description || '',
      tools: Array.isArray(agent.tools) ? agent.tools.slice() : [],
      workspace: agent.workspace || '',
      agentDir: agent.agent_dir || agent.agentDir || '',
      enabled: agent.enabled !== false,
    };
  }

  function _isDirty(initial, current) {
    try { return JSON.stringify(initial) !== JSON.stringify(current); }
    catch { return true; }
  }

  function _openAgentDrawer({ mode, agentId = null }) {
    if (_activeDrawer) { try { _activeDrawer.close('replaced', null); } catch {} _activeDrawer = null; }

    const found = _agents.find(a => a.id === agentId);
    if (!found) {
      UI.toast(`Agent "${agentId}" not found`, 'err');
      return;
    }
    const isBuiltin = found.isBuiltin || found.type === 'builtin';
    const seed = _agentToForm(found);

    const state = {
      mode,
      agentId,
      isBuiltin,
      initial: JSON.parse(JSON.stringify(seed)),
      current: JSON.parse(JSON.stringify(seed)),
      saving: false,
      // Carry-through for read-only display
      model: found.model || '',
      systemPromptHint: !!(found.system_prompt || found.systemPrompt),
    };

    const titleFor = (m) => (m === 'edit') ? `Edit agent: ${state.agentId}` : `Agent: ${state.agentId}`;

    const drawer = UI.drawer({
      title: titleFor(mode),
      width: 520,
      bodyHtml: '<div class="ag-drawer" data-ag-drawer></div>',
      footerHtml: '',
      beforeClose: async (reason) => {
        if (reason === 'save' || reason === 'destroy' || reason === 'replaced') return true;
        if (state.mode === 'view') return true;
        if (!_isDirty(state.initial, state.current)) return true;
        return await _confirmDiscardChanges();
      },
      onClose: () => { _activeDrawer = null; },
    });
    _activeDrawer = drawer;
    drawer.setMode(mode);

    const root = drawer.body().querySelector('[data-ag-drawer]');
    _renderDrawerBody(root, state, drawer, titleFor);
  }

  function _renderDrawerBody(root, state, drawer, titleFor) {
    const readonly = state.mode === 'view';
    const idDisabled = true; // ID is never editable post-create

    root.innerHTML = `
      <div class="ag-drawer__sections">
        <fieldset class="ag-drawer__section" data-section="identity">
          <legend>Identity</legend>
          <label class="ag-field">
            <span>Agent ID</span>
            <input class="ag-input" data-bind="id" type="text" autocomplete="off" disabled value="${_esc(state.current.id)}" />
          </label>
          <label class="ag-field">
            <span>Display name</span>
            <input class="ag-input" data-bind="name" type="text" autocomplete="off" ${readonly ? 'disabled' : ''} value="${_esc(state.current.name)}" placeholder="Defaults to ID" />
          </label>
          <label class="ag-field">
            <span>Description</span>
            <input class="ag-input" data-bind="description" type="text" autocomplete="off" ${readonly ? 'disabled' : ''} value="${_esc(state.current.description)}" placeholder="A short one-liner" />
          </label>
        </fieldset>

        <details class="ag-drawer__section ag-drawer__section--advanced" ${state.current.workspace || state.current.agentDir || (state.current.tools || []).length || !state.current.enabled ? 'open' : ''}>
          <summary>Capabilities · Advanced</summary>
          <label class="ag-field">
            <span>Tools (comma-separated)</span>
            <input class="ag-input" data-bind="tools" type="text" autocomplete="off" ${readonly ? 'disabled' : ''} value="${_esc((state.current.tools || []).join(', '))}" placeholder="Leave blank to inherit defaults" />
          </label>
          <label class="ag-field">
            <span>Workspace</span>
            <input class="ag-input" data-bind="workspace" type="text" autocomplete="off" ${readonly ? 'disabled' : ''} value="${_esc(state.current.workspace)}" placeholder="Leave blank to use the default path" />
          </label>
          <label class="ag-field">
            <span>Agent dir</span>
            <input class="ag-input" data-bind="agentDir" type="text" autocomplete="off" ${readonly ? 'disabled' : ''} value="${_esc(state.current.agentDir)}" placeholder="Optional" />
          </label>
          <label class="ag-field ag-field--inline">
            <input type="checkbox" data-bind="enabled" ${state.current.enabled ? 'checked' : ''} ${readonly ? 'disabled' : ''} />
            <span>Enabled</span>
          </label>
        </details>

        ${state.model || state.systemPromptHint ? `
          <div class="ag-drawer__readonly-meta">
            ${state.model ? `<div><dt>Inherited model</dt><dd class="ag-mono">${_esc(state.model)}</dd></div>` : ''}
            ${state.systemPromptHint ? `<div><dt>System prompt</dt><dd class="ag-dim">Stored in config — runtime currently sources from agent SOUL.md instead.</dd></div>` : ''}
          </div>` : ''}
      </div>`;

    function _readField(el) {
      const key = el.dataset.bind;
      if (!key) return;
      let value;
      if (el.type === 'checkbox') value = el.checked;
      else if (key === 'tools') value = String(el.value || '').split(',').map(s => s.trim()).filter(Boolean);
      else value = el.value;
      state.current[key] = value;
      _renderFooter();
    }
    root.querySelectorAll('[data-bind]').forEach(el => {
      const evt = el.tagName === 'INPUT' && el.type !== 'checkbox' ? 'input' : 'change';
      el.addEventListener(evt, () => _readField(el));
      el.addEventListener('change', () => _readField(el));
    });

    function _renderFooter() {
      const dirty = _isDirty(state.initial, state.current);
      let footerHtml = '';
      if (state.mode === 'view') {
        footerHtml = `
          <button class="btn btn--ghost" data-act="cancel">Close</button>
          ${state.isBuiltin
            ? `<button class="btn btn--primary" data-act="customize">${icons.plus()}<span>Customize…</span></button>`
            : `<button class="btn btn--primary" data-act="goto-edit">Edit</button>`}`;
      } else {
        footerHtml = `
          <button class="btn btn--ghost" data-act="cancel">Cancel</button>
          <button class="btn btn--primary" data-act="save" ${dirty ? '' : 'disabled'}>Save changes${dirty ? ' •' : ''}</button>`;
      }
      drawer.setFooter(footerHtml);
      drawer.footer().querySelectorAll('button[data-act]').forEach(btn => {
        btn.addEventListener('click', () => _onFooterClick(btn.dataset.act));
      });
    }

    function _onFooterClick(act) {
      if (act === 'cancel') { drawer.close('cancel', null); return; }
      if (act === 'goto-edit') { _switchMode('edit'); return; }
      if (act === 'customize') {
        const builtinId = state.agentId;
        drawer.close('replaced', null);
        _customizeFromBuiltin(builtinId);
        return;
      }
      if (act === 'save') { _onSave(); return; }
    }

    function _switchMode(nextMode) {
      state.mode = nextMode;
      drawer.setMode(nextMode);
      drawer.setTitle(titleFor(nextMode));
      _renderDrawerBody(root, state, drawer, titleFor);
    }

    async function _onSave() {
      if (state.saving) return;
      state.saving = true;
      _renderFooter();
      try {
        const payload = _buildUpdatePayload(state.initial, state.current, state.agentId);
        if (Object.keys(payload).length <= 1) {
          UI.toast('Nothing to save', 'info');
          state.saving = false;
          _renderFooter();
          return;
        }
        await _rpc.call('agents.update', payload);
        UI.toast('Agent updated: ' + state.agentId, 'ok');
        await _loadData();
        // Refresh state in-place to clear dirty + return to view mode.
        const updated = _agents.find(a => a.id === state.agentId);
        if (updated) {
          const seed = _agentToForm(updated);
          state.initial = JSON.parse(JSON.stringify(seed));
          state.current = JSON.parse(JSON.stringify(seed));
          state.model = updated.model || '';
          state.systemPromptHint = !!(updated.system_prompt || updated.systemPrompt);
        }
        _switchMode('view');
      } catch (err) {
        const code = err?.code || '';
        const msg = err?.message || String(err);
        let friendly = 'Failed to save: ' + msg;
        if (code === 'agent.not_found') friendly = `Agent "${state.agentId}" no longer exists.`;
        if (code === 'agent.builtin_immutable') friendly = `"${state.agentId}" is a built-in agent and cannot be modified.`;
        UI.toast(friendly, 'err');
      } finally {
        state.saving = false;
        _renderFooter();
      }
    }

    _renderFooter();
  }

  function _buildUpdatePayload(initial, current, id) {
    const p = { id };
    for (const k of ['name', 'description', 'workspace', 'agentDir', 'enabled']) {
      if (initial[k] !== current[k]) p[k] = current[k];
    }
    if (JSON.stringify(initial.tools || []) !== JSON.stringify(current.tools || [])) {
      p.tools = current.tools;
    }
    return p;
  }

  // ── Confirm dialogs (replace native confirm) ───────────────────────────

  function _confirmModal(title, bodyHtml, primaryLabel = 'Confirm', primaryCls = 'btn--danger') {
    return new Promise((resolve) => {
      let result = false;
      UI.modal(title, bodyHtml, [
        { label: primaryLabel, cls: primaryCls, onClick: () => { result = true; } },
        { label: 'Cancel', cls: '' },
      ]);
      const overlay = document.querySelector('.modal-backdrop');
      if (!overlay) { resolve(false); return; }
      const obs = new MutationObserver(() => {
        if (!document.body.contains(overlay)) {
          obs.disconnect();
          resolve(result);
        }
      });
      obs.observe(document.body, { childList: true });
    });
  }

  function _confirmDiscardChanges() {
    return _confirmModal(
      'Discard unsaved changes?',
      `<p>You have unsaved edits. Closing now will lose them.</p>`,
      'Discard',
      'btn--danger'
    );
  }

  async function _deleteAgent(id) {
    if (!id) return;
    if (!await _confirmModal(
      'Delete agent',
      `<p>Delete agent <strong>${_esc(id)}</strong>? Existing chats with this agent will keep working but become unmanaged.</p>`,
      'Delete',
      'btn--danger'
    )) return;
    _rpc.call('agents.delete', { id }).then(() => {
      UI.toast('Agent deleted: ' + id, 'ok');
      _loadData();
    }).catch(err => UI.toast('Failed to delete agent: ' + err.message, 'err'));
  }

  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return { render, destroy };
})();

window.AgentsView = AgentsView;
