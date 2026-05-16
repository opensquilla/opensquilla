"""Lockfile management for installed skills."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from opensquilla.paths import default_opensquilla_home


@dataclass
class LockEntry:
    """A single installed skill entry in the lockfile."""

    source: str
    identifier: str
    version: str = ""
    installed_at: str = ""
    path: str = ""
    sha256: str = ""
    license: str = ""
    upstream_url: str = ""
    source_trust: str = ""
    scan_verdict: str = ""
    scan_strategy: str = ""
    scan_findings: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class Lockfile:
    """Manages .opensquilla/skills-lock.json."""

    version: int = 1
    installed: dict[str, LockEntry] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> Lockfile:
        if not path.exists():
            return Lockfile()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lf = Lockfile(version=data.get("version", 1))
            known_fields = {
                "source",
                "identifier",
                "version",
                "installed_at",
                "path",
                "sha256",
                "license",
                "upstream_url",
                "source_trust",
                "scan_verdict",
                "scan_strategy",
                "scan_findings",
            }
            for name, entry_data in data.get("installed", {}).items():
                filtered = {k: v for k, v in entry_data.items() if k in known_fields}
                lf.installed[name] = LockEntry(**filtered)
            return lf
        except (json.JSONDecodeError, TypeError, OSError):
            return Lockfile()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self.version,
            "installed": {name: asdict(entry) for name, entry in self.installed.items()},
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add(self, name: str, entry: LockEntry) -> None:
        self.installed[name] = entry

    def remove(self, name: str) -> bool:
        if name in self.installed:
            del self.installed[name]
            return True
        return False

    def get(self, name: str) -> LockEntry | None:
        return self.installed.get(name)


def default_skill_lockfile_path() -> Path:
    """Return the default Community skill lockfile path."""

    return default_opensquilla_home() / "skills-lock.json"


def installed_skill_names(lockfile_path: Path | None = None) -> set[str]:
    """Return skill names recorded in the Community install lockfile.

    The lockfile is the authoritative "installed via Community source" record.
    Bundled or workspace skills with colliding names should not be flagged as
    installed from a Community source. Missing or corrupt lockfiles return an
    empty set.
    """

    path = lockfile_path if lockfile_path is not None else default_skill_lockfile_path()
    return set(Lockfile.load(path).installed.keys())


def compute_sha256(directory: Path) -> str:
    """Compute SHA-256 digest of all non-dotfiles in a directory."""
    hasher = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not any(p.startswith(".") for p in path.relative_to(directory).parts):
            hasher.update(str(path.relative_to(directory)).encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()
