"""meta.run RPC: stamps a one-shot pending /meta launch for the surface.

The handler only STAMPS a pending launch (the surface starts the turn
later); it validates the name against loaded meta-skills and respects the
master ``meta_skill.enabled`` flag. The pipeline step ``meta_command_launch``
is what later turns the stamp into ``ctx.metadata["meta_launch"]``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.engine.steps.meta_command import (
    meta_command_launch,
    pending_meta_launch_peek,
    pending_meta_launch_pop,
    pending_meta_launch_promote,
)
from opensquilla.gateway.rpc.registry import RpcContext, RpcHandlerError
from opensquilla.gateway.rpc_meta_runs import _handle_meta_run
from opensquilla.gateway.scopes import METHOD_SCOPES, WRITE_SCOPE
from opensquilla.session.manager import SessionManager
from opensquilla.session.storage import SessionStorage
from opensquilla.session.turn_context import turn_context_scope
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.types import (
    SkillPlatformMeta,
    SkillRequires,
    SkillSpec,
)
from tests.test_engine.test_runtime_meta_invoke_surfacing import _make_loader_with_meta


def _drain(session_key: str) -> None:
    """Clear any residual pending launch so each test starts clean."""
    pending_meta_launch_pop(session_key)


def _enabled_cfg(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(meta_skill=SimpleNamespace(enabled=enabled, auto_trigger=False))


def _openrouter_cfg(*, api_key: str = "", api_key_env: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        meta_skill=SimpleNamespace(enabled=True, auto_trigger=False),
        llm=SimpleNamespace(
            provider="openrouter",
            api_key=api_key,
            api_key_env=api_key_env,
        ),
    )


class _ShortDramaProviderLoader:
    def __init__(self, tmp_path: Path) -> None:
        bundled = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "opensquilla"
            / "skills"
            / "bundled"
        )
        loader = SkillLoader(
            bundled_dir=bundled,
            snapshot_path=tmp_path / "short-drama-provider-snapshot.json",
        )
        self._specs = loader.load_all()
        for spec in self._specs:
            # Keep this RPC test focused on provider readiness while retaining
            # the exact bundled parent plan used by the capability trust gate.
            spec.metadata = SkillPlatformMeta()
        image = self.get_by_name("nano-banana-pro")
        video = self.get_by_name("seedance-2-prompt")
        assert image is not None
        assert video is not None
        image.metadata = SkillPlatformMeta(
            requires=SkillRequires(env_any=["OPENROUTER_API_KEY"])
        )
        video.metadata = SkillPlatformMeta(
            requires=SkillRequires(env_any=["OPENROUTER_API_KEY", "ARK_API_KEY"])
        )

    def load_all(self) -> list[SkillSpec]:
        return list(self._specs)

    def get_by_name(self, name: str) -> SkillSpec | None:
        return {spec.name: spec for spec in self.load_all()}.get(name)


def test_meta_run_scope_contract() -> None:
    assert METHOD_SCOPES["meta.run"] == WRITE_SCOPE


def test_meta_run_valid_invokable_skill_stamps_launch(tmp_path: Path) -> None:
    _drain("sess-run-1")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "sessionKey": "sess-run-1"}, ctx)
    )

    assert payload == {"ok": True, "name": "meta-tiny", "sessionKey": "sess-run-1"}
    # Store was stamped — the next turn would pop this exact name.
    assert pending_meta_launch_pop("sess-run-1") == "meta-tiny"


@pytest.mark.asyncio
async def test_meta_run_identified_launch_is_durable_across_gateway_reopen(
    tmp_path: Path,
) -> None:
    session_key = "agent:main:webchat:durable-meta-run"
    request_id = "durable-meta-run-request"
    db_path = tmp_path / "sessions.db"
    storage = await SessionStorage.open(str(db_path))
    manager = SessionManager(storage, inject_time_prefix=False)
    await manager.create(session_key, agent_id="main")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(
        conn_id="test",
        config=_enabled_cfg(),
        skill_loader=loader,
        session_manager=manager,
    )
    try:
        first = await _handle_meta_run(
            {
                "name": "meta-tiny",
                "sessionKey": session_key,
                "clientRequestId": request_id,
            },
            ctx,
        )
        assert first["replayed"] is False
        assert pending_meta_launch_peek(
            session_key,
            client_request_id=request_id,
        ) is None
    finally:
        await storage.close()

    reopened = await SessionStorage.open(str(db_path))
    try:
        intent = await reopened.get_meta_control_intent(
            session_key=session_key,
            control_kind="manual",
            correlation_id=f"request:{request_id}",
        )
        assert intent is not None
        assert intent.meta_skill_name == "meta-tiny"
        assert intent.status == "staged"

        reopened_manager = SessionManager(reopened, inject_time_prefix=False)
        replayed = await _handle_meta_run(
            {
                "name": "meta-tiny",
                "sessionKey": session_key,
                "clientRequestId": request_id,
            },
            RpcContext(
                conn_id="test-reopened",
                config=_enabled_cfg(),
                    skill_loader=loader,
                session_manager=reopened_manager,
            ),
        )
        assert replayed["replayed"] is True
    finally:
        await reopened.close()


def test_meta_run_client_request_id_is_idempotent_after_launch_is_consumed(
    tmp_path: Path,
) -> None:
    session_key = "sess-run-cross-tab"
    client_request_id = "meta-provider-handoff-cross-tab"
    _drain(session_key)
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    first = asyncio.run(
        _handle_meta_run(
            {
                "name": "meta-tiny",
                "sessionKey": session_key,
                "clientRequestId": client_request_id,
            },
            ctx,
        )
    )
    assert first == {
        "ok": True,
        "name": "meta-tiny",
        "sessionKey": session_key,
        "clientRequestId": client_request_id,
        "replayed": False,
    }

    launch_turn = SimpleNamespace(
        session_key=session_key,
        message="/meta meta-tiny",
        semantic_message="/meta meta-tiny",
        metadata={},
    )
    assert (
        pending_meta_launch_promote(
            session_key,
            client_request_id=client_request_id,
            message=launch_turn.message,
        )
        == "promoted"
    )
    async def consume_launch() -> None:
        with turn_context_scope({"client_request_id": client_request_id}):
            await meta_command_launch(launch_turn)

    asyncio.run(consume_launch())
    assert launch_turn.metadata["meta_launch"] == {"name": "meta-tiny"}
    assert pending_meta_launch_peek(session_key) is None

    # A late second-tab meta.run uses the same durable request identity as its
    # duplicate chat.send. It succeeds idempotently without leaving a marker
    # that the already-deduplicated chat.send would never consume.
    replay = asyncio.run(
        _handle_meta_run(
            {
                "name": "meta-tiny",
                "sessionKey": session_key,
                "clientRequestId": client_request_id,
            },
            ctx,
        )
    )
    assert replay == {**first, "replayed": True}
    assert pending_meta_launch_peek(session_key) is None


@pytest.mark.parametrize(
    "client_request_id",
    ["", "   ", 42, "x" * 257],
)
def test_meta_run_rejects_invalid_client_request_id(
    tmp_path: Path,
    client_request_id: object,
) -> None:
    session_key = "sess-run-invalid-request-id"
    _drain(session_key)
    ctx = RpcContext(
        conn_id="test",
        config=_enabled_cfg(),
        skill_loader=_make_loader_with_meta(tmp_path),
    )

    with pytest.raises(Exception, match="clientRequestId"):
        asyncio.run(
            _handle_meta_run(
                {
                    "name": "meta-tiny",
                    "sessionKey": session_key,
                    "clientRequestId": client_request_id,
                },
                ctx,
            )
        )
    assert pending_meta_launch_peek(session_key) is None


def test_meta_run_pending_capacity_is_retryable_and_not_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = RpcContext(
        conn_id="test",
        config=_enabled_cfg(),
        skill_loader=_make_loader_with_meta(tmp_path),
    )
    monkeypatch.setattr(
        "opensquilla.gateway.rpc_meta_runs.pending_meta_launch_put",
        lambda *_args, **_kwargs: "capacity",
    )

    with pytest.raises(RpcHandlerError) as raised:
        asyncio.run(
            _handle_meta_run(
                {
                    "name": "meta-tiny",
                    "sessionKey": "sess-run-capacity",
                    "clientRequestId": "capacity-request",
                },
                ctx,
            )
        )

    assert raised.value.code == "META_LAUNCH_BUSY"
    assert raised.value.retryable is True
    assert raised.value.retry_after_ms == 1000
    assert raised.value.accepted is False


def test_meta_run_accepts_key_alias(tmp_path: Path) -> None:
    _drain("sess-run-alias")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "key": "sess-run-alias"}, ctx)
    )

    assert payload["ok"] is True
    assert payload["sessionKey"] == "sess-run-alias"
    assert pending_meta_launch_pop("sess-run-alias") == "meta-tiny"


def test_meta_run_uses_only_first_name_token(tmp_path: Path) -> None:
    _drain("sess-run-request")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run(
            {
                "name": "meta-tiny -- Write a ten-page paper",
                "sessionKey": "sess-run-request",
            },
            ctx,
        )
    )

    assert payload["ok"] is True
    assert payload["name"] == "meta-tiny"
    assert pending_meta_launch_pop("sess-run-request") == "meta-tiny"


def test_meta_run_unknown_name_refused_and_not_stamped(tmp_path: Path) -> None:
    _drain("sess-run-2")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "nope-skill", "sessionKey": "sess-run-2"}, ctx)
    )

    assert payload["ok"] is False
    assert "nope-skill" in payload["error"]
    assert pending_meta_launch_pop("sess-run-2") is None


def test_meta_run_disable_model_invocation_refused_and_not_stamped(tmp_path: Path) -> None:
    _drain("sess-run-3")
    loader = _make_loader_with_meta(tmp_path, disable_model_invocation=True)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "sessionKey": "sess-run-3"}, ctx)
    )

    assert payload["ok"] is False
    assert "meta-tiny" in payload["error"]
    assert pending_meta_launch_pop("sess-run-3") is None


def test_meta_run_disabled_flag_refused_and_not_stamped(tmp_path: Path) -> None:
    _drain("sess-run-4")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(
        conn_id="test",
        config={"meta_skill": {"enabled": False}},
        skill_loader=loader,
    )

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "sessionKey": "sess-run-4"}, ctx)
    )

    assert payload["ok"] is False
    assert payload.get("disabled") is True
    assert pending_meta_launch_pop("sess-run-4") is None


def test_meta_run_missing_dependency_refused_before_launch(tmp_path: Path) -> None:
    _drain("sess-run-setup")
    loader = _make_loader_with_meta(tmp_path)
    spec = loader.get_by_name("meta-tiny")
    assert spec is not None
    spec.metadata = SkillPlatformMeta(
        requires=SkillRequires(bins=["opensquilla-definitely-missing-binary"])
    )
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run(
            {"name": "meta-tiny", "sessionKey": "sess-run-setup"}, ctx
        )
    )

    assert payload["ok"] is False
    assert payload["code"] == "META_SKILL_SETUP_REQUIRED"
    assert payload["setup_required"] is True
    assert payload["readiness"]["missing_bins"] == [
        "opensquilla-definitely-missing-binary"
    ]
    assert pending_meta_launch_pop("sess-run-setup") is None


def test_short_drama_missing_provider_returns_manual_action_without_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_key = "sess-run-short-drama-provider"
    _drain(session_key)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setattr(
        "opensquilla.skills.meta.readiness.is_skill_available_live",
        lambda _name: True,
    )
    config = SimpleNamespace(
        meta_skill=SimpleNamespace(enabled=True, auto_trigger=False),
        llm=SimpleNamespace(
            provider="tokenrhythm",
            model="deepseek-v4-pro",
            api_key="synthetic-primary-only-key",
            api_key_env="",
            base_url="https://tokenrhythm.studio/v1",
            proxy="",
        ),
        llm_profiles={},
    )
    ctx = RpcContext(
        conn_id="test",
        config=config,
        skill_loader=_ShortDramaProviderLoader(tmp_path),
    )

    payload = asyncio.run(
        _handle_meta_run(
            {"name": "meta-short-drama", "sessionKey": session_key},
            ctx,
        )
    )

    assert payload["code"] == "META_SKILL_SETUP_REQUIRED"
    assert payload["readiness"]["manual_setup_actions"] == [
        {
            "id": "provider:openrouter",
            "kind": "provider_connection",
            "provider_id": "openrouter",
            "capability_ids": ["image.generate.reference", "video.generate"],
            "reason_code": "missing_credential",
            "label": "OpenRouter",
            "recommended": True,
            "available": True,
            "reason": "A provider credential is required.",
        }
    ]
    assert "synthetic-primary-only-key" not in repr(payload)
    assert pending_meta_launch_pop(session_key) is None


def test_short_drama_launch_accepts_secondary_openrouter_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_key = "sess-run-short-drama-secondary"
    _drain(session_key)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "opensquilla.skills.meta.readiness.is_skill_available_live",
        lambda _name: True,
    )
    secret = "synthetic-secondary-profile-key"
    config = SimpleNamespace(
        meta_skill=SimpleNamespace(enabled=True, auto_trigger=False),
        llm=SimpleNamespace(
            provider="tokenrhythm",
            model="deepseek-v4-pro",
            api_key="synthetic-primary-key",
            api_key_env="",
            base_url="https://tokenrhythm.studio/v1",
            proxy="",
        ),
        llm_profiles={
            "openrouter": SimpleNamespace(
                model="bytedance/seedance-2.0",
                api_key=secret,
                api_key_env="",
                api_key_env_pool=[],
                base_url="https://openrouter.ai/api/v1",
                proxy="",
            )
        },
    )
    ctx = RpcContext(
        conn_id="test",
        config=config,
        skill_loader=_ShortDramaProviderLoader(tmp_path),
    )

    payload = asyncio.run(
        _handle_meta_run(
            {"name": "meta-short-drama", "sessionKey": session_key},
            ctx,
        )
    )

    assert payload == {
        "ok": True,
        "name": "meta-short-drama",
        "sessionKey": session_key,
    }
    assert secret not in repr(payload)
    assert pending_meta_launch_pop(session_key) == "meta-short-drama"


@pytest.mark.parametrize("credential_source", ["config", "custom-env"])
def test_meta_run_does_not_globally_alias_openrouter_for_untrusted_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    credential_source: str,
) -> None:
    session_key = f"sess-run-openrouter-{credential_source}"
    _drain(session_key)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    custom_env = "OPENSQUILLA_TEST_META_OPENROUTER_KEY"
    monkeypatch.delenv(custom_env, raising=False)
    if credential_source == "config":
        secret = "synthetic-openrouter-config-key"
        config = _openrouter_cfg(api_key=secret)
    else:
        secret = "synthetic-openrouter-custom-env-key"
        monkeypatch.setenv(custom_env, secret)
        config = _openrouter_cfg(api_key_env=custom_env)

    loader = _make_loader_with_meta(tmp_path)
    spec = loader.get_by_name("meta-tiny")
    assert spec is not None
    spec.metadata = SkillPlatformMeta(
        requires=SkillRequires(env_any=["OPENROUTER_API_KEY"])
    )
    ctx = RpcContext(conn_id="test", config=config, skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "sessionKey": session_key}, ctx)
    )

    assert payload["ok"] is False
    assert payload["code"] == "META_SKILL_SETUP_REQUIRED"
    assert payload["readiness"]["missing_env_any"] == [["OPENROUTER_API_KEY"]]
    assert secret not in repr(payload)
    assert pending_meta_launch_pop(session_key) is None


def test_meta_run_requires_name_and_session_key(tmp_path: Path) -> None:
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    with pytest.raises(Exception):
        asyncio.run(_handle_meta_run({"sessionKey": "sess-x"}, ctx))
    with pytest.raises(Exception):
        asyncio.run(_handle_meta_run({"name": "meta-tiny"}, ctx))
