"""Lossless, CAS-protected patches for the top-level workspace setting."""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from opensquilla.recovery.atomic import (
    PathIdentity,
    _windows_extended_path,
    native_move_no_replace,
)
from opensquilla.recovery.errors import (
    ConfigChangedError,
    RecoveryError,
    UnsafePathError,
    WorkspaceOverrideError,
)

WORKSPACE_OVERRIDE_ENV_VARS = (
    "OPENSQUILLA_GATEWAY_WORKSPACE_DIR",
    # Kept for the standalone TUI compatibility spelling. It is not a
    # GatewayConfig source today, but treating it as an override is safer than
    # silently writing a setting the visible runtime may ignore.
    "OPENSQUILLA_WORKSPACE_DIR",
)
STATE_OVERRIDE_ENV_VARS = ("OPENSQUILLA_GATEWAY_STATE_DIR",)
_DOTENV_MAX_BYTES = 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_COPYFILE_ACL = 1 << 0
_COPYFILE_XATTR = 1 << 2

_TOP_LEVEL_KEY_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>workspace_dir|\"workspace_dir\"|'workspace_dir')(?P<spacing>\s*=\s*)"
)


@dataclass(frozen=True)
class ConfigSnapshot:
    path: Path
    identity: PathIdentity | None
    mode: int
    data: bytes
    digest: bytes

    @classmethod
    def capture(cls, path: str | Path) -> ConfigSnapshot:
        config_path = Path(path)
        try:
            path_stat = config_path.lstat()
        except FileNotFoundError:
            return cls(
                path=config_path,
                identity=None,
                mode=0o600,
                data=b"",
                digest=hashlib.sha256(b"").digest(),
            )
        except OSError as exc:
            raise UnsafePathError(
                f"cannot inspect config without following links: {config_path}"
            ) from exc
        path_attributes = int(getattr(path_stat, "st_file_attributes", 0))
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or path_attributes & _FILE_ATTRIBUTE_REPARSE_POINT
            or not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
        ):
            raise UnsafePathError(f"config must be a regular non-reparse file: {config_path}")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(config_path, flags)
        except FileNotFoundError as exc:
            raise ConfigChangedError("config disappeared while it was being opened") from exc
        except OSError as exc:
            raise UnsafePathError(
                f"cannot read config without following links: {config_path}"
            ) from exc
        try:
            before = os.fstat(fd)
            before_attributes = int(getattr(before, "st_file_attributes", 0))
            if (
                before_attributes & _FILE_ATTRIBUTE_REPARSE_POINT
                or not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
            ):
                raise UnsafePathError(f"config must be a regular single-link file: {config_path}")
            if (
                PathIdentity.from_stat(path_stat).metadata_tuple()
                != PathIdentity.from_stat(before).metadata_tuple()
            ):
                raise ConfigChangedError("config identity changed while it was being opened")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        before_identity = PathIdentity.from_stat(before)
        after_identity = PathIdentity.from_stat(after)
        if before_identity.metadata_tuple() != after_identity.metadata_tuple():
            raise ConfigChangedError("config changed while it was being read")
        data = b"".join(chunks)
        return cls(
            path=config_path,
            identity=after_identity,
            mode=stat.S_IMODE(after.st_mode),
            data=data,
            digest=hashlib.sha256(data).digest(),
        )

    def assert_current(self) -> None:
        current = ConfigSnapshot.capture(self.path)
        expected_identity = self.identity.metadata_tuple() if self.identity is not None else None
        current_identity = (
            current.identity.metadata_tuple() if current.identity is not None else None
        )
        if current_identity != expected_identity or current.digest != self.digest:
            raise ConfigChangedError("config changed after recovery preflight")


def _parse_dotenv_value(
    raw: str,
    *,
    label: str,
    error_type: type[RecoveryError],
    stable_code: str,
) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        escaped = False
        end = -1
        for index in range(1, len(value)):
            character = value[index]
            if quote == '"' and escaped:
                escaped = False
                continue
            if quote == '"' and character == "\\":
                escaped = True
                continue
            if character == quote:
                end = index
                break
        tail = value[end + 1 :].strip() if end >= 0 else ""
        if end < 0 or (tail and not tail.startswith("#")):
            raise error_type(
                f"{label} override in profile dotenv is not safely parseable",
                stable_code=stable_code,
            )
        parsed = value[1:end]
        if quote == '"':
            replacements = {
                r"\\": "\\",
                r'\"': '"',
                r"\n": "\n",
                r"\r": "\r",
                r"\t": "\t",
            }
            for encoded, decoded in replacements.items():
                parsed = parsed.replace(encoded, decoded)
        else:
            parsed = parsed.replace(r"\'", "'").replace(r"\\", "\\")
    else:
        # python-dotenv treats a whitespace-prefixed # as an inline comment.
        parsed = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    if "$" in parsed:
        # Normal dotenv bootstrap performs interpolation. Recovery deliberately
        # does not evaluate a general dotenv language or ambient substitutions;
        # an operator can remove the override or use a literal path.
        raise error_type(
            f"interpolated {label} override in profile dotenv is not safe offline",
            stable_code=stable_code,
        )
    return parsed


def _profile_dotenv_path(home: Path, *, include_legacy: bool) -> Path | None:
    current = home / ".env"
    if os.path.lexists(current):
        return current
    if not include_legacy:
        return None
    legacy = home / "state" / ".env"
    return legacy if os.path.lexists(legacy) else None


def _profile_dotenv_override(
    home: Path,
    *,
    include_legacy: bool,
    names: tuple[str, ...],
    label: str,
    error_type: type[RecoveryError],
    stable_code: str,
) -> tuple[str, str] | None:
    path = _profile_dotenv_path(home, include_legacy=include_legacy)
    if path is None:
        return None
    try:
        snapshot = ConfigSnapshot.capture(path)
    except RecoveryError as exc:
        raise error_type(
            "profile dotenv cannot be inspected without following links",
            stable_code=stable_code,
        ) from exc
    if snapshot.identity is None:
        return None
    if snapshot.identity.size > _DOTENV_MAX_BYTES:
        raise error_type(
            "profile dotenv is too large for offline recovery inspection",
            stable_code=stable_code,
        )
    try:
        text = snapshot.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error_type(
            "profile dotenv is not valid UTF-8",
            stable_code=stable_code,
        ) from exc
    parsed: dict[str, str] = {}
    key_pattern = "|".join(re.escape(name) for name in names)
    assignment = re.compile(
        rf"^\s*(?:export\s+)?(?P<key>{key_pattern})\s*=\s*(?P<value>.*)$"
    )
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = assignment.match(raw_line)
        if match is None:
            continue
        parsed[match.group("key")] = _parse_dotenv_value(
            match.group("value"),
            label=label,
            error_type=error_type,
            stable_code=stable_code,
        )
    for name in names:
        value = parsed.get(name, "").strip()
        if value:
            return name, value
    return None


def workspace_override(
    home: str | Path | None = None,
    *,
    include_legacy_dotenv: bool = False,
) -> tuple[str, str] | None:
    """Resolve only workspace overrides without loading a general dotenv.

    Process environment keeps normal precedence. When a Desktop home is
    supplied, inspect the current profile dotenv (or the legacy dotenv that a
    proven reconciliation would publish) with a narrow, no-follow parser.
    """

    for name in WORKSPACE_OVERRIDE_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return name, value
    if home is None:
        return None
    return _profile_dotenv_override(
        Path(home).expanduser().absolute(),
        include_legacy=include_legacy_dotenv,
        names=WORKSPACE_OVERRIDE_ENV_VARS,
        label="workspace",
        error_type=WorkspaceOverrideError,
        stable_code="workspace_env_override_unsafe",
    )


def state_override(
    home: str | Path | None = None,
    *,
    include_legacy_dotenv: bool = False,
    include_process_environment: bool = True,
) -> tuple[str, str] | None:
    """Resolve the Gateway state root without loading a general dotenv."""

    if include_process_environment:
        for name in STATE_OVERRIDE_ENV_VARS:
            value = os.environ.get(name, "").strip()
            if value:
                return name, value
    if home is None:
        return None
    return _profile_dotenv_override(
        Path(home).expanduser().absolute(),
        include_legacy=include_legacy_dotenv,
        names=STATE_OVERRIDE_ENV_VARS,
        label="state",
        error_type=RecoveryError,
        stable_code="state_env_override_unsafe",
    )


def _comment_start(value: str) -> int | None:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if quote == "'":
            if character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
        elif character == "#":
            return index
    return None


def _patch_text(raw: str, workspace: Path) -> str:
    replacement = json.dumps(str(workspace), ensure_ascii=False)
    lines = raw.splitlines(keepends=True)
    table_index = len(lines)
    matched_index: int | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("["):
            table_index = index
            break
        match = _TOP_LEVEL_KEY_RE.match(line)
        if match is None:
            continue
        if matched_index is not None:
            raise RecoveryError(
                "config contains duplicate top-level workspace_dir keys",
                stable_code="config_invalid",
            )
        matched_index = index
        suffix = line[match.end() :]
        newline = ""
        if suffix.endswith("\r\n"):
            suffix, newline = suffix[:-2], "\r\n"
        elif suffix.endswith("\n"):
            suffix, newline = suffix[:-1], "\n"
        comment_index = _comment_start(suffix)
        comment = suffix[comment_index:] if comment_index is not None else ""
        spacing_before_comment = " " if comment and not comment.startswith(" ") else ""
        lines[index] = (
            f"{match.group('indent')}{match.group('key')}{match.group('spacing')}"
            f"{replacement}{spacing_before_comment}{comment}{newline}"
        )

    if matched_index is None:
        newline = "\r\n" if "\r\n" in raw else "\n"
        insertion = f"workspace_dir = {replacement}{newline}"
        if table_index > 0 and lines[table_index - 1].strip():
            insertion += newline
        lines.insert(table_index, insertion)
    patched = "".join(lines)
    if not lines:
        patched = f"workspace_dir = {replacement}\n"
    try:
        payload = tomllib.loads(patched)
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise RecoveryError(
            "lossless workspace patch would produce invalid TOML",
            stable_code="config_invalid",
        ) from exc
    if payload.get("workspace_dir") != str(workspace):
        raise RecoveryError(
            "workspace_dir could not be patched as a top-level TOML key",
            stable_code="config_invalid",
        )
    return patched


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _create_backup(snapshot: ConfigSnapshot) -> Path | None:
    if snapshot.identity is None:
        return None
    backup = snapshot.path.with_name(f"{snapshot.path.name}.backup.{uuid.uuid4()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(backup, flags, 0o600)
    try:
        _write_all(fd, snapshot.data)
        with contextlib.suppress(OSError):
            os.fchmod(fd, 0o600)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        with contextlib.suppress(OSError):
            backup.unlink()
        raise
    os.close(fd)
    return backup


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_macos_config_metadata(snapshot: ConfigSnapshot, destination_fd: int) -> None:
    """Copy ACLs/xattrs with fcopyfile; copystat alone drops macOS ACL entries."""

    if sys.platform != "darwin" or snapshot.identity is None:
        return
    libc = ctypes.CDLL(None, use_errno=True)
    fcopyfile = getattr(libc, "fcopyfile", None)
    if fcopyfile is None:
        raise RecoveryError(
            "macOS ACL preservation is unavailable",
            stable_code="config_metadata_preservation_failed",
        )
    fcopyfile.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    fcopyfile.restype = ctypes.c_int
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(snapshot.path, flags)
    except OSError as exc:
        raise ConfigChangedError(
            "config changed before its ACLs could be preserved"
        ) from exc
    try:
        current = PathIdentity.from_stat(os.fstat(source_fd))
        if current.metadata_tuple() != snapshot.identity.metadata_tuple():
            raise ConfigChangedError(
                "config changed before its ACLs could be preserved"
            )
        if fcopyfile(
            source_fd,
            destination_fd,
            None,
            _COPYFILE_ACL | _COPYFILE_XATTR,
        ) != 0:
            error_number = ctypes.get_errno()
            raise RecoveryError(
                f"macOS ACL or extended metadata could not be preserved ({error_number})",
                stable_code="config_metadata_preservation_failed",
            )
    finally:
        os.close(source_fd)


def _replace_existing_config(temporary_path: Path, config_path: Path) -> None:
    if os.name == "nt":
        win_dll = getattr(ctypes, "WinDLL")
        kernel32 = win_dll("kernel32", use_last_error=True)
        replace_file = kernel32.ReplaceFileW
        replace_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        replace_file.restype = ctypes.c_int
        if not replace_file(
            _windows_extended_path(config_path),
            _windows_extended_path(temporary_path),
            None,
            0,
            None,
            None,
        ):
            error_number = getattr(ctypes, "get_last_error")()
            raise RecoveryError(
                f"Windows ReplaceFileW failed with error {error_number}",
                stable_code="config_publish_failed",
            )
        return
    os.replace(temporary_path, config_path)


def patch_workspace_dir(home: str | Path, workspace: str | Path) -> Path | None:
    """Patch only top-level ``workspace_dir`` and return the backup path.

    The content digest lives only in this process and is never included in a
    receipt, log, exception, or protocol response.
    """

    home_path = Path(home).expanduser().absolute()
    override = workspace_override(home_path)
    if override is not None:
        name, _value = override
        raise WorkspaceOverrideError(f"remove {name} before changing the persisted workspace path")
    workspace_path = Path(workspace).expanduser().absolute()
    config_path = home_path / "config.toml"
    home_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot = ConfigSnapshot.capture(config_path)
    try:
        raw = snapshot.data.decode("utf-8")
        if raw:
            tomllib.loads(raw)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RecoveryError(
            "config.toml is not valid UTF-8 TOML", stable_code="config_invalid"
        ) from exc
    patched = _patch_text(raw, workspace_path).encode("utf-8")
    if patched == snapshot.data:
        snapshot.assert_current()
        return None

    backup = _create_backup(snapshot)
    snapshot.assert_current()
    temporary_path: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{config_path.name}.recovery-",
            suffix=".tmp",
            dir=config_path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            if snapshot.identity is not None:
                try:
                    shutil.copystat(config_path, temporary_path, follow_symlinks=False)
                except OSError as exc:
                    raise RecoveryError(
                        "config permissions, ACLs, or extended metadata could not be preserved",
                        stable_code="config_metadata_preservation_failed",
                    ) from exc
                _copy_macos_config_metadata(snapshot, fd)
            os.fchmod(fd, snapshot.mode if snapshot.identity is not None else 0o600)
            _write_all(fd, patched)
            os.fsync(fd)
        finally:
            os.close(fd)
        snapshot.assert_current()
        if snapshot.identity is None:
            native_move_no_replace(temporary_path, config_path)
            temporary_path = None
        else:
            # This is an atomic file-content publication, not a profile/data
            # relocation. The destination identity and temporary digest were
            # checked immediately before publication under the profile lock.
            _replace_existing_config(temporary_path, config_path)
            temporary_path = None
        _fsync_directory(config_path.parent)
    finally:
        if temporary_path is not None:
            with contextlib.suppress(OSError):
                temporary_path.unlink()
    return backup


__all__ = [
    "ConfigSnapshot",
    "STATE_OVERRIDE_ENV_VARS",
    "WORKSPACE_OVERRIDE_ENV_VARS",
    "patch_workspace_dir",
    "state_override",
    "workspace_override",
]
