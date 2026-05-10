from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.engine.types import ThinkingLevel
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.types import (
    ChatConfig,
    ContentBlockToolResult,
    ContentBlockToolUse,
    DoneEvent,
    Message,
    ModelCapabilities,
    ToolDefinition,
    ToolInputSchema,
    ToolUseEndEvent,
)


def _sse_body(model: str = "test-model") -> bytes:
    chunks = [
        {
            "model": model,
            "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
        },
        {
            "model": model,
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    ]
    body = b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
    return body + b"data: [DONE]\n\n"


def _patch_transport(monkeypatch: Any, captured: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)


def _patch_transport_body(monkeypatch: Any, captured: dict[str, Any], body: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)


def _collect(provider: OpenAIProvider, cfg: ChatConfig) -> DoneEvent:
    async def _run() -> DoneEvent:
        done: DoneEvent | None = None
        async for event in provider.chat([Message(role="user", content="hi")], config=cfg):
            if isinstance(event, DoneEvent):
                done = event
        assert done is not None
        return done

    return asyncio.run(_run())


def test_openrouter_deepseek_v4_returns_reasoning_content_from_details(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    chunks = [
        {
            "model": "deepseek/deepseek-v4-flash",
            "choices": [
                {
                    "delta": {
                        "reasoning_details": [
                            {"type": "reasoning.text", "text": "I considered the request."}
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "deepseek/deepseek-v4-flash",
            "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
        },
        {
            "model": "deepseek/deepseek-v4-flash",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    ]
    body = b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
    body += b"data: [DONE]\n\n"
    _patch_transport_body(monkeypatch, captured, body)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek/deepseek-v4-flash",
        base_url="https://openrouter.ai/api/v1",
        provider_kind="openrouter",
        provider_routing={"deepseek/deepseek-v4-flash": "deepseek"},
    )
    cfg = ChatConfig(
        thinking=True,
        thinking_level=ThinkingLevel.HIGH,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="openrouter",
        ),
    )

    done = _collect(provider, cfg)

    assert captured["payload"]["provider"]["only"] == ["deepseek"]
    assert captured["payload"]["reasoning"] == {"effort": "high"}
    assert done.reasoning_content == "I considered the request."


def _collect_events(
    provider: OpenAIProvider,
    cfg: ChatConfig,
    tools: list[ToolDefinition] | None = None,
) -> list[Any]:
    async def _run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hi")],
                config=cfg,
                tools=tools,
            )
        ]

    return asyncio.run(_run())


def test_deepseek_thinking_uses_provider_thinking_field_not_openai_reasoning_effort(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        provider_kind="deepseek",
    )
    cfg = ChatConfig(
        thinking=True,
        thinking_level=ThinkingLevel.HIGH,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    _collect(provider, cfg)

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert captured["payload"]["reasoning_effort"] == "high"


def test_deepseek_non_thinking_sends_provider_disabled_for_default_thinking_model(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        provider_kind="deepseek",
    )
    cfg = ChatConfig(
        thinking=False,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured["payload"]


def test_deepseek_tool_replay_preserves_reasoning_content_in_payload(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
        provider_kind="deepseek",
    )
    messages = [
        Message(
            role="assistant",
            content=[
                ContentBlockToolUse(
                    id="call_lookup",
                    name="lookup",
                    input={"q": "cache"},
                )
            ],
            reasoning_content="I need to inspect the cache state before answering.",
        ),
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id="call_lookup",
                    content="cache is warm",
                )
            ],
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert captured["payload"]["messages"][0]["role"] == "assistant"
    assert captured["payload"]["messages"][0]["tool_calls"][0]["id"] == "call_lookup"
    assert (
        captured["payload"]["messages"][0]["reasoning_content"]
        == "I need to inspect the cache state before answering."
    )
    assert captured["payload"]["messages"][1] == {
        "role": "tool",
        "tool_call_id": "call_lookup",
        "content": "cache is warm",
    }


def test_deepseek_v4_tool_replay_adds_empty_reasoning_content_when_missing(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        provider_kind="deepseek",
    )
    messages = [
        Message(
            role="assistant",
            content=[
                ContentBlockToolUse(
                    id="call_lookup",
                    name="lookup",
                    input={"q": "cache"},
                )
            ],
        ),
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id="call_lookup",
                    content="cache is warm",
                )
            ],
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert captured["payload"]["messages"][0]["reasoning_content"] == ""


def test_deepseek_v4_text_replay_adds_empty_reasoning_content_when_missing(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        provider_kind="deepseek",
    )
    messages = [
        Message(role="assistant", content="Prior non-thinking assistant turn."),
        Message(role="user", content="continue in thinking mode"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert captured["payload"]["messages"][0] == {
        "role": "assistant",
        "content": "Prior non-thinking assistant turn.",
        "reasoning_content": "",
    }


def test_deepseek_v4_non_thinking_replays_prior_reasoning_content(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        provider_kind="deepseek",
    )
    messages = [
        Message(
            role="assistant",
            content="previous answer",
            reasoning_content="prior thinking from earlier deepseek turn",
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=False,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert (
        captured["payload"]["messages"][0]["reasoning_content"]
        == "prior thinking from earlier deepseek turn"
    )


def test_deepseek_v4_replays_reasoning_content_without_catalog_capabilities(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        provider_kind="deepseek",
    )
    messages = [
        Message(
            role="assistant",
            content="previous answer",
            reasoning_content="prior thinking from direct deepseek",
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(thinking=True, model_capabilities=None)

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert captured["payload"]["reasoning_effort"] == "high"
    assert (
        captured["payload"]["messages"][0]["reasoning_content"]
        == "prior thinking from direct deepseek"
    )


def test_openrouter_reasoning_model_replays_reasoning_content_by_capability(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="anthropic/claude-sonnet-4.5",
        base_url="https://openrouter.ai/api/v1",
        provider_kind="openrouter",
    )
    messages = [
        Message(
            role="assistant",
            content="previous answer",
            reasoning_content="openrouter-native reasoning should be replayed",
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="openrouter",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert (
        captured["payload"]["messages"][0]["reasoning_content"]
        == "openrouter-native reasoning should be replayed"
    )


def test_non_deepseek_reasoning_model_does_not_replay_reasoning_content(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="gemini-2.5-pro",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        provider_kind="gemini",
    )
    messages = [
        Message(
            role="assistant",
            content="previous answer",
            reasoning_content="provider-internal reasoning must not be replayed",
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="gemini",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert "reasoning_content" not in captured["payload"]["messages"][0]


def test_deepseek_non_v4_model_does_not_replay_reasoning_content(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        provider_kind="deepseek",
    )
    messages = [
        Message(
            role="assistant",
            content="previous answer",
            reasoning_content="must not be replayed for non-v4 direct DeepSeek",
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert "reasoning_content" not in captured["payload"]["messages"][0]


def test_deepseek_reasoning_format_without_deepseek_model_does_not_replay_reasoning_content(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="custom-reasoning-model",
        base_url="https://api.deepseek.com/v1",
        provider_kind="deepseek",
    )
    messages = [
        Message(
            role="assistant",
            content="previous answer",
            reasoning_content="must not be replayed for a non-DeepSeek model",
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="deepseek",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    assert "reasoning_content" not in captured["payload"]["messages"][0]


def test_gemini_reasoning_uses_openai_compatible_reasoning_effort(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        provider_kind="gemini",
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="gemini",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["reasoning_effort"] == "medium"
    assert "thinking" not in captured["payload"]


def test_gemini_25_flash_lite_non_thinking_uses_reasoning_effort_none(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="gemini-2.5-flash-lite",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        provider_kind="gemini",
    )
    cfg = ChatConfig(
        thinking=False,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="gemini",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["reasoning_effort"] == "none"
    assert "thinking" not in captured["payload"]


def test_zai_thinking_uses_provider_thinking_object(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="glm-4.5",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        provider_kind="zhipu",
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="zai",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in captured["payload"]


def test_glm_5_1_thinking_uses_provider_thinking_object(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="glm-5.1",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        provider_kind="zhipu",
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="zai",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in captured["payload"]


def test_zai_non_thinking_sends_provider_disabled_for_default_thinking_model(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="glm-5.1",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        provider_kind="zhipu",
    )
    cfg = ChatConfig(
        thinking=False,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="zai",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_dashscope_thinking_uses_enable_thinking_and_budget(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="qwen3.6-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_kind="dashscope",
    )
    cfg = ChatConfig(
        thinking=True,
        thinking_budget_tokens=4096,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="dashscope",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["enable_thinking"] is True
    assert captured["payload"]["thinking_budget"] == 4096
    assert "reasoning_effort" not in captured["payload"]


def test_dashscope_non_thinking_sends_enable_thinking_false(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="qwen3.6-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_kind="dashscope",
    )
    cfg = ChatConfig(
        thinking=False,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="dashscope",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["enable_thinking"] is False
    assert "thinking_budget" not in captured["payload"]


def test_moonshot_kimi_thinking_uses_provider_thinking_object(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="kimi-k2.5",
        base_url="https://api.moonshot.cn/v1",
        provider_kind="moonshot",
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="moonshot",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "enabled"}


def test_moonshot_kimi_non_thinking_sends_provider_disabled(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="kimi-k2.5",
        base_url="https://api.moonshot.cn/v1",
        provider_kind="moonshot",
    )
    cfg = ChatConfig(
        thinking=False,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="moonshot",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_volcengine_thinking_uses_provider_thinking_object(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="doubao-seed-1-6-thinking-250715",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        provider_kind="volcengine",
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="volcengine",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "enabled"}


def test_volcengine_non_thinking_sends_provider_disabled(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="doubao-seed-1-6-thinking-250715",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        provider_kind="volcengine",
    )
    cfg = ChatConfig(
        thinking=False,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="volcengine",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_moonshot_kimi_k2_6_omits_temperature_for_fixed_sampling(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="kimi-k2.6",
        base_url="https://api.moonshot.cn/v1",
        provider_kind="moonshot",
    )

    _collect(provider, ChatConfig(temperature=0))

    assert "temperature" not in captured["payload"]


def test_moonshot_v1_still_sends_temperature(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="moonshot-v1-8k",
        base_url="https://api.moonshot.cn/v1",
        provider_kind="moonshot",
    )

    _collect(provider, ChatConfig(temperature=0))

    assert captured["payload"]["temperature"] == 0


def test_direct_openai_gpt_5_5_reasoning_uses_max_completion_tokens_without_temperature(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="gpt-5.5",
        base_url="https://api.openai.com/v1",
        provider_kind="openai",
    )
    cfg = ChatConfig(
        thinking=True,
        temperature=0,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            supports_tools=True,
            reasoning_format="openai",
        ),
    )

    _collect(provider, cfg)

    assert captured["payload"]["max_completion_tokens"] == cfg.max_tokens
    assert "max_tokens" not in captured["payload"]
    assert captured["payload"]["reasoning_effort"] == "medium"
    assert "temperature" not in captured["payload"]


def test_openrouter_still_sends_temperature(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1",
        provider_kind="openrouter",
    )

    _collect(provider, ChatConfig(temperature=0))

    assert captured["payload"]["temperature"] == 0


def test_siliconflow_baseline_payload_does_not_enable_provider_thinking_by_default(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="test",
        model="deepseek-ai/DeepSeek-V3",
        base_url="https://api.siliconflow.cn/v1",
        provider_kind="siliconflow",
    )

    _collect(provider, ChatConfig())

    assert "enable_thinking" not in captured["payload"]
    assert "thinking_budget" not in captured["payload"]
    assert "thinking" not in captured["payload"]


def test_ovms_v3_base_url_posts_to_v3_chat_completions(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="unused",
        model="llama3",
        base_url="http://localhost:8000/v3",
        provider_kind="ovms",
    )

    _collect(provider, ChatConfig())

    assert captured["url"] == "http://localhost:8000/v3/chat/completions"


def test_qianfan_v2_base_url_posts_to_v2_chat_completions(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="unused",
        model="ernie-4.0-turbo-8k",
        base_url="https://qianfan.baidubce.com/v2",
        provider_kind="qianfan",
    )

    _collect(provider, ChatConfig())

    assert captured["url"] == "https://qianfan.baidubce.com/v2/chat/completions"


def test_zai_v4_base_url_posts_to_v4_chat_completions(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(monkeypatch, captured)
    provider = OpenAIProvider(
        api_key="unused",
        model="glm-4.5",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        provider_kind="zhipu",
    )

    _collect(provider, ChatConfig())

    assert captured["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def test_gemini_stream_tool_call_without_index_is_tolerated(monkeypatch: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [
            {
                "model": "gemini-2.5-flash",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "id": "call_lookup",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"q":"hi"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "model": "gemini-2.5-flash",
                "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        ]
        body = b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body + b"data: [DONE]\n\n",
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(
        api_key="test",
        model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        provider_kind="gemini",
    )
    tool = ToolDefinition(
        name="lookup",
        description="Lookup a value.",
        input_schema=ToolInputSchema(properties={"q": {"type": "string"}}, required=["q"]),
    )

    events = _collect_events(provider, ChatConfig(), tools=[tool])

    tool_end = next(event for event in events if isinstance(event, ToolUseEndEvent))
    done = next(event for event in events if isinstance(event, DoneEvent))
    assert tool_end.tool_use_id == "call_lookup"
    assert tool_end.tool_name == "lookup"
    assert tool_end.arguments == {"q": "hi"}
    assert done.model == "gemini-2.5-flash"
