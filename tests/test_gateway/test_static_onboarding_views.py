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
    assert "opensquilla configure --section channels" in txt


def test_channels_stats_do_not_report_attention_states_as_healthy():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    assert "all healthy" not in txt
    assert "need attention" in txt
    assert "restarting" in txt
    assert "exhausted" in txt


def test_channels_view_filters_to_configured_channels():
    txt = (VIEWS / "channels.js").read_text(encoding="utf-8")
    assert "configured !== false" in txt


def test_setup_view_loads_catalog_and_status():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "onboarding.catalog" in txt
    assert "onboarding.status" in txt
    assert "config.get" in txt
    assert "onboarding.provider.configure" in txt
    assert "onboarding.imageGeneration.configure" in txt
    assert "imageGenerationProviders" in txt
    assert "onboarding.memory_embedding.configure" in txt
    assert "Remote fallback API key" in txt
    assert "effectiveProvider" in txt
    assert "current.mode" in txt


def test_setup_view_is_available_and_uses_canonical_cli_fallbacks():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "SETUP_UI_AVAILABLE" not in txt
    assert "opensquilla onboard" in txt
    assert "opensquilla configure provider" in txt
    assert "opensquilla providers configure" not in txt
    assert "onboarding.router.configure" in txt
    assert "onboarding.channel.probe" in txt
    assert "channels.status" in txt
    assert "Connected" in txt


def test_setup_view_keeps_channel_fields_in_config_shape():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "scope === 'channel' ? label.dataset.name : _camel" in txt


def test_setup_view_renders_catalog_field_descriptions():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "field.description" in txt
    assert "setup-field-desc" in txt


def test_setup_view_warns_when_env_key_is_not_visible_to_gateway():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "missing_env" in txt
    assert "not visible to this gateway process" in txt
    assert "Set it before starting or restarting the gateway" in txt
    assert "if (_providerEnvMissing())" in txt


def test_setup_view_does_not_default_env_key_over_stored_provider_key():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "current.api_key ? '' : field.default" in txt


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
    assert "SetupView.render" in app
    assert "Router.register('/setup'" in app
    assert 'data-path="/setup"' not in app


def test_setup_view_marks_unsupported_providers_disabled():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "runtimeSupported" in txt


def test_setup_view_treats_image_configure_as_capability_enable_action():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "field.default !== false" in txt
    assert "imageGenerationEnabled === false" in txt


def test_setup_view_explains_image_generation_tool_visibility():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "image_generate is hidden from agents" in txt
    assert "image_generate will be available in new turns" in txt


def test_setup_view_preserves_selected_image_generation_provider():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "imageProviderSelected" in txt
    assert "imageGenerationProvider" in txt
    assert "imageGenerationPrimary || '').split('/')[0]" in txt


def test_setup_router_controls_use_user_facing_labels():
    txt = (VIEWS / "setup.js").read_text(encoding="utf-8")
    assert "SquillaRouter" in txt
    assert "OpenRouter mix" not in txt
    assert "Balanced default (t1)" in txt
    assert "Stronger reasoning (t2)" in txt


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
