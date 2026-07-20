# Daily usage telemetry API v1

This document is the client/server contract for hourly anonymous usage
telemetry. The usage API runs on the existing telemetry service but is isolated
from installation telemetry by route.

## Endpoint

```text
POST https://telemetry.opensquilla.ai/v1/usage
Content-Type: application/json
Idempotency-Key: <event_id>
```

Installation telemetry remains on `POST /v1/install`. A usage request must
never be sent to `/v1/install`.

The client endpoint can be overridden independently:

```sh
OPENSQUILLA_USAGE_TELEMETRY_ENDPOINT=https://example.com/v1/usage
```

Production transport must use HTTPS. The maximum accepted request body should
be 8 KiB.

## Cadence and snapshot semantics

The gateway attempts an upload immediately after startup and every 3600 seconds
afterward. It sends only pending UTC-day rows, including the current UTC day.
Each request is a cumulative snapshot, not an hourly delta. If no completed
turn changed a successfully uploaded row, the client does not resend it.

Failed requests remain pending. A turn that completes while a request is in
flight also keeps the newer local snapshot pending for the next attempt.

## Request

```json
{
  "schema_version": 1,
  "event": "daily_usage",
  "event_id": "4vKztbzl9PcDG5TdT84bIDkbzDPu6hCJnBtNJS8UQ7s",
  "install_id": "62d3839c173be2013d664d7bc195b628686613c367e14634721e502661df572d",
  "opensquilla_version": "0.5.0rc4",
  "day": "2026-07-20",
  "sent_at": "2026-07-20T11:00:00Z",
  "conversation_turns": 3,
  "input_tokens": 1200,
  "output_tokens": 300,
  "cached_tokens": 400,
  "cache_write_tokens": 50
}
```

| Field | Type | Required | Validation |
|---|---:|---:|---|
| `schema_version` | integer | yes | Exactly `1` |
| `event` | string | yes | Exactly `daily_usage` |
| `event_id` | string | yes | 43-character unpadded Base64URL |
| `install_id` | string | yes | 1-128 characters |
| `opensquilla_version` | string | yes | 1-64 characters |
| `day` | string | yes | Real UTC date in `YYYY-MM-DD` form |
| `sent_at` | string | yes | RFC 3339 UTC timestamp ending in `Z` |
| `conversation_turns` | integer | yes | `0..9223372036854775807` |
| `input_tokens` | integer | yes | `0..9223372036854775807` |
| `output_tokens` | integer | yes | `0..9223372036854775807` |
| `cached_tokens` | integer | yes | `0..9223372036854775807` |
| `cache_write_tokens` | integer | yes | `0..9223372036854775807` |

Unknown fields should be rejected for schema version 1. Numeric fields must be
JSON integers; strings and floating-point numbers are invalid.

### Event ID

`event_id` is stable for one installation and UTC day:

```text
message  = UTF8("daily-usage:v1:" + day)
digest   = HMAC-SHA256(key=UTF8(install_id), message=message)
event_id = Base64URL(digest), without "=" padding
```

The `Idempotency-Key` header must exactly equal the JSON `event_id`. The server
must recompute the event ID from `install_id` and `day` and reject a mismatch.
This HMAC is a deterministic integrity check, not authentication: `install_id`
is not a secret.

## Server persistence and upsert

Use `event_id` as the primary idempotency key and additionally enforce one row
per `(install_id, day)`. Processing must be atomic.

On first receipt, insert the snapshot. On conflict, do not add counters and do
not discard the request. Merge every cumulative counter using its monotonic
maximum:

```text
conversation_turns = max(stored.conversation_turns, incoming.conversation_turns)
input_tokens        = max(stored.input_tokens, incoming.input_tokens)
output_tokens       = max(stored.output_tokens, incoming.output_tokens)
cached_tokens       = max(stored.cached_tokens, incoming.cached_tokens)
cache_write_tokens  = max(stored.cache_write_tokens, incoming.cache_write_tokens)
```

This rule handles retries and prevents a delayed older snapshot from
overwriting newer totals. Store server-controlled `first_received_at` and
`last_received_at` timestamps. `sent_at` is client-supplied and must not be used
as a security boundary or substitute for server receipt time.

The collector must not derive totals by counting requests. One day can produce
multiple requests carrying the same `event_id`.

## Responses

Canonical success response:

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "ok": true,
  "event_id": "4vKztbzl9PcDG5TdT84bIDkbzDPu6hCJnBtNJS8UQ7s",
  "status": "accepted"
}
```

The current client treats `200`, `201`, `202`, and `204` as success and ignores
the response body. Any other status leaves the row pending for a later retry.

Error responses should use:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_payload",
    "message": "conversation_turns must be a non-negative integer"
  }
}
```

| HTTP status | Meaning |
|---:|---|
| `400` | Invalid JSON or header/body `event_id` mismatch |
| `413` | Request body exceeds the limit |
| `415` | Content type is not JSON |
| `422` | Schema or field validation failed |
| `429` | Rate limited; include `Retry-After` |
| `500` / `503` | Temporary collector failure |

## Privacy and abuse controls

The request contains no prompts, responses, provider/model names, channels,
session identifiers, costs, tools, paths, file names, or file contents. Source
IP can be visible at the HTTP transport layer but is not a request field.

API v1 has no client authentication. The idempotency key therefore prevents
accidental duplication but cannot prove that a request came from an authentic
client. The server should enforce payload limits, per-IP and per-`install_id`
rate limits, non-negative bounded counters, and anomaly monitoring. It should
not treat these telemetry totals as billing-grade or fraud-proof data.

The unified `privacy.disable_network_observability` setting and legacy network
opt-out environment variables suppress both installation and usage telemetry.
