"""Integration contracts for the Hatch WebUI build hook."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_verified_personal_bgm_artifact(probe: Path) -> None:
    """Create a valid private artifact so target-specific policy is exercised."""

    from scripts.verify_webui_artifact import MANIFEST_NAME, source_fingerprint

    webui = probe / "opensquilla-webui"
    music_source = webui / "public" / "music"
    music_source.mkdir(parents=True)
    (webui / ".node-version").write_text("22.12.0\n", encoding="utf-8")
    (music_source / "local.mp3").write_bytes(b"private audio\n")
    (music_source / "playlist.local.json").write_text(
        '{"tracks":[{"id":"local","title":"Local","src":"local.mp3"}]}\n',
        encoding="utf-8",
    )

    dist = probe / "src" / "opensquilla" / "gateway" / "static" / "dist"
    assets = dist / "assets"
    music = dist / "music"
    assets.mkdir(parents=True)
    music.mkdir()
    (assets / "app.js").write_text("console.log('probe')\n", encoding="utf-8")
    (assets / "app.css").write_text("body{}\n", encoding="utf-8")
    (dist / "index.html").write_text(
        '<script type="module" src="assets/app.js"></script>'
        '<link rel="stylesheet" href="assets/app.css">',
        encoding="utf-8",
    )
    (music / "local.mp3").write_bytes(b"private audio\n")
    (music / "playlist.local.json").write_text(
        '{"tracks":[{"id":"local","title":"Local","src":"local.mp3"}]}\n',
        encoding="utf-8",
    )
    records = []
    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        content = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(dist).as_posix(),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schemaVersion": 1,
        "sourceFingerprint": source_fingerprint(webui),
        "files": records,
    }
    (dist / MANIFEST_NAME).write_text(
        f"{json.dumps(manifest, indent=2)}\n",
        encoding="utf-8",
    )


def _build_contract_probe(tmp_path: Path) -> Path:
    """Create a tiny Hatch project that uses the repository's real hook."""

    probe = tmp_path / "probe"
    package = probe / "src" / "probe"
    scripts = probe / "scripts"
    package.mkdir(parents=True)
    scripts.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(REPO_ROOT / "hatch_build.py", probe / "hatch_build.py")
    shutil.copy2(
        REPO_ROOT / "scripts" / "verify_webui_artifact.py",
        scripts / "verify_webui_artifact.py",
    )
    (probe / "pyproject.toml").write_text(
        """\
[build-system]
requires = ["hatchling>=1.31,<2"]
build-backend = "hatchling.build"

[project]
name = "opensquilla-webui-build-contract-probe"
version = "0.0.0"
requires-python = ">=3.12"

[tool.hatch.build.targets.wheel]
packages = ["src/probe"]

[tool.hatch.build.hooks.custom]
""",
        encoding="utf-8",
    )
    return probe


def _run(*args: str, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_no_dist_allows_pep660_editable_but_blocks_standard_distributions(
    tmp_path: Path,
) -> None:
    probe = _build_contract_probe(tmp_path)
    assert not (probe / "src/opensquilla/gateway/static/dist").exists()

    for target_flag in ("--wheel", "--sdist"):
        result = _run(
            "uv",
            "build",
            target_flag,
            "--out-dir",
            str(tmp_path / target_flag.removeprefix("--")),
            cwd=probe,
        )
        assert result.returncode != 0
        output = f"{result.stdout}\n{result.stderr}"
        assert "A verified WebUI artifact is required" in output
        assert "npm ci && npm run build" in output

    venv = tmp_path / "venv"
    created = _run("uv", "venv", "--python", sys.executable, str(venv), cwd=probe)
    assert created.returncode == 0, created.stderr
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    installed = _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--no-deps",
        "--editable",
        str(probe),
        cwd=probe,
    )
    assert installed.returncode == 0, installed.stderr
    imported = _run(
        str(python),
        "-c",
        "import probe; print(probe.__file__)",
        cwd=probe,
    )
    assert imported.returncode == 0, imported.stderr
    assert str(probe / "src" / "probe") in imported.stdout


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_personal_bgm_is_allowed_in_direct_local_wheel_but_forbidden_in_sdist(
    tmp_path: Path,
) -> None:
    probe = _build_contract_probe(tmp_path)
    _write_verified_personal_bgm_artifact(probe)

    wheel = _run(
        "uv",
        "build",
        "--wheel",
        "--out-dir",
        str(tmp_path / "wheel"),
        cwd=probe,
    )
    assert wheel.returncode == 0, wheel.stderr

    sdist_dir = tmp_path / "sdist"
    sdist = _run(
        "uv",
        "build",
        "--sdist",
        "--out-dir",
        str(sdist_dir),
        cwd=probe,
    )
    assert sdist.returncode != 0
    output = f"{sdist.stdout}\n{sdist.stderr}"
    assert "personal BGM content is forbidden" in output
    assert "direct local wheel" in output
    assert not list(sdist_dir.glob("*.tar.gz"))
