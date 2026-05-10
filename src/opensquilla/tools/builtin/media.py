"""Media built-in tools: image, image_generate, pdf, tts."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from opensquilla.env import trust_env as _trust_env
from opensquilla.provider.image_generation import (
    ImageGenerationRequest,
    generate_with_fallbacks,
    get_image_generation_provider,
    list_image_generation_providers,
    parse_image_generation_model_ref,
    reset_image_generation_providers,
)
from opensquilla.tools.registry import tool
from opensquilla.tools.ssrf import validate_http_url_for_fetch
from opensquilla.tools.types import (
    SafeToolError,
    SSRFBlockedError,
    ToolError,
    UnsupportedURLSchemeError,
    current_tool_context,
)

_SUPPORTED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "webp"}
_IMAGE_SIZE_LIMIT = 20 * 1024 * 1024  # 20 MB
_PDF_TEXT_LIMIT = 50_000
_TTS_VALID_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
_MAX_REDIRECTS = 5
_image_generation_config: Any | None = None


def configure_image_generation(config: Any | None, *, llm_config: Any | None = None) -> None:
    global _image_generation_config
    _image_generation_config = config
    reset_image_generation_providers(config, llm_config=llm_config)


# ---------------------------------------------------------------------------
# image
# ---------------------------------------------------------------------------


@tool(
    name="image",
    description=(
        "Analyze an image using a vision-capable model. "
        "Accepts a local file path or HTTP(S) URL. "
        "Returns the model's text analysis of the image."
    ),
    params={
        "path": {
            "type": "string",
            "description": "Local file path or HTTP(S) URL to the image.",
        },
        "prompt": {
            "type": "string",
            "description": "What to analyze or describe about the image.",
        },
    },
    required=["path", "prompt"],
)
async def image(path: str, prompt: str = "Describe this image") -> str:
    if not prompt or not prompt.strip():
        raise ToolError("Prompt must not be empty")

    is_url = path.startswith("http://") or path.startswith("https://")

    if is_url:
        url_block = _sensitive_media_url_block("image", path)
        if url_block is not None:
            return json.dumps(url_block)
        image_bytes, media_type = await _fetch_image_url(path)
    else:
        p = _resolve_media_path(path)
        path_block = _sensitive_media_path_block("image", p, path)
        if path_block is not None:
            return json.dumps(path_block)
        image_bytes, media_type = await _read_image_file(path)

    # Validate not corrupt using Pillow
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
    except Exception as exc:
        raise ToolError(f"Image appears corrupt or unreadable: {exc}") from exc

    # Try provider vision call; graceful fallback if unavailable
    b64_data = base64.b64encode(image_bytes).decode()
    try:
        description = await _call_vision_provider(b64_data, media_type, prompt)
        model_used = "provider"
    except ToolError:
        raise
    except Exception:
        return json.dumps(
            {
                "status": "not_available",
                "note": "Vision provider not configured or unavailable",
                "path": path,
            }
        )

    return json.dumps({"description": description, "model": model_used, "path": path})


async def _read_image_file(path: str) -> tuple[bytes, str]:
    p = _resolve_media_path(path)
    if not p.exists():
        raise ToolError(f"Image file not found: {path}")
    ext = p.suffix.lstrip(".").lower()
    if ext not in _SUPPORTED_IMAGE_FORMATS:
        raise ToolError(
            f"Unsupported image format: {ext}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_IMAGE_FORMATS))}"
        )
    loop = asyncio.get_event_loop()
    image_bytes: bytes = await loop.run_in_executor(None, p.read_bytes)
    if len(image_bytes) > _IMAGE_SIZE_LIMIT:
        raise ToolError("Image exceeds 20MB size limit")
    media_type = _ext_to_mime(ext)
    return image_bytes, media_type


def _resolve_media_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    ctx = current_tool_context.get()
    if ctx and ctx.workspace_dir:
        return (Path(ctx.workspace_dir).expanduser() / candidate).resolve(strict=False)
    return candidate.resolve(strict=False)


def _sensitive_media_path_block(tool_name: str, resolved: Path, original_path: str) -> dict | None:
    from opensquilla.sandbox.sensitive_paths import build_block_envelope, is_sensitive_path
    from opensquilla.tools.builtin.shell import _context_elevated_mode

    if _context_elevated_mode() == "full":
        return None
    sensitive = is_sensitive_path(str(resolved))
    if sensitive is None:
        return None
    return build_block_envelope(f"{tool_name} {original_path}", sensitive, tool_name=tool_name)


def _sensitive_media_url_block(tool_name: str, url: str) -> dict | None:
    from opensquilla.tools.builtin.web import _sensitive_url_marker

    marker = _sensitive_url_marker(url)
    if marker is None:
        return None
    return {
        "status": "blocked",
        "reason": "sensitive_payload",
        "tool": tool_name,
        "sensitive_payload": marker,
        "message": (
            "Refusing to fetch a media URL whose query string appears to contain "
            "secrets or host account data."
        ),
        "retryable": False,
    }


async def _fetch_image_url(url: str) -> tuple[bytes, str]:
    import httpx

    def _check_image_url(candidate_url: str) -> None:
        marker = _sensitive_media_url_block("image", candidate_url)
        if marker is not None:
            raise ToolError("Blocked: URL contains sensitive data")
        try:
            validate_http_url_for_fetch(candidate_url)
        except UnsupportedURLSchemeError as exc:
            raise ToolError("Only HTTP/HTTPS URLs are supported for image fetch") from exc
        except SSRFBlockedError as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=False, trust_env=_trust_env()
        ) as client:
            current_url = url
            for _redirect_count in range(_MAX_REDIRECTS + 1):
                _check_image_url(current_url)
                resp = await client.get(current_url)
                if resp.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = resp.headers.get("location")
                if not location:
                    break
                current_url = urljoin(str(resp.url), location)
            else:
                raise ToolError(f"Too many redirects (>{_MAX_REDIRECTS})")
            resp.raise_for_status()
            image_bytes = resp.content
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"Failed to fetch image from URL: {exc}") from exc

    if len(image_bytes) > _IMAGE_SIZE_LIMIT:
        raise ToolError("Image exceeds 20MB size limit")

    # Detect format from content-type or URL extension
    content_type = resp.headers.get("content-type", "")
    final_parsed = urlparse(str(resp.url))
    ext = _mime_to_ext(content_type) or Path(final_parsed.path).suffix.lstrip(".").lower()
    if ext not in _SUPPORTED_IMAGE_FORMATS:
        raise ToolError(
            f"Unsupported image format: {ext}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_IMAGE_FORMATS))}"
        )
    return image_bytes, _ext_to_mime(ext)


def _ext_to_mime(ext: str) -> str:
    mapping = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    return mapping.get(ext, "image/png")


def _mime_to_ext(content_type: str) -> str:
    ct = content_type.split(";")[0].strip().lower()
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/gif": "gif",
        "image/webp": "webp",
    }
    return mapping.get(ct, "")


async def _complete_from_stream(provider: Any, messages: list, config: Any = None) -> str:
    """Consume a chat() stream and return the assembled text response."""
    text_parts: list[str] = []
    async for event in provider.chat(messages=messages, config=config):
        if hasattr(event, "text"):
            text_parts.append(event.text)
        elif hasattr(event, "delta") and isinstance(event.delta, str):
            text_parts.append(event.delta)
    return "".join(text_parts)


async def _call_vision_provider(b64_data: str, media_type: str, prompt: str) -> str:
    """Send image to provider vision API. Raises if provider not available."""
    try:
        from opensquilla.provider.selector import ModelSelector, SelectorConfig

        cfg = _resolve_provider_config("VISION", default_model="openai/gpt-4o-mini")
        selector = ModelSelector(SelectorConfig(primary=cfg))
        provider = selector.resolve()
    except Exception as exc:
        raise RuntimeError(f"Provider not available: {exc}") from exc

    vision_message = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_data,
                },
            },
            {"type": "text", "text": prompt},
        ],
    }
    return await _complete_from_stream(provider, [vision_message])


# ---------------------------------------------------------------------------
# image_generate
# ---------------------------------------------------------------------------


@tool(
    name="image_generate",
    description=(
        "Generate an image from a text prompt using a configured image provider. "
        "For code, HTML, SVG, canvas, or screenshot based image artifacts, use "
        "the appropriate code/runtime/rendering tool instead."
    ),
    params={
        "prompt": {
            "type": "string",
            "description": "Text description of the image to generate.",
        },
        "size": {
            "type": "string",
            "description": 'Image dimensions. One of "1024x1024", "1536x1024", "1024x1536".',
            "enum": ["1024x1024", "1536x1024", "1024x1536"],
        },
        "model": {
            "type": "string",
            "description": 'Optional provider/model identifier, e.g. "openai/gpt-image-1".',
        },
        "filename": {
            "type": "string",
            "description": "Optional output filename or relative path.",
        },
    },
    required=["prompt"],
)
async def image_generate(
    prompt: str,
    size: str = "1024x1024",
    model: str | None = None,
    filename: str | None = None,
) -> str:
    return await _image_generate_impl(prompt=prompt, size=size, model=model, filename=filename)


async def _image_generate_impl(
    *,
    prompt: str,
    size: str,
    model: str | None,
    filename: str | None,
) -> str:
    if not prompt or not prompt.strip():
        raise ToolError("Prompt must not be empty")

    valid_sizes = {"1024x1024", "1536x1024", "1024x1536"}
    if size not in valid_sizes:
        raise ToolError(f"Invalid size: {size}. Must be {' | '.join(sorted(valid_sizes))}")

    config = _resolve_image_generation_config()
    if not getattr(config, "enabled", False):
        raise ToolError("Image generation is disabled")

    candidates = _resolve_image_generation_candidates(model, config)
    if not candidates:
        raise ToolError("Image generation is not configured")

    output_format = getattr(config, "output_format", "png")
    target = _resolve_generated_image_path(filename, output_format)
    try:
        result = await generate_with_fallbacks(
            request=ImageGenerationRequest(
                prompt=prompt,
                model=candidates[0],
                size=size or getattr(config, "size", "1024x1024"),
                output_format=output_format,
                timeout_seconds=float(getattr(config, "timeout_seconds", 180.0)),
            ),
            candidates=candidates,
        )
    except Exception as exc:
        raise ToolError(f"Image generation failed: {exc}") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.image_bytes)
    return json.dumps(
        {
            "status": "ok",
            "path": str(target),
            "provider": result.provider,
            "model": result.model,
            "mime_type": result.mime_type,
            "size_bytes": len(result.image_bytes),
            "revised_prompt": result.revised_prompt,
        }
    )


def _resolve_image_generation_config() -> Any:
    if _image_generation_config is not None:
        return _image_generation_config
    from opensquilla.gateway.config import ImageGenerationConfig

    return ImageGenerationConfig()


def _resolve_image_generation_candidates(model: str | None, config: Any) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        if raw and raw not in seen:
            seen.add(raw)
            candidates.append(raw)

    add(model)
    add(getattr(config, "primary", None))
    for fallback in getattr(config, "fallbacks", []) or []:
        add(fallback)
    primary = getattr(config, "primary", None)
    fallbacks = getattr(config, "fallbacks", []) or []
    has_explicit_model_routing = (
        bool(model) or bool(fallbacks) or bool(primary and primary != "openai/gpt-image-1")
    )
    if not has_explicit_model_routing:
        for provider in list_image_generation_providers():
            if _image_generation_provider_has_auth(provider):
                add(f"{provider.provider_id}/{provider.default_model}")
    return candidates


def image_generation_available(config: Any | None = None) -> bool:
    """Return whether image generation has at least one configured provider."""
    resolved_config = config if config is not None else _resolve_image_generation_config()
    if not getattr(resolved_config, "enabled", False):
        return False

    for candidate in _resolve_image_generation_candidates(None, resolved_config):
        try:
            provider_id, _model = parse_image_generation_model_ref(candidate)
        except ValueError:
            continue
        provider = get_image_generation_provider(provider_id)
        if provider is not None and _image_generation_provider_has_auth(provider):
            return True
    return False


def _image_generation_provider_has_auth(provider: Any) -> bool:
    resolve_api_key = getattr(provider, "_resolve_api_key", None)
    if callable(resolve_api_key):
        try:
            return bool(resolve_api_key())
        except Exception:  # noqa: BLE001 - capability checks must be non-fatal
            return False

    auth_env_vars = tuple(getattr(provider, "auth_env_vars", ()) or ())
    if not auth_env_vars:
        return True
    return any(bool(os.environ.get(env_var)) for env_var in auth_env_vars)


def _resolve_generated_image_path(filename: str | None, output_format: str) -> Path:
    ext = "jpg" if output_format == "jpeg" else output_format
    raw = filename or f"generated-image-{uuid.uuid4().hex[:12]}.{ext}"
    candidate = Path(raw).expanduser()
    if not candidate.suffix:
        candidate = candidate.with_suffix(f".{ext}")

    ctx = current_tool_context.get()
    root = (
        Path(ctx.workspace_dir).expanduser().resolve() if ctx and ctx.workspace_dir else Path.cwd()
    )
    target = candidate if candidate.is_absolute() else root / candidate
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError(f"Image output path is outside workspace: {filename}") from exc
    return resolved


# ---------------------------------------------------------------------------
# pdf
# ---------------------------------------------------------------------------


@tool(
    name="pdf",
    description=(
        "Extract text from a PDF file, optionally filtered by page range. "
        "If a prompt is supplied, the extracted text is sent to the LLM for analysis."
    ),
    params={
        "path": {
            "type": "string",
            "description": "File path to the PDF.",
        },
        "pages": {
            "type": "string",
            "description": (
                'Page range to extract: "1-5", "3", or "1,3,5-10". Omit for all pages.'
            ),
        },
        "prompt": {
            "type": "string",
            "description": "Optional analysis prompt. Sends extracted text to the LLM.",
        },
    },
    required=["path"],
)
async def pdf(
    path: str,
    pages: str | None = None,
    prompt: str | None = None,
) -> str:
    p = _resolve_media_path(path)
    path_block = _sensitive_media_path_block("pdf", p, path)
    if path_block is not None:
        return json.dumps(path_block)
    if not p.exists():
        raise SafeToolError(f"PDF file not found: {path} (resolved={p})")

    try:
        import pdfplumber
    except ImportError as exc:
        raise SafeToolError("pdfplumber is not installed") from exc

    loop = asyncio.get_event_loop()

    def _extract() -> dict[str, Any]:
        try:
            with pdfplumber.open(str(p)) as doc:
                total_pages = len(doc.pages)

                # Resolve page indices (0-based)
                if pages:
                    indices = _parse_page_range(pages, total_pages)
                else:
                    indices = list(range(total_pages))

                texts: list[str] = []
                for idx in indices:
                    page_text = doc.pages[idx].extract_text() or ""
                    texts.append(page_text)

                extracted = "\n\n".join(t for t in texts if t)
                return {"total_pages": total_pages, "text": extracted}
        except ToolError:
            raise
        except Exception as exc:
            err_msg = str(exc).lower()
            if "password" in err_msg or "encrypted" in err_msg:
                raise SafeToolError("PDF is password-protected") from exc
            raise SafeToolError(f"File is not a valid PDF: {path} (resolved={p})") from exc

    result = await loop.run_in_executor(None, _extract)
    total_pages: int = result["total_pages"]
    extracted_text: str = result["text"]

    if not extracted_text.strip():
        raise SafeToolError("No extractable text found - PDF may be image-only")

    # Truncate
    truncated = len(extracted_text) > _PDF_TEXT_LIMIT
    if truncated:
        extracted_text = extracted_text[:_PDF_TEXT_LIMIT]

    page_desc = pages if pages else f"1-{total_pages}"

    if prompt and prompt.strip():
        # Send to LLM for analysis
        analysis = await _call_llm_with_text(extracted_text, prompt)
        return json.dumps(
            {
                "path": path,
                "pages": page_desc,
                "total_pages": total_pages,
                "analysis": analysis,
                "truncated": truncated,
            }
        )

    return json.dumps(
        {
            "path": path,
            "pages": page_desc,
            "total_pages": total_pages,
            "text": extracted_text,
            "truncated": truncated,
        }
    )


def _parse_page_range(pages: str, total: int) -> list[int]:
    """Parse page range string to 0-based index list."""
    indices: list[int] = []
    segments = [s.strip() for s in pages.split(",")]
    for seg in segments:
        if not seg:
            continue
        if "-" in seg:
            parts = seg.split("-", 1)
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise SafeToolError(f"Invalid page range: {pages}")
            start, end = int(parts[0]), int(parts[1])
            if start < 1 or end < start:
                raise SafeToolError(f"Invalid page range: {pages}")
            for n in range(start, end + 1):
                if n > total:
                    raise SafeToolError(f"Page {n} exceeds document length ({total} pages)")
                indices.append(n - 1)
        elif re.match(r"^\d+$", seg):
            n = int(seg)
            if n < 1:
                raise SafeToolError(f"Invalid page range: {pages}")
            if n > total:
                raise SafeToolError(f"Page {n} exceeds document length ({total} pages)")
            indices.append(n - 1)
        else:
            raise SafeToolError(f"Invalid page range: {pages}")
    return indices


async def _call_llm_with_text(text: str, prompt: str) -> str:
    """Send extracted text to LLM with analysis prompt. Graceful fallback."""
    try:
        from opensquilla.provider.selector import ModelSelector, SelectorConfig

        cfg = _resolve_provider_config("LLM", default_model="openai/gpt-4o-mini")
        selector = ModelSelector(SelectorConfig(primary=cfg))
        provider = selector.resolve()
        message = {
            "role": "user",
            "content": f"{prompt}\n\n---\n{text}",
        }
        return await _complete_from_stream(provider, [message])
    except Exception:
        return f"[LLM analysis not available] Extracted text ({len(text)} chars) ready."


def _resolve_provider_config(scope: str, *, default_model: str):
    from opensquilla.provider.selector import ProviderConfig

    provider_name = (
        os.environ.get(f"OPENSQUILLA_{scope}_PROVIDER")
        or os.environ.get("OPENSQUILLA_LLM_PROVIDER")
        or "openrouter"
    )
    model = (
        os.environ.get(f"OPENSQUILLA_{scope}_MODEL")
        or os.environ.get("OPENSQUILLA_LLM_MODEL")
        or default_model
    )

    if provider_name == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    elif provider_name == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_BASE_URL", "")

    return ProviderConfig(
        provider=provider_name,
        model=model,
        api_key=api_key,
        base_url=base_url,
        proxy=os.environ.get("OPENSQUILLA_LLM_PROXY", ""),
    )


# ---------------------------------------------------------------------------
# tts
# ---------------------------------------------------------------------------


@tool(
    name="tts",
    description=(
        "Synthesize text to speech audio using a TTS provider. "
        "Returns an explicit not_available envelope when no TTS provider is configured."
    ),
    params={
        "text": {
            "type": "string",
            "description": "Text to synthesize (max 4096 characters).",
        },
        "voice": {
            "type": "string",
            "description": (
                "Voice identifier. Available: alloy, echo, fable, onyx, nova, shimmer."
            ),
        },
        "output_path": {
            "type": "string",
            "description": "Output file path. Auto-generated if omitted.",
        },
        "speed": {
            "type": "number",
            "description": "Playback speed multiplier (0.25 to 4.0, default 1.0).",
            "minimum": 0.25,
            "maximum": 4.0,
        },
    },
    required=["text"],
)
async def tts(
    text: str,
    voice: str = "alloy",
    output_path: str | None = None,
    speed: float = 1.0,
) -> str:
    if not text or not text.strip():
        raise ToolError("Text must not be empty")

    if len(text) > 4096:
        raise ToolError(f"Text exceeds 4096 character limit ({len(text)} chars)")

    if voice not in _TTS_VALID_VOICES:
        raise ToolError(
            f"Unknown voice: {voice}. Available: {', '.join(sorted(_TTS_VALID_VOICES))}"
        )

    if speed < 0.25 or speed > 4.0:
        raise ToolError("Speed must be between 0.25 and 4.0")

    return json.dumps(
        {
            "status": "not_available",
            "note": "TTS provider not configured",
            "voice": voice,
            "text_length": len(text),
        }
    )
