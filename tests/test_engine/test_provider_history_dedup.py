"""Opt-in provider-view history dedup lever.

Covers OPENSQUILLA_PROVIDER_HISTORY_DEDUP (off by default). Motivation: long
single-turn episodes re-run the same
read/grep/diff commands and full-history replay resends every byte-identical
tool_result on every iteration, paying quadratic cost. When enabled, older
byte-identical tool results are replaced in the provider request projection
with a short back-reference to the surviving newest copy; persisted history is
never mutated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from opensquilla.engine import Agent, AgentConfig
from opensquilla.provider import (
    ContentBlockToolResult,
    ContentBlockToolUse,
    Message,
)
from opensquilla.provider.types import ChatConfig


class _StubProvider:
    provider_name = "fake"

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        return
        yield

    async def list_models(self) -> list[Any]:
        return []


# A payload comfortably above _PROVIDER_HISTORY_DEDUP_MIN_CHARS (400).
BIG_RESULT = "line of grep output\n" * 60


def _pair(use_id: str, content: str, *, is_error: bool = False) -> list[Message]:
    return [
        Message(
            role="assistant",
            content=[
                ContentBlockToolUse(
                    id=use_id, name="grep_search", input={"pattern": "foo"}
                ),
            ],
        ),
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id=use_id, content=content, is_error=is_error
                )
            ],
        ),
    ]


def _history(*contents: tuple[str, str]) -> list[Message]:
    messages: list[Message] = [Message(role="user", content="find the bug")]
    for use_id, content in contents:
        messages.extend(_pair(use_id, content))
    return messages


def _tool_results(messages: list[Message]) -> list[ContentBlockToolResult]:
    results: list[ContentBlockToolResult] = []
    for message in messages:
        if not isinstance(message.content, list):
            continue
        for block in message.content:
            if isinstance(block, ContentBlockToolResult):
                results.append(block)
    return results


def test_dedup_off_by_default() -> None:
    assert AgentConfig().provider_history_dedup_enabled is False
    agent = Agent(provider=_StubProvider(), config=AgentConfig())
    history = _history(("g1", BIG_RESULT), ("g2", BIG_RESULT), ("g3", BIG_RESULT))
    projected = agent._dedup_repeated_tool_results_for_provider(history)
    contents = [r.content for r in _tool_results(projected)]
    assert contents == [BIG_RESULT, BIG_RESULT, BIG_RESULT]


def test_dedup_elides_older_identical_results_keeps_newest() -> None:
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(provider_history_dedup_enabled=True),
    )
    # g1..g3 are byte-identical; g4 is unique. The recent-tail guard covers the
    # last two results (g3, g4), so g1 and g2 are elided and g3 survives full.
    history = _history(
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
        ("g3", BIG_RESULT),
        ("g4", "unique tail result " * 40),
    )
    projected = agent._dedup_repeated_tool_results_for_provider(history)
    results = _tool_results(projected)
    for stub in (results[0], results[1]):
        assert stub.content.startswith("[duplicate_tool_result_elided]\n")
        assert "identical_to_tool_use_id: g3" in stub.content
    # The surviving newest identical copy (g3) stays full.
    assert results[2].content == BIG_RESULT
    assert agent.config.metadata["provider_history_dedup_elided"] == 2
    assert agent.config.metadata["provider_history_dedup_chars_saved"] > 0


def test_dedup_is_idempotent_across_iterations() -> None:
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(provider_history_dedup_enabled=True),
    )
    history = _history(
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
        ("g3", BIG_RESULT),
        ("g4", "unique tail result " * 40),
    )
    once = agent._dedup_repeated_tool_results_for_provider(history)
    twice = agent._dedup_repeated_tool_results_for_provider(once)
    assert [r.content for r in _tool_results(twice)] == [
        r.content for r in _tool_results(once)
    ]


def test_dedup_leaves_recent_tail_duplicates_alone() -> None:
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(provider_history_dedup_enabled=True),
    )
    # The only duplicates are the two most recent results - the model is
    # actively looking at them, so nothing is elided.
    history = _history(
        ("u1", "unique first result " * 40),
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
    )
    projected = agent._dedup_repeated_tool_results_for_provider(history)
    contents = [r.content for r in _tool_results(projected)]
    assert contents.count(BIG_RESULT) == 2


def test_dedup_does_not_mutate_persisted_history() -> None:
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(provider_history_dedup_enabled=True),
    )
    history = _history(
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
        ("g3", BIG_RESULT),
        ("g4", "tail " * 120),
    )
    before = [r.content for r in _tool_results(history)]
    agent._dedup_repeated_tool_results_for_provider(history)
    after = [r.content for r in _tool_results(history)]
    assert before == after


def test_dedup_skips_error_results() -> None:
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(provider_history_dedup_enabled=True),
    )
    history = _history(
        ("e1", BIG_RESULT),
        ("e2", BIG_RESULT),
        ("e3", BIG_RESULT),
        ("t1", "tail " * 120),
    )
    # Mark the first three as errors post-hoc.
    for use_id in ("e1", "e2", "e3"):
        for message in history:
            if isinstance(message.content, list):
                for block in message.content:
                    if (
                        isinstance(block, ContentBlockToolResult)
                        and block.tool_use_id == use_id
                    ):
                        block.is_error = True
    projected = agent._dedup_repeated_tool_results_for_provider(history)
    contents = [r.content for r in _tool_results(projected)]
    assert all(not c.startswith("[duplicate_tool_result_elided]") for c in contents)


def test_dedup_skips_small_results_below_min_chars() -> None:
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(provider_history_dedup_enabled=True),
    )
    small = "tiny"  # < 400 chars
    history = _history(
        ("s1", small),
        ("s2", small),
        ("s3", small),
        ("t1", "tail " * 120),
    )
    projected = agent._dedup_repeated_tool_results_for_provider(history)
    contents = [r.content for r in _tool_results(projected)]
    assert contents.count(small) == 3


def test_dedup_respects_min_repeats_threshold() -> None:
    # With min_repeats=3, two copies are not enough to elide.
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(
            provider_history_dedup_enabled=True,
            provider_history_dedup_min_repeats=3,
        ),
    )
    history = _history(
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
        ("t1", "tail " * 120),
        ("t2", "other " * 120),
    )
    projected = agent._dedup_repeated_tool_results_for_provider(history)
    contents = [r.content for r in _tool_results(projected)]
    assert contents.count(BIG_RESULT) == 2


def test_dedup_groups_across_iterations_despite_frozen_survivor() -> None:
    # A block already frozen full (shown in a prior request) must still count
    # toward the digest group so newer duplicates get elided — it must only
    # be excluded from being re-stubbed itself.
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(
            provider_history_dedup_enabled=True,
            provider_history_dedup_min_repeats=3,
        ),
    )
    iter1_history = _history(("g1", BIG_RESULT))
    iter1_projected = agent._dedup_repeated_tool_results_for_provider(iter1_history)
    agent._remember_provider_visible_tool_results(iter1_projected)
    assert "g1" in agent._provider_tool_result_frozen_full_ids

    iter2_history = _history(
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
        ("g3", BIG_RESULT),
        ("u1", "unique final result " * 40),
    )
    projected = agent._dedup_repeated_tool_results_for_provider(iter2_history)
    results = {r.tool_use_id: r.content for r in _tool_results(projected)}
    # g1 stays full (frozen, protected from retroactive downgrade).
    assert results["g1"] == BIG_RESULT
    # g2 is now correctly elided against the newest survivor g3.
    assert results["g2"].startswith("[duplicate_tool_result_elided]\n")
    assert "identical_to_tool_use_id: g3" in results["g2"]
    assert results["g3"] == BIG_RESULT


def test_dedup_stub_is_not_permanently_frozen() -> None:
    # Elision depends on another block's state (its survivor), so it must
    # never be frozen into a permanent override — only recomputed fresh.
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(provider_history_dedup_enabled=True),
    )
    history = _history(
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
        ("g3", BIG_RESULT),
        ("u1", "unique final result " * 40),
    )
    projected = agent._dedup_repeated_tool_results_for_provider(history)
    agent._remember_provider_visible_tool_results(projected)

    assert "g1" not in agent._provider_tool_result_frozen_overrides
    assert "g1" not in agent._provider_tool_result_frozen_full_ids
    assert "g2" not in agent._provider_tool_result_frozen_overrides
    assert "g2" not in agent._provider_tool_result_frozen_full_ids


def test_compact_does_not_recompact_dedup_survivor_in_same_request() -> None:
    # The dedup survivor is the one full copy other stubs point back to; the
    # aggregate compaction pass running right after must not turn it into a
    # compacted stub too, or the back-references become dangling.
    agent = Agent(
        provider=_StubProvider(),
        config=AgentConfig(
            provider_history_dedup_enabled=True,
            context_window_tokens=100,
        ),
    )
    history = _history(
        ("g1", BIG_RESULT),
        ("g2", BIG_RESULT),
        ("g3", BIG_RESULT),
        ("u1", "unique tail result one " * 40),
        ("u2", "unique tail result two " * 40),
    )
    deduped = agent._dedup_repeated_tool_results_for_provider(history)
    assert agent._provider_history_dedup_survivor_ids == {"g3"}

    compacted = agent._compact_aggregate_tool_results_for_provider(deduped)
    results = {r.tool_use_id: r.content for r in _tool_results(compacted)}
    assert results["g3"] == BIG_RESULT


def test_dedup_env_plumbing(monkeypatch) -> None:
    from opensquilla.engine.turn_runner.agent_bootstrap_stage import (
        _bool_from_env,
        _positive_int_from_env,
    )

    assert _bool_from_env("OPENSQUILLA_PROVIDER_HISTORY_DEDUP", False) is False
    assert _positive_int_from_env("OPENSQUILLA_PROVIDER_HISTORY_DEDUP_MIN_REPEATS", 2) == 2
    monkeypatch.setenv("OPENSQUILLA_PROVIDER_HISTORY_DEDUP", "1")
    monkeypatch.setenv("OPENSQUILLA_PROVIDER_HISTORY_DEDUP_MIN_REPEATS", "4")
    assert _bool_from_env("OPENSQUILLA_PROVIDER_HISTORY_DEDUP", False) is True
    assert _positive_int_from_env("OPENSQUILLA_PROVIDER_HISTORY_DEDUP_MIN_REPEATS", 2) == 4


def test_tool_result_artifact_detection_is_cached() -> None:
    from opensquilla.engine.agent import _tool_result_content_has_artifact

    content = '{"status": "published", "marker": "cache-test-unique-9f3"}'
    _tool_result_content_has_artifact.cache_clear()
    before = _tool_result_content_has_artifact.cache_info()
    assert _tool_result_content_has_artifact(content) is True
    assert _tool_result_content_has_artifact(content) is True
    after = _tool_result_content_has_artifact.cache_info()
    assert after.hits == before.hits + 1
    assert after.misses == before.misses + 1
