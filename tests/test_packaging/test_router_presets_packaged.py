"""Verify packaged router preset data ships in the wheel.

Gateway config validation resolves ``squilla_router.tier_profile`` through the
preset registry's packaged TOML files; if they were dropped from the wheel,
every fresh install would reject the nine legacy profiles at boot.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

LEGACY_PRESET_IDS = (
    "byteplus",
    "dashscope",
    "deepseek",
    "gemini",
    "moonshot",
    "openai",
    "openrouter",
    "volcengine",
    "zhipu",
)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_wheel_contains_all_packaged_router_presets(tmp_path: Path) -> None:
    """`uv build --wheel` packages opensquilla/provider/presets/<id>.toml."""
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"uv build failed: {result.stderr}"

    wheels = list(tmp_path.glob("opensquilla-*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel, got {wheels}"

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    missing = [
        preset_id
        for preset_id in LEGACY_PRESET_IDS
        if f"opensquilla/provider/presets/{preset_id}.toml" not in names
    ]
    assert not missing, (
        f"router presets missing from wheel: {missing}; "
        f"found: {sorted(n for n in names if 'provider/presets' in n)}"
    )


def test_source_tree_ships_all_packaged_router_presets() -> None:
    """Cheap guard for the default test path: the preset files exist in-tree."""
    presets_dir = REPO_ROOT / "src" / "opensquilla" / "provider" / "presets"
    present = {p.stem for p in presets_dir.glob("*.toml")}
    assert present == set(LEGACY_PRESET_IDS), present
