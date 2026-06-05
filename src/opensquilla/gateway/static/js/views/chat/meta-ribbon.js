// MetaSkill run progress ribbon — design §8.
// Pure render functions; chat.js wires the event handlers and DOM root.
// Loaded as a classic script before chat.js so window.MetaRibbon is
// available when the chat IIFE initialises.

(function (root) {
  'use strict';

  const STATE_GLYPH = {
    pending: '○',
    running: '⚙',
    succeeded: '✓',
    failed: '✗',
    skipped: '↷',
    substituted: '⇄',
  };
  const RESCUE_ACTION_IDS = new Set([
    'retry-run',
    'retry-step',
    'retry-with-partial-context',
    'switch-meta-skill',
    'install-dependency',
    'continue-text-only',
  ]);

  function humanizeStepId(id) {
    if (!id) return '';
    return id.charAt(0).toUpperCase() + id.slice(1).replace(/[_-]/g, ' ');
  }

  function createRibbon(announce) {
    return {
      runId: announce.run_id,
      metaSkillName: announce.meta_skill_name,
      steps: (announce.steps || []).map((s) => ({
        id: s.id,
        label: s.label || humanizeStepId(s.id),
        kind: s.kind,
        dependsOn: s.depends_on || [],
        state: 'pending',
        statusText: '',
        error: '',
        substituteFor: null,
        rescue: {},
      })),
      total: announce.total || 0,
      collapsed: false,
      runOutcome: null,
      currentIndex: 0,
    };
  }

  function updateStep(state, stepStateEvent) {
    const step = state.steps.find((s) => s.id === stepStateEvent.step_id);
    if (!step) return state;
    step.state = stepStateEvent.state;
    if (stepStateEvent.status_text != null) step.statusText = stepStateEvent.status_text;
    if (stepStateEvent.error) step.error = stepStateEvent.error;
    if (stepStateEvent.substitute_for) step.substituteFor = stepStateEvent.substitute_for;
    if (stepStateEvent.rescue) step.rescue = stepStateEvent.rescue;
    state.currentIndex = Math.max(
      state.currentIndex,
      state.steps.findIndex((s) => s.id === step.id),
    );
    return state;
  }

  function completeRun(state, completedEvent) {
    state.runOutcome = completedEvent.outcome;
    const completed = new Set(completedEvent.completed_steps || []);
    const failed = new Set(completedEvent.failed_steps || []);
    const recovered = new Set(completedEvent.recovered_steps || []);
    const skipped = new Set(completedEvent.skipped_steps || []);
    state.steps.forEach((step) => {
      if (recovered.has(step.id)) {
        step.state = 'substituted';
        step.statusText = step.statusText || '已由替代步骤恢复';
      } else if (failed.has(step.id)) {
        step.state = 'failed';
      } else if (skipped.has(step.id)) {
        step.state = 'skipped';
      } else if (completed.has(step.id)) {
        step.state = 'succeeded';
      }
    });
    return state;
  }

  function renderRibbon(rootEl, state) {
    const completedCount = state.steps.filter(
      (s) => s.state === 'succeeded' || s.state === 'skipped' || s.state === 'substituted',
    ).length;
    const runningIndex = state.steps.findIndex((s) => s.state === 'running');
    const headerIndex = runningIndex >= 0 ? runningIndex + 1 : completedCount;

    rootEl.classList.add('meta-ribbon');
    rootEl.setAttribute('data-run-id', state.runId);
    rootEl.setAttribute('data-collapsed', String(state.collapsed));
    rootEl.setAttribute('role', 'region');
    rootEl.setAttribute(
      'aria-label',
      `MetaSkill ${state.metaSkillName} run progress: ${headerIndex} of ${state.total}`,
    );

    const currentStep = runningIndex >= 0 ? state.steps[runningIndex] : null;
    const statusText = currentStep ? currentStep.statusText || '运行中…' : '';

    rootEl.innerHTML = `
      <header class="meta-ribbon-head">
        <button class="meta-ribbon-toggle" aria-label="折叠/展开 ribbon">${state.collapsed ? '▶' : '▼'}</button>
        <span class="meta-ribbon-title">${escapeHtml(state.metaSkillName)}</span>
        <span class="meta-ribbon-counter">${headerIndex}/${state.total}</span>
      </header>
      <ol class="meta-ribbon-chips" aria-live="polite">
        ${state.steps.map((s, i) => `
          <li class="chip ${s.state}" data-step-id="${escapeAttr(s.id)}"
              tabindex="0"
              aria-label="step ${i + 1} of ${state.total}: ${escapeAttr(s.label)} ${s.state}">
            ${stepGlyph(s)} ${escapeHtml(s.label)}
          </li>
        `).join('')}
      </ol>
      <div class="meta-ribbon-status">${escapeHtml(statusText)}</div>
      <div class="meta-ribbon-actions" ${shouldShowActions(state) ? '' : 'hidden'}>
        ${shouldShowActions(state) ? renderActions(state) : ''}
      </div>
    `;

    wireToggle(rootEl, state);
    wireChipClicks(rootEl);
    wireActionClicks(rootEl, state);

    return rootEl;
  }

  function shouldShowActions(state) {
    return state.runOutcome === 'failed' && state.steps.some((s) => s.state === 'failed');
  }

  function stepGlyph(step) {
    return step.substituteFor ? STATE_GLYPH.substituted : (STATE_GLYPH[step.state] || '○');
  }

  function renderActions(state) {
    const failedStep = state.steps.find((s) => s.state === 'failed');
    const errText = failedStep ? failedStep.error || '步骤失败' : '';
    const rescueActions = failedStep
      && failedStep.rescue
      && Array.isArray(failedStep.rescue.actions)
      ? failedStep.rescue.actions.filter((action) => (
        action && RESCUE_ACTION_IDS.has(action.id)
      ))
      : [];
    const dynamicActions = rescueActions.length > 0
      ? rescueActions.map((action) => `
        <button data-action="${escapeAttr(action.id || '')}" data-step-id="${escapeAttr(failedStep.id)}">
          ${escapeHtml(action.label || humanizeStepId(action.id || 'action'))}
        </button>
      `).join('')
      : `
        <button data-action="retry-run">重试整个 run</button>
        <button data-action="switch-skill">切换 meta-skill…</button>
      `;
    return `
      <span class="meta-ribbon-fail-summary">
        ✗ ${escapeHtml(failedStep.label)} 失败 · ${escapeHtml(truncate(errText, 80))}
      </span>
      ${dynamicActions}
      <button data-action="show-detail" data-step-id="${escapeAttr(failedStep.id)}">查看错误详情</button>
    `;
  }

  function wireToggle(rootEl, state) {
    const btn = rootEl.querySelector('.meta-ribbon-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
      state.collapsed = !state.collapsed;
      renderRibbon(rootEl, state);
    });
  }

  function wireChipClicks(rootEl) {
    rootEl.querySelectorAll('.meta-ribbon-chips .chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const stepId = chip.getAttribute('data-step-id');
        const card = document.querySelector(
          `[data-tool-use-id="meta_step_${cssEscape(stepId)}"]`,
        );
        if (card && typeof card.scrollIntoView === 'function') {
          card.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
      });
    });
  }

  function wireActionClicks(rootEl, state) {
    rootEl.querySelectorAll('.meta-ribbon-actions button').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.getAttribute('data-action');
        const stepId = btn.getAttribute('data-step-id');
        rootEl.dispatchEvent(new CustomEvent('meta-ribbon-action', {
          bubbles: true,
          detail: { action, stepId, runId: state.runId },
        }));
      });
    });
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(s) {
    return escapeHtml(s);
  }

  function truncate(s, n) {
    const str = String(s ?? '');
    return str.length <= n ? str : str.slice(0, n - 1) + '…';
  }

  function cssEscape(s) {
    if (typeof window !== 'undefined' && window.CSS && typeof window.CSS.escape === 'function') {
      return window.CSS.escape(s);
    }
    return String(s ?? '').replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }

  root.MetaRibbon = {
    createRibbon,
    updateStep,
    completeRun,
    renderRibbon,
  };
}(typeof window !== 'undefined' ? window : globalThis));
