"""History turn limiting, orphan tool-pairing repair, and transcript reload."""

from __future__ import annotations

import json
from typing import Any

from opensquilla.provider import (
    ContentBlockText,
    ContentBlockToolResult,
    ContentBlockToolUse,
    Message,
)


def limit_turns(messages: list[Message], max_turns: int) -> list[Message]:
    """Keep the most recent max_turns user/assistant turn pairs.

    A 'turn' is counted by user messages. Returns the original list
    reference if no truncation needed (caller can use identity check).
    """
    if max_turns <= 0 or not messages:
        return messages

    # Count user messages from the end; cut just before the (max_turns+1)th user msg
    user_count = 0
    cut_index = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            user_count += 1
            if user_count > max_turns:
                # i is the user msg we want to exclude; next msg after i is the cut point
                # but we want to start at the *next* user msg (i+2 skips the assistant at i+1)
                # Actually: cut at the user msg itself, i.e. cut_index = i + 1 would include
                # the assistant reply to this user msg. We want to exclude msg[i] and prior,
                # so cut at the first non-excluded index, which is i+1 only if i+1 is a user msg.
                # Simpler: scan forward from i+1 to find the next user message.
                cut_index = i + 1
                while cut_index < len(messages) and messages[cut_index].role != "user":
                    cut_index += 1
                break

    if cut_index == 0:
        return messages  # within budget

    return messages[cut_index:]


def _extract_tool_use_ids(content: Any) -> set[str]:
    """Extract tool_use IDs from message content."""
    ids: set[str] = set()
    if isinstance(content, list):
        for block in content:
            # ContentBlockToolUse has 'id' field
            if hasattr(block, "id") and hasattr(block, "name") and hasattr(block, "input"):
                ids.add(block.id)
    return ids


def _extract_tool_result_ids(content: Any) -> set[str]:
    """Extract tool_use_ids from tool result blocks."""
    ids: set[str] = set()
    if isinstance(content, list):
        for block in content:
            if hasattr(block, "tool_use_id") and hasattr(block, "is_error"):
                ids.add(block.tool_use_id)
    return ids


def repair_tool_pairing(messages: list[Message]) -> list[Message]:
    """Remove messages with orphaned tool_use or tool_result blocks.

    A tool_use is orphaned if no subsequent message has a matching tool_result.
    A tool_result is orphaned if no prior message has a matching tool_use.
    Returns original list reference if no repairs needed.
    """
    # Collect all tool_use IDs and tool_result IDs
    all_use_ids: set[str] = set()
    all_result_ids: set[str] = set()

    for msg in messages:
        all_use_ids.update(_extract_tool_use_ids(msg.content))
        all_result_ids.update(_extract_tool_result_ids(msg.content))

    # Find orphans
    orphan_uses = all_use_ids - all_result_ids
    orphan_results = all_result_ids - all_use_ids

    if not orphan_uses and not orphan_results:
        return messages

    # Filter out messages that ONLY contain orphan blocks
    repaired: list[Message] = []
    for msg in messages:
        use_ids = _extract_tool_use_ids(msg.content)
        result_ids = _extract_tool_result_ids(msg.content)

        # If message has tool blocks and ALL are orphaned, skip it
        if use_ids and use_ids.issubset(orphan_uses) and not isinstance(msg.content, str):
            continue
        if result_ids and result_ids.issubset(orphan_results) and not isinstance(msg.content, str):
            continue

        repaired.append(msg)

    return repaired


def _coerce_tool_input(raw: Any) -> dict[str, Any]:
    """Coerce a persisted tool_use.input back into a dict.

    Persistence may store input as dict, JSON string, or empty string (mid-stream
    partial). Anthropic's tool_use.input must conform to the tool's input_schema;
    fabricating a fallback key like ``{"_raw": ...}`` produces a shape no real
    schema declares, so on any non-dict payload we emit ``{}`` — a faithful
    "input missing" marker. Matching tool_result blocks still pair via
    tool_use_id, and ``repair_tool_pairing`` prunes any remaining orphan.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def reconstruct_messages_from_entry(
    role: str,
    content: Any,
    tool_calls: list[dict[str, Any]] | None,
    reasoning_content: str | None = None,
) -> list[Message]:
    """Rebuild provider Messages from one persisted transcript entry.

    An assistant turn is persisted as a single row whose ``tool_calls`` JSON
    column flattens every iteration's segments (text / tool_use / tool_result)
    into one ordered list. The in-memory agent loop instead appends a separate
    Message per iteration (see ``agent.run_turn``): each iteration produces an
    assistant message (text + tool_use blocks) followed, once the tools run,
    by a user message carrying tool_result blocks. A multi-iteration turn
    reloaded from disk must restore that per-iteration shape.

    Segmentation rule: a ``tool_result`` segment closes the current iteration.
    Whatever arrives after (text or tool_use) starts the next iteration — so we
    flush the accumulated assistant + user(tool_result) pair first.

    Returns ``[]`` for entries that contribute nothing. Orphan tool_use blocks
    without a matching tool_result are preserved here; ``repair_tool_pairing``
    prunes them later if they stay orphan across the whole conversation.
    """
    if role not in ("user", "assistant"):
        return []

    if role == "user":
        if content:
            return [Message(role="user", content=content)]
        return []

    if not tool_calls:
        if content:
            return [
                Message(
                    role="assistant",
                    content=content,
                    reasoning_content=reasoning_content,
                )
            ]
        return []

    messages: list[Message] = []
    pending_assistant: list[Any] = []
    pending_results: list[Any] = []

    def _flush() -> None:
        if pending_assistant:
            messages.append(Message(role="assistant", content=list(pending_assistant)))
            pending_assistant.clear()
        if pending_results:
            messages.append(Message(role="user", content=list(pending_results)))
            pending_results.clear()

    for seg in tool_calls:
        if not isinstance(seg, dict):
            continue
        seg_type = seg.get("type")
        if seg_type == "text":
            text = seg.get("text") or ""
            if not text:
                continue
            # text after a tool_result begins the next iteration → flush prior pair
            if pending_results:
                _flush()
            pending_assistant.append(ContentBlockText(text=text))
        elif seg_type == "tool_use":
            tool_use_id = seg.get("tool_use_id") or seg.get("id")
            name = seg.get("name") or ""
            if not tool_use_id or not name:
                continue
            if pending_results:
                _flush()
            pending_assistant.append(
                ContentBlockToolUse(
                    id=tool_use_id,
                    name=name,
                    input=_coerce_tool_input(seg.get("input")),
                )
            )
        elif seg_type == "tool_result":
            tool_use_id = seg.get("tool_use_id")
            if not tool_use_id:
                continue
            raw_result = seg.get("result", "")
            if isinstance(raw_result, (str, list)):
                result_content: str | list[Any] = raw_result
            else:
                result_content = str(raw_result)
            pending_results.append(
                ContentBlockToolResult(
                    tool_use_id=tool_use_id,
                    content=result_content,
                    is_error=bool(seg.get("is_error")),
                )
            )

    _flush()

    # If the segment list carried no text at all but the entry.content still
    # holds the concatenated turn text, prepend it to the first assistant
    # message as a best-effort preserve. (The per-iteration assignment is
    # ambiguous in this degenerate case, but never happens in practice — the
    # runtime flushes current_text_parts into a "text" segment before any
    # tool_use or at end of stream.)
    if (
        isinstance(content, str)
        and content.strip()
        and not any(
            isinstance(m.content, list) and any(isinstance(b, ContentBlockText) for b in m.content)
            for m in messages
            if m.role == "assistant"
        )
    ):
        first_assistant = next((m for m in messages if m.role == "assistant"), None)
        if first_assistant is not None and isinstance(first_assistant.content, list):
            first_assistant.content.insert(0, ContentBlockText(text=content))
        elif not messages:
            messages.append(Message(role="assistant", content=content))

    if isinstance(content, str) and "[generated artifact omitted:" in content:
        markers = [
            line.strip()
            for line in content.splitlines()
            if line.strip().startswith("[generated artifact omitted:")
        ]
        if markers:
            marker_text = "\n".join(markers)
            assistant = next(
                (
                    m
                    for m in reversed(messages)
                    if m.role == "assistant" and isinstance(m.content, list)
                ),
                None,
            )
            if assistant is not None:
                content_blocks = assistant.content
                if not isinstance(content_blocks, list):
                    return messages
                existing = "\n".join(
                    block.text for block in content_blocks if isinstance(block, ContentBlockText)
                )
                if marker_text not in existing:
                    content_blocks.append(ContentBlockText(text=marker_text))
            elif not messages:
                messages.append(Message(role="assistant", content=marker_text))

    if reasoning_content:
        first_assistant = next((m for m in messages if m.role == "assistant"), None)
        if first_assistant is not None:
            first_assistant.reasoning_content = reasoning_content

    return messages
