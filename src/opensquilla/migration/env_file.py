"""Shared helpers for preserving hand-written `.env` files during migration."""

from __future__ import annotations


def env_line_key(text: str) -> str | None:
    stripped = text.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    key, _, _ = stripped.partition("=")
    return key.strip().lstrip("\ufeff")


def merge_env_lines(existing_lines: list[str], additions: dict[str, str]) -> list[str]:
    lines: list[str] = []
    consumed: set[str] = set()
    for line in existing_lines:
        key = env_line_key(line)
        if key is not None and key in additions:
            if key not in consumed:
                lines.append(f"{key}={additions[key]}")
                consumed.add(key)
            continue
        lines.append(line)
    for key, value in sorted(additions.items()):
        if key not in consumed:
            lines.append(f"{key}={value}")
    return lines
