"""Live multi-model router accuracy harness (Step D.2).

Drives each fixture in ``tests/test_skills/router_fixtures/`` against
multiple real LLM models via OpenRouter, then prints per-model + per-
skill + per-language accuracy.

Maintainer-only; never on the default PR path. Gated by:

* ``@pytest.mark.llm_router_acc`` marker (declared in pyproject).
* ``OPENSQUILLA_RUN_LLM_ROUTER_ACC=1`` explicit opt-in.
* ``OPENROUTER_API_KEY`` env var (loaded from ``~/.env`` if present).

Usage::

    OPENSQUILLA_RUN_LLM_ROUTER_ACC=1 \\
      uv run pytest tests/test_skills/test_meta_router_live.py -v -s \\
      -m llm_router_acc

The harness is **measurement, not gate** — it asserts only that the
total accuracy for each model is ≥ 50 % (a catastrophic-failure floor).
Marginal accuracy regressions show up in the printed summary; we do
not fail the test because cross-model variance is inherent to the
question being asked.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from router_fixtures import ALL_CASES, RouterCase

from opensquilla.engine.types import AgentConfig, AgentEvent
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.executors.llm_classify import run_llm_classify_step
from opensquilla.skills.meta.orchestrator import make_llm_chat_from_provider
from opensquilla.skills.meta.parser import parse_meta_plan

_BUNDLED_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "bundled"
)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Conservative cross-vendor lineup. Cheap-per-token to keep the harness
# affordable; routing is a short prompt so any modern instruct-tuned
# model should clear the catastrophic-failure floor.
_MODELS = [
    "anthropic/claude-3.5-haiku",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-chat",
    "moonshotai/kimi-k2-0905",
]

# Floor: a model that classifies worse than this is broken, not weak.
_MIN_TOTAL_ACCURACY = 0.50

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENSQUILLA_RUN_LLM_ROUTER_ACC") != "1",
    reason="set OPENSQUILLA_RUN_LLM_ROUTER_ACC=1 to run live router accuracy",
)


def _load_home_env_into_environ() -> None:
    """Load ``~/.env`` into os.environ (never overrides existing vars).

    The default candidate is ``Path.home() / ".env"``. When the test is
    invoked as a different OS user than the one that owns the API key
    (e.g. ``sudo``, dev container running as root, CI runners), set
    ``OPENSQUILLA_DEVELOPER_ENV_FILE`` to the absolute path of the
    ``.env`` to consult — that path is read in addition to the home
    default. Existing environment variables are never overwritten.
    """
    candidates: list[Path] = [Path.home() / ".env"]
    extra = os.environ.get("OPENSQUILLA_DEVELOPER_ENV_FILE", "").strip()
    if extra:
        extra_path = Path(extra)
        if extra_path not in candidates:
            candidates.append(extra_path)
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


@pytest.fixture(scope="module")
def _openrouter_key() -> str:
    _load_home_env_into_environ()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not available in ~/.env or environment")
    return key


@pytest.fixture(scope="module")
def _loader(tmp_path_factory: pytest.TempPathFactory) -> SkillLoader:
    snapshot = tmp_path_factory.mktemp("router-live") / "snapshot.json"
    loader = SkillLoader(bundled_dir=_BUNDLED_DIR, snapshot_path=snapshot)
    loader.invalidate_cache()
    loader.load_all()
    return loader


async def _explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
    raise AssertionError("agent_runner must not be called when llm_chat is wired")
    yield  # pragma: no cover


@pytest.mark.llm_router_acc
@pytest.mark.asyncio
@pytest.mark.parametrize("model", _MODELS)
async def test_router_accuracy_per_model(
    _loader: SkillLoader, _openrouter_key: str, model: str,
) -> None:
    """Run every fixture against one model; print per-skill + per-language
    accuracy. Floor-only assertion (>=50 % total) so cross-model variance
    does not break CI; the printed numbers are the actual signal."""

    config = AgentConfig(model_id=model)
    provider = OpenAIProvider(
        api_key=_openrouter_key,
        model=model,
        base_url=_OPENROUTER_BASE,
    )
    llm_chat = make_llm_chat_from_provider(provider=provider, base_config=config)

    by_skill: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [correct, total]
    by_lang: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    failures: list[tuple[RouterCase, str]] = []
    overall_correct = 0
    overall_total = 0

    # Cache the parsed classify step per skill to avoid re-parsing once
    # per fixture.
    classify_cache: dict[str, object] = {}

    for case in ALL_CASES:
        if case.skill not in classify_cache:
            spec = _loader.get_by_name(case.skill)
            assert spec is not None
            plan = parse_meta_plan(spec)
            assert plan is not None
            classify_cache[case.skill] = next(
                s for s in plan.steps if s.kind == "llm_classify"
            )
        classify = classify_cache[case.skill]

        try:
            verdict = await run_llm_classify_step(
                classify,  # type: ignore[arg-type]
                {"user_message": case.user_message},
                {},
                llm_chat=llm_chat,
                agent_runner=_explode_runner,
            )
        except Exception as exc:  # noqa: BLE001
            verdict = f"<error: {type(exc).__name__}: {exc}>"

        correct = verdict == case.expected_choice
        overall_total += 1
        overall_correct += int(correct)
        by_skill[case.skill][1] += 1
        by_skill[case.skill][0] += int(correct)
        by_lang[case.lang][1] += 1
        by_lang[case.lang][0] += int(correct)
        if not correct:
            failures.append((case, verdict))

    # ---- Print structured summary so `pytest -s` users see the result ----
    pct = 100.0 * overall_correct / overall_total if overall_total else 0.0
    print(f"\n\n=== {model} — {overall_correct}/{overall_total} = {pct:.1f}% ===")

    print("\nPer skill:")
    for skill, (c, t) in sorted(by_skill.items()):
        skill_pct = 100.0 * c / t if t else 0.0
        print(f"  {skill}: {c}/{t} = {skill_pct:.1f}%")

    print("\nPer language:")
    for lang, (c, t) in sorted(by_lang.items()):
        lang_pct = 100.0 * c / t if t else 0.0
        print(f"  {lang}: {c}/{t} = {lang_pct:.1f}%")

    if failures:
        print(f"\nFailures ({len(failures)}):")
        for case, verdict in failures:
            print(
                f"  {case.skill}/{case.note} (lang={case.lang}): "
                f"expected={case.expected_choice!r}, got={verdict!r}",
            )
            print(f"    input: {case.user_message[:80]}")

    assert overall_correct >= int(_MIN_TOTAL_ACCURACY * overall_total), (
        f"model {model!r} fell below the catastrophic-failure floor "
        f"({_MIN_TOTAL_ACCURACY * 100:.0f}%): "
        f"{overall_correct}/{overall_total}"
    )
