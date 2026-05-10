"""web_fetch built-in tool: fetch a URL and extract readable content."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.parse import urljoin

import httpx
import structlog
from cachetools import TTLCache

from opensquilla.env import trust_env as _trust_env
from opensquilla.sandbox.integration import sandboxed
from opensquilla.tools.registry import tool
from opensquilla.tools.ssrf import validate_http_url_for_fetch
from opensquilla.tools.types import SSRFBlockedError

log = structlog.get_logger(__name__)

# 15-minute cache keyed by (url, extract_mode)
_cache: TTLCache = TTLCache(maxsize=256, ttl=900)

# Escalate to Firecrawl when local readability returns None or content below
# this threshold. Keeps free local path as the default, reserves the paid SaaS
# path for JS-heavy / anti-bot pages where readability struggles.
_READABILITY_ESCALATION_MIN_CHARS = 200

_DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
}

_UA_PRIMARY = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_UA_FALLBACK = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)

_TRANSIENT_STATUSES: frozenset[int] = frozenset({403, 408, 425, 429, 500, 502, 503, 504})
_RETRY_DELAY_SECONDS = 0.25
_WEB_FETCH_DEFAULT_MAX_CHARS = 20_000
_WEB_FETCH_MAX_CHARS_ENV = "OPENSQUILLA_WEB_FETCH_MAX_CHARS"
_MAX_REDIRECTS = 5


def _check_ssrf(url: str) -> None:
    """Raise ValueError if the URL resolves to a private/internal address."""
    validate_http_url_for_fetch(url)


def _html_to_markdown(html: str) -> str:
    import html2text

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.body_width = 0
    return h.handle(html)


def _markdown_to_text(markdown: str) -> str:
    """Strip markdown formatting to plain text via html2text."""
    import html2text

    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    h.body_width = 0
    # html2text can also strip simple markdown when fed as plain text
    # but the cleanest approach: pass through as-is since we already
    # have the markdown. Just strip link/image noise.
    return h.handle(markdown)


async def _try_firecrawl(url: str, api_key: str) -> tuple[str, str] | None:
    """Try Firecrawl API. Returns (content, extractor) or None."""
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=_trust_env()) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"url": url, "formats": ["markdown"]},
            )
            data = resp.json()
            if data.get("success"):
                return data["data"]["markdown"], "firecrawl"
            log.warning("web_fetch.firecrawl_unsuccessful", url=url, response=data)
    except Exception as exc:
        log.warning("web_fetch.firecrawl_error", url=url, error=str(exc))
    return None


def _try_readability(html: str) -> tuple[str, str, str] | None:
    """Try readability-lxml. Returns (title, content_markdown, extractor) or None."""
    try:
        from readability import Document

        doc = Document(html)
        title = doc.title()
        summary_html = doc.summary()
        content = _html_to_markdown(summary_html)
        return title, content, "readability"
    except Exception:
        return None


def _try_html2text(html: str) -> tuple[str, str, str]:
    """html2text fallback — always succeeds."""
    content = _html_to_markdown(html)
    return "", content, "html2text"


def _resolve_default_max_chars() -> int:
    """Return default output cap for omitted max_chars."""
    raw = os.environ.get(_WEB_FETCH_MAX_CHARS_ENV, "").strip()
    if not raw:
        return _WEB_FETCH_DEFAULT_MAX_CHARS
    try:
        value = int(raw)
    except ValueError:
        return _WEB_FETCH_DEFAULT_MAX_CHARS
    return value if value >= 100 else _WEB_FETCH_DEFAULT_MAX_CHARS


def _resolve_effective_max_chars(max_chars: int | None) -> int | None:
    """Resolve explicit max_chars or the default cap for omitted values."""
    if max_chars is not None:
        return max_chars if max_chars >= 100 else None
    return _resolve_default_max_chars()


@tool(
    name="web_fetch",
    description=(
        "Fetch a URL and extract readable content as markdown or plain text. "
        "Uses a multi-extractor pipeline (readability → Firecrawl escalation → "
        "html2text). Includes SSRF protection and a 15-minute response cache."
    ),
    params={
        "url": {
            "type": "string",
            "description": "HTTP or HTTPS URL to fetch.",
        },
        "extract_mode": {
            "type": "string",
            "description": 'Extraction format: "markdown" (default) or "text".',
            "enum": ["markdown", "text"],
        },
        "max_chars": {
            "type": "integer",
            "description": (
                "Maximum characters to return (minimum 100). "
                "Defaults to 20,000 when omitted; override default with "
                "OPENSQUILLA_WEB_FETCH_MAX_CHARS."
            ),
            "minimum": 100,
        },
    },
    required=["url"],
)
@sandboxed(
    kind="web.fetch",
    argv_factory=lambda a: (
        "web_fetch",
        str(a.get("url", "")),
        str(a.get("extract_mode", "markdown")),
    ),
    record_payload=False,
)
async def web_fetch(
    url: str,
    extract_mode: str = "markdown",
    max_chars: int | None = None,
) -> str:
    # --- SSRF guard ---
    _check_ssrf(url)
    from opensquilla.tools.builtin.web import _sensitive_body_block, _sensitive_url_marker

    marker = _sensitive_url_marker(url)
    if marker is not None:
        return _sensitive_body_block("web_fetch", marker)

    effective_max_chars = _resolve_effective_max_chars(max_chars)

    # --- Cache lookup ---
    cache_key = (url, extract_mode)
    if cache_key in _cache:
        cached: dict[str, Any] = dict(_cache[cache_key])
        return json.dumps(_apply_max_chars(cached, effective_max_chars), ensure_ascii=False)

    # --- Fetch ---
    title = ""
    content_type = ""
    final_url = url
    status = 0
    raw_html = ""

    async def _do_fetch(user_agent: str) -> tuple[int, str, str, str]:
        headers = dict(_DEFAULT_HEADERS)
        headers["User-Agent"] = user_agent
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            trust_env=_trust_env(),
            headers=headers,
        ) as client:
            current_url = url
            for _redirect_count in range(_MAX_REDIRECTS + 1):
                _check_ssrf(current_url)
                marker = _sensitive_url_marker(current_url)
                if marker is not None:
                    raise ValueError("Blocked redirect URL containing sensitive data")

                response = await client.get(current_url)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get("location")
                if not location:
                    break
                current_url = urljoin(str(response.url), location)
            else:
                raise ValueError(f"Too many redirects (>{_MAX_REDIRECTS})")

            return (
                response.status_code,
                str(response.url),
                response.headers.get("content-type", ""),
                response.text,
            )

    last_error: str | None = None
    for attempt_idx, user_agent in enumerate((_UA_PRIMARY, _UA_FALLBACK)):
        try:
            status, final_url, content_type, raw_html = await _do_fetch(user_agent)
        except SSRFBlockedError:
            raise
        except httpx.TimeoutException:
            raise
        except Exception as exc:
            last_error = str(exc)
            if attempt_idx == 0:
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                continue
            result: dict[str, Any] = {
                "url": url,
                "final_url": url,
                "status": 0,
                "content_type": "",
                "title": "",
                "extract_mode": extract_mode,
                "extractor": "none",
                "truncated": False,
                "length": 0,
                "text": "",
                "error": last_error,
            }
            return json.dumps(result, ensure_ascii=False)

        is_transient = status in _TRANSIENT_STATUSES
        is_empty_success = 200 <= status < 300 and not raw_html.strip()
        if attempt_idx == 0 and (is_transient or is_empty_success):
            await asyncio.sleep(_RETRY_DELAY_SECONDS)
            continue
        break

    # --- Non-HTML: return as-is ---
    is_html = "html" in content_type.lower()
    if not is_html:
        result = {
            "url": url,
            "final_url": final_url,
            "status": status,
            "content_type": content_type,
            "title": "",
            "extract_mode": extract_mode,
            "extractor": "raw",
            "truncated": False,
            "length": len(raw_html),
            "text": _wrap_content(final_url, raw_html),
        }
        _cache[cache_key] = result
        return json.dumps(_apply_max_chars(result, effective_max_chars), ensure_ascii=False)

    # --- Error HTTP status: return empty ---
    if status >= 400:
        hint = (
            "rate-limited or blocked upstream; try a different URL from search results, "
            "retry after a brief delay, or use another source"
            if status in _TRANSIENT_STATUSES
            else "HTTP error from upstream; try a different URL or adjust the path"
        )
        result = {
            "url": url,
            "final_url": final_url,
            "status": status,
            "content_type": content_type,
            "title": "",
            "extract_mode": extract_mode,
            "extractor": "none",
            "truncated": False,
            "length": 0,
            "text": "",
            "error": hint,
        }
        if status not in _TRANSIENT_STATUSES:
            _cache[cache_key] = result
        return json.dumps(result, ensure_ascii=False)

    # --- Extraction pipeline ---
    # Try local extractors first (zero-cost, handles ~90% of mainstream pages),
    # escalate to Firecrawl only when readability misses (JS-heavy / anti-bot
    # sites), and fall back to html2text for everything else.
    extracted_content = ""
    extractor_used = "html2text"

    # 1. readability-lxml (local, free, main-content extraction)
    rd_result = _try_readability(raw_html)
    if rd_result is not None:
        title, extracted_content, extractor_used = rd_result

    # 2. Firecrawl escalation — only when readability returns nothing or too
    # little content (SaaS call, requires API key)
    readability_short = len(extracted_content) < _READABILITY_ESCALATION_MIN_CHARS
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if firecrawl_key and readability_short:
        log.info(
            "web_fetch.firecrawl_escalation",
            url=url,
            readability_chars=len(extracted_content),
            reason="readability_miss" if rd_result is None else "readability_short",
        )
        fc_result = await _try_firecrawl(url, firecrawl_key)
        if fc_result is not None:
            extracted_content, extractor_used = fc_result

    # 3. html2text fallback — always succeeds on valid HTML
    if not extracted_content:
        title, extracted_content, extractor_used = _try_html2text(raw_html)

    # --- Mode conversion ---
    if extract_mode == "text":
        extracted_content = _markdown_to_text(extracted_content)

    result = {
        "url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "title": title,
        "extract_mode": extract_mode,
        "extractor": extractor_used,
        "truncated": False,
        "length": len(extracted_content),
        "text": _wrap_content(final_url, extracted_content),
    }
    _cache[cache_key] = result
    return json.dumps(_apply_max_chars(result, effective_max_chars), ensure_ascii=False)


def _wrap_content(source: str, content: str) -> str:
    return f'<external-content source="{source}">{content}</external-content>'


def _extract_inner(wrapped: str) -> str:
    """Extract content from inside <external-content> tags."""
    start_tag_end = wrapped.find(">")
    end_tag_start = wrapped.rfind("</external-content>")
    if start_tag_end == -1 or end_tag_start == -1:
        return wrapped
    return wrapped[start_tag_end + 1 : end_tag_start]


def _apply_max_chars(result: dict[str, Any], max_chars: int | None) -> dict[str, Any]:
    """Return a display copy with max_chars applied.

    The cache stores untruncated content so callers can later request a larger
    explicit cap without waiting for cache expiry.
    """
    if max_chars is None:
        return dict(result)

    output = dict(result)
    inner = _extract_inner(str(output.get("text", "")))
    if len(inner) <= max_chars:
        return output

    source = str(output.get("final_url") or output.get("url") or "")
    output["text"] = _wrap_content(source, inner[:max_chars])
    output["truncated"] = True
    output["length"] = max_chars
    return output
