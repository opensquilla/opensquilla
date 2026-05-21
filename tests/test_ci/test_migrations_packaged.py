"""Verify migrations are packaged into the wheel and discoverable post-install.

Critical (C1): without this, default-enabled persistence would silently
boot on an out-of-date schema after fresh install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import venv
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_wheel_contains_v010_migration(tmp_path: Path) -> None:
    """`uv build --wheel` packages migrations/ as opensquilla/_migrations/."""
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
        names = wheel.namelist()

    assert any(
        n.endswith("opensquilla/_migrations/V010__meta_skill_runs.py") for n in names
    ), f"V010 missing from wheel; found: {[n for n in names if '_migrations' in n]}"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_installed_wheel_resolves_migrations(tmp_path: Path) -> None:
    """After pip-installing into a fresh venv, _resolve_migrations_dir() finds V010."""
    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True)
    pip = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "pip"
    py = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"

    wheel_dir = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        timeout=180,
    )
    wheels = list(wheel_dir.glob("opensquilla-*.whl"))
    subprocess.run(
        [str(pip), "install", str(wheels[0])],
        check=True,
        capture_output=True,
        timeout=120,
    )

    result = subprocess.run(
        [
            str(py),
            "-c",
            (
                "from opensquilla.gateway.boot import _resolve_migrations_dir;"
                " d = _resolve_migrations_dir();"
                " assert (d / 'V010__meta_skill_runs.py').exists(),"
                "        f'V010 missing in {d}';"
                " print('OK', d)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"resolver failed: {result.stderr}"
    assert "OK" in result.stdout


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not on PATH")
@pytest.mark.skipif(
    os.environ.get("OPENSQUILLA_SKIP_DOCKER_SMOKE") == "1",
    reason="docker smoke disabled via env",
)
def test_docker_image_resolves_migrations() -> None:
    """`docker build` + `docker run` resolves _migrations including V010.

    Verifies (C1 v2): .dockerignore no longer excludes migrations/.
    """
    tag = "opensquilla-test:meta-runs-persistence"
    build = subprocess.run(
        ["docker", "build", "-t", tag, "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, f"docker build failed: {build.stderr[-2000:]}"

    run = subprocess.run(
        [
            "docker", "run", "--rm", "--entrypoint", "python", tag,
            "-c",
            (
                "from opensquilla.gateway.boot import _resolve_migrations_dir;"
                " d = _resolve_migrations_dir();"
                " assert (d / 'V010__meta_skill_runs.py').exists();"
                " print('OK', d)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, f"docker run failed: {run.stderr}"
    assert "OK" in run.stdout
