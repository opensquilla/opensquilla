/** OpenSquilla Web UI - setup flow. */

const SetupView = (() => {
  const STEPS = [
    { id: 'provider', label: 'Provider' },
    { id: 'router', label: 'Router Tiers' },
    { id: 'channels', label: 'Channels' },
    { id: 'extras', label: 'Extras' },
    { id: 'finish', label: 'Finish' },
  ];
  const TEXT_TIERS = ['t0', 't1', 't2', 't3'];
  const TIER_LABELS = {
    t0: 'Fast/simple (t0)',
    t1: 'Balanced default (t1)',
    t2: 'Stronger reasoning (t2)',
    t3: 'Max quality (t3)',
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

  async function render(el) {
    _el = el;
    _rpc = App.getRpc();
    await _rpc.waitForConnection();
    await _load();
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
    _el.innerHTML = `
      <section class="setup">
        <header class="setup__head">
          <div>
            <p class="setup__kicker">OpenSquilla setup</p>
            <h2>Core runtime configuration</h2>
          </div>
          <div class="setup__head-aside">
            <button type="button" class="setup__exit" data-exit-setup aria-label="Exit setup and return to Overview">
              <span aria-hidden="true">←</span><span>Exit setup</span>
            </button>
            <div class="setup__status ${_status.needsOnboarding ? 'is-warn' : 'is-ok'}">
              ${_status.needsOnboarding ? 'Action needed' : 'Configured'}
            </div>
          </div>
        </header>
        <nav class="setup-stepper" aria-label="Setup steps">
          ${STEPS.map((s, idx) => `<button class="setup-stepper__item ${s.id === _step ? 'is-active' : ''}" data-step="${s.id}">
            <span>${idx + 1}</span>${_esc(s.label)}
          </button>`).join('')}
        </nav>
        <div class="setup__body">${_renderCurrentStep()}</div>
      </section>`;

    _el.querySelectorAll('[data-step]').forEach(btn => {
      btn.addEventListener('click', () => {
        _step = btn.dataset.step;
        _draw();
      });
    });
    _bindStep();
  }

  function _renderCurrentStep() {
    if (_step === 'router') return _renderRouterStep();
    if (_step === 'channels') return _renderChannelsStep();
    if (_step === 'extras') return _renderExtrasStep();
    if (_step === 'finish') return _renderFinishStep();
    return _renderProviderStep();
  }

  function _renderProviderStep() {
    const providers = (_catalog.providers || []).filter(p => p.runtimeSupported);
    const current = (_config.llm || {});
    const selected = current.provider || providers[0]?.providerId || 'openrouter';
    const spec = providers.find(p => p.providerId === selected) || providers[0] || {};
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Provider</h3>
          <p>${_esc(current.provider || 'not configured')}</p>
        </header>
        <div class="setup-form">
          <label><span>Provider</span>
            <select data-provider-select>
              ${providers.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === selected ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
            </select>
          </label>
          <div class="setup-provider-fields">
            ${_renderProviderFields(spec, current)}
          </div>
          ${_providerEnvWarning()}
          <div class="setup-actions">
            <button class="setup-btn setup-btn--primary" data-save-provider>Save Provider</button>
            <button class="setup-btn" data-next="router">Next</button>
          </div>
        </div>
      </section>`;
  }

  function _renderProviderFields(spec, current) {
    return (spec.fields || []).map(field => {
      const name = field.name;
      let value = '';
      if (name === 'model') value = current.model || field.default || '';
      else if (name === 'base_url') value = current.base_url || field.default || '';
      else if (name === 'proxy') value = current.proxy || '';
      else if (name === 'api_key_env') value = current.api_key_env || (current.api_key ? '' : field.default || '');
      return _fieldHtml(field, value, 'provider');
    }).join('');
  }

  function _providerEnvMissing() {
    return _status.llmSource === 'missing_env';
  }

  function _providerEnvKey() {
    return ((_config.llm || {}).api_key_env || 'the selected API key environment variable');
  }

  function _providerEnvWarning() {
    if (!_providerEnvMissing()) return '';
    const envKey = _providerEnvKey();
    return `<div class="setup-warning">${_esc(envKey)} is not visible to this gateway process. Set it before starting or restarting the gateway, or paste an API key instead.</div>`;
  }

  function _renderRouterStep() {
    const router = (_config.squilla_router || {});
    const provider = (_config.llm || {}).provider || 'openrouter';
    const catalog = _catalog.routerProfiles || {};
    const profiles = catalog.profiles || [];
    const profile = profiles.find(p => p.providerId === provider) || profiles.find(p => p.profileId === 'openrouter') || {};
    const tiers = Object.assign({}, profile.tiers || {}, router.tiers || {});
    const defaultTier = router.default_tier || catalog.defaultTier || 't1';
    const mode = router.enabled === false ? 'disabled' : 'recommended';
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Router Tiers</h3>
          <p>${_esc(provider)} / ${_esc(_tierLabel(defaultTier))}</p>
        </header>
        <div class="setup-router-toolbar">
          <label><span>Mode</span>
            <select data-router-mode>
              <option value="recommended"${mode === 'recommended' ? ' selected' : ''}>SquillaRouter</option>
              <option value="disabled"${mode === 'disabled' ? ' selected' : ''}>Disabled</option>
            </select>
          </label>
          <label><span>Default text model</span>
            <select data-default-tier>
              ${TEXT_TIERS.map(t => `<option value="${t}"${t === defaultTier ? ' selected' : ''}>${_esc(_tierLabel(t))}</option>`).join('')}
            </select>
          </label>
        </div>
        <div class="setup-tier-table" role="table">
          <div class="setup-tier-table__row is-head" role="row">
            <span>Tier</span><span>Provider</span><span>Model</span><span>Thinking</span><span>Image</span>
          </div>
          ${Object.entries(tiers).filter(([name]) => TEXT_TIERS.includes(name) || name === 'image_model').map(([name, tier]) => _tierRow(name, tier)).join('')}
        </div>
        <div class="setup-actions">
          <button class="setup-btn" data-prev="provider">Back</button>
          <button class="setup-btn setup-btn--primary" data-save-router>Save Router</button>
          <button class="setup-btn" data-next="channels">Next</button>
        </div>
      </section>`;
  }

  function _tierRow(name, tier) {
    return `<div class="setup-tier-table__row" role="row" data-tier="${_esc(name)}">
      <span><code>${_esc(name)}</code></span>
      <input data-tier-field="provider" value="${_esc(tier.provider || '')}">
      <input data-tier-field="model" value="${_esc(tier.model || '')}">
      <select data-tier-field="thinkingLevel">
        ${['', 'off', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh'].map(v => `<option value="${v}"${v === (tier.thinkingLevel || tier.thinking_level || '') ? ' selected' : ''}>${v || '-'}</option>`).join('')}
      </select>
      <input type="checkbox" data-tier-field="supportsImage"${tier.supportsImage || tier.supports_image ? ' checked' : ''}>
    </div>`;
  }

  function _tierLabel(tier) {
    return TIER_LABELS[tier] || tier || 'Balanced default (t1)';
  }

  function _renderChannelsStep() {
    const channels = (_catalog.channels || []);
    const selected = channels.some(c => c.type === _channelType) ? _channelType : (channels[0]?.type || 'telegram');
    _channelType = selected;
    const runtimeRows = (_channelStatus.channels || []).filter(row => row.configured !== false);
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Channels</h3>
          <p>${runtimeRows.length} configured</p>
        </header>
        <div class="setup-channel-grid">
          <div class="setup-form">
            <label><span>Channel type</span>
              <select data-channel-type>
                ${channels.map(c => `<option value="${_esc(c.type)}"${c.type === selected ? ' selected' : ''}>${_esc(c.label)}</option>`).join('')}
              </select>
            </label>
            <div class="setup-channel-fields">${_renderChannelFields(channels.find(c => c.type === selected))}</div>
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
    const imageProviders = (_catalog.imageGenerationProviders || []).filter(p => p.runtimeSupported);
    const memoryProviders = _catalog.memoryEmbeddingProviders || [];
    const current = ((_config || {}).memory || {}).embedding || {};
    const effectiveProvider = current.provider || current.mode || 'auto';
    const currentMode = current.mode; // current.mode is kept explicit for static coverage.
    const imageSpec = imageProviders[0] || {};
    const field = (imageSpec.fields || []).find(candidate => candidate.name === 'enabled') || { default: true };
    const imageEnabledDefault = _status.imageGenerationEnabled === false ? false : field.default !== false;
    const imageProviderSelected = _status.imageGenerationProvider || (_status.imageGenerationPrimary || '').split('/')[0] || imageProviders[0]?.providerId || 'openrouter';
    const imageStatusText = _imageGenerationStatusText();
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Extras</h3>
          <p>${_esc(effectiveProvider || currentMode || 'auto')}</p>
        </header>
        <div class="setup-extras">
          <div class="setup-mini">
            <h4>Memory embedding</h4>
            <label><span>Provider</span>
              <select data-memory-provider>
                ${memoryProviders.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === effectiveProvider ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
              </select>
            </label>
            <label><span>Model</span><input data-memory-field="model" value="${_esc((current.remote || {}).model || '')}" placeholder="text-embedding-3-small"></label>
            <label><span>Remote fallback API key</span><input type="password" data-memory-field="api_key" data-secret="true" placeholder="leave blank to keep current"></label>
            <label><span>Base URL</span><input data-memory-field="base_url" value="${_esc((current.remote || {}).base_url || '')}" placeholder="https://api.openai.com/v1"></label>
            <button class="setup-btn setup-btn--primary" data-save-memory>Save Memory</button>
          </div>
          <div class="setup-mini">
            <h4>Image generation</h4>
            <p class="setup-muted">${_esc(imageStatusText)}</p>
            <label><span>Provider</span>
              <select data-image-provider>
                ${imageProviders.map(p => `<option value="${_esc(p.providerId)}"${p.providerId === imageProviderSelected ? ' selected' : ''}>${_esc(p.label)}</option>`).join('')}
              </select>
            </label>
            <label><span>Primary model</span><input data-image-field="primary" value="${_esc(_status.imageGenerationPrimary || '')}"></label>
            <label><span>API key</span><input type="password" data-image-field="api_key" data-secret="true" placeholder="leave blank to keep current"></label>
            <label class="setup-check"><input type="checkbox" data-image-enabled${imageEnabledDefault ? ' checked' : ''}><span>Enabled</span></label>
            <button class="setup-btn setup-btn--primary" data-save-image>Save Image</button>
          </div>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" data-prev="channels">Back</button>
          <button class="setup-btn" data-next="finish">Next</button>
        </div>
      </section>`;
  }

  function _imageGenerationStatusText() {
    if (_status.imageGenerationEnabled === false) {
      return 'image_generate is hidden from agents until this capability is enabled.';
    }
    if (_status.imageGenerationConfigured === true) {
      return 'image_generate will be available in new turns once the gateway has the visible key.';
    }
    return 'image_generate is enabled but still needs a visible provider key before agents can use it.';
  }

  function _renderFinishStep() {
    const router = (_config.squilla_router || {});
    return `
      <section class="setup-panel">
        <header class="setup-panel__head">
          <h3>Finish</h3>
          <p>${_esc(_status.configPath || '')}</p>
        </header>
        <div class="setup-summary">
          <div><span>Provider</span><strong>${_esc((_config.llm || {}).provider || '')}</strong></div>
          <div><span>Model</span><strong>${_esc((_config.llm || {}).model || '')}</strong></div>
          <div><span>Router</span><strong>${router.enabled === false ? 'disabled' : _esc(router.tier_profile || 'openrouter-mix')}</strong></div>
          <div><span>Channels</span><strong>${_esc(String(_status.channelCount || 0))}</strong></div>
        </div>
        <div class="setup-cli">
          <code>opensquilla onboard --if-needed</code>
          <code>opensquilla configure provider</code>
          <code>opensquilla channels status &lt;name&gt; --json</code>
        </div>
        <div class="setup-actions">
          <button class="setup-btn" data-prev="extras">Back</button>
          <button class="setup-btn" data-reload>Refresh</button>
          <button class="setup-btn setup-btn--primary" data-exit-setup>Open Overview</button>
        </div>
      </section>`;
  }

  function _fieldHtml(field, value, scope) {
    const required = field.required ? ' *' : '';
    const desc = field.description ? `<small class="setup-field-desc">${_esc(field.description)}</small>` : '';
    const showWhen = field.showWhen && Object.keys(field.showWhen).length ? _esc(JSON.stringify(field.showWhen)) : '';
    const attrs = `data-name="${_esc(field.name)}" data-scope="${scope}" data-show-when="${showWhen}"`;
    if (field.type === 'bool') {
      return `<label class="setup-check" ${attrs}><input type="checkbox" ${field.default ? ' checked' : ''}><span>${_esc(field.label)}${required}${desc}</span></label>`;
    }
    if (field.type === 'select') {
      return `<label ${attrs}><span>${_esc(field.label)}${required}</span>${desc}<select>
        ${(field.choices || []).map(choice => `<option value="${_esc(choice)}"${choice === value ? ' selected' : ''}>${_esc(choice)}</option>`).join('')}
      </select></label>`;
    }
    const isSecret = field.secret || field.type === 'password';
    const inputType = isSecret ? 'password' : (field.type === 'int' || field.type === 'float' ? 'number' : 'text');
    const placeholder = field.placeholder || (isSecret ? 'leave blank to keep current' : '');
    return `<label ${attrs}><span>${_esc(field.label)}${required}</span>${desc}<input type="${inputType}" data-secret="${isSecret}" value="${isSecret ? '' : _esc(String(value || ''))}" placeholder="${_esc(placeholder)}"></label>`;
  }

  function _bindStep() {
    _el.querySelectorAll('[data-next]').forEach(btn => btn.addEventListener('click', () => { _step = btn.dataset.next; _draw(); }));
    _el.querySelectorAll('[data-prev]').forEach(btn => btn.addEventListener('click', () => { _step = btn.dataset.prev; _draw(); }));
    _el.querySelectorAll('[data-exit-setup]').forEach(btn => btn.addEventListener('click', () => Router.navigate('/overview')));
    _el.querySelector('[data-reload]')?.addEventListener('click', async () => { await _load(); _draw(); });
    _el.querySelector('[data-provider-select]')?.addEventListener('change', () => _drawProviderFields());
    _el.querySelector('[data-channel-type]')?.addEventListener('change', () => _drawChannelFields());
    _bindConditionalSelects(_el);
    _applyConditionalFields();
    _el.querySelector('[data-save-provider]')?.addEventListener('click', _saveProvider);
    _el.querySelector('[data-save-router]')?.addEventListener('click', _saveRouter);
    _el.querySelector('[data-save-channel]')?.addEventListener('click', _saveChannel);
    _el.querySelector('[data-save-memory]')?.addEventListener('click', _saveMemory);
    _el.querySelector('[data-save-image]')?.addEventListener('click', _saveImage);
  }

  function _drawProviderFields() {
    const providerId = _el.querySelector('[data-provider-select]')?.value;
    const spec = (_catalog.providers || []).find(p => p.providerId === providerId);
    const box = _el.querySelector('.setup-provider-fields');
    if (box && spec) box.innerHTML = _renderProviderFields(spec, _config.llm || {});
    _bindConditionalSelects(box || _el);
    _applyConditionalFields();
  }

  function _drawChannelFields() {
    const type = _el.querySelector('[data-channel-type]')?.value;
    _channelType = type;
    const spec = (_catalog.channels || []).find(c => c.type === type);
    const box = _el.querySelector('.setup-channel-fields');
    if (box && spec) box.innerHTML = _renderChannelFields(spec);
    _bindConditionalSelects(box || _el);
    _applyConditionalFields();
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

  async function _saveProvider() {
    const providerId = _el.querySelector('[data-provider-select]')?.value;
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
      _step = 'router';
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveRouter() {
    const tiers = {};
    _el.querySelectorAll('[data-tier]').forEach(row => {
      const tier = {};
      row.querySelectorAll('[data-tier-field]').forEach(input => {
        const key = input.dataset.tierField;
        tier[key] = input.type === 'checkbox' ? input.checked : input.value;
      });
      tiers[row.dataset.tier] = tier;
    });
    try {
      await _rpc.call('onboarding.router.configure', {
        mode: _el.querySelector('[data-router-mode]')?.value || 'recommended',
        defaultTier: _el.querySelector('[data-default-tier]')?.value || 't1',
        tiers,
      });
      UI.toast('Router saved.', 'info');
      await _load();
      _step = 'channels';
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveChannel() {
    const entry = Object.assign({ type: _el.querySelector('[data-channel-type]')?.value }, _readScopedFields('channel'));
    try {
      await _rpc.call('onboarding.channel.probe', { entry });
      await _rpc.call('onboarding.channel.upsert', { entry });
      UI.toast('Channel saved. Restart required.', 'info');
      await _loadChannelStatus();
      _draw();
    } catch (err) {
      UI.toast('Save failed: ' + err.message, 'err');
    }
  }

  async function _saveMemory() {
    const params = { providerId: _el.querySelector('[data-memory-provider]')?.value || 'auto' };
    _el.querySelectorAll('[data-memory-field]').forEach(input => {
      if (input.value !== '' || input.dataset.secret !== 'true') params[_camel(input.dataset.memoryField)] = input.value;
    });
    try {
      await _rpc.call('onboarding.memory_embedding.configure', params);
      UI.toast('Memory embedding saved. Restart required.', 'info');
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
      await _rpc.call('onboarding.imageGeneration.configure', params);
      UI.toast('Image generation saved.', 'info');
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
      await _loadChannelStatus();
      _draw();
    }, 5000);
  }

  function _camel(name) {
    return String(name || '').replace(/_([a-z])/g, (_, c) => c.toUpperCase());
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
  }

  return { render, destroy };
})();

window.SetupView = SetupView;
