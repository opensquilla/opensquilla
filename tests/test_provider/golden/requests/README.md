# Provider request goldens

Frozen outbound request snapshots for every provider adapter, captured
offline by `tests/test_provider/test_request_goldens.py` through
`tests/test_provider/golden/_harness.py` (httpx.MockTransport; no network,
no real credentials).

Each `<backend>/<kind-or-provider>__<case>.json` records the request one
adapter builds today: `method`, `url`, `auth_style` (a redacted marker —
`bearer` / `x-api-key` / `none`; never the key itself), `content_type`, and
`body` (the parsed JSON payload), serialized with
`json.dumps(..., indent=2, sort_keys=True)` plus a trailing newline.

## Freeze policy

These files are a behavior contract. Any diff in a golden means the outbound
request changed — a refactor of the request builders (reasoning-toggle
ladder, compat model-id sets, schema keyword strips, URL joins, auth style)
must leave every file byte-identical. A failing golden is never "fixed" by
blind regeneration: treat the diff as a deliberate behavior change that needs
review.

## Regenerating

```sh
OPENSQUILLA_REGEN_GOLDENS=1 uv run pytest tests/test_provider/test_request_goldens.py -q
uv run pytest tests/test_provider/test_request_goldens.py -q   # must pass afterwards
```

Regeneration rewrites files in place; renamed or removed cases leave stale
files behind that `test_golden_tree_matches_case_matrix` flags — delete them
by hand. `test_matrix_covers_every_compat_policy_kind` fails when a new
provider kind is added to `_POLICIES_BY_KIND` until its goldens land.

## Scope notes

- `openai_codex` is excluded: its OAuth flow (Codex CLI credentials) is out
  of scope for offline request capture.
- All data is synthetic: fake key `sk-test-000` (asserted absent from every
  golden), dummy messages, and a synthetic base URL for kinds registered
  without a default one.
