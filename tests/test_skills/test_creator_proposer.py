"""Tests for creator/proposer.py (fill_slots, assemble) + patterns."""

from __future__ import annotations

import json

import pytest

from opensquilla.skills.creator.patterns.schemas import (
    FanOutMergeSlots,
    SequentialSlots,
)
from opensquilla.skills.creator.proposer import meta_skill_assemble


def test_sequential_slots_min_steps() -> None:
    with pytest.raises(ValueError):
        SequentialSlots(
            name="test-x", description="d" * 30, triggers=["t"],
            steps=[{"id": "a", "skill": "x", "task": "t"}],
        )


def test_sequential_with_keys_default_empty() -> None:
    slots = SequentialSlots(
        name="test-x", description="d" * 30, triggers=["t"],
        steps=[
            {"id": "a", "skill": "summarize", "task": "do thing"},
            {"id": "b", "skill": "memory", "task": "save"},
        ],
    )
    assert slots.steps[0].with_keys == {}


def test_fanout_tail_optional() -> None:
    slots = FanOutMergeSlots(
        name="test-x", description="d" * 30, triggers=["t"],
        branches=[
            {"id": "a", "skill": "weather", "task": "t"},
            {"id": "b", "skill": "summarize", "task": "t"},
        ],
        merge={"id": "m", "skill": "summarize", "task": "t"},
    )
    assert slots.tail is None


def test_meta_skill_assemble_p1() -> None:
    slots = {
        "name": "test-t1", "description": "d" * 30, "triggers": ["go"],
        "steps": [
            {"id": "a", "skill": "summarize", "task": "extract", "with_keys": {}},
            {"id": "b", "skill": "memory", "task": "store", "with_keys": {}},
        ],
        "meta_priority": 50,
    }
    md = meta_skill_assemble("p1_sequential", json.dumps(slots))
    # N2: tojson wraps values in JSON double-quotes (valid YAML scalars)
    assert 'name: "test-t1"' in md
    assert 'skill: "summarize"' in md
    assert 'skill: "memory"' in md
    assert "depends_on: [a]" in md


def test_meta_skill_assemble_rejects_invalid_slots() -> None:
    with pytest.raises(ValueError):
        meta_skill_assemble("p1_sequential", '{"name": "x"}')


def test_meta_skill_fill_slots_with_stub_llm(monkeypatch) -> None:
    from opensquilla.skills.creator import proposer

    call_log: list[str] = []
    canned_response = json.dumps({
        "name": "synth-pipeline",
        "description": "Synthetic pipeline that does X then Y. Sample for testing fill_slots flow.",
        "meta_priority": 50,
        "triggers": ["synth test"],
        "steps": [
            {"id": "a", "skill": "summarize", "task": "process", "with_keys": {}},
            {"id": "b", "skill": "memory", "task": "save", "with_keys": {}},
        ],
    })

    def stub_llm(prompt: str, **_kwargs) -> str:
        call_log.append(prompt)
        return canned_response

    monkeypatch.setattr(proposer, "_call_llm_for_slots", stub_llm)

    result = proposer.meta_skill_fill_slots(
        pattern_id="p1_sequential",
        history_summary="(no history)",
        user_intent="process docs then save",
    )
    data = json.loads(result)
    assert data["name"] == "synth-pipeline"
    assert len(call_log) == 1
    # Catalog injection: skill names must appear in prompt
    assert "summarize" in call_log[0]


def test_creator_package_import_registers_tools() -> None:
    """C1 regression: importing the creator package must register both tools
    in the default ToolRegistry. Phase 1 cross-task review found that the
    @tool decorators only run when the module is imported — production code
    must import opensquilla.skills.creator somewhere in the meta-skill branch."""
    import importlib

    import opensquilla.skills.creator
    importlib.reload(opensquilla.skills.creator)

    from opensquilla.tools.registry import get_default_registry
    names = get_default_registry().list_names()
    meta_names = sorted(n for n in names if n.startswith("meta"))
    assert "meta_skill_assemble" in names, (
        f"meta_skill_assemble not registered; got: {meta_names}"
    )
    assert "meta_skill_fill_slots" in names, "meta_skill_fill_slots not registered"


def test_meta_skill_fill_slots_retries_once_on_validation_error(monkeypatch) -> None:
    from opensquilla.skills.creator import proposer

    responses = iter([
        '{"name": "bad"}',  # missing fields → ValidationError
        json.dumps({
            "name": "synth-pipeline",
            "description": "Synthetic pipeline that does X then Y. Sample.",
            "meta_priority": 50,
            "triggers": ["synth test"],
            "steps": [
                {"id": "a", "skill": "summarize", "task": "process", "with_keys": {}},
                {"id": "b", "skill": "memory", "task": "save", "with_keys": {}},
            ],
        }),
    ])
    prompts: list[str] = []

    def stub_llm(prompt: str, **_kwargs) -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(proposer, "_call_llm_for_slots", stub_llm)

    result = proposer.meta_skill_fill_slots(
        pattern_id="p1_sequential",
        history_summary="(no history)",
        user_intent="process docs then save",
    )
    data = json.loads(result)
    assert data["name"] == "synth-pipeline"
    assert len(prompts) == 2
    # Retry prompt must include the ValidationError feedback
    assert "failed schema validation" in prompts[1] or "errors" in prompts[1]


def test_creator_tools_hidden_from_owner_default() -> None:
    """N1: meta_skill_{assemble,fill_slots} must NOT appear in the default
    owner tool catalog. They are internal orchestrator-only tools."""
    import importlib

    import opensquilla.skills.creator  # trigger @tool registration
    importlib.reload(opensquilla.skills.creator)

    from opensquilla.tools.registry import ToolContext, get_default_registry

    reg = get_default_registry()
    # Use the default owner context (is_owner=True, no allowed_tools override).
    # _iter_visible_tools with this context filters out exposed_by_default=False.
    ctx = ToolContext(is_owner=True)
    visible_names = {rt.spec.name for rt in reg._iter_visible_tools(ctx)}

    for tool_name in ("meta_skill_assemble", "meta_skill_fill_slots"):
        assert tool_name not in visible_names, (
            f"{tool_name} is visible in the default owner tool catalog; "
            "N1 fix requires exposed_by_default=False so C1 lazy import "
            "does not leak it into normal owner turns."
        )

    # But the tools must still be registered (reachable by name for tool_invoker).
    registered_names = set(reg.list_names())
    assert "meta_skill_assemble" in registered_names
    assert "meta_skill_fill_slots" in registered_names


def test_slot_filler_rejects_yaml_unsafe_strings() -> None:
    """N2: Pydantic validators reject control chars / quotes that would
    break YAML rendering."""
    import pytest as _pytest

    from opensquilla.skills.creator.patterns.schemas import SequentialStep

    # Acceptable
    SequentialStep(id="ok", skill="summarize", task="simple task")

    # Unacceptable: double quote in task
    with _pytest.raises(ValueError):
        SequentialStep(id="ok", skill="summarize", task='save "summary"')

    # Unacceptable: newline in task
    with _pytest.raises(ValueError):
        SequentialStep(id="ok", skill="summarize", task="step 1\nstep 2")

    # Unacceptable: backslash in task
    with _pytest.raises(ValueError):
        SequentialStep(id="ok", skill="summarize", task="path\\to\\file")

    # Unacceptable: double quote in skill name
    with _pytest.raises(ValueError):
        SequentialStep(id="ok", skill='sum"marize', task="simple task")


def test_fill_slots_retry_no_type_error_on_custom_validator_error(monkeypatch) -> None:
    """N4 regression: Pydantic v2 custom-validator errors put a raw ValueError
    object in ctx.error which is not JSON-serializable. The retry path must use
    default=str so json.dumps(exc.errors()) doesn't TypeError before the retry
    LLM call fires.

    Triggers the N2 validator (double-quote in task) on the first response,
    then returns a clean payload on the second call. Asserts no TypeError is
    raised and the final result is the clean payload.
    """
    import json as _json

    from opensquilla.skills.creator import proposer

    clean_payload = _json.dumps({
        "name": "synth-pipeline",
        "description": "Synthetic pipeline that does X then Y. Sample for N4 regression.",
        "meta_priority": 50,
        "triggers": ["synth test"],
        "steps": [
            {"id": "a", "skill": "summarize", "task": "process input", "with_keys": {}},
            {"id": "b", "skill": "memory", "task": "save result", "with_keys": {}},
        ],
    })
    # First response: task contains a double-quote — triggers the N2
    # custom validator on SequentialStep and raises ValidationError whose
    # exc.errors() contains a raw ValueError in ctx.error.
    bad_payload = _json.dumps({
        "name": "synth-pipeline",
        "description": "Synthetic pipeline. Sample for N4 regression.",
        "meta_priority": 50,
        "triggers": ["synth test"],
        "steps": [
            {"id": "a", "skill": "summarize", "task": 'save "summary"', "with_keys": {}},
            {"id": "b", "skill": "memory", "task": "save result", "with_keys": {}},
        ],
    })

    responses = iter([bad_payload, clean_payload])

    def stub_llm(prompt: str, **_kwargs) -> str:
        return next(responses)

    monkeypatch.setattr(proposer, "_call_llm_for_slots", stub_llm)

    # Must not raise TypeError; must return clean payload
    result = proposer.meta_skill_fill_slots(
        pattern_id="p1_sequential",
        history_summary="(no history)",
        user_intent="process docs then save",
    )
    data = _json.loads(result)
    assert data["name"] == "synth-pipeline", f"unexpected result: {data}"


def test_creator_tools_registered_via_meta_invoke_module_import() -> None:
    """N10: importing the meta_invoke soft-path module (agent.py) must also
    ensure creator tools are registered. The lazy import added at the top of
    _run_meta_invoke_streaming fires whenever the method is entered; here we
    verify the underlying registration by importing opensquilla.skills.creator
    directly (the same effect as the lazy import) and asserting the registry
    reflects the tools — mirrors the C1 hard-takeover test but for the
    soft-path entry in agent.py.
    """
    import importlib

    # Simulate what the N10 lazy import does when _run_meta_invoke_streaming fires.
    import opensquilla.skills.creator  # noqa: F401
    importlib.reload(opensquilla.skills.creator)

    from opensquilla.tools.registry import get_default_registry

    reg = get_default_registry()
    names = reg.list_names()
    assert "meta_skill_fill_slots" in names, (
        "N10: meta_skill_fill_slots not registered via soft-path import; "
        f"registered names starting with 'meta': "
        f"{sorted(n for n in names if n.startswith('meta'))}"
    )
    assert "meta_skill_assemble" in names, (
        "N10: meta_skill_assemble not registered via soft-path import"
    )


def test_resolve_provider_config_accepts_empty_api_key(tmp_path, monkeypatch) -> None:
    """N11: _resolve_provider_from_config must return a valid triple when
    provider and model are set but api_key is absent (keyless local providers
    such as ollama / lm_studio). Previously the `and api_key` truthy guard
    returned (None, None, None), causing the resolution to fall through to
    env-var scan and ultimately raise RuntimeError on keyless deployments."""
    config_toml = tmp_path / "opensquilla.toml"
    config_toml.write_text(
        '[llm]\nprovider = "ollama"\nmodel = "llama3"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(config_toml))

    from opensquilla.skills.creator.proposer import _resolve_provider_from_config

    provider, model, api_key = _resolve_provider_from_config()
    assert provider == "ollama", (
        f"N11: expected 'ollama', got {provider!r}; "
        "keyless provider must not be rejected by _resolve_provider_from_config"
    )
    assert model == "llama3"
    assert api_key == ""  # empty string is correct for ollama
