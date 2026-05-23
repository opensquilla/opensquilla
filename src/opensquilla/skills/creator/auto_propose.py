"""Library function that drives meta-skill-creator unattended.

Used by:
  * the scheduler's ``auto_propose`` cron handler (Path 1)
  * the dream handler's post-completion hook (Path 2)

Behaviour: read the decision-log, aggregate top-K co-occurrence chains,
filter by frequency floor and existing-coverage, deduplicate against
already-pending proposals, then for each surviving pattern run the
meta-skill-creator DAG once and patch the resulting ``gates.json``
with provenance so the WebUI (Path 3) can distinguish auto-generated
proposals from user-invoked ones.

This function is intentionally **fault-tolerant**: it never raises,
because both callers (cron + dream) run in fire-and-forget contexts
where a single bad pattern must not kill the handler. All exceptions
are collected into ``AutoProposeResult.errors``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from opensquilla.observability.decision_log_aggregate import (
    aggregate_co_occurrences,
)
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch

_log = logging.getLogger(__name__)

# Whichever home the gateway uses for state — also where proposals/ lives.
_DEFAULT_PROPOSALS_DIRNAME = "proposals"

# meta-skill-creator's name in the bundled skill catalog. The DAG that
# auto_propose drives.
_META_SKILL_CREATOR = "meta-skill-creator"

# Trigger phrases of meta-skill-creator. The synthesised user_message
# must avoid ALL of these as substrings so the substring-match in
# engine/steps/meta_resolution.py cannot accidentally re-fire the
# meta-resolution pipeline against our generated text (would only matter
# if the synthesised message were ever fed back into a turn, but cheap
# insurance).
_META_SKILL_CREATOR_TRIGGERS: tuple[str, ...] = (
    "新增 meta 技能",
    "组合现有 skill 成 meta-skill",
    "synthesize meta-skill",
    "compose meta-skill",
)


@dataclass(frozen=True)
class _SkippedPattern:
    skills: list[str]
    freq: int
    reason: str


@dataclass(frozen=True)
class _PatternError:
    skills: list[str]
    freq: int
    error: str


@dataclass(frozen=True)
class AutoProposeResult:
    """Structured outcome — never the exception itself.

    ``proposals_created`` lists the 8-hex proposal_ids that landed
    under ``proposals_dir`` during this run. ``skipped`` and
    ``errors`` are diagnostic only — the caller logs them but does
    not act on them.
    """

    proposals_created: list[str] = field(default_factory=list)
    skipped: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    triggered_by: str = "cron"

    def summary(self) -> str:
        return (
            f"auto_propose proposals={len(self.proposals_created)} "
            f"skipped={len(self.skipped)} errors={len(self.errors)} "
            f"via={self.triggered_by}"
        )


def _chain_hash(skills: list[str]) -> str:
    """Stable identifier for a co-occurrence chain (order-insensitive)."""
    joined = "|".join(sorted(skills))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _existing_chain_hashes(proposals_dir: Path) -> set[str]:
    """Read every pending proposal's ``gates.json`` and collect chain hashes."""
    hashes: set[str] = set()
    if not proposals_dir.is_dir():
        return hashes
    for sub in proposals_dir.iterdir():
        if not sub.is_dir():
            continue
        gates_path = sub / "gates.json"
        if not gates_path.is_file():
            continue
        try:
            gates = json.loads(gates_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        prov = gates.get("provenance") or {}
        ch = prov.get("chain_hash")
        if isinstance(ch, str) and ch:
            hashes.add(ch)
    return hashes


def _meta_skill_coverage(skill_loader: SkillLoader) -> list[set[str]]:
    """Return one set per existing meta-skill — the skills it composes.

    Used to skip patterns whose every member is already covered by
    some existing meta-skill (no point synthesising a duplicate
    wrapper).
    """
    coverage: list[set[str]] = []
    for spec in skill_loader.list_meta_specs():
        composition = getattr(spec, "composition_raw", None) or {}
        steps = composition.get("steps") or []
        if not isinstance(steps, list):
            continue
        skills: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                continue
            name = step.get("skill")
            if isinstance(name, str) and name:
                skills.add(name)
        if skills:
            coverage.append(skills)
    return coverage


def _pattern_already_covered(skills: list[str], coverage: list[set[str]]) -> bool:
    pattern_set = set(skills)
    return any(pattern_set <= covered for covered in coverage)


def _synthesise_user_message(skills: list[str], freq: int, window_days: int) -> str:
    """Build a user_message string for the DAG that does NOT contain any
    meta-skill-creator trigger phrase (regression-tested)."""
    skill_list = ", ".join(skills)
    msg = (
        f"auto-proposal: candidate skill chain {{{skill_list}}} observed "
        f"{freq} times in last {window_days}d. Wrap as a new bundled "
        f"meta-skill."
    )
    # Loop-safety assertion — promoted to a hard check because the
    # consequence of regression is real recursion in the resolver.
    lower = msg.lower()
    for trig in _META_SKILL_CREATOR_TRIGGERS:
        assert trig.lower() not in lower, (
            f"synthesised user_message contains meta-skill-creator trigger "
            f"{trig!r}; auto_propose would recursively trigger itself"
        )
    return msg


def _patch_gates_provenance(
    proposal_dir: Path,
    *,
    triggered_by: str,
    skills: list[str],
    freq: int,
    window_days: int,
    chain_hash: str,
) -> None:
    """Add an additive ``provenance`` key to gates.json without touching
    the existing lint / smoke / auto_enable_eligible payload."""
    gates_path = proposal_dir / "gates.json"
    if not gates_path.is_file():
        return
    try:
        gates = json.loads(gates_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("auto_propose.gates_read_failed: %s", exc)
        return
    gates["provenance"] = {
        "triggered_by": f"auto_{triggered_by}",
        "chain_hash": chain_hash,
        "auto_propose_meta": {
            "skills": list(skills),
            "freq": freq,
            "window_days": window_days,
        },
    }
    try:
        gates_path.write_text(
            json.dumps(gates, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        _log.warning("auto_propose.gates_write_failed: %s", exc)


def _resolve_proposals_dir(proposals_dir: Path | None) -> Path:
    if proposals_dir is not None:
        return proposals_dir
    env_home = os.environ.get("OPENSQUILLA_STATE_DIR")
    home = Path(env_home).expanduser() if env_home else Path.home() / ".opensquilla"
    return home / _DEFAULT_PROPOSALS_DIRNAME


async def auto_propose(
    *,
    orchestrator: MetaOrchestrator,
    skill_loader: SkillLoader,
    log_dir: Path,
    window_days: int = 30,
    min_freq: int = 3,
    top_k: int = 5,
    triggered_by: str = "cron",
    proposals_dir: Path | None = None,
) -> AutoProposeResult:
    """Drive meta-skill-creator once per qualifying co-occurrence pattern.

    Args:
        orchestrator: pre-wired MetaOrchestrator. Fresh-per-fire; not
            reused across calls (orchestrator carries per-run state).
        skill_loader: the gateway's shared SkillLoader. Used to look up
            the meta-skill-creator plan + existing meta-skill coverage.
        log_dir: directory containing ``decisions-*.jsonl``. Usually
            ``~/.opensquilla/logs``.
        window_days: rolling window for co-occurrence aggregation.
        min_freq: drop patterns observed fewer than this many times.
        top_k: at most this many patterns are considered per call.
        triggered_by: ``"cron"`` or ``"dream"``. Recorded in provenance.
        proposals_dir: where the meta-skill-creator persist step writes
            proposals. Defaults to ``$OPENSQUILLA_STATE_DIR/proposals``
            or ``~/.opensquilla/proposals``.

    Returns:
        AutoProposeResult capturing proposals_created / skipped /
        errors. NEVER raises — every exception is collected.
    """
    proposals_dir = _resolve_proposals_dir(proposals_dir)
    proposals_created: list[str] = []
    skipped: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    creator_spec = skill_loader.get_by_name(_META_SKILL_CREATOR)
    if creator_spec is None:
        errors.append({
            "reason": "meta-skill-creator spec missing from loader",
        })
        return AutoProposeResult(
            proposals_created=proposals_created,
            skipped=skipped,
            errors=errors,
            triggered_by=triggered_by,
        )
    try:
        creator_plan = parse_meta_plan(creator_spec)
    except Exception as exc:  # noqa: BLE001 — fault-tolerant
        errors.append({
            "reason": f"meta-skill-creator plan parse failed: {exc}",
        })
        return AutoProposeResult(
            proposals_created=proposals_created,
            skipped=skipped,
            errors=errors,
            triggered_by=triggered_by,
        )
    if creator_plan is None:
        errors.append({"reason": "meta-skill-creator spec is not kind=meta"})
        return AutoProposeResult(
            proposals_created=proposals_created,
            skipped=skipped,
            errors=errors,
            triggered_by=triggered_by,
        )

    try:
        patterns = aggregate_co_occurrences(log_dir, window_days, top_k)
    except Exception as exc:  # noqa: BLE001
        errors.append({"reason": f"aggregate_co_occurrences failed: {exc}"})
        return AutoProposeResult(
            proposals_created=proposals_created,
            skipped=skipped,
            errors=errors,
            triggered_by=triggered_by,
        )

    coverage = _meta_skill_coverage(skill_loader)
    existing_hashes = _existing_chain_hashes(proposals_dir)

    for pattern in patterns:
        skills = list(pattern.get("skills") or [])
        freq = int(pattern.get("freq") or 0)
        if not skills:
            continue
        if freq < min_freq:
            skipped.append(asdict(_SkippedPattern(
                skills=skills, freq=freq, reason="below_min_freq",
            )))
            continue
        if _pattern_already_covered(skills, coverage):
            skipped.append(asdict(_SkippedPattern(
                skills=skills, freq=freq, reason="already_covered",
            )))
            continue
        chain_hash = _chain_hash(skills)
        if chain_hash in existing_hashes:
            skipped.append(asdict(_SkippedPattern(
                skills=skills, freq=freq, reason="duplicate_pending",
            )))
            continue

        msg = _synthesise_user_message(skills, freq, window_days)
        match = MetaMatch(
            plan=creator_plan,
            inputs={"user_message": msg},
        )
        before = {p.name for p in proposals_dir.iterdir()} if proposals_dir.is_dir() else set()
        try:
            await orchestrator.run(match)
        except asyncio.CancelledError:
            # propagate cancellation — don't bury it
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(asdict(_PatternError(
                skills=skills, freq=freq, error=str(exc),
            )))
            continue

        after = {p.name for p in proposals_dir.iterdir()} if proposals_dir.is_dir() else set()
        new_ids = sorted(after - before)
        if not new_ids:
            # DAG completed but no proposal landed — usually means
            # lint/smoke gates failed; that is normal and not an error.
            skipped.append(asdict(_SkippedPattern(
                skills=skills, freq=freq, reason="dag_produced_no_proposal",
            )))
            continue
        for proposal_id in new_ids:
            proposals_created.append(proposal_id)
            existing_hashes.add(chain_hash)
            _patch_gates_provenance(
                proposals_dir / proposal_id,
                triggered_by=triggered_by,
                skills=skills,
                freq=freq,
                window_days=window_days,
                chain_hash=chain_hash,
            )

    return AutoProposeResult(
        proposals_created=proposals_created,
        skipped=skipped,
        errors=errors,
        triggered_by=triggered_by,
    )


__all__ = ["auto_propose", "AutoProposeResult"]
