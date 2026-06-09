#!/usr/bin/env python3
"""Generate images via OpenRouter (default google/gemini-3.1-flash-image-preview).

Pipeline: OpenRouter `/api/v1/chat/completions` with
`modalities=["image", "text"]`. The response carries a base64 data URL
in `choices[0].message.images[0].image_url.url`.

Resilience knobs (the meta-skill uses them; raw CLI users can opt in):

  --max-retries N           extra retries on the PRIMARY model (default 0).
  --fallback-model M ...    repeatable: try each model once after the
                            primary exhausts its retries.
  --placeholder-on-fail     when every model fails (typically moderation
                            refusing the prompt), emit a 720x1280
                            solid-colour PNG with a "Scene placeholder"
                            label so downstream merge steps still have a
                            file in this slot. Off by default.

Usage:
    python generate_image.py --prompt "..." --filename "out.png" \\
        [--input-image PATH] [--aspect-ratio 9:16] [--image-size 1K|2K|4K] \\
        [--model google/gemini-3.1-flash-image-preview] \\
        [--max-retries 1] [--fallback-model google/gemini-3-pro-image-preview] \\
        [--placeholder-on-fail] [--api-key KEY]

Auth:
    1. --api-key argument
    2. OPENROUTER_API_KEY environment variable
    3. OPENSQUILLA_LLM_API_KEY when the effective LLM provider is openrouter
    4. llm.api_key / llm.api_key_env from the selected OpenSquilla config

Output: prints the absolute path of the saved PNG on stdout.
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
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_MODEL = "google/gemini-3.1-flash-image-preview"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

# Mirrors src/opensquilla/provider/openrouter_attribution.py — kept inline so
# this script can run as a standalone subprocess without importing the
# opensquilla package. Keep the three constants and the predicate in sync if
# the canonical helper changes.
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

    Bundled skills run as detached Python subprocesses and cannot import
    opensquilla itself, so this duplicates the config-discovery logic
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


def resolve_api_key(provided: str | None) -> str | None:
    if provided:
        key = provided.strip()
        if key:
            return key
    val = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if val:
        return val
    llm = _selected_llm_config()
    return _openrouter_llm_env_key(llm) or _openrouter_key_from_config(llm)


def encode_input_image(path: str) -> str:
    raw = Path(path).read_bytes()
    suffix = Path(path).suffix.lower().lstrip(".")
    mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def build_payload(prompt: str, input_image: str | None, aspect_ratio: str, image_size: str, model: str) -> dict:
    user_content: list = [{"type": "text", "text": prompt}]
    if input_image:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": encode_input_image(input_image)},
            }
        )
    return {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "modalities": ["image", "text"],
        "stream": False,
        "image_config": {
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        },
    }


def extract_image_url(data: dict) -> str | None:
    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        for image in message.get("images") or []:
            image_url = image.get("image_url") or image.get("imageUrl") or {}
            url = image_url.get("url")
            if isinstance(url, str) and url:
                return url
    return None


def extract_finish_reason(data: dict) -> str | None:
    """OpenRouter signals moderation refusals via native_finish_reason."""
    for choice in data.get("choices") or []:
        for key in ("native_finish_reason", "finish_reason"):
            val = choice.get(key)
            if isinstance(val, str) and val:
                return val
    return None


def decode_data_url(data_url: str) -> bytes:
    prefix, sep, encoded = data_url.partition(",")
    if not sep or ";base64" not in prefix:
        raise RuntimeError("OpenRouter returned a non-base64 image URL")
    return base64.b64decode(encoded)


def post_chat_completions(base_url: str, api_key: str, payload: dict, timeout: int) -> dict:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(_openrouter_attribution_headers(url))
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {body_text}") from exc


def _try_one_attempt(
    *,
    base_url: str,
    api_key: str,
    prompt: str,
    input_image: str | None,
    aspect_ratio: str,
    image_size: str,
    model: str,
    timeout: int,
) -> bytes:
    """Single network round-trip. Raises RuntimeError on any failure."""
    payload = build_payload(prompt, input_image, aspect_ratio, image_size, model)
    data = post_chat_completions(base_url, api_key, payload, timeout)
    image_url = extract_image_url(data)
    if not image_url:
        reason = extract_finish_reason(data) or "unknown"
        head = json.dumps(data, ensure_ascii=False)[:600]
        raise RuntimeError(f"no image (finish_reason={reason}); head={head}")
    return decode_data_url(image_url)


def _write_placeholder_png(out_path: Path, prompt: str, aspect_ratio: str) -> None:
    """Last-resort 720x1280 solid-colour PNG with a short label so merge can run."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Pillow not installed; cannot write placeholder. "
            "pip install pillow or disable --placeholder-on-fail."
        ) from exc

    width, height = {
        "9:16": (720, 1280),
        "16:9": (1280, 720),
        "1:1": (1024, 1024),
        "3:2": (1080, 720),
        "2:3": (720, 1080),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
    }.get(aspect_ratio, (720, 1280))

    img = Image.new("RGB", (width, height), color=(28, 30, 38))
    draw = ImageDraw.Draw(img)
    title = "Scene placeholder"
    subtitle = "(image model refused this prompt)"
    snippet = prompt.strip().split("\n", 1)[0][:120]
    try:
        font_title = ImageFont.truetype("arial.ttf", 36)
        font_body = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    def _center(text: str, y: int, font) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        draw.text(((width - text_w) // 2, y), text, fill=(220, 220, 230), font=font)

    _center(title, height // 2 - 80, font_title)
    _center(subtitle, height // 2 - 30, font_body)
    # Wrap snippet to ~40 chars per line
    line = ""
    y = height // 2 + 30
    for word in snippet.split():
        if len(line) + len(word) + 1 > 40:
            _center(line, y, font_body)
            y += 28
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        _center(line, y, font_body)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", "-p", required=True)
    parser.add_argument("--filename", "-f", required=True, help="Output filename (.png)")
    parser.add_argument("--input-image", "-i", help="Optional reference image path")
    parser.add_argument("--aspect-ratio", default="1:1", choices=["1:1", "3:2", "2:3", "16:9", "9:16", "4:3", "3:4"])
    parser.add_argument("--image-size", default="1K", choices=["1K", "2K", "4K"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--max-retries", type=int, default=0,
        help="Extra retries on the PRIMARY model before moving on to --fallback-model entries. Default 0.",
    )
    parser.add_argument(
        "--fallback-model", action="append", default=[],
        help="Repeatable. Each is tried ONCE after the primary model exhausts its retries.",
    )
    parser.add_argument(
        "--placeholder-on-fail", default="no", choices=["yes", "no"],
        help="When every model refuses, write a solid-colour placeholder PNG instead of exiting non-zero. Default no.",
    )
    parser.add_argument(
        "--retry-backoff-cap", type=int, default=8,
        help="Maximum sleep seconds between retries (exponential backoff capped here).",
    )
    parser.add_argument("--api-key", "-k")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print(
            "Error: no OpenRouter API key found. Pass --api-key, set "
            "OPENROUTER_API_KEY, or configure an OpenRouter llm key in "
            "OpenSquilla config.",
            file=sys.stderr,
        )
        return 1

    if args.input_image and not Path(args.input_image).is_file():
        print(f"Error: --input-image not found: {args.input_image}", file=sys.stderr)
        return 1

    # Build the attempt schedule:
    #   primary model gets (1 + max_retries) shots, then each fallback gets one.
    max_retries = max(0, args.max_retries)
    fallback_models = [m for m in (args.fallback_model or []) if m]
    schedule: list[tuple[str, int, int]] = []  # (model, attempt_index_in_model, total_for_model)
    for i in range(1 + max_retries):
        schedule.append((args.model, i + 1, 1 + max_retries))
    for fm in fallback_models:
        schedule.append((fm, 1, 1))

    out_path = Path(args.filename).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    last_error: str | None = None
    for attempt_idx, (model, n, total) in enumerate(schedule, start=1):
        print(
            f"==> [{attempt_idx}/{len(schedule)}] model={model} (attempt {n}/{total})",
            file=sys.stderr,
        )
        try:
            image_bytes = _try_one_attempt(
                base_url=args.base_url,
                api_key=api_key,
                prompt=args.prompt,
                input_image=args.input_image,
                aspect_ratio=args.aspect_ratio,
                image_size=args.image_size,
                model=model,
                timeout=args.timeout,
            )
            out_path.write_bytes(image_bytes)
            print(str(out_path))
            return 0
        except Exception as exc:  # noqa: BLE001 - we want to capture and continue
            last_error = f"[{model} #{n}] {exc}"
            print(f"  {last_error}", file=sys.stderr)
            if attempt_idx < len(schedule):
                backoff = min(2 ** n, args.retry_backoff_cap)
                print(f"  sleeping {backoff}s before next attempt", file=sys.stderr)
                time.sleep(backoff)

    # All real model attempts failed. Maybe fall back to a placeholder PNG.
    if args.placeholder_on_fail == "yes":
        print(
            f"All {len(schedule)} model attempt(s) failed; writing placeholder PNG. Last error: {last_error}",
            file=sys.stderr,
        )
        try:
            _write_placeholder_png(out_path, args.prompt, args.aspect_ratio)
        except Exception as exc:  # noqa: BLE001
            print(f"Error: placeholder generation failed: {exc}", file=sys.stderr)
            return 1
        print(str(out_path))
        return 0

    print(
        f"Error: all {len(schedule)} model attempt(s) failed. Last: {last_error}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
