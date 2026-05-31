"""Media built-in tools: image, image_generate, pdf, tts."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from opensquilla.artifacts import (
    DEFAULT_ARTIFACT_DISK_BUDGET_BYTES,
    DEFAULT_ARTIFACT_MAX_BYTES,
    ArtifactBudgetError,
    ArtifactStore,
    artifact_payload,
)
from opensquilla.env import trust_env as _trust_env
from opensquilla.provider.image_generation import (
    ImageGenerationRequest,
    generate_with_fallbacks,
    get_image_generation_provider,
    list_image_generation_providers,
    parse_image_generation_model_ref,
    reset_image_generation_providers,
)
from opensquilla.tools.path_aliases import resolve_workspace_alias
from opensquilla.tools.path_policy import reject_foreign_host_path
from opensquilla.tools.registry import tool
from opensquilla.tools.ssrf import validate_http_url_for_fetch
from opensquilla.tools.types import (
    CallerKind,
    SafeToolError,
    SSRFBlockedError,
    ToolError,
    UnsupportedURLSchemeError,
    current_tool_context,
)

_SUPPORTED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "webp"}
_IMAGE_SIZE_LIMIT = 20 * 1024 * 1024  # 20 MB
_PDF_RENDER_SCALE = 2.0
_PDF_TEXT_LIMIT = 50_000
_TTS_VALID_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
_MAX_REDIRECTS = 5
_VISION_ANALYSIS_TIMEOUT_SECONDS = 180.0
_image_generation_config: Any | None = None
_media_llm_config: Any | None = None
_media_squilla_router_config: Any | None = None


def configure_image_generation(
    config: Any | None,
    *,
    llm_config: Any | None = None,
    squilla_router_config: Any | None = None,
) -> None:
    global _image_generation_config, _media_llm_config, _media_squilla_router_config
    _image_generation_config = config
    _media_llm_config = llm_config
    _media_squilla_router_config = squilla_router_config
    reset_image_generation_providers(config, llm_config=llm_config)


# ---------------------------------------------------------------------------
# image
# ---------------------------------------------------------------------------


@tool(
    name="image",
    description=(
        "Analyze an image using a vision-capable model. "
        "Accepts only a real local file path or HTTP(S) URL. "
        "Do not call this tool for images already attached to the current chat turn; "
        "use the attachment content directly. "
        "Returns the model's text analysis of the image."
    ),
    params={
        "path": {
            "type": "string",
            "description": (
                "Real local file path or HTTP(S) URL to the image. "
                "Do not pass a chat attachment display name or a filename visible "
                "inside a screenshot."
            ),
        },
        "prompt": {
            "type": "string",
            "description": "What to analyze or describe about the image.",
        },
    },
    required=["path", "prompt"],
    execution_timeout_seconds=_VISION_ANALYSIS_TIMEOUT_SECONDS,
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
        raise SafeToolError(f"Image appears corrupt or unreadable: {exc}") from exc

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
        raise SafeToolError(
            f"Image path is not accessible by the image tool: {path}. "
            "Pass a real local file path or HTTP(S) URL. If this is a chat attachment, "
            "answer from the attached image directly instead of calling the image tool."
        )
    ext = p.suffix.lstrip(".").lower()
    if ext == "pdf":
        loop = asyncio.get_event_loop()
        rendered_bytes = await loop.run_in_executor(None, _render_pdf_first_page_png, p)
        if len(rendered_bytes) > _IMAGE_SIZE_LIMIT:
            raise SafeToolError("Rendered PDF page exceeds 20MB image size limit")
        return rendered_bytes, "image/png"
    if ext not in _SUPPORTED_IMAGE_FORMATS:
        raise SafeToolError(
            f"Unsupported image format: {ext}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_IMAGE_FORMATS))}"
        )
    loop = asyncio.get_event_loop()
    image_bytes: bytes = await loop.run_in_executor(None, p.read_bytes)
    if len(image_bytes) > _IMAGE_SIZE_LIMIT:
        raise SafeToolError("Image exceeds 20MB size limit")
    media_type = _ext_to_mime(ext)
    return image_bytes, media_type


def _render_pdf_first_page_png(path: Path) -> bytes:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except Exception as exc:  # pragma: no cover - dependency is provided by pdfplumber
        raise ToolError("PDF image analysis requires pypdfium2 to render pages") from exc

    pdf = None
    page = None
    bitmap = None
    try:
        pdf = pdfium.PdfDocument(str(path))
        if len(pdf) < 1:
            raise ToolError(f"PDF has no pages: {path}")
        page = pdf[0]
        bitmap = page.render(scale=_PDF_RENDER_SCALE)
        image = bitmap.to_pil()
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"Failed to render PDF first page: {path}") from exc
    finally:
        for obj in (bitmap, page, pdf):
            close = getattr(obj, "close", None)
            if close is not None:
                close()


def _resolve_media_path(path: str) -> Path:
    ctx = current_tool_context.get()
    reject_foreign_host_path(path, platform=os.name)
    candidate = Path(path).expanduser()
    workspace = Path(ctx.workspace_dir).expanduser() if ctx and ctx.workspace_dir else None
    alias = resolve_workspace_alias(candidate, workspace)
    if alias is not None:
        return alias
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
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
        elif getattr(event, "kind", None) == "error":
            code = getattr(event, "code", "") or "provider_error"
            message = getattr(event, "message", "") or "Provider stream failed"
            raise RuntimeError(f"Provider stream error ({code}): {message}")
    return "".join(text_parts)


async def _call_vision_provider(b64_data: str, media_type: str, prompt: str) -> str:
    """Send image to provider vision API. Raises if provider not available."""
    try:
        from opensquilla.provider.selector import ModelSelector, SelectorConfig
        from opensquilla.provider.types import ContentBlockImage, ContentBlockText, Message

        cfg = _resolve_vision_provider_config(default_model="openai/gpt-4o-mini")
        selector = ModelSelector(SelectorConfig(primary=cfg))
        provider = selector.resolve()
    except Exception as exc:
        raise RuntimeError(f"Provider not available: {exc}") from exc

    vision_message = Message(
        role="user",
        content=[
            ContentBlockImage(media_type=media_type, data=b64_data),
            ContentBlockText(text=prompt),
        ],
    )
    return await _complete_from_stream(provider, [vision_message])


# ---------------------------------------------------------------------------
# image_generate
# ---------------------------------------------------------------------------


@tool(
    name="image_generate",
    description=(
        "Generate an image from a text prompt using a configured image provider. "
        "On web and channel surfaces, the generated image is registered as an artifact "
        "for that surface to deliver; do not call publish_artifact again for the returned path. "
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
    payload: dict[str, Any] = {
        "status": "ok",
        "path": str(target),
        "provider": result.provider,
        "model": result.model,
        "mime_type": result.mime_type,
        "size_bytes": len(result.image_bytes),
        "revised_prompt": result.revised_prompt,
    }
    artifact = _publish_generated_image_artifact(target, result.mime_type)
    if artifact is not None:
        payload["artifact"] = {k: v for k, v in artifact.items() if k != "download_url"}
        payload["artifact"]["registered_for_delivery"] = True
        payload["artifact"]["delivery_managed_by_surface"] = True
        payload["note"] = (
            "The generated image is registered for the current chat surface. "
            "Do not call publish_artifact again for this same file unless the user explicitly "
            "asks for a separate copy."
        )
    return json.dumps(payload)


def _publish_generated_image_artifact(target: Path, mime_type: str) -> dict[str, Any] | None:
    ctx = current_tool_context.get()
    if (
        ctx is None
        or ctx.caller_kind is CallerKind.SUBAGENT
        or not ctx.artifact_media_root
        or not ctx.artifact_session_id
        or not ctx.session_key
    ):
        return None

    store = ArtifactStore(ctx.artifact_media_root)
    try:
        ref = store.publish_file(
            target,
            session_id=ctx.artifact_session_id,
            session_key=ctx.session_key,
            name=target.name,
            mime=mime_type or "image/png",
            source="image_generate",
            max_bytes=ctx.artifact_max_bytes
            if ctx.artifact_max_bytes is not None
            else DEFAULT_ARTIFACT_MAX_BYTES,
            disk_budget_bytes=ctx.artifact_disk_budget_bytes
            if ctx.artifact_disk_budget_bytes is not None
            else DEFAULT_ARTIFACT_DISK_BUDGET_BYTES,
        )
    except ArtifactBudgetError as exc:
        raise ToolError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise ToolError(f"artifact storage path is unavailable: {exc}") from exc
    payload = artifact_payload(ref)
    ctx.published_artifacts.append(payload)
    return payload


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
    ctx = current_tool_context.get()
    reject_foreign_host_path(raw, platform=os.name)
    root = (
        Path(ctx.workspace_dir).expanduser().resolve(strict=False)
        if ctx and ctx.workspace_dir
        else Path.cwd()
    )
    candidate = Path(raw).expanduser()
    if not candidate.suffix:
        candidate = candidate.with_suffix(f".{ext}")

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
        from opensquilla.provider.types import Message

        cfg = _resolve_provider_config("LLM", default_model="openai/gpt-4o-mini")
        selector = ModelSelector(SelectorConfig(primary=cfg))
        provider = selector.resolve()
        message = Message(role="user", content=f"{prompt}\n\n---\n{text}")
        return await _complete_from_stream(provider, [message])
    except Exception:
        return f"[LLM analysis not available] Extracted text ({len(text)} chars) ready."


def _config_value(config: Any | None, key: str, default: Any = "") -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _has_explicit_scope_override(scope: str) -> bool:
    return bool(
        os.environ.get(f"OPENSQUILLA_{scope}_PROVIDER")
        or os.environ.get(f"OPENSQUILLA_{scope}_MODEL")
    )


def _configured_image_tier(router_config: Any | None) -> Any | None:
    tiers = _config_value(router_config, "tiers", {})
    if not isinstance(tiers, dict):
        return None

    preferred = tiers.get("image_model")
    if _config_value(preferred, "supports_image", False):
        return preferred

    for tier in tiers.values():
        if _config_value(tier, "supports_image", False):
            return tier
    return None


def _configured_provider_config(provider_name: str, model: str):
    from opensquilla.provider.selector import ProviderConfig

    provider_name = str(provider_name or "").strip().lower() or "openrouter"
    llm_provider = str(_config_value(_media_llm_config, "provider", "") or "").strip().lower()
    use_llm_config = provider_name == llm_provider

    api_key = str(_config_value(_media_llm_config, "api_key", "") or "") if use_llm_config else ""
    if use_llm_config and not api_key:
        api_key_env = str(_config_value(_media_llm_config, "api_key_env", "") or "")
        if api_key_env:
            api_key = os.environ.get(api_key_env, "")

    base_url = str(_config_value(_media_llm_config, "base_url", "") or "") if use_llm_config else ""
    proxy = str(_config_value(_media_llm_config, "proxy", "") or "") if use_llm_config else ""
    provider_routing = (
        _config_value(_media_llm_config, "provider_routing", {}) if use_llm_config else {}
    )
    if not isinstance(provider_routing, dict):
        provider_routing = {}

    if provider_name == "anthropic":
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "")
    elif provider_name == "openrouter":
        api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    else:
        api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        base_url = base_url or os.environ.get("OPENAI_BASE_URL", "")

    return ProviderConfig(
        provider=provider_name,
        model=model,
        api_key=api_key,
        base_url=base_url,
        proxy=proxy or os.environ.get("OPENSQUILLA_LLM_PROXY", ""),
        provider_routing=provider_routing,
    )


def _resolve_vision_provider_config(*, default_model: str):
    if not _has_explicit_scope_override("VISION"):
        tier = _configured_image_tier(_media_squilla_router_config)
        model = str(_config_value(tier, "model", "") or "")
        if tier is not None and model:
            provider_name = str(
                _config_value(tier, "provider", _config_value(_media_llm_config, "provider", ""))
                or "openrouter"
            )
            return _configured_provider_config(provider_name, model)
    return _resolve_provider_config("VISION", default_model=default_model)


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
