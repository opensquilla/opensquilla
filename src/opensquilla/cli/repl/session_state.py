"""Mutable state carried by an interactive chat REPL."""

from __future__ import annotations

from dataclasses import dataclass, field

from opensquilla.cli.repl.stream import UsageCounter


def _model_alias(full: str | None) -> str:
    """Return a short display alias for a model identifier.

    - None or empty  → "…"
    - "provider/model-name" → "model-name" (segment after last "/")
    - If the segment is over 28 chars → first 12 + "…" + last 12
    - No slash → the whole string as-is
    """
    if not full:
        return "…"
    seg = full.rsplit("/", 1)[-1]
    if len(seg) > 28:
        return seg[:12] + "…" + seg[-12:]
    return seg


@dataclass
class PromptState:
    model: str | None = None
    elevated: str | None = None

    @property
    def label(self) -> str:
        mode = self.elevated or "normal"
        return f"[{_model_alias(self.model)} {mode}] you > "


@dataclass
class TranscriptTurn:
    role: str
    content: str


@dataclass
class ReplTranscript:
    turns: list[TranscriptTurn] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        if content:
            self.turns.append(TranscriptTurn(role=role, content=content))

    def clear(self) -> None:
        self.turns.clear()

    def to_markdown(self) -> str:
        chunks: list[str] = []
        for turn in self.turns:
            heading = "You" if turn.role == "user" else "Assistant"
            chunks.append(f"## {heading}\n\n{turn.content.strip()}\n")
        return "\n".join(chunks)


def messages_to_markdown(messages: list[dict]) -> str:
    chunks: list[str] = []
    for message in messages:
        role = str(message.get("role") or "message")
        if role == "user":
            heading = "You"
        elif role == "assistant":
            heading = "Assistant"
        else:
            heading = role.title()
        text = str(message.get("text") or message.get("content") or "").strip()
        if text:
            chunks.append(f"## {heading}\n\n{text}\n")
    return "\n".join(chunks)


@dataclass
class ChatSessionState:
    session_key: str
    model: str | None = None
    elevated: str | None = None
    transcript: ReplTranscript = field(default_factory=ReplTranscript)
    usage: UsageCounter = field(default_factory=UsageCounter)

    def prompt_state(self) -> PromptState:
        return PromptState(model=self.model, elevated=self.elevated)
