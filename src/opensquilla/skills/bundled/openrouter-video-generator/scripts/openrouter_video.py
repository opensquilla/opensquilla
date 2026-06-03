#!/usr/bin/env python3
"""OpenRouter video entrypoint for meta-skill ``skill_exec`` steps."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}


def _safe_filename(value: str, default: str) -> str:
    name = Path(value or default).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not name:
        name = default
    if not name.lower().endswith(".mp4"):
        name = re.sub(r"\.[A-Za-z0-9]+$", "", name) + ".mp4"
    return name


def _preview(text: str) -> str:
    return " ".join(text.split())[:80]


def _print_record(label: str, payload: dict[str, object]) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}")


def _failure(label: str, filename: str, **extra: object) -> None:
    payload: dict[str, object] = {
        "replacement_slot": f"project/assets/video/{filename}",
    }
    payload.update(extra)
    _print_record(label, payload)


def _request_json(
    url: str,
    *,
    key: str,
    method: str = "GET",
    body: dict[str, object] | None = None,
    timeout: float = 60.0,
) -> dict[str, object]:
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        parsed = json.loads(resp.read().decode("utf-8", "replace"))
    if not isinstance(parsed, dict):
        raise ValueError("response_not_object")
    return parsed


def _download(url: str, *, key: str, timeout: float = 120.0) -> bytes:
    req = Request(url, headers={"Authorization": f"Bearer {key}"}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--filename", default="intro.mp4")
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--max-wait", type=float, default=300.0)
    args = parser.parse_args()

    filename = _safe_filename(args.filename, "intro.mp4")
    prompt = sys.stdin.read().strip()
    if not prompt:
        prompt = "Create a short browser-playable video for this webpage."

    key = os.environ.get("OPENROUTER_API_KEY")
    missing = []
    if not key:
        missing.append("OPENROUTER_API_KEY")
    if not args.model:
        missing.append("awesome_webpage.openrouter.models.video_generation")
    if not args.output_dir:
        missing.append("awesome_webpage.output_dir")
    if missing:
        _failure("VIDEO_CONFIG_NEEDED", filename, missing=missing)
        return 0

    output_dir = Path(args.output_dir).expanduser()
    output_path = output_dir / filename
    local_path = f"project/assets/video/{filename}"
    base_url = args.base_url.rstrip("/")

    try:
        submit = _request_json(
            f"{base_url}/videos",
            key=key,
            method="POST",
            body={
                "model": args.model,
                "prompt": prompt,
                "duration": args.duration,
                "aspect_ratio": args.aspect_ratio,
            },
        )
    except HTTPError as exc:
        _failure("VIDEO_GENERATION_FAILED", filename, phase="submit", status=exc.code)
        return 0
    except (URLError, ValueError) as exc:
        _failure(
            "VIDEO_GENERATION_FAILED",
            filename,
            phase="submit",
            reason=exc.__class__.__name__,
        )
        return 0

    job_id = str(submit.get("id") or "")
    poll_url = str(submit.get("polling_url") or f"{base_url}/videos/{job_id}")
    last = submit
    status = str(last.get("status") or "pending")
    deadline = time.time() + max(1.0, args.max_wait)
    while status not in TERMINAL_STATUSES and time.time() < deadline:
        time.sleep(max(1.0, args.poll_interval))
        try:
            last = _request_json(poll_url, key=key)
        except HTTPError as exc:
            _failure(
                "VIDEO_GENERATION_FAILED",
                filename,
                phase="poll",
                status=exc.code,
                job_id=job_id,
            )
            return 0
        except (URLError, ValueError) as exc:
            _failure(
                "VIDEO_GENERATION_FAILED",
                filename,
                phase="poll",
                reason=exc.__class__.__name__,
                job_id=job_id,
            )
            return 0
        status = str(last.get("status") or "unknown")

    if status != "completed":
        _failure("VIDEO_GENERATION_FAILED", filename, status=status, job_id=job_id)
        return 0

    urls = last.get("unsigned_urls") or last.get("urls") or []
    if not isinstance(urls, list) or not urls:
        _failure("VIDEO_MODEL_UNSUPPORTED", filename, reason="no_download_url", job_id=job_id)
        return 0

    try:
        body = _download(str(urls[0]), key=key)
    except HTTPError as exc:
        _failure(
            "VIDEO_GENERATION_FAILED",
            filename,
            phase="download",
            status=exc.code,
            job_id=job_id,
        )
        return 0
    except URLError as exc:
        _failure(
            "VIDEO_GENERATION_FAILED",
            filename,
            phase="download",
            reason=exc.reason.__class__.__name__,
            job_id=job_id,
        )
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body)
    _print_record(
        "VIDEO_READY",
        {
            "local_path": local_path,
            "mime": "video/mp4",
            "duration_s": args.duration,
            "resolution": None,
            "prompt_preview": _preview(prompt),
            "job_id": job_id,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
