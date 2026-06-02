"""Static-asset smoke tests for onboarding-aware WebUI views."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src/opensquilla/gateway"
VIEWS = ROOT / "static/js/views"
TEMPLATE = ROOT / "templates/index.html"
APP = ROOT / "static/js/app.js"


def test_channels_view_is_read_only_status_surface():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    assert "channels.status" in txt
    assert "onboarding.catalog" not in txt
    assert "onboarding.channel.upsert" not in txt
    assert "onboarding.channel.remove" not in txt
    assert "onboarding.channel.enable" not in txt
    assert "onboarding.channel.disable" not in txt
    assert "Add channel" not in txt
    assert "Save channel" not in txt
    assert "data-ch-remove" not in txt
    assert "data-ch-toggle" not in txt
    assert "data-ch-logout" not in txt
    assert "channels.logout" not in txt
    assert "channels.restart" not in txt


def test_channels_view_points_configuration_to_cli_onboarding():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    assert "opensquilla channels list" in txt
    assert "opensquilla onboard configure channels" in txt


def test_channels_stats_do_not_report_attention_states_as_healthy():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    assert "all healthy" not in txt
    assert "need attention" in txt
    assert "restarting" in txt
    assert "exhausted" in txt


def test_channels_view_filters_to_configured_channels():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    assert "configured !== false" in txt


def test_channels_load_stops_if_view_is_destroyed_while_waiting_for_rpc():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    start = txt.index("async function _loadData()")
    end = txt.index("  function _renderStats", start)
    body = txt[start:end]

    assert "const rpc = _rpc;" in body
    assert "await rpc.waitForConnection();" in body
    assert "if (!_el || _rpc !== rpc) return;" in body


def test_setup_view_loads_catalog_and_status():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "onboarding.catalog" in txt
    assert "onboarding.status" in txt
    assert "config.get" in txt
    assert "onboarding.provider.configure" in txt
    assert "onboarding.search.configure" in txt
    assert "onboarding.imageGeneration.configure" in txt
    assert "onboarding.audio.configure" in txt
    assert "imageGenerationProviders" in txt
    assert "audioProviders" in txt
    assert "onboarding.memory_embedding.configure" in txt
    assert "Fallback API key" in txt
    assert "data-memory-api-key-label" in txt
    assert "effectiveProvider" in txt
    assert "current.mode" in txt


def test_setup_view_is_available_and_uses_canonical_cli_fallbacks():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "SETUP_UI_AVAILABLE" not in txt
    assert "opensquilla onboard" in txt
    assert "opensquilla onboard catalog providers" in txt
    assert "opensquilla providers configure" not in txt
    assert "onboarding.router.configure" in txt
    assert "onboarding.channel.probe" in txt
    assert "channels.status" in txt
    assert "Connected" in txt


def test_setup_view_locks_image_model_image_support():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "const isImageModel = name === 'image_model';" in txt
    assert "isImageModel ? ' checked disabled' :" in txt
    assert "tier.supportsImage = true;" in txt
    assert "tier.image_only = true;" in txt


def test_setup_finish_cli_commands_target_active_config_path():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderFinishStep()")
    end = txt.index("  function _renderReadinessSummary", start)
    body = txt[start:end]

    assert "const configArg = _configCliArg(_status.configPath)" in body
    assert "function _configCliArg" in txt
    assert "function _shellArg" in txt
    assert "Guided CLI" in body
    assert "`opensquilla onboard --if-needed${configArg}`" in body
    assert "Check status" in body
    assert "`opensquilla onboard status${configArg}`" in body
    assert "Provider options" in body
    assert "`opensquilla onboard catalog providers${configArg}`" in body
    assert "Router tiers" in body
    assert "`opensquilla onboard catalog router${configArg}`" in body
    assert "Search options" in body
    assert "`opensquilla onboard catalog search${configArg}`" in body
    assert "Channel options" in body
    assert "`opensquilla onboard catalog channels${configArg}`" in body
    assert "Image options" in body
    assert "`opensquilla onboard catalog image${configArg}`" in body
    assert "Memory options" in body
    assert "`opensquilla onboard catalog memory${configArg}`" in body
    assert "Catalog overview" not in body
    assert "`opensquilla onboard catalog${configArg}`" not in body
    assert "Channel field guide" not in body
    assert "opensquilla channels describe <type>" not in body
    assert "<type>" not in body
    assert "const envRecoveryCommands = Array.isArray(_status.envRecoveryCommands)" in body
    assert "const fixCommands = _envFixCommands(envRecoveryCommands, configArg)" in body
    assert "const handoffCommands = [" in body
    assert "const recipeCommands = [" in body
    assert "_renderCliCommandGroup('Fix now', fixCommands)" in body
    assert "_renderCliCommandGroup('CLI handoff', handoffCommands)" in body
    assert "_renderCliCommandGroup('CLI recipes', recipeCommands)" in body


def test_setup_finish_groups_recovery_commands_before_cli_reference():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")
    start = txt.index("function _renderFinishStep()")
    end = txt.index("  function _renderCliCommand", start)
    body = txt[start:end]

    assert "const fixCommands = _envFixCommands(envRecoveryCommands, configArg)" in body
    assert "const handoffCommands = [" in body
    assert "const recipeCommands = [" in body
    assert "Fix now" in body
    assert "CLI handoff" in body
    assert "CLI recipes" in body
    assert (
        "_renderCliCommandGroup('Fix now', fixCommands)"
        in body
    )
    assert (
        "_renderCliCommandGroup('CLI handoff', handoffCommands)"
        in body
    )
    assert (
        "_renderCliCommandGroup('CLI recipes', recipeCommands)"
        in body
    )
    assert body.index("_renderCliCommandGroup('Fix now'") < body.index(
        "_renderCliCommandGroup('CLI handoff'"
    )
    assert body.index("_renderCliCommandGroup('CLI handoff'") < body.index(
        "_renderCliCommandGroup('CLI recipes'"
    )
    assert "function _renderCliCommandGroup" in txt
    assert "setup-cli__group" in txt
    assert ".setup-cli__group" in css
    assert ".setup-cli__group-head" in css


def test_setup_finish_prioritizes_cli_actions_before_configuration_details():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderFinishStep()")
    end = txt.index("  function _renderCliCommand", start)
    body = txt[start:end]

    assert body.index('<div class="setup-cli">') < body.index('<div class="setup-summary">')
    assert body.index('<div class="setup-cli">') < body.index("_renderReadinessSummary()")


def test_setup_finish_pairs_env_recovery_with_gateway_restart_command():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderFinishStep()")
    end = txt.index("  function _renderReadinessSummary", start)
    body = txt[start:end]

    assert "const fixCommands = _envFixCommands(envRecoveryCommands, configArg)" in body
    assert "function _envFixCommands" in txt
    assert "if (!envRecoveryCommands.length) return [];" in txt
    assert "label: 'Restart gateway after env fix'" in txt
    assert "command: `opensquilla gateway restart${configArg}`" in txt
    assert body.index("const envRecoveryCommands = Array.isArray") < body.index(
        "const fixCommands = _envFixCommands(envRecoveryCommands, configArg)"
    )


def test_setup_finish_cli_commands_are_provider_neutral():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderFinishStep()")
    end = txt.index("  function _renderReadinessSummary", start)
    body = txt[start:end]

    assert "opensquilla onboard catalog providers" in body
    assert "opensquilla onboard catalog search" in body
    assert "opensquilla onboard catalog image" in body
    assert "opensquilla onboard catalog memory" in body
    assert "--search-provider <provider>" not in body
    assert "--image-provider <provider>" not in body
    assert "--memory-provider <provider>" not in body
    assert "--api-key-env <ENV_NAME>" not in body
    assert "--search-provider brave" not in body
    assert "--image-provider openrouter" not in body
    assert "--memory-provider openai" not in body
    assert "OPENAI_API_KEY" not in body
    assert "BRAVE_SEARCH_API_KEY" not in body


def test_setup_view_starts_on_most_relevant_step():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    render_start = txt.index("async function render(el)")
    render_end = txt.index("  async function _load()", render_start)
    render_body = txt[render_start:render_end]
    destroy_start = txt.index("function destroy()")
    destroy_body = txt[destroy_start:]

    assert "let _hasAutoSelectedStep = false" in txt
    assert "function _selectInitialStep()" in txt
    assert "function _initialStepFromStatus()" in txt
    assert "await _load();\n    _selectInitialStep();" in render_body
    assert render_body.index("await _load();") < render_body.index("_selectInitialStep();")
    assert txt.index("const entry = sectionSteps.find") < txt.index(
        "if (_status.needsOnboarding === false) return 'finish';"
    )
    assert "if (_status.needsOnboarding === false) return 'finish';" in txt
    assert "detail.actionRequired" in txt
    assert "['llm', 'provider']" in txt
    assert "['router', 'router']" in txt
    assert "['search', 'extras']" in txt
    assert "['image_generation', 'extras']" in txt
    assert "['audio', 'extras']" in txt
    assert "['memory_embedding', 'extras']" in txt
    assert "_step = 'provider';" in destroy_body
    assert "_hasAutoSelectedStep = false;" in destroy_body


def test_setup_header_tracks_optional_action_required_sections():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    draw_start = txt.index("function _draw()")
    draw_end = txt.index("  function _renderOnboardingReasons()", draw_start)
    draw_body = txt[draw_start:draw_end]
    reasons_start = txt.index("function _onboardingReasons()")
    reasons_end = txt.index("  function _renderCurrentStep()", reasons_start)
    reasons_body = txt[reasons_start:reasons_end]

    assert "function _hasSetupAction()" in txt
    assert "const setupAction = _hasSetupAction();" in draw_body
    assert "${setupAction ? 'Action needed' : 'Ready to run'}" in draw_body
    assert "setup__status ${setupAction ? 'is-warn' : 'is-ok'}" in draw_body
    assert "${setupAction ? 'Action needed' : 'Ready'}" in draw_body
    assert "if (!_hasSetupAction()) return [];" in reasons_body
    assert "if (!detail.blocking && !detail.actionRequired)" in reasons_body


def test_setup_finish_summarizes_provider_proxy_only_when_present():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderFinishStep()")
    end = txt.index("  function _renderReadinessSummary", start)
    body = txt[start:end]

    assert (
        "const providerProxy = configuredProvider "
        "? ((_config.llm || {}).proxy || '').trim() : ''"
    ) in body
    assert "providerProxy ?" in body
    assert "<span>Proxy</span>" in body


def test_setup_finish_cli_commands_are_copyable():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")

    assert "function _renderCliCommand" in txt
    assert "const copyLabel = `Copy ${label} command`" in txt
    assert "data-setup-copy-command" in txt
    assert 'title="${_esc(copyLabel)}"' in txt
    assert 'aria-label="${_esc(copyLabel)}"' in txt
    assert 'title="Copy command"' not in txt
    assert 'aria-label="Copy command"' not in txt
    assert "navigator.clipboard.writeText" in txt
    assert "Copied command" in txt
    assert "setup-cli__copy" in txt
    assert "setup-cli__label" in txt
    assert "${icons.copy()}" in txt
    assert ".setup-cli__copy" in css
    assert ".setup-cli__label" in css


def test_setup_finish_cli_commands_stack_labels_on_mobile():
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 560px)", 1)[1]

    assert ".setup-cli__row" in mobile
    assert "grid-template-columns: minmax(0, 1fr) 34px" in mobile
    assert ".setup-cli__label" in mobile
    assert "grid-column: 1 / -1" in mobile


def test_setup_view_keeps_channel_fields_in_config_shape():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "scope === 'channel' ? label.dataset.name : _camel" in txt


def test_setup_view_renders_catalog_field_descriptions():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "field.description" in txt
    assert "setup-field-desc" in txt


def test_setup_view_surfaces_catalog_requirements_before_fields():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "function _renderNeedList" in txt
    assert "setup-need-list" in txt
    assert "spec.whatYouNeed" in txt
    assert "searchSpec.whatYouNeed" in txt
    assert "_memoryNeedList(memorySpec" in txt
    assert "imageSpec.whatYouNeed" in txt
    assert "channelSpec.whatYouNeed" in txt


def test_setup_view_ties_need_lists_to_selected_env_keys():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "function _credentialNeedList" in txt
    assert "_credentialNeedList(searchSpec.whatYouNeed, searchEnv || searchSpec.envKey)" in txt
    assert "_credentialNeedList(imageSpec.whatYouNeed, imageEnv || imageSpec.envKey)" in txt
    assert "envInput.value = spec.requiresApiKey ? (spec.envKey || '') : ''" in txt
    assert "_credentialNeedList(spec.whatYouNeed, envInput?.value || spec.envKey)" in txt


def test_setup_provider_step_is_neutral_before_provider_choice():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")
    start = txt.index("function _renderProviderStep()")
    end = txt.index("  function _providerConfigFor", start)
    body = txt[start:end]
    sync_start = txt.index("function _drawProviderFields")
    sync_end = txt.index("  function _drawChannelFields", sync_start)
    sync_body = txt[sync_start:sync_end]
    save_start = txt.index("async function _saveProvider()")
    save_end = txt.index("  async function _saveRouter()", save_start)
    save_body = txt[save_start:save_end]

    assert "const selected = _effectiveProvider();" in body
    assert "Choose from ${providers.length} supported providers" in body
    assert (
        '<option value="" disabled${selected ? \'\' : \' selected\'}>'
        "Choose a provider</option>"
    ) in body
    assert "const spec = selected ? providers.find" in body
    assert "selected ? spec.whatYouNeed : ['Choose a provider to see required fields.']" in body
    assert "data-save-provider${selected ? '' : ' disabled'}" in body
    assert 'data-next="router"${selected ? \'\' : \' disabled\'}' in body
    assert "saveButton.disabled = !providerId" in sync_body
    assert 'const nextButton = _el.querySelector(\'[data-next="router"]\')' in sync_body
    assert "if (nextButton) nextButton.disabled = !providerId" in sync_body
    assert "if (!providerId)" in save_body
    assert "Choose a provider before saving." in save_body
    assert ".setup-btn:disabled" in css
    assert "cursor: not-allowed" in css


def test_setup_view_declutters_memory_auto_requirements():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "function _memoryNeedList" in txt
    assert "_memoryNeedList(memorySpec, effectiveProvider, memoryEnv)" in txt
    assert "!/remote fallback credentials/i.test(item)" in txt


def test_setup_view_collapses_search_advanced_options_by_default():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "const searchAdvancedOpen" in txt
    assert 'details class="setup-mini__advanced" data-search-advanced${searchAdvancedOpen}' in txt
    assert "<summary>Advanced search options</summary>" in txt
    assert "setup-mini__advanced-body" in txt
    assert "searchFallbackPolicy !== 'off'" in txt
    assert "setup_search_proxy" in txt


def test_setup_view_collapses_provider_connection_options_by_default():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "const providerCoreFields" in txt
    assert "const providerAdvancedFields" in txt
    assert "const providerAdvancedOpen" in txt
    assert "_isProviderAdvancedField(field, spec)" in txt
    assert (
        "_renderProviderAdvancedFields(providerAdvancedFields, values, providerAdvancedOpen)"
        in txt
    )
    assert 'details class="setup-mini__advanced" data-provider-advanced${openAttr}' in txt
    assert "<summary>Advanced provider connection</summary>" in txt
    assert "setup-provider-fields" in txt
    assert "Provider connection" in txt
    assert "base_url" in txt
    assert "proxy" in txt


def test_setup_provider_advanced_opens_for_required_or_custom_connection():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "function _providerAdvancedOpen" in txt
    assert "if (field.required) return true;" in txt
    assert "value !== defaultValue" in txt
    assert "return value.length > 0;" in txt


def test_setup_view_moves_optional_router_model_into_provider_advanced_connection():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "_isProviderAdvancedField(field, spec)" in txt
    assert "field.name === 'model'" in txt
    assert "spec.routerSupported === true" in txt
    assert "field.required !== true" in txt
    assert (
        "providerCoreFields = providerFields.filter(field => "
        "!_isProviderAdvancedField(field, spec))"
    ) in txt
    assert (
        "providerAdvancedFields = providerFields.filter(field => "
        "_isProviderAdvancedField(field, spec))"
    ) in txt
    assert "if (defaultValue) return value !== defaultValue;" in txt


def test_setup_view_keeps_required_provider_model_in_core_fields():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    model_start = txt.index("if (field.name === 'model')")
    model_clause = txt[model_start : txt.index("return false;", model_start)]
    assert "field.required !== true" in model_clause
    assert "spec.routerSupported === true" in model_clause


def test_setup_provider_switch_redraws_core_and_advanced_fields_together():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    start = txt.index("function _drawProviderFields")
    body = txt[start : txt.index("  function _drawChannelFields", start)]
    assert "const providerFields = spec.fields || []" in body
    assert "const providerCoreFields" in body
    assert "const providerAdvancedFields" in body
    assert "box.innerHTML = _renderProviderFields(providerCoreFields" in body
    assert "advanced.innerHTML = _renderProviderAdvancedFields(" in body
    assert "_renderProviderFields(spec," not in body


def test_setup_view_warns_when_env_key_is_not_visible_to_gateway():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")

    assert "missing_env" in txt
    assert "not visible to this gateway process" in txt
    assert "Set it before starting or restarting the gateway" in txt
    assert "if (_providerEnvMissing())" in txt
    assert "function _providerEnvRecoveryCommand()" in txt
    assert "Array.isArray(_status.envRecoveryCommands)" in txt
    assert "return _envRecoveryCommand('llm')" in txt
    assert "_providerEnvRecoveryCommand()" in txt
    assert "setup-warning__command" in txt
    assert 'data-setup-copy-command="${safeCommand}"' in txt
    assert "Copy set provider key command" in txt
    assert ".setup-warning__command" in css
    assert ".setup-warning__command code" in css


def test_setup_view_does_not_default_env_key_over_stored_provider_key():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "current.api_key ? '' : field.default" in txt


def test_setup_provider_form_can_submit_api_key_env():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "api_key_env" in txt
    assert "_camel(label.dataset.name)" in txt
    assert "onboarding.provider.configure" in txt


def test_setup_provider_controls_have_browser_field_names():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert 'name="setup_provider"' in txt
    assert "const fieldName = `setup_${scope}_${rawName}`" in txt
    assert 'for="${_esc(fieldId)}"' in txt
    assert 'id="${_esc(fieldId)}"' in txt
    assert 'name="${_esc(fieldName)}"' in txt


def test_setup_provider_switch_refreshes_provider_defaults():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "function _providerConfigFor(providerId)" in txt
    assert "current.provider === providerId ? current : {}" in txt
    assert 'data-provider-summary' in txt
    assert "_drawProviderFields({ rememberDraft: true })" in txt


def test_setup_all_wizard_controls_have_browser_field_names():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    for name in (
        "setup_router_mode",
        "setup_router_default_tier",
        "setup_channel_type",
        "setup_search_provider",
        "setup_search_max_results",
        "setup_search_api_key",
        "setup_search_api_key_env",
        "setup_search_proxy",
        "setup_search_use_env_proxy",
        "setup_search_fallback_policy",
        "setup_search_diagnostics",
        "setup_memory_provider",
        "setup_memory_model",
        "setup_memory_api_key",
        "setup_memory_api_key_env",
        "setup_memory_base_url",
        "setup_memory_onnx_dir",
        "setup_image_provider",
        "setup_image_primary",
        "setup_image_api_key",
        "setup_image_api_key_env",
        "setup_image_base_url",
        "setup_image_enabled",
    ):
        assert f'name="{name}"' in txt

    assert "const tierFieldName = `setup_router_${name}_${field}`" in txt
    assert 'name="${_esc(tierFieldName)}"' in txt
    assert 'aria-label="${_esc(tierLabel)}' in txt


def test_setup_view_bounds_search_max_results_control():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index('id="setup-search-max-results"')
    end = txt.index('data-search-field="max_results"', start)
    control = txt[start:end]

    assert 'type="number"' in control
    assert 'min="1"' in control
    assert 'step="1"' in control
    assert 'inputmode="numeric"' in control


def test_setup_view_preserves_selected_channel_type_while_redrawing_fields():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "let _channelType" in txt
    assert "_channelType = type" in txt
    assert "channels.some(c => c.type === _channelType)" in txt


def test_setup_view_rebinds_conditional_fields_after_dynamic_redraw():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "function _bindConditionalSelects" in txt
    assert "_bindConditionalSelects(_el)" in txt
    assert "_bindConditionalSelects(box || _el)" in txt


def test_setup_view_is_loaded_and_registered_but_not_sidebar_primary():
    template = TEMPLATE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert "static/js/views/setup.js" in template
    assert "_renderStandardView(SetupView, el)" in app
    assert "Router.register('/setup'" in app
    assert 'data-path="/setup"' not in app


def test_setup_view_marks_unsupported_providers_disabled():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "runtimeSupported" in txt


def test_setup_view_validates_visible_required_channel_fields_before_save():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _saveChannel()")
    end = txt.index("  async function _saveMemory()", start)
    body = txt[start:end]

    assert 'data-required="${field.required ? \'true\' : \'false\'}"' in txt
    assert "function _validateScopedRequiredFields(scope)" in txt
    assert "function _canKeepExistingSecret(scope)" in txt
    assert "input.dataset.secret === 'true' && _canKeepExistingSecret(scope)" in txt
    assert "row.configured !== false" in txt
    assert "String(row.type || '') === String(type)" in txt
    assert "String(row.name || '') === String(name).trim()" in txt
    assert "_validateScopedRequiredFields('channel')" in body
    assert "if (missing)" in body
    assert "is required." in body
    assert "return;" in body


def test_setup_view_treats_image_configure_as_capability_enable_action():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "field.default !== false" in txt
    assert "imageGenerationEnabled === false" in txt


def test_setup_view_explains_image_generation_tool_visibility():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _imageGenerationStatusText")
    end = txt.index("  function _memoryEmbeddingStatusText", start)
    body = txt[start:end]

    assert "Image generation is hidden from agents" in body
    assert "Image generation will be available in new turns" in body
    assert "_status.imageGenerationSource === 'missing_env'" in body
    assert "_status.imageGenerationEnvKey" in body
    assert "image_generate" not in body
    assert "imageGenerationSource === 'llm_fallback'" in txt
    assert "same provider key" in txt


def test_setup_view_uses_product_language_for_search_status_text():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _searchStatusText")
    end = txt.index("  function _imageGenerationStatusText", start)
    body = txt[start:end]

    assert "Web search is off until a provider is selected." in body
    assert "Web search is ready for new turns." in body
    assert "_status.searchSource === 'missing_env'" in body
    assert "_status.searchEnvKey" in body
    assert "Web search is selected but still needs a visible provider key." in body
    assert "web_search" not in body


def test_setup_view_names_missing_env_key_for_memory_embedding_status_text():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _memoryEmbeddingStatusText")
    end = txt.index("  function _toastEnvReferenceSave", start)
    body = txt[start:end]

    assert "_status.memoryEmbeddingSource === 'missing_env'" in body
    assert "_status.memoryEmbeddingEnvKey" in body
    assert "Remote memory embeddings need a visible provider key before they can run." in body


def test_setup_capability_cards_offer_copyable_env_recovery_commands():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderExtrasStep()")
    end = txt.index("  function _capabilitySaveButtonClass", start)
    body = txt[start:end]

    assert "function _capabilityEnvRecoveryCommand(section)" in txt
    assert "function _renderCapabilityEnvRecoveryCommand(section)" in txt
    assert "Array.isArray(_status.envRecoveryCommands)" in txt
    assert "entry.section === section" in txt
    assert "_renderCapabilityEnvRecoveryCommand('search')" in body
    assert "_renderCapabilityEnvRecoveryCommand('memory_embedding')" in body
    assert "_renderCapabilityEnvRecoveryCommand('image_generation')" in body
    assert "_renderCapabilityEnvRecoveryCommand('audio')" in body
    assert "Copy set search key command" in txt
    assert "Copy set memory key command" in txt
    assert "Copy set image key command" in txt
    assert "Copy set audio key command" in txt
    assert 'data-setup-copy-command="${safeCommand}"' in txt


def test_setup_view_exposes_image_generation_env_key_config():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "imageProviders.find(p => p.providerId === imageProviderSelected)" in txt
    assert "imageProviderConfig.api_key_env" in txt
    assert 'data-image-field="api_key_env"' in txt
    assert "setup_image_api_key_env" in txt
    assert "imageSpec.envKey" in txt
    assert "_syncImageProviderDefaults" in txt
    assert "[data-image-provider]')?.addEventListener('change', _syncImageProviderDefaults)" in txt
    assert "primaryInput.value = spec.defaultModel || primaryInput.value" in txt


def test_setup_view_exposes_audio_provider_config():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "audioProviders.find(p => p.providerId === audioProviderSelected)" in txt
    assert "audioProviderConfig.api_key_env" in txt
    assert 'data-audio-field="api_key_env"' in txt
    assert 'data-audio-field="tts_voice"' in txt
    assert 'data-audio-field="tts_model"' in txt
    assert 'data-audio-field="language_code"' in txt
    assert "setup_audio_api_key_env" in txt
    assert "audioSpec.envKey" in txt
    assert "_syncAudioProviderDefaults" in txt
    assert "[data-audio-provider]')?.addEventListener('change', _syncAudioProviderDefaults)" in txt
    assert "const res = await _rpc.call('onboarding.audio.configure', params)" in txt


def test_setup_image_generation_hides_provider_fields_until_enabled():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderExtrasStep()")
    end = txt.index("  function _capabilitySaveButtonClass", start)
    body = txt[start:end]

    assert "const imageConfigHidden = imageEnabledDefault ? '' : ' hidden'" in body
    assert 'data-image-config-fields${imageConfigHidden}' in body
    assert "[data-image-enabled]')?.addEventListener('change', _syncImageProviderDefaults)" in txt

    sync_start = txt.index("function _syncImageProviderDefaults()")
    sync_end = txt.index("  function _bindConditionalSelects", sync_start)
    sync_body = txt[sync_start:sync_end]
    assert "const enabledInput = _el.querySelector('[data-image-enabled]')" in sync_body
    assert "const imageConfigFields = _el.querySelector('[data-image-config-fields]')" in sync_body
    assert "imageConfigFields.hidden = !imageEnabled" in sync_body


def test_setup_view_exposes_image_generation_base_url_config():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "imageProviderConfig.base_url" in txt
    assert "imageSpec.defaultBaseUrl" in txt
    assert 'data-image-field="base_url"' in txt
    assert "setup_image_base_url" in txt
    assert "baseInput.value = spec.defaultBaseUrl || baseInput.value" in txt


def test_setup_view_preserves_selected_image_generation_provider():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "imageProviderSelected" in txt
    assert "imageGenerationProvider" in txt
    assert "imageGenerationPrimary || '').split('/')[0]" in txt


def test_setup_router_controls_use_user_facing_labels():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "SquillaRouter" in txt
    assert "OpenRouter mix" not in txt
    assert "Route c1" in txt
    assert "Route c2" in txt


def test_setup_view_preserves_unsaved_form_values_across_step_navigation():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "const _drafts" in txt
    assert "function _rememberDraft" in txt
    assert "function _restoreDraft" in txt
    assert "function _setStep" in txt
    assert "data-next" in txt
    assert "_setStep(btn.dataset.next)" in txt


def test_setup_view_reconciles_search_key_state_after_restoring_draft_provider():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _restoreDynamicDraftFields()")
    end = txt.index("  function _fieldKey", start)
    body = txt[start:end]

    assert "function _syncSearchProviderKeyControls" in txt
    assert "if (_step === 'extras' && _drafts.has('extras'))" in body
    assert "_syncSearchProviderKeyControls({ refreshEnv: false })" in body


def test_setup_view_does_not_redraw_dirty_channel_form_during_status_poll():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "let _channelDirty" in txt
    assert "data-channel-dirty-root" in txt
    assert "if (_channelDirty) return;" in txt


def test_setup_view_surfaces_action_needed_reasons():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "function _onboardingReasons" in txt
    assert "setup-reasons" in txt
    assert "Connect a model provider" in txt
    assert "detail.status === 'missing'" in txt
    assert "Provider action required" not in txt
    assert "sectionDetails" in txt
    assert "detail.blocking" in txt
    assert "(_status.channelCount || 0) === 0" not in txt


def test_setup_stepper_surfaces_readiness_for_each_setup_area():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")
    draw_start = txt.index("function _draw()")
    draw_end = txt.index("  function _renderOnboardingReasons()", draw_start)
    draw_body = txt[draw_start:draw_end]

    assert "STEPS.map(_renderStepButton).join('')" in draw_body
    assert "function _renderStepButton" in txt
    assert "function _stepStatus" in txt
    assert "function _aggregateStepStatus" in txt
    assert "setup-stepper__state" in txt
    assert "setup-stepper__label" in txt
    assert "setup-stepper__num" in txt
    assert (
        "_aggregateStepStatus(['search', 'image_generation', 'audio', "
        "'memory_embedding'])"
    ) in txt
    assert "detail.blocking || detail.actionRequired" in txt
    assert "detail.status === 'missing' || detail.status === 'degraded'" in txt
    assert "aria-label=\"${_esc(`${s.label}: ${status.label}`)}\"" in txt
    assert ".setup-stepper__state" in css
    assert ".setup-stepper__state.is-ok" in css
    assert ".setup-stepper__state.is-warn" in css
    assert ".setup-stepper__label" in css


def test_setup_stepper_names_router_provider_prerequisite():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _stepStatus")
    body = txt[start : txt.index("  function _aggregateStepStatus", start)]

    assert "if (stepId === 'router' && !_effectiveProvider())" in body
    assert "Provider first" in body


def test_setup_header_reasons_name_missing_env_keys_for_capabilities():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _onboardingReasons()")
    end = txt.index("  function _hasSetupAction()", start)
    body = txt[start:end]

    assert "function _setupActionReason" in txt
    assert "const missingEnvPrefix = 'env key not visible: '" in txt
    assert "return `${envKey} is not visible`" in txt
    assert "_setupActionReason(name, detail)" in body
    assert "Memory embedding setup needed" not in body


def test_setup_provider_first_run_summary_does_not_headline_default_provider():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderProviderStep()")
    end = txt.index("  function _providerConfigFor", start)
    body = txt[start:end]

    assert "const selected = _effectiveProvider();" in body
    assert (
        "const providerSummary = selected\n"
        "      ? (spec.label || selected)\n"
        "      : `Choose from ${providers.length} supported providers`"
    ) in body
    assert '<p data-provider-summary>${_esc(providerSummary)}</p>' in body
    assert '<p data-provider-summary>${_esc(selected || \'not configured\')}</p>' not in body


def test_setup_provider_step_surfaces_squillarouter_tier_support():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderProviderStep()")
    end = txt.index("  function _providerConfigFor", start)
    body = txt[start:end]
    sync_start = txt.index("function _drawProviderFields")
    sync_end = txt.index("  function _drawChannelFields", sync_start)
    sync_body = txt[sync_start:sync_end]

    assert "function _providerRouterSupportText" in txt
    assert "function _providerRouterSupportTone" in txt
    assert "spec.routerSupported === true" in txt
    assert "'SquillaRouter ready'" in txt
    assert "'Direct only'" in txt
    assert "'available'" not in body
    assert "'direct model only'" not in body
    assert "data-provider-router-support" in body
    assert "data-provider-router-support-label" in body
    assert "setup-provider-meta__badge" in body
    assert "SquillaRouter tiers" in body
    assert "_providerRouterSupportText(selected ? spec : null)" in body
    assert "_providerRouterSupportTone(selected ? spec : null)" in body
    assert "routerSupport.textContent = _providerRouterSupportText(spec);" in sync_body
    assert "routerSupport.className = `setup-provider-meta__badge" in sync_body
    assert "_providerRouterSupportTone(spec)" in sync_body


def test_setup_provider_router_support_badge_has_distinct_tones():
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")

    assert ".setup-provider-meta__badge" in css
    assert ".setup-provider-meta__badge.is-ready" in css
    assert ".setup-provider-meta__badge.is-direct" in css
    assert ".setup-provider-meta__badge.is-neutral" in css


def test_setup_provider_switch_summary_uses_provider_label():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _drawProviderFields")
    end = txt.index("  function _drawChannelFields", start)
    body = txt[start:end]

    assert "summary.textContent = spec.label || providerId || 'not configured';" in body


def test_setup_router_step_uses_effective_provider_without_hardcoded_fallback():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderRouterStep()")
    end = txt.index("  function _tierRow", start)
    body = txt[start:end]

    assert "const provider = _effectiveProvider();" in body
    assert "const canSaveRouter = provider && provider === _configuredProvider();" in body
    assert "const routerSummary = provider" in body
    assert "'Choose a provider first'" in body
    assert "profiles.find(p => p.profileId === 'openrouter')" not in body
    assert "const tiers = provider ?" in body
    assert "data-router-provider-needed" in body
    assert "data-router-provider-unsaved" in body
    assert "data-save-router${saveDisabled}" in body

    save_start = txt.index("async function _saveRouter()")
    save_end = txt.index("  async function _saveChannel()", save_start)
    save_body = txt[save_start:save_end]
    assert "const provider = _effectiveProvider();" in save_body
    assert "const configuredProvider = _configuredProvider();" in save_body
    assert "Choose a provider before saving router tiers." in save_body
    assert "Save the provider before saving router tiers." in save_body


def test_setup_effective_provider_accepts_runtime_config_but_not_bare_defaults():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _configuredProvider()")
    end = txt.index("  function _renderProviderFields", start)
    body = txt[start:end]

    assert "if (_status.hasConfig !== false) return provider;" in body
    assert "if (_status.llmConfigured === true) return provider;" in body
    assert "['explicit', 'env', 'not_required'].includes(_status.llmSource)" in body
    assert "providerDraft['provider:selected']" in body
    assert "return (includeDraft ? _draftProvider() : '') || _configuredProvider();" in body


def test_setup_view_exposes_search_in_capability_center():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "Capability Center" in txt
    assert "label: 'Capabilities'" in txt
    assert "label: 'Extras'" not in txt
    assert "function _renderCapabilityBadge" in txt
    assert "setup-badge" in txt
    assert "data-search-provider" in txt
    assert "data-save-search" in txt
    assert "_syncSearchProviderEnvHint" in txt


def test_setup_capability_center_names_each_capability_action():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderExtrasStep()")
    end = txt.index("  function _capabilitySaveButtonClass", start)
    body = txt[start:end]

    assert "Web search · Memory recall · Image generation" in body
    assert "search / memory / image" not in body
    assert "Save web search" in body
    assert "Save memory embedding" in body
    assert "Save image generation" in body
    assert "Save Memory" not in body
    assert "Save Image" not in body


def test_setup_capability_save_buttons_prioritize_action_required_card():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "function _capabilitySaveButtonClass" in txt
    start = txt.index("function _capabilitySaveButtonClass")
    end = txt.index("  function _renderCapabilityBadge", start)
    body = txt[start:end]

    assert "detail.blocking || detail.actionRequired" in body
    assert "'setup-btn setup-btn--primary'" in body
    assert "'setup-btn'" in body
    assert 'class="${_capabilitySaveButtonClass(\'search\')}"' in txt
    assert 'class="${_capabilitySaveButtonClass(\'memory_embedding\')}"' in txt
    assert 'class="${_capabilitySaveButtonClass(\'image_generation\')}"' in txt


def test_setup_view_exposes_all_search_configuration_controls():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    for name in (
        "setup_search_proxy",
        "setup_search_use_env_proxy",
        "setup_search_fallback_policy",
        "setup_search_diagnostics",
    ):
        assert f'name="{name}"' in txt

    assert "_config.search_proxy" in txt
    assert "_config.search_use_env_proxy" in txt
    assert "_config.search_fallback_policy" in txt
    assert "_config.search_diagnostics" in txt
    assert 'data-search-field="proxy"' in txt
    assert 'data-search-field="use_env_proxy"' in txt
    assert 'data-search-field="fallback_policy"' in txt
    assert 'data-search-field="diagnostics"' in txt


def test_setup_view_treats_search_provider_keys_as_conditional():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "searchSpec.requiresApiKey === true" in txt
    assert "searchRequiresKey ? '' : ' disabled'" in txt
    assert "not required for this provider" in txt
    assert "const searchKeyHidden = searchRequiresKey ? '' : ' hidden'" in txt
    assert 'data-search-key-fields${searchKeyHidden}' in txt
    assert "keyInput.disabled = !requiresKey" in txt
    assert "envInput.disabled = !requiresKey" in txt
    assert "keyFields.hidden = !requiresKey" in txt


def test_setup_view_treats_memory_remote_fields_as_provider_conditional():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "memorySpec.requiresApiKey === true" in txt
    assert "memoryApiKeyEnabled" in txt
    assert "memoryRemoteControlEnabled" in txt
    assert "function _syncMemoryProviderControls" in txt
    assert (
        "[data-memory-provider]')?.addEventListener('change', "
        "_syncMemoryProviderControls)"
    ) in txt
    assert "apiKeyInput.disabled = !apiKeyEnabled" in txt
    assert "envInput.disabled = !apiKeyEnabled" in txt
    assert "baseInput.disabled = !remoteControlEnabled" in txt
    assert "modelInput.disabled = !remoteControlEnabled" in txt
    assert "remoteOptions.hidden = !hasRemoteOptions" in txt
    assert "remoteOptions.open = providerId !== 'auto' && hasRemoteOptions" in txt
    assert 'data-memory-field="api_key_env"' in txt


def test_setup_memory_embedding_exposes_local_onnx_dir_without_cluttering_auto():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderExtrasStep()")
    end = txt.index("  function _capabilitySaveButtonClass", start)
    body = txt[start:end]

    assert "const memoryLocal = current.local || {}" in body
    assert "const memoryLocalControlEnabled = effectiveProvider === 'local'" in body
    assert "const memoryRemoteOptionsSummary" in body
    assert "Remote fallback options" in body
    assert "Connection options" in body
    assert (
        "data-memory-remote-options"
        "${memoryRemoteOptionsOpen}${memoryRemoteOptionsHidden}"
    ) in body
    assert 'data-memory-local-field${memoryLocalHidden}' in body
    assert 'name="setup_memory_onnx_dir"' in body
    assert 'data-memory-field="onnx_dir"' in body
    assert "memoryLocal.onnx_dir || ''" in body


def test_setup_view_surfaces_env_reference_save_feedback():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    memory_start = txt.index("async function _saveMemory()")
    memory_end = txt.index("  async function _saveSearch()", memory_start)
    memory_body = txt[memory_start:memory_end]
    image_start = txt.index("async function _saveImage()")
    image_end = txt.index("  async function _saveAudio()", image_start)
    image_body = txt[image_start:image_end]
    audio_start = txt.index("async function _saveAudio()")
    audio_end = txt.index("  async function _loadChannelStatus()", audio_start)
    audio_body = txt[audio_start:audio_end]

    assert "function _toastEnvReferenceSave" in txt
    assert (
        "const res = await _rpc.call('onboarding.memory_embedding.configure', params)"
        in memory_body
    )
    assert "_toastEnvReferenceSave(" in memory_body
    assert "'Memory embedding'" in memory_body
    assert "remote.api_key_env" in memory_body
    assert "restartRequired" in memory_body
    assert (
        "const res = await _rpc.call('onboarding.imageGeneration.configure', params)"
        in image_body
    )
    assert "_toastEnvReferenceSave(" in image_body
    assert "'Image generation'" in image_body
    assert "entry.api_key_source" in image_body
    assert (
        "const res = await _rpc.call('onboarding.audio.configure', params)"
        in audio_body
    )
    assert "_toastEnvReferenceSave(" in audio_body
    assert "'Voice audio'" in audio_body
    assert "entry.api_key_source" in audio_body


def test_setup_view_explains_memory_embedding_provider_modes():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "function _memoryEmbeddingStatusText" in txt
    assert 'data-memory-status-text' in txt
    assert "Local-first memory search" in txt
    assert "Uses local BGE embeddings" in txt
    assert "Uses your Ollama server" in txt
    assert "Keyword search stays available; embeddings are disabled." in txt
    assert "savedProvider" in txt
    assert "provider === savedProvider" in txt
    assert "statusText.textContent = _memoryEmbeddingStatusText(providerId)" in txt


def test_setup_view_does_not_submit_disabled_memory_fields():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("async function _saveMemory()")
    end = txt.index("  async function _saveSearch()", start)
    body = txt[start:end]

    assert "if (input.disabled) return;" in body


def test_setup_view_saves_search_checkboxes_as_booleans():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("async function _saveSearch()")
    end = txt.index("  async function _saveImage()", start)
    body = txt[start:end]

    assert "input.type === 'checkbox'" in body
    assert "params[key] = input.checked" in body


def test_setup_finish_groups_required_and_optional_readiness():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "function _renderReadinessGroup" in txt
    assert "Required setup" in txt
    assert "Optional capabilities" in txt
    assert "setup-readiness__group" in txt


def test_setup_finish_readiness_rows_render_detail_text():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderReadinessGroup")
    end = txt.index("  function _readinessTone", start)
    body = txt[start:end]

    assert "detail.detail" in body
    assert "setup-readiness__detail" in body


def test_setup_finish_readiness_rows_offer_direct_config_actions():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")
    start = txt.index("function _renderReadinessGroup")
    end = txt.index("  function _readinessTone", start)
    body = txt[start:end]

    assert "function _setupStepForSection" in txt
    assert "function _readinessActionLabel" in txt
    assert "const step = _setupStepForSection(name, detail)" in body
    assert "const action = _renderReadinessAction(step, detail, name)" in body
    assert "function _renderReadinessAction" in txt
    assert "const actionAriaLabel = _readinessActionAriaLabel(detail, name)" in body
    assert 'class="setup-readiness__action"' in body
    assert "aria-label=\"${_esc(actionAriaLabel)}\"" in body
    assert "title=\"${_esc(actionAriaLabel)}\"" in body
    assert "data-step=\"${_esc(step)}\"" in body
    assert "_readinessActionLabel(detail, name)" in body
    assert "function _readinessActionAriaLabel" in txt
    assert ".setup-readiness__action" in css
    assert "grid-template-columns: minmax(0, 1fr) auto auto auto" in css


def test_setup_finish_readiness_names_router_provider_prerequisite():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")

    assert "function _routerNeedsProvider" in txt
    assert "uses SquillaRouter after provider setup" in txt

    start = txt.index("function _setupStepForSection")
    end = txt.index("  function _readinessActionLabel", start)
    setup_body = txt[start:end]
    assert "if (_routerNeedsProvider(detail, name)) return 'provider'" in setup_body

    start = txt.index("function _readinessActionLabel")
    end = txt.index("  function _renderReadinessAction", start)
    action_body = txt[start:end]
    assert "if (_routerNeedsProvider(detail, name)) return 'Choose provider'" in action_body

    start = txt.index("function _readinessActionAriaLabel")
    aria_body = txt[start : txt.index("  function _readinessTone", start)]
    assert "return `Choose provider for ${label}`" in aria_body

    start = txt.index("function _readinessStatusLabel")
    status_body = txt[start : txt.index("  function _fieldHtml", start)]
    assert "if (_routerNeedsProvider(detail, name)) return 'Provider first'" in status_body


def test_setup_finish_summary_stays_neutral_before_provider_is_configured():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    start = txt.index("function _renderFinishStep()")
    end = txt.index("  function _renderCliCommand", start)
    body = txt[start:end]

    assert "const configuredProvider = _configuredProvider();" in body
    assert "const providerSummary = configuredProvider || 'not configured'" in body
    assert (
        "const modelSummary = configuredProvider"
        "\n      ? ((_config.llm || {}).model || 'SquillaRouter defaults')"
        "\n      : 'not configured'"
    ) in body
    assert (
        "const routerSummary = configuredProvider"
        "\n      ? (router.enabled === false ? 'disabled' : 'SquillaRouter')"
        "\n      : 'choose a provider first'"
    ) in body
    assert "router.tier_profile || 'openrouter-mix'" not in body
    assert "<strong>${_esc(providerSummary)}</strong>" in body
    assert "<strong>${_esc(modelSummary)}</strong>" in body
    assert "<strong>${_esc(routerSummary)}</strong>" in body


def test_setup_panel_avoids_dense_background_rule_lines():
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")
    panel_block = css.split(".setup-panel {", 1)[1].split("}", 1)[0]
    assert "repeating-linear-gradient" not in panel_block


def test_setup_capability_cards_keep_controls_top_aligned():
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")
    mini_block = css.split(".setup-mini {", 1)[1].split("}", 1)[0]

    assert "align-content: start" in mini_block


def test_setup_hidden_controls_remain_hidden_after_label_layout_rules():
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")

    assert ".setup [hidden]" in css
    hidden_block = css.split(".setup [hidden]", 1)[1].split("}", 1)[0]
    assert "display: none !important" in hidden_block


def test_setup_search_advanced_details_are_styled_as_secondary_controls():
    css = (ROOT / "static/css/views/setup.css").read_text(encoding="utf-8")

    assert ".setup-mini__advanced > summary" in css
    assert ".setup-mini__advanced-body" in css
    assert "details.setup-mini__advanced[open] > summary::after" in css


def test_config_view_exposes_memory_tab_and_restart_notice():
    txt = (VIEWS / "config.js").read_text(encoding="utf-8")
    assert "label: 'Memory'" in txt
    assert "memory.embedding.provider" in txt
    assert "Gateway restart required for the change to take effect" in txt


def test_config_view_links_to_guided_setup():
    txt = (VIEWS / "config.js").read_text(encoding="utf-8")
    assert "Guided setup" in txt
    assert "Router.navigate('/setup')" in txt


def test_channels_view_remains_status_only_but_links_guided_setup():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    assert "Runtime status" in txt
    assert "Guided setup" in txt
    assert "Router.navigate('/setup')" in txt
    assert "onboarding.channel.upsert" not in txt
    assert "channels.restart" not in txt


def test_example_config_does_not_advertise_local_embedding_model_override():
    txt = (ROOT.parents[2] / "opensquilla.toml.example").read_text(encoding="utf-8")
    local_section = txt.split("# [memory.embedding.local]", 1)[1].split(
        "# [memory.embedding.remote]",
        1,
    )[0]
    assert "model =" not in local_section
    assert "onnx_dir" in local_section
