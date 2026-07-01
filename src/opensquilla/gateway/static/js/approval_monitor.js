/** OpenSquilla Web UI - global approval prompt monitor. */

const ApprovalMonitor = (() => {
  const POLL_MS = 1500;
  const POLL_MAX_MS = 30000;
  const ELEVATED_MODE_KEY = 'opensquilla.elevatedMode';
  const ELEVATED_MODE_VERSION_KEY = 'opensquilla.elevatedMode.version';
  const ELEVATED_MODE_STORAGE_VERSION = '2';
  let _timer = null;
  let _modal = null;
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
        if (window.Router) Router.navigate('/approvals');
      });
    }
  }

  function _openModal(item, mode) {
    _closeModal();
    const overlay = document.createElement('div');
    overlay.className = 'modal-backdrop';

    const canAlways = item.namespace === 'exec' && !!item.command;
    const command = _approvalCommand(item);
    const detail = _approvalDetail(item);
    const meta = [
      item.namespace ? 'Namespace: ' + item.namespace : '',
      mode ? 'Mode: ' + mode : '',
      item.sessionKey ? 'Session: ' + item.sessionKey : '',
    ].filter(Boolean).join(' · ');

    overlay.innerHTML = `
      <div class="modal approval-modal" role="dialog" aria-modal="true" aria-labelledby="approval-modal-title">
        <div class="modal-title" id="approval-modal-title">Approval Required</div>
        <div class="modal-body">
          <div class="approval-modal-tool">${_esc(item.toolName || item.actionKind || 'Tool execution')}</div>
          ${meta ? `<div class="approval-modal-meta">${_esc(meta)}</div>` : ''}
          ${command ? `<pre class="approval-modal-command">${_esc(command)}</pre>` : ''}
          ${detail ? `<div class="approval-modal-detail">${_esc(detail)}</div>` : ''}
        </div>
        <div class="modal-foot">
          <button class="btn btn--primary" data-approval-action="once" title="Approve only this pending tool call">Approve This Time</button>
          ${canAlways ? '<button class="btn btn--ghost" data-approval-action="always" title="Remember this operation type for future matching intents">Always Allow This Type</button>' : ''}
          <button class="btn btn--warn" data-approval-action="bypass" title="Enable approval bypass in this browser session and approve this pending tool call">Bypass Approvals</button>
          <button class="btn btn--danger" data-approval-action="deny">Deny</button>
        </div>
      </div>`;

    overlay.querySelectorAll('[data-approval-action]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.approvalAction;
        const approved = action === 'once' || action === 'always' || action === 'bypass';
        const allowAlways = action === 'always';
        const rememberIntent = action === 'always';
        const elevatedMode = action === 'bypass' ? 'bypass' : '';
        _resolve(item, approved, allowAlways, rememberIntent, elevatedMode, overlay);
      });
    });

    document.body.appendChild(overlay);
    _modal = overlay;
  }

  async function _resolve(item, approved, allowAlways, rememberIntent, elevatedMode, overlay) {
    if (_busy) return;
    _busy = true;
    overlay.querySelectorAll('button').forEach((btn) => { btn.disabled = true; });
    const body = {
      id: item.id,
      namespace: item.namespace || 'exec',
      approved,
      allowAlways,
      rememberIntent,
    };
    if (elevatedMode) body.elevatedMode = elevatedMode;
    try {
      const resp = await fetch('/api/approvals/resolve', {
        method: 'POST',
        headers: _authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      if (elevatedMode) _setBrowserElevated(elevatedMode);
      _closeModal();
      UI.toast(
        elevatedMode ? 'Approval bypass enabled' : (approved ? 'Approval granted' : 'Approval denied'),
        approved ? 'info' : 'warn',
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
