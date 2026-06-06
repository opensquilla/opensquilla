// MetaSkill run preview card.
// Pure render functions; chat.js owns placement and actions.

(function (root) {
  'use strict';

  function createPreflight(payload) {
    const template = payload.request_template || {};
    const language = detectLanguage(
      payload.language
      || template.language
      || payload.interpreted_request
      || template.outcome
      || '',
    );
    return {
      runId: payload.run_id || '',
      metaSkillName: payload.meta_skill_name || '',
      language,
      interpretedRequest: payload.interpreted_request || '',
      missingFields: payload.missing_fields || [],
      assumptions: payload.assumptions || [],
      fields: Array.isArray(template.fields) ? template.fields : [],
      outcome: template.outcome || template.deliverable || '',
      canSkip: payload.can_skip !== false,
      requiresGate: payload.requires_confirmation === true,
    };
  }

  function renderPreflight(rootEl, state) {
    rootEl.classList.add('meta-preflight');
    rootEl.classList.remove('meta-preflight--collapsed');
    rootEl.setAttribute('data-run-id', state.runId);
    rootEl.setAttribute('data-state', 'ready');
    rootEl.setAttribute('data-language', state.language);
    rootEl.setAttribute('role', 'group');
    const copy = preflightCopy(state.language);
    rootEl.setAttribute(
      'aria-label',
      copy.aria(state.metaSkillName),
    );

    const assumptions = state.assumptions.length > 0
      ? `<ul class="meta-preflight-list">${state.assumptions
        .map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
      : '';
    const displayName = skillDisplayName(state.metaSkillName);
    const headline = state.outcome
      ? copy.headlineWithOutcome(displayName, state.outcome)
      : copy.headline(displayName);

    rootEl.innerHTML = `
      <header class="meta-preflight-head">
        <span class="meta-preflight-title" title="${escapeAttr(headline)}">${escapeHtml(headline)}</span>
        <span class="meta-preflight-badge">${escapeHtml(copy.badge)}</span>
      </header>
      <div class="meta-preflight-body">
        <section class="meta-preflight-understood">
          <h4>${escapeHtml(copy.understood)}</h4>
          <p class="meta-preflight-request">${escapeHtml(state.interpretedRequest)}</p>
          <p class="meta-preflight-muted">${escapeHtml(copy.correctionHint)}</p>
        </section>
        ${assumptions ? `<section>
          <h4>${escapeHtml(copy.assumptions)}</h4>
          ${assumptions}
        </section>` : ''}
        ${state.requiresGate ? renderMissingFields(state) : ''}
        <p class="meta-preflight-error" role="alert" hidden></p>
      </div>
      <div class="meta-preflight-actions">
        ${state.requiresGate && state.canSkip ? `<button class="meta-preflight-link" data-action="defaults">${escapeHtml(copy.useDefaults)}</button>` : ''}
        <button class="meta-preflight-secondary" data-action="dismiss">${escapeHtml(state.requiresGate ? copy.cancel : copy.dismiss)}</button>
        ${state.requiresGate ? `<button class="meta-preflight-primary" data-action="continue">${escapeHtml(copy.start)}</button>` : ''}
      </div>
    `;

    rootEl.querySelectorAll('.meta-preflight-actions button').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.getAttribute('data-action');
        if (action === 'continue' && !validateRequiredFields(rootEl, state)) return;
        rootEl.dispatchEvent(new CustomEvent('meta-preflight-action', {
          bubbles: true,
          detail: {
            action,
            runId: state.runId,
            metaSkillName: state.metaSkillName,
            interpretedRequest: state.interpretedRequest,
            missingFields: state.missingFields,
            confirmedFields: collectFieldValues(rootEl, state, {
              useDefaults: action === 'defaults',
            }),
          },
        }));
      });
    });

    return rootEl;
  }

  function renderMissingFields(state) {
    const fields = missingFieldSpecs(state);
    if (fields.length === 0) return '';
    const copy = preflightCopy(state.language);
    return `
      <section class="meta-preflight-fields">
        <h4>${escapeHtml(copy.missingFields)}</h4>
        <div class="meta-preflight-field-list">
          ${fields.map((field) => renderField(field, state.language)).join('')}
        </div>
      </section>
    `;
  }

  function renderField(field, language) {
    const name = String(field.name || '');
    const label = fieldLabel(field);
    const helper = field.description || field.help || field.hint || '';
    const copy = preflightCopy(language);
    const value = field.default != null ? String(field.default) : '';
    const inputId = `meta-preflight-field-${safeId(name)}`;
    const helperId = `${inputId}-help`;
    const errorId = `${inputId}-error`;
    const required = field.required === true;
    const control = renderFieldControl(field, inputId, value, helperId, errorId, language);
    return `
      <label class="meta-preflight-field" data-field-name="${escapeAttr(name)}">
        <span class="meta-preflight-field-label">
          ${escapeHtml(label)}
          ${required ? `<span class="meta-preflight-required">${escapeHtml(copy.required)}</span>` : ''}
        </span>
        ${helper ? `<span class="meta-preflight-field-help" id="${escapeAttr(helperId)}">${escapeHtml(helper)}</span>` : ''}
        ${control}
        <span class="meta-preflight-field-error" id="${escapeAttr(errorId)}" aria-live="polite"></span>
      </label>
    `;
  }

  function renderFieldControl(field, inputId, value, helperId, errorId, language) {
    const describedBy = `${helperId} ${errorId}`.trim();
    const common = `class="meta-preflight-field-control" data-field-name="${escapeAttr(field.name)}"
      aria-required="${field.required === true ? 'true' : 'false'}"
      aria-describedby="${escapeAttr(describedBy)}"`;
    const type = normalizeFieldType(field);
    if (type === 'textarea') {
      return `<textarea id="${escapeAttr(inputId)}" ${common} rows="3">${escapeHtml(value)}</textarea>`;
    }
    if (type === 'boolean') {
      const checked = value === 'true' || value === '1' ? ' checked' : '';
      return `<input id="${escapeAttr(inputId)}" ${common} type="checkbox"${checked}>`;
    }
    const options = fieldOptions(field);
    if (type === 'select' && options.length > 0) {
      return `<select id="${escapeAttr(inputId)}" ${common}>
        <option value="">${escapeHtml(preflightCopy(language).selectOne)}</option>
        ${options.map((option) => renderOption(option, value)).join('')}
      </select>`;
    }
    const htmlType = type === 'number' ? 'number' : 'text';
    return `<input id="${escapeAttr(inputId)}" ${common} type="${htmlType}" value="${escapeAttr(value)}">`;
  }

  function renderOption(option, value) {
    const raw = typeof option === 'object' && option !== null
      ? option.value ?? option.label
      : option;
    const label = typeof option === 'object' && option !== null
      ? option.label ?? option.value
      : option;
    const selected = String(raw ?? '') === value ? ' selected' : '';
    return `<option value="${escapeAttr(raw)}"${selected}>${escapeHtml(label)}</option>`;
  }

  function collectFieldValues(rootEl, state, options) {
    const out = defaultFieldValues(state.fields);
    if (options && options.useDefaults) return out;
    rootEl.querySelectorAll('.meta-preflight-field-control').forEach((input) => {
      const name = input.getAttribute('data-field-name');
      if (!name) return;
      if (input.type === 'checkbox') {
        out[name] = input.checked;
        return;
      }
      const value = String(input.value || '').trim();
      if (value) out[name] = value;
    });
    return out;
  }

  function validateRequiredFields(rootEl, state) {
    let firstInvalid = null;
    missingFieldSpecs(state).forEach((field) => {
      const name = String(field.name || '');
      const row = rootEl.querySelector(`.meta-preflight-field[data-field-name="${cssEscape(name)}"]`);
      const input = rootEl.querySelector(`.meta-preflight-field-control[data-field-name="${cssEscape(name)}"]`);
      const error = row ? row.querySelector('.meta-preflight-field-error') : null;
      if (!row || !input || !error) return;
      const value = input.type === 'checkbox' ? input.checked : String(input.value || '').trim();
      const invalid = field.required === true && input.type !== 'checkbox' && value === '';
      row.classList.toggle('is-invalid', invalid);
      input.setAttribute('aria-invalid', invalid ? 'true' : 'false');
      error.textContent = invalid ? preflightCopy(state.language).requiredError : '';
      if (invalid && !firstInvalid) firstInvalid = input;
    });
    if (firstInvalid && typeof firstInvalid.focus === 'function') firstInvalid.focus();
    return firstInvalid === null;
  }

  function setSubmitting(rootEl, submitting) {
    rootEl.setAttribute('data-state', submitting ? 'submitting' : 'ready');
    rootEl.setAttribute('aria-busy', submitting ? 'true' : 'false');
    rootEl.querySelectorAll('.meta-preflight-actions button').forEach((btn) => {
      btn.disabled = submitting;
    });
    const primary = rootEl.querySelector('.meta-preflight-primary');
    const language = rootEl.getAttribute('data-language') || detectLanguage(rootEl.textContent || '');
    const copy = preflightCopy(language);
    if (primary) primary.textContent = submitting ? copy.starting : copy.start;
  }

  function setError(rootEl, err) {
    const language = rootEl.getAttribute('data-language') || detectLanguage(rootEl.textContent || '');
    const copy = preflightCopy(language);
    const message = err && err.message ? err.message : copy.error;
    const error = rootEl.querySelector('.meta-preflight-error');
    if (!error) return;
    rootEl.setAttribute('data-state', 'error');
    error.textContent = message;
    error.hidden = false;
  }

  function renderCollapsed(rootEl, detail, status) {
    const name = skillDisplayName((detail && detail.metaSkillName) || '');
    const copy = preflightCopy(detectLanguage((detail && detail.interpretedRequest) || ''));
    const normalizedStatus = status === 'cancelled' || status === 'canceled'
      ? 'cancelled'
      : status;
    const text = normalizedStatus === 'running'
      ? copy.running(name)
      : copy.dismissed;
    rootEl.classList.add('meta-preflight--collapsed');
    rootEl.setAttribute('data-state', normalizedStatus);
    rootEl.innerHTML = `<p class="meta-preflight-collapsed">${escapeHtml(text)}</p>`;
    return rootEl;
  }

  function missingFieldSpecs(state) {
    const byName = {};
    state.fields.forEach((field) => {
      if (field && field.name) byName[field.name] = field;
    });
    return state.missingFields
      .map((name) => byName[name] || { name, required: true })
      .filter((field) => field && field.name);
  }

  function defaultFieldValues(fields) {
    const out = {};
    (Array.isArray(fields) ? fields : []).forEach((field) => {
      if (!field || !field.name) return;
      if (field.default != null) out[field.name] = field.default;
    });
    return out;
  }

  function normalizeFieldType(field) {
    const type = String(field.type || field.kind || '').toLowerCase();
    if (field.multiline === true || ['textarea', 'long_text', 'markdown'].includes(type)) {
      return 'textarea';
    }
    if (['bool', 'boolean', 'toggle'].includes(type)) return 'boolean';
    if (['number', 'integer', 'float'].includes(type)) return 'number';
    if (fieldOptions(field).length > 0) return 'select';
    return 'text';
  }

  function fieldOptions(field) {
    if (Array.isArray(field.options)) return field.options;
    if (Array.isArray(field.choices)) return field.choices;
    return [];
  }

  function fieldLabel(field) {
    return field.label || field.title || humanizeToken(field.name);
  }

  function detectLanguage(text) {
    return /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(String(text || ''))
      ? 'zh'
      : 'en';
  }

  function preflightCopy(language) {
    if (language === 'zh') {
      return {
        aria: (name) => `运行 ${name} 前确认`,
        badge: '检查点',
        headline: (name) => `我准备运行 ${name}`,
        headlineWithOutcome: (name, outcome) => `我准备运行 ${name}，产出 ${outcome}`,
        understood: '我理解的是',
        correctionHint: '不对的话，直接回复补充，我会重新理解。',
        assumptions: '我会先按这些假设处理',
        missingFields: '开始前还需要',
        useDefaults: '使用默认值运行',
        cancel: '取消',
        dismiss: '知道了',
        start: '开始运行',
        starting: '启动中...',
        required: '必填',
        requiredError: '必填。',
        selectOne: '选择一项',
        error: '没能启动，请重试或直接回复修改。',
        running: (name) => `正在运行 ${name}...`,
        dismissed: '已收起这条检查点。',
      };
    }
    return {
      aria: (name) => `Confirm before running ${name}`,
      badge: 'Checkpoint',
      headline: (name) => `Before running ${name}`,
      headlineWithOutcome: (name, outcome) => `Before running ${name}: ${outcome}`,
      understood: 'I understood',
      correctionHint: 'If this is off, reply with the correction and I will update it.',
      assumptions: 'I will use these assumptions',
      missingFields: 'Needed before starting',
      useDefaults: 'Use defaults',
      cancel: 'Cancel',
      dismiss: 'Dismiss',
      start: 'Start',
      starting: 'Starting...',
      required: 'Required',
      requiredError: 'Please fill this in.',
      selectOne: 'Choose one',
      error: 'Could not start. Retry or reply with a correction.',
      running: (name) => `Running ${name}...`,
      dismissed: 'Dismissed this checkpoint.',
    };
  }

  function skillDisplayName(name) {
    return humanizeToken(String(name || '').replace(/^meta[-_]/, ''));
  }

  function humanizeToken(value) {
    return String(value || '')
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b\w/g, (ch) => ch.toUpperCase());
  }

  function safeId(value) {
    return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '-');
  }

  function cssEscape(value) {
    if (typeof root.CSS !== 'undefined' && typeof root.CSS.escape === 'function') {
      return root.CSS.escape(value);
    }
    return String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '\\$&');
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

  root.MetaPreflight = {
    createPreflight,
    renderPreflight,
    renderMissingFields,
    collectFieldValues,
    validateRequiredFields,
    renderCollapsed,
    setSubmitting,
    setError,
    defaultFieldValues,
  };
}(typeof window !== 'undefined' ? window : globalThis));
