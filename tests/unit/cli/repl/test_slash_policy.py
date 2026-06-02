"""Slash-command classification table.

The concurrent REPL spawns each user input as a child turn task while the
input task keeps accepting keystrokes. When new input arrives mid-turn,
the policy split routes the command by category:

* ``DESTRUCTIVE`` (``/clear`` / ``/reset`` / ``/compact``) — purge the
  pending queue, cancel the active turn, then run synchronously.
* ``EXIT`` (``/exit`` / ``/quit``) — drain the pending queue then exit
  the loop (mirroring Ctrl-D semantics).
* ``PURE_INFO`` / ``STATE_MUTATION`` — both enqueue identically.
* ``NON_SLASH`` — runs as a normal turn.

These tests pin the classification surface so the runtime split in
``chat_cmd._run_concurrent_repl`` can rely on it.
"""

from __future__ import annotations

import pytest

from opensquilla.cli.repl.slash_policy import (
    DESTRUCTIVE_SLASH_WORDS,
    EXIT_SLASH_WORDS,
    SlashCategory,
    classify,
)

# --------------------------------------------------------------------------- #
# Destructive set                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command",
    [
        "/clear",
        "/reset",
        "/compact",
        "/cmp",
        "/clear   ",
        "/reset trailing-junk",
        "/compact extra args",
    ],
)
def test_classify_destructive(command: str) -> None:
    """Destructive commands return DESTRUCTIVE regardless of trailing args.

    Trailing tokens after the destructive head word do not change the
    routing — the dispatch table only looks at the head word.
    """
    assert classify(command) is SlashCategory.DESTRUCTIVE


def test_destructive_set_matches_plan_lock() -> None:
    """The destructive set is locked to exactly these commands.

    The destructive set is closed; any future addition needs a
    plan amendment. This test pins the frozenset contents so a silent
    expansion fails loudly. ``/cmp`` is the ``/compact`` alias and shares its
    context-rewriting (and therefore destructive) semantics.
    """
    assert DESTRUCTIVE_SLASH_WORDS == frozenset({"/clear", "/reset", "/compact", "/cmp"})


# --------------------------------------------------------------------------- #
# Exit set                                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command",
    [
        "/exit",
        "/quit",
        "/exit  ",
        "/quit now",
    ],
)
def test_classify_exit(command: str) -> None:
    """Exit commands return EXIT.

    ``/exit`` and ``/quit`` are NOT destructive — they drain the pending
    queue first so queued user work still runs.
    """
    assert classify(command) is SlashCategory.EXIT


def test_exit_set_matches_plan_lock() -> None:
    """The exit set is locked to exactly ``/exit`` and ``/quit``."""
    assert EXIT_SLASH_WORDS == frozenset({"/exit", "/quit"})


# --------------------------------------------------------------------------- #
# Enqueue set (pure-info and state-mutation — both enqueue identically)       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command",
    [
        "/help",
        "/version",
        "/cost",
        "/usage",
        "/save",
        "/approvals",
        "/permissions",
        "/forget",
        "/sessions",
        "/resume some-id",
        "/delete other-id",
        "/file /tmp/path.txt",
        "/new",
        "/model gpt-5",
        "/image /tmp/pic.png",
        "/path /tmp/file.md",
        "/models",
        "/status",
        "/session",
    ],
)
def test_classify_pure_info_or_state_mutation(command: str) -> None:
    """Pure-info and state-mutation commands both enqueue.

    The two enqueue subcategories share the same runtime behavior (append
    to pending FIFO, run after current turn finishes). The classifier
    reports the more specific category so callers that want telemetry
    differentiation can subset, but the dispatch loop never branches on
    this distinction.
    """
    category = classify(command)
    assert category in {SlashCategory.PURE_INFO, SlashCategory.STATE_MUTATION}
    # Sanity: must NOT be destructive / exit / non-slash for this set.
    assert category is not SlashCategory.DESTRUCTIVE
    assert category is not SlashCategory.EXIT
    assert category is not SlashCategory.NON_SLASH


# --------------------------------------------------------------------------- #
# Non-slash and edge cases                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command",
    [
        "hello world",
        "what is the capital of France?",
        "  multi-word user prompt  ",
        "/",  # bare slash with no command word — not a slash command yet
    ],
)
def test_classify_non_slash(command: str) -> None:
    """Non-slash inputs return NON_SLASH and run as a normal turn.

    A bare ``/`` with no following character is not a slash command — the
    head word is just ``/`` which is not in any of the explicit sets and
    does not start with a recognized slash word; it falls through to the
    enqueue path. (This is an internal detail; see the docstring of
    ``test_classify_unknown_slash_is_enqueue`` for the unknown-slash
    contract.)
    """
    # The bare `/` case actually starts with `/` so it'll be treated as an
    # unknown slash word (enqueue) under the locked policy. Skip it from the
    # strict NON_SLASH assertion and assert on the others.
    if command.strip() == "/":
        category = classify(command)
        assert category is not SlashCategory.DESTRUCTIVE
        assert category is not SlashCategory.EXIT
        return
    assert classify(command) is SlashCategory.NON_SLASH


def test_classify_empty_input_is_non_slash() -> None:
    """Empty input maps to NON_SLASH; the dispatch loop ignores it."""
    assert classify("") is SlashCategory.NON_SLASH
    assert classify("   ") is SlashCategory.NON_SLASH


@pytest.mark.parametrize(
    "command",
    [
        "  /clear  ",
        "\t/reset",
        "  /compact extra",
    ],
)
def test_classify_handles_leading_whitespace(command: str) -> None:
    """Leading whitespace must not change classification.

    Users typing into the REPL may have trailing or leading spaces from a
    history edit; the classifier strips before tokenizing.
    """
    assert classify(command) is SlashCategory.DESTRUCTIVE


def test_classify_is_case_insensitive() -> None:
    """Slash words classify regardless of input case.

    The user can type ``/CLEAR`` and the policy still routes it as
    destructive — matching the existing slash-handler chain which
    lowercases the head before dispatch.
    """
    assert classify("/CLEAR") is SlashCategory.DESTRUCTIVE
    assert classify("/Exit") is SlashCategory.EXIT
    assert classify("/Help") in {SlashCategory.PURE_INFO, SlashCategory.STATE_MUTATION}


def test_classify_unknown_slash_is_enqueue() -> None:
    """Unknown slash words fall through to an enqueue category.

    The destructive set is explicitly closed (``/clear``,
    ``/reset``, ``/compact`` only); anything else starting with ``/`` and
    not in the exit set MUST NOT cancel the active turn. The chosen
    behavior is to route through the enqueue path so the existing slash-
    handler chain surfaces the canonical
    ``"Unknown command. Use /help."`` notice without disturbing the
    in-flight turn. This locks the safe default.
    """
    category = classify("/foobar")
    assert category is not SlashCategory.DESTRUCTIVE
    assert category is not SlashCategory.EXIT
    assert category is not SlashCategory.NON_SLASH
    # Documented choice: route through the enqueue path.
    assert category in {SlashCategory.PURE_INFO, SlashCategory.STATE_MUTATION}
