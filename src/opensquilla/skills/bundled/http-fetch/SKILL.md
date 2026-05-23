---
name: http-fetch
description: "Fetch a URL via HTTP/HTTPS and return the response body as text. Lightweight entrypoint replacement for `coding-agent` steps whose only job is a single GET/POST. Supports GET (default), POST with JSON or form bodies, custom headers, and timeout — no LLM agent loop. Use for simple data-fetch steps in meta-skill DAGs; for crawling, JS-rendered pages, or complex auth chains use coding-agent + scrapling instead."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  requires:
    anyBins: ["python", "python3"]
entrypoint:
  command: python {baseDir}/scripts/http_fetch.py
  args:
    - --url
    - "{{ with.url }}"
    - --method
    - "{{ with.method | default('GET') }}"
    - --timeout
    - "{{ with.timeout | default(30) }}"
    - --max-bytes
    - "{{ with.max_bytes | default(2000000) }}"
  stdin: "{{ with.body | default('') }}"
  parse: text
  timeout: 60
---

# http-fetch (sub-skill)

Direct shell wrapper for a single HTTP request. Replaces
``coding-agent`` sub-Agent steps that just GET/POST a URL — order-of-
magnitude faster (no LLM round-trip, no tool surface, no iteration
loop).

## Inputs (``with:``)

| key         | required | default                | notes                                                          |
|-------------|----------|------------------------|----------------------------------------------------------------|
| `url`       | yes      | —                      | absolute http(s) URL                                           |
| `method`    | no       | `GET`                  | `GET` / `POST` / `PUT` / `DELETE` (case-insensitive)           |
| `body`      | no       | `''`                   | request body, piped via stdin (for POST/PUT); empty = no body  |
| `timeout`   | no       | `30`                   | request timeout in seconds                                     |
| `max_bytes` | no       | `2000000`              | response body cap; larger payloads truncated + suffixed `…`    |

## Output

- Success: response body on stdout (UTF-8 decoded, truncated to
  ``max_bytes`` if larger; lossy decode replaces invalid bytes).
- Non-2xx response: exit 1, stderr ``HTTP <code>: <reason> <body[:200]>``;
  stdout still carries the body for callers that want to inspect.
- Network / DNS / timeout failure: exit 2, stderr cause.

## When NOT to use

- Crawling multiple pages → use ``scrapling`` (via ``coding-agent``).
- JS-rendered pages → use ``coding-agent`` + browser tools.
- OAuth dance / multi-step auth → use ``coding-agent``.
- Streaming responses → not supported (we buffer + return).

## Fallback

If this skill is unavailable, callers should spawn ``coding-agent``
with a curl/requests task — same result, ~10× the latency and a
non-deterministic tool loop.
