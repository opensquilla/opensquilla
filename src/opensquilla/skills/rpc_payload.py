"""RPC payload builders for skills surfaces."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from typing import Any

from opensquilla.skills.runtime_facade import (
    skill_get_payload,
    skill_status_detail,
    skill_status_from_report,
    skill_to_rpc_payload,
    skills_list_payload,
    skills_status_payload,
)


def skills_status_rpc_payload(loader: Any | None) -> list[dict[str, Any]]:
    """Build the RPC wire payload for ``skills.status``."""

    return skills_status_payload(loader)


def skills_list_rpc_payload(loader: Any | None) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.list``."""

    return skills_list_payload(loader)


def skills_bins_rpc_payload(loader: Any | None) -> dict[str, bool]:
    """Build the RPC wire payload for ``skills.bins``."""

    if loader is None:
        return {}

    bins_status: dict[str, bool] = {}
    for skill in loader.load_all():
        meta = getattr(skill, "metadata", None)
        requires = getattr(meta, "requires", None) if meta is not None else None
        if requires is None:
            continue
        for bin_name in list(requires.bins) + list(requires.any_bins):
            if bin_name not in bins_status:
                bins_status[bin_name] = shutil.which(bin_name) is not None
    return bins_status


def skill_search_result_rpc_payload(result: Any, installed_names: set[str]) -> dict[str, Any]:
    """Build one Community skill search result row."""

    return {
        "name": result.name,
        "description": result.description,
        "version": result.version,
        "author": result.author,
        "source": result.source_id,
        "trust_level": result.trust_level,
        "identifier": result.identifier,
        "installed": result.identifier in installed_names or result.name in installed_names,
    }


def skills_search_rpc_payload(results: list[Any], installed_names: set[str]) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.search`` results."""

    return {
        "results": [
            skill_search_result_rpc_payload(result, installed_names) for result in results
        ]
    }


def skills_search_unavailable_rpc_payload() -> dict[str, Any]:
    """Build the empty ``skills.search`` payload when no sources are configured."""

    return {"results": [], "message": "No skill sources configured"}


def skill_install_unavailable_rpc_payload(message: str) -> dict[str, Any]:
    """Build the unavailable RPC wire payload for ``skills.install``."""

    return {"success": False, "message": message}


def skill_install_result_rpc_payload(result: Any) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.install`` results."""

    payload: dict[str, Any] = {
        "success": result.success,
        "name": result.name,
        "message": result.message,
    }
    if result.scan:
        payload["scan_verdict"] = result.scan.verdict
        payload["scan_findings"] = [finding.__dict__ for finding in result.scan.findings]
    return payload


def _skill_result_rpc_payload(result: Any) -> dict[str, Any]:
    return {
        "success": result.success,
        "name": result.name,
        "message": result.message,
    }


def skills_update_empty_results_rpc_payload(message: str) -> dict[str, Any]:
    """Build an empty results RPC wire payload for failed ``skills.update``."""

    return {"results": [], "success": False, "message": message}


def skills_update_unavailable_rpc_payload(message: str) -> dict[str, Any]:
    """Build the unavailable RPC wire payload for ``skills.update``."""

    return {"success": False, "message": message}


def skills_update_results_rpc_payload(results: list[Any]) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.update`` results."""

    return {"results": [_skill_result_rpc_payload(result) for result in results]}


def skill_uninstall_unavailable_rpc_payload(message: str) -> dict[str, Any]:
    """Build the unavailable RPC wire payload for ``skills.uninstall``."""

    return {"success": False, "message": message}


def skill_uninstall_result_rpc_payload(result: Any) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.uninstall`` results."""

    return _skill_result_rpc_payload(result)


def skill_deps_install_result_rpc_payload(
    result: Any,
    missing_still: Mapping[str, list[str]],
) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.deps.install`` results."""

    return {
        "success": result.success,
        "kind": result.kind,
        "message": result.message,
        "missing_still": dict(missing_still),
    }


def skill_get_rpc_payload(params: Mapping[str, Any] | None, loader: Any | None) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.get``."""

    return skill_get_payload(params, loader)


__all__ = [
    "skill_deps_install_result_rpc_payload",
    "skill_get_rpc_payload",
    "skill_install_result_rpc_payload",
    "skill_install_unavailable_rpc_payload",
    "skill_uninstall_result_rpc_payload",
    "skill_uninstall_unavailable_rpc_payload",
    "skill_search_result_rpc_payload",
    "skill_status_detail",
    "skill_status_from_report",
    "skill_to_rpc_payload",
    "skills_bins_rpc_payload",
    "skills_list_rpc_payload",
    "skills_search_rpc_payload",
    "skills_search_unavailable_rpc_payload",
    "skills_status_rpc_payload",
    "skills_update_empty_results_rpc_payload",
    "skills_update_results_rpc_payload",
    "skills_update_unavailable_rpc_payload",
]
