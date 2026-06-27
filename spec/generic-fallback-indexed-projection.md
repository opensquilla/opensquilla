# Generic Fallback Indexed Projection Spec

Date: 2026-06-03
Status: draft
Scope: `generic/fallback` tokenjuice reducer only

## 1. Purpose

Redesign `generic/fallback` so unknown tool output is compressed without hiding
the middle body as an unrecoverable blind spot.

The design must preserve the existing tokenjuice path for specialized reducers.
Known reducers such as pytest, rg, git, docker, package managers, and build tools
continue to own their current output-specific behavior. The new indexed fallback
is used only after no specialized tokenjuice rule matches.

## 2. Current Failure Mode

Current fallback behavior is line-oriented head/tail truncation:

```text
show first N lines
... omitted M lines ...
show last K lines
```

This is risky for unknown output because the middle may contain the relevant
method, stack frame, file excerpt, configuration value, or diagnostic message.
When that happens, the model sees an incomplete result and may repeatedly call
more tools to rediscover information already present in the original output.

The issue is not merely that the head/tail windows are too small. The issue is
that a catch-all fallback assumes the middle is low value even though the command
shape is unknown.

## 3. Design Principle

`generic/fallback` must be a conservative evidence indexer, not a semantic
summarizer.

It should:

- keep specialized tokenjuice reducers untouched;
- avoid extra model calls;
- scan the complete output locally;
- show high-probability useful ranges in the first projection;
- show some middle content even with no signals;
- render a deterministic map of shown and omitted line ranges;
- make omitted content explicit instead of silently hiding it.

It should not:

- ask the model to summarize raw output;
- make line-range guessing the main recovery path;
- replace existing specialized reducers;
- globally change `head_tail()`;
- assume that middle content is safe to discard.

## 4. Pipeline Placement

The reducer routing contract remains:

```text
tool result
  -> tokenjuice load_rules()
  -> tokenjuice select_rule()
  -> if rule.id != "generic/fallback":
       use the existing specialized reducer behavior
  -> if rule.id == "generic/fallback":
       use indexed generic fallback
```

The new code path is gated strictly on:

```python
rule.id == "generic/fallback"
```

No specialized reducer should emit `[generic_fallback_index]`.

## 5. Vocabulary

`original_lines`
: Number of lines after existing fallback transforms such as ANSI stripping,
  adjacent dedupe, and edge trimming.

`shown_range`
: A 1-based inclusive line range included in the projected output.

`omitted_range`
: A 1-based inclusive line range not included in the projected output.

`signal`
: A deterministic local match suggesting diagnostic value, such as `error`,
  `exception`, `traceback`, `failed`, `path:line`, or a command/task keyword.

`middle_sample`
: A deterministic sample range from the middle of the output, used when the
  selected ranges would otherwise leave the middle completely opaque.

`precise follow-up retrieval`
: Future fallback recovery through a stored tool-result handle. This is not the
  main path for the first implementation slice.

## 6. Output Contract

`generic/fallback` should render this shape:

```text
[generic_fallback_index]
original_lines: <int>

shown_ranges:
- <start>-<end> <reason>
- <start>-<end> <reason>

omitted_ranges:
- <start>-<end>
- <start>-<end>

[range <start>-<end> <reason>]
<line text>
...

[range <start>-<end> <reason>]
<line text>
...
```

Example:

```text
[generic_fallback_index]
original_lines: 500

shown_ranges:
- 1-80 head
- 120-150 signal: initialize
- 250-280 middle_sample
- 430-500 tail

omitted_ranges:
- 81-119
- 151-249
- 281-429

[range 1-80 head]
...

[range 120-150 signal: initialize]
...

[range 250-280 middle_sample]
...

[range 430-500 tail]
...
```

The map is part of the model-visible result. It tells the model which content it
has and which content remains hidden.

## 7. Shown Range Selection

### 7.1 Inputs

The first implementation slice can use:

- transformed output lines;
- `exit_code`;
- `rule.id`;
- command string, if reducer plumbing makes it available;
- tool arguments, if reducer plumbing makes them available.

If command/task keywords are not available in the first slice, the fallback
still ships with head, tail, high-signal regex windows, and middle samples.

### 7.2 Selection Order

Select ranges in this order:

1. Add head range.
2. Add tail range.
3. Add high-signal regex windows from a full scan of all lines.
4. Add command-derived keyword windows, when available.
5. Add task-derived keyword windows, when available.
6. Add middle samples.
7. Merge overlapping or adjacent ranges.
8. Derive omitted ranges from the merged shown ranges.

This order does not imply rendering order. Rendering order must be ascending by
line number after merge.

### 7.3 Head And Tail

Suggested first-pass defaults:

```text
success output:
  head = 80
  tail = 80

error output:
  head = 40
  tail = 120
```

These are generic fallback defaults. Specialized reducers can stay more
aggressive because they understand their output shape.

### 7.4 High-Signal Windows

Scan the complete transformed line list with a deterministic case-insensitive
regex.

Suggested initial signal terms:

```text
error
failed
failure
exception
traceback
assert
warning
panic
timeout
permission denied
no such file
segmentation fault
cannot find
not found
denied
line <number>
path:line, for example file.py:123 or src/app.ts:88
```

For each matched line, add a context window:

```text
success output:
  signal_context = 15

error output:
  signal_context = 20
```

Window calculation:

```text
start = max(1, matched_line_number - signal_context)
end = min(original_lines, matched_line_number + signal_context)
reason = "signal: <matched-label>"
```

### 7.5 Command-Derived Keyword Windows

When command text is available, extract low-risk keywords from:

- basename of paths;
- file stems;
- quoted path fragments;
- words longer than 3 characters that are not common shell flags;
- command arguments likely to be search targets.

Examples:

```text
cat -n /testbed/foo/zip.rb
  -> zip.rb, zip

sed -n '1,120p' app/controllers/users_controller.rb
  -> users_controller.rb, users_controller

custom-tool --target initialize --verbose
  -> initialize
```

If a keyword appears in output, add the same context window used for signal
matches. Reasons should distinguish command keywords:

```text
signal: command-keyword initialize
signal: command-keyword zip.rb
```

The first implementation may skip this section if command text is not available
at the formatter boundary. It should be added before task-derived keywords.

### 7.6 Task-Derived Keyword Windows

If future plumbing provides current user/task keywords, scan for them like
command keywords.

This is useful for cases where the user asks about a symbol such as
`initialize`, but the command itself is only a generic file read.

This is not required for the first implementation slice. Do not add another LLM
call to infer these keywords.

### 7.7 Middle Samples

Middle samples prevent the middle body from being fully opaque when no signal
matches or when signal matches are only near the head/tail.

Suggested defaults:

```text
success output:
  middle_samples = 3
  middle_sample_size = 30

error output:
  middle_samples = 2
  middle_sample_size = 30
```

Sampling rule:

1. Identify the interior region after reserving head and tail:

```text
interior_start = head + 1
interior_end = original_lines - tail
```

2. If `interior_start > interior_end`, no middle sample is needed.
3. Divide the interior into `middle_samples + 1` gaps.
4. Place each sample around its gap point.
5. Clamp to `1..original_lines`.
6. Add reason `middle_sample`.

Middle samples should be added even if signals exist, unless merged ranges
already cover at least one interior range that is not adjacent to head/tail.

### 7.8 Caps

To prevent verbose fallback output:

```text
max_signal_windows = 8 for success output
max_signal_windows = 12 for error output
max_command_keyword_windows = 4
max_task_keyword_windows = 4
```

If there are more matches than the cap, choose representative windows:

- earliest match;
- latest match;
- evenly distributed matches between them.

After choosing representative matches, merge ranges. The existing
`max_inline_chars` guard remains the final safety cap.

## 8. Range Merge Rules

Represent ranges as:

```python
@dataclass(frozen=True)
class LineRange:
    start: int  # 1-based inclusive
    end: int    # 1-based inclusive
    reason: str
```

Normalize every range before merge:

```text
start = max(1, min(start, original_lines))
end = max(1, min(end, original_lines))
drop if start > end
```

Merge if ranges overlap or touch:

```text
current.end + 1 >= next.start
```

Reason merge rule:

- preserve `head` if a merged range starts at line 1 because of head;
- preserve `tail` if a merged range ends at `original_lines` because of tail;
- preserve unique signal labels;
- preserve `middle_sample` if present;
- render combined reasons as comma-separated text.

Example:

```text
1-80 head
70-100 signal: error
```

becomes:

```text
1-100 head, signal: error
```

## 9. Omitted Map

`omitted_ranges` is deterministic:

```text
omitted_ranges = total line range - merged shown_ranges
```

Algorithm:

```python
def omitted_ranges(total_lines: int, shown: list[LineRange]) -> list[LineRange]:
    omitted = []
    cursor = 1
    for current in shown:
        if cursor < current.start:
            omitted.append(LineRange(cursor, current.start - 1, "omitted"))
        cursor = max(cursor, current.end + 1)
    if cursor <= total_lines:
        omitted.append(LineRange(cursor, total_lines, "omitted"))
    return omitted
```

Properties:

- `shown_ranges` and `omitted_ranges` never overlap.
- Combined, they cover exactly `1..original_lines`.
- Empty omitted ranges are allowed for outputs where all lines are shown.
- The omitted map is generated by code, not by the model.

## 10. Precise Follow-Up Retrieval

Precise follow-up retrieval is separate from `shown_ranges`.

`shown_ranges` are the lines included in the first compressed result.

Precise follow-up retrieval means a later system capability can use a stored
`tool_result_handle` to search or read the preserved raw output:

```text
tool_result_search(handle, query, context_lines, max_matches)
tool_result_read(handle, start_line, end_line)
```

This is a fallback recovery mechanism, not the primary path. The first indexed
fallback pass should already include high-signal windows and middle samples so
the model usually does not need follow-up retrieval.

If follow-up retrieval is implemented later, `tool_result_search` should be
preferred over `tool_result_read` because it lets the system search locally and
return multiple candidate windows in one call. Avoid designs where the model
repeatedly guesses line numbers.

## 11. Implementation Plan

### 11.1 `src/opensquilla/plugins/tokenjuice/formatters.py`

Add helpers without changing `head_tail()`:

```python
SIGNAL_RE = re.compile(..., re.IGNORECASE)

@dataclass(frozen=True)
class LineRange:
    start: int
    end: int
    reason: str

def indexed_fallback(
    lines: list[str],
    *,
    is_error: bool,
    head: int,
    tail: int,
    signal_context: int,
    middle_samples: int,
    middle_sample_size: int,
    max_signal_windows: int,
) -> str:
    ...

def indexed_fallback_ranges(...) -> list[LineRange]:
    ...

def merge_ranges(ranges: list[LineRange], total_lines: int) -> list[LineRange]:
    ...

def omitted_ranges(total_lines: int, shown: list[LineRange]) -> list[LineRange]:
    ...
```

### 11.2 `src/opensquilla/plugins/tokenjuice/reducer.py`

Branch only for `generic/fallback`:

```python
head, tail = _summarize_window(rule, exit_code=exit_code)

if rule.id == "generic/fallback":
    compacted = indexed_fallback(
        lines,
        is_error=exit_code != 0,
        head=head,
        tail=tail,
        signal_context=20 if exit_code != 0 else 15,
        middle_samples=2 if exit_code != 0 else 3,
        middle_sample_size=30,
        max_signal_windows=12 if exit_code != 0 else 8,
    )
else:
    compacted = "\n".join(head_tail(lines, head, tail)).strip()

return compacted, facts
```

### 11.3 `src/opensquilla/plugins/tokenjuice/rules/generic/fallback.json`

First slice can keep the existing schema. If config becomes necessary, add:

```json
"indexedFallback": {
  "signalContext": 15,
  "middleSamples": 3,
  "middleSampleSize": 30,
  "maxSignalWindows": 8
}
```

Do not add indexed fallback config to specialized rule files.

### 11.4 Agent Layer

No first-slice change is required if the agent already prepends
`tool_result_handle` after storing projected raw results.

The indexed fallback is still valuable without handle retrieval because the
first compressed result includes signal windows, middle samples, and omitted
ranges.

## 12. Rendering Details

Render line content exactly as transformed by the reducer before fallback range
selection. Do not add line numbers unless the original output already contains
them.

Render ranges in ascending line order:

```text
[range 120-150 signal: initialize]
<line 120 text>
<line 121 text>
```

Use blank lines between sections for readability.

If there are no omitted ranges, render:

```text
omitted_ranges:
- none
```

If all transformed lines fit within the selected ranges and the projection is
not shorter than the original, the existing adapter no-op behavior may preserve
the original result.

## 13. Examples

### 13.1 Middle Signal In File Read

Input shape:

```text
1-8 shown by old head
13 def initialize(...)
73-80 shown by old tail
```

New fallback should include:

```text
shown_ranges:
- 1-8 head
- 9-25 signal: initialize
- 73-80 tail

omitted_ranges:
- 26-72
```

### 13.2 Unknown Long Log With Error

Input shape:

```text
1-80 normal startup
211 ERROR failed to connect
212 stack detail
900 final summary
```

New fallback should include:

```text
shown_ranges:
- 1-80 head
- 191-231 signal: ERROR
- <middle sample range> middle_sample
- 821-900 tail
```

### 13.3 Unknown Output With No Signals

Input shape:

```text
1000 low-signal progress lines
```

New fallback should include:

```text
shown_ranges:
- 1-80 head
- 300-329 middle_sample
- 540-569 middle_sample
- 760-789 middle_sample
- 921-1000 tail
```

## 14. Acceptance Criteria

- Known pytest output still uses the `tests/pytest` reducer.
- Known docker build output still uses the `devops/docker-build` reducer.
- Known rg output still uses the search reducer.
- Specialized reducer outputs do not include `[generic_fallback_index]`.
- Unknown long output uses `generic/fallback` and includes
  `[generic_fallback_index]`.
- Unknown long output includes `original_lines`, `shown_ranges`, and
  `omitted_ranges`.
- A high-signal line in the middle of unknown output is included with context.
- Unknown long output with no high-signal lines includes middle samples.
- `shown_ranges` and `omitted_ranges` cover exactly `1..original_lines`.
- Projection remains deterministic for the same input.
- Fallback projection does not call an LLM.
- Fallback projection remains subject to the existing no-op and
  `max_inline_chars` guards.

## 15. Verification Plan

Targeted regression suite:

```bash
PYTHONPATH=src pytest tests/test_engine/test_tokenjuice_tool_result_projection.py
```

Add tests for:

- `generic/fallback` middle signal extraction.
- `generic/fallback` middle sampling with no signals.
- omitted map coverage and no overlap.
- specialized pytest path unchanged.
- specialized docker path unchanged.
- specialized rg path unchanged.
- adapter still no-ops when projection is not shorter.

Static check:

```bash
rg -n "generic_fallback_index|indexed_fallback|LineRange|omitted_ranges" \
  src/opensquilla/plugins/tokenjuice tests/test_engine
```

## 16. Risks And Mitigations

Risk: generic fallback output becomes too verbose.
: Cap signal windows and middle samples; keep `max_inline_chars` as final guard.

Risk: signal windows crowd out middle samples.
: Merge and cap signals, then ensure at least one interior sample unless interior
  content is already represented.

Risk: specialized reducers are accidentally changed.
: Gate indexed fallback by `rule.id == "generic/fallback"` and add regression
  tests for representative specialized reducers.

Risk: high-signal regex misses the relevant content.
: Include middle samples and omitted maps; add command/task keyword windows when
  plumbing is available.

Risk: model still needs hidden content.
: Future handle-based `tool_result_search` can recover preserved raw result
  windows without rerunning the original command. This is not required for the
  first slice.

## 17. Decision Summary

Use single-pass indexed projection for `generic/fallback` only. Keep existing
tokenjuice specialized reducers unchanged. The fallback locally scans unknown
output, shows head, tail, signal windows, command/task keyword windows when
available, and middle samples, then renders a deterministic shown/omitted range
map. Precise follow-up retrieval is a future handle-based recovery mechanism,
not the main path for deciding what to show.
