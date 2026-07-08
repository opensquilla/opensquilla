from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.provider.ollama import OllamaProvider
from opensquilla.provider.types import ChatConfig, DoneEvent, Message


def test_ollama_provider_writes_llm_trace(monkeypatch: Any, tmp_path: Any) -> None:
    trace_path = tmp_path / "ollama-llm-calls.jsonl"
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_RECORDER", "full")
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_PATH", str(trace_path))
    body = b"".join(
        [
            json.dumps({"message": {"content": "ok"}, "done": False}).encode() + b"\n",
            json.dumps(
                {"message": {}, "done": True, "prompt_eval_count": 5, "eval_count": 2}
            ).encode()
            + b"\n",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=body,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.ollama.httpx.AsyncClient", patched_async_client)
    provider = OllamaProvider(model="llama3")

    async def _run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hi")],
                config=ChatConfig(max_tokens=12),
            )
        ]

    events = asyncio.run(_run())

    assert any(isinstance(event, DoneEvent) for event in events)
    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == [
        "llm.request",
        "llm.response_chunk",
        "llm.response_chunk",
        "llm.response",
    ]
    assert rows[0]["provider"] == "ollama"
    assert rows[-1]["assistant_text"] == "ok"
    assert rows[-1]["usage"]["input_tokens"] == 5
