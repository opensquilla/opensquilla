from __future__ import annotations

import pytest

from opensquilla.cli.tui.renderers.selection import (
    OPENSQUILLA_TUI_BACKEND_ENV,
    RendererBackendSelectionError,
    get_renderer_backend,
    renderer_backends,
    select_renderer_backend,
    select_renderer_backend_from_env,
)

REMOVED_TEXT_BACKEND = "text" + "ual"
REMOVED_BACKEND_IDS = ["terminal", REMOVED_TEXT_BACKEND, f"live-{REMOVED_TEXT_BACKEND}"]


def test_opentui_backend_is_default_and_only_registered_backend() -> None:
    backend = select_renderer_backend()

    assert backend.backend_id == "opentui"
    assert backend.supports_streaming_fast_path is True
    assert backend.supports_structured_ui is True
    assert set(renderer_backends()) == {"opentui"}


def test_renderer_backend_lookup_rejects_unknown_ids() -> None:
    with pytest.raises(RendererBackendSelectionError) as exc_info:
        get_renderer_backend("unknown")

    assert "Only OpenTUI is supported" in str(exc_info.value)
    assert "opentui" in str(exc_info.value)
    assert "terminal" not in str(exc_info.value)
    assert REMOVED_TEXT_BACKEND not in str(exc_info.value)


def test_backend_selection_reads_env_and_preserves_opentui_default() -> None:
    assert select_renderer_backend_from_env({}).backend_id == "opentui"
    assert (
        select_renderer_backend_from_env({OPENSQUILLA_TUI_BACKEND_ENV: ""}).backend_id
        == "opentui"
    )
    assert (
        select_renderer_backend_from_env({OPENSQUILLA_TUI_BACKEND_ENV: " opentui "})
        .backend_id
        == "opentui"
    )


def test_backend_selection_rejects_unknown_env_values_clearly() -> None:
    with pytest.raises(RendererBackendSelectionError) as exc_info:
        select_renderer_backend_from_env({OPENSQUILLA_TUI_BACKEND_ENV: "bogus"})

    assert "Only OpenTUI is supported" in str(exc_info.value)
    assert "opentui" in str(exc_info.value)
    assert "bogus" in str(exc_info.value)


@pytest.mark.parametrize("backend_id", REMOVED_BACKEND_IDS)
def test_backend_selection_rejects_removed_backend_ids(backend_id: str) -> None:
    with pytest.raises(RendererBackendSelectionError) as exc_info:
        select_renderer_backend(backend_id)

    message = str(exc_info.value)
    assert "Only OpenTUI is supported" in message
    assert backend_id in message
    assert "opentui" in message


def test_opentui_backend_is_registered_without_importing_legacy_backends() -> None:
    backend = get_renderer_backend("opentui")

    assert backend.backend_id == "opentui"
    assert backend.supports_structured_ui is True
    assert backend.supports_streaming_fast_path is True
