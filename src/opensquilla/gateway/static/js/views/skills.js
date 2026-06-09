/** OpenSquilla Web UI — Skills Management view. */

const SkillsView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];
  let _allSkills = [];
  let _proposals = [];
  let _autoEnabledSkills = [];
  let _proposalsSettings = {
    available: false,
    enabled: false,
    on_dream_complete: false,
    auto_enable: false,
    auto_enable_max_risk: 'low',
  };
  let _filterText = '';
  let _statusFilter = 'all';
  let _activeTab = 'installed';
  let _skillDialogRequestSeq = 0;
  let _skillDialogSelectedName = '';

  const _LAYER_ORDER = ['workspace', 'bundled', 'managed', 'personal', 'project', 'extra'];
  const _LAYER_LABEL = {
    workspace: 'Workspace',
    bundled: 'Bundled',
    managed: 'Managed',
    personal: 'Personal',
    project: 'Project',
    extra: 'Extra',
  };
  const _LAYER_HELP = {
    workspace: 'Workspace skills are local to the active workspace.',
    bundled: 'Bundled skills ship with OpenSquilla.',
    managed: 'Managed skills are locally installed into OpenSquilla state.',
    personal: 'Personal skills are local user installs, not bundled.',
    project: 'Project skills are local to the current project.',
    extra: 'Extra skills come from configured local directories.',
  };

  function _ensureCss() {
    if (document.querySelector('link[data-view-css="skills"]')) return;
    const data = document.getElementById('opensquilla-data');
    const base = data?.dataset.basePath || '';
    const cssVersion = data?.dataset.version || '';
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${base}/static/css/views/skills.css${cssVersion ? '?v=' + encodeURIComponent(cssVersion) : ''}`;
    link.dataset.viewCss = 'skills';
    document.head.appendChild(link);
  }

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _ensureCss();

    _el.innerHTML = `
      <div class="sk-stage">
        <header class="sk-stage__header">
          <div class="sk-stage__title-block">
            <span class="sk-stage__eyebrow">Control · Skills</span>
            <h2 class="sk-stage__title">Skills</h2>
            <p class="sk-stage__subtitle">Composable agent capabilities: bundled OpenSquilla skills plus local managed, personal, project, and workspace packs.</p>
          </div>
          <div class="sk-stage__actions">
            <div class="sk-search-wrap" id="sk-search-wrap">
              <span class="sk-search-icon">${icons.search()}</span>
              <input class="sk-search-input" type="search" id="skills-filter" placeholder="Filter skills…" autocomplete="off" />
            </div>
            <button class="btn btn--ghost" id="skills-refresh" title="Refresh">
              ${icons.refresh()}<span>Refresh</span>
            </button>
          </div>
        </header>

        <section class="sk-stats" id="sk-stats"></section>

        <div class="sk-tabs" role="group" aria-label="Skill source">
          <button class="sk-tab is-active" data-tab="installed" aria-pressed="true">${icons.skills()}<span>Installed</span></button>
          <button class="sk-tab" data-tab="registry" aria-pressed="false">${icons.download()}<span>Community</span></button>
        </div>

        <div id="skills-tab-installed" class="sk-panel">
          <div id="skills-installed-wrap"></div>
        </div>
        <div id="skills-tab-registry" class="sk-panel" hidden>
          <div class="sk-registry">
            <div class="sk-registry__head">
              <div class="sk-search-wrap sk-search-wrap--lg">
                <span class="sk-search-icon">${icons.search()}</span>
                <input class="sk-search-input sk-search-input--lg" type="search" id="skills-registry-search" placeholder="Search community skills..." autocomplete="off" />
              </div>
              <button class="btn btn--primary" id="skills-registry-search-btn">Search</button>
            </div>
            <div class="sk-github-install">
              <div class="sk-search-wrap sk-search-wrap--lg">
                <span class="sk-search-icon">${icons.download()}</span>
                <input class="sk-search-input sk-search-input--lg" type="url" id="skills-github-url" placeholder="https://github.com/owner/repo/tree/main/path/to/skill" autocomplete="off" />
              </div>
              <button class="btn btn--primary" id="skills-github-install">Install GitHub URL</button>
            </div>
            <div id="skills-registry-results" class="sk-registry__results">
              <div class="sk-registry__hint">
                <div class="sk-registry__hint-icon">${icons.skills()}</div>
                <p>Search ClawHub skills to browse and install.</p>
                <p class="sk-dim">Paste a GitHub skill URL above for direct install.</p>
              </div>
            </div>
          </div>
        </div>

        <dialog id="skill-detail-dialog" class="sk-dialog">
          <div id="skill-detail-body"></div>
        </dialog>
      </div>`;

    // Dialog backdrop and close-button click → close (attach once, not per-open).
    const _dlg = _el.querySelector('#skill-detail-dialog');
    if (_dlg && !_dlg.dataset.closeHandler) {
      _dlg.addEventListener('click', (e) => {
        const closeTarget = e.target && typeof e.target.closest === 'function'
          ? e.target.closest('[data-dialog-close]')
          : null;
        if (closeTarget) {
          e.preventDefault();
          e.stopPropagation();
          _closeSkillDialog(_dlg);
          return;
        }
        if (e.target === _dlg) _closeSkillDialog(_dlg);
      });
      _dlg.addEventListener('cancel', (e) => {
        e.preventDefault();
        _closeSkillDialog(_dlg);
      });
      _dlg.dataset.closeHandler = '1';
    }

    const _filterInput = _el.querySelector('#skills-filter');
    const _searchWrap = _el.querySelector('#sk-search-wrap');
    _el.querySelectorAll('.sk-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        _activeTab = btn.dataset.tab;
        _el.querySelectorAll('.sk-tab').forEach(b => {
          const active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        _el.querySelectorAll('.sk-panel').forEach(p => { p.hidden = true; });
        const panel = _el.querySelector('#skills-tab-' + btn.dataset.tab);
        if (panel) panel.hidden = false;
        if (_searchWrap) _searchWrap.style.visibility = btn.dataset.tab === 'installed' ? '' : 'hidden';
      });
    });

    _el.querySelector('#skills-refresh').addEventListener('click', _loadData);

    _filterInput.addEventListener('input', () => {
      _filterText = _filterInput.value.toLowerCase();
      _renderCards();
    });

    // Registry search
    const searchBtn = _el.querySelector('#skills-registry-search-btn');
    const searchInput = _el.querySelector('#skills-registry-search');
    const githubBtn = _el.querySelector('#skills-github-install');
    const githubInput = _el.querySelector('#skills-github-url');
    if (searchBtn) {
      searchBtn.addEventListener('click', () => _searchRegistry(searchInput.value));
      searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') _searchRegistry(searchInput.value);
      });
    }
    if (githubBtn && githubInput) {
      githubBtn.addEventListener('click', () => {
        if (githubInput.value.trim()) _installSkill(githubInput.value.trim(), 'github', githubBtn);
      });
      githubInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && githubInput.value.trim()) _installSkill(githubInput.value.trim(), 'github', githubBtn);
      });
    }

    // Delegate install / uninstall / card / status-filter / deps-install clicks
    _el.addEventListener('click', (e) => {
      const installBtn = e.target.closest('[data-install]');
      if (installBtn) {
        _installSkill(installBtn.dataset.install, installBtn.dataset.source || 'clawhub', installBtn);
        return;
      }
      const uninstallBtn = e.target.closest('[data-uninstall]');
      if (uninstallBtn) {
        _uninstallSkill(uninstallBtn.dataset.uninstall, uninstallBtn);
        return;
      }
      const statusPill = e.target.closest('[data-status-filter]');
      if (statusPill) {
        const v = statusPill.dataset.statusFilter;
        if (v === 'proposals') {
          // Proposals tile: not a real filter — scroll to the section.
          const target = _el.querySelector('.sk-group--proposals');
          if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          return;
        }
        _statusFilter = v;
        _renderStats();
        _renderCards();
        return;
      }
      const depsBtn = e.target.closest('[data-install-deps-name]');
      if (depsBtn) {
        _installDeps(depsBtn.dataset.installDepsName, depsBtn.dataset.installDepsId, depsBtn);
        return;
      }
      const propShow = e.target.closest('[data-proposal-show]');
      if (propShow) { _showProposal(propShow.dataset.proposalShow); return; }
      const apToggle = e.target.closest('[data-ap-toggle]');
      if (apToggle) {
        // Fires on the checkbox click; the new checked state is already
        // reflected in apToggle.checked.
        _toggleAutoPropose(apToggle.dataset.apToggle, apToggle.checked, apToggle);
        return;
      }
      const propAccept = e.target.closest('[data-proposal-accept]');
      if (propAccept) { _acceptProposal(propAccept.dataset.proposalAccept); return; }
      const propReject = e.target.closest('[data-proposal-reject]');
      if (propReject) { _rejectProposal(propReject.dataset.proposalReject); return; }
      const autoDisable = e.target.closest('[data-auto-enabled-disable]');
      if (autoDisable) { _disableAutoEnabled(autoDisable.dataset.autoEnabledDisable); return; }
      const card = e.target.closest('[data-skill-card]');
      if (card) {
        const skill = _allSkills.find(s => s.name === card.dataset.skillCard);
        if (skill) _openSkillDialog(skill);
      }
    });

    _el.addEventListener('change', (e) => {
      const apRisk = e.target.closest('[data-ap-risk-select]');
      if (apRisk) {
        _setAutoEnableRisk(apRisk.value, apRisk);
      }
    });

    _loadData();
  }

  function destroy() {
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    _allSkills = [];
    _skillDialogRequestSeq = 0;
    _skillDialogSelectedName = '';
    _el = null;
    _rpc = null;
  }

  async function _loadData() {
    if (!_el) return;
    await _rpc.waitForConnection();
    try {
      const data = await _rpc.call('skills.list');
      _allSkills = data.skills || [];
      await _loadProposals();
      _renderStats();
      _renderCards();
    } catch (err) {
      const wrap = _el && _el.querySelector('#skills-installed-wrap');
      if (wrap) {
        wrap.innerHTML = `<div class="sk-error">Failed to load skills: ${_esc(err.message)}</div>`;
      }
    }
  }

  async function _loadProposals() {
    // Path 3: meta-skill-creator's pending proposal queue. Best-effort —
    // if the gateway is too old to expose the RPC method, fall through
    // with an empty list and the skills view continues to function.
    try {
      const data = await _rpc.call('exec.proposals.list');
      _proposals = (data && data.proposals) || [];
    } catch {
      _proposals = [];
    }
    try {
      const data = await _rpc.call('exec.proposals.auto_enabled.list');
      _autoEnabledSkills = (data && data.skills) || [];
    } catch {
      _autoEnabledSkills = [];
    }
    try {
      const settings = await _rpc.call('exec.proposals.settings.get');
      _proposalsSettings = settings || _proposalsSettings;
    } catch {
      _proposalsSettings = {
        available: false,
        enabled: false,
        on_dream_complete: false,
        auto_enable: false,
        auto_enable_max_risk: 'low',
      };
    }
  }

  async function _toggleAutoPropose(key, value, button) {
    if (button) button.disabled = true;
    try {
      const out = await _rpc.call('exec.proposals.settings.set', { [key]: value });
      if (out && out.status === 'error') {
        UI.toast('Settings update failed: ' + (out.reason || 'unknown'), 'err');
        return;
      }
      _proposalsSettings = (out && out.settings) || _proposalsSettings;
      _renderStats();
      _renderCards();
    } catch (err) {
      UI.toast('Settings update failed: ' + err.message, 'err');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function _setAutoEnableRisk(value, select) {
    if (select) select.disabled = true;
    try {
      const out = await _rpc.call('exec.proposals.settings.set', { auto_enable_max_risk: value });
      if (out && out.status === 'error') {
        UI.toast('Settings update failed: ' + (out.reason || 'unknown'), 'err');
        return;
      }
      _proposalsSettings = (out && out.settings) || _proposalsSettings;
      _renderCards();
    } catch (err) {
      UI.toast('Settings update failed: ' + err.message, 'err');
    } finally {
      if (select) select.disabled = false;
    }
  }

  function _renderStats() {
    if (!_el) return;
    const wrap = _el.querySelector('#sk-stats');
    if (!wrap) return;

    const total = _allSkills.length;
    const ready = _allSkills.filter(s => s.status === 'ready').length;
    const needs = _allSkills.filter(s => s.status === 'needs_setup').length;
    const notDeclared = _allSkills.filter(s => s.status === 'not_declared').length;
    const layers = new Set();
    _allSkills.forEach(s => { if (s.layer) layers.add(s.layer); });

    const tile = (key, label, value, hint, mods = '') => {
      const active = _statusFilter === key;
      return `<button class="sk-stat ${mods}${active ? ' is-active' : ''}" data-status-filter="${key}" type="button">
        <div class="sk-stat__label">${label}</div>
        <div class="sk-stat__value">${value}</div>
        <div class="sk-stat__hint">${hint}</div>
      </button>`;
    };

    const proposalsCount = _proposals.length;
    const proposalsTile = proposalsCount > 0
      ? `<button class="sk-stat sk-stat--proposals${_statusFilter === 'proposals' ? ' is-active' : ''}" data-status-filter="proposals" type="button" title="Pending meta-skill proposals — synthesised by meta-skill-creator from your usage patterns">
          <div class="sk-stat__label">Pending Proposals</div>
          <div class="sk-stat__value"><span class="sk-stat__warn">${proposalsCount}</span></div>
          <div class="sk-stat__hint">awaiting review</div>
        </button>`
      : '';

    wrap.innerHTML = `
      ${tile('all', 'All skills', total, `${layers.size} layer${layers.size === 1 ? '' : 's'}`, 'sk-stat--accent')}
      ${tile('ready', 'Ready', `<span class="sk-stat__ok">${ready}</span>`, ready ? 'install-ready' : 'none ready')}
      ${tile('needs-setup', 'Needs setup', `<span class="sk-stat__warn">${needs}</span>`, needs ? 'awaiting deps' : 'all set')}
      ${tile('not-declared', 'Not declared', notDeclared, 'no manifest')}
      ${proposalsTile}
    `;
  }

  function _renderCards() {
    if (!_el) return;
    const wrap = _el.querySelector('#skills-installed-wrap');
    if (!wrap) return;

    let skills = _allSkills;
    if (_filterText) {
      skills = skills.filter(s =>
        (s.name || '').toLowerCase().includes(_filterText) ||
        (s.description || '').toLowerCase().includes(_filterText) ||
        (s.triggers || []).some(t => t.toLowerCase().includes(_filterText))
      );
    }
    if (_statusFilter === 'ready') {
      skills = skills.filter(s => s.status === 'ready');
    } else if (_statusFilter === 'needs-setup') {
      skills = skills.filter(s => s.status === 'needs_setup');
    } else if (_statusFilter === 'not-declared') {
      skills = skills.filter(s => s.status === 'not_declared');
    }

    if (skills.length === 0) {
      const msg = _filterText
        ? `No skills match <strong>${_esc(_filterText)}</strong>.`
        : _statusFilter === 'ready'
          ? 'No skills are ready. Install dependencies to enable them.'
          : _statusFilter === 'needs-setup'
            ? 'No skills currently need setup.'
            : _statusFilter === 'not-declared'
              ? 'No skills without declared dependencies.'
              : 'No skills installed.';
      wrap.innerHTML = `<div class="state">
        <div class="state-icon">${icons.skills()}</div>
        <p class="state-text">${msg}</p>
      </div>`;
      return;
    }

    const _rank = (s) => {
      if (s.status === 'ready') return 0;
      if (s.status === 'not_declared') return 1;
      return 2;
    };

    // Bucket: meta-skills (kind in {"meta", "meta_sop"}) get a dedicated
    // top-level group; everything else falls back to the layer-based
    // grouping. Meta-skills are conceptually different (they orchestrate
    // sub-skills) and deserve a separate visual lane.
    const metaList = [];
    const groups = {};
    skills.forEach(s => {
      const kind = s.kind || 'skill';
      if (kind === 'meta' || kind === 'meta_sop') {
        metaList.push(s);
        return;
      }
      const l = s.layer || 'extra';
      (groups[l] = groups[l] || []).push(s);
    });

    const _sortByReady = (list) => list.sort((a, b) => {
      const ra = _rank(a);
      const rb = _rank(b);
      if (ra !== rb) return ra - rb;
      return (a.name || '').localeCompare(b.name || '');
    });
    _sortByReady(metaList);
    Object.values(groups).forEach(_sortByReady);

    let html = '';

    // Auto-propose settings (always rendered when runtime is available
    // — even if there are no pending proposals — so the operator can
    // turn the feature on in the first place from a clean state).
    if (_proposalsSettings && _proposalsSettings.available) {
      html += _renderAutoProposeSettings();
    }

    // Pending proposals come below the settings. Path 3 of the
    // auto-propose feature — `meta-skill-creator` writes proposals
    // here when the cron job or dream-hook fires.
    if (_proposals.length) {
      html += `<details class="sk-group sk-group--proposals" open>
        <summary class="sk-group__head">
          <span class="sk-group__caret">▾</span>
          <span class="sk-group__label">Pending Proposals</span>
          <span class="sk-group__count">${_proposals.length}</span>
          <span class="sk-group__meta">meta-skill-creator candidates awaiting your accept/reject decision.</span>
        </summary>
        <div class="sk-proposals-list">
          ${_proposals.map(_renderProposalRow).join('')}
        </div>
      </details>`;
    }

    if (_autoEnabledSkills.length) {
      html += `<details class="sk-group sk-group--proposals" open>
        <summary class="sk-group__head">
          <span class="sk-group__caret">▾</span>
          <span class="sk-group__label">Auto-Enabled Meta-Skills</span>
          <span class="sk-group__count">${_autoEnabledSkills.length}</span>
          <span class="sk-group__meta">Promoted by auto-enable. Disable moves the skill back to pending proposals.</span>
        </summary>
        <div class="sk-proposals-list">
          ${_autoEnabledSkills.map(_renderAutoEnabledRow).join('')}
        </div>
      </details>`;
    }

    // Meta-skills group first (if any). Different summary styling so the
    // user instantly sees "this is the high-level orchestrators bucket".
    if (metaList.length) {
      html += `<details class="sk-group sk-group--meta" open>
        <summary class="sk-group__head">
          <span class="sk-group__caret">▾</span>
          <span class="sk-group__label">Meta-Skills</span>
          <span class="sk-group__count">${metaList.length}</span>
          <span class="sk-group__meta">Composed workflows that drive a DAG of sub-skills.</span>
        </summary>
        <div class="sk-grid">
          ${metaList.map(_renderCard).join('')}
        </div>
      </details>`;
    }

    _LAYER_ORDER.forEach(layer => {
      const list = groups[layer];
      if (!list || list.length === 0) return;
      html += `<details class="sk-group" open>
        <summary class="sk-group__head">
          <span class="sk-group__caret">▾</span>
          <span class="sk-group__label">${_esc(_layerLabel(layer))}</span>
          <span class="sk-group__count">${list.length}</span>
          <span class="sk-group__meta">${_esc(_layerHelp(layer))}</span>
        </summary>
        <div class="sk-grid">
          ${list.map(_renderCard).join('')}
        </div>
      </details>`;
    });

    wrap.innerHTML = html;
  }

  function _renderAutoProposeSettings() {
    const s = _proposalsSettings || {};
    const cronChecked = s.enabled ? 'checked' : '';
    const dreamChecked = s.on_dream_complete ? 'checked' : '';
    const autoEnableChecked = s.auto_enable ? 'checked' : '';
    const cronExpr = _esc(s.cron || '0 5 * * *');
    const statusOn = s.enabled || s.on_dream_complete || s.auto_enable;
    const maxRisk = _esc(s.auto_enable_max_risk || 'low');
    const riskOption = (value, label) => `<option value="${value}" ${maxRisk === value ? 'selected' : ''}>${label}</option>`;
    return `<details class="sk-group sk-group--ap-settings" ${statusOn ? 'open' : ''}>
      <summary class="sk-group__head">
        <span class="sk-group__caret">▾</span>
        <span class="sk-group__label">Auto-Propose Settings</span>
        <span class="sk-group__count">${statusOn ? 'on' : 'off'}</span>
        <span class="sk-group__meta">Off by default. Enable cron or dream to synthesize gated meta-skills from usage patterns.</span>
      </summary>
      <div class="sk-ap-settings">
        <label class="sk-ap-toggle">
          <input type="checkbox" data-ap-toggle="enabled" ${cronChecked} />
          <span class="sk-ap-toggle__label">Scheduled (cron)</span>
          <span class="sk-ap-toggle__hint">Run on <code>${cronExpr}</code>. Drives the meta-skill-creator DAG against your top co-occurrence patterns.</span>
        </label>
        <label class="sk-ap-toggle">
          <input type="checkbox" data-ap-toggle="on_dream_complete" ${dreamChecked} />
          <span class="sk-ap-toggle__label">After memory consolidation (dream)</span>
          <span class="sk-ap-toggle__hint">Piggyback on the memory-dream completion. Independent of the cron toggle.</span>
        </label>
        <label class="sk-ap-toggle">
          <input type="checkbox" data-ap-toggle="auto_enable" ${autoEnableChecked} />
          <span class="sk-ap-toggle__label">Auto-enable gated proposals</span>
          <span class="sk-ap-toggle__hint">Promote only proposals that pass all gates and stay within the configured <code>${maxRisk}</code> risk ceiling.</span>
        </label>
        <label class="sk-ap-toggle">
          <span class="sk-ap-toggle__label">Auto-enable risk ceiling</span>
          <select class="sk-ap-select" data-ap-risk-select>
            ${riskOption('low', 'Low')}
            ${riskOption('medium', 'Medium')}
            ${riskOption('high', 'High')}
          </select>
          <span class="sk-ap-toggle__hint">Low is the default. Higher ceilings still run the static safety preflight and keep audit metadata.</span>
        </label>
      </div>
    </details>`;
  }

  function _renderProposalRow(p) {
    const pid = _esc(p.proposal_id || '');
    const eligibleBadge = p.auto_enable_eligible
      ? '<span class="sk-prop-chip sk-prop-chip--ok">gates ✓</span>'
      : '<span class="sk-prop-chip sk-prop-chip--warn">gates ✗</span>';
    const autoChip = (typeof p.triggered_by === 'string' && p.triggered_by.startsWith('auto_'))
      ? `<span class="sk-prop-chip sk-prop-chip--auto" title="Auto-generated by ${_esc(p.triggered_by)}">[auto]</span>`
      : '';
    const autoDecision = p.auto_enable && p.auto_enable.status
      ? `<span class="sk-prop-chip sk-prop-chip--warn" title="${_esc(p.auto_enable.reason || '')}">auto-enable: ${_esc(p.auto_enable.status)}</span>`
      : '';
    const profile = p.auto_enable && p.auto_enable.validation_profile
      ? `<span class="sk-prop-chip" title="validation profile">${_esc(p.auto_enable.validation_profile)}</span>`
      : '';
    const chainHint = p.chain_hash
      ? `<span class="sk-prop-hash" title="chain hash">${_esc(String(p.chain_hash).slice(0, 8))}</span>`
      : '';
    return `<div class="sk-proposal-row" data-proposal-id="${pid}">
      <div class="sk-proposal-row__head">
        <code class="sk-proposal-row__id">${pid}</code>
        ${eligibleBadge}
        ${autoChip}
        ${autoDecision}
        ${profile}
        ${chainHint}
      </div>
      <div class="sk-proposal-row__actions">
        <button class="btn btn--ghost btn--sm" data-proposal-show="${pid}" type="button">Show</button>
        <button class="btn btn--primary btn--sm" data-proposal-accept="${pid}" type="button">Accept</button>
        <button class="btn btn--ghost btn--sm" data-proposal-reject="${pid}" type="button">Reject</button>
      </div>
    </div>`;
  }

  function _renderAutoEnabledRow(s) {
    const name = _esc(s.name || '');
    const risk = _esc(s.risk_level || 'unknown');
    const source = _esc(s.triggered_by || 'unknown');
    const profile = _esc(s.validation_profile || 'unknown');
    const skills = Array.isArray(s.skills) && s.skills.length
      ? `<span class="sk-prop-chip" title="Referenced skills">${s.skills.slice(0, 4).map(_esc).join(', ')}</span>`
      : '';
    const pid = s.proposal_id ? `<span class="sk-prop-hash" title="proposal id">${_esc(String(s.proposal_id))}</span>` : '';
    return `<div class="sk-proposal-row" data-auto-enabled="${name}">
      <div class="sk-proposal-row__head">
        <code class="sk-proposal-row__id">${name}</code>
        <span class="sk-prop-chip sk-prop-chip--ok">enabled</span>
        <span class="sk-prop-chip sk-prop-chip--auto">${source}</span>
        <span class="sk-prop-chip">risk: ${risk}</span>
        <span class="sk-prop-chip">${profile}</span>
        ${skills}
        ${pid}
      </div>
      <div class="sk-proposal-row__actions">
        <button class="btn btn--ghost btn--sm" data-auto-enabled-disable="${name}" type="button">Disable</button>
      </div>
    </div>`;
  }

  function _renderAutoEnableAudit(audit) {
    if (!audit || !audit.status) {
      return '<div class="sk-audit-empty">No auto-enable decision recorded.</div>';
    }
    const list = (items) => Array.isArray(items) && items.length
      ? items.map(v => `<code>${_esc(String(v))}</code>`).join(' ')
      : '<span class="sk-dim">none</span>';
    return `<div class="sk-audit-grid">
      <div><span>Status</span><strong>${_esc(audit.status)}</strong></div>
      <div><span>Risk</span><strong>${_esc(audit.risk_level || 'unknown')} / ${_esc(audit.max_risk || 'unknown')}</strong></div>
      <div><span>static-safety profile</span><strong>${_esc(audit.validation_profile || 'unknown')}</strong></div>
      <div><span>Reason</span><strong>${_esc(audit.reason || 'none')}</strong></div>
      <div class="sk-audit-grid__wide"><span>Skills</span><p>${list(audit.skills)}</p></div>
      <div class="sk-audit-grid__wide"><span>Tools</span><p>${list(audit.tools)}</p></div>
      <div class="sk-audit-grid__wide"><span>Static-safety reasons</span><p>${list(audit.reasons)}</p></div>
    </div>`;
  }

  async function _showProposal(proposalId) {
    try {
      const data = await _rpc.call('exec.proposals.show', { proposal_id: proposalId });
      if (data.status !== 'ok') {
        UI.toast('Show failed: ' + (data.reason || 'unknown'), 'err');
        return;
      }
      const dlg = _el.querySelector('#skill-detail-dialog');
      const body = _el.querySelector('#skill-detail-body');
      if (!dlg || !body) return;
      const gatesJson = JSON.stringify(data.gates || {}, null, 2);
      const auditHtml = _renderAutoEnableAudit(data.auto_enable_audit || {});
      body.innerHTML = `<div class="sk-detail">
        <header class="sk-detail__header">
          <h3>Proposal ${_esc(proposalId)}</h3>
          <button class="btn btn--ghost btn--sm" data-dialog-close type="button">Close</button>
        </header>
        <section class="sk-detail__section">
          <h4>Auto-enable Audit</h4>
          ${auditHtml}
        </section>
        <section class="sk-detail__section">
          <h4>SKILL.md</h4>
          <pre class="sk-detail__pre">${_esc(data.skill_md || '')}</pre>
        </section>
        <section class="sk-detail__section">
          <h4>Gates</h4>
          <pre class="sk-detail__pre">${_esc(gatesJson)}</pre>
        </section>
      </div>`;
      const closeBtn = body.querySelector('[data-dialog-close]');
      if (closeBtn) closeBtn.addEventListener('click', () => _closeSkillDialog(dlg));
      dlg.showModal();
    } catch (err) {
      UI.toast('Show failed: ' + err.message, 'err');
    }
  }

  async function _acceptProposal(proposalId) {
    try {
      let data = await _rpc.call('exec.proposals.accept', { proposal_id: proposalId });
      if (data.status === 'refused' && data.reason && data.reason.indexOf('gates') !== -1) {
        const ok = await UI.confirm({
          title: 'Force accept proposal?',
          message: `<p>Proposal <strong>${_esc(proposalId)}</strong> did not pass all gates.</p><p>${_esc(data.reason)}</p><p>Accept anyway?</p>`,
          confirmLabel: 'Force accept',
          danger: true,
        });
        if (!ok) return;
        data = await _rpc.call('exec.proposals.accept', { proposal_id: proposalId, force: true });
      }
      if (data.status !== 'ok') {
        UI.toast('Accept failed: ' + (data.reason || data.status), 'err');
        return;
      }
      // Reload list + cards so the proposal disappears and the new
      // skill appears under MANAGED layer.
      await _loadData();
    } catch (err) {
      UI.toast('Accept failed: ' + err.message, 'err');
    }
  }

  async function _rejectProposal(proposalId) {
    const ok = await UI.confirm({
      title: 'Reject proposal?',
      message: `<p>Reject and delete proposal <strong>${_esc(proposalId)}</strong>?</p><p>This cannot be undone.</p>`,
      confirmLabel: 'Reject proposal',
      danger: true,
    });
    if (!ok) return;
    try {
      const data = await _rpc.call('exec.proposals.reject', { proposal_id: proposalId });
      if (data.status !== 'ok') {
        UI.toast('Reject failed: ' + (data.reason || data.status), 'err');
        return;
      }
      await _loadData();
    } catch (err) {
      UI.toast('Reject failed: ' + err.message, 'err');
    }
  }

  async function _disableAutoEnabled(name) {
    const ok = await UI.confirm({
      title: 'Disable auto-enabled skill?',
      message: `<p>Disable <strong>${_esc(name)}</strong> and move it back to pending proposals?</p>`,
      confirmLabel: 'Disable skill',
      danger: true,
    });
    if (!ok) return;
    try {
      const data = await _rpc.call('exec.proposals.auto_enabled.disable', { name });
      if (data.status !== 'ok') {
        UI.toast('Disable failed: ' + (data.reason || data.status), 'err');
        return;
      }
      await _loadData();
    } catch (err) {
      UI.toast('Disable failed: ' + err.message, 'err');
    }
  }

  function _renderCard(skill) {
    const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup');
    let dotCls;
    if (status === 'ready') dotCls = 'is-ready';
    else if (status === 'needs_setup') dotCls = 'is-needs';
    else dotCls = 'is-unverified';

    const dotTitle = skill.status_detail || (skill.eligible ? 'Ready' : 'Needs setup');
    const emoji = skill.emoji ? `<span class="sk-card__emoji">${_esc(skill.emoji)}</span>` : '';
    const desc = skill.description || '';
    // Meta-skill card adds a "uses:" chip strip showing the sub-skills its
    // composition references. Limit to 6 visible chips + "+N" overflow so
    // the card height stays bounded for large DAGs.
    const isMeta = skill.kind === 'meta' || skill.kind === 'meta_sop';
    let subSkillsHtml = '';
    if (isMeta && Array.isArray(skill.sub_skills) && skill.sub_skills.length) {
      const subs = skill.sub_skills;
      const visible = subs.slice(0, 6);
      const overflow = subs.length - visible.length;
      const chips = visible
        .map(n => `<span class="sk-card__sub-chip">${_esc(n)}</span>`)
        .join('');
      const more = overflow > 0
        ? `<span class="sk-card__sub-chip sk-card__sub-chip--more">+${overflow}</span>`
        : '';
      subSkillsHtml = `<div class="sk-card__sub-row" title="Sub-skills used by this meta-skill">
        <span class="sk-card__sub-label">uses</span>
        ${chips}${more}
      </div>`;
    }
    const kindBadge = isMeta
      ? `<span class="sk-card__kind-badge" title="${_esc(skill.kind)}">${skill.kind === 'meta_sop' ? 'SOP' : 'META'}</span>`
      : '';
    const dependencyBadges = _renderDependencyBadges(skill);
    return `<button type="button" class="sk-card${isMeta ? ' sk-card--meta' : ''}" data-skill-card="${_esc(skill.name)}" title="${_esc(skill.name + (desc ? ': ' + desc : ''))}">
      <div class="sk-card__head">
        <span class="sk-card__dot ${dotCls}" title="${_esc(dotTitle)}"></span>
        ${emoji}
        <span class="sk-card__name">${_esc(skill.name)}</span>
        ${kindBadge}
      </div>
      <p class="sk-card__desc" title="${_esc(desc)}">${_esc(desc)}</p>
      ${dependencyBadges}
      ${subSkillsHtml}
    </button>`;
  }

  function _renderDependencyBadges(skill) {
    const summary = _dependencySummary(skill);
    const packageCount = summary.declared.python_packages.length;
    const binaryCount = summary.declared.binaries.all.length + (summary.declared.binaries.any.length ? 1 : 0);
    const apiEnvCount = summary.declared.api_env.all.length + (summary.declared.api_env.any.length ? 1 : 0);
    const missingCount = summary.missing.count
      + summary.sub_skill_dependencies.missing_count
      + summary.sub_skill_dependencies.missing_references.length;
    const advisoryCount = summary.inferred.python_imports.length
      + summary.inferred.api_env.length
      + summary.inferred.scan_errors.length
      + summary.sub_skill_dependencies.inferred_count;
    const badges = [];
    if (packageCount > 0) badges.push(_dependencyBadge(`py ${packageCount}`));
    if (binaryCount > 0) badges.push(_dependencyBadge(`bin ${binaryCount}`));
    if (apiEnvCount > 0) badges.push(_dependencyBadge(`env ${apiEnvCount}`));
    if (missingCount > 0) badges.push(_dependencyBadge(`missing ${missingCount}`, 'missing'));
    if (advisoryCount > 0) badges.push(_dependencyBadge(`advisory ${advisoryCount}`, 'advisory'));
    if (!badges.length) return '';
    return `<div class="sk-card__deps" aria-label="Dependency summary">${badges.join('')}</div>`;
  }

  function _dependencyBadge(label, tone = '') {
    const toneClass = tone ? ` sk-card__dep-badge--${tone}` : '';
    return `<span class="sk-card__dep-badge${toneClass}">${_esc(label)}</span>`;
  }

  async function _openSkillDialog(skill) {
    const dlg = _el.querySelector('#skill-detail-dialog');
    const body = _el.querySelector('#skill-detail-body');
    if (!dlg || !body) return;

    const requestSeq = ++_skillDialogRequestSeq;
    _skillDialogSelectedName = skill.name || '';
    _renderSkillDialogBody(dlg, body, skill, { loading: true });
    if (!dlg.open) {
      if (typeof dlg.showModal === 'function') dlg.showModal();
      else dlg.setAttribute('open', '');
    }

    let detail = skill;
    let loadError = '';
    try {
      const data = await _rpc.call('skills.get', { name: skill.name });
      if (data && data.name) detail = { ...skill, ...data };
    } catch (err) {
      detail = skill;
      loadError = err && err.message ? err.message : 'Failed to refresh details.';
    }
    if (_skillDialogRequestSeq !== requestSeq) return;
    if (_skillDialogSelectedName !== (skill.name || '')) return;
    if (!dlg.open) return;

    _renderSkillDialogBody(dlg, body, detail, { loadError });
  }

  function _renderSkillDialogBody(dlg, body, detail, { loading = false, loadError = '' } = {}) {
    const statusDetail = detail.status_detail || '';
    const status = detail.status || (detail.eligible ? 'ready' : 'needs_setup');
    let statusChip;
    if (status === 'ready') {
      statusChip = `<span class="sk-chip sk-chip--ok" title="${_esc(statusDetail)}">✓ ready</span>`;
    } else if (status === 'not_declared') {
      statusChip = `<span class="sk-chip sk-chip--unverified" title="${_esc(statusDetail)}">no deps declared</span>`;
    } else {
      statusChip = `<span class="sk-chip sk-chip--warn" title="${_esc(statusDetail)}">needs deps</span>`;
    }
    const layerChip = `<span class="sk-chip" title="${_esc(_layerHelp(detail.layer))}">${_esc(_layerLabel(detail.layer))}</span>`;
    const dependencyHtml = _renderDependencySection(detail);

    let installHtml = '';
    const installs = loading ? [] : _actionableInstallEntries(detail);
    if (installs.length) {
      const rows = installs.map(i => {
        const bins = (i.bins || []).length ? `<span class="sk-dim"> (${(i.bins || []).map(_esc).join(', ')})</span>` : '';
        const label = i.label || `Install via ${i.kind}`;
        return `<div class="sk-dialog__install-row">
          <span>${_esc(label)}${bins}</span>
          <button class="btn btn--primary btn--sm" data-install-deps-name="${_esc(detail.name)}" data-install-deps-id="${_esc(i.id)}">Install via ${_esc(i.kind)}</button>
        </div>`;
      }).join('');
      installHtml = `<div class="sk-dialog__section">
        <div class="sk-dialog__section-title">Install</div>
        ${rows}
      </div>`;
    }
    const loadingHtml = loading
      ? `<div class="sk-dialog__section"><div class="sk-dialog__section-title">Refreshing</div><div class="sk-dep-note">Loading latest dependency details…</div></div>`
      : '';
    const loadErrorHtml = loadError
      ? `<div class="sk-dialog__section"><div class="sk-dialog__section-title">Refresh</div><div class="sk-dep-note">${_esc(loadError)}</div></div>`
      : '';

    const homepage = detail.homepage
      ? `<a href="${_esc(detail.homepage)}" target="_blank" rel="noopener" class="sk-dialog__link">Homepage ↗</a>`
      : '';

    const footer = detail.file_path
      ? `<small class="sk-dim sk-dialog__path">${_esc(detail.file_path)}</small>`
      : '';

    const removeBtn = detail.layer === 'managed'
      ? `<button class="btn btn--sm" data-uninstall="${_esc(detail.name)}">Remove</button>`
      : '';

    // Meta-skill composition: render the sub-skill list as a vertical
    // chip stack. Order is preserved (parser yields composition.steps in
    // declaration order, dedup'd). Each chip is the literal skill name
    // referenced by `composition.steps[].skill` (or `routes[].skill`).
    const isMeta = detail.kind === 'meta' || detail.kind === 'meta_sop';
    let compositionHtml = '';
    if (isMeta && Array.isArray(detail.sub_skills) && detail.sub_skills.length) {
      const chips = detail.sub_skills
        .map(n => `<span class="sk-chip sk-chip--sub">${_esc(n)}</span>`)
        .join(' ');
      const kindLabel = detail.kind === 'meta_sop' ? 'meta_sop' : 'meta';
      compositionHtml = `<div class="sk-dialog__section">
        <div class="sk-dialog__section-title">Composition (${_esc(kindLabel)}, ${detail.sub_skills.length} sub-skills)</div>
        <div class="sk-dialog__sub-list">${chips}</div>
      </div>`;
    }
    let triggersHtml = '';
    if (isMeta && Array.isArray(detail.triggers) && detail.triggers.length) {
      const triggers = detail.triggers
        .map(t => `<code class="sk-chip sk-chip--trigger">${_esc(t)}</code>`)
        .join(' ');
      triggersHtml = `<div class="sk-dialog__section">
        <div class="sk-dialog__section-title">Triggers</div>
        <div class="sk-dialog__sub-list">${triggers}</div>
      </div>`;
    }

    body.innerHTML = `
      <header class="sk-dialog__head">
        <div class="sk-dialog__head-left">
          ${detail.emoji ? `<span class="sk-dialog__emoji">${_esc(detail.emoji)}</span>` : ''}
          <strong class="sk-dialog__name">${_esc(detail.name)}</strong>
          <div class="sk-dialog__chips">${layerChip} ${statusChip}</div>
        </div>
        <button type="button" class="sk-iconbtn" id="skill-dialog-close" data-dialog-close aria-label="Close">${icons.x()}</button>
      </header>
      <section class="sk-dialog__body">
        <p class="sk-dialog__desc">${_esc(detail.description || '')}</p>
        ${loadingHtml}
        ${loadErrorHtml}
        ${triggersHtml}
        ${compositionHtml}
        ${dependencyHtml}
        ${installHtml}
        ${homepage ? `<div class="sk-dialog__section">${homepage}</div>` : ''}
      </section>
      <footer class="sk-dialog__foot">
        ${footer}
        ${removeBtn}
      </footer>`;

    const closeBtn = body.querySelector('#skill-dialog-close');
    if (closeBtn) closeBtn.addEventListener('click', () => _closeSkillDialog(dlg), { once: true });
  }

  function _closeSkillDialog(dlg) {
    if (!dlg) return;
    _skillDialogRequestSeq += 1;
    _skillDialogSelectedName = '';
    try {
      if (typeof dlg.close === 'function') dlg.close();
    } catch (_err) {
      // Some browsers throw if close() is called while the dialog is not open.
    }
    if (typeof dlg.removeAttribute === 'function') dlg.removeAttribute('open');
    if ('open' in dlg) dlg.open = false;
  }

  function _renderDependencySection(skill) {
    const summary = _dependencySummary(skill);
    const blocks = [
      _renderDependencyBlock('Suggested next steps', _renderDependencySuggestions(skill, summary), '', 'sk-dep-block--suggestions'),
      _renderDependencyBlock('Declared Python Packages', _renderDeclaredPythonPackages(summary)),
      _renderDependencyBlock('Declared Binaries', _renderDeclaredRequirementList({
        all: summary.declared.binaries.all,
        any: summary.declared.binaries.any,
        kind: 'binary',
      })),
      _renderDependencyBlock('Declared API Env', _renderDeclaredRequirementList({
        all: summary.declared.api_env.all,
        any: summary.declared.api_env.any,
        kind: 'env',
      })),
      _renderDependencyBlock('Missing Dependencies', _renderMissingDependencies(summary)),
      _renderDependencyBlock('Advisory only', _renderAdvisoryDependencies(summary), 'Advisory only. Not enforced for readiness.'),
    ];
    const subSkillRollup = _renderSubSkillDependencyRollup(summary);
    if (subSkillRollup) {
      blocks.push(_renderDependencyBlock('Meta-skill sub-skill rollup', subSkillRollup, 'sub-skill rollup'));
    }
    return `<div class="sk-dialog__section">
      <div class="sk-dialog__section-title">Dependencies</div>
      <div class="sk-dep-grid">${blocks.join('')}</div>
    </div>`;
  }

  function _renderDependencyBlock(title, content, note = '', extraClass = '') {
    const noteHtml = note ? `<div class="sk-dep-note">${_esc(note)}</div>` : '';
    const className = extraClass ? `sk-dep-block ${extraClass}` : 'sk-dep-block';
    return `<section class="${className}">
      <div class="sk-dep-block__title">${_esc(title)}</div>
      ${noteHtml}
      ${content}
    </section>`;
  }

  function _renderDeclaredPythonPackages(summary) {
    const packages = summary.declared.python_packages || [];
    if (!packages.length) return '<div class="sk-dep-note">No declared Python package installs.</div>';
    return `<ul class="sk-dep-list">${packages.map(pkg => {
      const label = pkg.label || pkg.package || pkg.module || pkg.install_id || 'uv install';
      const meta = [
        pkg.install_id ? `install_id <code>${_esc(pkg.install_id)}</code>` : '',
        pkg.package ? `package <code>${_esc(pkg.package)}</code>` : '',
        pkg.module ? `module <code>${_esc(pkg.module)}</code>` : '',
      ].filter(Boolean).join(' · ');
      return `<li><strong>${_esc(label)}</strong>${meta ? `<span class="sk-dep-meta">${meta}</span>` : ''}</li>`;
    }).join('')}</ul>`;
  }

  function _renderDeclaredRequirementList({ all, any, kind }) {
    const items = [];
    (all || []).forEach(name => {
      items.push(`<li><code>${_esc(name)}</code><span class="sk-dep-meta">required ${_esc(kind)}</span></li>`);
    });
    if ((any || []).length) {
      const alternatives = any.map(name => `<code>${_esc(name)}</code>`).join(' or ');
      items.push(`<li>${alternatives}<span class="sk-dep-meta">any one ${_esc(kind)}</span></li>`);
    }
    if (!items.length) return '<div class="sk-dep-note">None declared.</div>';
    return `<ul class="sk-dep-list">${items.join('')}</ul>`;
  }

  function _renderMissingDependencies(summary) {
    const items = [];
    summary.missing.binaries.all.forEach(name => {
      items.push(`<li><code>${_esc(name)}</code><span class="sk-dep-meta">missing binary</span></li>`);
    });
    summary.missing.binaries.any.forEach(group => {
      const alternatives = Array.isArray(group) ? group.map(name => `<code>${_esc(name)}</code>`).join(' or ') : '';
      if (alternatives) items.push(`<li>${alternatives}<span class="sk-dep-meta">missing.binaries.any</span></li>`);
    });
    summary.missing.api_env.all.forEach(name => {
      items.push(`<li><code>${_esc(name)}</code><span class="sk-dep-meta">missing env</span></li>`);
    });
    summary.missing.api_env.any.forEach(group => {
      const alternatives = Array.isArray(group) ? group.map(name => `<code>${_esc(name)}</code>`).join(' or ') : '';
      if (alternatives) items.push(`<li>${alternatives}<span class="sk-dep-meta">missing.api_env.any · env var group</span></li>`);
    });
    if (!items.length) return '<div class="sk-dep-note">All declared dependencies are currently satisfied.</div>';
    return `<ul class="sk-dep-list">${items.join('')}</ul>`;
  }

  function _renderDependencySuggestions(skill, summary) {
    const suggestions = [];
    const actionableInstalls = _actionableInstallEntries(skill);
    const hasPackageSetupAction = actionableInstalls.some(install =>
      _isActionablePythonPackageInstall(install, summary, skill)
    );
    const hasMissing = summary.missing.count > 0
      || summary.missing.binaries.all.length > 0
      || summary.missing.binaries.any.length > 0
      || summary.missing.api_env.all.length > 0
      || summary.missing.api_env.any.length > 0
      || summary.sub_skill_dependencies.missing_references.length > 0
      || summary.sub_skill_dependencies.missing_count > 0;

    actionableInstalls.forEach(install => {
      const label = install.label || install.id || `Install via ${install.kind || 'installer'}`;
      suggestions.push({
        title: `Use WebUI install action: ${label}`,
        command: '',
        note: 'Prefer the install button in this dialog when it is shown; it uses the skill manifest installer and then rechecks readiness.',
      });
    });

    if (hasMissing || hasPackageSetupAction) {
      (summary.declared.python_packages || []).forEach(pkg => {
        const pkgName = pkg.package || pkg.module || pkg.label || '';
        if (!pkgName) return;
        suggestions.push({
          title: `Install Python package ${pkgName}`,
          command: `uv pip install ${pkgName}`,
          note: 'Run inside the same environment used to start this gateway, then restart or refresh the skill.',
        });
      });
    }

    summary.missing.binaries.all.forEach(name => {
      suggestions.push({
        title: `Install ${name}`,
        command: '',
        note: 'Install it with the skill install action if available, or with your OS package manager, then make sure it is available on PATH.',
      });
    });
    summary.missing.binaries.any.forEach(group => {
      const names = Array.isArray(group) ? group.filter(Boolean) : [];
      if (!names.length) return;
      suggestions.push({
        title: `Install one of ${names.join(' or ')}`,
        command: '',
        note: 'Any one option satisfies this dependency group. Reopen the dialog after installation to refresh readiness.',
      });
    });
    summary.missing.api_env.all.forEach(name => {
      suggestions.push({
        title: `Set ${name}`,
        command: `export ${name}=...`,
        note: 'Add it to the environment file used before starting the gateway, then restart the gateway so the process can read it.',
      });
    });
    summary.missing.api_env.any.forEach(group => {
      const names = Array.isArray(group) ? group.filter(Boolean) : [];
      if (!names.length) return;
      suggestions.push({
        title: `Set one of ${names.join(' or ')}`,
        command: `export ${names[0]}=...`,
        note: 'Only one variable in this group is required. Prefer the provider you actually plan to use.',
      });
    });
    summary.sub_skill_dependencies.missing_references.forEach(name => {
      suggestions.push({
        title: `Install or enable sub-skill ${name}`,
        command: `opensquilla skills install ${name}`,
        note: 'Meta-skills can only run after every referenced sub-skill is visible to the gateway. If this is an exp/bundled skill, enable it in a visible layer instead.',
      });
    });
    summary.sub_skill_dependencies.skills.forEach(item => {
      const childName = item && item.name ? String(item.name) : '';
      const childSummary = item && item.summary ? item.summary : null;
      if (!childName || !childSummary || !(childSummary.missing && childSummary.missing.count > 0)) return;
      suggestions.push({
        title: `Resolve dependencies for sub-skill ${childName}`,
        command: '',
        note: 'Open that sub-skill and follow its missing dependency suggestions first; the parent meta-skill inherits that readiness.',
      });
    });

    if (!suggestions.length) {
      return '<div class="sk-dep-note">No setup advice needed for the currently reported dependencies.</div>';
    }
    return `<ul class="sk-dep-list sk-dep-list--suggestions">${suggestions.map(item => `
      <li>
        <strong>${_esc(item.title)}</strong>
        ${item.command ? `<code class="sk-dep-command">${_esc(item.command)}</code>` : ''}
        <span class="sk-dep-meta">${_esc(item.note)}</span>
      </li>`).join('')}</ul>`;
  }

  function _renderAdvisoryDependencies(summary) {
    const items = [];
    summary.inferred.python_imports.forEach(item => {
      items.push(`<li><code>${_esc(item.module || '')}</code><span class="sk-dep-meta">import from ${_esc(item.source || 'unknown')} · Advisory only</span></li>`);
    });
    summary.inferred.api_env.forEach(item => {
      const sources = Array.isArray(item.sources) ? item.sources.join(', ') : '';
      items.push(`<li><code>${_esc(item.name || '')}</code><span class="sk-dep-meta">seen in ${_esc(sources || 'unknown')} · Advisory only</span></li>`);
    });
    summary.inferred.scan_errors.forEach(item => {
      items.push(`<li><code>scan_errors</code><span class="sk-dep-meta">${_esc(item)}</span></li>`);
    });
    if (!items.length) return '<div class="sk-dep-note">No advisory dependencies inferred.</div>';
    return `<ul class="sk-dep-list">${items.join('')}</ul>`;
  }

  function _renderSubSkillDependencyRollup(summary) {
    const rollup = summary.sub_skill_dependencies || {};
    const childRows = [];
    (rollup.skills || []).forEach(entry => {
      const childSummary = _dependencySummary({ dependency_summary: entry.summary || {} });
      const childMissing = childSummary.missing.count
        + childSummary.sub_skill_dependencies.missing_count
        + childSummary.sub_skill_dependencies.missing_references.length;
      const childAdvisory = childSummary.inferred.python_imports.length
        + childSummary.inferred.api_env.length
        + childSummary.inferred.scan_errors.length
        + childSummary.sub_skill_dependencies.inferred_count;
      childRows.push(`<div class="sk-dep-subskill-row">
        <code>${_esc(entry.name || '')}</code>
        <span class="sk-dep-subskill-metrics">missing ${childMissing} · advisory ${childAdvisory}</span>
      </div>`);
    });
    (rollup.missing_references || []).forEach(name => {
      childRows.push(`<div class="sk-dep-subskill-row">
        <code>${_esc(name)}</code>
        <span class="sk-dep-subskill-metrics">missing reference</span>
      </div>`);
    });
    const hasRollup = childRows.length
      || rollup.missing_count
      || rollup.inferred_count
      || (rollup.missing_references || []).length;
    if (!hasRollup) return '';
    return `
      <div class="sk-dep-summary">
        <span class="sk-chip">skills ${_esc((rollup.skills || []).length)}</span>
        <span class="sk-chip sk-chip--warn">missing ${_esc(rollup.missing_count || 0)}</span>
        <span class="sk-chip">inferred ${_esc(rollup.inferred_count || 0)}</span>
        <span class="sk-chip">${_esc((rollup.missing_references || []).length)} unresolved refs</span>
      </div>
      ${childRows.length ? `<div class="sk-dep-subskills">${childRows.join('')}</div>` : '<div class="sk-dep-note">No referenced sub-skills reported.</div>'}
    `;
  }

  function _dependencySummary(skill) {
    const raw = skill && skill.dependency_summary ? skill.dependency_summary : {};
    const declaredBinariesAny = Array.isArray(raw?.declared?.binaries?.any) ? raw.declared.binaries.any.slice() : [];
    const declaredApiEnvAny = Array.isArray(raw?.declared?.api_env?.any) ? raw.declared.api_env.any.slice() : [];
    const missingBinsAny = Array.isArray(raw?.missing?.binaries?.any) ? raw.missing.binaries.any.map(group => Array.isArray(group) ? group.slice() : []) : [];
    const missingApiAny = Array.isArray(raw?.missing?.api_env?.any) ? raw.missing.api_env.any.map(group => Array.isArray(group) ? group.slice() : []) : [];
    const summary = {
      declared: {
        binaries: {
          all: Array.isArray(raw?.declared?.binaries?.all) ? raw.declared.binaries.all.slice() : [],
          any: declaredBinariesAny,
        },
        python_packages: Array.isArray(raw?.declared?.python_packages) ? raw.declared.python_packages.slice() : [],
        api_env: {
          all: Array.isArray(raw?.declared?.api_env?.all) ? raw.declared.api_env.all.slice() : [],
          any: declaredApiEnvAny,
        },
      },
      missing: {
        binaries: {
          all: Array.isArray(raw?.missing?.binaries?.all) ? raw.missing.binaries.all.slice() : [],
          any: missingBinsAny,
        },
        api_env: {
          all: Array.isArray(raw?.missing?.api_env?.all) ? raw.missing.api_env.all.slice() : [],
          any: missingApiAny,
        },
        count: Number.isFinite(raw?.missing?.count) ? raw.missing.count : 0,
      },
      inferred: {
        python_imports: Array.isArray(raw?.inferred?.python_imports) ? raw.inferred.python_imports.slice() : [],
        api_env: Array.isArray(raw?.inferred?.api_env) ? raw.inferred.api_env.slice() : [],
        scan_errors: Array.isArray(raw?.inferred?.scan_errors) ? raw.inferred.scan_errors.slice() : [],
      },
      sub_skill_dependencies: {
        skills: Array.isArray(raw?.sub_skill_dependencies?.skills) ? raw.sub_skill_dependencies.skills.slice() : [],
        missing_count: Number.isFinite(raw?.sub_skill_dependencies?.missing_count) ? raw.sub_skill_dependencies.missing_count : 0,
        inferred_count: Number.isFinite(raw?.sub_skill_dependencies?.inferred_count) ? raw.sub_skill_dependencies.inferred_count : 0,
        missing_references: Array.isArray(raw?.sub_skill_dependencies?.missing_references) ? raw.sub_skill_dependencies.missing_references.slice() : [],
      },
      declaration_quality: raw?.declaration_quality || 'none',
    };
    if (!raw || Object.keys(raw).length === 0) {
      summary.missing.binaries.all = Array.isArray(skill?.missing_bins) ? skill.missing_bins.slice() : [];
      summary.missing.api_env.all = Array.isArray(skill?.missing_env) ? skill.missing_env.slice() : [];
      summary.missing.api_env.any = Array.isArray(skill?.missing_env_any)
        ? skill.missing_env_any.map(group => Array.isArray(group) ? group.slice() : [])
        : [];
    }
    if (!summary.missing.count) {
      summary.missing.count = summary.missing.binaries.all.length
        + summary.missing.binaries.any.length
        + summary.missing.api_env.all.length
        + summary.missing.api_env.any.length;
    }
    return summary;
  }

  function _actionableInstallEntries(skill) {
    const installs = Array.isArray(skill?.install) ? skill.install : [];
    if (!installs.length) return [];
    const summary = _dependencySummary(skill);
    const missingAll = new Set(summary.missing.binaries.all || []);
    const missingAny = Array.isArray(summary.missing.binaries.any) ? summary.missing.binaries.any : [];
    return installs.filter(install => {
      if (_isActionablePythonPackageInstall(install, summary, skill)) return true;
      const bins = Array.isArray(install?.bins) ? install.bins.filter(Boolean) : [];
      if (missingAll.size === 0 && missingAny.length === 0) return false;
      if (!bins.length) return true;
      if (bins.some(bin => missingAll.has(bin))) return true;
      return missingAny.some(group =>
        Array.isArray(group) && group.some(bin => bins.includes(bin))
      );
    });
  }

  function _isActionablePythonPackageInstall(install, summary, skill) {
    if (!install || String(install.kind || '').toLowerCase() !== 'uv') return false;
    const status = String(skill?.status || '').toLowerCase();
    if (status === 'ready' || status === 'enabled') return false;
    const bins = Array.isArray(install.bins) ? install.bins.filter(Boolean) : [];
    if (bins.length) return false;
    const packages = summary.declared.python_packages || [];
    if (!packages.length) return false;
    const installKeys = [install.id, install.install_id, install.package, install.module, install.label]
      .filter(Boolean)
      .map(value => String(value));
    if (!installKeys.length) return false;
    return packages.some(pkg => {
      const packageKeys = [pkg.install_id, pkg.package, pkg.module, pkg.label]
        .filter(Boolean)
        .map(value => String(value));
      return packageKeys.some(key => installKeys.includes(key));
    });
  }

  async function _installDeps(name, installId, btn) {
    if (!_rpc || !name || !installId) return;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Installing…';
    try {
      const res = await _rpc.call('skills.deps.install', { name, install_id: installId });
      if (res.success) {
        btn.textContent = '✓ Installed';
        UI.toast(res.message || 'Installed', 'ok');
      } else {
        btn.textContent = 'Failed';
        btn.disabled = false;
        UI.toast(res.message || 'Install failed', 'err');
      }
      const still = res.missing_still || {};
      const stillMissing = (still.bins || []).length + (still.env || []).length + (still.env_any || []).length;
      if (stillMissing === 0) {
        setTimeout(() => {
          const dlg = _el && _el.querySelector('#skill-detail-dialog');
          if (dlg && dlg.open) dlg.close();
        }, 600);
      }
      await _loadData();
    } catch (err) {
      btn.textContent = originalText;
      btn.disabled = false;
      UI.toast(err.message, 'err');
    }
  }

  async function _searchRegistry(query) {
    if (!_el || !_rpc || !query.trim()) return;
    const wrap = _el.querySelector('#skills-registry-results');
    if (!wrap) return;
    wrap.innerHTML = `<div class="sk-registry__loading"><span class="sk-spinner"></span> Searching ClawHub...</div>`;

    try {
      const data = await _rpc.call('skills.search', { query: query.trim(), limit: 20 });
      const results = data.results || [];
      if (results.length === 0) {
        wrap.innerHTML = `<div class="sk-registry__hint">
          <p>No results for <strong>${_esc(query)}</strong>. Try a different query.</p>
        </div>`;
        return;
      }
      let html = '<table class="sk-registry__table"><thead><tr><th>Name</th><th>Description</th><th>Source</th><th>Trust</th><th></th></tr></thead><tbody>';
      results.forEach(r => {
        const trustCls = r.trust_level === 'trusted' ? 'sk-chip--ok' : 'sk-chip--warn';
        const trustChip = `<span class="sk-chip ${trustCls}">${_esc(r.trust_level || 'community')}</span>`;
        const actionCell = r.installed
          ? `<button class="btn btn--sm" disabled>✓ Installed</button>`
          : `<button class="btn btn--primary btn--sm" data-install="${_esc(r.identifier || r.name)}" data-source="${_esc(r.source || 'clawhub')}">Install</button>`;
        html += `<tr>
          <td class="sk-registry__name">${_esc(r.name)}</td>
          <td class="sk-registry__desc">${_esc((r.description || '').slice(0, 80))}</td>
          <td class="sk-mono sk-dim">${_esc(r.source || '')}</td>
          <td>${trustChip}</td>
          <td>${actionCell}</td>
        </tr>`;
      });
      html += '</tbody></table>';
      wrap.innerHTML = html;
    } catch (err) {
      wrap.innerHTML = `<div class="sk-error">Search failed: ${_esc(err.message)}</div>`;
    }
  }

  async function _installSkill(identifier, source, btn) {
    if (!_rpc) return;
    btn.disabled = true;
    btn.textContent = 'Installing…';
    try {
      const res = await _rpc.call('skills.install', { identifier, source });
      if (res.success) {
        btn.textContent = '✓ Installed';
        btn.classList.remove('btn--primary');
        _loadData();
      } else {
        btn.textContent = 'Failed';
        UI.toast(res.message || 'Install failed', 'err');
      }
    } catch (err) {
      btn.textContent = 'Error';
      UI.toast(err.message, 'err');
    }
  }

  async function _uninstallSkill(name, btn) {
    if (!_rpc) return;
    btn.disabled = true;
    btn.textContent = 'Removing…';
    try {
      const res = await _rpc.call('skills.uninstall', { name });
      if (res.success) { _loadData(); }
      else { btn.textContent = 'Failed'; UI.toast(res.message || 'Uninstall failed', 'err'); }
    } catch (err) { btn.textContent = 'Error'; UI.toast(err.message, 'err'); }
  }

  function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _layerLabel(layer) {
    return _LAYER_LABEL[layer] || layer || 'Unknown';
  }

  function _layerHelp(layer) {
    return _LAYER_HELP[layer] || 'Configured local skill directory.';
  }

  return { render, destroy };
})();

window.SkillsView = SkillsView;
