"""Strict, composable configuration for reproducible DRACO experiments."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class DracoReferenceConfig(_StrictConfig):
    repository: str = Field(min_length=1)
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    run_directory: str = Field(min_length=1)
    group: str = Field(min_length=1)
    profile: str = Field(min_length=1)


class DracoBenchmarkInputConfig(_StrictConfig):
    name: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_count: int = Field(gt=0)
    task_ids: list[str] = Field(min_length=1)
    enforce_reference_input: bool = True

    @model_validator(mode="after")
    def _validate_tasks(self) -> DracoBenchmarkInputConfig:
        if len(self.task_ids) != self.task_count:
            raise ValueError("benchmark_input.task_ids must match task_count")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("benchmark_input.task_ids must be unique")
        return self


class DracoRoutingConfig(_StrictConfig):
    selection_mode: Literal["static_openrouter_b5"]
    skip_single_model_router: bool


ThinkingSetting = Literal[
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "adaptive",
]


class DracoEnsembleMemberConfig(_StrictConfig):
    label: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key_env: str = ""
    base_url: str = ""
    temperature: float | None
    max_tokens: int = Field(gt=0)
    thinking: ThinkingSetting
    k: int = Field(default=1, ge=1)


class DracoEnsembleConfig(_StrictConfig):
    profile_name: str = Field(min_length=1)
    proposers: list[DracoEnsembleMemberConfig] = Field(min_length=1)
    aggregator: DracoEnsembleMemberConfig
    min_successful_proposers: int = Field(ge=1)
    all_failed_policy: Literal["fallback_single", "error"]
    candidate_max_chars: int = Field(ge=0)
    shuffle_candidates: bool
    record_candidates: bool
    proposer_tools: bool
    aggregator_tools: bool
    wait_for_all_proposers: bool
    quorum_grace_seconds: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _validate_wait_policy(self) -> DracoEnsembleConfig:
        if self.aggregator.k != 1:
            raise ValueError("ensemble.aggregator.k must be 1; aggregation runs once")
        if self.min_successful_proposers > sum(member.k for member in self.proposers):
            raise ValueError("ensemble.min_successful_proposers exceeds proposer sample count")
        if self.wait_for_all_proposers and self.quorum_grace_seconds != 0:
            raise ValueError(
                "ensemble.quorum_grace_seconds must be 0 when wait_for_all_proposers=true"
            )
        if not self.wait_for_all_proposers and self.quorum_grace_seconds <= 0:
            raise ValueError(
                "ensemble.quorum_grace_seconds must be positive when wait_for_all_proposers=false"
            )
        return self


class DracoTimeoutConfig(_StrictConfig):
    task_seconds: float = Field(gt=0.0)
    proposer_seconds: float = Field(gt=0.0)
    aggregator_seconds: float = Field(gt=0.0)
    task_margin_seconds: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _validate_budget(self) -> DracoTimeoutConfig:
        sequential_budget = (
            self.proposer_seconds + self.aggregator_seconds + self.task_margin_seconds
        )
        if sequential_budget > self.task_seconds + 1e-9:
            raise ValueError("timeouts proposer + aggregator + margin must not exceed task_seconds")
        return self


class DracoRunnerConfig(_StrictConfig):
    mode: Literal["agent_loop", "provider"]
    agent_max_iterations: int = Field(ge=0)
    concurrency: int = Field(ge=1)


class DracoGenerationConfig(_StrictConfig):
    thinking_enabled: bool
    thinking_budget_tokens: int = Field(gt=0)
    default_thinking_level: ThinkingSetting
    model_thinking_levels: dict[str, ThinkingSetting]
    require_highest_thinking: bool
    temperature: float | None
    max_tokens: int = Field(gt=0)
    max_attempts: int = Field(ge=1, le=3)
    retry_backoff_seconds: float = Field(ge=0.0)


class DracoWebSearchConfig(_StrictConfig):
    provider: Literal["brave", "duckduckgo"]
    api_key_env: str
    max_results: int = Field(gt=0)


class DracoWebFetchConfig(_StrictConfig):
    max_content_tokens: int = Field(gt=0)


class DracoToolsConfig(_StrictConfig):
    mode: Literal["local_web_tools", "provider_only", "openrouter_server_tools"]
    contamination_blocked_domains: list[str]
    web_search: DracoWebSearchConfig
    web_fetch: DracoWebFetchConfig


class DracoJudgeConfig(_StrictConfig):
    model: str = Field(min_length=1)
    repeats: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    max_attempts: int = Field(ge=1, le=3)
    judge_candidates: bool


class DracoExperimentConfig(_StrictConfig):
    schema_version: Literal[1]
    profile_id: str = Field(min_length=1)
    group: Literal["B2"]
    reference: DracoReferenceConfig
    benchmark_input: DracoBenchmarkInputConfig
    routing: DracoRoutingConfig
    ensemble: DracoEnsembleConfig
    timeouts: DracoTimeoutConfig
    runner: DracoRunnerConfig
    generation: DracoGenerationConfig
    tools: DracoToolsConfig
    judge: DracoJudgeConfig

    @model_validator(mode="after")
    def _validate_thinking_policy(self) -> DracoExperimentConfig:
        if not self.generation.require_highest_thinking:
            return self
        for member in (*self.ensemble.proposers, self.ensemble.aggregator):
            expected = self.generation.model_thinking_levels.get(member.model)
            if expected is None:
                raise ValueError(
                    f"generation.model_thinking_levels has no highest setting for {member.model!r}"
                )
            if member.thinking != expected:
                raise ValueError(
                    f"ensemble member {member.model!r} uses {member.thinking!r}; "
                    f"highest configured setting is {expected!r}"
                )
        return self


@dataclass(frozen=True)
class DracoExperimentConfigBundle:
    config: DracoExperimentConfig
    base_path: Path
    base_document: dict[str, Any]
    override_documents: tuple[tuple[Path, dict[str, Any]], ...]
    inline_overrides: tuple[dict[str, Any], ...]
    merged_document: dict[str, Any]

    def provenance(self) -> dict[str, Any]:
        return {
            "precedence": [
                "base_json",
                "override_json_in_cli_order",
                "inline_path_overrides_in_cli_order",
            ],
            "base": _path_provenance(self.base_path),
            "overrides": [_path_provenance(path) for path, _ in self.override_documents],
            "inline_overrides": list(self.inline_overrides),
        }


def _path_provenance(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    return {
        "path": str(resolved),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def load_json_object(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"experiment config does not exist: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid experiment config JSON {resolved}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"experiment config must contain a JSON object: {resolved}")
    return value


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _inline_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _apply_path_override(document: dict[str, Any], path: str, value: Any) -> None:
    parts = [part.strip() for part in path.split(".")]
    if not parts or any(not part for part in parts):
        raise ValueError(f"invalid experiment config override path: {path!r}")
    current: Any = document
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise ValueError(f"invalid list index {part!r} in override path {path!r}") from exc
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ValueError(f"unknown experiment config override path: {path!r}")
    leaf = parts[-1]
    if isinstance(current, list):
        try:
            current[int(leaf)] = value
        except (ValueError, IndexError) as exc:
            raise ValueError(f"invalid list index {leaf!r} in override path {path!r}") from exc
    elif isinstance(current, dict) and leaf in current:
        current[leaf] = value
    else:
        raise ValueError(f"unknown experiment config override path: {path!r}")


def load_draco_experiment_config(
    base_path: Path,
    *,
    override_paths: list[Path] | None = None,
    inline_sets: list[str] | None = None,
) -> DracoExperimentConfigBundle:
    base_document = load_json_object(base_path)
    merged = copy.deepcopy(base_document)
    override_documents: list[tuple[Path, dict[str, Any]]] = []
    for override_path in override_paths or []:
        document = load_json_object(override_path)
        merged = _deep_merge(merged, document)
        override_documents.append((override_path.expanduser().resolve(), document))

    inline_overrides: list[dict[str, Any]] = []
    for raw in inline_sets or []:
        if "=" not in raw:
            raise ValueError("--experiment-config-set must use dotted.path=JSON_VALUE syntax")
        dotted_path, raw_value = raw.split("=", 1)
        value = _inline_value(raw_value)
        _apply_path_override(merged, dotted_path, value)
        inline_overrides.append({"path": dotted_path, "value": value})

    config = DracoExperimentConfig.model_validate(merged)
    return DracoExperimentConfigBundle(
        config=config,
        base_path=base_path.expanduser().resolve(),
        base_document=base_document,
        override_documents=tuple(override_documents),
        inline_overrides=tuple(inline_overrides),
        merged_document=merged,
    )


def validate_reference_input(
    path: Path,
    *,
    task_ids: list[str],
    config: DracoBenchmarkInputConfig,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    actual_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    actual_ids = [str(task_id) for task_id in task_ids]
    trace = {
        "name": config.name,
        "path": str(resolved),
        "enforced": config.enforce_reference_input,
        "expected_sha256": config.sha256,
        "actual_sha256": actual_sha256,
        "expected_task_count": config.task_count,
        "actual_task_count": len(actual_ids),
        "task_ids_match": actual_ids == config.task_ids,
    }
    if not config.enforce_reference_input:
        trace["status"] = "not_enforced"
        return trace
    mismatches: list[str] = []
    if actual_sha256 != config.sha256:
        mismatches.append("sha256")
    if len(actual_ids) != config.task_count:
        mismatches.append("task_count")
    if actual_ids != config.task_ids:
        mismatches.append("task_ids_or_order")
    if mismatches:
        raise ValueError(
            "DRACO input does not match the G12 reference dataset: " + ", ".join(mismatches)
        )
    trace["status"] = "matched"
    return trace
