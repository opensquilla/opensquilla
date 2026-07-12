"""Regression tests for codex auth token persistence.

The original ``_persist_refreshed_tokens`` wrote the token via
``tempfile.mkstemp`` and then called ``os.chmod(tmp_name, 0o600)``
*after* writing the JSON. That leaves two problems:

1. On Windows, ``os.chmod`` is a no-op so the inherited ACL stayed
   broad (group/world-readable) until ``os.replace``.
2. Between ``mkstemp`` and ``chmod`` a parallel reader could observe
   the file at the umask-derived (typically 0o644) perms.

The fix re-opens the tmp file with explicit ``O_WRONLY | O_CREAT |
O_TRUNC | O_NOFOLLOW`` and mode ``0o600`` before writing through the
new fd, so the file is never observable at broader perms and the
tightening is bound to the open fd (no path-based TOCTOU).
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from opensquilla.provider.codex_auth import _persist_refreshed_tokens


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only apply on Unix")
def test_persist_refreshed_tokens_writes_strict_0600(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {}}), encoding="utf-8")

    _persist_refreshed_tokens(auth, {"access_token": "tok-new"})

    mode = stat.S_IMODE(os.stat(auth).st_mode)
    assert mode == 0o600, f"expected 0o600 on persisted auth file, got 0o{mode:o}"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only apply on Unix")
def test_persist_refreshed_tokens_tmp_file_is_never_broad(tmp_path: Path, monkeypatch) -> None:
    """The tmp file that lives between mkstemp and replace must be 0o600.

    We intercept ``os.open`` to capture the mode passed for the tmp
    file (the second call, after the mkstemp fd is closed), and verify
    the mode is 0o600 — not the default umask-derived value.
    """

    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {}}), encoding="utf-8")

    captured_modes: list[int] = []

    real_open = os.open

    def spy_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Only capture opens inside our tmp_path and with a numeric mode arg.
        if args and isinstance(args[0], int) and "auth-" in str(path):
            captured_modes.append(args[0])
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)

    _persist_refreshed_tokens(auth, {"access_token": "tok-new"})

    assert captured_modes, "expected os.open to be called with an explicit mode for the tmp file"
    assert all((mode & 0o777) == 0o600 for mode in captured_modes), (
        f"tmp file was opened with non-0o600 modes: {[oct(m) for m in captured_modes]}"
    )

    # The final persisted file is also 0o600.
    mode = stat.S_IMODE(os.stat(auth).st_mode)
    assert mode == 0o600


def test_persist_refreshed_tokens_preserves_payload(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"old": "v"}}), encoding="utf-8")

    _persist_refreshed_tokens(
        auth,
        {
            "access_token": "tok-new",
            "refresh_token": "refresh-new",
            "id_token": "id-new",
        },
    )

    payload = json.loads(auth.read_text(encoding="utf-8"))
    assert payload["tokens"]["access_token"] == "tok-new"
    assert payload["tokens"]["refresh_token"] == "refresh-new"
    assert payload["tokens"]["id_token"] == "id-new"
    assert payload["tokens"]["old"] == "v"  # existing fields preserved
    assert payload["last_refresh"].endswith("Z")


def test_persist_refreshed_tokens_cleans_tmp_on_write_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """If json.dump raises, the partial tmp file must be unlinked."""

    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {}}), encoding="utf-8")

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated disk error")

    monkeypatch.setattr(json, "dump", boom)

    with pytest.raises(RuntimeError):
        _persist_refreshed_tokens(auth, {"access_token": "tok-new"})

    leftovers = [
        p for p in tmp_path.iterdir()
        if p.name.startswith(".auth-") and p.is_file()
    ]
    assert leftovers == [], f"tmp auth file leaked: {leftovers}"
