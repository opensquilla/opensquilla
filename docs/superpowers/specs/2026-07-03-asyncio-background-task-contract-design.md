# Asyncio Background Task Contract Repair Design

## Context

GitHub issue #70 reports that `opensquilla.asyncio_utils.create_background_task`
claims to close unconsumed coroutines in tests, but its close branch is unclear
and mostly unreachable during normal runtime. The current helper first calls
`asyncio.create_task(coro)`, then closes `coro` only if the returned object is
not an `asyncio.Task`.

Normal OpenSquilla users are not expected to hit this issue because
`asyncio.create_task` returns a real task. The risk is mainly a maintenance and
test-contract risk: tests or call sites may rely on the helper to avoid
unawaited coroutine warnings when task creation is stubbed.

## Goals

- Preserve normal runtime behavior: successful calls still delegate to
  `asyncio.create_task` and return its result.
- Make the test-helper contract explicit and covered by focused tests.
- Close still-unconsumed coroutines when task creation is stubbed to return a
  non-`asyncio.Task` object.
- Close still-unconsumed coroutines when task creation raises, then re-raise the
  original exception.
- Keep the repair narrow to `asyncio_utils` and direct tests for that helper.

## Non-Goals

- Do not change gateway, scheduler, heartbeat, or channel background-task call
  sites.
- Do not replace `asyncio.create_task` usage repository-wide.
- Do not introduce a new task abstraction or dependency.
- Do not suppress exceptions from `asyncio.create_task`.

## Proposed Behavior

`create_background_task(coro)` should follow this contract:

1. Call `asyncio.create_task(coro)`.
2. If `asyncio.create_task` raises, close `coro` when it still has a live
   coroutine frame, then re-raise the same exception.
3. If task creation returns an `asyncio.Task`, return it unchanged.
4. If task creation returns a non-`asyncio.Task` object and `coro` still has a
   live coroutine frame, close `coro` and return the non-task object unchanged.

This keeps production behavior unchanged while documenting the narrow testing
case that the existing code already hints at.

## Testing

Add a focused `tests/test_asyncio_utils.py` with three tests:

- A normal async test verifies that the helper returns an `asyncio.Task` and the
  coroutine runs to completion.
- A stubbed `asyncio.create_task` test returns a sentinel object, verifies the
  sentinel is returned, and verifies the original coroutine frame is closed.
- A stubbed `asyncio.create_task` test raises a sentinel exception, verifies the
  exception is re-raised, and verifies the original coroutine frame is closed.

These tests should be synthetic, offline, deterministic, and independent of
gateway boot or scheduler behavior.

## Verification

Run the narrow verification first:

```bash
uv run pytest tests/test_asyncio_utils.py -q
```

If implementation touches only `src/opensquilla/asyncio_utils.py` and the new
test file, no broad runtime suite should be necessary for the initial repair.
If call sites are changed later, expand verification to the relevant package
tests.

## Issue Resolution

This closes issue #70 by turning the ambiguous close branch into an explicit,
tested helper contract. The branch remains intentionally narrow: it exists for
test stubs and exceptional task-creation cleanup, not for normal runtime task
creation.
