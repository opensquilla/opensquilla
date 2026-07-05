"""Destructive-command intent extraction used by sensitive-path detection."""

from __future__ import annotations

from opensquilla.sandbox.destructive_intents import _extract_intent, _extract_intents


def test_extract_rm_targets_multiple_and_flags(tmp_path):
    intents = _extract_intents(f"rm -rf {tmp_path / 'a'} {tmp_path / 'b'}", base_dir=tmp_path)
    targets = {target for _kind, target in intents}
    assert str((tmp_path / "a").resolve()) in targets
    assert str((tmp_path / "b").resolve()) in targets
    assert all(kind == "delete" for kind, _ in intents)


def test_extract_stops_at_shell_separator():
    intents = _extract_intents("rm foo; ls bar")
    targets = [t for _k, t in intents]
    # "bar" belongs to the ls command and must not be treated as a delete target.
    assert not any(t.endswith("bar") for t in targets)


def test_extract_python_deletes():
    intents = _extract_intents("shutil.rmtree('a'); os.remove('b')")
    assert len(intents) == 2


def test_extract_intent_returns_first_or_none():
    assert _extract_intent("echo hello") is None
    first = _extract_intent("rm /tmp/x")
    assert first is not None and first[0] == "delete"
