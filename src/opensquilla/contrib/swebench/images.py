"""Ensure SWE-bench Docker images are available (local → pull → build).

Requirement chain for ``ensure_image``:

1. A matching image already exists locally → use it.
2. ``docker pull`` the official prebuilt image from the ``swebench/``
   Docker Hub namespace (x86_64 only; 1-3 GB per instance).
3. Optionally build the image locally via the official harness
   (``swebench.harness.prepare_images``) — opt-in because builds take
   tens of minutes and need the ``swebench`` extra installed.
"""

from __future__ import annotations

import logging
import subprocess

from opensquilla.contrib.swebench.config import (
    harness_python,
    instance_id_to_image,
    instance_id_to_image_sweagent,
)

logger = logging.getLogger(__name__)

PULL_TIMEOUT = 1800  # seconds; images are 1-3 GB
BUILD_TIMEOUT = 3600


class ImageNotFoundError(RuntimeError):
    """No usable Docker image could be located, pulled, or built."""


def image_exists_locally(image_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Docker missing or unresponsive: report "not available" so the
        # caller reaches its ImageNotFoundError guidance instead of crashing.
        logger.warning("docker image inspect failed for %s: %s", image_name, exc)
        return False
    return result.returncode == 0


def find_local_image(instance_id: str) -> str | None:
    """Return the first locally available image name for the instance."""
    for name_fn in (instance_id_to_image, instance_id_to_image_sweagent):
        candidate = name_fn(instance_id)
        if image_exists_locally(candidate):
            return candidate
    return None


def pull_image(instance_id: str) -> str | None:
    """Pull the official prebuilt image from Docker Hub.

    Only the SWE-agent naming scheme (``swebench/`` namespace) is published
    on Docker Hub. Returns the image name on success, None on failure.
    """
    image = instance_id_to_image_sweagent(instance_id)
    logger.info("Pulling %s (1-3 GB, may take a few minutes)...", image)
    try:
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            timeout=PULL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("docker pull timed out after %ds for %s", PULL_TIMEOUT, image)
        return None
    except OSError as exc:
        logger.warning("docker pull failed for %s: %s", image, exc)
        return None
    if result.returncode == 0:
        logger.info("Pulled %s", image)
        return image
    logger.warning("docker pull failed for %s: %s", image, (result.stderr or "").strip()[-300:])
    return None


def build_image(instance_id: str, dataset_name: str) -> str | None:
    """Build the instance image locally via the official harness.

    Requires the ``swebench`` package (pip install opensquilla[swebench])
    in the interpreter returned by :func:`harness_python`.
    Returns the image name on success, None on failure.
    """
    cmd = [
        harness_python(),
        "-m",
        "swebench.harness.prepare_images",
        "--dataset_name",
        dataset_name,
        "--split",
        "test",
        "--instance_ids",
        instance_id,
        "--max_workers",
        "1",
    ]
    logger.info("Building image for %s via harness (may take a while)...", instance_id)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Image build timed out after %ds for %s", BUILD_TIMEOUT, instance_id)
        return None
    except OSError as exc:
        logger.warning("Image build failed for %s: %s", instance_id, exc)
        return None
    if result.returncode != 0:
        logger.warning(
            "Image build failed for %s: %s",
            instance_id,
            (result.stderr or result.stdout or "").strip()[-500:],
        )
        return None
    return find_local_image(instance_id)


def ensure_image(
    instance_id: str,
    dataset_name: str,
    *,
    pull: bool = True,
    build: bool = False,
) -> str:
    """Make sure a Docker image for the instance is available locally.

    Returns the usable image name; raises :class:`ImageNotFoundError` with
    actionable guidance when every enabled strategy fails.
    """
    local = find_local_image(instance_id)
    if local:
        logger.debug("Image for %s found locally: %s", instance_id, local)
        return local

    if pull:
        pulled = pull_image(instance_id)
        if pulled:
            return pulled

    if build:
        built = build_image(instance_id, dataset_name)
        if built:
            return built

    tried = ["local lookup"]
    if pull:
        tried.append("docker pull (swebench/ namespace)")
    if build:
        tried.append("harness build")
    raise ImageNotFoundError(
        f"No Docker image available for {instance_id} after: {', '.join(tried)}. "
        "Either pre-build it (python -m swebench.harness.prepare_images ...), "
        "retry with build enabled, or check network access to Docker Hub."
    )
