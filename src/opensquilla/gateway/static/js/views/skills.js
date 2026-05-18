/** OpenSquilla Web UI — Skills Management view. */

const SkillsView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];
  let _allSkills = [];
  let _filterText = '';
  let _statusFilter = 'all';
  let _activeTab = 'installed';

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
    _rpc = WebUiRpc.client();
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

        <div class="sk-tabs" role="tablist" aria-label="Skill source">
          <button class="sk-tab is-active" data-tab="installed" role="tab">${icons.skills()}<span>Installed</span></button>
          <button class="sk-tab" data-tab="registry" role="tab">${icons.download()}<span>Community</span></button>
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

    // Dialog backdrop click → close (attach once, not per-open)
    const _dlg = _el.querySelector('#skill-detail-dialog');
    if (_dlg) {
      _dlg.addEventListener('click', (e) => {
        if (e.target === _dlg) _dlg.close();
      });
    }

    const _filterInput = _el.querySelector('#skills-filter');
    const _searchWrap = _el.querySelector('#sk-search-wrap');
    _el.querySelectorAll('.sk-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        _activeTab = btn.dataset.tab;
        _el.querySelectorAll('.sk-tab').forEach(b => b.classList.toggle('is-active', b === btn));
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
        _statusFilter = statusPill.dataset.statusFilter;
        _renderStats();
        _renderCards();
        return;
      }
      const depsBtn = e.target.closest('[data-install-deps-name]');
      if (depsBtn) {
        _installDeps(depsBtn.dataset.installDepsName, depsBtn.dataset.installDepsId, depsBtn);
        return;
      }
      const card = e.target.closest('[data-skill-card]');
      if (card) {
        const skill = _allSkills.find(s => s.name === card.dataset.skillCard);
        if (skill) _openSkillDialog(skill);
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
    _el = null;
    _rpc = null;
  }

  async function _loadData() {
    if (!_el) return;
    await _rpc.waitForConnection();
    try {
      const data = await _rpc.call('skills.list');
      _allSkills = data.skills || [];
      _renderStats();
      _renderCards();
    } catch (err) {
      const wrap = _el && _el.querySelector('#skills-installed-wrap');
      if (wrap) {
        wrap.innerHTML = `<div class="sk-error">Failed to load skills: ${_esc(err.message)}</div>`;
      }
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

    wrap.innerHTML = `
      ${tile('all', 'All skills', total, `${layers.size} layer${layers.size === 1 ? '' : 's'}`, 'sk-stat--accent')}
      ${tile('ready', 'Ready', `<span class="sk-stat__ok">${ready}</span>`, ready ? 'install-ready' : 'none ready')}
      ${tile('needs-setup', 'Needs setup', `<span class="sk-stat__warn">${needs}</span>`, needs ? 'awaiting deps' : 'all set')}
      ${tile('not-declared', 'Not declared', notDeclared, 'no manifest')}
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

    const groups = {};
    skills.forEach(s => {
      const l = s.layer || 'extra';
      (groups[l] = groups[l] || []).push(s);
    });

    Object.values(groups).forEach(list => {
      list.sort((a, b) => {
        const ra = _rank(a);
        const rb = _rank(b);
        if (ra !== rb) return ra - rb;
        return (a.name || '').localeCompare(b.name || '');
      });
    });

    let html = '';
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

  function _renderCard(skill) {
    const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup');
    let dotCls;
    if (status === 'ready') dotCls = 'is-ready';
    else if (status === 'needs_setup') dotCls = 'is-needs';
    else dotCls = 'is-unverified';

    const dotTitle = skill.status_detail || (skill.eligible ? 'Ready' : 'Needs setup');
    const emoji = skill.emoji ? `<span class="sk-card__emoji">${_esc(skill.emoji)}</span>` : '';
    const desc = skill.description
      ? (skill.description.length > 100 ? skill.description.slice(0, 100) + '…' : skill.description)
      : '';
    return `<button type="button" class="sk-card" data-skill-card="${_esc(skill.name)}">
      <div class="sk-card__head">
        <span class="sk-card__dot ${dotCls}" title="${_esc(dotTitle)}"></span>
        ${emoji}
        <span class="sk-card__name">${_esc(skill.name)}</span>
      </div>
      <p class="sk-card__desc">${_esc(desc)}</p>
    </button>`;
  }

  function _openSkillDialog(skill) {
    const dlg = _el.querySelector('#skill-detail-dialog');
    const body = _el.querySelector('#skill-detail-body');
    if (!dlg || !body) return;

    const statusDetail = skill.status_detail || '';
    const status = skill.status || (skill.eligible ? 'ready' : 'needs_setup');
    let statusChip;
    if (status === 'ready') {
      statusChip = `<span class="sk-chip sk-chip--ok" title="${_esc(statusDetail)}">✓ ready</span>`;
    } else if (status === 'not_declared') {
      statusChip = `<span class="sk-chip sk-chip--unverified" title="${_esc(statusDetail)}">no deps declared</span>`;
    } else {
      statusChip = `<span class="sk-chip sk-chip--warn" title="${_esc(statusDetail)}">needs deps</span>`;
    }
    const layerChip = `<span class="sk-chip" title="${_esc(_layerHelp(skill.layer))}">${_esc(_layerLabel(skill.layer))}</span>`;

    let missingHtml = '';
    if (status === 'needs_setup') {
      const missing = [];
      (skill.missing_bins || []).forEach(b => missing.push(`<li><code>${_esc(b)}</code> <span class="sk-dim">binary</span></li>`));
      (skill.missing_env || []).forEach(e => missing.push(`<li><code>${_esc(e)}</code> <span class="sk-dim">env var</span></li>`));
      if (missing.length) {
        missingHtml = `<div class="sk-dialog__section">
          <div class="sk-dialog__section-title">Missing</div>
          <ul class="sk-dialog__missing">${missing.join('')}</ul>
        </div>`;
      }
    }

    let installHtml = '';
    const hasMissingBins = (skill.missing_bins || []).length > 0;
    const installs = hasMissingBins ? (skill.install || []) : [];
    if (installs.length) {
      const rows = installs.map(i => {
        const bins = (i.bins || []).length ? `<span class="sk-dim"> (${(i.bins || []).map(_esc).join(', ')})</span>` : '';
        const label = i.label || `Install via ${i.kind}`;
        return `<div class="sk-dialog__install-row">
          <span>${_esc(label)}${bins}</span>
          <button class="btn btn--primary btn--sm" data-install-deps-name="${_esc(skill.name)}" data-install-deps-id="${_esc(i.id)}">Install via ${_esc(i.kind)}</button>
        </div>`;
      }).join('');
      installHtml = `<div class="sk-dialog__section">
        <div class="sk-dialog__section-title">Install</div>
        ${rows}
      </div>`;
    }

    const homepage = skill.homepage
      ? `<a href="${_esc(skill.homepage)}" target="_blank" rel="noopener" class="sk-dialog__link">Homepage ↗</a>`
      : '';

    const footer = skill.file_path
      ? `<small class="sk-dim sk-dialog__path">${_esc(skill.file_path)}</small>`
      : '';

    const removeBtn = skill.layer === 'managed'
      ? `<button class="btn btn--sm" data-uninstall="${_esc(skill.name)}">Remove</button>`
      : '';

    body.innerHTML = `
      <header class="sk-dialog__head">
        <div class="sk-dialog__head-left">
          ${skill.emoji ? `<span class="sk-dialog__emoji">${_esc(skill.emoji)}</span>` : ''}
          <strong class="sk-dialog__name">${_esc(skill.name)}</strong>
          <div class="sk-dialog__chips">${layerChip} ${statusChip}</div>
        </div>
        <button type="button" class="sk-iconbtn" id="skill-dialog-close" aria-label="Close">${icons.x()}</button>
      </header>
      <section class="sk-dialog__body">
        <p class="sk-dialog__desc">${_esc(_truncDesc(skill.description))}</p>
        ${missingHtml}
        ${installHtml}
        ${homepage ? `<div class="sk-dialog__section">${homepage}</div>` : ''}
      </section>
      <footer class="sk-dialog__foot">
        ${footer}
        ${removeBtn}
      </footer>`;

    const closeBtn = body.querySelector('#skill-dialog-close');
    if (closeBtn) closeBtn.addEventListener('click', () => dlg.close(), { once: true });

    if (dlg.open) dlg.close();
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
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
      const stillMissing = (still.bins || []).length + (still.env || []).length;
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

  function _truncDesc(s, n = 220) {
    if (!s) return '';
    const firstSent = s.split(/(?<=\.)\s+(?=[A-Z])/)[0] || s;
    const base = firstSent.length <= n ? firstSent : firstSent.slice(0, n).replace(/\s+\S*$/, '') + '…';
    return base;
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
