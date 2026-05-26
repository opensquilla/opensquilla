"""Library functions for the ``~/.opensquilla/proposals/`` directory.

Lifted out of ``skills/bundled/skill-creator-proposals/scripts/proposals.py``
so the gateway RPC layer (Path 3) can call them in-process — the
bundled script's hyphenated path is not importable.

The bundled script now delegates here so there's one source of truth.

Path layout::

    ~/.opensquilla/proposals/<8-hex>/SKILL.md
    ~/.opensquilla/proposals/<8-hex>/gates.json
    ~/.opensquilla/skills/<name>/                # MANAGED layer after accept
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

PROPOSAL_ID_PATTERN = re.compile(r"[0-9a-f]{8}")
SKILL_NAME_PATTERN = re.compile(r"[\w\-]+")
RISK_LEVELS = frozenset({"low", "medium", "high"})


def proposals_dir(home: Path) -> Path:
    return home / "proposals"


def skills_dir(home: Path) -> Path:
    return home / "skills"


def is_valid_proposal_id(proposal_id: str | None) -> bool:
    if not proposal_id:
        return False
    return bool(PROPOSAL_ID_PATTERN.fullmatch(proposal_id))


def atomic_write_proposal(
    home: Path, skill_md: str, gates: dict,
) -> str:
    """Materialise a proposal directory atomically.

    Writes ``SKILL.md`` + ``gates.json`` under ``$home/.tmp/proposal-<id>``
    then renames into ``$home/proposals/<id>`` — readers never see a
    half-built dir. Returns the new 8-hex proposal_id.
    """
    proposals = proposals_dir(home)
    proposals.mkdir(parents=True, exist_ok=True)
    proposal_id = uuid.uuid4().hex[:8]

    tmp_parent = home / ".tmp"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = tmp_parent / f"proposal-{proposal_id}"
    tmp_dir.mkdir()
    (tmp_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (tmp_dir / "gates.json").write_text(
        json.dumps(gates, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    final_dir = proposals / proposal_id
    tmp_dir.rename(final_dir)
    return proposal_id


def write_proposal(
    home: Path,
    skill_md: str,
    lint_result: dict,
    smoke_result: dict,
) -> dict:
    """Atomic write + return the standard ``{status, proposal_id, ...}`` shape."""
    eligible = (
        lint_result.get("G1", {}).get("passed", False)
        and lint_result.get("G2", {}).get("passed", False)
        and smoke_result.get("G3", {}).get("passed", False)
        and smoke_result.get("G4", {}).get("passed", False)
    )
    gates = {
        "lint": lint_result,
        "smoke": smoke_result,
        "auto_enable_eligible": eligible,
    }
    proposal_id = atomic_write_proposal(home, skill_md, gates)
    return {
        "status": "ok",
        "proposal_id": proposal_id,
        "auto_enable_eligible": eligible,
    }


def auto_enable_audit_from_gates(gates: dict) -> dict[str, object]:
    """Return a compact, UI-ready auto-enable audit summary."""
    auto_enable = gates.get("auto_enable")
    if not isinstance(auto_enable, dict):
        return {}
    details = auto_enable.get("details")
    if not isinstance(details, dict):
        details = {}
    reason = auto_enable.get("reason") or details.get("reason") or ""
    skills = details.get("skills")
    tools = details.get("tools")
    reasons = details.get("reasons")
    return {
        "status": auto_enable.get("status", "unknown"),
        "reason": reason,
        "risk_level": auto_enable.get("risk_level", details.get("risk_level", "unknown")),
        "max_risk": auto_enable.get("max_risk", details.get("max_risk", "unknown")),
        "validation_profile": details.get("validation_profile", "unknown"),
        "skills": skills if isinstance(skills, list) else [],
        "tools": tools if isinstance(tools, list) else [],
        "reasons": reasons if isinstance(reasons, list) else [],
    }


def list_proposals(home: Path) -> dict:
    """Snapshot of pending proposals (id + eligibility + provenance digest)."""
    proposals = proposals_dir(home)
    if not proposals.is_dir():
        return {"proposals": []}
    rows: list[dict] = []
    for sub in sorted(proposals.iterdir()):
        if not (sub / "SKILL.md").is_file():
            continue
        gates_path = sub / "gates.json"
        gates: dict = {}
        if gates_path.is_file():
            try:
                gates = json.loads(gates_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                gates = {}
        provenance = gates.get("provenance") or {}
        auto_enable_digest = auto_enable_audit_from_gates(gates)
        rows.append({
            "proposal_id": sub.name,
            "auto_enable_eligible": bool(gates.get("auto_enable_eligible", False)),
            "triggered_by": provenance.get("triggered_by", "manual"),
            "chain_hash": provenance.get("chain_hash"),
            "auto_enable": auto_enable_digest,
        })
    return {"proposals": rows}


def pending_count(home: Path) -> dict:
    """Number of pending proposals — cheap badge backend for the WebUI."""
    proposals = proposals_dir(home)
    if not proposals.is_dir():
        return {"count": 0}
    count = 0
    for sub in proposals.iterdir():
        if sub.is_dir() and (sub / "SKILL.md").is_file():
            count += 1
    return {"count": count}


def show_proposal(home: Path, proposal_id: str) -> dict:
    """Full payload for one proposal: SKILL.md text + gates.json."""
    if not is_valid_proposal_id(proposal_id):
        return {"status": "error", "reason": "invalid proposal_id format"}
    sub = proposals_dir(home) / proposal_id
    skill_path = sub / "SKILL.md"
    gates_path = sub / "gates.json"
    if not skill_path.is_file():
        return {"status": "error", "reason": f"proposal {proposal_id} not found"}
    skill_md = skill_path.read_text(encoding="utf-8")
    gates: dict = {}
    if gates_path.is_file():
        try:
            gates = json.loads(gates_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            gates = {}
    return {
        "status": "ok",
        "proposal_id": proposal_id,
        "skill_md": skill_md,
        "gates": gates,
        "auto_enable_audit": auto_enable_audit_from_gates(gates),
    }


def accept_proposal(home: Path, proposal_id: str, force: bool = False) -> dict:
    """Promote a proposal to the MANAGED skills layer."""
    if not is_valid_proposal_id(proposal_id):
        return {
            "status": "error",
            "reason": (
                f"invalid proposal_id format (expected 8 hex chars): {proposal_id!r}"
            ),
        }
    src = proposals_dir(home) / proposal_id
    if not (src / "SKILL.md").is_file():
        return {"status": "error", "reason": f"proposal {proposal_id} not found"}
    gates: dict = {}
    if (src / "gates.json").is_file():
        try:
            gates = json.loads((src / "gates.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            gates = {}
    if not gates.get("auto_enable_eligible") and not force:
        return {
            "status": "refused",
            "reason": "gates not all passed; use --force to override",
            "gates": gates,
        }
    skill_md = (src / "SKILL.md").read_text(encoding="utf-8")
    # Accept both `name: foo` and `name: "foo"` (creator's tojson emits quoted).
    name_match = re.search(r'^name:\s*"?([\w\-]+)"?\s*$', skill_md, re.MULTILINE)
    if not name_match:
        return {"status": "error", "reason": "cannot parse skill name from SKILL.md"}
    name = name_match.group(1)

    dst = skills_dir(home) / name
    if dst.exists():
        return {"status": "refused", "reason": f"skill {name} already exists at {dst}"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"status": "ok", "skill_path": str(dst), "name": name}


def list_auto_enabled_skills(home: Path) -> dict:
    """Return managed skills that were promoted by auto-enable."""
    managed = skills_dir(home)
    if not managed.is_dir():
        return {"skills": []}
    rows: list[dict] = []
    for sub in sorted(managed.iterdir()):
        if not (sub / "SKILL.md").is_file():
            continue
        gates_path = sub / "gates.json"
        if not gates_path.is_file():
            continue
        try:
            gates = json.loads(gates_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        auto_enable = gates.get("auto_enable")
        if not isinstance(auto_enable, dict):
            continue
        if auto_enable.get("status") != "enabled":
            continue
        audit = auto_enable_audit_from_gates(gates)
        rows.append({
            "name": sub.name,
            "proposal_id": auto_enable.get("proposal_id"),
            "risk_level": auto_enable.get("risk_level", "unknown"),
            "max_risk": auto_enable.get("max_risk", "unknown"),
            "triggered_by": auto_enable.get("triggered_by", "unknown"),
            "enabled_at_ms": auto_enable.get("enabled_at_ms"),
            "validation_profile": audit.get("validation_profile", "unknown"),
            "skills": audit.get("skills", []),
            "tools": audit.get("tools", []),
            "reasons": audit.get("reasons", []),
        })
    return {"skills": rows}


def disable_auto_enabled_skill(home: Path, name: str) -> dict:
    """Move an auto-enabled managed skill back to proposals for review."""
    if not isinstance(name, str) or not SKILL_NAME_PATTERN.fullmatch(name):
        return {"status": "error", "reason": "invalid skill name"}
    src = skills_dir(home) / name
    if not (src / "SKILL.md").is_file():
        return {"status": "error", "reason": f"skill {name} not found"}
    gates_path = src / "gates.json"
    gates: dict = {}
    if gates_path.is_file():
        try:
            parsed = json.loads(gates_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                gates = parsed
        except (json.JSONDecodeError, OSError):
            gates = {}
    auto_enable = gates.get("auto_enable")
    if not isinstance(auto_enable, dict) or auto_enable.get("status") != "enabled":
        return {"status": "refused", "reason": f"skill {name} is not auto-enabled"}

    proposal_id = str(auto_enable.get("proposal_id") or uuid.uuid4().hex[:8])
    if not is_valid_proposal_id(proposal_id) or (proposals_dir(home) / proposal_id).exists():
        proposal_id = uuid.uuid4().hex[:8]
    proposals_dir(home).mkdir(parents=True, exist_ok=True)
    dst = proposals_dir(home) / proposal_id

    disabled = dict(auto_enable)
    disabled["previous_status"] = auto_enable.get("status")
    disabled["status"] = "disabled"
    disabled["proposal_id"] = proposal_id
    gates["auto_enable"] = disabled
    gates_path.write_text(json.dumps(gates, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.move(str(src), str(dst))
    return {"status": "ok", "proposal_id": proposal_id, "name": name}


def reject_proposal(home: Path, proposal_id: str) -> dict:
    """Delete the proposal directory. Idempotent — re-deleting is fine."""
    if not is_valid_proposal_id(proposal_id):
        return {
            "status": "error",
            "reason": (
                f"invalid proposal_id format (expected 8 hex chars): {proposal_id!r}"
            ),
        }
    target = proposals_dir(home) / proposal_id
    if not target.is_dir():
        return {"status": "error", "reason": f"proposal {proposal_id} not found"}
    shutil.rmtree(target)
    return {"status": "ok", "proposal_id": proposal_id}


# ─── Auto-propose settings (Path 1/2 runtime toggle) ──────────────────

_AUTO_PROPOSE_BOOL_SETTINGS_KEYS = ("enabled", "on_dream_complete", "auto_enable")
_AUTO_PROPOSE_SETTINGS_KEYS = (*_AUTO_PROPOSE_BOOL_SETTINGS_KEYS, "auto_enable_max_risk")


def auto_propose_settings_path(home: Path) -> Path:
    """Path to the per-installation runtime overrides JSON."""
    return home / "state" / "auto_propose_settings.json"


def read_auto_propose_settings(home: Path) -> dict[str, object]:
    """Return the persisted runtime overrides, or {} when not present.

    The dict is keyed by ``enabled``, ``on_dream_complete``, and/or
    ``auto_enable``. Missing keys mean "no override" — the caller should fall
    back to the toml / pydantic-settings default.
    """
    path = auto_propose_settings_path(home)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, object] = {
        k: bool(v) for k, v in payload.items()
        if k in _AUTO_PROPOSE_BOOL_SETTINGS_KEYS and isinstance(v, bool)
    }
    risk = payload.get("auto_enable_max_risk")
    if isinstance(risk, str) and risk in RISK_LEVELS:
        out["auto_enable_max_risk"] = risk
    return out


def write_auto_propose_settings(home: Path, settings: dict[str, object]) -> None:
    """Persist the runtime overrides atomically. Unknown keys are dropped."""
    path = auto_propose_settings_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitised: dict[str, object] = {
        k: bool(settings.get(k))
        for k in _AUTO_PROPOSE_BOOL_SETTINGS_KEYS
        if k in settings
    }
    risk = settings.get("auto_enable_max_risk")
    if isinstance(risk, str) and risk in RISK_LEVELS:
        sanitised["auto_enable_max_risk"] = risk
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sanitised, indent=2), encoding="utf-8")
    tmp.replace(path)


__all__ = [
    "PROPOSAL_ID_PATTERN",
    "atomic_write_proposal",
    "accept_proposal",
    "auto_enable_audit_from_gates",
    "auto_propose_settings_path",
    "disable_auto_enabled_skill",
    "is_valid_proposal_id",
    "list_auto_enabled_skills",
    "list_proposals",
    "pending_count",
    "proposals_dir",
    "read_auto_propose_settings",
    "reject_proposal",
    "show_proposal",
    "skills_dir",
    "write_auto_propose_settings",
    "write_proposal",
]
