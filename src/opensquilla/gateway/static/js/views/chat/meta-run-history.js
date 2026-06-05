// MetaSkill run history panel.
// Pure-ish UI helper; chat.js supplies the RPC client and session key.

(function (root) {
  'use strict';

  async function openRunHistory(options) {
    const opts = options || {};
    const rpc = opts.rpc;
    if (!rpc || typeof rpc.call !== 'function') return null;
    if (typeof rpc.waitForConnection === 'function') {
      await rpc.waitForConnection();
    }
    const panel = renderRunHistoryPanel({ runs: [], loading: true });
    document.body.appendChild(panel);
    try {
      const payload = await rpc.call('meta.runs.list', {
        sessionKey: opts.sessionKey || '',
        limit: opts.limit || 20,
      });
      renderRunHistoryPanel(payload || {}, { rootEl: panel, rpc, sessionKey: opts.sessionKey || '' });
    } catch (err) {
      renderRunHistoryPanel({
        runs: [],
        error: err && err.message ? err.message : String(err || 'Failed to load runs'),
      }, { rootEl: panel, rpc, sessionKey: opts.sessionKey || '' });
    }
    return panel;
  }

  function renderRunHistoryPanel(payload, options) {
    const opts = options || {};
    const rootEl = opts.rootEl || document.createElement('section');
    const runs = Array.isArray(payload.runs) ? payload.runs : [];
    rootEl.className = 'meta-run-history';
    rootEl.setAttribute('role', 'region');
    rootEl.setAttribute('aria-label', 'MetaSkill run history');
    const body = payload.loading
      ? '<p class="meta-run-history__empty">Loading…</p>'
      : renderRuns(runs, payload.error);
    rootEl.innerHTML = `
      <header class="meta-run-history__head">
        <strong>MetaSkill runs</strong>
        <button data-action="close" aria-label="Close MetaSkill run history">×</button>
      </header>
      <div class="meta-run-history__body">${body}</div>
    `;
    wirePanel(rootEl, opts.rpc, opts.sessionKey || '');
    return rootEl;
  }

  function renderRuns(runs, error) {
    if (error) {
      return `<p class="meta-run-history__error">${escapeHtml(error)}</p>`;
    }
    if (!runs.length) {
      return '<p class="meta-run-history__empty">No MetaSkill runs for this session.</p>';
    }
    return `<ol class="meta-run-history__list">${runs.map(renderRun).join('')}</ol>`;
  }

  function renderRun(run) {
    const summary = run.summary || {};
    const usage = summary.usage || {};
    const cost = usage.available && usage.cost_usd != null
      ? ` · $${Number(usage.cost_usd || 0).toFixed(4)}`
      : '';
    return `
      <li class="meta-run-history__item" data-run-id="${escapeAttr(run.run_id || '')}">
        <button data-action="show" data-run-id="${escapeAttr(run.run_id || '')}">
          ${escapeHtml(run.meta_skill_name || 'meta-skill')}
        </button>
        <span>${escapeHtml(run.status || 'unknown')}${cost}</span>
        <button data-action="draft" data-run-id="${escapeAttr(run.run_id || '')}">Draft</button>
      </li>
    `;
  }

  function wirePanel(rootEl, rpc, sessionKey) {
    rootEl.querySelectorAll('[data-action]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const action = btn.getAttribute('data-action');
        const runId = btn.getAttribute('data-run-id') || '';
        if (action === 'close') {
          rootEl.remove();
          return;
        }
        if (!rpc || !runId) return;
        try {
          if (action === 'show') {
            const payload = await rpc.call('meta.runs.show', { runId });
            showRunDetail(rootEl, payload.run || payload);
          } else if (action === 'draft') {
            const payload = await rpc.call('meta.runs.draft', { runId, sessionKey });
            showRunDraft(rootEl, payload.draft || payload);
          }
        } catch (err) {
          showRunError(rootEl, err && err.message ? err.message : String(err || 'Action failed'));
        }
      });
    });
  }

  function showRunDetail(rootEl, run) {
    const detail = document.createElement('pre');
    detail.className = 'meta-run-history__detail';
    detail.textContent = JSON.stringify(run || {}, null, 2);
    rootEl.querySelector('.meta-run-history__body').appendChild(detail);
  }

  function showRunDraft(rootEl, draft) {
    const detail = document.createElement('pre');
    detail.className = 'meta-run-history__draft';
    detail.textContent = JSON.stringify(draft || {}, null, 2);
    rootEl.querySelector('.meta-run-history__body').appendChild(detail);
  }

  function showRunError(rootEl, message) {
    const detail = document.createElement('p');
    detail.className = 'meta-run-history__error';
    detail.textContent = message || 'Action failed';
    rootEl.querySelector('.meta-run-history__body').appendChild(detail);
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, '&#39;');
  }

  root.MetaRunHistory = {
    openRunHistory,
    renderRunHistoryPanel,
  };
}(typeof window !== 'undefined' ? window : globalThis));
