"""Skills domain RPC handlers (Tier 3 stubs)."""

from __future__ import annotations

import asyncio
import shutil
import weakref
from pathlib import Path
from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.skills.eligibility import (
    EligibilityContext,
    EligibilityReport,
    diagnose_eligibility,
)
from opensquilla.skills.hub.defaults import (
    build_default_skill_installer,
    get_default_skill_router,
    installed_skill_names,
)
from opensquilla.skills.hub.deps import install_deps
from opensquilla.skills.loader import SkillLoader

_d = get_dispatcher()

# Per-(name, install_id) install serialization. WeakValueDictionary prevents
# unbounded growth: once all coroutines release a lock it gets GC'd.
_deps_locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _deps_lock_for(name: str, install_id: str) -> asyncio.Lock:
    key = (name, install_id)
    lock = _deps_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _deps_locks[key] = lock
    return lock


def _get_loader(ctx: RpcContext) -> SkillLoader | None:
    return getattr(ctx, "skill_loader", None)


def _loader_managed_dir(ctx: RpcContext) -> Path | None:
    loader = _get_loader(ctx)
    return getattr(loader, "managed_dir", None) if loader is not None else None


def _status_from_report(report: EligibilityReport) -> str:
    """Map an EligibilityReport to a tri-state status string.

    Wire contract: one of ``"ready" | "needs_setup" | "not_declared"``.
    """
    if not report.eligible:
        return "needs_setup"
    if report.declared:
        return "ready"
    return "not_declared"


def _status_detail(spec: Any, report: EligibilityReport) -> str:
    """Human-readable tooltip detail for the skill status dot/chip."""
    if not report.eligible:
        if report.disabled:
            return "Needs setup — disabled"
        if report.wrong_os:
            meta = getattr(spec, "metadata", None)
            os_list = list(meta.os) if meta and meta.os else []
            return f"Needs setup — wrong OS (requires: {', '.join(os_list)})"
        missing = list(report.missing_bins) + list(report.missing_env)
        if missing:
            return f"Needs setup — missing: {', '.join(missing)}"
        return "Needs setup"
    if not report.declared:
        return "Ready — no dependencies declared"
    meta = getattr(spec, "metadata", None)
    requires = meta.requires if meta is not None else None
    if requires is None:
        total = 0
    else:
        total = len(requires.bins) + (1 if requires.any_bins else 0) + len(requires.env)
    return f"Ready — {total}/{total} dependencies satisfied"


def _skill_to_dict(spec: Any, report: EligibilityReport, os_name: str = "") -> dict[str, Any]:
    """Convert a SkillSpec to a dict with eligibility diagnostics.

    Install options are filtered against ``os_name`` before serialization.
    An install entry is kept when its ``os`` list is empty (treated as
    "any OS") or contains the current ``os_name``. This applies the two-layer
    OS filter (skill-level ``metadata.os`` + per-install ``os``), and keeps the
    wire payload narrow (no ``os`` field per entry).
    Passing an empty ``os_name`` disables per-entry filtering (backward compat).
    """
    meta = getattr(spec, "metadata", None)
    install_entries: list[dict[str, Any]] = []
    if meta is not None:
        for ispec in meta.install:
            spec_os = list(getattr(ispec, "os", []) or [])
            if spec_os and os_name and os_name not in spec_os:
                continue
            install_entries.append(
                {
                    "id": ispec.id,
                    "kind": ispec.kind,
                    "label": ispec.label,
                    "bins": list(ispec.bins),
                }
            )

    # Meta-skill metadata: expose kind + the list of sub-skills referenced
    # by the composition DAG so the WebUI can group meta-skills separately
    # and surface "uses: X, Y, Z" badges without a second round-trip.
    kind = getattr(spec, "kind", "skill") or "skill"
    sub_skills: list[str] = []
    composition_raw = getattr(spec, "composition_raw", None)
    if isinstance(composition_raw, dict):
        steps_raw = composition_raw.get("steps")
        if isinstance(steps_raw, list):
            seen: set[str] = set()
            for step in steps_raw:
                if not isinstance(step, dict):
                    continue
                sub = step.get("skill")
                if isinstance(sub, str) and sub and sub not in seen:
                    seen.add(sub)
                    sub_skills.append(sub)
                # routes (kind=llm_classify) may also reference sub-skills
                routes = step.get("routes")
                if isinstance(routes, list):
                    for route in routes:
                        if isinstance(route, dict):
                            rsub = route.get("skill")
                            if isinstance(rsub, str) and rsub and rsub not in seen:
                                seen.add(rsub)
                                sub_skills.append(rsub)

    d: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "layer": str(spec.layer),
        "always": spec.always,
        "triggers": spec.triggers,
        "eligible": report.eligible,
        "emoji": meta.emoji if meta else "",
        "primary_env": meta.primary_env if meta else "",
        "homepage": meta.homepage if meta else getattr(spec, "homepage", ""),
        "file_path": getattr(spec, "file_path", ""),
        "os": list(meta.os) if meta else [],
        "disabled": report.disabled,
        "install": install_entries,
        "kind": kind,
        "sub_skills": sub_skills,
    }
    provenance = getattr(spec, "provenance", None)
    d["provenance"] = {
        "origin": provenance.origin if provenance else "unknown",
        "license": provenance.license if provenance else "unknown",
        "upstream_url": provenance.upstream_url if provenance else "",
        "maintained_by": provenance.maintained_by if provenance else "OpenSquilla",
    }
    d["declared"] = report.declared
    d["status"] = _status_from_report(report)
    d["status_detail"] = _status_detail(spec, report)
    if not report.eligible:
        d["reasons"] = report.reasons
        d["missing_bins"] = report.missing_bins
        d["missing_env"] = report.missing_env
    return d


@_d.method("skills.status", scope="operator.read")
async def _handle_skills_status(params: dict | None, ctx: RpcContext) -> list[dict[str, Any]]:
    """Return all skills with their eligibility status."""
    loader = _get_loader(ctx)
    if loader is None:
        return []

    ctx_eligible = EligibilityContext.auto()
    skills = loader.load_all()
    return [
        _skill_to_dict(skill, diagnose_eligibility(skill, ctx_eligible), ctx_eligible.os_name)
        for skill in skills
    ]


@_d.method("skills.list", scope="operator.read")
async def _handle_skills_list(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """List installed skills."""
    loader = _get_loader(ctx)
    if loader is None:
        return {"skills": []}

    ctx_eligible = EligibilityContext.auto()
    skills = loader.get_user_invocable()
    return {
        "skills": [
            _skill_to_dict(skill, diagnose_eligibility(skill, ctx_eligible), ctx_eligible.os_name)
            for skill in skills
        ]
    }


@_d.method("skills.bins", scope="node")
async def _handle_skills_bins(params: dict | None, ctx: RpcContext) -> dict[str, bool]:
    """Return the availability status of required bins across all skills."""
    loader = _get_loader(ctx)
    if loader is None:
        return {}

    bins_status: dict[str, bool] = {}
    skills = loader.load_all()

    for skill in skills:
        if skill.metadata and skill.metadata.requires:
            for bin_name in skill.metadata.requires.bins:
                if bin_name not in bins_status:
                    bins_status[bin_name] = shutil.which(bin_name) is not None
            for bin_name in skill.metadata.requires.any_bins:
                if bin_name not in bins_status:
                    bins_status[bin_name] = shutil.which(bin_name) is not None

    return bins_status


@_d.method("skills.get", scope="operator.read")
async def _handle_skills_get(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Get a single skill by name, including its full content."""
    if not isinstance(params, dict) or "name" not in params:
        raise ValueError("params.name is required")

    loader = _get_loader(ctx)
    if loader is None:
        raise KeyError("No skill loader available")

    skill = loader.get_by_name(params["name"])
    if skill is None:
        raise KeyError(f"Skill not found: {params['name']}")

    ctx_eligible = EligibilityContext.auto()
    result = _skill_to_dict(skill, diagnose_eligibility(skill, ctx_eligible), ctx_eligible.os_name)
    result["content"] = skill.content
    result["file_path"] = skill.file_path
    result["base_dir"] = skill.base_dir
    return result


def _installed_names() -> set[str]:
    """Return the set of skill names currently recorded in the lockfile.

    Lockfile is the authoritative "installed via Community source" record —
    bundled or workspace skills with colliding names won't be mis-flagged
    as installed-from-ClawHub. Missing/corrupt lockfile returns an empty
    set (treat everything as not-yet-installed).
    """
    return installed_skill_names()


@_d.method("skills.search", scope="operator.read")
async def _handle_skills_search(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Search for skills across Community sources."""
    if not isinstance(params, dict) or "query" not in params:
        raise ValueError("params.query is required")

    router = getattr(ctx, "_skill_router", None)
    if router is None:
        router = _get_default_router()
    if router is None:
        return {"results": [], "message": "No skill sources configured"}

    query = params["query"]
    try:
        limit = min(int(params.get("limit", 20)), 100)
    except (TypeError, ValueError):
        limit = 20
    source_id = params.get("source")
    if source_id is not None and not isinstance(source_id, str):
        source_id = None
    results = await router.search(query, limit=limit, source_id=source_id)
    installed = _installed_names()
    # Lockfile keys are the installer's name — which for ClawHub is the
    # slug (``identifier``), not the human-readable ``displayName`` a
    # source may return as ``SkillMeta.name``. Check both so we catch
    # either convention; a future source that matches on name directly
    # still works.
    return {
        "results": [
            {
                "name": r.name,
                "description": r.description,
                "version": r.version,
                "author": r.author,
                "source": r.source_id,
                "trust_level": r.trust_level,
                "identifier": r.identifier,
                "installed": r.identifier in installed or r.name in installed,
            }
            for r in results
        ]
    }


def _invalidate_loader(ctx: RpcContext) -> None:
    """Drop the loader's in-memory cache so the next read re-scans disk.

    The disk snapshot has its own mtime/size manifest check, but the
    in-memory ``_cached`` field is populated at boot and would otherwise
    mask newly-installed (or removed) managed skills until the next
    restart.
    """
    loader = _get_loader(ctx)
    if loader is not None:
        loader.invalidate_cache()


@_d.method("skills.install", scope="operator.admin")
async def _handle_skills_install(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Install a skill from a Community source."""
    if not isinstance(params, dict) or "identifier" not in params:
        raise ValueError("params.identifier is required")
    loader = _get_loader(ctx)
    if loader is None:
        return {"success": False, "message": "No skill loader configured"}

    installer = _get_default_installer(managed_dir=loader.managed_dir)
    if installer is None:
        return {"success": False, "message": "No skill installer configured"}

    identifier = params["identifier"]
    source_id = params.get("source", "clawhub")
    force = params.get("force", False)
    result = await installer.install(identifier, source_id, force=force)
    if result.success:
        _invalidate_loader(ctx)
    resp: dict[str, Any] = {
        "success": result.success,
        "name": result.name,
        "message": result.message,
    }
    if result.path:
        resp["path"] = result.path
    if result.scan:
        resp["scan_verdict"] = result.scan.verdict
        resp["scan_findings"] = [finding.__dict__ for finding in result.scan.findings]
    return resp


@_d.method("skills.update", scope="operator.admin")
async def _handle_skills_update(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Update installed skills from lockfile."""
    loader = _get_loader(ctx)
    if loader is None:
        return {
            "results": [],
            "success": False,
            "message": "No skill loader configured",
        }
    installer = _get_default_installer(managed_dir=loader.managed_dir)
    if installer is None:
        return {"success": False, "message": "No skill installer configured"}

    name = (params or {}).get("name")
    try:
        results = await installer.update(name)
    except OSError as exc:
        return {
            "results": [],
            "success": False,
            "message": f"Skill update unavailable: {exc}",
        }
    if any(r.success for r in results):
        _invalidate_loader(ctx)
    return {
        "results": [{"success": r.success, "name": r.name, "message": r.message} for r in results]
    }


@_d.method("skills.uninstall", scope="operator.admin")
async def _handle_skills_uninstall(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Uninstall a managed skill."""
    if not isinstance(params, dict) or "name" not in params:
        raise ValueError("params.name is required")

    installer = _get_default_installer(managed_dir=_loader_managed_dir(ctx))
    if installer is None:
        return {"success": False, "message": "No skill installer configured"}

    result = await installer.uninstall(params["name"])
    if result.success:
        _invalidate_loader(ctx)
    return {"success": result.success, "name": result.name, "message": result.message}


@_d.method("skills.deps.install", scope="operator.admin")
async def _handle_skills_deps_install(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Install runtime dependencies for an already-loaded skill.

    Looks up the skill by name, finds the matching SkillInstallSpec by id in
    `metadata.install`, runs it via `install_deps`, then re-runs
    `diagnose_eligibility` and returns `missing_still` reflecting post-install state.

    Note: `kind == "download"` is non-idempotent — re-running re-downloads.
    Callers should consult `missing_still` before retrying.
    """
    if not isinstance(params, dict):
        raise ValueError("params must be a dict")
    if "name" not in params:
        raise ValueError("params.name is required")
    if "install_id" not in params:
        raise ValueError("params.install_id is required")

    name = params["name"]
    install_id = params["install_id"]
    loader = _get_loader(ctx)
    if loader is None:
        raise KeyError("No skill loader available")
    skill = loader.get_by_name(name)
    if skill is None:
        raise KeyError(f"Skill not found: {name}")

    specs = skill.metadata.install if skill.metadata else []
    spec = next((s for s in specs if s.id == install_id), None)
    if spec is None:
        raise KeyError(f"Install spec not found: {install_id}")

    ctx_eligible = EligibilityContext.auto()
    if spec.os and ctx_eligible.os_name and ctx_eligible.os_name not in spec.os:
        raise ValueError(
            f"Install spec {install_id!r} not supported on "
            f"{ctx_eligible.os_name} (requires: {', '.join(spec.os)})"
        )

    async with _deps_lock_for(name, install_id):
        results = await install_deps([spec])
        r = results[0]
        report = diagnose_eligibility(skill, ctx_eligible)

    return {
        "success": r.success,
        "kind": r.kind,
        "message": r.message,
        "missing_still": {
            "bins": list(report.missing_bins),
            "env": list(report.missing_env),
        },
    }


# ---------------------------------------------------------------------------
# Default router/installer (lazy init)
# ---------------------------------------------------------------------------

def _get_default_router():
    return get_default_skill_router()


def _get_default_installer(*, managed_dir=None):
    return build_default_skill_installer(managed_dir=managed_dir)
