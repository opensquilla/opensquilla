/** OpenSquilla Web UI - global approval prompt monitor. */

const ApprovalMonitor = (() => {
  const POLL_MS = 1500;
  const POLL_MAX_MS = 30000;
  let _timer = null;
  let _modal = null;
  let _modalApprovalId = null;
  let _busy = false;
  let _pollBusy = false;
  let _pollDelayMs = POLL_MS;
  let _started = false;
  let _lastToastCount = 0;

  function start() {
    if (_started) return;
    _started = true;
    _schedulePoll(0);
    window.addEventListener('focus', _onFocus);
    document.addEventListener('visibilitychange', _onVisibilityChange);
  }

  function stop() {
    _started = false;
    if (_timer) clearTimeout(_timer);
    _timer = null;
    window.removeEventListener('focus', _onFocus);
    document.removeEventListener('visibilitychange', _onVisibilityChange);
    _closeModal();
  }

  async function pollNow() {
    await _poll();
  }

  function _schedulePoll(delayMs = _pollDelayMs) {
    if (!_started) return;
    if (_timer) clearTimeout(_timer);
    _timer = setTimeout(async () => {
      _timer = null;
      await _poll();
      _schedulePoll(_pollDelayMs);
    }, delayMs);
  }

  function _resetPollBackoff() {
    _pollDelayMs = POLL_MS;
  }

  function _increasePollBackoff() {
    _pollDelayMs = Math.min(POLL_MAX_MS, Math.max(POLL_MS, _pollDelayMs * 2));
  }

  function _authHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    const token = (typeof App !== 'undefined' && App.getAuthToken && App.getAuthToken()) || '';
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return headers;
  }

  async function _poll() {
    if (_pollBusy) return;
    _pollBusy = true;
    try {
      const resp = await fetch('/api/approvals', {
        cache: 'no-store',
        headers: _authHeaders(),
      });
      if (!resp.ok) {
        _setBadge(0);
        _increasePollBackoff();
        return;
      }
      const data = await resp.json();
      const pending = Array.isArray(data.pending) ? data.pending : [];
      _setBadge(pending.length);
      _notifyPending(pending);
      if (pending.length > 0) _resetPollBackoff();
      else _increasePollBackoff();

      const modalStillPending = _modalApprovalId
        && pending.some((item) => String(item.id || '') === _modalApprovalId);
      if (_modal && !modalStillPending) {
        _closeModal();
      }

      if (pending.length > 0 && pending.length !== _lastToastCount) {
        _lastToastCount = pending.length;
        UI.toast('Approval required', 'warn', 2500);
      } else if (pending.length === 0) {
        _lastToastCount = 0;
      }

      if (_modal || pending.length === 0) return;
      _openModal(pending[0], data.mode || 'prompt');
    } catch {
      _setBadge(0);
      _increasePollBackoff();
    } finally {
      _pollBusy = false;
    }
  }

  function _onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      _resetPollBackoff();
      _poll();
    }
  }

  function _onFocus() {
    _resetPollBackoff();
    _poll();
  }

  function _notifyPending(pending) {
    window.dispatchEvent(new CustomEvent('opensquilla:approvals-pending', {
      detail: { pending, count: pending.length },
    }));
  }

  function _setBadge(count) {
    const badge = document.getElementById('approval-count');
    if (badge) {
      badge.textContent = String(count);
      badge.classList.toggle('hidden', count <= 0);
    }

    const inline = document.getElementById('approval-inline');
    if (!inline) return;
    const inlineText = count === 1 ? 'Approval required' : `${count} approvals required`;
    inline.textContent = inlineText;
    inline.setAttribute('aria-label', inlineText);
    inline.title = inlineText;
    inline.classList.toggle('hidden', count <= 0);
    if (!inline.dataset.bound) {
      inline.dataset.bound = '1';
      inline.addEventListener('click', () => {
        if (_modal) return;
        _resetPollBackoff();
        _poll();
      });
    }
  }

  function _openModal(item, mode) {
    _closeModal();
    _modalApprovalId = String(item.id || '');
    const overlay = document.createElement('div');
    overlay.className = 'modal-backdrop';

    const canAlways = item.namespace === 'exec' && !!item.command;
    const customChoices = Array.isArray(item.params && item.params.choices) ? item.params.choices : [];
    const title = _approvalTitle(item);
    const command = _approvalCommand(item);
    const detail = _approvalDetailHtml(item);
    const meta = _approvalMeta(item, mode);
    const footer = customChoices.length > 0
      ? _renderCustomChoices(customChoices)
      : `
          <button class="btn btn--primary" data-approval-action="once" title="Approve only this pending tool call">Approve This Time</button>
          ${canAlways ? '<button class="btn btn--ghost" data-approval-action="always" title="Remember this operation type for future matching intents">Always Allow This Type</button>' : ''}
          <button class="btn btn--danger" data-approval-action="deny">Deny</button>
        `;

    overlay.innerHTML = `
      <div class="modal approval-modal" role="dialog" aria-modal="true" aria-labelledby="approval-modal-title">
        <div class="modal-title" id="approval-modal-title">${_esc(title)}</div>
        <div class="modal-body">
          <div class="approval-modal-tool">${_esc(_approvalToolLabel(item))}</div>
          ${meta ? `<div class="approval-modal-meta">${_esc(meta)}</div>` : ''}
          ${command ? `<pre class="approval-modal-command">${_esc(command)}</pre>` : ''}
          ${detail}
        </div>
        <div class="modal-foot">
          ${footer}
        </div>
      </div>`;

    overlay.querySelectorAll('[data-choice-id]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const choiceId = btn.dataset.choiceId || '';
        const approved = btn.dataset.approved !== 'false';
        _resolve(
          item,
          {
            approved,
            allowAlways: false,
            rememberIntent: false,
            choice: choiceId,
            decision: choiceId,
          },
          overlay,
        );
      });
    });
    overlay.querySelectorAll('[data-approval-action]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.approvalAction;
        const approved = action === 'once' || action === 'always';
        const allowAlways = action === 'always';
        const rememberIntent = action === 'always';
        _resolve(item, { approved, allowAlways, rememberIntent }, overlay);
      });
    });

    document.body.appendChild(overlay);
    _modal = overlay;
  }

  function _renderCustomChoices(customChoices) {
    const buttons = customChoices.map((choice, index) => {
      const approved = choice && choice.approved !== false;
      const style = choice && choice.style
        ? String(choice.style)
        : (!approved ? 'danger' : (index === 0 ? 'primary' : 'ghost'));
      const label = choice && choice.label ? String(choice.label) : 'Choose';
      const description = choice && choice.description ? String(choice.description) : '';
      const choiceId = choice && choice.id ? String(choice.id) : '';
      const tone = _approvalChoiceTone(style);
      return `
        <button class="btn approval-modal-choice approval-modal-choice--${_esc(tone)}" data-choice-id="${_esc(choiceId)}" data-approved="${approved ? 'true' : 'false'}">
          <span class="approval-modal-choice-copy">
            <span class="approval-modal-choice-label">${_esc(label)}</span>
            ${description ? `<span class="approval-modal-choice-description">${_esc(description)}</span>` : ''}
          </span>
        </button>`;
    }).join('');
    return `<div class="approval-modal-choices">${buttons}</div>`;
  }

  function _approvalChoiceTone(style) {
    const tone = String(style || '').trim().toLowerCase();
    if (tone === 'primary' || tone === 'danger' || tone === 'warn') return tone;
    return 'ghost';
  }

  function _approvalToolLabel(item) {
    const raw = String(item.toolName || item.actionKind || '').trim();
    if (raw && raw.toLowerCase() !== 'unknown') return raw;
    const approvalKind = _approvalKind(item);
    const labels = {
      sandbox_path: 'Workspace boundary',
      sandbox_network: 'Network boundary',
      host_once: 'Sandbox fallback',
    };
    return labels[approvalKind] || raw || 'Tool execution';
  }

  function _approvalKind(item) {
    return String(item.params?.approvalKind || '').trim();
  }

  function _isSandboxApproval(item) {
    return ['sandbox_path', 'sandbox_network', 'host_once'].includes(_approvalKind(item));
  }

  function _approvalTitle(item) {
    const approvalKind = _approvalKind(item);
    if (approvalKind === 'sandbox_path') return 'Allow access outside the workspace?';
    if (approvalKind === 'sandbox_network') return 'Allow network access?';
    if (approvalKind === 'host_once') return 'Run outside the sandbox?';
    return 'Approval Required';
  }

  function _approvalMeta(item, mode) {
    if (_isSandboxApproval(item)) return '';
    return [
      item.namespace ? 'Namespace: ' + item.namespace : '',
      mode ? 'Mode: ' + mode : '',
      item.sessionKey ? 'Session: ' + item.sessionKey : '',
    ].filter(Boolean).join(' · ');
  }

  function _approvalDetailHtml(item) {
    const approvalKind = _approvalKind(item);
    if (approvalKind === 'sandbox_path') return _renderSandboxPathApproval(item);
    const detail = _approvalDetail(item);
    return detail ? `<div class="approval-modal-detail">${_esc(detail)}</div>` : '';
  }

  function _renderSandboxPathApproval(item) {
    const params = item.params || {};
    const path = String(params.path || '');
    const workspace = String(params.workspace || '');
    const requestedMount = String(params.access || 'ro').toLowerCase() === 'rw' ? 'Read/write' : 'Read-only';
    const impact = requestedMount === 'Read/write'
      ? 'If approved, OpenSquilla can read and modify files under this path.'
      : 'If approved, OpenSquilla can read/list this path and copy files into the workspace, but cannot modify the original files.';
    return `
      <div class="approval-modal-summary">
        <p>OpenSquilla needs access to a folder or file outside the current workspace.</p>
        <dl class="approval-modal-summary-grid">
          ${workspace ? `<dt>Current workspace</dt><dd>${_esc(workspace)}</dd>` : ''}
          <dt>Path requested</dt><dd>${_esc(path || 'Unknown')}</dd>
          <dt>Access needed</dt><dd>${_esc(requestedMount)}</dd>
        </dl>
        <div class="approval-modal-note">${_esc(impact)}</div>
      </div>`;
  }

  async function _resolve(item, resolution, overlay) {
    if (_busy) return;
    _busy = true;
    overlay.querySelectorAll('button').forEach((btn) => { btn.disabled = true; });
    const body = {
      id: item.id,
      namespace: item.namespace || 'exec',
      approved: !!resolution.approved,
      allowAlways: !!resolution.allowAlways,
      rememberIntent: !!resolution.rememberIntent,
    };
    if (resolution.choice) body.choice = resolution.choice;
    if (resolution.decision) body.decision = resolution.decision;
    try {
      const resp = await fetch('/api/approvals/resolve', {
        method: 'POST',
        headers: _authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        _resetPollBackoff();
        await _poll();
        throw new Error('HTTP ' + resp.status);
      }
      _closeModal();
      UI.toast(
        body.approved ? 'Approval granted' : 'Approval denied',
        body.approved ? 'info' : 'warn',
        2500
      );
      _resetPollBackoff();
      setTimeout(_poll, 150);
    } catch (err) {
      UI.toast('Approval failed: ' + err.message, 'err', 4000);
      overlay.querySelectorAll('button').forEach((btn) => { btn.disabled = false; });
    } finally {
      _busy = false;
    }
  }

  function _closeModal() {
    if (_modal) _modal.remove();
    _modal = null;
    _modalApprovalId = null;
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
      const text = JSON.stringify(args, null, 2);
      return text.length > 900 ? text.slice(0, 900) + '...' : text;
    } catch {
      return String(args);
    }
  }

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return { start, stop, pollNow };
})();

window.ApprovalMonitor = ApprovalMonitor;
