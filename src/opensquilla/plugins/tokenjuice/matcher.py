from __future__ import annotations

import re
import shlex
from typing import Any

from .types import Rule


def command_argv(command: str | None, argv: list[str] | None = None) -> list[str]:
    if argv:
        return argv
    if not command:
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value]


def _list_of_string_lists(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [
        [item for item in entry if isinstance(item, str)]
        for entry in value
        if isinstance(entry, list)
    ]


def _contains_all(argv: list[str], needles: list[str]) -> bool:
    return all(needle in argv for needle in needles)


def _contains_command_text(command: str, needles: list[str]) -> bool:
    lowered = command.lower()
    return all(needle.lower() in lowered for needle in needles)


def rule_matches(
    rule: Rule,
    *,
    tool_name: str,
    command: str | None,
    argv: list[str] | None,
    content: str,
    exit_code: int,
) -> bool:
    match = rule.match
    if not match:
        return True

    normalized_tool = "exec" if command else tool_name
    tool_names = _list_of_strings(match.get("toolNames"))
    if tool_names and normalized_tool not in tool_names and tool_name not in tool_names:
        return False

    tokens = command_argv(command, argv)
    argv0 = _list_of_strings(match.get("argv0"))
    if argv0 and (not tokens or tokens[0] not in argv0):
        return False

    argv_includes = _list_of_string_lists(match.get("argvIncludes"))
    if argv_includes and not any(_contains_all(tokens, entry) for entry in argv_includes):
        return False

    command_text = command or " ".join(tokens)
    command_includes = _list_of_strings(match.get("commandIncludes"))
    if command_includes and not _contains_command_text(command_text, command_includes):
        return False

    command_includes_any = _list_of_strings(match.get("commandIncludesAny"))
    if command_includes_any and not any(
        needle.lower() in command_text.lower() for needle in command_includes_any
    ):
        return False

    command_regex = match.get("commandRegex")
    if isinstance(command_regex, str) and not re.search(command_regex, command_text):
        return False

    exit_codes = match.get("exitCodes")
    if isinstance(exit_codes, list) and exit_codes and exit_code not in exit_codes:
        return False

    output_regex = match.get("outputRegex")
    if isinstance(output_regex, str) and not re.search(output_regex, content, re.MULTILINE):
        return False

    return True


def select_rule(
    rules: tuple[Rule, ...],
    *,
    tool_name: str,
    command: str | None,
    argv: list[str] | None,
    content: str,
    exit_code: int,
) -> Rule | None:
    for rule in rules:
        if rule_matches(
            rule,
            tool_name=tool_name,
            command=command,
            argv=argv,
            content=content,
            exit_code=exit_code,
        ):
            return rule
    return None
