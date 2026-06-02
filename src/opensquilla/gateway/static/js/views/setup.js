/** OpenSquilla Web UI - setup flow. */

const SetupView = (() => {
  const STEPS = [
    { id: 'provider', label: 'Provider' },
    { id: 'router', label: 'Router Tiers' },
    { id: 'channels', label: 'Channels' },
    { id: 'extras', label: 'Capabilities' },
    { id: 'finish', label: 'Finish' },
  ];
  const TEXT_TIERS = ['c0', 'c1', 'c2', 'c3'];
  const TIER_LABELS = {
    c0: 'Route c0',
    c1: 'Route c1',
    c2: 'Route c2',
    c3: 'Route c3',
  };
  const READINESS_LABELS = {
    ok: 'Ready',
    optional: 'Optional',
    missing: 'Missing',
    degraded: 'Needs action',
    unknown: 'Check',
  };

  let _el = null;
  let _rpc = null;
  let _catalog = {};
  let _status = {};
  let _config = {};
  let _channelStatus = { channels: [] };
  let _step = 'provider';
  let _channelType = '';
  let _pollTimer = null;
  let _hasAutoSelectedStep = false;
  const _drafts = new Map();
  let _channelDirty = false;

  async function render(el) {
    _el = el;
    _rpc = App.getRpc();
    await _rpc.waitForConnection();
    await _load();
    _selectInitialStep();
    _draw();
    _startChannelPolling();
  }

  async function _load() {
    try {
      const [catalog, status, config, channelStatus] = await Promise.all([
        _rpc.call('onboarding.catalog'),
        _rpc.call('onboarding.status'),
        _rpc.call('config.get'),
        _rpc.call('channels.status').catch(() => ({ channels: [] })),
      ]);
      _catalog = catalog || {};
      _status = status || {};
      _config = config || {};
      _channelStatus = channelStatus || { channels: [] };
    } catch (err) {
      _el.innerHTML = `<div class="setup-error">Failed to load setup catalog: ${_esc(err.message)}</div>`;
    }
  }

  function _draw() {
    if (!_el) return;
    const setupAction = _hasSetupAction();
    _el.innerHTML = `
      <section class="setup">
        <header class="setup__head">
          <div>
            <p class="setup__kicker">OpenSquilla setup</p>
            <h2>${setupAction ? 'Action needed' : 'Ready to run'}</h2>
          </div>
          <div class="setup__head-aside">
            <button type="button" class="setup__exit" data-exit-setup aria-label="Exit setup and return to Overview">
              <span aria-hidden="true">←</span><span>Exit setup</span>
            </button>
            <div class="setup__status ${setupAction ? 'is-warn' : 'is-ok'}">
              ${setupAction ? 'Action needed' : 'Ready'}
            </div>
            ${_renderOnboardingReasons()}
          </div>
        </header>
        <nav class="setup-stepper" aria-label="Setup steps">
          ${STEPS.map(_renderStepButton).join('')}
        </nav>
        <div class="setup__body">${_renderCurrentStep()}</div>
      </section>`;

    _restoreDraft(_step);
    _restoreDynamicDraftFields();
    _el.querySelectorAll('[data-step]').forEach(btn => {
      btn.addEventListener('click', () => _setStep(btn.dataset.step));
    });
    _bindStep();
  }

  function _renderStepButton(s, idx) {
    const status = _stepStatus(s.id);
    return `<button class="setup-stepper__item ${s.id === _step ? 'is-active' : ''}" data-step="${_esc(s.id)}" aria-label="${_esc(`${s.label}: ${status.label}`)}">
      <span class="setup-stepper__num">${idx + 1}</span>
      <span class="setup-stepper__label">${_esc(s.label)}</span>
      <small class="setup-stepper__state ${_esc(status.tone)}">${_esc(status.label)}</small>
    </button>`;
  }

  function _stepStatus(stepId) {
    if (stepId === 'provider') {
      if (_providerEnvMissing()) return { label: 'Needs action', tone: 'is-warn' };
      return _detailStepStatus((_status.sectionDetails || {}).llm || (_status.sectionDetails || {}).provider);
    }
    if (stepId === 'router' && !_effectiveProvider()) {
      return { label: 'Provider first', tone: 'is-muted' };
    }
    if (stepId === 'router') return _detailStepStatus((_status.sectionDetails || {}).router);
    if (stepId === 'channels') return _detailStepStatus((_status.sectionDetails || {}).channels);
    if (stepId === 'extras') {
      return _aggregateStepStatus(['search', 'image_generation', 'audio', 'memory_embedding']);
    }
    if (stepId === 'finish') {
      return _hasSetupAction()
        ? { label: 'Review', tone: 'is-warn' }
        : { label: 'Ready', tone: 'is-ok' };
    }
    return { label: 'Review', tone: 'is-muted' };
  }

  function _aggregateStepStatus(sectionNames) {
    const details = _status.sectionDetails || {};
    const entries = sectionNames.map(name => details[name]).filter(Boolean);
    if (entries.some(detail => _stepDetailNeedsAction(detail))) {
      return { label: 'Needs action', tone: 'is-warn' };
    }
    if (entries.length && entries.every(detail => detail.status === 'ok')) {
      return { label: 'Ready', tone: 'is-ok' };
    }
    return { label: 'Optional', tone: 'is-muted' };
  }

  function _detailStepStatus(detail) {
    if (!detail) return { label: 'Review', tone: 'is-muted' };
    if (_stepDetailNeedsAction(detail)) return { label: 'Needs action', tone: 'is-warn' };
    if (detail.status === 'ok') return { label: 'Ready', tone: 'is-ok' };
    return { label: READINESS_LABELS[detail.status] || 'Optional', tone: 'is-muted' };
  }

  function _stepDetailNeedsAction(detail) {
    return Boolean(
      detail
      && (
        detail.blocking || detail.actionRequired
        || detail.status === 'missing' || detail.status === 'degraded'
      )
    );
  }

  function _renderOnboardingReasons() {
    const reasons = _onboardingReasons();
    if (!reasons.length) return '';
    return `<ul class="setup-reasons" aria-label="Setup actions needed">
      ${reasons.map(reason => `<li>${_esc(reason)}</li>`).join('')}
    </ul>`;
  }

  function _onboardingReasons() {
    if (!_hasSetupAction()) return [];
    const reasons = [];
    const llm = _config.llm || {};
    if (_providerEnvMissing()) {
      reasons.push(`${_providerEnvKey()} is not visible`);
    } else if (!llm.provider || !llm.model) {
      reasons.push('Connect a model provider');
    }
    const details = _status.sectionDetails || {};
    Object.entries(details).forEach(([name, detail]) => {
      if (!detail.blocking && !detail.actionRequired) return;
      if ((name === 'llm' || name === 'provider') && detail.status === 'missing') {
        if (!reasons.includes('Connect a model provider')) reasons.push('Connect a model provider');
        return;
      }
      if ((name === 'llm' || name === 'provider') && reasons.length) return;
      const reason = _setupActionReason(name, detail);
      if (!reasons.includes(reason)) reasons.push(reason);
    });
    return reasons.length ? reasons : ['Review setup sections for pending actions'];
  }

  function _setupActionReason(name, detail) {
    const missingEnvPrefix = 'env key not visible: ';
    const detailText = String(detail.detail || '');
    if (detailText.startsWith(missingEnvPrefix)) {
      const envKey = detailText.slice(missingEnvPrefix.length).trim();
      if (envKey) return `${envKey} is not visible`;
    }
    return `${detail.label || name} setup needed`;
  }

  function _hasSetupAction() {
    if (_status.needsOnboarding) return true;
    const details = _status.sectionDetails || {};
    return Object.values(details).some(detail => (
      detail.blocking
      || detail.actionRequired
      || detail.status === 'missing'
      || detail.status === 'degraded'
    ));
  }

  function _renderCurrentStep() {
    if (_step === 'router') return _renderRouterStep();
    if (_step === 'channels') return _renderChannelsStep();
    if (_step === 'extras') return _renderExtrasStep();
    if (_step === 'finish') return _renderFinishStep();
    return _renderProviderStep();
  }

  function _selectInitialStep() {
    if (_hasAutoSelectedStep) return;
    _step = _initialStepFromStatus();
    _hasAutoSelectedStep = true;
  }

  function _initialStepFromStatus() {
    const details = _status.sectionDetails || {};
    const sectionSteps = [
      ['llm', 'provider'],
      ['router', 'router'],
      ['channels', 'channels'],
      ['search', 'extras'],
      ['image_generation', 'extras'],
      ['audio', 'extras'],
      ['memory_embedding', 'extras'],
    ];
    const entry = sectionSteps.find(([section]) => {
      const detail = details[section] || {};
      return (
        detail.blocking
        || detail.actionRequired
        || detail.status === 'missing'
        || detail.status === 'degraded'
      );
    });
    if (entry) return entry[1];
    if (_status.needsOnboarding === false) return 'finish';
    return 'provider';
  }

  function _renderNeedList(items, label, dataAttr = '') {
    const needs = (items || []).filter(Boolean);
    const attr = dataAttr ? ` ${dataAttr}` : '';
    if (!needs.length) return `<div class="setup-need-list is-empty"${attr} hidden></div>`;
    return `<div class="setup-need-list"${attr} aria-label="${_esc(label)}">
      <span>${_esc(label)}</span>
      <ul>${needs.map(item => `<li>${_esc(item)}</li>`).join('')}</ul>
    </div>`;
  }

  function _credentialNeedList(items, envKey) {
    const key = String(envKey || '').trim();
    if (!key) return items || [];
    return (items || []).map(item => {
      if (/API key via [A-Z0-9_]+ or a one-time paste\./.test(item)) {
        return `API key via ${key} or a one-time paste.`;
      }
      if (/Remote embedding API key or [A-Z0-9_]+ reference\./.test(item)) {
        return `Remote embedding API key or ${key} reference.`;
      }
      return item;
    });
  }

  function _memoryNeedList(spec, providerId, envKey) {
    const items = (spec?.whatYouNeed || []).filter(Boolean);
    if (providerId === 'auto' && !String(envKey || '').trim()) {
      return items.filter(item => !/remote fallback credentials/i.test(item));
    }
    return spec?.requiresApiKey ? _credentialNeedList(items, envKey || spec.envKey) : items;
  }

  function _replaceNeedList(selector, items, label, dataAttr) {
    const box = _el?.querySelector(selector);
    if (box) box.outerHTML = _renderNeedList(items, label, dataAttr);
  }

  function _renderProviderStep() {
    const providers = (_catalog.providers || []).filter(p => p.runtimeSupported);
    const selected = _effectiveProvider();
    const spec = selected ? providers.find(p => p.providerId === selected) || {} : {};
    const providerSummary = selected
      ? (spec.label || selected)
      : `Choose from ${providers.length} supported providers`;
    const values = selected ? _providerConfigFor(selected) : {};
    const providerFields = spec.fields || [];
    const providerCoreFields = providerFields.filter(field => !_isProviderAdvancedField(field, spec));
    const providerAdvancedFields = providerFields.filter(field => _isProviderAdvancedField(field, spec));
    const providerAdvancedOpen = _providerAdvancedOpen(providerAdvancedFields, values) ? ' open' : '';
    const routerSupportTone = _providerRouterSupportTone(selected ? spec : null);
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Provider</h3>
          <p data-provider-summary>${_esc(providerSummary)}</p>
        </header>
        <div class="setup-form">
          <label><span>Provider</span>
            <select data-provider-select name="setup_provider">
              <option value="" disabled${selected ? '' : ' selected'}>Choose a provider</option>
              ${providers.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === selected ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
            </select>
          </label>
          <div class="setup-provider-meta" data-provider-router-support>
            <span>SquillaRouter tiers</span>
            <strong class="setup-provider-meta__badge ${_esc(routerSupportTone)}" data-provider-router-support-label>${_esc(_providerRouterSupportText(selected ? spec : null))}</strong>
          </div>
          ${_renderNeedList(selected ? spec.whatYouNeed : ['Choose a provider to see required fields.'], 'Provider needs', 'data-provider-needs')}
          <div class="setup-provider-fields">
            ${_renderProviderFields(providerCoreFields, values)}
          </div>
          <div data-provider-advanced-wrap>
            ${_renderProviderAdvancedFields(providerAdvancedFields, values, providerAdvancedOpen)}
          </div>
          ${_providerEnvWarning()}
          <div class="setup-actions">
            <button class="setup-btn setup-btn--primary" data-save-provider${selected ? '' : ' disabled'}>Save Provider</button>
            <button class="setup-btn" data-next="router"${selected ? '' : ' disabled'}>Next</button>
          </div>
        </div>
      </section>`;
  }

  function _providerRouterSupportText(spec) {
    if (!spec || !spec.providerId) return 'choose provider';
    return spec.routerSupported === true ? 'SquillaRouter ready' : 'Direct only';
  }

  function _providerRouterSupportTone(spec) {
    if (!spec || !spec.providerId) return 'is-neutral';
    return spec.routerSupported === true ? 'is-ready' : 'is-direct';
  }

  function _providerConfigFor(providerId) {
    const current = _config.llm || {};
    return current.provider === providerId ? current : {};
  }

  function _configuredProvider() {
    const provider = String((_config.llm || {}).provider || '').trim();
    if (!provider) return '';
    if (_status.hasConfig !== false) return provider;
    if (_status.llmConfigured === true) return provider;
    if (['explicit', 'env', 'not_required'].includes(_status.llmSource)) return provider;
    return '';
  }

  function _draftProvider() {
    const live = _el?.querySelector('[data-provider-select]')?.value || '';
    if (live) return live;
    const providerDraft = _drafts.get('provider') || {};
    return providerDraft['provider:selected'] || '';
  }

  function _effectiveProvider({ includeDraft = true } = {}) {
    return (includeDraft ? _draftProvider() : '') || _configuredProvider();
  }

  function _isProviderAdvancedField(field, spec) {
    if (['base_url', 'proxy'].includes(field.name)) return true;
    if (field.name === 'model') {
      return spec.routerSupported === true && field.required !== true;
    }
    return false;
  }

  function _providerFieldValue(field, current) {
    const name = field.name;
    if (name === 'model') return current.model || field.default || '';
    if (name === 'base_url') return current.base_url || field.default || '';
    if (name === 'proxy') return current.proxy || '';
    if (name === 'api_key_env') return current.api_key_env || (current.api_key ? '' : field.default || '');
    return '';
  }

  function _providerAdvancedOpen(fields, current) {
    return fields.some(field => {
      if (field.required) return true;
      const value = String(_providerFieldValue(field, current) || '').trim();
      const defaultValue = String(field.default || '').trim();
      if (defaultValue) return value !== defaultValue;
      return value.length > 0;
    });
  }

  function _renderProviderFields(fields, current) {
    return (fields || []).map(field => {
      const value = _providerFieldValue(field, current);
      return _fieldHtml(field, value, 'provider');
    }).join('');
  }

  function _renderProviderAdvancedFields(fields, current, openAttr = '') {
    if (!fields.length) return '';
    return `<details class="setup-mini__advanced" data-provider-advanced${openAttr}>
      <summary>Advanced provider connection</summary>
      <div class="setup-mini__advanced-body" aria-label="Provider connection">
        ${_renderProviderFields(fields, current)}
      </div>
    </details>`;
  }

  function _providerEnvMissing() {
    return _status.llmSource === 'missing_env';
  }

  function _providerEnvKey() {
    return ((_config.llm || {}).api_key_env || 'the selected API key environment variable');
  }

  function _providerEnvRecoveryCommand() {
    return _envRecoveryCommand('llm');
  }

  function _capabilityEnvRecoveryCommand(section) {
    return _envRecoveryCommand(section);
  }

  function _envRecoveryCommand(section) {
    const commands = Array.isArray(_status.envRecoveryCommands)
      ? _status.envRecoveryCommands
      : [];
    const entry = commands.find(entry => entry && entry.section === section && entry.command);
    return entry ? entry.command : '';
  }

  function _providerEnvWarning() {
    if (!_providerEnvMissing()) return '';
    const envKey = _providerEnvKey();
    const command = _providerEnvRecoveryCommand();
    const commandRow = command ? _renderProviderEnvCommand(command) : '';
    return `<div class="setup-warning">
      <div>${_esc(envKey)} is not visible to this gateway process. Set it before starting or restarting the gateway, or paste an API key instead.</div>
      ${commandRow}
    </div>`;
  }

  function _renderProviderEnvCommand(command) {
    return _renderEnvRecoveryCommand(command, 'Copy set provider key command');
  }

  function _renderCapabilityEnvRecoveryCommand(section) {
    const command = _capabilityEnvRecoveryCommand(section);
    if (!command) return '';
    const labels = {
      search: 'Copy set search key command',
      image_generation: 'Copy set image key command',
      audio: 'Copy set audio key command',
      memory_embedding: 'Copy set memory key command',
    };
    return _renderEnvRecoveryCommand(
      command,
      labels[section] || 'Copy set environment key command',
      'setup-warning__command setup-mini__env-command',
    );
  }

  function _renderEnvRecoveryCommand(command, copyLabel, className = 'setup-warning__command') {
    const safeCommand = _esc(command);
    return `<div class="${_esc(className)}">
      <code>${safeCommand}</code>
      <button class="setup-cli__copy" type="button" data-setup-copy-command="${safeCommand}" title="${_esc(copyLabel)}" aria-label="${_esc(copyLabel)}">
        ${icons.copy()}
      </button>
    </div>`;
  }

  function _renderRouterStep() {
    const router = (_config.squilla_router || {});
    const provider = _effectiveProvider();
    const canSaveRouter = provider && provider === _configuredProvider();
    const catalog = _catalog.routerProfiles || {};
    const profiles = catalog.profiles || [];
    const profile = provider ? profiles.find(p => p.providerId === provider) || {} : {};
    const tiers = provider ? Object.assign({}, profile.tiers || {}, router.tiers || {}) : {};
    const defaultTier = router.default_tier || catalog.defaultTier || 'c1';
    const mode = router.enabled === false ? 'disabled' : 'recommended';
    const routerSummary = provider
      ? `${provider} / ${_tierLabel(defaultTier)}`
      : 'Choose a provider first';
    const routerDisabled = provider ? '' : ' disabled';
    const saveDisabled = canSaveRouter ? '' : ' disabled';
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Router Tiers</h3>
          <p>${_esc(routerSummary)}</p>
        </header>
        <div class="setup-router-toolbar">
          <label><span>Mode</span>
            <select id="setup-router-mode" name="setup_router_mode" data-router-mode${routerDisabled}>
              <option value="recommended"${mode === 'recommended' ? ' selected' : ''}>SquillaRouter</option>
              <option value="disabled"${mode === 'disabled' ? ' selected' : ''}>Disabled</option>
            </select>
          </label>
          <label><span>Default text model</span>
            <select id="setup-router-default-tier" name="setup_router_default_tier" data-default-tier${routerDisabled}>
              ${TEXT_TIERS.map(t => `<option value="${t}"${t === defaultTier ? ' selected' : ''}>${_esc(_tierLabel(t))}</option>`).join('')}
            </select>
          </label>
        </div>
        ${provider ? `<div class="setup-tier-table" role="table">
          <div class="setup-tier-table__row is-head" role="row">
            <span>Tier</span><span>Provider</span><span>Model</span><span>Thinking</span><span>Image</span>
          </div>
          ${Object.entries(tiers).filter(([name]) => TEXT_TIERS.includes(name) || name === 'image_model').map(([name, tier]) => _tierRow(name, tier)).join('')}
        </div>` : `<div class="setup-warning" data-router-provider-needed>Choose a provider first to preview and save SquillaRouter tiers.</div>`}
        ${provider && !canSaveRouter ? `<div class="setup-warning" data-router-provider-unsaved>Save the provider before saving router tiers.</div>` : ''}
        <div class="setup-actions">
          <button class="setup-btn" data-prev="provider">Back</button>
          <button class="setup-btn setup-btn--primary" data-save-router${saveDisabled}>Save Router</button>
          <button class="setup-btn" data-next="channels">Next</button>
        </div>
      </section>`;
  }

  function _tierRow(name, tier) {
    const isImageModel = name === 'image_model';
    const imageCheckedAttr = isImageModel ? ' checked disabled' :
      (tier.supportsImage || tier.supports_image ? ' checked' : '');
    return `<div class="setup-tier-table__row" role="row" data-tier="${_esc(name)}">
      <span><code>${_esc(name)}</code></span>
      <input ${_tierControlAttrs(name, 'provider', 'provider')} data-tier-field="provider" value="${_esc(tier.provider || '')}">
      <input ${_tierControlAttrs(name, 'model', 'model')} data-tier-field="model" value="${_esc(tier.model || '')}">
      <select ${_tierControlAttrs(name, 'thinkingLevel', 'thinking level')} data-tier-field="thinkingLevel">
        ${['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh'].map(v => `<option value="${v}"${v === (tier.thinkingLevel || tier.thinking_level || '') ? ' selected' : ''}>${v || '-'}</option>`).join('')}
      </select>
      <input ${_tierControlAttrs(name, 'supportsImage', 'supports image')} type="checkbox" data-tier-field="supportsImage"${imageCheckedAttr}>
    </div>`;
  }

  function _tierControlAttrs(name, field, label) {
    const safeTier = String(name || 'tier').replace(/[^a-zA-Z0-9_-]+/g, '-');
    const tierFieldName = `setup_router_${name}_${field}`;
    const tierFieldId = `setup-router-${safeTier}-${field}`;
    const tierLabel = `${name} ${label}`;
    return `id="${_esc(tierFieldId)}" name="${_esc(tierFieldName)}" aria-label="${_esc(tierLabel)}"`;
  }

  function _tierLabel(tier) {
    return TIER_LABELS[tier] || tier || 'Route c1';
  }

  function _renderChannelsStep() {
    const channels = (_catalog.channels || []);
    const selected = channels.some(c => c.type === _channelType) ? _channelType : (channels[0]?.type || 'telegram');
    _channelType = selected;
    const channelSpec = channels.find(c => c.type === selected);
    const runtimeRows = (_channelStatus.channels || []).filter(row => row.configured !== false);
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Channels</h3>
          <p>${runtimeRows.length} configured</p>
        </header>
        <div class="setup-channel-grid">
          <div class="setup-form" data-channel-dirty-root>
            <label><span>Channel type</span>
              <select id="setup-channel-type" name="setup_channel_type" data-channel-type>
                ${channels.map(c => `<option value="${_esc(c.type)}"${c.type === selected ? ' selected' : ''}>${_esc(c.label)}</option>`).join('')}
              </select>
            </label>
            ${_renderNeedList(channelSpec ? channelSpec.whatYouNeed : [], 'Channel needs', 'data-channel-needs')}
            <div class="setup-channel-fields">${_renderChannelFields(channelSpec)}</div>
            <div class="setup-actions">
              <button class="setup-btn setup-btn--primary" data-save-channel>Save Channel</button>
            </div>
          </div>
          <div class="setup-runtime">
            <h4>Runtime status</h4>
            ${runtimeRows.length ? runtimeRows.map(_channelStatusRow).join('') : '<p class="setup-muted">No channels configured.</p>'}
          </div>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" data-prev="router">Back</button>
          <button class="setup-btn" data-next="extras">Next</button>
        </div>
      </section>`;
  }

  function _renderChannelFields(spec) {
    if (!spec) return '';
    return (spec.fields || []).map(field => _fieldHtml(field, field.default ?? '', 'channel')).join('');
  }

  function _channelStatusRow(row) {
    const connected = row.connected === true;
    const state = connected ? 'Connected' : (row.status === 'stopped' ? 'Action needed' : row.status || 'connecting');
    return `<div class="setup-runtime__row ${connected ? 'is-ok' : 'is-warn'}">
      <span>${_esc(row.name)}</span>
      <span>${_esc(row.type || '')}</span>
      <strong>${_esc(state)}</strong>
    </div>`;
  }

  function _renderExtrasStep() {
    const searchProviders = (_catalog.searchProviders || []).filter(p => p.runtimeSupported);
    const searchSelected = _config.search_provider || searchProviders.find(p => p.providerId === 'duckduckgo')?.providerId || searchProviders[0]?.providerId || 'duckduckgo';
    const searchSpec = searchProviders.find(p => p.providerId === searchSelected) || searchProviders[0] || {};
    const searchEnv = _config.search_api_key_env || (searchSpec.requiresApiKey ? searchSpec.envKey : '') || '';
    const searchRequiresKey = searchSpec.requiresApiKey === true;
    const searchKeyDisabled = searchRequiresKey ? '' : ' disabled';
    const searchKeyClass = searchRequiresKey ? '' : ' is-disabled';
    const searchKeyHidden = searchRequiresKey ? '' : ' hidden';
    const searchKeyPlaceholder = searchRequiresKey ? 'leave blank to keep current' : 'not required for this provider';
    const searchEnvPlaceholder = searchRequiresKey ? (searchSpec.envKey || 'SEARCH_API_KEY') : 'not required for this provider';
    const searchProxy = _config.search_proxy || '';
    const searchUseEnvProxy = _config.search_use_env_proxy === true;
    const searchFallbackPolicy = _config.search_fallback_policy || 'off';
    const searchDiagnostics = _config.search_diagnostics === true;
    const searchAdvancedOpen = searchProxy || searchUseEnvProxy || searchFallbackPolicy !== 'off' || searchDiagnostics ? ' open' : '';
    const imageProviders = (_catalog.imageGenerationProviders || []).filter(p => p.runtimeSupported);
    const memoryProviders = _catalog.memoryEmbeddingProviders || [];
    const current = ((_config || {}).memory || {}).embedding || {};
    const effectiveProvider = current.provider || current.mode || 'auto';
    const currentMode = current.mode; // current.mode is kept explicit for static coverage.
    const memorySpec = memoryProviders.find(p => p.providerId === effectiveProvider) || memoryProviders[0] || {};
    const memoryRemote = current.remote || {};
    const memoryLocal = current.local || {};
    const memoryOllama = current.ollama || {};
    const memoryRemoteControlEnabled = ['auto', 'openai', 'openai-compatible', 'ollama'].includes(effectiveProvider);
    const memoryApiKeyEnabled = effectiveProvider === 'auto' || memorySpec.requiresApiKey === true;
    const memoryLocalControlEnabled = effectiveProvider === 'local';
    const memoryRemoteDisabled = memoryRemoteControlEnabled ? '' : ' disabled';
    const memoryApiKeyDisabled = memoryApiKeyEnabled ? '' : ' disabled';
    const memoryLocalDisabled = memoryLocalControlEnabled ? '' : ' disabled';
    const memoryRemoteClass = memoryRemoteControlEnabled ? '' : ' is-disabled';
    const memoryApiKeyClass = memoryApiKeyEnabled ? '' : ' is-disabled';
    const memoryLocalClass = memoryLocalControlEnabled ? '' : ' is-disabled';
    const memoryApiKeyLabel = effectiveProvider === 'auto' ? 'Fallback API key' : 'API key';
    const memoryApiKeyPlaceholder = memoryApiKeyEnabled ? 'leave blank to keep current' : 'not required for this provider';
    const memoryEnv = memoryRemote.api_key_env || (memoryApiKeyEnabled ? memorySpec.envKey || '' : '') || '';
    const memoryEnvPlaceholder = memorySpec.envKey || 'OPENAI_API_KEY';
    const memoryModelPlaceholder = effectiveProvider === 'ollama' ? 'nomic-embed-text' : (memoryRemoteControlEnabled ? 'text-embedding-3-small' : 'not used by this provider');
    const memoryBasePlaceholder = effectiveProvider === 'ollama' ? 'http://localhost:11434' : (memoryRemoteControlEnabled ? 'https://api.openai.com/v1' : 'not used by this provider');
    const memoryOnnxPlaceholder = memoryLocalControlEnabled ? 'models/bge-onnx' : 'only for bundled local provider';
    const memoryRemoteOptionsHasSaved = Boolean(String(
      memoryRemote.model || memoryRemote.api_key || memoryRemote.api_key_env || memoryRemote.base_url
      || memoryOllama.model || memoryOllama.base_url || '',
    ).trim());
    const memoryRemoteOptionsOpen = effectiveProvider !== 'auto' || memoryRemoteOptionsHasSaved ? ' open' : '';
    const memoryRemoteOptionsHidden = memoryRemoteControlEnabled || memoryApiKeyEnabled ? '' : ' hidden';
    const memoryRemoteOptionsSummary = effectiveProvider === 'auto' ? 'Remote fallback options' : 'Connection options';
    const memoryLocalHidden = memoryLocalControlEnabled ? '' : ' hidden';
    const memoryStatusText = _memoryEmbeddingStatusText(effectiveProvider);
    const memoryNeeds = _memoryNeedList(memorySpec, effectiveProvider, memoryEnv);
    const imageProviderSelected = _status.imageGenerationProvider || (_status.imageGenerationPrimary || '').split('/')[0] || imageProviders[0]?.providerId || 'openrouter';
    const imageSpec = imageProviders.find(p => p.providerId === imageProviderSelected) || imageProviders[0] || {};
    const imageConfig = ((_config || {}).image_generation || {});
    const imageProviderConfig = ((imageConfig.providers || {})[imageProviderSelected] || {});
    const imageEnv = imageProviderConfig.api_key_env || (imageSpec.requiresApiKey ? imageSpec.envKey : '') || '';
    const imageBaseUrl = imageProviderConfig.base_url || imageSpec.defaultBaseUrl || '';
    const imagePrimary = _status.imageGenerationPrimary || imageSpec.defaultModel || '';
    const field = (imageSpec.fields || []).find(candidate => candidate.name === 'enabled') || { default: true };
    const imageEnabledDefault = _status.imageGenerationEnabled === false ? false : field.default !== false;
    const imageConfigHidden = imageEnabledDefault ? '' : ' hidden';
    const imageNeeds = imageEnabledDefault
      ? _credentialNeedList(imageSpec.whatYouNeed, imageEnv || imageSpec.envKey)
      : ['No key required while image generation is disabled.'];
    const imageStatusText = _imageGenerationStatusText();
    const audioProviders = (_catalog.audioProviders || []).filter(p => p.runtimeSupported);
    const audioProviderSelected = _status.audioProvider || audioProviders[0]?.providerId || 'elevenlabs';
    const audioSpec = audioProviders.find(p => p.providerId === audioProviderSelected) || audioProviders[0] || {};
    const audioConfig = ((_config || {}).audio || {});
    const audioProviderConfig = ((audioConfig.providers || {})[audioProviderSelected] || {});
    const audioTtsConfig = audioConfig.tts || {};
    const audioEnv = audioProviderConfig.api_key_env || (audioSpec.requiresApiKey ? audioSpec.envKey : '') || '';
    const audioBaseUrl = audioProviderConfig.base_url || audioSpec.defaultBaseUrl || '';
    const audioTtsVoice = audioTtsConfig.voice || audioSpec.defaultTtsVoice || '';
    const audioTtsModel = audioTtsConfig.model || audioSpec.defaultTtsModel || '';
    const audioLanguageCode = audioTtsConfig.language_code || audioSpec.defaultLanguageCode || '';
    const audioEnabledDefault = _status.audioEnabled === true || audioConfig.enabled === true;
    const audioConfigHidden = audioEnabledDefault ? '' : ' hidden';
    const audioNeeds = audioEnabledDefault
      ? _credentialNeedList(audioSpec.whatYouNeed, audioEnv || audioSpec.envKey)
      : ['No key required while voice audio is disabled.'];
    const audioStatusText = _audioStatusText();
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Capability Center</h3>
          <p>Web search · Memory recall · Image generation · Voice audio</p>
        </header>
        <div class="setup-extras">
          <div class="setup-mini">
            <div class="setup-mini__head">
              <h4>Web search</h4>
              ${_renderCapabilityBadge('search')}
            </div>
            <p class="setup-muted">${_esc(_searchStatusText())}</p>
            ${_renderCapabilityEnvRecoveryCommand('search')}
            ${_renderNeedList(_credentialNeedList(searchSpec.whatYouNeed, searchEnv || searchSpec.envKey), 'Search needs', 'data-search-needs')}
            <label><span>Provider</span>
              <select id="setup-search-provider" name="setup_search_provider" data-search-provider>
                ${searchProviders.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === searchSelected ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
              </select>
            </label>
            <label><span>Max results</span><input id="setup-search-max-results" name="setup_search_max_results" type="number" min="1" step="1" inputmode="numeric" data-search-field="max_results" value="${_esc(String(_config.search_max_results || 5))}"></label>
            <div class="setup-mini__advanced-body" data-search-key-fields${searchKeyHidden}>
              <label class="${searchKeyClass}"><span>API key</span><input id="setup-search-api-key" name="setup_search_api_key" type="password" data-search-field="api_key" data-secret="true" placeholder="${_esc(searchKeyPlaceholder)}"${searchKeyDisabled}></label>
              <label class="${searchKeyClass}"><span>API key env</span><input id="setup-search-api-key-env" name="setup_search_api_key_env" data-search-field="api_key_env" value="${_esc(searchEnv)}" placeholder="${_esc(searchEnvPlaceholder)}"${searchKeyDisabled}></label>
            </div>
            <details class="setup-mini__advanced" data-search-advanced${searchAdvancedOpen}>
              <summary>Advanced search options</summary>
              <div class="setup-mini__advanced-body" aria-label="Search behavior">
                <label><span>HTTP proxy</span><input id="setup-search-proxy" name="setup_search_proxy" data-search-field="proxy" value="${_esc(searchProxy)}" placeholder="http://127.0.0.1:7890"></label>
                <label class="setup-check"><input id="setup-search-use-env-proxy" name="setup_search_use_env_proxy" type="checkbox" data-search-field="use_env_proxy"${searchUseEnvProxy ? ' checked' : ''}><span>Use environment proxy</span></label>
                <label><span>Fallback policy</span>
                  <select id="setup-search-fallback-policy" name="setup_search_fallback_policy" data-search-field="fallback_policy">
                    <option value="off"${searchFallbackPolicy === 'off' ? ' selected' : ''}>Off</option>
                    <option value="network"${searchFallbackPolicy === 'network' ? ' selected' : ''}>Network retry</option>
                  </select>
                </label>
                <label class="setup-check"><input id="setup-search-diagnostics" name="setup_search_diagnostics" type="checkbox" data-search-field="diagnostics"${searchDiagnostics ? ' checked' : ''}><span>Diagnostics</span></label>
              </div>
            </details>
            <button class="${_capabilitySaveButtonClass('search')}" data-save-search>Save web search</button>
          </div>
          <div class="setup-mini">
            <div class="setup-mini__head">
              <h4>Memory embedding</h4>
              ${_renderCapabilityBadge('memory_embedding')}
            </div>
            <p class="setup-muted" data-memory-status-text>${_esc(memoryStatusText)}</p>
            ${_renderCapabilityEnvRecoveryCommand('memory_embedding')}
            ${_renderNeedList(memoryNeeds, 'Memory needs', 'data-memory-needs')}
            <label><span>Provider</span>
              <select id="setup-memory-provider" name="setup_memory_provider" data-memory-provider>
                ${memoryProviders.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === effectiveProvider ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
              </select>
            </label>
            <label class="${memoryLocalClass}" data-memory-local-field${memoryLocalHidden}><span>ONNX directory</span><input id="setup-memory-onnx-dir" name="setup_memory_onnx_dir" data-memory-field="onnx_dir" value="${_esc(memoryLocal.onnx_dir || '')}" placeholder="${_esc(memoryOnnxPlaceholder)}"${memoryLocalDisabled}></label>
            <details class="setup-mini__advanced" data-memory-remote-options${memoryRemoteOptionsOpen}${memoryRemoteOptionsHidden}>
              <summary>${_esc(memoryRemoteOptionsSummary)}</summary>
              <div class="setup-mini__advanced-body" aria-label="Memory embedding connection">
                <label class="${memoryRemoteClass}"><span>Model</span><input id="setup-memory-model" name="setup_memory_model" data-memory-field="model" value="${_esc(memoryRemote.model || memoryOllama.model || '')}" placeholder="${_esc(memoryModelPlaceholder)}"${memoryRemoteDisabled}></label>
                <label class="${memoryApiKeyClass}"><span data-memory-api-key-label>${_esc(memoryApiKeyLabel)}</span><input id="setup-memory-api-key" name="setup_memory_api_key" type="password" data-memory-field="api_key" data-secret="true" placeholder="${_esc(memoryApiKeyPlaceholder)}"${memoryApiKeyDisabled}></label>
                <label class="${memoryApiKeyClass}"><span>API key env</span><input id="setup-memory-api-key-env" name="setup_memory_api_key_env" data-memory-field="api_key_env" value="${_esc(memoryEnv)}" placeholder="${_esc(memoryEnvPlaceholder)}"${memoryApiKeyDisabled}></label>
                <label class="${memoryRemoteClass}"><span>Base URL</span><input id="setup-memory-base-url" name="setup_memory_base_url" data-memory-field="base_url" value="${_esc(memoryRemote.base_url || memoryOllama.base_url || '')}" placeholder="${_esc(memoryBasePlaceholder)}"${memoryRemoteDisabled}></label>
              </div>
            </details>
            <button class="${_capabilitySaveButtonClass('memory_embedding')}" data-save-memory>Save memory embedding</button>
          </div>
          <div class="setup-mini">
            <div class="setup-mini__head">
              <h4>Image generation</h4>
              ${_renderCapabilityBadge('image_generation')}
            </div>
            <p class="setup-muted">${_esc(imageStatusText)}</p>
            ${_renderCapabilityEnvRecoveryCommand('image_generation')}
            ${_renderNeedList(imageNeeds, 'Image needs', 'data-image-needs')}
            <div class="setup-mini__advanced-body" data-image-config-fields${imageConfigHidden}>
              <label><span>Provider</span>
                <select id="setup-image-provider" name="setup_image_provider" data-image-provider>
                  ${imageProviders.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === imageProviderSelected ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
                </select>
              </label>
              <label><span>Primary model</span><input id="setup-image-primary" name="setup_image_primary" data-image-field="primary" value="${_esc(imagePrimary)}"></label>
              <label><span>API key</span><input id="setup-image-api-key" name="setup_image_api_key" type="password" data-image-field="api_key" data-secret="true" placeholder="leave blank to keep current"></label>
              <label><span>API key env</span><input id="setup-image-api-key-env" name="setup_image_api_key_env" data-image-field="api_key_env" value="${_esc(imageEnv)}" placeholder="${_esc(imageSpec.envKey || 'OPENROUTER_API_KEY')}"></label>
              <label><span>Base URL</span><input id="setup-image-base-url" name="setup_image_base_url" data-image-field="base_url" value="${_esc(imageBaseUrl)}" placeholder="${_esc(imageSpec.defaultBaseUrl || 'https://api.openai.com/v1')}"></label>
            </div>
            <label class="setup-check"><input id="setup-image-enabled" name="setup_image_enabled" type="checkbox" data-image-enabled${imageEnabledDefault ? ' checked' : ''}><span>Enabled</span></label>
            <button class="${_capabilitySaveButtonClass('image_generation')}" data-save-image>Save image generation</button>
          </div>
          <div class="setup-mini">
            <div class="setup-mini__head">
              <h4>Voice audio</h4>
              ${_renderCapabilityBadge('audio')}
            </div>
            <p class="setup-muted">${_esc(audioStatusText)}</p>
            ${_renderCapabilityEnvRecoveryCommand('audio')}
            ${_renderNeedList(audioNeeds, 'Audio needs', 'data-audio-needs')}
            <div class="setup-mini__advanced-body" data-audio-config-fields${audioConfigHidden}>
              <label><span>Provider</span>
                <select id="setup-audio-provider" name="setup_audio_provider" data-audio-provider>
                  ${audioProviders.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === audioProviderSelected ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
                </select>
              </label>
              <label><span>API key</span><input id="setup-audio-api-key" name="setup_audio_api_key" type="password" data-audio-field="api_key" data-secret="true" placeholder="leave blank to keep current"></label>
              <label><span>API key env</span><input id="setup-audio-api-key-env" name="setup_audio_api_key_env" data-audio-field="api_key_env" value="${_esc(audioEnv)}" placeholder="${_esc(audioSpec.envKey || 'ELEVENLABS_API_KEY')}"></label>
              <label><span>Base URL</span><input id="setup-audio-base-url" name="setup_audio_base_url" data-audio-field="base_url" value="${_esc(audioBaseUrl)}" placeholder="${_esc(audioSpec.defaultBaseUrl || 'https://api.elevenlabs.io')}"></label>
              <label><span>TTS voice</span><input id="setup-audio-tts-voice" name="setup_audio_tts_voice" data-audio-field="tts_voice" value="${_esc(audioTtsVoice)}" placeholder="${_esc(audioSpec.defaultTtsVoice || 'voice id')}"></label>
              <label><span>TTS model</span><input id="setup-audio-tts-model" name="setup_audio_tts_model" data-audio-field="tts_model" value="${_esc(audioTtsModel)}" placeholder="${_esc(audioSpec.defaultTtsModel || 'eleven_multilingual_v2')}"></label>
              <label><span>Language code</span><input id="setup-audio-language-code" name="setup_audio_language_code" data-audio-field="language_code" value="${_esc(audioLanguageCode)}" placeholder="zh-CN, en-US, en-GB"></label>
            </div>
            <label class="setup-check"><input id="setup-audio-enabled" name="setup_audio_enabled" type="checkbox" data-audio-enabled${audioEnabledDefault ? ' checked' : ''}><span>Enabled</span></label>
            <button class="${_capabilitySaveButtonClass('audio')}" data-save-audio>Save voice audio</button>
          </div>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" data-prev="channels">Back</button>
          <button class="setup-btn" data-next="finish">Next</button>
        </div>
      </section>`;
  }

  function _capabilitySaveButtonClass(name) {
    const detail = (_status.sectionDetails || {})[name] || {};
    return detail.blocking || detail.actionRequired
      ? 'setup-btn setup-btn--primary'
      : 'setup-btn';
  }

  function _renderCapabilityBadge(name) {
    const detail = (_status.sectionDetails || {})[name] || {};
    return `<span class="setup-badge ${_readinessTone(detail)}">${_esc(_readinessStatusLabel(detail))}</span>`;
  }

  function _missingEnvStatusText(capability, envKey, fallback) {
    const key = String(envKey || '').trim();
    if (!key) return fallback;
    return `${capability} is selected, but $${key} is not visible to the gateway.`;
  }

  function _searchStatusText() {
    if (!_config.search_provider) {
      return 'Web search is off until a provider is selected.';
    }
    if (_status.searchConfigured === true) {
      return 'Web search is ready for new turns.';
    }
    if (_status.searchSource === 'missing_env') {
      return _missingEnvStatusText(
        'Web search',
        _status.searchEnvKey,
        'Web search is selected but still needs a visible provider key.',
      );
    }
    return 'Web search is selected but still needs a visible provider key.';
  }

  function _imageGenerationStatusText() {
    if (_status.imageGenerationEnabled === false) {
      return 'Image generation is hidden from agents until this capability is enabled.';
    }
    if (_status.imageGenerationConfigured === true) {
      if (_status.imageGenerationSource === 'llm_fallback') {
        return 'Image generation will be available in new turns using the same provider key.';
      }
      return 'Image generation will be available in new turns once the gateway has the visible key.';
    }
    if (_status.imageGenerationSource === 'missing_env') {
      return _missingEnvStatusText(
        'Image generation',
        _status.imageGenerationEnvKey,
        'Image generation is enabled but still needs a visible provider key before agents can use it.',
      );
    }
    return 'Image generation is enabled but still needs a visible provider key before agents can use it.';
  }

  function _audioStatusText() {
    if (_status.audioEnabled === false) {
      return 'Voice audio tools stay hidden until this capability is enabled.';
    }
    if (_status.audioConfigured === true) {
      return 'Voice audio tools are ready for TTS, transcription, dubbing, cloning, conversion, and music.';
    }
    if (_status.audioSource === 'missing_env') {
      return _missingEnvStatusText(
        'Voice audio',
        _status.audioEnvKey,
        'Voice audio is enabled but still needs a visible provider key.',
      );
    }
    return 'Voice audio is enabled but still needs a visible provider key.';
  }

  function _memoryEmbeddingStatusText(providerId = '') {
    const current = ((_config || {}).memory || {}).embedding || {};
    const savedProvider = current.provider || current.mode || _status.memoryEmbeddingProvider || 'auto';
    const provider = providerId || savedProvider;
    if (provider === 'none') {
      return 'Keyword search stays available; embeddings are disabled.';
    }
    if (provider === 'local') {
      return 'Uses local BGE embeddings; no remote key is needed.';
    }
    if (provider === 'ollama') {
      return 'Uses your Ollama server; no API key is needed.';
    }
    if (provider === 'auto') {
      return 'Local-first memory search; optional remote fallback can be configured.';
    }
    if (provider === savedProvider && _status.memoryEmbeddingConfigured === true) {
      return 'Remote memory embeddings are configured for new turns.';
    }
    if (provider === savedProvider && _status.memoryEmbeddingSource === 'missing_env') {
      return _missingEnvStatusText(
        'Remote memory embeddings',
        _status.memoryEmbeddingEnvKey,
        'Remote memory embeddings need a visible provider key before they can run.',
      );
    }
    return 'Remote memory embeddings need a visible provider key before they can run.';
  }

  function _toastEnvReferenceSave(
    surface,
    envKey,
    keySource = '',
    hasInlineKey = '',
    restartRequired = false,
  ) {
    const key = String(envKey || '').trim();
    if (!key || hasInlineKey) return false;
    if (keySource === 'missing_env' || restartRequired) {
      UI.toast(`${surface} saved $${key}. Start or restart the gateway with that variable set.`, 'warn', 5200);
      return true;
    }
    UI.toast(`${surface} saved $${key} reference. Keep it set for gateway restarts.`, 'info', 4200);
    return true;
  }

  function _renderFinishStep() {
    const router = (_config.squilla_router || {});
    const configuredProvider = _configuredProvider();
    const providerSummary = configuredProvider || 'not configured';
    const modelSummary = configuredProvider
      ? ((_config.llm || {}).model || 'SquillaRouter defaults')
      : 'not configured';
    const routerSummary = configuredProvider
      ? (router.enabled === false ? 'disabled' : 'SquillaRouter')
      : 'choose a provider first';
    const providerProxy = configuredProvider ? ((_config.llm || {}).proxy || '').trim() : '';
    const configArg = _configCliArg(_status.configPath);
    const envRecoveryCommands = Array.isArray(_status.envRecoveryCommands)
      ? _status.envRecoveryCommands
        .map(entry => ({
          label: entry.label || 'Set environment key',
          command: entry.command || '',
        }))
        .filter(entry => entry.command)
      : [];
    const fixCommands = _envFixCommands(envRecoveryCommands, configArg);
    const handoffCommands = [
      {
        label: 'Guided CLI',
        command: `opensquilla onboard --if-needed${configArg}`,
      },
      {
        label: 'Check status',
        command: `opensquilla onboard status${configArg}`,
      },
    ];
    const recipeCommands = [
      {
        label: 'Provider options',
        command: `opensquilla onboard catalog providers${configArg}`,
      },
      {
        label: 'Router tiers',
        command: `opensquilla onboard catalog router${configArg}`,
      },
      {
        label: 'Search options',
        command: `opensquilla onboard catalog search${configArg}`,
      },
      {
        label: 'Channel options',
        command: `opensquilla onboard catalog channels${configArg}`,
      },
      {
        label: 'Image options',
        command: `opensquilla onboard catalog image${configArg}`,
      },
      {
        label: 'Memory options',
        command: `opensquilla onboard catalog memory${configArg}`,
      },
    ];
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Finish</h3>
          <p>${_esc(_status.configPath || '')}</p>
        </header>
        <div class="setup-cli">
          ${_renderCliCommandGroup('Fix now', fixCommands)}
          ${_renderCliCommandGroup('CLI handoff', handoffCommands)}
          ${_renderCliCommandGroup('CLI recipes', recipeCommands)}
        </div>
        <div class="setup-summary">
          <div><span>Provider</span><strong>${_esc(providerSummary)}</strong></div>
          <div><span>Model</span><strong>${_esc(modelSummary)}</strong></div>
          ${providerProxy ? `<div><span>Proxy</span><strong>${_esc(providerProxy)}</strong></div>` : ''}
          <div><span>Router</span><strong>${_esc(routerSummary)}</strong></div>
          <div><span>Channels</span><strong>${_esc(String(_status.channelCount || 0))}</strong></div>
        </div>
        ${_renderReadinessSummary()}
        <div class="setup-actions">
          <button class="setup-btn" data-prev="extras">Back</button>
          <button class="setup-btn" data-reload>Refresh</button>
          <button class="setup-btn setup-btn--primary" data-exit-setup>Open Overview</button>
        </div>
      </section>`;
  }

  function _renderCliCommandGroup(title, commands) {
    if (!commands.length) return '';
    return `<section class="setup-cli__group" aria-label="${_esc(title)}">
      <div class="setup-cli__group-head">
        <h4>${_esc(title)}</h4>
      </div>
      ${commands.map(_renderCliCommand).join('')}
    </section>`;
  }

  function _envFixCommands(envRecoveryCommands, configArg) {
    if (!envRecoveryCommands.length) return [];
    return [
      ...envRecoveryCommands,
      {
        label: 'Restart gateway after env fix',
        command: `opensquilla gateway restart${configArg}`,
      },
    ];
  }

  function _renderCliCommand({ label, command }) {
    const safeCommand = _esc(command);
    const copyLabel = `Copy ${label} command`;
    return `<div class="setup-cli__row">
      <span class="setup-cli__label">${_esc(label)}</span>
      <code>${safeCommand}</code>
      <button class="setup-cli__copy" type="button" data-setup-copy-command="${safeCommand}" title="${_esc(copyLabel)}" aria-label="${_esc(copyLabel)}">
        ${icons.copy()}
      </button>
    </div>`;
  }

  function _renderReadinessSummary() {
    const details = _status.sectionDetails || {};
    const entries = Object.entries(details);
    if (!entries.length) return '';
    const required = entries.filter(([, detail]) => detail.required);
    const optional = entries.filter(([, detail]) => !detail.required);
    return `<div class="setup-readiness" aria-label="Onboarding readiness">
      ${_renderReadinessGroup('Required setup', required)}
      ${_renderReadinessGroup('Optional capabilities', optional)}
    </div>`;
  }

  function _renderReadinessGroup(title, entries) {
    if (!entries.length) return '';
    return `<div class="setup-readiness__group">
      <h4>${_esc(title)}</h4>
      ${entries.map(([name, detail]) => {
        const note = detail.detail ? `<em class="setup-readiness__detail">${_esc(detail.detail)}</em>` : '';
        const step = _setupStepForSection(name, detail);
        const action = _renderReadinessAction(step, detail, name);
        return `<div class="setup-readiness__row ${_readinessTone(detail, name)}">
          <span>${_esc(detail.label || name)}</span>
          <strong>${_esc(_readinessStatusLabel(detail, name))}</strong>
          <small>${detail.required ? 'Required' : 'Optional'}</small>
          ${action}
          ${note}
        </div>`;
      }).join('')}
    </div>`;
  }

  function _setupStepForSection(name, detail = {}) {
    if (_routerNeedsProvider(detail, name)) return 'provider';
    if (name === 'llm' || name === 'provider') return 'provider';
    if (name === 'router') return 'router';
    if (name === 'channels') return 'channels';
    if (name === 'search' || name === 'image_generation' || name === 'memory_embedding') return 'extras';
    return '';
  }

  function _routerNeedsProvider(detail, name) {
    return name === 'router'
      && detail.status === 'ok'
      && detail.detail === 'uses SquillaRouter after provider setup';
  }

  function _readinessActionLabel(detail, name) {
    if (_routerNeedsProvider(detail, name)) return 'Choose provider';
    if (detail.blocking || detail.actionRequired) return 'Fix';
    if (detail.status === 'ok') return 'Review';
    return 'Configure';
  }

  function _renderReadinessAction(step, detail, name) {
    if (!step) return '';
    const actionAriaLabel = _readinessActionAriaLabel(detail, name);
    return `<button type="button" class="setup-readiness__action" ` +
      `aria-label="${_esc(actionAriaLabel)}" title="${_esc(actionAriaLabel)}" ` +
      `data-step="${_esc(step)}">${_esc(_readinessActionLabel(detail, name))}</button>`;
  }

  function _readinessActionAriaLabel(detail, name) {
    const label = detail.label || name.replace(/_/g, ' ');
    if (_routerNeedsProvider(detail, name)) return `Choose provider for ${label}`;
    return `${_readinessActionLabel(detail, name)} ${label}`;
  }

  function _readinessTone(detail, name) {
    if (_routerNeedsProvider(detail, name)) return 'is-warn';
    if (detail.blocking || detail.actionRequired) return 'is-warn';
    if (detail.status === 'ok') return 'is-ok';
    return 'is-muted';
  }

  function _readinessStatusLabel(detail, name) {
    if (_routerNeedsProvider(detail, name)) return 'Provider first';
    if (detail.blocking || detail.actionRequired) return 'Needs action';
    return READINESS_LABELS[detail.status] || 'Optional';
  }

  function _fieldHtml(field, value, scope) {
    const required = field.required ? ' *' : '';
    const desc = field.description ? `<small class="setup-field-desc">${_esc(field.description)}</small>` : '';
    const showWhen = field.showWhen && Object.keys(field.showWhen).length ? _esc(JSON.stringify(field.showWhen)) : '';
    const rawName = String(field.name || 'field');
    const fieldName = `setup_${scope}_${rawName}`;
    const fieldId = `setup-${scope}-${rawName.replace(/[^a-zA-Z0-9_-]+/g, '-')}`;
    const attrs = `data-name="${_esc(rawName)}" data-scope="${scope}" data-show-when="${showWhen}" data-required="${field.required ? 'true' : 'false'}"`;
    if (field.type === 'bool') {
      return `<label class="setup-check" ${attrs} for="${_esc(fieldId)}"><input id="${_esc(fieldId)}" name="${_esc(fieldName)}" type="checkbox" ${field.default ? ' checked' : ''}><span>${_esc(field.label)}${required}${desc}</span></label>`;
    }
    if (field.type === 'select') {
      return `<label ${attrs} for="${_esc(fieldId)}"><span>${_esc(field.label)}${required}</span>${desc}<select id="${_esc(fieldId)}" name="${_esc(fieldName)}">
        ${(field.choices || []).map(choice => `<option value="${_esc(choice)}"${choice === value ? ' selected' : ''}>${_esc(choice)}</option>`).join('')}
      </select></label>`;
    }
    const isSecret = field.secret || field.type === 'password';
    const inputType = isSecret ? 'password' : (field.type === 'int' || field.type === 'float' ? 'number' : 'text');
    const placeholder = field.placeholder || (isSecret ? 'leave blank to keep current' : '');
    return `<label ${attrs} for="${_esc(fieldId)}"><span>${_esc(field.label)}${required}</span>${desc}<input id="${_esc(fieldId)}" name="${_esc(fieldName)}" type="${inputType}" data-secret="${isSecret}" value="${isSecret ? '' : _esc(String(value || ''))}" placeholder="${_esc(placeholder)}"></label>`;
  }

  function _bindStep() {
    _el.querySelectorAll('[data-next]').forEach(btn => btn.addEventListener('click', () => _setStep(btn.dataset.next)));
    _el.querySelectorAll('[data-prev]').forEach(btn => btn.addEventListener('click', () => _setStep(btn.dataset.prev)));
    _el.querySelectorAll('[data-exit-setup]').forEach(btn => btn.addEventListener('click', () => Router.navigate('/overview')));
    _el.querySelector('[data-reload]')?.addEventListener('click', async () => { await _load(); _draw(); });
    _el.querySelector('[data-provider-select]')?.addEventListener('change', () => {
      _drawProviderFields({ rememberDraft: true });
    });
    _el.querySelector('[data-channel-type]')?.addEventListener('change', () => {
      _channelDirty = true;
      _rememberDraft('channels');
      _drawChannelFields();
      _bindChannelDirtyTracking();
    });
    _el.querySelector('[data-search-provider]')?.addEventListener('change', _syncSearchProviderEnvHint);
    _el.querySelector('[data-memory-provider]')?.addEventListener('change', _syncMemoryProviderControls);
    _el.querySelector('[data-image-provider]')?.addEventListener('change', _syncImageProviderDefaults);
    _el.querySelector('[data-image-enabled]')?.addEventListener('change', _syncImageProviderDefaults);
    _el.querySelector('[data-audio-provider]')?.addEventListener('change', _syncAudioProviderDefaults);
    _el.querySelector('[data-audio-enabled]')?.addEventListener('change', _syncAudioProviderDefaults);
    _el.querySelectorAll('[data-setup-copy-command]').forEach(btn => btn.addEventListener('click', _onSetupCommandCopy));
    _bindChannelDirtyTracking();
    _bindConditionalSelects(_el);
    _applyConditionalFields();
    _el.querySelector('[data-save-provider]')?.addEventListener('click', _saveProvider);
    _el.querySelector('[data-save-router]')?.addEventListener('click', _saveRouter);
    _el.querySelector('[data-save-channel]')?.addEventListener('click', _saveChannel);
    _el.querySelector('[data-save-search]')?.addEventListener('click', _saveSearch);
    _el.querySelector('[data-save-memory]')?.addEventListener('click', _saveMemory);
    _el.querySelector('[data-save-image]')?.addEventListener('click', _saveImage);
    _el.querySelector('[data-save-audio]')?.addEventListener('click', _saveAudio);
  }

  async function _onSetupCommandCopy(event) {
    const btn = event.currentTarget;
    const command = btn.dataset.setupCopyCommand || '';
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

  function _setStep(step) {
    if (!step || step === _step) return;
    _rememberDraft(_step);
    _step = step;
    _draw();
  }

  function _rememberDraft(step = _step) {
    if (!_el) return;
    const fields = {};
    _el.querySelectorAll('.setup__body input, .setup__body select, .setup__body textarea').forEach((input, idx) => {
      fields[_fieldKey(input, idx)] = input.type === 'checkbox' ? input.checked : input.value;
    });
    _drafts.set(step, fields);
  }

  function _restoreDraft(step = _step) {
    const fields = _drafts.get(step);
    if (!fields || !_el) return;
    _el.querySelectorAll('.setup__body input, .setup__body select, .setup__body textarea').forEach((input, idx) => {
      const key = _fieldKey(input, idx);
      if (!Object.prototype.hasOwnProperty.call(fields, key)) return;
      if (input.type === 'checkbox') input.checked = fields[key] === true;
      else input.value = fields[key];
    });
  }

  function _restoreDynamicDraftFields() {
    if (_step === 'provider' && _drafts.has('provider')) {
      _drawProviderFields();
      _restoreDraft('provider');
    }
    if (_step === 'channels' && _drafts.has('channels')) {
      _drawChannelFields();
      _restoreDraft('channels');
    }
    if (_step === 'extras' && _drafts.has('extras')) {
      _syncSearchProviderKeyControls({ refreshEnv: false });
      _syncMemoryProviderControls();
      _syncAudioProviderDefaults({ refreshDefaults: false });
    }
  }

  function _fieldKey(input, idx) {
    const scoped = input.closest('[data-scope][data-name]');
    if (scoped) return `${scoped.dataset.scope}:${scoped.dataset.name}`;
    const tier = input.closest('[data-tier]');
    if (tier && input.dataset.tierField) return `tier:${tier.dataset.tier}:${input.dataset.tierField}`;
    if (input.dataset.routerMode !== undefined) return 'router:mode';
    if (input.dataset.defaultTier !== undefined) return 'router:defaultTier';
    if (input.dataset.providerSelect !== undefined) return 'provider:selected';
    if (input.dataset.channelType !== undefined) return 'channel:type';
    if (input.dataset.searchProvider !== undefined) return 'extras:search:provider';
    if (input.dataset.searchField) return `extras:search:${input.dataset.searchField}`;
    if (input.dataset.memoryProvider !== undefined) return 'extras:memory:provider';
    if (input.dataset.memoryField) return `extras:memory:${input.dataset.memoryField}`;
    if (input.dataset.imageProvider !== undefined) return 'extras:image:provider';
    if (input.dataset.imageEnabled !== undefined) return 'extras:image:enabled';
    if (input.dataset.imageField) return `extras:image:${input.dataset.imageField}`;
    if (input.dataset.audioProvider !== undefined) return 'extras:audio:provider';
    if (input.dataset.audioEnabled !== undefined) return 'extras:audio:enabled';
    if (input.dataset.audioField) return `extras:audio:${input.dataset.audioField}`;
    return `field:${idx}`;
  }

  function _bindChannelDirtyTracking() {
    const root = _el.querySelector('[data-channel-dirty-root]');
    if (!root) return;
    root.querySelectorAll('input, select, textarea').forEach(input => {
      const markDirty = () => {
        _channelDirty = true;
        _rememberDraft('channels');
      };
      input.addEventListener('input', markDirty);
      input.addEventListener('change', markDirty);
    });
  }

  function _drawProviderFields({ rememberDraft = false } = {}) {
    const providerId = _el.querySelector('[data-provider-select]')?.value;
    const saveButton = _el.querySelector('[data-save-provider]');
    if (saveButton) saveButton.disabled = !providerId;
    const nextButton = _el.querySelector('[data-next="router"]');
    if (nextButton) nextButton.disabled = !providerId;
    const spec = (_catalog.providers || []).find(p => p.providerId === providerId);
    const routerSupport = _el.querySelector('[data-provider-router-support-label]');
    if (routerSupport) {
      routerSupport.textContent = _providerRouterSupportText(spec);
      routerSupport.className = `setup-provider-meta__badge ${_providerRouterSupportTone(spec)}`;
    }
    if (!spec) return;
    const providerFields = spec.fields || [];
    const providerCoreFields = providerFields.filter(field => !_isProviderAdvancedField(field, spec));
    const providerAdvancedFields = providerFields.filter(field => _isProviderAdvancedField(field, spec));
    const values = _providerConfigFor(providerId);
    const box = _el.querySelector('.setup-provider-fields');
    if (box) box.innerHTML = _renderProviderFields(providerCoreFields, values);
    const advanced = _el.querySelector('[data-provider-advanced-wrap]');
    if (advanced) {
      const providerAdvancedOpen = _providerAdvancedOpen(providerAdvancedFields, values) ? ' open' : '';
      advanced.innerHTML = _renderProviderAdvancedFields(
        providerAdvancedFields,
        values,
        providerAdvancedOpen,
      );
    }
    _replaceNeedList('[data-provider-needs]', spec?.whatYouNeed, 'Provider needs', 'data-provider-needs');
    const summary = _el.querySelector('[data-provider-summary]');
    if (summary) summary.textContent = spec.label || providerId || 'not configured';
    _bindConditionalSelects(_el);
    _applyConditionalFields();
    if (rememberDraft) _rememberDraft('provider');
  }

  function _drawChannelFields() {
    const type = _el.querySelector('[data-channel-type]')?.value;
    _channelType = type;
    const spec = (_catalog.channels || []).find(c => c.type === type);
    const box = _el.querySelector('.setup-channel-fields');
    if (box && spec) box.innerHTML = _renderChannelFields(spec);
    _replaceNeedList('[data-channel-needs]', spec?.whatYouNeed, 'Channel needs', 'data-channel-needs');
    _bindConditionalSelects(box || _el);
    _applyConditionalFields();
  }

  function _syncSearchProviderEnvHint() {
    _syncSearchProviderKeyControls();
    _rememberDraft('extras');
  }

  function _syncSearchProviderKeyControls({ refreshEnv = true } = {}) {
    const providerId = _el.querySelector('[data-search-provider]')?.value;
    const spec = (_catalog.searchProviders || []).find(p => p.providerId === providerId) || {};
    const requiresKey = spec.requiresApiKey === true;
    const keyInput = _el.querySelector('[data-search-field="api_key"]');
    const envInput = _el.querySelector('[data-search-field="api_key_env"]');
    const keyFields = _el.querySelector('[data-search-key-fields]');
    _replaceNeedList('[data-search-needs]', _credentialNeedList(spec.whatYouNeed, envInput?.value || spec.envKey), 'Search needs', 'data-search-needs');
    if (keyFields) {
      keyFields.hidden = !requiresKey;
    }
    if (keyInput) {
      keyInput.disabled = !requiresKey;
      keyInput.placeholder = requiresKey ? 'leave blank to keep current' : 'not required for this provider';
      if (!requiresKey) keyInput.value = '';
      keyInput.closest('label')?.classList.toggle('is-disabled', !requiresKey);
    }
    if (envInput) {
      envInput.disabled = !requiresKey;
      envInput.placeholder = requiresKey ? (spec.envKey || 'SEARCH_API_KEY') : 'not required for this provider';
      if (!requiresKey) envInput.value = '';
      else if (refreshEnv) envInput.value = spec.envKey || '';
      envInput.closest('label')?.classList.toggle('is-disabled', !requiresKey);
    }
  }

  function _syncMemoryProviderControls() {
    const providerId = _el.querySelector('[data-memory-provider]')?.value || 'auto';
    const memorySpec = (_catalog.memoryEmbeddingProviders || []).find(p => p.providerId === providerId) || {};
    const remoteControlEnabled = ['auto', 'openai', 'openai-compatible', 'ollama'].includes(providerId);
    const apiKeyEnabled = providerId === 'auto' || memorySpec.requiresApiKey === true;
    const modelInput = _el.querySelector('[data-memory-field="model"]');
    const apiKeyInput = _el.querySelector('[data-memory-field="api_key"]');
    const envInput = _el.querySelector('[data-memory-field="api_key_env"]');
    const baseInput = _el.querySelector('[data-memory-field="base_url"]');
    const onnxInput = _el.querySelector('[data-memory-field="onnx_dir"]');
    const apiKeyLabel = _el.querySelector('[data-memory-api-key-label]');
    const localField = _el.querySelector('[data-memory-local-field]');
    const remoteOptions = _el.querySelector('[data-memory-remote-options]');
    const statusText = _el.querySelector('[data-memory-status-text]');
    const localControlEnabled = providerId === 'local';
    const hasRemoteOptions = remoteControlEnabled || apiKeyEnabled;
    _replaceNeedList('[data-memory-needs]', _memoryNeedList(memorySpec, providerId, envInput?.value || memorySpec.envKey), 'Memory needs', 'data-memory-needs');
    if (remoteOptions) {
      remoteOptions.hidden = !hasRemoteOptions;
      remoteOptions.open = providerId !== 'auto' && hasRemoteOptions;
      const summary = remoteOptions.querySelector('summary');
      if (summary) summary.textContent = providerId === 'auto' ? 'Remote fallback options' : 'Connection options';
    }
    if (modelInput) {
      modelInput.disabled = !remoteControlEnabled;
      modelInput.placeholder = providerId === 'ollama' ? 'nomic-embed-text' : (remoteControlEnabled ? 'text-embedding-3-small' : 'not used by this provider');
      if (!remoteControlEnabled) modelInput.value = '';
      modelInput.closest('label')?.classList.toggle('is-disabled', !remoteControlEnabled);
    }
    if (apiKeyInput) {
      apiKeyInput.disabled = !apiKeyEnabled;
      apiKeyInput.placeholder = apiKeyEnabled ? 'leave blank to keep current' : 'not required for this provider';
      if (!apiKeyEnabled) apiKeyInput.value = '';
      apiKeyInput.closest('label')?.classList.toggle('is-disabled', !apiKeyEnabled);
    }
    if (envInput) {
      envInput.disabled = !apiKeyEnabled;
      envInput.placeholder = memorySpec.envKey || 'OPENAI_API_KEY';
      if (!apiKeyEnabled) envInput.value = '';
      else if (!envInput.value) envInput.value = memorySpec.envKey || '';
      envInput.closest('label')?.classList.toggle('is-disabled', !apiKeyEnabled);
    }
    if (apiKeyLabel) {
      apiKeyLabel.textContent = providerId === 'auto' ? 'Fallback API key' : 'API key';
    }
    if (baseInput) {
      baseInput.disabled = !remoteControlEnabled;
      baseInput.placeholder = providerId === 'ollama' ? 'http://localhost:11434' : (remoteControlEnabled ? 'https://api.openai.com/v1' : 'not used by this provider');
      if (!remoteControlEnabled) baseInput.value = '';
      baseInput.closest('label')?.classList.toggle('is-disabled', !remoteControlEnabled);
    }
    if (onnxInput) {
      onnxInput.disabled = !localControlEnabled;
      onnxInput.placeholder = localControlEnabled ? 'models/bge-onnx' : 'only for bundled local provider';
      if (!localControlEnabled) onnxInput.value = '';
      onnxInput.closest('label')?.classList.toggle('is-disabled', !localControlEnabled);
    }
    if (localField) {
      localField.hidden = !localControlEnabled;
    }
    if (statusText) {
      statusText.textContent = _memoryEmbeddingStatusText(providerId);
    }
    _rememberDraft('extras');
  }

  function _syncImageProviderDefaults() {
    const enabledInput = _el.querySelector('[data-image-enabled]');
    const imageEnabled = enabledInput?.checked !== false;
    const imageConfigFields = _el.querySelector('[data-image-config-fields]');
    if (imageConfigFields) imageConfigFields.hidden = !imageEnabled;
    const providerId = _el.querySelector('[data-image-provider]')?.value;
    const spec = (_catalog.imageGenerationProviders || []).find(p => p.providerId === providerId) || {};
    const envInput = _el.querySelector('[data-image-field="api_key_env"]');
    if (envInput) {
      envInput.value = spec.requiresApiKey ? (spec.envKey || '') : '';
    }
    const imageNeeds = imageEnabled
      ? _credentialNeedList(spec.whatYouNeed, envInput?.value || spec.envKey)
      : ['No key required while image generation is disabled.'];
    _replaceNeedList('[data-image-needs]', imageNeeds, 'Image needs', 'data-image-needs');
    const primaryInput = _el.querySelector('[data-image-field="primary"]');
    const currentProvider = (primaryInput?.value || '').split('/')[0];
    if (primaryInput && currentProvider !== providerId) {
      primaryInput.value = spec.defaultModel || primaryInput.value;
    }
    const baseInput = _el.querySelector('[data-image-field="base_url"]');
    if (baseInput) {
      baseInput.value = spec.defaultBaseUrl || baseInput.value;
    }
    _rememberDraft('extras');
  }

  function _syncAudioProviderDefaults({ refreshDefaults = true } = {}) {
    const enabledInput = _el.querySelector('[data-audio-enabled]');
    const audioEnabled = enabledInput?.checked === true;
    const audioConfigFields = _el.querySelector('[data-audio-config-fields]');
    if (audioConfigFields) audioConfigFields.hidden = !audioEnabled;
    const providerId = _el.querySelector('[data-audio-provider]')?.value || 'elevenlabs';
    const spec = (_catalog.audioProviders || []).find(p => p.providerId === providerId) || {};
    const envInput = _el.querySelector('[data-audio-field="api_key_env"]');
    const baseInput = _el.querySelector('[data-audio-field="base_url"]');
    const voiceInput = _el.querySelector('[data-audio-field="tts_voice"]');
    const modelInput = _el.querySelector('[data-audio-field="tts_model"]');
    const languageInput = _el.querySelector('[data-audio-field="language_code"]');
    if (envInput && refreshDefaults) envInput.value = spec.envKey || '';
    if (baseInput && refreshDefaults) baseInput.value = spec.defaultBaseUrl || baseInput.value;
    if (voiceInput && refreshDefaults) voiceInput.value = spec.defaultTtsVoice || voiceInput.value;
    if (modelInput && refreshDefaults) modelInput.value = spec.defaultTtsModel || modelInput.value;
    if (languageInput && refreshDefaults && !languageInput.value) {
      languageInput.value = spec.defaultLanguageCode || '';
    }
    const audioNeeds = audioEnabled
      ? _credentialNeedList(spec.whatYouNeed, envInput?.value || spec.envKey)
      : ['No key required while voice audio is disabled.'];
    _replaceNeedList('[data-audio-needs]', audioNeeds, 'Audio needs', 'data-audio-needs');
    _rememberDraft('extras');
  }

  function _bindConditionalSelects(root) {
    root.querySelectorAll('select').forEach(sel => sel.addEventListener('change', _applyConditionalFields));
  }

  function _applyConditionalFields() {
    _el.querySelectorAll('[data-show-when]').forEach(label => {
      const raw = label.dataset.showWhen || '';
      if (!raw) {
        label.hidden = false;
        return;
      }
      let visible = true;
      try {
        const cond = JSON.parse(raw);
        visible = Object.entries(cond).every(([name, expected]) => {
          const owner = label.parentElement || _el;
          const input = owner.querySelector(`[data-name="${CSS.escape(name)}"] select, [data-name="${CSS.escape(name)}"] input`);
          return input ? String(input.value) === String(expected) : true;
        });
      } catch (_) {
        visible = true;
      }
      label.hidden = !visible;
    });
  }

  function _readScopedFields(scope) {
    const out = {};
    _el.querySelectorAll(`[data-scope="${scope}"][data-name]`).forEach(label => {
      if (label.hidden) return;
      const input = label.querySelector('input, select');
      if (!input) return;
      const name = scope === 'channel' ? label.dataset.name : _camel(label.dataset.name);
      if (input.type === 'checkbox') out[name] = input.checked;
      else if (input.value !== '' || input.dataset.secret !== 'true') out[name] = input.value;
    });
    return out;
  }

  function _validateScopedRequiredFields(scope) {
    let missing = '';
    _el.querySelectorAll(`[data-scope="${scope}"][data-name][data-required="true"]`).forEach(label => {
      if (missing || label.hidden) return;
      const input = label.querySelector('input, select');
      if (!input || input.type === 'checkbox') return;
      if (String(input.value || '').trim()) return;
      if (input.dataset.secret === 'true' && _canKeepExistingSecret(scope)) return;
      const labelText = label.querySelector('span')?.textContent || label.dataset.name || 'required field';
      missing = labelText.replace(/\s*\*\s*$/, '').trim();
    });
    return missing;
  }

  function _canKeepExistingSecret(scope) {
    if (scope !== 'channel') return false;
    const type = _el.querySelector('[data-channel-type]')?.value || _channelType || '';
    const name = _el.querySelector('[data-scope="channel"][data-name="name"] input')?.value || '';
    return (_channelStatus.channels || []).some(row => (
      row.configured !== false
      && String(row.type || '') === String(type)
      && String(row.name || '') === String(name).trim()
    ));
  }

  async function _saveProvider() {
    const providerId = _el.querySelector('[data-provider-select]')?.value;
    if (!providerId) {
      UI.toast('Choose a provider before saving.', 'err');
      return;
    }
    try {
      await _rpc.call('onboarding.provider.configure', Object.assign({ providerId }, _readScopedFields('provider')));
      await _load();
      if (_providerEnvMissing()) {
        UI.toast(`${_providerEnvKey()} is not visible to this gateway process.`, 'err');
        _step = 'provider';
        _draw();
        return;
      }
      UI.toast('Provider saved.', 'info');
      _drafts.delete('provider');
      _step = 'router';
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveRouter() {
    const provider = _effectiveProvider();
    const configuredProvider = _configuredProvider();
    if (!provider) {
      UI.toast('Choose a provider before saving router tiers.', 'err');
      return;
    }
    if (provider !== configuredProvider) {
      UI.toast('Save the provider before saving router tiers.', 'err');
      return;
    }
    const tiers = {};
    _el.querySelectorAll('[data-tier]').forEach(row => {
      const tier = {};
      row.querySelectorAll('[data-tier-field]').forEach(input => {
        const key = input.dataset.tierField;
        tier[key] = input.type === 'checkbox' ? input.checked : input.value;
      });
      if (row.dataset.tier === 'image_model') {
        tier.supportsImage = true;
        tier.image_only = true;
      }
      tiers[row.dataset.tier] = tier;
    });
    try {
      await _rpc.call('onboarding.router.configure', {
        mode: _el.querySelector('[data-router-mode]')?.value || 'recommended',
        defaultTier: _el.querySelector('[data-default-tier]')?.value || 'c1',
        tiers,
      });
      UI.toast('Router saved.', 'info');
      await _load();
      _drafts.delete('router');
      _step = 'channels';
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveChannel() {
    const missing = _validateScopedRequiredFields('channel');
    if (missing) {
      UI.toast(`${missing} is required.`, 'err');
      return;
    }
    const entry = Object.assign({ type: _el.querySelector('[data-channel-type]')?.value }, _readScopedFields('channel'));
    try {
      await _rpc.call('onboarding.channel.probe', { entry });
      await _rpc.call('onboarding.channel.upsert', { entry });
      UI.toast('Channel saved. Restart required.', 'info');
      _channelDirty = false;
      _drafts.delete('channels');
      await _loadChannelStatus();
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveMemory() {
    const params = { providerId: _el.querySelector('[data-memory-provider]')?.value || 'auto' };
    _el.querySelectorAll('[data-memory-field]').forEach(input => {
      if (input.disabled) return;
      if (input.value !== '' || input.dataset.secret !== 'true') params[_camel(input.dataset.memoryField)] = input.value;
    });
    try {
      const res = await _rpc.call('onboarding.memory_embedding.configure', params);
      const remote = ((res || {}).entry || {}).remote || {};
      if (!_toastEnvReferenceSave(
        'Memory embedding',
        remote.api_key_env,
        '',
        remote.api_key,
        (res || {}).restartRequired,
      )) {
        UI.toast('Memory embedding saved. Restart required.', 'info');
      }
      await _load();
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveSearch() {
    const params = { providerId: _el.querySelector('[data-search-provider]')?.value || 'duckduckgo' };
    _el.querySelectorAll('[data-search-field]').forEach(input => {
      if (input.value === '' && input.dataset.secret === 'true') return;
      const key = _camel(input.dataset.searchField);
      if (input.type === 'checkbox') params[key] = input.checked;
      else params[key] = input.type === 'number' ? Number.parseInt(input.value || '0', 10) : input.value;
    });
    try {
      await _rpc.call('onboarding.search.configure', params);
      UI.toast('Search saved.', 'info');
      await _load();
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveImage() {
    const params = { providerId: _el.querySelector('[data-image-provider]')?.value || 'openrouter' };
    params.enabled = _el.querySelector('[data-image-enabled]')?.checked !== false;
    _el.querySelectorAll('[data-image-field]').forEach(input => {
      if (input.value !== '' || input.dataset.secret !== 'true') params[_camel(input.dataset.imageField)] = input.value;
    });
    try {
      const res = await _rpc.call('onboarding.imageGeneration.configure', params);
      const entry = (res || {}).entry || {};
      if (!_toastEnvReferenceSave(
        'Image generation',
        entry.api_key_env,
        entry.api_key_source,
        entry.api_key,
        (res || {}).restartRequired,
      )) {
        UI.toast('Image generation saved.', 'info');
      }
      await _load();
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveAudio() {
    const params = { providerId: _el.querySelector('[data-audio-provider]')?.value || 'elevenlabs' };
    params.enabled = _el.querySelector('[data-audio-enabled]')?.checked === true;
    _el.querySelectorAll('[data-audio-field]').forEach(input => {
      if (input.value !== '' || input.dataset.secret !== 'true') params[_camel(input.dataset.audioField)] = input.value;
    });
    try {
      const res = await _rpc.call('onboarding.audio.configure', params);
      const entry = (res || {}).entry || {};
      if (!_toastEnvReferenceSave(
        'Voice audio',
        entry.api_key_env,
        entry.api_key_source,
        entry.api_key,
        (res || {}).restartRequired,
      )) {
        UI.toast('Voice audio saved.', 'info');
      }
      await _load();
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _loadChannelStatus() {
    _channelStatus = await _rpc.call('channels.status').catch(() => ({ channels: [] }));
  }

  function _startChannelPolling() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(async () => {
      if (!_el || _step !== 'channels') return;
      if (_channelDirty) return;
      await _loadChannelStatus();
      _draw();
    }, 5000);
  }

  function _camel(name) {
    return String(name || '').replace(/_([a-z])/g, (_, c) => c.toUpperCase());
  }

  function _configCliArg(configPath) {
    return configPath ? ` --config ${_shellArg(configPath)}` : '';
  }

  function _shellArg(value) {
    const text = String(value || '');
    if (/^[A-Za-z0-9_@%+=:,./~-]+$/.test(text)) return text;
    return `'${text.replace(/'/g, `'\\''`)}'`;
  }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function destroy() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = null;
    _el = null;
    _rpc = null;
    _catalog = {};
    _status = {};
    _config = {};
    _channelStatus = { channels: [] };
    _step = 'provider';
    _hasAutoSelectedStep = false;
  }

  return { render, destroy };
})();

window.SetupView = SetupView;
