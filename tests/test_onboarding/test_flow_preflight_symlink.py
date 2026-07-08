"""Writability preflight must probe where ``persist_config`` really writes.

``persist_config`` resolves a symlinked config path and mkstemps in the
parent of the TARGET file. A preflight that probed only the symlink's own
parent passed on a writable link directory even when the directory that
actually receives the temp file is read-only — resurfacing the exact
post-input crash the preflight was added to prevent.
"""

from __future__ import annotations

import os
from io import StringIO

import pytest
from rich.console import Console

from opensquilla.onboarding import flow
from opensquilla.onboarding.config_store import persist_config

pytestmark = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="read-only directory permissions are not enforceable for this user",
)


def _capture_console(monkeypatch) -> StringIO:
    output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=output, force_terminal=False, highlight=False, width=300),
    )
    return output


def test_preflight_fails_fast_when_symlink_target_dir_is_read_only(
    tmp_path, monkeypatch
):
    """config.toml is a symlink from a writable state dir into a read-only
    dotfiles dir: the preflight must fail with the actionable exit-2 message
    instead of passing and letting persist_config crash after all input."""
    dotfiles = tmp_path / "dotfiles_ro"
    dotfiles.mkdir()
    real = dotfiles / "config.toml"
    real.write_text("port = 18791\n")
    state = tmp_path / "state"
    state.mkdir()
    link = state / "config.toml"
    link.symlink_to(real)
    output = _capture_console(monkeypatch)

    dotfiles.chmod(0o555)
    try:
        with pytest.raises(SystemExit) as exc_info:
            flow._ensure_config_dir_writable(link)
    finally:
        dotfiles.chmod(0o755)

    assert exc_info.value.code == 2
    out = output.getvalue()
    assert "Setup directory not writable" in out
    # The message names the directory that actually receives the temp file.
    assert str(dotfiles) in out


def test_preflight_probes_the_same_directory_persist_config_writes(
    tmp_path, monkeypatch
):
    """Positive twin: with a writable symlink target the preflight passes,
    and a subsequent persist really lands in the resolved target's parent —
    the two sides agree on WHERE the write happens."""
    dotfiles = tmp_path / "dotfiles_rw"
    dotfiles.mkdir()
    real = dotfiles / "config.toml"
    real.write_text("port = 18791\n")
    state = tmp_path / "state"
    state.mkdir()
    link = state / "config.toml"
    link.symlink_to(real)

    flow._ensure_config_dir_writable(link)  # must not raise

    from opensquilla.onboarding.config_store import load_config

    cfg = load_config(link)
    result = persist_config(cfg, path=link, backup=False)
    # persist reports (and writes) the RESOLVED target — the directory the
    # preflight must therefore probe.
    assert result.path == real
    assert link.is_symlink(), "persist must write through the link, not replace it"
    assert real.exists()
    # No stray probe files left behind on either side.
    assert [p.name for p in dotfiles.iterdir()] == ["config.toml"]
    assert [p.name for p in state.iterdir()] == ["config.toml"]
