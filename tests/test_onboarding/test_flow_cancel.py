"""User-cancellation handling in the interactive onboarding flow."""

from __future__ import annotations

from typing import Any

import pytest

from opensquilla.onboarding import flow
from opensquilla.onboarding.errors import UserCancelledError


class _Prompt:
    def __init__(self, value: Any) -> None:
        self._value = value

    def ask(self) -> Any:
        return self._value


class _Questionary:
    """Minimal stand-in that returns canned answers per prompt type."""

    def __init__(
        self,
        *,
        select_value: Any = None,
        password_value: Any = None,
        confirm_value: bool = False,
    ) -> None:
        self._select = select_value
        self._password = password_value
        self._confirm = confirm_value

    def select(self, *_args, **_kwargs):
        return _Prompt(self._select)

    def password(self, *_args, **_kwargs):
        return _Prompt(self._password)

    def confirm(self, *_args, **_kwargs):
        return _Prompt(self._confirm)

    def text(self, *_args, **_kwargs):
        return _Prompt("")


def test_search_choice_cancel_raises_user_cancelled():
    q = _Questionary(select_value=None)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_search_choice(q)
    assert exc_info.value.section == "search"


def test_search_api_key_cancel_raises_user_cancelled():
    spec = flow.get_search_provider_setup_spec("brave")
    q = _Questionary(password_value=None, confirm_value=False)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_search_fields(q, spec)
    assert exc_info.value.section == "search"


def test_search_api_key_cancel_aborts_before_followup_prompts(monkeypatch):
    """Once the user cancels the api_key prompt, the helper must abort
    immediately. Counting how many times ``.ask()`` is invoked after the
    password prompt protects against future prompt-label changes without
    making the test brittle to wording."""

    spec = flow.get_search_provider_setup_spec("brave")
    asks_after_password = {"count": 0}
    password_seen = {"seen": False}

    class _CountingPrompt:
        def __init__(self, kind: str, value: Any) -> None:
            self._kind = kind
            self._value = value

        def ask(self) -> Any:
            if self._kind == "password":
                password_seen["seen"] = True
            elif password_seen["seen"]:
                asks_after_password["count"] += 1
            return self._value

    class _Tracker:
        def select(self, *_a, **_kw):
            return _CountingPrompt("select", None)

        def password(self, *_a, **_kw):
            return _CountingPrompt("password", None)

        def confirm(self, *_a, **_kw):
            return _CountingPrompt("confirm", False)

        def text(self, *_a, **_kw):
            return _CountingPrompt("text", "")

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    with pytest.raises(UserCancelledError):
        flow._ask_search_fields(_Tracker(), spec)

    assert password_seen["seen"], "password prompt should have fired"
    assert asks_after_password["count"] == 0, (
        "no further prompts should run after api_key cancel"
    )


def test_search_fallback_cancel_raises_user_cancelled(monkeypatch):
    """A cancel at the fallback-policy select used to leak ``None`` into the
    enum mapper. With ``_ask_or_cancel``, it must surface as a typed cancel
    so the optional-section runner can route the user back cleanly."""

    spec = flow.get_search_provider_setup_spec("brave")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    fired: list[str] = []

    class _Tracker:
        def select(self, label, *_a, **_kw):
            fired.append(f"select:{label}")
            # Cancel only the fallback select; let earlier selects pass.
            if "fallback" in label:
                return _Prompt(None)
            return _Prompt(None)

        def password(self, *_a, **_kw):
            fired.append("password")
            return _Prompt("explicit-key")

        def confirm(self, *_a, **_kw):
            fired.append("confirm")
            return _Prompt(False)

        def text(self, label, *_a, **_kw):
            fired.append(f"text:{label}")
            return _Prompt("5" if "Max" in label else "")

    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_search_fields(_Tracker(), spec)
    assert exc_info.value.section == "search"
    assert any("fallback" in line for line in fired)


def test_provider_choice_cancel_raises_user_cancelled():
    """Provider select returning ``None`` previously crashed with
    ``AttributeError: 'NoneType' object has no attribute 'split'``."""

    from opensquilla.onboarding.flow import OnboardOptions

    q = _Questionary(select_value=None)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_provider_choice(q, OnboardOptions())
    assert exc_info.value.section == "provider"


class _RecordingConsole:
    """Stand-in for ``opensquilla.ui.console`` that records ``print`` calls.

    The real ``console`` is a Rich ``Console`` constructed at import time with
    a captured stdout reference, which makes ``capsys`` brittle under full
    test-suite execution. Monkeypatching ``flow.console`` keeps the assertion
    deterministic regardless of how Rich initialised in earlier tests.
    """

    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message: str = "", *_a, **_kw) -> None:
        self.messages.append(str(message))

    def joined(self) -> str:
        return "\n".join(self.messages)


def test_optional_section_runner_swallows_user_cancelled(monkeypatch):
    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    def _runner():
        raise UserCancelledError(section="search")

    flow._run_optional_section(
        section="search", label="search", runner=_runner
    )

    text = recorder.joined().lower()
    assert "search setup cancelled" in text
    assert "opensquilla onboard configure search" in recorder.joined()


def test_optional_section_runner_resume_hint_uses_section_slug_not_label(monkeypatch):
    """For multi-word labels (e.g. "image generation"), the resume hint must
    use the typed section slug so the command is actually runnable."""

    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    def _runner():
        raise UserCancelledError(section="image-generation")

    flow._run_optional_section(
        section="image-generation",
        label="image generation",
        runner=_runner,
    )

    assert "opensquilla onboard configure image-generation" in recorder.joined()


def test_optional_section_runner_swallows_keyboard_interrupt(monkeypatch):
    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    def _runner():
        raise KeyboardInterrupt

    flow._run_optional_section(
        section="search", label="search", runner=_runner
    )

    assert "interrupted" in recorder.joined().lower()


def test_optional_section_runner_propagates_value_error():
    """ValueError must propagate — those usually indicate real validation
    or programming errors, not user cancels. Swallowing them would let
    "Onboarding Complete" print over a broken config."""

    def _runner():
        raise ValueError("search provider 'brave' requires an api_key")

    with pytest.raises(ValueError):
        flow._run_optional_section(
            section="search", label="search", runner=_runner
        )


def test_optional_section_runner_propagates_unexpected_exception():
    class _BoomError(RuntimeError):
        pass

    def _runner():
        raise _BoomError("unexpected")

    with pytest.raises(_BoomError):
        flow._run_optional_section(
            section="search", label="search", runner=_runner
        )
