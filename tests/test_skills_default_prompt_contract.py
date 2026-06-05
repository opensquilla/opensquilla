from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import opensquilla.engine.steps.skills_filter as skills_filter_step
from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.steps.skills_filter import filter_skills
from opensquilla.gateway.config import GatewayConfig
from opensquilla.skills.eligibility import EligibilityContext
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.semantic_guards import semantic_meta_skill_allowed

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
AUDIO_DEFAULTS = {
    "advanced-dubbing-studio",
    "music-and-singing-studio",
    "voice-clone-lab",
    "voice-conversion-studio",
    "voiceover-studio",
}
DEFAULTS = {
    "ai-video-script",
    "cron",
    "deep-research",
    "docx",
    "git-diff",
    "github",
    "history-explorer",
    "html-to-pdf",
    "http-fetch",
    "latex-compile",
    "memory",
    "meta-competitive-intel",
    "meta-daily-operator-brief",
    "meta-document-to-decision",
    "meta-job-search-pipeline",
    "meta-kid-project-planner",
    "meta-paper-write",
    "meta-short-drama",
    "meta-skill-creator",
    "meta-web-research-to-report",
    "multi-search-engine",
    "nano-banana-pro",
    "nano-pdf",
    "paper-abstract-author",
    "paper-citation-planner",
    "paper-experiment-stub",
    "paper-outline-author",
    "paper-plot-stub",
    "paper-preference-planner",
    "paper-refbib-stub",
    "paper-revision-author",
    "paper-section-author",
    "paper-source-curator",
    "pdf-toolkit",
    "pptx",
    "seedance-2-prompt",
    "skill-creator",
    "srt-from-script",
    "sub-agent",
    "subtitle-burner",
    "summarize",
    "text-file-read",
    "title-card-image",
    "tmux",
    "video-merger",
    "video-still-animator",
    "weather",
    "xlsx",
} | AUDIO_DEFAULTS
PROMPT_DEFAULTS_WITHOUT_AUDIO_TOOLS = DEFAULTS - AUDIO_DEFAULTS
INTERNAL_HELPERS = {
    "skill-creator-linter",
    "skill-creator-proposals",
    "skill-creator-smoke-test",
    "stack-trace-generic-probe",
    "stack-trace-go-probe",
    "stack-trace-js-probe",
    "stack-trace-python-probe",
    "stack-trace-rust-probe",
}
STABLE_META_BOUNDARY_CASES = [
    (
        "meta-competitive-intel",
        "Build a competitive intelligence brief for these two named competitors.",
        (
            "inception labs,创始团队和核心员工有哪些？现在估值，"
            "核心技术路线和进展是啥？然后每一轮交割大概节奏和估值股东等信息列出来。"
        ),
    ),
    (
        "meta-daily-operator-brief",
        "Create my daily operating brief from calendar, tasks, weather, and open loops.",
        "Today plan: remind me to call Alex at 4pm.",
    ),
    (
        "meta-document-to-decision",
        "Analyze this contract excerpt for a decision: sign, reject, or negotiate.",
        "Summarize this contract excerpt generally; I am not deciding whether to sign.",
    ),
    (
        "meta-job-search-pipeline",
        "Tailor my resume to this job using the pasted JD and build a job application pack.",
        "Give me career advice and better resume tips in general, without a target role.",
    ),
    (
        "meta-kid-project-planner",
        "Help my kid build a child science fair school project with safe materials.",
        "帮我设计一个成人手工 logo 展示方案，不是孩子作业。",
    ),
    (
        "meta-paper-write",
        "Draft a paper as a LaTeX manuscript with citations and experiment placeholders.",
        "Summarize this paper and list the main claims; do not draft a manuscript.",
    ),
    (
        "meta-short-drama",
        "Generate a short drama from this topic and render the shot list to final MP4.",
        "Write a short script idea, not a video or MP4.",
    ),
    (
        "meta-skill-creator",
        "Create a meta-skill that orchestrates existing skills for PDF digest workflows.",
        "Create a normal standalone skill, not a meta-skill.",
    ),
    (
        "meta-web-research-to-report",
        "Write a cited research report with sources, key findings, and risks.",
        "Who founded Inception Labs? Just answer briefly, no report.",
    ),
]


def _ctx(
    loader: SkillLoader,
    tools: set[str] | None = None,
    *,
    message: str = "please summarize weather and github state",
    skills_config: SimpleNamespace | None = None,
) -> TurnContext:
    tool_defs = [
        SimpleNamespace(name=name)
        for name in (
            tools
            or {
                "background_process",
                "cron",
                "exec_command",
                "memory_get",
                "memory_save",
                "memory_search",
                "process",
            }
        )
    ]
    if skills_config is None:
        skills_config = SimpleNamespace(
            filter_enabled=False,
            max_skills_prompt_chars=100_000,
            injection_mode="system",
        )
    return TurnContext(
        message=message,
        session_key="agent:main:webchat:default",
        config=SimpleNamespace(
            tools=SimpleNamespace(profile="standard"),
            skills=skills_config,
        ),
        provider=None,
        model="test-model",
        tool_defs=tool_defs,
        system_prompt="base",
        metadata={"skill_loader": loader},
    )


def test_bundled_directory_only_contains_retained_default_skills() -> None:
    bundled_names = {
        path.name
        for path in BUNDLED.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }

    assert bundled_names == DEFAULTS | INTERNAL_HELPERS


def test_skill_filter_defaults_are_release_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_SKILLS_FILTER_ENABLED", raising=False)
    monkeypatch.delenv("OPENSQUILLA_SKILLS_FILTER_STRATEGY", raising=False)

    cfg = GatewayConfig()

    assert cfg.skills.filter_enabled is False
    assert cfg.skills.filter_strategy == "lexical"


@pytest.mark.parametrize(
    ("skill_name", "positive_prompt", "negative_prompt"),
    STABLE_META_BOUNDARY_CASES,
)
def test_semantic_guards_cover_stable_bundled_meta_skill_boundaries(
    skill_name: str,
    positive_prompt: str,
    negative_prompt: str,
) -> None:
    assert semantic_meta_skill_allowed(skill_name, positive_prompt)
    assert not semantic_meta_skill_allowed(skill_name, negative_prompt)


@pytest.mark.asyncio
async def test_default_prompt_only_injects_retained_bundled_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        skills_filter_step,
        "_elig_ctx",
        EligibilityContext(
            os_name="linux",
            has_bin_cache={
                "bibtex": True,
                "codex": True,
                "curl": True,
                "ffmpeg": True,
                "ffprobe": True,
                "xelatex": True,
                "nano-pdf": True,
                "python": True,
                "python3": True,
                "tmux": True,
            },
        ),
    )
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")

    ctx = await filter_skills(_ctx(loader))

    prompt = ctx.system_prompt[1]
    for name in PROMPT_DEFAULTS_WITHOUT_AUDIO_TOOLS:
        assert f"<name>{name}</name>" in prompt
    for name in AUDIO_DEFAULTS:
        assert f"<name>{name}</name>" not in prompt
    for name in INTERNAL_HELPERS:
        assert f"<name>{name}</name>" not in prompt
    assert "<name>healthcheck</name>" not in prompt


@pytest.mark.asyncio
async def test_default_prompt_prefers_matching_meta_skills_over_direct_answers(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")

    ctx = await filter_skills(_ctx(loader))

    prompt = ctx.system_prompt[1]
    assert "When a kind=\"meta\" entry clearly matches" in prompt
    assert "prefer `meta_invoke(name=\"<name>\")` over answering directly" in prompt
    assert "Do not call `skill_view` for kind=\"meta\" entries" in prompt
    assert "multi-skill orchestration" in prompt


@pytest.mark.asyncio
async def test_hybrid_filter_hides_competitive_intel_for_single_company_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    prompt = (
        "inception labs,创始团队和核心员工有哪些？现在估值，"
        "核心技术路线和进展是啥？然后每一轮交割大概节奏和"
        "估值股东等信息列出来。"
    )

    class FakeRetriever:
        def retrieve(self, skills, query: str, top_k: int = 5):
            assert query == prompt
            by_name = {s.name: s for s in skills}
            return [
                by_name["meta-competitive-intel"],
                by_name["meta-web-research-to-report"],
            ][:top_k]

    monkeypatch.setattr(skills_filter_step, "_get_retriever", lambda _cfg: FakeRetriever())

    ctx = await filter_skills(
        _ctx(
            loader,
            message=prompt,
            skills_config=SimpleNamespace(
                filter_enabled=True,
                filter_top_k=5,
                filter_strategy="hybrid",
                filter_lexical_top_n=20,
                filter_semantic_top_n=20,
                filter_rrf_k=60,
                filter_embedding_model="BAAI/bge-small-zh-v1.5",
                max_skills_prompt_chars=100_000,
                injection_mode="system",
            ),
        )
    )

    assert "meta-competitive-intel" not in ctx.metadata["filtered_skill_ids"]
    assert "meta-web-research-to-report" in ctx.metadata["filtered_skill_ids"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("skill_name", "prompt"),
    [
        (
            "meta-daily-operator-brief",
            "Today plan: remind me to call Alex at 4pm.",
        ),
        (
            "meta-short-drama",
            "Write a short script idea, not a video or MP4.",
        ),
        (
            "meta-kid-project-planner",
            "帮我设计一个成人手工 logo 展示方案，不是孩子作业。",
        ),
    ],
)
async def test_hybrid_filter_hides_neighboring_meta_workflows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skill_name: str,
    prompt: str,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")

    class FakeRetriever:
        def retrieve(self, skills, query: str, top_k: int = 5):
            assert query == prompt
            by_name = {s.name: s for s in skills}
            return [by_name[skill_name]][:top_k]

    monkeypatch.setattr(skills_filter_step, "_get_retriever", lambda _cfg: FakeRetriever())

    ctx = await filter_skills(
        _ctx(
            loader,
            message=prompt,
            skills_config=SimpleNamespace(
                filter_enabled=True,
                filter_top_k=5,
                filter_strategy="hybrid",
                filter_lexical_top_n=20,
                filter_semantic_top_n=20,
                filter_rrf_k=60,
                filter_embedding_model="BAAI/bge-small-zh-v1.5",
                max_skills_prompt_chars=100_000,
                injection_mode="system",
            ),
        )
    )

    assert skill_name not in ctx.metadata["filtered_skill_ids"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("skill_name", "positive_prompt", "negative_prompt"),
    STABLE_META_BOUNDARY_CASES,
)
async def test_hybrid_filter_applies_stable_meta_boundary_guards_both_directions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skill_name: str,
    positive_prompt: str,
    negative_prompt: str,
) -> None:
    monkeypatch.setattr(
        skills_filter_step,
        "_elig_ctx",
        EligibilityContext(
            os_name="linux",
            has_bin_cache={
                "bibtex": True,
                "codex": True,
                "curl": True,
                "ffmpeg": True,
                "ffprobe": True,
                "xelatex": True,
                "nano-pdf": True,
                "python": True,
                "python3": True,
                "tmux": True,
            },
        ),
    )
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")

    class FakeRetriever:
        prompt = positive_prompt

        def retrieve(self, skills, query: str, top_k: int = 5):
            assert query == self.prompt
            by_name = {s.name: s for s in skills}
            return [by_name[skill_name]][:top_k]

    retriever = FakeRetriever()
    monkeypatch.setattr(skills_filter_step, "_get_retriever", lambda _cfg: retriever)

    def skills_config() -> SimpleNamespace:
        return SimpleNamespace(
            filter_enabled=True,
            filter_top_k=5,
            filter_strategy="hybrid",
            filter_lexical_top_n=20,
            filter_semantic_top_n=20,
            filter_rrf_k=60,
            filter_embedding_model="BAAI/bge-small-zh-v1.5",
            max_skills_prompt_chars=100_000,
            injection_mode="system",
        )

    positive_ctx = await filter_skills(
        _ctx(
            loader,
            message=positive_prompt,
            skills_config=skills_config(),
        )
    )

    assert skill_name in positive_ctx.metadata["filtered_skill_ids"]

    retriever.prompt = negative_prompt
    negative_ctx = await filter_skills(
        _ctx(
            loader,
            message=negative_prompt,
            skills_config=skills_config(),
        )
    )

    assert skill_name not in negative_ctx.metadata["filtered_skill_ids"]


@pytest.mark.asyncio
async def test_meta_skill_disabled_hides_meta_prompt_without_hiding_normal_skills(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    ctx = _ctx(loader)
    ctx.config.meta_skill = SimpleNamespace(enabled=False)

    ctx = await filter_skills(ctx)
    prompt = ctx.system_prompt[1]

    assert "When a kind=\"meta\" entry clearly matches" not in prompt
    assert "prefer `meta_invoke(name=\"<name>\")` over answering directly" not in prompt
    assert "multi-skill orchestration" not in prompt
    assert "<available_skills>" in prompt


@pytest.mark.asyncio
async def test_internal_meta_helpers_stay_loadable_but_hidden_from_model(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")

    ctx = await filter_skills(_ctx(loader))
    prompt = ctx.system_prompt[1]

    for name in INTERNAL_HELPERS:
        skill = loader.get_by_name(name)
        assert skill is not None
        assert skill.user_invocable is False
        assert skill.disable_model_invocation is True
        assert name not in {s.name for s in loader.get_user_invocable()}
        assert f"<name>{name}</name>" not in prompt


@pytest.mark.asyncio
async def test_allowlist_does_not_hide_managed_or_workspace_skills(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    skill_dir = managed / "custom-community"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: custom-community\n"
        "description: Use when testing managed skills.\n"
        "---\n\n# Custom\n",
        encoding="utf-8",
    )
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        managed_dir=managed,
        snapshot_path=tmp_path / "snapshot.json",
    )

    ctx = await filter_skills(_ctx(loader))

    assert "<name>custom-community</name>" in ctx.system_prompt[1]


@pytest.mark.asyncio
async def test_lexical_skill_filter_is_opt_in_and_dependency_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    for name, description, triggers in (
        ("weather-local", "Fetch weather forecasts.", "[weather, forecast]"),
        ("github-local", "Inspect GitHub pull requests.", "[github, pull request]"),
    ):
        skill_dir = workspace / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"triggers: {triggers}\n"
            "---\n\n"
            f"# {name}\n",
            encoding="utf-8",
        )

    def fail_get_embedder(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("lexical skill filtering must not load embeddings")

    monkeypatch.setattr(skills_filter_step, "_retriever", None)
    monkeypatch.setattr("opensquilla.skills.retrieval.embedder.get_embedder", fail_get_embedder)
    loader = SkillLoader(workspace_dir=workspace, snapshot_path=tmp_path / "snapshot.json")

    ctx = await filter_skills(
        _ctx(
            loader,
            message="please check the weather forecast",
            skills_config=SimpleNamespace(
                filter_enabled=True,
                filter_top_k=1,
                filter_strategy="lexical",
                filter_lexical_top_n=20,
                filter_semantic_top_n=20,
                filter_rrf_k=60,
                filter_embedding_model="BAAI/bge-small-zh-v1.5",
                max_skills_prompt_chars=100_000,
                injection_mode="system",
            ),
        )
    )

    prompt = ctx.system_prompt[1]
    assert "<name>weather-local</name>" in prompt
    assert "<name>github-local</name>" not in prompt
    assert ctx.metadata["filtered_skill_ids"] == ["weather-local"]
    assert ctx.metadata["skill_count"] == 1


def test_workspace_overrides_managed_and_bundled_precedence(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    workspace = tmp_path / "workspace"
    for root, desc in ((managed, "managed desc"), (workspace, "workspace desc")):
        skill_dir = root / "github"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: github\ndescription: {desc}\n---\n\n# {desc}\n",
            encoding="utf-8",
        )

    loader = SkillLoader(
        bundled_dir=BUNDLED,
        managed_dir=managed,
        workspace_dir=workspace,
        snapshot_path=tmp_path / "snapshot.json",
    )

    skill = loader.get_by_name("github")

    assert skill is not None
    assert skill.description == "workspace desc"


@pytest.mark.asyncio
async def test_disable_model_invocation_hides_from_prompt_but_not_loader(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    skill_dir = workspace / "hidden-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: hidden-skill\n"
        "description: Use when hidden testing.\n"
        "disable-model-invocation: true\n"
        "---\n\n# Hidden\n",
        encoding="utf-8",
    )
    loader = SkillLoader(
        bundled_dir=BUNDLED,
        workspace_dir=workspace,
        snapshot_path=tmp_path / "snapshot.json",
    )

    skill = loader.get_by_name("hidden-skill")
    ctx = await filter_skills(_ctx(loader))

    assert skill is not None
    assert skill.content == "# Hidden"
    assert "<name>hidden-skill</name>" not in ctx.system_prompt[1]


def test_retained_default_skills_are_parseable_and_not_disabled(tmp_path: Path) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    skills = {skill.name: skill for skill in loader.load_all()}

    for name in DEFAULTS:
        assert name in skills
        assert skills[name].disable_model_invocation is False
        assert skills[name].description
