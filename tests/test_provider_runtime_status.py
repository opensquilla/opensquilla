from __future__ import annotations

import ast
import dataclasses
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import opensquilla.provider.runtime_status as runtime_status
from opensquilla.provider.runtime_status import (
    build_provider_status_payload,
    build_provider_status_report,
    build_provider_status_rpc_payload,
)

ROOT = Path(__file__).resolve().parents[1]
RPC_PROVIDERS = ROOT / "src/opensquilla/gateway/rpc_providers.py"


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


@dataclass(frozen=True)
class FakeStatusSpec:
    provider_id: str
    runtime_supported: bool = True
    env_key: str = "OPENROUTER_API_KEY"
    default_base_url: str = "https://openrouter.ai/api/v1"
    requires_api_key: bool = True
    requires_base_url: bool = False


class FailingModelSelector:
    current_config = SimpleNamespace(provider="openrouter")

    async def list_models(self) -> list[dict[str, object]]:
        raise RuntimeError("catalog unavailable")


class ListingModelSelector:
    current_config = SimpleNamespace(provider="openrouter")

    async def list_models(self) -> list[dict[str, object]]:
        return [
            {"provider": "openrouter", "id": "openrouter/model"},
            {"provider": "ollama", "id": "ollama/model"},
        ]


def _config(
    *,
    provider: str = "openrouter",
    model: str = "openrouter/model",
    api_key: str = "",
    base_url: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        llm=SimpleNamespace(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
    )


@pytest.mark.asyncio
async def test_probe_provider_models_uses_model_listing_catalog_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selector = ListingModelSelector()
    calls: list[object] = []

    class Catalog:
        def count_provider(self, provider_id: str) -> int:
            assert provider_id == "openrouter"
            return 7

    async def load_catalog(provider_selector: object) -> Catalog:
        calls.append(provider_selector)
        return Catalog()

    monkeypatch.setattr(runtime_status, "load_provider_model_catalog", load_catalog)

    probe = await runtime_status.probe_provider_models("openrouter", selector)

    assert calls == [selector]
    assert probe.attempted is True
    assert probe.status == "ok"
    assert probe.count == 7
    assert probe.error is None


@pytest.mark.asyncio
async def test_build_provider_status_report_resolves_configured_active_provider() -> None:
    report = await build_provider_status_report(
        [FakeStatusSpec(provider_id="openrouter")],
        provider_selector=None,
        config=_config(api_key="secret-key", base_url="https://custom.example/v1"),
        environ={},
    )

    assert report.active_provider == "openrouter"
    row = report.rows[0]
    assert row.active is True
    assert row.configured is True
    assert row.buildable is True
    assert row.model == "openrouter/model"
    assert row.api_key_configured is True
    assert row.base_url_configured is True
    assert row.model_probe.status == "skipped"
    assert "secret-key" not in repr(report)


@pytest.mark.asyncio
async def test_build_provider_status_report_from_domain_query_separates_rpc_params() -> None:
    query_type = getattr(runtime_status, "ProviderStatusQuery", None)
    assert query_type is not None
    assert {field.name for field in dataclasses.fields(query_type)} == {
        "provider_filter",
        "probe_models",
    }

    query = query_type(provider_filter="openrouter", probe_models=True)
    report = await runtime_status.build_provider_status_report_for_query(
        [
            FakeStatusSpec(provider_id="openrouter"),
            FakeStatusSpec(
                provider_id="ollama",
                env_key="",
                requires_api_key=False,
                default_base_url="",
            ),
        ],
        query,
        provider_selector=ListingModelSelector(),
        config=_config(api_key="secret-key", base_url="https://custom.example/v1"),
        environ={},
    )

    assert report.active_provider == "openrouter"
    assert [row.provider_id for row in report.rows] == ["openrouter"]
    assert report.rows[0].model_probe.status == "ok"
    assert report.rows[0].model_probe.count == 1
    assert "secret-key" not in repr(report)


@pytest.mark.asyncio
async def test_build_provider_status_report_filters_and_raises_unknown_provider() -> None:
    report = await build_provider_status_report(
        [
            FakeStatusSpec(provider_id="openrouter"),
            FakeStatusSpec(provider_id="ollama", env_key="", requires_api_key=False),
        ],
        provider_selector=None,
        config=_config(),
        provider_filter="ollama",
        environ={},
    )

    assert [row.provider_id for row in report.rows] == ["ollama"]
    with pytest.raises(ValueError, match="Unknown provider"):
        await build_provider_status_report(
            [FakeStatusSpec(provider_id="openrouter")],
            provider_selector=None,
            config=_config(),
            provider_filter="missing",
            environ={},
        )


@pytest.mark.asyncio
async def test_build_provider_status_report_probes_selector_errors() -> None:
    report = await build_provider_status_report(
        [FakeStatusSpec(provider_id="openrouter")],
        provider_selector=FailingModelSelector(),
        config=_config(),
        probe_models=True,
        environ={"OPENROUTER_API_KEY": "from-env"},
    )

    probe = report.rows[0].model_probe
    assert probe.attempted is True
    assert probe.status == "error"
    assert probe.count == 0
    assert probe.error == "catalog unavailable"


@pytest.mark.asyncio
async def test_build_provider_status_payload_owns_gateway_wire_shape() -> None:
    payload = await build_provider_status_payload(
        [
            FakeStatusSpec(provider_id="openrouter"),
            FakeStatusSpec(
                provider_id="ollama",
                env_key="",
                requires_api_key=False,
                default_base_url="",
            ),
        ],
        provider_selector=ListingModelSelector(),
        config=_config(api_key="secret-key", base_url="https://custom.example/v1"),
        provider_filter="openrouter",
        probe_models=True,
        environ={},
    )

    assert payload == {
        "activeProvider": "openrouter",
        "providers": [
            {
                "providerId": "openrouter",
                "active": True,
                "configured": True,
                "buildable": True,
                "model": "openrouter/model",
                "requiresApiKey": True,
                "apiKeyConfigured": True,
                "baseUrlConfigured": True,
                "error": None,
                "modelProbe": {
                    "attempted": True,
                    "status": "ok",
                    "count": 1,
                    "error": None,
                },
            }
        ],
        "count": 1,
    }
    assert "secret-key" not in repr(payload)


@pytest.mark.asyncio
async def test_build_provider_status_rpc_payload_owns_request_params() -> None:
    payload = await build_provider_status_rpc_payload(
        [
            FakeStatusSpec(provider_id="openrouter"),
            FakeStatusSpec(
                provider_id="ollama",
                env_key="",
                requires_api_key=False,
                default_base_url="",
            ),
        ],
        {"provider": "openrouter", "probeModels": True},
        provider_selector=ListingModelSelector(),
        config=_config(api_key="secret-key", base_url="https://custom.example/v1"),
        environ={},
    )

    assert payload["activeProvider"] == "openrouter"
    assert [row["providerId"] for row in payload["providers"]] == ["openrouter"]
    assert payload["providers"][0]["modelProbe"] == {
        "attempted": True,
        "status": "ok",
        "count": 1,
        "error": None,
    }
    assert "secret-key" not in repr(payload)

    with pytest.raises(ValueError, match="params must be an object"):
        await build_provider_status_rpc_payload(
            [FakeStatusSpec(provider_id="openrouter")],
            "bad-params",  # type: ignore[arg-type]
            provider_selector=None,
            config=_config(),
            environ={},
        )


def test_gateway_delegates_provider_status_wire_shape_to_gateway_facade() -> None:
    imports = _imports_from(RPC_PROVIDERS)

    assert (
        "opensquilla.gateway.provider_rpc_payloads",
        "build_provider_status_rpc_payload",
    ) in imports
    assert (
        "opensquilla.provider.runtime_status",
        "build_provider_status_rpc_payload",
    ) not in imports
    assert (
        "opensquilla.provider.runtime_status",
        "build_provider_status_payload",
    ) not in imports
    assert (
        "opensquilla.provider.runtime_status",
        "build_provider_status_report",
    ) not in imports
    assert ("opensquilla.provider.runtime_status", "ProviderStatusRow") not in imports
    assert ("opensquilla.provider.runtime_status", "ProviderModelProbe") not in imports
    assert "provider_status_report_to_wire" not in _top_level_functions(
        ROOT / "src/opensquilla/provider/runtime_status.py"
    )
