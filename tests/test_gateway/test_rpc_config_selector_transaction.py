"""Provider-selector ordering for mutating config RPCs."""

from __future__ import annotations

import tomllib
from typing import Any

import pytest
import tomli_w

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_config import (
    _handle_config_apply,
    _handle_config_patch,
    _handle_config_set,
)


class _RecordingSelector:
    def __init__(self, *, fail: bool = False) -> None:
        self.configs: list[Any] = []
        self.fail = fail

    def sync_primary(self, config: Any) -> None:
        self.configs.append(config)
        if self.fail:
            raise RuntimeError("selector sync failed")


def _write_config(path) -> None:
    path.write_text(
        'config_version = 1\n\n'
        '[llm]\nprovider = "openai"\nmodel = "gpt-old"\n'
    )


async def _mutate_model(kind: str, ctx: RpcContext, model: str) -> dict[str, Any]:
    if kind == "set":
        return await _handle_config_set({"path": "llm.model", "value": model}, ctx)
    if kind == "patch":
        return await _handle_config_patch({"patches": {"llm.model": model}}, ctx)
    payload = ctx.config.model_dump(mode="python")
    payload["llm"]["model"] = model
    return await _handle_config_apply({"config": payload}, ctx)


@pytest.mark.parametrize("kind", ["set", "patch", "apply"])
async def test_persist_failure_does_not_sync_live_selector(
    tmp_path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    original = path.read_text()
    config = GatewayConfig.load(str(path))
    selector = _RecordingSelector()
    ctx = RpcContext(conn_id="test", config=config, provider_selector=selector)

    import opensquilla.onboarding.config_store as config_store

    def _fail_replace(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(config_store.os, "replace", _fail_replace)

    with pytest.raises(OSError, match="disk full"):
        await _mutate_model(kind, ctx, "gpt-new")

    assert ctx.config is config
    assert config.llm.model == "gpt-old"
    assert path.read_text() == original
    assert selector.configs == []


@pytest.mark.parametrize("kind", ["set", "patch", "apply"])
async def test_selector_failure_after_persist_keeps_disk_and_live_config_aligned(
    tmp_path, kind: str
) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    config = GatewayConfig.load(str(path))
    selector = _RecordingSelector(fail=True)
    ctx = RpcContext(conn_id="test", config=config, provider_selector=selector)

    with pytest.raises(RuntimeError, match="selector sync failed"):
        await _mutate_model(kind, ctx, "gpt-new")

    assert ctx.config is config
    assert config.llm.model == "gpt-new"
    assert GatewayConfig.load(str(path)).llm.model == "gpt-new"
    assert config.force_persist_paths() == set()
    assert [provider_config.model for provider_config in selector.configs] == ["gpt-new"]


@pytest.mark.parametrize("kind", ["set", "patch"])
async def test_explicit_baseline_value_wins_over_disk_drift_once(
    tmp_path, kind: str
) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    config = GatewayConfig.load(str(path))
    ctx = RpcContext(conn_id="test", config=config)

    drifted = tomllib.loads(path.read_text())
    drifted["llm"]["model"] = "gpt-drifted"
    path.write_text(tomli_w.dumps(drifted))

    await _mutate_model(kind, ctx, "gpt-old")

    assert tomllib.loads(path.read_text())["llm"]["model"] == "gpt-old"
    assert config.force_persist_paths() == set()

    drifted_again = tomllib.loads(path.read_text())
    drifted_again["llm"]["model"] = "gpt-drifted-again"
    path.write_text(tomli_w.dumps(drifted_again))

    await _handle_config_set({"path": "naming.enabled", "value": False}, ctx)

    persisted = tomllib.loads(path.read_text())
    assert persisted["llm"]["model"] == "gpt-drifted-again"
    assert persisted["naming"]["enabled"] is False


async def test_apply_preserves_unchanged_disk_drift_without_materializing_defaults(
    tmp_path,
) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    config = GatewayConfig.load(str(path))
    ctx = RpcContext(conn_id="test", config=config)

    drifted = tomllib.loads(path.read_text())
    drifted["llm"]["model"] = "gpt-drifted"
    path.write_text(tomli_w.dumps(drifted))

    await _mutate_model("apply", ctx, "gpt-old")

    persisted_text = path.read_text()
    assert tomllib.loads(persisted_text)["llm"]["model"] == "gpt-drifted"
    assert "[memory]" not in persisted_text


async def test_explicit_nullable_reset_removes_post_load_disk_value(tmp_path) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    config = GatewayConfig.load(str(path))
    ctx = RpcContext(conn_id="test", config=config)

    drifted = tomllib.loads(path.read_text())
    drifted["naming"] = {"model": "gpt-drifted"}
    path.write_text(tomli_w.dumps(drifted))

    await _handle_config_patch({"patches": {"naming.model": None}}, ctx)

    persisted = tomllib.loads(path.read_text())
    assert "model" not in persisted.get("naming", {})
    assert config.naming.model is None
    assert config.force_persist_paths() == set()


@pytest.mark.parametrize("kind", ["set", "patch", "merge"])
async def test_explicit_env_equal_base_url_is_persisted(
    tmp_path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    env_url = "https://env-equal.example/v1"
    monkeypatch.setenv("OPENAI_BASE_URL", env_url)
    path = tmp_path / "config.toml"
    _write_config(path)
    config = GatewayConfig.load(str(path))
    resolve_llm_runtime_config(config)
    assert config.runtime_field_overrides()["llm.base_url"][1] == env_url
    ctx = RpcContext(conn_id="test", config=config)

    if kind == "set":
        await _handle_config_set({"path": "llm.base_url", "value": env_url}, ctx)
    elif kind == "patch":
        await _handle_config_patch({"patches": {"llm.base_url": env_url}}, ctx)
    else:
        await _handle_config_patch({"patch": {"llm": {"base_url": env_url}}}, ctx)

    persisted = tomllib.loads(path.read_text())
    assert persisted["llm"]["base_url"] == env_url
    assert config.llm.base_url == env_url


async def test_apply_roundtrip_does_not_bake_env_base_url(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_url = "https://env-roundtrip.example/v1"
    monkeypatch.setenv("OPENAI_BASE_URL", env_url)
    path = tmp_path / "config.toml"
    _write_config(path)
    config = GatewayConfig.load(str(path))
    resolve_llm_runtime_config(config)
    ctx = RpcContext(conn_id="test", config=config)

    await _handle_config_apply(
        {"config": config.model_dump(mode="python")},
        ctx,
    )

    assert env_url not in path.read_text()


async def test_empty_merge_patch_is_sparse_noop_and_preserves_disk_drift(tmp_path) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    config = GatewayConfig.load(str(path))
    ctx = RpcContext(conn_id="test", config=config)

    drifted = tomllib.loads(path.read_text())
    drifted["memory"] = {"flush_enabled": True}
    path.write_text(tomli_w.dumps(drifted))

    response = await _handle_config_patch({"patch": {"memory": {}}}, ctx)

    persisted = tomllib.loads(path.read_text())
    assert response["patched"] == ["(merge)"]
    assert persisted["memory"] == {"flush_enabled": True}
    assert config.memory.flush_enabled is False


async def test_merge_patch_force_path_preserves_dotted_dynamic_key(tmp_path) -> None:
    path = tmp_path / "config.toml"
    initial = tomllib.loads(
        'config_version = 1\n\n'
        '[llm]\nprovider = "openai"\nmodel = "gpt-old"\n'
    )
    initial["models"] = {
        "openrouter": {"foo.bar": {"context_window": 8192}},
    }
    path.write_text(tomli_w.dumps(initial))
    config = GatewayConfig.load(str(path))
    ctx = RpcContext(conn_id="test", config=config)

    drifted = tomllib.loads(path.read_text())
    drifted["models"]["openrouter"]["foo.bar"]["context_window"] = 16384
    path.write_text(tomli_w.dumps(drifted))

    await _handle_config_patch(
        {
            "patch": {
                "models": {
                    "openrouter": {"foo.bar": {"context_window": 8192}},
                }
            }
        },
        ctx,
    )

    persisted = tomllib.loads(path.read_text())
    assert persisted["models"]["openrouter"]["foo.bar"]["context_window"] == 8192
    assert config.force_persist_paths() == set()
