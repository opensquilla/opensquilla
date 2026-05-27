const HealthView = (() => {
  let _el = null;
  let _rpc = null;
  const _HIDDEN_EVIDENCE_KEYS = new Set(['restart_required', 'restartRequired']);

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    el.innerHTML = `
      <div class="health-layout health-stage">
        <header class="health-stage__header">
          <div class="health-stage__title-block">
            <span class="health-eyebrow">Control · Health</span>
            <h2>OpenSquilla Health</h2>
            <p id="health-summary">Checking readiness</p>
          </div>
          <button class="btn btn--ghost" id="health-refresh" title="Refresh health report">
            ${icons.refresh()}<span>Refresh</span>
          </button>
        </header>
        <section class="health-status__rail is-loading" id="health-strip" aria-label="Health summary"></section>
        <section class="health-findings" id="health-findings" aria-label="Health findings"></section>
      </div>`;
    el.querySelector('#health-refresh')?.addEventListener('click', _load);
    el.addEventListener('click', _onCommandCopy);
    _load();
  }

  function destroy() {
    if (_el) _el.removeEventListener('click', _onCommandCopy);
    _el = null;
    _rpc = null;
  }

  async function _onCommandCopy(event) {
    const btn = event.target.closest('[data-health-copy-command]');
    if (!btn || !_el || !_el.contains(btn)) return;
    const command = btn.dataset.healthCopyCommand || '';
    if (!command) return;
    try {
      await _copyText(command);
      UI.toast('Copied command', 'ok', 1600);
    } catch (err) {
      UI.toast('Copy failed: ' + (err.message || String(err)), 'err', 2500);
    }
  }

  function _copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      return navigator.clipboard.writeText(text);
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok ? Promise.resolve() : Promise.reject(new Error('Copy command failed'));
  }

  async function _load() {
    if (!_el || !_rpc) return;
    const summary = _el.querySelector('#health-summary');
    const strip = _el.querySelector('#health-strip');
    const findings = _el.querySelector('#health-findings');
    if (summary) summary.textContent = 'Checking readiness';
    if (strip) {
      strip.className = 'health-status__rail is-loading';
      strip.innerHTML = _renderLoadingStrip();
    }
    if (findings) findings.innerHTML = '<article class="health-empty">Loading health report</article>';
    try {
      await _rpc.waitForConnection();
      const report = await _rpc.call('doctor.status', { agentId: 'main', deep: true });
      if (!report.gatewayUrl) report.gatewayUrl = _gatewayContextUrl();
      if (!_el) return;
      if (summary) summary.textContent = report.summary || report.status || 'Health report loaded';
      if (strip) {
        strip.className = `health-status__rail is-${_classToken(report.status || 'unknown')}`;
        strip.innerHTML = _renderStrip(report);
      }
      if (findings) findings.innerHTML = _renderFindings(report.findings || []);
    } catch (err) {
      const gatewayUrl = _gatewayContextUrl();
      const configPath = _usesDefaultGatewayUrl(gatewayUrl) ? _bootstrapConfigPath() : '';
      if (summary) summary.textContent = 'Health report unavailable';
      if (strip) {
        strip.className = 'health-status__rail is-unavailable';
        strip.innerHTML = _renderStrip({
          status: 'unavailable',
          ready: false,
          summary: 'Gateway health report unavailable',
          gatewayUrl,
          configPath,
          counts: { error: 1, warn: 0, info: 0, ok: 0 },
          impactCounts: { blocks_ready: 1, degrades: 0, optional: 0, none: 0 },
        });
      }
      if (findings) {
        findings.innerHTML = _renderFindings([{
          id: 'gateway.unavailable',
          severity: 'error',
          readinessImpact: 'blocks_ready',
          surface: 'gateway',
          title: 'Gateway health report unavailable',
          detail: _gatewayUnavailableDetail(gatewayUrl, err),
          evidence: configPath ? { gatewayUrl, configPath } : { gatewayUrl },
          fixSteps: _gatewayUnavailableFixSteps(gatewayUrl),
          restartRequired: false,
        }]);
      }
    }
  }

  function _renderLoadingStrip() {
    return `
      <div class="health-score">
        <span class="health-score__label">Readiness</span>
        <strong>Checking</strong>
        <span class="health-score__summary">Waiting for doctor.status</span>
      </div>
      <div class="health-count-grid">
        ${_countTile('Needs action', 0, 'blocks_ready')}
        ${_countTile('Degraded', 0, 'degrades')}
        ${_countTile('Optional', 0, 'optional')}
        ${_countTile('Ready', 0, 'none')}
      </div>`;
  }

  function _renderStrip(report) {
    const impactCounts = report.impactCounts || _impactCountsFromSeverity(report.counts || {});
    const status = report.status || 'unknown';
    const context = _renderReportContext(report);
    return `
      <div class="health-score">
        <span class="health-score__label">Readiness</span>
        <strong>${_esc(_statusLabel(status, report.ready))}</strong>
        <span class="health-score__summary">${_esc(report.summary || status)}</span>
        ${context}
      </div>
      <div class="health-count-grid">
        ${_countTile('Needs action', impactCounts.blocks_ready || 0, 'blocks_ready')}
        ${_countTile('Degraded', impactCounts.degrades || 0, 'degrades')}
        ${_countTile('Optional', impactCounts.optional || 0, 'optional')}
        ${_countTile('Ready', impactCounts.none || 0, 'none')}
    </div>`;
  }

  function _renderReportContext(report) {
    const items = [];
    const gatewayUrl = report.gatewayUrl || _gatewayContextUrl();
    if (gatewayUrl) items.push(['Gateway', gatewayUrl]);
    if (report.configPath) items.push(['Config', report.configPath]);
    if (report.requestedConfigPath && report.requestedConfigPath !== report.configPath) {
      items.push(['Requested config', report.requestedConfigPath]);
    }
    if (report.agentId) items.push(['Agent', report.agentId]);
    if (!items.length) return '';
    const contextItems = items.map(([label, value]) => `
        <span class="health-report-context__item">
          <b>${_esc(label)}</b>
          <span class="health-report-context__value">${_esc(value)}</span>
        </span>`).join('');
    return `<div class="health-report-context" aria-label="Health report context">
      ${contextItems}
    </div>`;
  }

  function _gatewayContextUrl() {
    if (typeof App === 'undefined') return '';
    try {
      if (typeof App.loadConnectionSettings === 'function') {
        return App.loadConnectionSettings().url || '';
      }
    } catch {}
    try {
      if (typeof App.getDefaultRpcUrl === 'function') {
        return App.getDefaultRpcUrl() || '';
      }
    } catch {}
    return '';
  }

  function _bootstrapConfigPath() {
    return document.getElementById('opensquilla-data')?.dataset.configPath || '';
  }

  function _gatewayUnavailableDetail(gatewayUrl, err) {
    const reason = err?.message || String(err);
    if (!gatewayUrl) return reason;
    return `Cannot load doctor.status from ${gatewayUrl}. ${reason}`;
  }

  function _gatewayUnavailableFixSteps(gatewayUrl) {
    if (!_isLocalGatewayUrl(gatewayUrl)) {
      return [
        {
          label: 'Inspect remote gateway',
          command: `opensquilla gateway status --gateway ${_shellArg(gatewayUrl)} --json`,
        },
        {
          label: 'Repair remote deployment',
          detail: 'Start or repair the remote OpenSquilla gateway deployment, then refresh health.',
        },
      ];
    }
    const target = _gatewayStatusTarget(gatewayUrl);
    const bindArgs = target ? ` --bind ${target.host} --port ${target.port}` : '';
    const useConfigTarget = _usesDefaultGatewayUrl(gatewayUrl) && Boolean(_bootstrapConfigPath());
    const doctorTarget = useConfigTarget ? '' : (gatewayUrl ? ` --gateway ${_shellArg(gatewayUrl)}` : '');
    const configTarget = useConfigTarget ? _configOption(_bootstrapConfigPath()) : '';
    const targetArgs = useConfigTarget ? '' : bindArgs;
    return [
      {
        label: 'Run local doctor',
        command: `opensquilla doctor${doctorTarget}${configTarget} --json`,
        detail: 'Checks local config and onboarding before restarting the gateway.',
      },
      { label: 'Start local gateway', command: `opensquilla gateway start${targetArgs}${configTarget}` },
      { label: 'Inspect local gateway', command: `opensquilla gateway status${targetArgs} --json${configTarget}` },
    ];
  }

  function _usesDefaultGatewayUrl(gatewayUrl) {
    if (typeof App === 'undefined' || typeof App.getDefaultRpcUrl !== 'function') return false;
    try {
      const requested = new URL(gatewayUrl || App.getDefaultRpcUrl(), location.href);
      const defaults = new URL(App.getDefaultRpcUrl(), location.href);
      return requested.protocol === defaults.protocol
        && requested.host === defaults.host
        && requested.pathname === defaults.pathname;
    } catch {
      return false;
    }
  }

  function _configOption(configPath) {
    return configPath ? ` --config ${_shellArg(configPath)}` : '';
  }

  function _shellArg(value) {
    const text = String(value || '');
    if (/^[A-Za-z0-9_@%+=:,./~-]+$/.test(text)) return text;
    return `'${text.replace(/'/g, `'\\''`)}'`;
  }

  function _isLocalGatewayUrl(gatewayUrl) {
    const target = _gatewayStatusTarget(gatewayUrl);
    if (!target) return true;
    return ['127.0.0.1', '::1', 'localhost', '0.0.0.0'].includes(target.host);
  }

  function _gatewayStatusTarget(gatewayUrl) {
    try {
      const url = new URL(gatewayUrl || App.getDefaultRpcUrl());
      let host = url.hostname || '127.0.0.1';
      if (host.startsWith('[') && host.endsWith(']')) host = host.slice(1, -1);
      if (host === '0.0.0.0') host = '127.0.0.1';
      if (host === '::') host = '::1';
      const port = url.port || ((url.protocol === 'wss:' || url.protocol === 'https:') ? '443' : '18791');
      return { host, port };
    } catch {
      return null;
    }
  }

  function _countTile(label, value, kind) {
    return `<div class="health-count is-${_classToken(kind)}">
      <span>${_esc(label)}</span>
      <strong>${Number(value || 0)}</strong>
    </div>`;
  }

  function _renderFindings(findings) {
    if (!findings.length) {
      return '<article class="health-empty">No findings returned.</article>';
    }
    const groups = [
      {
        title: 'Needs action',
        note: 'Fix these first to make OpenSquilla ready.',
        findings: findings.filter(finding => _findingGroupKind(finding) === 'action'),
      },
      {
        title: 'Degraded capabilities',
        note: 'OpenSquilla can run, but these capabilities need attention.',
        findings: findings.filter(finding => _findingGroupKind(finding) === 'degraded'),
      },
      {
        title: 'Optional setup',
        note: 'These improve capability or posture but do not block readiness.',
        findings: findings.filter(finding => _findingGroupKind(finding) === 'optional'),
      },
      {
        title: 'Ready checks',
        note: 'These surfaces are already working.',
        findings: findings.filter(finding => _findingGroupKind(finding) === 'ready'),
      },
    ].filter(group => group.findings.length);

    return groups.map(group => `<section class="health-finding-group">
      <header class="health-finding-group__header">
        <div>
          <h3>${_esc(group.title)}</h3>
          <p>${_esc(group.note)}</p>
        </div>
        <span>${group.findings.length}</span>
      </header>
      ${group.findings.map((finding, index) => _renderFinding(finding, index)).join('')}
    </section>`).join('');
  }

  function _findingGroupKind(finding) {
    const impact = _impactValue(finding);
    if (impact === 'blocks_ready') return 'action';
    if (impact === 'degrades') return 'degraded';
    if (impact === 'optional') return 'optional';
    if (impact === 'none') return 'ready';
  }

  function _renderFinding(finding, index) {
      const kind = _findingGroupKind(finding);
      const severity = String(finding.severity || 'info');
      const impact = _impactValue(finding);
      const surface = String(finding.surface || 'system');
      const evidence = _renderEvidence(finding.evidence);
      const steps = _renderSteps(finding.fixSteps || [], kind);
      const badges = _findingBadges(finding);
      const restartRequired = finding.restartRequired
        ? '<span class="health-chip">Recovery requires restart</span>'
        : '';
      return `<article class="health-finding is-${_classToken(_findingTone(kind))}">
        <div class="health-finding__marker" aria-hidden="true">
          <span class="health-finding__dot"></span>
          <span class="health-finding__line"></span>
        </div>
        <div class="health-finding__body">
          <div class="health-finding__meta">
            <span>${_esc(severity)}</span>
            <span class="health-impact">${_esc(_impactLabel(impact))}</span>
            <span class="health-surface">${_esc(surface)}</span>
            ${badges}
            ${restartRequired}
          </div>
          <div class="health-finding__title">${_esc(finding.title || finding.id || `Finding ${index + 1}`)}</div>
          <div class="health-finding__detail">${_esc(finding.detail || '')}</div>
          ${evidence}
          ${steps}
        </div>
      </article>`;
  }

  function _findingBadges(finding) {
    const id = String(finding?.id || '');
    if (id.endsWith('.diagnostic.incomplete')) {
      return '<span class="health-chip health-chip--diagnostic">Diagnostics incomplete</span>';
    }
    if (id.endsWith('.repair.pending')) {
      return '<span class="health-chip health-chip--repair">Repair pending</span>';
    }
    if (id === 'gateway.config.mismatch') {
      return '<span class="health-chip health-chip--config">Config mismatch</span>';
    }
    return '';
  }

  function _renderSteps(steps, kind) {
    if (!steps.length) return '';
    const heading = _stepsHeading(kind);
    const items = steps.map((step, index) => {
      const command = step.command ? _renderCommand(step.command) : '';
      const detail = step.detail ? `<span class="health-step__detail">${_esc(step.detail)}</span>` : '';
      const label = _esc(step.label || 'Step');
      return `<li class="health-step">
        <span class="health-step__number">${index + 1}</span>
        <span class="health-step__body"><b>${label}</b>${command}${detail}</span>
      </li>`;
    }).join('');
    return `<div class="health-steps">
      <div class="health-steps__heading">${_esc(heading)}</div>
      <ol>${items}</ol>
    </div>`;
  }

  function _renderCommand(command) {
    return `<span class="health-step__command">
      <code>${_esc(command)}</code>
      <button class="health-step__copy" type="button" data-health-copy-command="${_esc(command)}" title="Copy command" aria-label="Copy command">
        ${icons.copy()}
      </button>
    </span>`;
  }

  function _stepsHeading(kind) {
    if (kind === 'optional') return 'Optional setup steps';
    if (kind === 'ready') return 'Reference steps';
    return 'Recovery steps';
  }

  function _impactValue(finding) {
    const impact = String(finding?.readinessImpact || '');
    if (['blocks_ready', 'degrades', 'optional', 'none'].includes(impact)) return impact;
    const severity = String(finding?.severity || 'info');
    if (severity === 'error') return 'blocks_ready';
    if (severity === 'warn') return 'degrades';
    if (severity === 'info') return 'optional';
    return 'none';
  }

  function _impactCountsFromSeverity(counts) {
    return {
      blocks_ready: Number(counts.error || 0),
      degrades: Number(counts.warn || 0),
      optional: Number(counts.info || 0),
      none: Number(counts.ok || 0),
    };
  }

  function _impactLabel(impact) {
    const labels = {
      blocks_ready: 'Blocks readiness',
      degrades: 'Degrades',
      optional: 'Optional',
      none: 'Reference',
    };
    return labels[impact] || 'Reference';
  }

  function _findingTone(kind) {
    if (kind === 'action') return 'error';
    if (kind === 'degraded') return 'warn';
    if (kind === 'optional') return 'info';
    return 'ok';
  }

  function _renderEvidence(evidence) {
    const entries = _visibleEvidenceEntries(evidence).slice(0, 6);
    if (!entries.length) return '';
    const tags = entries.map(([key, value]) => {
      return `<span><b>${_esc(_evidenceLabel(key))}</b>${_esc(_evidenceValue(value))}</span>`;
    }).join('');
    return `<div class="health-evidence" aria-label="Finding evidence">${tags}</div>`;
  }

  function _visibleEvidenceEntries(evidence) {
    return Object.entries(evidence || {})
      .filter(([key, value]) => value !== undefined && value !== null && !_HIDDEN_EVIDENCE_KEYS.has(key));
  }

  function _evidenceLabel(key) {
    const label = String(key || '')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    return label ? label.charAt(0).toUpperCase() + label.slice(1) : '';
  }

  function _statusLabel(status, ready) {
    if (ready && status === 'degraded') return 'Ready with warnings';
    if (ready) return 'Ready';
    const labels = {
      action_required: 'Action required',
      degraded: 'Degraded',
      unavailable: 'Unavailable',
      ready: 'Ready',
    };
    return labels[status] || status;
  }

  function _evidenceValue(value) {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    try {
      const text = JSON.stringify(value);
      return text.length > 120 ? `${text.slice(0, 117)}...` : text;
    } catch (err) {
      return String(value);
    }
  }

  function _classToken(value) {
    return String(value || 'unknown').toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
  }

  function _esc(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  return { render, destroy };
})();

window.HealthView = HealthView;
