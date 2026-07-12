from __future__ import annotations

import json
import stat
import uuid
from pathlib import Path

import pytest

from opensquilla.recovery import inspect_profile, path_identity
from opensquilla.recovery.errors import RecoveryError, StaleRecoveryTransactionError
from opensquilla.recovery.transaction import (
    recover_profile_transaction,
    typed_transaction_available,
)


def _profile(home: Path, marker: str) -> Path:
    workspace = home / "workspace"
    state = home / "state"
    workspace.mkdir(parents=True)
    state.mkdir()
    (workspace / "SOUL.md").write_text(marker + "\n", encoding="utf-8")
    (home / "config.toml").write_text(
        'state_dir = "state"\nworkspace_dir = "workspace"\n',
        encoding="utf-8",
    )
    return home


def _identity_payload(path: Path) -> dict[str, int]:
    identity = path_identity(path)
    return {
        "device": identity.device,
        "inode": identity.inode,
        "file_type": stat.S_IFMT(identity.mode),
        "mode": identity.mode,
        "size": identity.size,
        "modified_at_ns": identity.modified_at_ns,
    }


def _write_journal(home: Path, payload: dict[str, object]) -> Path:
    path = home.parent / f".{home.name}.profile-replace.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _import_payload(
    home: Path,
    *,
    transaction_id: str,
    source: Path,
    backup: Path,
    staging: Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "profile-import",
        "source_kind": "cli-home",
        "transaction_id": transaction_id,
        "source": str(source),
        "target": str(home),
        "backup": str(backup),
        "staging": str(staging),
        "phase": "target_parked",
        "target_existed": True,
        "target_had_real_data": True,
        "target_was_empty": False,
        "identities": {
            "source": _identity_payload(source),
            "original_target": _identity_payload(backup),
            "staging": _identity_payload(staging),
            "backup": _identity_payload(backup),
            "candidate": None,
        },
    }


def test_typed_import_without_adapter_fails_closed_without_mutation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "opensquilla"
    source = _profile(tmp_path / "source", "source must remain untouched")
    transaction_id = str(uuid.uuid4())
    backup = _profile(home.with_name(f"{home.name}.backup.{transaction_id}"), "original")
    staging = _profile(
        home.parent / f".{home.name}.profile-staging.{transaction_id}",
        "unpublished candidate",
    )
    journal = _write_journal(
        home,
        _import_payload(
            home,
            transaction_id=transaction_id,
            source=source,
            backup=backup,
            staging=staging,
        ),
    )
    before_bytes = {
        path: (path / "workspace" / "SOUL.md").read_bytes()
        for path in (source, backup, staging)
    }
    report = inspect_profile(home, profile_kind="desktop-primary")

    assert report.stable_code == "transaction_incomplete"
    assert "recover-transaction" in report.allowed_actions
    with pytest.raises(RecoveryError) as caught:
        recover_profile_transaction(
            home,
            transaction_id=report.transaction_id,
            expected_revision=report.revision,
        )

    assert caught.value.stable_code == "transaction_recovery_unsafe"
    assert not home.exists()
    assert journal.is_file()
    for path, expected in before_bytes.items():
        assert (path / "workspace" / "SOUL.md").read_bytes() == expected


def test_typed_restore_without_restore_module_fails_closed_without_mutation(
    tmp_path: Path,
) -> None:
    home = _profile(tmp_path / "opensquilla", "current")
    selected = _profile(tmp_path / "opensquilla.backup.selected", "selected")
    transaction_id = str(uuid.uuid4())
    backup = home.with_name(f"{home.name}.backup.{transaction_id}")
    payload = {
        "schema_version": 1,
        "operation": "restore-profile",
        "transaction_id": transaction_id,
        "source": str(selected),
        "target": str(home),
        "backup": str(backup),
        "staging": "",
        "phase": "prepared",
        "target_existed": True,
        "identities": {
            "source": _identity_payload(selected),
            "original_target": _identity_payload(home),
            "staging": None,
            "backup": None,
            "candidate": _identity_payload(selected),
        },
    }
    journal = _write_journal(home, payload)
    current_before = (home / "workspace" / "SOUL.md").read_bytes()
    selected_before = (selected / "workspace" / "SOUL.md").read_bytes()
    report = inspect_profile(home, profile_kind="desktop-primary")

    assert typed_transaction_available(home)
    assert "recover-transaction" in report.allowed_actions
    with pytest.raises(RecoveryError) as caught:
        recover_profile_transaction(
            home,
            transaction_id=report.transaction_id,
            expected_revision=report.revision,
        )

    assert caught.value.stable_code == "transaction_recovery_unsafe"
    assert journal.is_file()
    assert not backup.exists()
    assert (home / "workspace" / "SOUL.md").read_bytes() == current_before
    assert (selected / "workspace" / "SOUL.md").read_bytes() == selected_before


def test_untyped_or_tampered_journal_has_no_automatic_recovery_action(
    tmp_path: Path,
) -> None:
    home = _profile(tmp_path / "opensquilla", "current")
    _write_journal(
        home,
        {
            "schema_version": 1,
            "phase": "prepared",
            "transaction_id": str(uuid.uuid4()),
        },
    )

    report = inspect_profile(home, profile_kind="desktop-primary")

    assert report.outcome == "recovery_required"
    assert report.stable_code == "transaction_incomplete"
    assert "recover-transaction" not in report.allowed_actions


@pytest.mark.parametrize("tamper", ["extra", "empty-identities", "missing-flags"])
def test_almost_typed_import_journal_is_read_only_and_not_recoverable(
    tmp_path: Path,
    tamper: str,
) -> None:
    home = _profile(tmp_path / "opensquilla", "current")
    source = _profile(tmp_path / "source", "source")
    transaction_id = str(uuid.uuid4())
    staging = _profile(
        home.parent / f".{home.name}.profile-staging.{transaction_id}",
        "candidate",
    )
    backup = home.with_name(f"{home.name}.backup.{transaction_id}")
    home_identity = _identity_payload(home)
    payload: dict[str, object] = {
        "schema_version": 1,
        "operation": "profile-import",
        "source_kind": "cli-home",
        "transaction_id": transaction_id,
        "source": str(source),
        "target": str(home),
        "backup": str(backup),
        "staging": str(staging),
        "phase": "prepared",
        "target_existed": True,
        "target_had_real_data": True,
        "target_was_empty": False,
        "identities": {
            "source": _identity_payload(source),
            "original_target": home_identity,
            "staging": _identity_payload(staging),
            "backup": home_identity,
            "candidate": None,
        },
    }
    if tamper == "extra":
        payload["unexpected"] = "future"
    elif tamper == "empty-identities":
        payload["identities"] = {}
    else:
        payload.pop("target_had_real_data")
        payload.pop("target_was_empty")
    journal = _write_journal(home, payload)
    journal_before = journal.read_bytes()
    home_before = (home / "workspace" / "SOUL.md").read_bytes()
    source_before = (source / "workspace" / "SOUL.md").read_bytes()
    staging_before = (staging / "workspace" / "SOUL.md").read_bytes()

    report = inspect_profile(home, profile_kind="desktop-primary")

    assert report.outcome == "recovery_required"
    assert report.stable_code == "transaction_incomplete"
    assert "recover-transaction" not in report.allowed_actions
    assert journal.read_bytes() == journal_before
    assert (home / "workspace" / "SOUL.md").read_bytes() == home_before
    assert (source / "workspace" / "SOUL.md").read_bytes() == source_before
    assert (staging / "workspace" / "SOUL.md").read_bytes() == staging_before
    assert not backup.exists()


def test_recovery_revision_rejects_a_typed_journal_replaced_after_inspection(
    tmp_path: Path,
) -> None:
    home = tmp_path / "opensquilla"
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    first_source = _profile(tmp_path / "source-first", "first source")
    second_source = _profile(tmp_path / "source-second", "second source")
    first_backup = _profile(
        home.with_name(f"{home.name}.backup.{first_id}"),
        "first original",
    )
    second_backup = _profile(
        home.with_name(f"{home.name}.backup.{second_id}"),
        "second original",
    )
    first_staging = _profile(
        home.parent / f".{home.name}.profile-staging.{first_id}",
        "first candidate",
    )
    second_staging = _profile(
        home.parent / f".{home.name}.profile-staging.{second_id}",
        "second candidate",
    )
    first_payload = _import_payload(
        home,
        transaction_id=first_id,
        source=first_source,
        backup=first_backup,
        staging=first_staging,
    )
    second_payload = _import_payload(
        home,
        transaction_id=second_id,
        source=second_source,
        backup=second_backup,
        staging=second_staging,
    )
    journal = _write_journal(home, first_payload)
    inspected = inspect_profile(home, profile_kind="desktop-primary")
    journal.write_text(json.dumps(second_payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(StaleRecoveryTransactionError):
        recover_profile_transaction(
            home,
            transaction_id=inspected.transaction_id,
            expected_revision=inspected.revision,
        )

    assert journal.is_file()
    assert first_backup.is_dir()
    assert first_staging.is_dir()
    assert second_backup.is_dir()
    assert second_staging.is_dir()
