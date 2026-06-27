from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("error", re.compile(r"\berror\b", re.IGNORECASE)),
    ("failed", re.compile(r"\bfailed\b", re.IGNORECASE)),
    ("failure", re.compile(r"\bfailure\b", re.IGNORECASE)),
    ("exception", re.compile(r"\bexception\b", re.IGNORECASE)),
    ("traceback", re.compile(r"\btraceback\b", re.IGNORECASE)),
    ("assert", re.compile(r"\bassert(?:ion)?\b", re.IGNORECASE)),
    ("warning", re.compile(r"\bwarning\b", re.IGNORECASE)),
    ("panic", re.compile(r"\bpanic\b", re.IGNORECASE)),
    ("timeout", re.compile(r"\btimeout\b", re.IGNORECASE)),
    ("permission denied", re.compile(r"\bpermission denied\b", re.IGNORECASE)),
    ("no such file", re.compile(r"\bno such file\b", re.IGNORECASE)),
    ("segmentation fault", re.compile(r"\bsegmentation fault\b", re.IGNORECASE)),
    ("cannot find", re.compile(r"\bcannot find\b", re.IGNORECASE)),
    ("not found", re.compile(r"\bnot found\b", re.IGNORECASE)),
    ("denied", re.compile(r"\bdenied\b", re.IGNORECASE)),
    (
        "path:line",
        re.compile(
            r"(?<!\S)(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_+-]+:\d+(?:[:\s-]|$)"
        ),
    ),
)

COMMAND_KEYWORD_STOPWORDS = {
    "true",
    "false",
    "null",
    "none",
    "verbose",
    "quiet",
    "force",
    "help",
    "version",
    "color",
    "json",
    "line",
    "lines",
}

ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)


@dataclass(frozen=True)
class LineRange:
    start: int
    end: int
    reason: str


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def trim_empty_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def dedupe_adjacent(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    last: str | None = None
    for line in lines:
        if line != last:
            deduped.append(line)
        last = line
    return deduped


def head_tail(lines: list[str], head: int, tail: int) -> list[str]:
    if len(lines) <= head + tail:
        return lines
    omitted = len(lines) - head - tail
    return [*lines[:head], f"... omitted {omitted} lines ...", *lines[-tail:]]


def _normalize_range(line_range: LineRange, total_lines: int) -> LineRange | None:
    start = max(1, min(line_range.start, total_lines))
    end = max(1, min(line_range.end, total_lines))
    if start > end:
        return None
    return LineRange(start, end, line_range.reason)


def _merge_reason(existing: str, next_reason: str) -> str:
    reasons: list[str] = []
    for reason in [*existing.split(", "), *next_reason.split(", ")]:
        if reason and reason not in reasons:
            reasons.append(reason)
    return ", ".join(reasons)


def merge_ranges(ranges: list[LineRange], total_lines: int) -> list[LineRange]:
    normalized = [
        normalized
        for line_range in ranges
        if (normalized := _normalize_range(line_range, total_lines)) is not None
    ]
    normalized.sort(key=lambda line_range: (line_range.start, line_range.end))

    merged: list[LineRange] = []
    for line_range in normalized:
        if not merged or merged[-1].end + 1 < line_range.start:
            merged.append(line_range)
            continue

        previous = merged[-1]
        merged[-1] = LineRange(
            previous.start,
            max(previous.end, line_range.end),
            _merge_reason(previous.reason, line_range.reason),
        )
    return merged


def omitted_ranges(total_lines: int, shown: list[LineRange]) -> list[LineRange]:
    omitted: list[LineRange] = []
    cursor = 1
    for current in shown:
        if cursor < current.start:
            omitted.append(LineRange(cursor, current.start - 1, "omitted"))
        cursor = max(cursor, current.end + 1)
    if cursor <= total_lines:
        omitted.append(LineRange(cursor, total_lines, "omitted"))
    return omitted


def _representative_matches(
    matches: list[tuple[int, str]], max_windows: int
) -> list[tuple[int, str]]:
    matches = sorted(matches, key=lambda match: (match[0], match[1]))
    if max_windows <= 0:
        return []
    if len(matches) <= max_windows:
        return matches
    if max_windows == 1:
        return [matches[0]]

    selected: list[tuple[int, str]] = []
    used_indexes: set[int] = set()
    for index in range(max_windows):
        source_index = round(index * (len(matches) - 1) / (max_windows - 1))
        if source_index in used_indexes:
            continue
        used_indexes.add(source_index)
        selected.append(matches[source_index])
    return selected


def _signal_matches(lines: list[str], max_signal_windows: int) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        for label, pattern in SIGNAL_PATTERNS:
            if pattern.search(line):
                matches.append((line_number, label))
                break
    return _representative_matches(matches, max_signal_windows)


def _command_keywords(command: str | None) -> list[str]:
    if not command:
        return []
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    keywords: list[str] = []

    def add_keyword(value: str) -> None:
        normalized = value.strip().strip("'\"`")
        normalized = normalized.strip(".,:;()[]{}")
        if len(normalized) <= 3:
            return
        if normalized.startswith("-"):
            return
        if normalized.lower() in COMMAND_KEYWORD_STOPWORDS:
            return
        if normalized.isdigit():
            return
        if normalized not in keywords:
            keywords.append(normalized)

    def add_token_keywords(value: str) -> None:
        basename = os.path.basename(value)
        if basename:
            add_keyword(basename)
            stem, _extension = os.path.splitext(basename)
            add_keyword(stem)
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_-]{3,}", value):
            add_keyword(word)

    skip_next = False
    for index, token in enumerate(tokens[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if "=" in token:
                _flag, value = token.split("=", 1)
                add_token_keywords(value)
            elif index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                add_token_keywords(tokens[index + 1])
                skip_next = True
            continue
        add_token_keywords(token)
    return keywords


def _keyword_matches(
    lines: list[str],
    keywords: list[str],
    max_windows: int,
) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for keyword in keywords:
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                matches.append((line_number, f"command-keyword {keyword}"))
    return _representative_matches(matches, max_windows)


def _window_range(
    line_number: int,
    total_lines: int,
    context: int,
    reason: str,
) -> LineRange:
    return LineRange(
        max(1, line_number - context),
        min(total_lines, line_number + context),
        reason,
    )


def _middle_sample_ranges(
    total_lines: int,
    *,
    head: int,
    tail: int,
    middle_samples: int,
    middle_sample_size: int,
) -> list[LineRange]:
    if middle_samples <= 0 or middle_sample_size <= 0:
        return []

    interior_start = min(total_lines + 1, max(1, head + 1))
    interior_end = max(0, total_lines - tail)
    if interior_start > interior_end:
        return []

    interior_size = interior_end - interior_start + 1
    sample_size = min(middle_sample_size, interior_size)
    half = sample_size // 2
    ranges: list[LineRange] = []

    for index in range(1, middle_samples + 1):
        anchor = interior_start + round(index * (interior_size - 1) / (middle_samples + 1))
        start = max(interior_start, anchor - half)
        end = min(interior_end, start + sample_size - 1)
        start = max(interior_start, end - sample_size + 1)
        ranges.append(LineRange(start, end, "middle_sample"))
    return ranges


def indexed_fallback_ranges(
    lines: list[str],
    *,
    head: int,
    tail: int,
    signal_context: int,
    middle_samples: int,
    middle_sample_size: int,
    max_signal_windows: int,
    command: str | None = None,
    max_command_keyword_windows: int = 4,
) -> list[LineRange]:
    total_lines = len(lines)
    if total_lines == 0:
        return []

    ranges: list[LineRange] = []
    if head > 0:
        ranges.append(LineRange(1, min(head, total_lines), "head"))
    if tail > 0:
        ranges.append(LineRange(max(1, total_lines - tail + 1), total_lines, "tail"))

    for line_number, label in _signal_matches(lines, max_signal_windows):
        ranges.append(_window_range(line_number, total_lines, signal_context, f"signal: {label}"))

    for line_number, label in _keyword_matches(
        lines,
        _command_keywords(command),
        max_command_keyword_windows,
    ):
        ranges.append(_window_range(line_number, total_lines, signal_context, f"signal: {label}"))

    ranges.extend(
        _middle_sample_ranges(
            total_lines,
            head=head,
            tail=tail,
            middle_samples=middle_samples,
            middle_sample_size=middle_sample_size,
        )
    )

    return merge_ranges(ranges, total_lines)


def _render_range_list(ranges: list[LineRange], *, include_reason: bool) -> list[str]:
    if not ranges:
        return ["- none"]
    if include_reason:
        return [
            f"- {line_range.start}-{line_range.end} {line_range.reason}"
            for line_range in ranges
        ]
    return [f"- {line_range.start}-{line_range.end}" for line_range in ranges]


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
    command: str | None = None,
) -> str:
    del is_error
    shown = indexed_fallback_ranges(
        lines,
        head=head,
        tail=tail,
        signal_context=signal_context,
        middle_samples=middle_samples,
        middle_sample_size=middle_sample_size,
        max_signal_windows=max_signal_windows,
        command=command,
    )
    omitted = omitted_ranges(len(lines), shown)

    rendered: list[str] = [
        "[generic_fallback_index]",
        f"original_lines: {len(lines)}",
        "",
        "shown_ranges:",
        *_render_range_list(shown, include_reason=True),
        "",
        "omitted_ranges:",
        *_render_range_list(omitted, include_reason=False),
    ]

    for line_range in shown:
        rendered.extend(
            [
                "",
                f"[range {line_range.start}-{line_range.end} {line_range.reason}]",
                *lines[line_range.start - 1 : line_range.end],
            ]
        )

    return "\n".join(rendered).strip()


def count_pattern(lines: list[str], pattern: str, flags: str = "") -> int:
    re_flags = 0
    if "i" in flags:
        re_flags |= re.IGNORECASE
    if "m" in flags:
        re_flags |= re.MULTILINE
    compiled = re.compile(pattern, re_flags)
    return sum(1 for line in lines if compiled.search(line))
