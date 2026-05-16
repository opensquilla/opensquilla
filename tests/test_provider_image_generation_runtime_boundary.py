from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.provider import image_generation_runtime
from opensquilla.provider.image_generation_config import ImageGenerationConfig
from opensquilla.tools.builtin import media

ROOT = Path(__file__).resolve().parents[1]
MEDIA_TOOL = ROOT / "src/opensquilla/tools/builtin/media.py"
BOOT = ROOT / "src/opensquilla/gateway/boot.py"
RPC_CONFIG = ROOT / "src/opensquilla/gateway/rpc_config.py"
RPC_ONBOARDING = ROOT / "src/opensquilla/gateway/rpc_onboarding.py"
RPC_TOOLS = ROOT / "src/opensquilla/gateway/rpc_tools.py"
TOOLS_POLICY = ROOT / "src/opensquilla/tools/policy.py"


def _top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def test_media_tool_does_not_own_image_generation_runtime_state() -> None:
    assert "_image_generation_config" not in _top_level_names(MEDIA_TOOL)


def test_gateway_configures_image_generation_runtime_boundary() -> None:
    forbidden = ("opensquilla.tools.builtin.media", "configure_image_generation")

    for path in (BOOT, RPC_CONFIG, RPC_ONBOARDING):
        assert forbidden not in _imports_from(path)
        assert (
            "opensquilla.provider.image_generation_runtime",
            "configure_image_generation",
        ) in _imports_from(path)


def test_gateway_reads_image_generation_capability_from_runtime_boundary() -> None:
    forbidden = ("opensquilla.tools.builtin.media", "image_generation_available")

    assert forbidden not in _imports_from(RPC_TOOLS)
    assert forbidden not in _imports_from(TOOLS_POLICY)
    assert (
        "opensquilla.provider.image_generation_runtime",
        "image_generation_available",
    ) in _imports_from(RPC_TOOLS)
    assert (
        "opensquilla.provider.image_generation_runtime",
        "image_generation_available",
    ) in _imports_from(TOOLS_POLICY)


def test_media_compat_wrappers_delegate_to_image_runtime() -> None:
    config = ImageGenerationConfig(enabled=True, primary="openai/test-image")

    media.configure_image_generation(config)

    assert image_generation_runtime.current_image_generation_config() is config
    assert media._resolve_image_generation_config() is config
    assert media._resolve_image_generation_candidates("openai/override", config)[0] == (
        "openai/override"
    )

    image_generation_runtime.configure_image_generation(None)

