#!/usr/bin/env python3
"""Generate a short video via Seedance 2.0 (OpenRouter or Volcengine/BytePlus).

Two providers are supported with the same submit-then-poll lifecycle but
slightly different request/response shapes. Select with --provider.

  openrouter  (default)
    POST https://openrouter.ai/api/v1/videos
    Body:  {model, prompt, aspect_ratio, duration,
            frame_images?, input_references?}
    Resp:  {id, polling_url, status}
    Auth:  Authorization: Bearer $OPENROUTER_API_KEY
    Poll:  GET <polling_url>
    Done:  status in {completed}; download from top-level unsigned_urls[0]
    Models e.g. bytedance/seedance-2.0, bytedance/seedance-2.0-fast.

  volcengine                                  (CN region, official Ark)
  byteplus                                    (international, BytePlus ModelArk)
    POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
         (or https://ark.ap-southeast.bytepluses.com/api/v3/...)
    Body:  {model, content: [{type:"text", text:"..."},
                              {type:"image_url", image_url:{url:"..."}}],
            resolution, ratio, duration, watermark:false}
    Resp:  {id}
    Auth:  Authorization: Bearer $ARK_API_KEY
    Poll:  GET <base>/contents/generations/tasks/<id>
    Done:  status in {succeeded}; download from content.video_url
    Models e.g. doubao-seedance-2-0-260128 (CN),
                dreamina-seedance-2-0-260128 (intl).

Usage:
    python generate_video.py --prompt "..." --filename "out.mp4" \\
        [--provider openrouter|volcengine|byteplus] \\
        [--input-image PATH] [--input-reference PATH] \\
        [--aspect-ratio 9:16] [--duration 5] [--resolution 720p] \\
        [--model MODEL_ID] [--api-key KEY] [--base-url URL]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

TERMINAL_STATES = {
    "completed", "succeeded",
    "failed", "cancelled", "expired",
}
SUCCESS_STATES = {"completed", "succeeded"}

# Mirrors src/opensquilla/provider/openrouter_attribution.py — kept inline so
# this script can run as a standalone subprocess without importing the
# opensquilla package. Volcengine / BytePlus URLs DO NOT receive these
# headers (the predicate gates by host).
_OPENROUTER_APP_REFERER = "https://opensquilla.ai"
_OPENROUTER_APP_TITLE = "OpenSquilla"
_OPENROUTER_APP_CATEGORIES = "cli-agent,personal-agent"


def _is_openrouter_url(url: str | None) -> bool:
    if not url:
        return False
    raw = url.strip()
    if not raw:
        return False
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    return host == "openrouter.ai" or host.endswith(".openrouter.ai")


def _openrouter_attribution_headers(url: str | None) -> dict[str, str]:
    if not _is_openrouter_url(url):
        return {}
    return {
        "HTTP-Referer": _OPENROUTER_APP_REFERER,
        "X-OpenRouter-Title": _OPENROUTER_APP_TITLE,
        "X-OpenRouter-Categories": _OPENROUTER_APP_CATEGORIES,
    }


# -------- provider config -----------------------------------------------------


@dataclass(frozen=True)
class Provider:
    name: str
    default_base_url: str
    default_model: str
    default_env: tuple[str, ...]
    submit_path: str
    polls_url_in_response: bool  # True = use submit response's polling_url;
                                 # False = construct from id
    build_payload: Callable[[Args], dict]
    extract_url: Callable[[dict], str | None]


def _build_openrouter_payload(args: Args) -> dict:
    user_prompt = args.prompt
    payload: dict = {
        "model": args.model,
        "prompt": user_prompt,
        "aspect_ratio": args.aspect_ratio,
        "duration": int(args.duration),
    }
    # frame_images locks the literal first/last frame.
    # input_references is a softer identity/style anchor — same picture can be
    # shared across multiple shots to keep the character consistent.
    # If both are provided OpenRouter prefers frame_images.
    if args.input_image:
        payload["frame_images"] = [
            {
                "type": "image_url",
                "image_url": {"url": _encode_input_image(args.input_image)},
                "frame_type": "first_frame",
            }
        ]
    elif args.input_references:
        refs = [r for r in args.input_references if r]
        if refs:
            payload["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": _encode_input_image(r)},
                }
                for r in refs
            ]
    return payload


def _build_volcengine_payload(args: Args) -> dict:
    """Volcengine ARK / BytePlus ModelArk shape — content[] array."""
    content: list = [{"type": "text", "text": args.prompt}]
    # First-frame image
    if args.input_image:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _encode_input_image(args.input_image)},
                # ARK uses a "role" field for first/last frame, optional
                "role": "first_frame",
            }
        )
    # Style/identity references (no role marker — just stacked images)
    for ref in args.input_references or []:
        if ref:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _encode_input_image(ref)},
                }
            )
    payload: dict = {
        "model": args.model,
        "content": content,
        "ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "duration": int(args.duration),
        "watermark": False,
    }
    return payload


def _extract_openrouter_url(job: dict) -> str | None:
    """Top-level unsigned_urls[0] is the canonical OpenRouter path."""
    # Top-level url lists are where OpenRouter currently puts the video.
    for key in ("unsigned_urls", "urls"):
        urls = job.get(key) or []
        if isinstance(urls, list) and urls:
            first = urls[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict) and isinstance(first.get("url"), str):
                return first["url"]
    # Nested videos[] (older shape some routes still emit)
    videos = job.get("videos") or job.get("output") or []
    if isinstance(videos, dict):
        videos = [videos]
    for v in videos if isinstance(videos, list) else []:
        if not isinstance(v, dict):
            continue
        for key in ("url", "content_url", "download_url"):
            url = v.get(key)
            if isinstance(url, str) and url:
                return url
        for key in ("video_url", "videoUrl"):
            obj = v.get(key)
            if isinstance(obj, dict) and isinstance(obj.get("url"), str):
                return obj["url"]
            if isinstance(obj, str) and obj:
                return obj
    # Scalar top-level
    for key in ("content_url", "download_url", "url"):
        url = job.get(key)
        if isinstance(url, str) and url:
            return url
    return None


def _extract_volcengine_url(job: dict) -> str | None:
    """Volcengine puts the final URL at content.video_url."""
    content = job.get("content") or {}
    if isinstance(content, dict):
        url = content.get("video_url")
        if isinstance(url, str) and url:
            return url
    return _extract_openrouter_url(job)  # last-resort, schema can drift


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        name="openrouter",
        default_base_url="https://openrouter.ai/api/v1",
        default_model="bytedance/seedance-2.0",
        default_env=("OPENROUTER_API_KEY",),
        submit_path="/videos",
        polls_url_in_response=True,
        build_payload=_build_openrouter_payload,
        extract_url=_extract_openrouter_url,
    ),
    "volcengine": Provider(
        name="volcengine",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seedance-2-0-260128",
        default_env=("ARK_API_KEY", "VOLC_ARK_API_KEY"),
        submit_path="/contents/generations/tasks",
        polls_url_in_response=False,
        build_payload=_build_volcengine_payload,
        extract_url=_extract_volcengine_url,
    ),
    "byteplus": Provider(
        name="byteplus",
        default_base_url="https://ark.ap-southeast.bytepluses.com/api/v3",
        default_model="dreamina-seedance-2-0-260128",
        default_env=("ARK_API_KEY", "BYTEPLUS_API_KEY"),
        submit_path="/contents/generations/tasks",
        polls_url_in_response=False,
        build_payload=_build_volcengine_payload,
        extract_url=_extract_volcengine_url,
    ),
}


# -------- helpers -------------------------------------------------------------


@dataclass
class Args:
    """Typed mirror of argparse.Namespace, used by per-provider builders."""
    prompt: str
    model: str
    aspect_ratio: str
    duration: int
    resolution: str
    input_image: str
    input_references: list[str]


def _encode_input_image(path: str) -> str:
    raw = Path(path).read_bytes()
    suffix = Path(path).suffix.lower().lstrip(".")
    mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _home_dir() -> Path:
    home = os.environ.get("HOME", "").strip()
    if home:
        return Path(home).expanduser()
    return Path.home()


def _expand_user(path: str) -> Path:
    if path == "~":
        return _home_dir()
    if path.startswith("~/") or path.startswith("~\\"):
        return _home_dir() / path[2:]
    return Path(path).expanduser()


def _default_opensquilla_home() -> Path:
    state_dir = (os.environ.get("OPENSQUILLA_STATE_DIR") or "").strip()
    if state_dir:
        return _expand_user(state_dir)
    return _home_dir() / ".opensquilla"


def _gateway_config_candidates() -> list[Path]:
    config_path = (os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH") or "").strip()
    if config_path:
        return [_expand_user(config_path)]
    return [
        Path.cwd() / "opensquilla.toml",
        _default_opensquilla_home() / "config.toml",
    ]


def _selected_llm_config() -> dict | None:
    """Return the llm table from the config file GatewayConfig would select.

    This intentionally stops at the first existing candidate, matching
    ``GatewayConfig.load``. In particular, ``OPENSQUILLA_STATE_DIR`` replaces
    the default home; it is not a profile layered over ``~/.opensquilla``.
    """
    import tomllib

    for path in _gateway_config_candidates():
        try:
            if not path.is_file():
                continue
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        llm = data.get("llm") if isinstance(data, dict) else None
        return llm if isinstance(llm, dict) else {}
    return None


def _config_llm_provider(llm: dict | None) -> str:
    if llm is None:
        return "openrouter"
    return str(llm.get("provider") or "openrouter").strip().lower()


def _effective_llm_provider(llm: dict | None) -> str:
    if isinstance(llm, dict) and "provider" in llm:
        return _config_llm_provider(llm)
    env_provider = (os.environ.get("OPENSQUILLA_LLM_PROVIDER") or "").strip()
    if env_provider:
        return env_provider.lower()
    return _config_llm_provider(llm)


def _openrouter_llm_env_key(llm: dict | None) -> str | None:
    if _effective_llm_provider(llm) != "openrouter":
        return None
    return (os.environ.get("OPENSQUILLA_LLM_API_KEY") or "").strip() or None


def _openrouter_key_from_config(llm: dict | None) -> str | None:
    """Fallback: read OpenRouter credentials from the selected TOML config.

    Bundled skills run as detached Python subprocesses and cannot
    import opensquilla, so this duplicates the config-discovery logic
    from ``opensquilla.gateway.config.GatewayConfig.load`` and
    ``opensquilla.paths.default_opensquilla_home`` deliberately.
    """
    if not isinstance(llm, dict) or _effective_llm_provider(llm) != "openrouter":
        return None
    key = str(llm.get("api_key") or "").strip()
    if key:
        return key
    key_env = str(llm.get("api_key_env") or "").strip()
    if key_env:
        return (os.environ.get(key_env) or "").strip() or None
    return None


def _resolve_api_key(
    provided: str | None,
    env_names: Iterable[str],
    *,
    provider_name: str = "",
) -> str | None:
    if provided:
        key = provided.strip()
        if key:
            return key
    for name in env_names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    if provider_name == "openrouter":
        llm = _selected_llm_config()
        return _openrouter_llm_env_key(llm) or _openrouter_key_from_config(llm)
    return None


def _http_request(
    method: str,
    url: str,
    api_key: str,
    body: dict | None = None,
    timeout: int = 120,
) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(_openrouter_attribution_headers(url))
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body_text}") from exc


def _fetch_url_to_bytes(url: str, api_key: str, timeout: int) -> bytes:
    if url.startswith("data:"):
        prefix, sep, encoded = url.partition(",")
        if not sep:
            raise RuntimeError("Malformed data URL")
        if ";base64" in prefix:
            return base64.b64decode(encoded)
        return encoded.encode("utf-8")
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"Unsupported URL scheme: {url[:60]}")
    headers: dict[str, str] = {}
    # OpenRouter signs unsigned_urls with the same bearer token; Volcengine
    # URLs are pre-signed object-storage URLs that reject extra auth headers.
    # The attribution helper itself is host-gated so it's safe to call here
    # — it's a no-op for non-OpenRouter hosts.
    if _is_openrouter_url(url):
        headers["Authorization"] = f"Bearer {api_key}"
        headers.update(_openrouter_attribution_headers(url))
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _poll(
    provider: Provider,
    base_url: str,
    api_key: str,
    job_id: str,
    polling_url: str | None,
    timeout_total: int,
    poll_interval: int,
) -> dict:
    deadline = time.time() + timeout_total
    last: dict = {}
    while time.time() < deadline:
        if provider.polls_url_in_response and polling_url:
            url = polling_url
        else:
            url = f"{base_url.rstrip('/')}{provider.submit_path}/{job_id}"
        try:
            last = _http_request("GET", url, api_key, timeout=60)
        except RuntimeError as exc:
            print(f"  poll error (continuing): {exc}", file=sys.stderr)
            time.sleep(poll_interval)
            continue
        status = (last.get("status") or "").lower()
        print(f"  job {job_id} status={status}", file=sys.stderr)
        if status in TERMINAL_STATES:
            return last
        time.sleep(poll_interval)
    raise RuntimeError(
        f"Polling timeout after {timeout_total}s; last status={last.get('status')}"
    )


# -------- single attempt ------------------------------------------------------


class _AttemptError(RuntimeError):
    """Marker for failures that should be retried by the outer loop."""


def _run_attempt(
    *,
    provider: Provider,
    base_url: str,
    submit_url: str,
    api_key: str,
    payload: dict,
    timeout_total: int,
    poll_interval: int,
) -> bytes:
    """Submit → poll → download. Raises _AttemptError on any retryable failure."""
    try:
        submit = _http_request("POST", submit_url, api_key, body=payload, timeout=120)
    except Exception as exc:
        raise _AttemptError(f"submit failed: {exc}") from exc

    job_id = submit.get("id") or submit.get("task_id") or submit.get("job_id")
    polling_url = submit.get("polling_url")
    if not job_id:
        raise _AttemptError(
            "submit response missing job id; raw="
            + json.dumps(submit, ensure_ascii=False)[:600]
        )
    print(f"  job_id={job_id}", file=sys.stderr)

    try:
        final = _poll(
            provider, base_url, api_key, job_id, polling_url,
            timeout_total, poll_interval,
        )
    except Exception as exc:
        raise _AttemptError(f"poll failed: {exc}") from exc

    status = (final.get("status") or "").lower()
    if status not in SUCCESS_STATES:
        err = final.get("error") or final
        raise _AttemptError(
            f"job ended with status={status}: "
            + json.dumps(err, ensure_ascii=False)[:600]
        )

    content_url = provider.extract_url(final)
    if not content_url:
        raise _AttemptError(
            "completed job has no content URL; raw="
            + json.dumps(final, ensure_ascii=False)[:600]
        )

    print(f"==> downloading {content_url[:80]}...", file=sys.stderr)
    try:
        return _fetch_url_to_bytes(content_url, api_key, timeout=600)
    except Exception as exc:
        raise _AttemptError(f"download failed: {exc}") from exc


# -------- main ----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", "-p", required=True)
    parser.add_argument("--filename", "-f", required=True)
    parser.add_argument(
        "--provider", choices=tuple(PROVIDERS), default="openrouter",
        help="Backend API (default: openrouter)",
    )
    parser.add_argument("--input-image", "-i", default="")
    parser.add_argument(
        "--input-reference",
        dest="input_references",
        action="append",
        default=[],
        help="Style/identity reference image path; repeatable. Used only when --input-image is empty.",
    )
    parser.add_argument(
        "--aspect-ratio", default="9:16",
        choices=["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"],
    )
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument(
        "--resolution", default="720p",
        choices=["480p", "720p", "1080p"],
        help="Output resolution (volcengine/byteplus only; ignored by openrouter)",
    )
    parser.add_argument(
        "--model", default="",
        help="Override the model id. Defaults to the provider's recommended model.",
    )
    parser.add_argument("--api-key", "-k", default="")
    parser.add_argument(
        "--base-url", default="",
        help="Override the provider's base URL.",
    )
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--timeout-total", type=int, default=600)
    parser.add_argument(
        "--max-retries", type=int, default=0,
        help="Extra retries on transient submit/poll/download failures or non-success terminal status. 0 = single attempt (default).",
    )
    parser.add_argument(
        "--retry-backoff-cap", type=int, default=15,
        help="Maximum sleep seconds between retries (exponential backoff is capped here).",
    )
    raw = parser.parse_args()

    if not 3 <= raw.duration <= 15:
        print(f"Error: --duration must be 3..15 (got {raw.duration})", file=sys.stderr)
        return 1

    provider = PROVIDERS[raw.provider]
    base_url = raw.base_url or provider.default_base_url
    model_id = raw.model or provider.default_model
    api_key = _resolve_api_key(
        raw.api_key or None, provider.default_env, provider_name=provider.name,
    )
    if not api_key:
        env_hint = " / ".join(provider.default_env)
        if provider.name == "openrouter":
            print(
                "Error: no OpenRouter API key found. Pass --api-key, set "
                "OPENROUTER_API_KEY, or configure an OpenRouter llm key in "
                "OpenSquilla config.",
                file=sys.stderr,
            )
        else:
            print(
                f"Error: no API key. Pass --api-key or set one of: {env_hint}.",
                file=sys.stderr,
            )
        return 1

    if raw.input_image and not Path(raw.input_image).is_file():
        print(f"Error: --input-image not found: {raw.input_image}", file=sys.stderr)
        return 1
    for ref in raw.input_references or []:
        if ref and not Path(ref).is_file():
            print(f"Error: --input-reference not found: {ref}", file=sys.stderr)
            return 1

    args = Args(
        prompt=raw.prompt,
        model=model_id,
        aspect_ratio=raw.aspect_ratio,
        duration=int(raw.duration),
        resolution=raw.resolution,
        input_image=raw.input_image,
        input_references=raw.input_references or [],
    )
    payload = provider.build_payload(args)
    submit_url = base_url.rstrip("/") + provider.submit_path
    out_path = Path(raw.filename).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    max_retries = max(0, raw.max_retries)
    attempts = max_retries + 1
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        print(
            f"==> attempt {attempt}/{attempts} provider={provider.name} "
            f"model={model_id} ({args.duration}s, {args.aspect_ratio}, {args.resolution})",
            file=sys.stderr,
        )
        try:
            video_bytes = _run_attempt(
                provider=provider,
                base_url=base_url,
                submit_url=submit_url,
                api_key=api_key,
                payload=payload,
                timeout_total=raw.timeout_total,
                poll_interval=raw.poll_interval,
            )
            out_path.write_bytes(video_bytes)
            print(str(out_path))
            return 0
        except _AttemptError as exc:
            last_error = str(exc)
            print(f"  attempt {attempt} failed: {last_error}", file=sys.stderr)
            if attempt < attempts:
                backoff = min(2 ** attempt, raw.retry_backoff_cap)
                print(f"  retrying in {backoff}s...", file=sys.stderr)
                time.sleep(backoff)

    print(
        f"Error: all {attempts} attempt(s) failed. Last: {last_error}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
