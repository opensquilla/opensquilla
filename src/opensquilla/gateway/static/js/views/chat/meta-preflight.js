// MetaSkill run preview card.
// Pure render functions; chat.js owns placement and actions.

(function (root) {
  'use strict';

  function createPreflight(payload) {
    const template = payload.request_template || {};
    return {
      runId: payload.run_id || '',
      metaSkillName: payload.meta_skill_name || '',
      interpretedRequest: payload.interpreted_request || '',
      missingFields: payload.missing_fields || [],
      assumptions: payload.assumptions || [],
      outcome: template.outcome || template.deliverable || '',
      canSkip: payload.can_skip !== false,
    };
  }

  function renderPreflight(rootEl, state) {
    rootEl.classList.add('meta-preflight');
    rootEl.setAttribute('data-run-id', state.runId);
    rootEl.setAttribute('role', 'region');
    rootEl.setAttribute(
      'aria-label',
      `MetaSkill ${state.metaSkillName} run preview`,
    );

    const missing = state.missingFields.length > 0
      ? `<ul class="meta-preflight-list">${state.missingFields
        .map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
      : '<p class="meta-preflight-muted">没有必填字段缺失</p>';
    const assumptions = state.assumptions.length > 0
      ? `<ul class="meta-preflight-list">${state.assumptions
        .map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
      : '<p class="meta-preflight-muted">没有额外假设</p>';

    rootEl.innerHTML = `
      <header class="meta-preflight-head">
        <span class="meta-preflight-title">${escapeHtml(state.metaSkillName)}</span>
        <span class="meta-preflight-badge">Confirmation</span>
      </header>
      <div class="meta-preflight-body">
        <p class="meta-preflight-request">${escapeHtml(state.interpretedRequest)}</p>
        ${state.outcome ? `<p class="meta-preflight-outcome">${escapeHtml(state.outcome)}</p>` : ''}
        <section>
          <h4>缺失字段</h4>
          ${missing}
        </section>
        <section>
          <h4>默认假设</h4>
          ${assumptions}
        </section>
      </div>
      <div class="meta-preflight-actions">
        <button data-action="dismiss">知道了</button>
        <button data-action="edit">补充到输入框</button>
        ${state.canSkip ? '<button data-action="continue">继续默认值</button>' : ''}
      </div>
    `;

    rootEl.querySelectorAll('.meta-preflight-actions button').forEach((btn) => {
      btn.addEventListener('click', () => {
        rootEl.dispatchEvent(new CustomEvent('meta-preflight-action', {
          bubbles: true,
          detail: {
            action: btn.getAttribute('data-action'),
            runId: state.runId,
            interpretedRequest: state.interpretedRequest,
            missingFields: state.missingFields,
          },
        }));
      });
    });

    return rootEl;
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  root.MetaPreflight = {
    createPreflight,
    renderPreflight,
  };
}(typeof window !== 'undefined' ? window : globalThis));
