"""The thumb -> memory -> consolidated -> projection round-trip.

The profile no longer accumulates anything of its own; it is a projection over
what Dream consolidated. The load-bearing risk is the round-trip: a thumb is
transcribed to a memory line, Dream's LLM promotion may reword it, and the
projection must still recover the exact model id and its direction. These tests
pin both ends against the *real* ``classify_signal`` so the transcription verbs
cannot drift out of the buckets Dream promotes on.
"""

from __future__ import annotations

from opensquilla.memory.dream.candidates import classify_signal
from opensquilla.squilla_router.self_learning.preference_projection import (
    project_history,
    transcribe_thumb,
)

_MODEL = "anthropic/claude-sonnet-4-5"
_OTHER = "openai/gpt-5"


def test_an_up_thumb_transcribes_to_a_line_dream_calls_positive() -> None:
    line = transcribe_thumb(_MODEL, "up")
    assert line is not None
    # The transcription verb must land in Dream's positive bucket, or the line
    # would never be promoted as a preference.
    assert classify_signal(line) == "positive"
    assert project_history(line)["positive_model_ids"] == [_MODEL]


def test_a_down_thumb_transcribes_to_a_line_dream_calls_correction() -> None:
    line = transcribe_thumb(_MODEL, "down")
    assert line is not None
    assert classify_signal(line) == "correction"
    assert project_history(line)["negative_model_ids"] == [_MODEL]


def test_the_id_survives_an_llm_rewording_that_keeps_the_marker() -> None:
    """Dream promotes via an LLM patch; only the backticked marker is contracted
    to survive. Prose around it may change freely."""
    reworded = (
        "## Routing preferences\n"
        f"- The operator prefers routing to `model:{_MODEL}` for coding tasks\n"
        f"- We do not route to `model:{_OTHER}` after repeated failures\n"
    )
    history = project_history(reworded)
    assert history["positive_model_ids"] == [_MODEL]
    assert history["negative_model_ids"] == [_OTHER]
    assert history["feedback_count"] == 2


def test_neutral_and_unresolvable_thumbs_say_nothing() -> None:
    assert transcribe_thumb(_MODEL, "neutral") is None
    assert transcribe_thumb(None, "up") is None
    assert transcribe_thumb("   ", "up") is None
    # A token outside the model-id alphabet is not a model id.
    assert transcribe_thumb("has spaces", "up") is None


def test_a_model_asserted_both_ways_lands_in_neither_list() -> None:
    text = (
        f"- prefers routing to `model:{_MODEL}`\n"
        f"- do not route to `model:{_MODEL}`\n"
    )
    history = project_history(text)
    assert history["positive_model_ids"] == []
    assert history["negative_model_ids"] == []
    # Both statements still count toward confidence.
    assert history["feedback_count"] == 2


def test_avoid_wins_a_mixed_line() -> None:
    """A single line that says do-not-prefer is an avoidance, not a preference."""
    line = f"- do not prefer `model:{_MODEL}`"
    history = project_history(line)
    assert history["negative_model_ids"] == [_MODEL]
    assert history["positive_model_ids"] == []


def test_lines_without_the_marker_are_ignored() -> None:
    text = (
        "## Long-Term Memory\n"
        "- The user prefers dark mode in the editor\n"
        "- Remember that the build uses uv\n"
    )
    history = project_history(text)
    assert history == {
        "positive_model_ids": [],
        "negative_model_ids": [],
        "feedback_count": 0,
    }


def test_empty_and_garbage_memory_never_raises() -> None:
    for text in ("", "   ", "not markdown at all", "`model:` empty id"):
        history = project_history(text)
        assert history["feedback_count"] == 0
