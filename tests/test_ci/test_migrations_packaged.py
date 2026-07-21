"""Verify migrations and the Control UI are packaged and discoverable post-install.

Critical (C1): without this, default-enabled persistence would silently
boot on an out-of-date schema after fresh install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_wheel_contains_migrations_and_built_usage_ui(tmp_path: Path) -> None:
    """The wheel carries both migration history and the built Usage client."""
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
        javascript = [
            name
            for name in names
            if name.startswith("opensquilla/gateway/static/dist/assets/")
            and name.endswith(".js")
        ]
        usage_query_is_built = any(b"usage.query" in wheel.read(name) for name in javascript)

    assert any(
        n.endswith("opensquilla/_migrations/V010__meta_skill_runs.py") for n in names
    ), f"V010 missing from wheel; found: {[n for n in names if '_migrations' in n]}"
    assert any(
        n.endswith("opensquilla/_migrations/V021__usage_ledger.py") for n in names
    ), f"V021 missing from wheel; found: {[n for n in names if '_migrations' in n]}"
    assert any(
        n.endswith("opensquilla/_migrations/V022__telemetry_daily_usage.py") for n in names
    ), f"V022 missing from wheel; found: {[n for n in names if '_migrations' in n]}"
    assert "opensquilla/gateway/static/dist/index.html" in names
    assert usage_query_is_built, "built Control UI does not contain the usage.query client"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_installed_wheel_resolves_migrations(tmp_path: Path) -> None:
    """An installed wheel resolves both the historical and latest migration."""
    venv_dir = tmp_path / "venv"
    subprocess.run(
        ["uv", "venv", "--seed", str(venv_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        timeout=120,
    )
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
    # 120s was tight enough that Windows CI runners began timing out as
    # the base dependency list grew (each transitive wheel adds I/O the
    # Defender real-time scanner has to walk through). Ubuntu still
    # completes in ~30s; Windows now needs ~90-150s. Bumping the budget
    # rather than skipping preserves the test's intent — verify the
    # built wheel installs cleanly into a fresh venv and the migration
    # resolver finds V010 afterwards.
    subprocess.run(
        [str(pip), "install", str(wheels[0])],
        check=True,
        capture_output=True,
        timeout=300,
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
                " assert (d / 'V021__usage_ledger.py').exists(),"
                "        f'V021 missing in {d}';"
                " assert (d / 'V022__telemetry_daily_usage.py').exists(),"
                "        f'V022 missing in {d}';"
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
@pytest.mark.skipif(os.name == "nt", reason="docker smoke uses Linux container images")
@pytest.mark.skipif(
    os.environ.get("OPENSQUILLA_SKIP_DOCKER_SMOKE") == "1",
    reason="docker smoke disabled via env",
)
@pytest.mark.skipif(
    os.environ.get("OPENSQUILLA_RUN_DOCKER_SMOKE") != "1",
    reason="docker smoke is opt-in; it pulls external images",
)
def test_docker_image_resolves_migrations() -> None:
    """`docker build` + `docker run` resolves _migrations through V022.

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
                " assert (d / 'V021__usage_ledger.py').exists();"
                " assert (d / 'V022__telemetry_daily_usage.py').exists();"
                " print('OK', d)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, f"docker run failed: {run.stderr}"
    assert "OK" in run.stdout
