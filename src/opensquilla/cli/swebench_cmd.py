"""``opensquilla swebench`` — run SWE-bench instances with OpenSquilla agents.

Optional feature: heavy dependencies (datasets, swebench) install via
``pip install opensquilla[swebench]``. Everything below the command
boundary is lazy-imported so this module stays cheap for ``--help``.
"""

from __future__ import annotations

import json

import typer

swebench_app = typer.Typer(
    help="Run SWE-bench instances inside official Docker images.",
    no_args_is_help=True,
)

_INSTALL_HINT = (
    "SWE-bench support needs optional dependencies (swebench, datasets). "
    "Install them with:  uv sync --extra swebench  "
    "(or, for a non-uv install:  pip install 'opensquilla[swebench]')"
)


def _require_datasets() -> None:
    try:
        import datasets  # noqa: F401
    except ImportError as exc:
        typer.secho(_INSTALL_HINT, err=True, fg=typer.colors.RED)
        raise typer.Exit(2) from exc


def _require_swebench() -> None:
    try:
        import swebench  # noqa: F401
    except ImportError as exc:
        typer.secho(_INSTALL_HINT, err=True, fg=typer.colors.RED)
        raise typer.Exit(2) from exc


def _docker_install_hint() -> str:
    """OS-appropriate guidance for installing the Docker CLI."""
    import platform

    system = platform.system().lower()
    if system == "darwin":
        return "Install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/"
    if system == "linux":
        return (
            "Install Docker, e.g. `curl -fsSL https://get.docker.com | sh` "
            "(or your distro's docker.io / docker-ce package), then start the daemon."
        )
    return "Install Docker: https://docs.docker.com/get-docker/"


def _require_docker() -> None:
    """Preflight: SWE-bench runs official Docker images. Guide install if missing.

    Checks two things, because "installed" is not "usable":
    1. the ``docker`` CLI is on PATH, and
    2. the Docker daemon is actually reachable (``docker info``) — Docker
       Desktop is commonly installed but not started, which otherwise fails
       later with a cryptic daemon-connection error.

    Rather than dead-ending, tell the user exactly what to install/start so
    they can come back and run it.
    """
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        typer.secho(
            "SWE-bench mode needs the Docker CLI to run the official evaluation "
            "images, but `docker` was not found on PATH.",
            err=True,
            fg=typer.colors.RED,
        )
        typer.secho(_docker_install_hint(), err=True, fg=typer.colors.YELLOW)
        typer.secho(
            "Tip: to solve a real-repository coding task WITHOUT Docker, use "
            "`opensquilla code-task` instead.",
            err=True,
            fg=typer.colors.BLUE,
        )
        raise typer.Exit(2)

    # Docker is installed — is the daemon running? `docker info` talks to it.
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        daemon_ok = proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        daemon_ok = False
    if not daemon_ok:
        typer.secho(
            "Docker is installed but its daemon is not reachable — start Docker "
            "Desktop (or the docker service) and wait for it to be ready, then "
            "re-run.",
            err=True,
            fg=typer.colors.RED,
        )
        typer.secho(_docker_install_hint(), err=True, fg=typer.colors.YELLOW)
        raise typer.Exit(2)


@swebench_app.command("solve")
def solve(
    instance_id: str = typer.Argument(..., help="SWE-bench instance, e.g. django__django-16429"),
    dataset: str = typer.Option(
        "verified",
        help="Dataset: 'verified', 'multilingual', or a full HuggingFace name.",
    ),
    model: str = typer.Option("", help="Model override; empty lets squilla_router decide."),
    thinking: str = typer.Option("", help="Thinking effort; empty lets the router decide."),
    timeout: int = typer.Option(1200, help="Agent timeout in seconds."),
    run_id: str = typer.Option("", help="Run identifier (auto-generated when empty)."),
    pull: bool = typer.Option(True, help="Auto-pull missing images from Docker Hub."),
    build: bool = typer.Option(
        False, "--build", help="Build the image locally when pull fails (slow)."
    ),
    evaluate: bool = typer.Option(
        False, "--evaluate", help="Run official evaluation on the collected patch."
    ),
    json_output: bool = typer.Option(False, "--json", help="Print the result as JSON on stdout."),
) -> None:
    """Run one instance end-to-end: image → container → agent → patch."""
    _require_docker()
    _require_datasets()
    if evaluate or build:
        _require_swebench()

    from opensquilla.contrib.swebench.images import ImageNotFoundError
    from opensquilla.contrib.swebench.runner import solve_instance

    try:
        result = solve_instance(
            instance_id=instance_id,
            dataset=dataset,
            model=model,
            thinking=thinking,
            timeout=timeout,
            run_id=run_id or None,
            pull=pull,
            build=build,
            evaluate=evaluate,
        )
    except ImageNotFoundError as exc:
        if json_output:
            typer.echo(
                json.dumps({"instance_id": instance_id, "state": "failed", "error": str(exc)})
            )
        else:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc

    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False))
    else:
        state = result["state"]
        color = typer.colors.GREEN if state == "patch_collected" else typer.colors.YELLOW
        typer.secho(f"[{state}] {instance_id}", fg=color)
        if result.get("patch_path"):
            typer.echo(f"  patch:     {result['patch_path']}")
        typer.echo(f"  artifacts: {result['artifact_dir']}")
        if result.get("resolved") is not None:
            typer.echo(f"  resolved:  {result['resolved']}")
        if result.get("error"):
            typer.secho(f"  error:     {result['error']}", fg=typer.colors.RED)

    if result["state"] in ("failed", "timeout"):
        raise typer.Exit(1)


@swebench_app.command("eval")
def eval_predictions(
    predictions: str = typer.Argument(..., help="Path to predictions.jsonl"),
    dataset: str = typer.Option("verified", help="Dataset the predictions belong to."),
    run_id: str = typer.Option("manual-eval", help="Evaluation run identifier."),
    instance_id: list[str] = typer.Option(
        None, "--instance-id", help="Limit evaluation to these instances (repeatable)."
    ),
    max_workers: int = typer.Option(1, help="Parallel evaluation workers."),
    timeout: int = typer.Option(1800, help="Per-instance evaluation timeout (seconds)."),
) -> None:
    """Run the official SWE-bench evaluation harness on a predictions file."""
    _require_docker()
    _require_swebench()

    from opensquilla.contrib.swebench.evaluate import run_evaluation
    from opensquilla.contrib.swebench.runner import resolve_dataset_name

    code = run_evaluation(
        predictions_path=predictions,
        dataset_name=resolve_dataset_name(dataset),
        run_id=run_id,
        instance_ids=list(instance_id) if instance_id else None,
        max_workers=max_workers,
        timeout=timeout,
    )
    raise typer.Exit(code)


@swebench_app.command("pull")
def pull(
    instance_id: str = typer.Argument(..., help="SWE-bench instance to fetch the image for."),
    dataset: str = typer.Option("verified", help="Dataset (used only for build fallback)."),
    build: bool = typer.Option(False, "--build", help="Build locally when pull fails."),
) -> None:
    """Pre-fetch the Docker image for an instance (local → pull → build)."""
    _require_docker()
    if build:
        _require_swebench()

    from opensquilla.contrib.swebench.images import ImageNotFoundError, ensure_image
    from opensquilla.contrib.swebench.runner import resolve_dataset_name

    try:
        image = ensure_image(instance_id, resolve_dataset_name(dataset), pull=True, build=build)
    except ImageNotFoundError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    typer.echo(image)
