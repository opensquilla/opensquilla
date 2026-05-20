"""Internal tools for meta-skill-creator."""

from __future__ import annotations

from collections.abc import Callable


def meta_skill_fill_slots(
    pattern_id: str, history_summary: str, user_intent: str,
) -> str:
    raise NotImplementedError("Implemented in Task 5")


def meta_skill_assemble(pattern_id: str, slots_json: str) -> str:
    raise NotImplementedError("Implemented in Task 5")


def simulate_meta_resolution(
    skill_md: str, prompt: str, classifier_model: str,
) -> bool:
    """Load skill_md into a tmp SkillLoader, run trigger matching against
    `prompt`, return True if the candidate skill matches.

    For Phase 1, classifier_model is informational only; matching uses the
    same word-boundary regex used by `engine.steps.meta_resolution` (which
    is itself a deterministic substring/word-boundary check, no LLM)."""
    import tempfile
    from pathlib import Path

    from opensquilla.engine.steps.meta_resolution import _trigger_matches
    from opensquilla.skills.loader import SkillLoader

    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "candidate"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        loader = SkillLoader(
            bundled_dir=Path(tmp),
            snapshot_path=Path(tmp) / "snap.json",
        )
        loader.invalidate_cache()
        specs = loader.load_all()
        if not specs:
            return False
        spec = specs[0]
        # IMPORTANT: _trigger_matches requires pre-lowered second arg
        # (meta_resolution.py:32). Pre-lower once here.
        prompt_lower = prompt.lower()
        return any(_trigger_matches(trig, prompt_lower) for trig in spec.triggers)


def run_smoke_gates(
    skill_md: str,
    *,
    fixture_gen_fn: Callable[..., str],
    classifier_model: str,
) -> dict:
    """Run G3 (positive smoke) + G4 (negative smoke).

    `fixture_gen_fn(skill_md, kind, ...)` returns a generated prompt string
    for kind in {"positive", "negative"}. Cross-vendor pinning: caller is
    expected to inject a fixture_gen_fn that uses a DIFFERENT model family
    than `classifier_model` to break LLM-self-confirmation bias.
    """
    positive = fixture_gen_fn(skill_md, "positive")
    g3_matched = simulate_meta_resolution(skill_md, positive, classifier_model)

    negative = fixture_gen_fn(skill_md, "negative")
    g4_matched = simulate_meta_resolution(skill_md, negative, classifier_model)

    return {
        "G3": {
            "passed": g3_matched,
            "positive_fixture": positive,
            "classifier": classifier_model,
        },
        "G4": {
            "passed": not g4_matched,
            "negative_fixture": negative,
            "classifier": classifier_model,
        },
    }


def real_fixture_gen(
    skill_md: str,
    kind: str,
    *,
    llm_chat,
    fixture_gen_model: str,
) -> str:
    """LLM-driven fixture generation. Used inside meta-skill-smoke-test's
    sub-agent. Caller must supply an llm_chat bound to fixture_gen_model
    that is DIFFERENT from the classifier_model.

    Phase 1 ships a deterministic fallback (extract first trigger for
    positive; pull a phrase from another bundle's triggers for negative)
    when llm_chat is None — keeps default-path tests offline.
    """
    if llm_chat is None:
        return _deterministic_fixture(skill_md, kind)
    raise NotImplementedError(
        "real LLM fixture-gen is wired in Step 3.14 with cross-vendor pinning"
    )


def _deterministic_fixture(skill_md: str, kind: str) -> str:
    """Trigger-string based fixture generator for offline tests."""
    import re
    if kind == "positive":
        m = re.search(r"triggers:\s*\n((?:\s*-\s*\"[^\"]+\"\s*\n)+)", skill_md)
        if m:
            first = re.search(r'-\s*"([^"]+)"', m.group(1))
            if first:
                return f"please use {first.group(1)}"
        return "please run this meta-skill"
    if kind == "negative":
        return "what's the weather forecast for tomorrow?"
    raise ValueError(f"Unknown fixture kind: {kind}")
