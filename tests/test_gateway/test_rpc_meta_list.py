"""Tests for the read-only ``meta.list`` RPC handler."""

from __future__ import annotations

import asyncio

from opensquilla.gateway.rpc.registry import RpcContext
from opensquilla.gateway.rpc_meta_runs import _handle_meta_list
from opensquilla.skills.types import SkillLayer, SkillSpec


def _make_spec(
    name: str,
    *,
    kind: str = "skill",
    description: str = "",
    disable_model_invocation: bool = False,
) -> SkillSpec:
    return SkillSpec(
        name=name,
        description=description,
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="",
        kind=kind,
        disable_model_invocation=disable_model_invocation,
    )


class _StubLoader:
    """Minimal skill loader exposing ``load_all`` like the real loader."""

    def __init__(self, specs: list[SkillSpec]) -> None:
        self._specs = specs

    def load_all(self) -> list[SkillSpec]:
        return list(self._specs)


def test_meta_list_returns_only_invokable_meta_skills() -> None:
    loader = _StubLoader(
        [
            _make_spec("beta-meta", kind="meta", description="Beta meta-skill"),
            _make_spec("alpha-meta", kind="meta", description="Alpha meta-skill"),
            _make_spec("plain-skill", kind="skill", description="Not a meta-skill"),
            _make_spec(
                "hidden-meta",
                kind="meta",
                description="Disabled meta-skill",
                disable_model_invocation=True,
            ),
        ]
    )
    ctx = RpcContext(conn_id="test", skill_loader=loader)

    payload = asyncio.run(_handle_meta_list(None, ctx))

    assert "disabled" not in payload
    assert payload["skills"] == [
        {"name": "alpha-meta", "description": "Alpha meta-skill"},
        {"name": "beta-meta", "description": "Beta meta-skill"},
    ]


def test_meta_list_disabled_when_master_gate_off() -> None:
    loader = _StubLoader(
        [_make_spec("alpha-meta", kind="meta", description="Alpha meta-skill")]
    )
    ctx = RpcContext(
        conn_id="test",
        skill_loader=loader,
        config={"meta_skill": {"enabled": False}},
    )

    payload = asyncio.run(_handle_meta_list(None, ctx))

    assert payload == {"skills": [], "disabled": True}
