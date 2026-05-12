from __future__ import annotations

import pytest

from opensquilla.provider.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    OpenRouterImageGenerationProvider,
    get_image_generation_provider,
)


@pytest.mark.asyncio
async def test_openrouter_image_provider_adds_app_attribution_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "images": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "data:image/png;base64,b3BlbnNxdWlsbGE="},
                                }
                            ]
                        }
                    }
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "opensquilla.provider.image_generation.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    provider = OpenRouterImageGenerationProvider(api_key="or-test")
    result = await provider.generate(
        ImageGenerationRequest(
            prompt="draw a squid",
            model="google/gemini-3.1-flash-image-preview",
            size="1536x1024",
            output_format="png",
            timeout_seconds=10.0,
        )
    )

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer or-test",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://opensquilla.ai",
        "X-OpenRouter-Title": "OpenSquilla",
        "X-OpenRouter-Categories": "cli-agent,personal-agent",
    }
    assert result.image_bytes == b"opensquilla"


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_kind", ["web", "channel"])
async def test_image_generate_auto_publishes_generated_image_artifact_for_surfaces(
    monkeypatch, tmp_path, caller_kind
) -> None:
    from opensquilla.gateway.config import ImageGenerationConfig
    from opensquilla.tools.builtin import media
    from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context

    async def fake_generate_with_fallbacks(**_kwargs):
        return ImageGenerationResult(
            image_bytes=b"fake-png",
            mime_type="image/png",
            model="google/gemini-3.1-flash-image-preview",
            provider="openrouter",
        )

    monkeypatch.setattr(media, "generate_with_fallbacks", fake_generate_with_fallbacks)
    config = ImageGenerationConfig(
        enabled=True,
        primary="openrouter/google/gemini-3.1-flash-image-preview",
    )
    config.providers.openrouter.api_key = "sk-or-test"
    media.configure_image_generation(config)

    ctx = ToolContext(
        caller_kind=CallerKind(caller_kind),
        workspace_dir=str(tmp_path / "workspace"),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key=f"agent:main:{caller_kind}:test",
    )
    token = current_tool_context.set(ctx)
    try:
        payload = await media.image_generate(
            prompt="draw an elephant",
            filename="Elephant.png",
        )
    finally:
        current_tool_context.reset(token)
        media.configure_image_generation(None)

    result = __import__("json").loads(payload)
    assert result["status"] == "ok"
    assert result["path"].endswith("Elephant.png")
    assert result["artifact"]["name"] == "Elephant.png"
    assert result["artifact"]["mime"] == "image/png"
    assert result["artifact"]["delivered_to_user"] is True
    assert "download_url" not in result["artifact"]
    assert "already published" in result["note"]
    assert "Do not call publish_artifact" in result["note"]
    assert len(ctx.published_artifacts) == 1
    published = ctx.published_artifacts[0]
    assert published["name"] == "Elephant.png"
    assert published["mime"] == "image/png"
    assert published["download_url"] == f"/api/v1/artifacts/{published['id']}"


@pytest.mark.asyncio
async def test_image_generate_does_not_auto_publish_artifact_for_subagent(
    monkeypatch, tmp_path
) -> None:
    from opensquilla.gateway.config import ImageGenerationConfig
    from opensquilla.tools.builtin import media
    from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context

    async def fake_generate_with_fallbacks(**_kwargs):
        return ImageGenerationResult(
            image_bytes=b"fake-png",
            mime_type="image/png",
            model="google/gemini-3.1-flash-image-preview",
            provider="openrouter",
        )

    monkeypatch.setattr(media, "generate_with_fallbacks", fake_generate_with_fallbacks)
    config = ImageGenerationConfig(
        enabled=True,
        primary="openrouter/google/gemini-3.1-flash-image-preview",
    )
    config.providers.openrouter.api_key = "sk-or-test"
    media.configure_image_generation(config)

    ctx = ToolContext(
        caller_kind=CallerKind.SUBAGENT,
        workspace_dir=str(tmp_path / "workspace"),
        artifact_media_root=str(tmp_path / "media"),
        artifact_session_id="session-1",
        session_key="agent:main:subagent:test",
    )
    token = current_tool_context.set(ctx)
    try:
        payload = await media.image_generate(
            prompt="draw an elephant",
            filename="Elephant.png",
        )
    finally:
        current_tool_context.reset(token)
        media.configure_image_generation(None)

    result = __import__("json").loads(payload)
    assert result["status"] == "ok"
    assert "artifact" not in result
    assert ctx.published_artifacts == []


def test_image_generation_reuses_llm_key_only_after_capability_is_enabled(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    from opensquilla.gateway.config import ImageGenerationConfig, LlmProviderConfig
    from opensquilla.tools.builtin.media import (
        _resolve_image_generation_candidates,
        configure_image_generation,
        image_generation_available,
    )

    image_config = ImageGenerationConfig()
    llm_config = LlmProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.1",
        api_key="sk-or-configured",
        base_url="https://openrouter.ai/api/v1",
    )

    configure_image_generation(image_config, llm_config=llm_config)

    provider = get_image_generation_provider("openrouter")
    assert provider is not None
    assert provider._resolve_api_key() == "sk-or-configured"
    assert "openrouter/google/gemini-3.1-flash-image-preview" in (
        _resolve_image_generation_candidates(None, image_config)
    )
    assert not image_generation_available()

    image_config.enabled = True
    assert image_generation_available()


def test_image_generation_uses_provider_specific_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    from opensquilla.gateway.config import (
        ImageGenerationConfig,
        ImageGenerationOpenAIProviderConfig,
        ImageGenerationProvidersConfig,
    )
    from opensquilla.tools.builtin.media import (
        configure_image_generation,
        image_generation_available,
    )

    image_config = ImageGenerationConfig(
        enabled=True,
        primary="openai/gpt-image-1",
        providers=ImageGenerationProvidersConfig(
            openai=ImageGenerationOpenAIProviderConfig(api_key="sk-openai-configured")
        ),
    )

    configure_image_generation(image_config)

    provider = get_image_generation_provider("openai")
    assert provider is not None
    assert provider._resolve_api_key() == "sk-openai-configured"
    assert image_generation_available()


def test_image_generation_nondefault_primary_does_not_auto_add_llm_provider(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    from opensquilla.gateway.config import ImageGenerationConfig, LlmProviderConfig
    from opensquilla.tools.builtin.media import (
        _resolve_image_generation_candidates,
        configure_image_generation,
    )

    image_config = ImageGenerationConfig(primary="openai/custom-image-model")
    configure_image_generation(
        image_config,
        llm_config=LlmProviderConfig(provider="openrouter", api_key="sk-or-configured"),
    )

    assert _resolve_image_generation_candidates(None, image_config) == ["openai/custom-image-model"]


def test_image_generation_persisted_default_primary_still_adds_llm_provider(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
    from opensquilla.tools.builtin.media import (
        _resolve_image_generation_candidates,
        configure_image_generation,
    )

    config = GatewayConfig.model_validate(GatewayConfig().model_dump(mode="python"))
    config.llm = LlmProviderConfig(provider="openrouter", api_key="sk-or-configured")
    configure_image_generation(config.image_generation, llm_config=config.llm)

    assert "openrouter/google/gemini-3.1-flash-image-preview" in (
        _resolve_image_generation_candidates(None, config.image_generation)
    )


def test_image_generation_capability_exposes_agent_tool_when_configured(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.gateway.config import ImageGenerationConfig, LlmProviderConfig
    from opensquilla.tools.builtin.media import configure_image_generation
    from opensquilla.tools.registry import get_default_registry
    from opensquilla.tools.types import CallerKind, ToolContext

    configure_image_generation(
        ImageGenerationConfig(enabled=True),
        llm_config=LlmProviderConfig(provider="openrouter", api_key="sk-or-configured"),
    )
    runner = object.__new__(TurnRunner)
    runner._tool_registry = get_default_registry()

    ctx = ToolContext(is_owner=True, caller_kind=CallerKind.WEB, agent_id="main")
    ctx = TurnRunner._apply_runtime_capability_denies(runner, ctx)
    tool_defs = runner._tool_registry.to_tool_definitions(ctx)
    tool_defs = TurnRunner._filter_tool_defs_by_capability(runner, tool_defs)
    names = {tool.name for tool in tool_defs}

    assert "image_generate" in names


def test_image_generation_capability_does_not_expose_agent_tool_when_disabled(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.gateway.config import ImageGenerationConfig, LlmProviderConfig
    from opensquilla.tools.builtin.media import configure_image_generation
    from opensquilla.tools.registry import get_default_registry
    from opensquilla.tools.types import CallerKind, ToolContext

    configure_image_generation(
        ImageGenerationConfig(),
        llm_config=LlmProviderConfig(provider="openrouter", api_key="sk-or-configured"),
    )
    runner = object.__new__(TurnRunner)
    runner._tool_registry = get_default_registry()

    ctx = ToolContext(is_owner=True, caller_kind=CallerKind.WEB, agent_id="main")
    ctx = TurnRunner._apply_runtime_capability_denies(runner, ctx)
    tool_defs = runner._tool_registry.to_tool_definitions(ctx)
    tool_defs = TurnRunner._filter_tool_defs_by_capability(runner, tool_defs)
    names = {tool.name for tool in tool_defs}

    assert "image_generate" not in names
