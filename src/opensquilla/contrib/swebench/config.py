"""Configuration and constants for the SWE-bench harness.

All host paths are derived from the running interpreter so a regular
``pip install opensquilla[swebench]`` needs no manual configuration.
Every derived value can be overridden with an ``OPENSQUILLA_SWEBENCH_*``
environment variable for non-standard setups (separate runner venv,
custom artifact location, pre-built standalone Python, ...).
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

from opensquilla.paths import default_opensquilla_home

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
DATASET_VERIFIED = "princeton-nlp/SWE-bench_Verified"
DATASET_MULTILINGUAL = "SWE-bench/SWE-bench_Multilingual"
DEFAULT_SPLIT = "test"

# ---------------------------------------------------------------------------
# Docker image / container naming
# ---------------------------------------------------------------------------
DOCKER_IMAGE_PREFIX = "sweb.eval.x86_64"
DOCKER_IMAGE_TAG = "latest"
CONTAINER_NAME_PREFIX = "opensquilla-swe"

# ---------------------------------------------------------------------------
# Agent defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = ""  # empty = router self-decides via [squilla_router] in config.toml
DEFAULT_AGENT_TIMEOUT = 1200  # seconds (20 minutes)
DEFAULT_THINKING = ""  # empty = router decides; otherwise off|minimal|low|medium|high|xhigh
DEFAULT_MAX_RETRIES = 1

# ---------------------------------------------------------------------------
# Evaluation defaults
# ---------------------------------------------------------------------------
DEFAULT_EVAL_TIMEOUT = 1800  # seconds per instance
DEFAULT_EVAL_WORKERS = 1

# ---------------------------------------------------------------------------
# Repo cleanup
# ---------------------------------------------------------------------------
SETUP_FILES_TO_REMOVE = (
    # Python setup files
    "pyproject.toml",
    "tox.ini",
    "setup.py",
    # Dependency lock files (auto-generated, often massive and conflict with base)
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Gemfile.lock",
    "composer.lock",
    "Pipfile.lock",
    "go.sum",
)

GITIGNORE_PATTERNS = [
    "*.class",
    "*.jar",
    "*.war",
    "*.ear",
    "*.o",
    "*.obj",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.a",
    "*.lib",
    "*.out",
    "*.pyc",
    "*.pyo",
    "__pycache__/",
    "*.egg-info/",
    "/target/",
    "node_modules/",
    "*.exe",
    "*.bin",
]

# ---------------------------------------------------------------------------
# Git config injected into containers
# ---------------------------------------------------------------------------
GIT_USER_EMAIL = "opensquilla-eval@test.com"
GIT_USER_NAME = "OpenSquilla Eval"

# Package data shipped with the wheel (prompt template, container config).
_DATA_DIR = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------------------
# Host paths (derived, env-overridable)
# ---------------------------------------------------------------------------
def python_home() -> str:
    """Host path of the standalone Python installation mounted into containers.

    Inside a uv/venv environment ``sys.base_prefix`` is the standalone
    CPython root, which is exactly what the containers need read-only.
    """
    return os.environ.get("OPENSQUILLA_SWEBENCH_PYTHON_HOME", sys.base_prefix)


def python_bin() -> str:
    """Host path of the standalone python binary (also valid in-container)."""
    override = os.environ.get("OPENSQUILLA_SWEBENCH_PYTHON_BIN")
    if override:
        return override
    return f"{python_home()}/bin/python3.{sys.version_info.minor}"


def env_path() -> str:
    """Host path of the virtualenv whose site-packages provide opensquilla."""
    return os.environ.get("OPENSQUILLA_SWEBENCH_ENV_PATH", sys.prefix)


def site_packages() -> str:
    """Site-packages dir of :func:`env_path`, mounted into containers."""
    override = os.environ.get("OPENSQUILLA_SWEBENCH_SITE_PACKAGES")
    if override:
        return override
    env = env_path()
    if env == sys.prefix:
        return sysconfig.get_paths()["purelib"]
    return f"{env}/lib/python3.{sys.version_info.minor}/site-packages"


def opensquilla_source_dir() -> str | None:
    """Source tree providing ``opensquilla`` when it lives outside the venv.

    Editable installs (``pip install -e``) keep the package in the source
    checkout; containers must bind-mount that tree too or the in-container
    interpreter cannot import opensquilla. Returns ``None`` for regular
    installs where site-packages already contains the package.
    """
    import opensquilla

    src_root = Path(opensquilla.__file__).resolve().parent.parent
    try:
        src_root.relative_to(Path(env_path()).resolve())
    except ValueError:
        return str(src_root)
    return None


def container_pythonpath() -> str:
    """PYTHONPATH for in-container opensquilla invocations."""
    parts = []
    source_dir = opensquilla_source_dir()
    if source_dir:
        parts.append(source_dir)
    parts.append(site_packages())
    return ":".join(parts)


def container_config_dir() -> Path:
    """Host dir holding config.toml, mounted at /opt/opensquilla-config."""
    override = os.environ.get("OPENSQUILLA_SWEBENCH_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return _DATA_DIR / "container_config"


def prompt_template_path() -> Path:
    """Prompt template rendered for each instance."""
    override = os.environ.get("OPENSQUILLA_SWEBENCH_PROMPT_TEMPLATE")
    if override:
        return Path(override).expanduser()
    return _DATA_DIR / "prompts" / "default.txt"


def artifacts_root() -> Path:
    """Root dir for per-run artifacts (prompt, patch, usage, logs)."""
    override = os.environ.get("OPENSQUILLA_SWEBENCH_ARTIFACTS_DIR")
    if override:
        return Path(override).expanduser()
    return default_opensquilla_home() / "swebench" / "artifacts"


def harness_python() -> str:
    """Interpreter used to run the official ``swebench`` evaluation harness.

    Defaults to the current interpreter (the ``swebench`` extra installs the
    package alongside opensquilla); point the env var at a dedicated venv's
    python to keep using a separate harness environment.
    """
    return os.environ.get("OPENSQUILLA_SWEBENCH_HARNESS_PYTHON", sys.executable)


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------
def instance_id_to_image(instance_id: str) -> str:
    """Convert instance_id to Docker image name.

    SWE-bench harness builds images as:
        sweb.eval.x86_64.django__django-16429:latest
    SWE-agent expects images as:
        swebench/sweb.eval.x86_64.django_1776_django-16429:latest

    We try the harness format first (no prefix, double underscore),
    falling back to the SWE-agent format (swebench/ prefix, _1776_).
    """
    return f"{DOCKER_IMAGE_PREFIX}.{instance_id}:{DOCKER_IMAGE_TAG}"


def instance_id_to_image_sweagent(instance_id: str) -> str:
    """Alternative image name used by SWE-agent (with swebench/ prefix)."""
    transformed = instance_id.replace("__", "_1776_").lower()
    return f"swebench/{DOCKER_IMAGE_PREFIX}.{transformed}:{DOCKER_IMAGE_TAG}"


def instance_id_to_container(instance_id: str) -> str:
    """Convert instance_id to container name.

    django__django-16429 -> opensquilla-swe-django__django-16429
    """
    return f"{CONTAINER_NAME_PREFIX}-{instance_id}"


def get_artifact_dir(run_id: str, instance_id: str) -> Path:
    """Return <artifacts_root>/<run_id>/<instance_id>/."""
    return artifacts_root() / run_id / instance_id


def get_state_path(run_id: str) -> Path:
    """Return <artifacts_root>/<run_id>/state.jsonl."""
    return artifacts_root() / run_id / "state.jsonl"


def get_predictions_path(run_id: str) -> Path:
    """Return <artifacts_root>/<run_id>/predictions.jsonl."""
    return artifacts_root() / run_id / "predictions.jsonl"
