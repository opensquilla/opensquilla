"""Slash-command classification for the concurrent chat REPL.

The concurrent REPL spawns each user input as a child turn task while the
input task keeps accepting keystrokes. When new input arrives mid-turn, the
policy split below decides whether the new command:

* **PURGES** the pending FIFO queue, cancels the current turn task, then
  runs immediately (``/clear``, ``/reset``, ``/compact``);
* **ENQUEUES** behind the current turn (state-mutation and pure-info
  commands) — both subclasses behave identically so the distinction is
  purely informational;
* **DRAINS** the pending queue and exits the loop (``/exit``, ``/quit``);
* runs as a non-slash turn through the normal flow.

The destructive and exit word sets are explicit frozensets to make the
behavior auditable; everything else is treated as enqueuable. Unknown
slash words (not in any of the explicit sets) are also treated as
enqueuable so the existing slash-handler chain can surface the canonical
"Unknown command. Use /help." notice synchronously inside the dispatch
without disturbing the in-flight turn.

The pure-info-vs-state-mutation distinction is internal taxonomy only:
both categories enqueue identically. Callers that need the finer split
(e.g., for future telemetry) can subset on the names below.
"""

from __future__ import annotations

from enum import Enum


class SlashCategory(Enum):
    """How the concurrent REPL routes a single input.

    ``DESTRUCTIVE`` and ``EXIT`` are the only categories the dispatch loop
    actually branches on; ``STATE_MUTATION`` and ``PURE_INFO`` both reach
    the same enqueue path. ``NON_SLASH`` short-circuits to the regular
    turn-task spawn.
    """

    DESTRUCTIVE = "destructive"
    STATE_MUTATION = "state_mutation"
    PURE_INFO = "pure_info"
    EXIT = "exit"
    NON_SLASH = "non_slash"


# Destructive commands clear pending work AND cancel the active turn before
# their handler runs. The plan locks these to the context-rewriting slash
# words; /cmp is the /compact alias and shares its destructive semantics.
DESTRUCTIVE_SLASH_WORDS: frozenset[str] = frozenset(
    {"/clear", "/reset", "/compact", "/cmp"}
)

# Exit commands drain the pending queue and then terminate the loop, mirroring
# the Ctrl-D / EOF path. They MUST NOT discard queued user work.
EXIT_SLASH_WORDS: frozenset[str] = frozenset({"/exit", "/quit"})

# Pure-info commands. Both pure-info and state-mutation enqueue identically;
# this set exists so the classifier can return a more specific category for
# callers that want it (and for the unit tests pinning the taxonomy). Keep in
# sync with the slash-command policy table.
PURE_INFO_SLASH_WORDS: frozenset[str] = frozenset(
    {
        "/help",
        "/version",
        "/cost",
        "/usage",
        "/save",
        "/approvals",
        "/permissions",
        "/forget",
        "/sessions",
        "/resume",
        "/delete",
        "/file",
    }
)

# State-mutation commands. Same enqueue behavior as pure-info; kept distinct
# so the classifier reports the more accurate category for callers that want
# to differentiate (e.g., for telemetry).
STATE_MUTATION_SLASH_WORDS: frozenset[str] = frozenset(
    {
        "/new",
        "/model",
        "/image",
        "/path",
        "/models",
        "/status",
        "/session",
        "/elevated",
    }
)


def _head_word(input_text: str) -> str:
    """Return the lowercased first whitespace-delimited token of ``input_text``.

    Leading whitespace is tolerated so that ``"  /clear  "`` classifies the
    same as ``"/clear"``. Empty input maps to ``""`` so ``classify`` can
    fast-path to ``NON_SLASH``.
    """
    stripped = input_text.strip()
    if not stripped:
        return ""
    return stripped.split(maxsplit=1)[0].lower()


def classify(input_text: str) -> SlashCategory:
    """Return the routing category for ``input_text``.

    Classification looks only at the first whitespace-delimited token of
    the input (lowercased, leading whitespace stripped). Anything that
    does not start with ``/`` returns ``NON_SLASH``. Slash words in the
    explicit destructive / exit / pure-info / state-mutation sets return
    the matching category. Unknown slash words fall through to
    ``STATE_MUTATION`` — they enqueue (which is the safe default) so the
    existing slash-handler chain can surface the canonical
    "Unknown command. Use /help." notice without disturbing the
    in-flight turn.
    """
    head = _head_word(input_text)
    if not head or not head.startswith("/"):
        return SlashCategory.NON_SLASH
    if head in DESTRUCTIVE_SLASH_WORDS:
        return SlashCategory.DESTRUCTIVE
    if head in EXIT_SLASH_WORDS:
        return SlashCategory.EXIT
    if head in PURE_INFO_SLASH_WORDS:
        return SlashCategory.PURE_INFO
    if head in STATE_MUTATION_SLASH_WORDS:
        return SlashCategory.STATE_MUTATION
    # Unknown slash word: treat as enqueuable so the slash-handler chain can
    # surface the "Unknown command" notice without cancelling the active turn.
    return SlashCategory.STATE_MUTATION


__all__ = [
    "DESTRUCTIVE_SLASH_WORDS",
    "EXIT_SLASH_WORDS",
    "PURE_INFO_SLASH_WORDS",
    "STATE_MUTATION_SLASH_WORDS",
    "SlashCategory",
    "classify",
]
