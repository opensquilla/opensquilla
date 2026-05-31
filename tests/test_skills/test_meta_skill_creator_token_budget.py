"""Token budget: end-to-end input ≤ 25k tokens, output ≤ 4k tokens."""

from __future__ import annotations

import json

from opensquilla.skills.creator import proposer


class _RecordingChat:
    def __init__(self) -> None:
        self.input_chars: int = 0
        self.output_chars: int = 0

    def __call__(self, prompt: str, **_kwargs) -> str:
        self.input_chars += len(prompt)
        response = json.dumps({
            "name": "synth-budget", "description": "x" * 50,
            "meta_priority": 50, "triggers": ["t"],
            "steps": [
                {"id": "a", "skill": "summarize", "task": "t", "with_keys": {}},
                {"id": "b", "skill": "memory", "task": "t", "with_keys": {}},
            ],
        })
        self.output_chars += len(response)
        return response


CHARS_PER_TOKEN = 4
INPUT_TOKEN_BUDGET = 25_000
OUTPUT_TOKEN_BUDGET = 4_000


def test_total_pipeline_within_token_budget(monkeypatch) -> None:
    recorder = _RecordingChat()
    # _RecordingChat receives the real base_prompt assembled by
    # meta_skill_fill_slots (catalog + history + intent), so input_chars
    # reflects actual prompt construction — not a canned constant.
    # NOTE: _build_catalog_summary() reads from a tempdir snapshot; if
    # the snapshot is stale or empty the catalog section shrinks and
    # this budget check becomes optimistic. Fresh snapshot is built on
    # first SkillLoader.load_all() call.
    monkeypatch.setattr(proposer, "_call_llm_for_slots", recorder)

    proposer.meta_skill_fill_slots(
        pattern_id="p1_sequential",
        history_summary="(stub history)",
        user_intent="process docs then save",
    )
    proposer.meta_skill_fill_slots(
        pattern_id="p1_sequential",
        history_summary="(stub history; pick_pattern sim)",
        user_intent="(short)",
    )

    input_tokens = recorder.input_chars // CHARS_PER_TOKEN
    output_tokens = recorder.output_chars // CHARS_PER_TOKEN
    assert input_tokens <= INPUT_TOKEN_BUDGET, (
        f"input tokens {input_tokens} > {INPUT_TOKEN_BUDGET}"
    )
    assert output_tokens <= OUTPUT_TOKEN_BUDGET, (
        f"output tokens {output_tokens} > {OUTPUT_TOKEN_BUDGET}"
    )
