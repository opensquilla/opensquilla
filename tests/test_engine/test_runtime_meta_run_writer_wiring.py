"""TurnRunner accepts an optional meta_run_writer kwarg."""

from __future__ import annotations

from unittest.mock import MagicMock

from opensquilla.engine.runtime import TurnRunner


def test_turnrunner_accepts_meta_run_writer_kwarg() -> None:
    """TurnRunner.__init__ accepts the new optional meta_run_writer arg."""
    mock_writer = MagicMock()
    runner = TurnRunner(
        provider_selector=None,
        config=None,
        meta_run_writer=mock_writer,
    )
    assert runner._meta_run_writer is mock_writer


def test_turnrunner_default_meta_run_writer_is_none() -> None:
    runner = TurnRunner(provider_selector=None, config=None)
    assert runner._meta_run_writer is None
