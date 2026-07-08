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
    ],
)
def test_classify_destructive(command: str) -> None:
    """Exact bare destructive words return DESTRUCTIVE.

    Only the exact bare lowercase word qualifies: the slash handlers match
    exact strings, so anything else must not purge queued work and then
    fall through to "Unknown command".
    """
    assert classify(command) is SlashCategory.DESTRUCTIVE


@pytest.mark.parametrize(
    "command",
    [
        "/reset trailing-junk",
        "/compact extra args",
        "/CLEAR",
        "/Clear",
    ],
)
def test_classify_destructive_requires_exact_bare_word(command: str) -> None:
    """Case slips and stray arguments never classify as DESTRUCTIVE.

    Destructive routing purges the pending queue and cancels the in-flight
    turn BEFORE dispatch, while the handlers only match the exact bare
    lowercase word — so these variants must enqueue instead, letting the
    handler chain surface "Unknown command" without destroying work.
    """
    assert classify(command) is not SlashCategory.DESTRUCTIVE


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
    ],
)
def test_classify_exit(command: str) -> None:
    """Exact bare exit words return EXIT.

    ``/exit`` and ``/quit`` are NOT destructive — they drain the pending
    queue first so queued user work still runs.
    """
    assert classify(command) is SlashCategory.EXIT


@pytest.mark.parametrize("command", ["/quit now", "/Exit", "/EXIT stuff"])
def test_classify_exit_requires_exact_bare_word(command: str) -> None:
    """Case slips and stray arguments never classify as EXIT.

    EXIT drains the queue and terminates the loop before dispatch; a
    variant the handlers would reject must enqueue instead.
    """
    assert classify(command) is not SlashCategory.EXIT


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
    ],
)
def test_classify_handles_leading_whitespace(command: str) -> None:
    """Surrounding whitespace must not change classification.

    Users typing into the REPL may have trailing or leading spaces from a
    history edit; the classifier strips before matching the bare word.
    """
    assert classify(command) is SlashCategory.DESTRUCTIVE


def test_classify_destructive_and_exit_are_case_sensitive() -> None:
    """DESTRUCTIVE/EXIT match only the exact lowercase spelling.

    The handlers match exact lowercase strings, so ``/CLEAR`` must not
    purge the queue and cancel the turn only to land on "Unknown
    command". Enqueue categories keep matching case-insensitively via the
    lowercased head word.
    """
    assert classify("/CLEAR") is not SlashCategory.DESTRUCTIVE
    assert classify("/Exit") is not SlashCategory.EXIT
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


# --------------------------------------------------------------------------- #
# Local (host-only UI) set                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("command", ["/theme", "/theme midnight", "/theme   ", "/THEME"])
def test_classify_local_theme(command: str) -> None:
    """/theme is a host-only UI command -> LOCAL.

    LOCAL commands run immediately (inline on the runtime loop), are never echoed
    as a prompt block, and are never queued behind an in-flight turn.
    """
    assert classify(command) is SlashCategory.LOCAL


def test_local_set_is_narrow_and_disjoint() -> None:
    from opensquilla.cli.repl.slash_policy import (
        LOCAL_SLASH_WORDS,
        PURE_INFO_SLASH_WORDS,
        STATE_MUTATION_SLASH_WORDS,
    )

    # Keep LOCAL narrow: only side-effect-free host commands belong here today.
    assert LOCAL_SLASH_WORDS == {"/theme"}
    # LOCAL must not overlap any queue/cancel/exit category.
    for other in (
        DESTRUCTIVE_SLASH_WORDS,
        EXIT_SLASH_WORDS,
        PURE_INFO_SLASH_WORDS,
        STATE_MUTATION_SLASH_WORDS,
    ):
        assert not (LOCAL_SLASH_WORDS & other)
