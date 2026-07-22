#!/usr/bin/env python3
"""Install and smoke-test the real pinned managed-toolchain artifacts.

This is intentionally an opt-in release/CI check rather than an offline unit
test: it downloads the catalog artifacts and, on macOS, may install the pinned
Homebrew formula selected by the catalog.  Use an isolated root so validation
receipts and extracted payloads never enter the normal user state directory.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from opensquilla.skills.toolchains import (
    component_ids,
    describe_component,
    install_component,
    invalidate_probe_cache,
    probe_component,
)

_VALIDATION_ROOT_ENV = "OPENSQUILLA_TOOLCHAIN_VALIDATION_ROOT"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download, verify, install, and smoke-test pinned toolchain artifacts."
    )
    parser.add_argument(
        "--component",
        action="append",
        dest="components",
        choices=component_ids(),
        help="Component to validate; repeat as needed (default: every component).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help=(
            "Isolated validation root. Defaults to "
            f"${_VALIDATION_ROOT_ENV} or the system temporary directory."
        ),
    )
    parser.add_argument(
        "--expect-platform-key",
        help=(
            "Fail unless native host detection resolves this catalog platform key. "
            "This assertion never overrides platform detection."
        ),
    )
    return parser


def _validation_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get(_VALIDATION_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()).resolve() / "opensquilla-toolchain-artifact-validation"


def _progress(component_id: str):
    last_bucket = -1

    def report(downloaded: int, total: int) -> None:
        nonlocal last_bucket
        if total <= 0:
            return
        bucket = min(10, max(0, int(downloaded * 10 / total)))
        if bucket == last_bucket:
            return
        last_bucket = bucket
        print(
            json.dumps(
                {
                    "event": "download_progress",
                    "component_id": component_id,
                    "downloaded": downloaded,
                    "total": total,
                    "percent": bucket * 10,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    return report


def validate(
    components: Sequence[str],
    *,
    root: Path,
    expected_platform_key: str | None = None,
) -> int:
    root.mkdir(parents=True, exist_ok=True)
    for component_id in components:
        descriptor = describe_component(component_id)
        if (
            expected_platform_key is not None
            and descriptor.platform_key != expected_platform_key
        ):
            print(
                json.dumps(
                    {
                        "event": "platform_mismatch",
                        "component_id": component_id,
                        "actual_platform_key": descriptor.platform_key,
                        "expected_platform_key": expected_platform_key,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return 1
        print(
            json.dumps(
                {
                    "event": "validation_start",
                    "component_id": component_id,
                    "platform_key": descriptor.platform_key,
                    "version": descriptor.version,
                    "download_size_bytes": descriptor.total_download_size,
                    "install_backend": descriptor.install_backend,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        receipt = install_component(
            component_id,
            root=root,
            progress_cb=_progress(component_id),
        )
        invalidate_probe_cache(component_id)
        report = probe_component(component_id, root=root)
        print(
            json.dumps(
                {
                    "event": "validation_result",
                    "component_id": component_id,
                    "platform_key": report.platform_key,
                    "version": report.version,
                    "ready": report.ready,
                    "reason": report.reason,
                    "receipt_id": receipt.receipt_id,
                    "artifact_sha256": receipt.sha256,
                    "install_backend": receipt.install_backend,
                    "binaries": sorted(report.binaries),
                    "resources": sorted(report.resources),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if not report.ready:
            return 1
    return 0


def main() -> int:
    args = _parser().parse_args()
    components = tuple(args.components or component_ids())
    root = _validation_root(args.root)
    print(json.dumps({"event": "validation_root", "path": str(root)}, sort_keys=True))
    return validate(
        components,
        root=root,
        expected_platform_key=args.expect_platform_key,
    )


if __name__ == "__main__":
    raise SystemExit(main())
