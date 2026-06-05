# TUI Renderer Evaluation Result

Date: 2026-05-28

## Recommendation

Keep the terminal renderer as the production default. Keep Textual as an
explicit experimental backend for evaluation, but do not promote it to the
default terminal chat path yet.

Textual is installed in the development dependency group for this branch, so
the replay thresholds can run locally. The replay evidence is clean, but the
current Textual backend is still a headless evaluation renderer rather than a
live interactive app. Promotion should wait until the real-terminal visual test
environment exercises the live TUI flow and confirms the layout/interaction
quality.

## Evidence

Commands run:

```bash
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture long-stream --summary-json .artifacts/tui/terminal-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture long-stream --summary-json .artifacts/tui/textual-long-stream.json
uv run python scripts/bench_tui_replay.py --renderer terminal --fixture dense-history --summary-json .artifacts/tui/terminal-dense-history.json
uv run python scripts/bench_tui_replay.py --renderer textual --fixture dense-history --summary-json .artifacts/tui/textual-dense-history.json
```

Local JSON summaries:

- `.artifacts/tui/terminal-long-stream.json`: available, 4,011 events,
  160,000 text chars, 86 flushes, coalescing ratio 0.02,
  max buffer 2,040 chars, rendered text matched, 0 plugin errors, 0 errors,
  wall time 16.019 ms.
- `.artifacts/tui/textual-long-stream.json`: available, 4,011 events,
  160,000 text chars, 80 flushes, coalescing ratio 0.02,
  max buffer 2,040 chars, rendered text matched, 0 plugin errors, 0 errors,
  wall time 146.097 ms.
- `.artifacts/tui/terminal-dense-history.json`: available, 624 events,
  624 transcript items, 30 visible items, 20 expanded tools,
  projection wall time 0.059 ms, 0 plugin errors, 0 errors,
  wall time 2.782 ms.
- `.artifacts/tui/textual-dense-history.json`: available, 624 events,
  624 transcript items, 30 visible items, 20 expanded tools,
  projection wall time 0.060 ms, 0 plugin errors, 0 errors,
  wall time 2.675 ms.

## Threshold Assessment

- Long-stream terminal and Textual replay preserved final text exactly.
- Textual long-stream flush count was 80 versus terminal's 86, within the
  25 percent relative threshold.
- Dense-history projection stayed bounded to 30 visible items from 624
  transcript items for both terminal and Textual.
- No replay summary reported plugin dispatch errors.
- Textual is in the development dependency group, not the production dependency
  list, so existing prompt-toolkit behavior and default CLI launch remain
  unchanged.

Textual promotion remains blocked until a live interactive terminal visual test
environment validates the actual app surface, keyboard/input behavior, and
layout quality. Replay evidence is necessary but not sufficient for changing
the production default.
