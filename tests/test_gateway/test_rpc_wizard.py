from __future__ import annotations

import ast
from pathlib import Path

import pytest

import opensquilla.gateway.rpc_wizard as rpc_wizard  # noqa: F401  ensures registration
from opensquilla.application.wizard import reset_wizard_registry
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.rpc import RpcContext, get_dispatcher


def _admin_ctx() -> RpcContext:
    return RpcContext(
        conn_id="t",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.admin"}),
            is_owner=True,
            authenticated=True,
        ),
    )


@pytest.fixture(autouse=True)
def _clean_wizard_registry() -> None:
    reset_wizard_registry()


@pytest.mark.asyncio
async def test_wizard_rpc_flow_uses_application_state_machine() -> None:
    dispatcher = get_dispatcher()
    ctx = _admin_ctx()

    started = await dispatcher.dispatch(
        "r1",
        "wizard.start",
        {"wizardType": "onboard_agent"},
        ctx,
    )
    assert started.error is None, started.error
    wizard_id = started.payload["wizardId"]
    assert started.payload["step"]["stepId"] == "agent_identity"

    advanced = await dispatcher.dispatch(
        "r2",
        "wizard.next",
        {"wizardId": wizard_id, "answers": {"agent_name": "cora"}},
        ctx,
    )
    assert advanced.error is None, advanced.error
    assert advanced.payload == {
        "step": {
            "stepId": "system_prompt",
            "title": "System Prompt & Persona",
            "description": "Define how the agent behaves.",
            "fields": [
                {
                    "name": "system_prompt",
                    "label": "System Prompt",
                    "fieldType": "text",
                    "required": True,
                    "choices": None,
                    "default": None,
                    "description": "Long-form instructions the LLM sees at the top of every turn.",
                },
                {
                    "name": "persona_tone",
                    "label": "Persona Tone",
                    "fieldType": "select",
                    "required": False,
                    "choices": ["professional", "casual", "friendly"],
                    "default": "professional",
                    "description": "Conversational register used when no tone override applies.",
                },
            ],
            "nextStepId": "defaults",
        },
        "completed": False,
        "result": None,
    }

    status = await dispatcher.dispatch("r3", "wizard.status", {"wizardId": wizard_id}, ctx)
    assert status.error is None, status.error
    assert status.payload["wizardId"] == wizard_id
    assert status.payload["wizardType"] == "onboard_agent"
    assert status.payload["currentStepId"] == "system_prompt"
    assert status.payload["totalSteps"] == 3
    assert status.payload["completed"] is False


@pytest.mark.asyncio
async def test_wizard_cancel_removes_session() -> None:
    dispatcher = get_dispatcher()
    ctx = _admin_ctx()
    started = await dispatcher.dispatch(
        "r1",
        "wizard.start",
        {"wizardType": "onboard_agent"},
        ctx,
    )
    wizard_id = started.payload["wizardId"]

    cancelled = await dispatcher.dispatch("r2", "wizard.cancel", {"wizardId": wizard_id}, ctx)

    assert cancelled.error is None, cancelled.error
    assert cancelled.payload == {"wizardId": wizard_id, "cancelled": True}
    status = await dispatcher.dispatch("r3", "wizard.status", {"wizardId": wizard_id}, ctx)
    assert status.error is not None


def test_gateway_rpc_wizard_depends_on_application_boundary() -> None:
    source = Path(rpc_wizard.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    helper_names = {
        "wizard_cancel_rpc_payload",
        "wizard_next_rpc_payload",
        "wizard_start_rpc_payload",
        "wizard_status_rpc_payload",
    }
    imported_helpers = {
        alias.name
        for node in imports
        if node.module == "opensquilla.application.wizard_rpc"
        for alias in node.names
    }
    handlers = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name
        in {
            "_handle_wizard_start",
            "_handle_wizard_next",
            "_handle_wizard_cancel",
            "_handle_wizard_status",
        }
    }
    handler_names = {
        node.id
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    handler_attributes = {
        node.attr
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
    }

    assert any(node.module == "opensquilla.application.wizard" for node in imports)
    assert all(node.module != "opensquilla.gateway.wizard" for node in imports)
    assert helper_names.issubset(imported_helpers)
    assert helper_names.issubset(handler_names)
    assert ("wizardId", "step") not in direct_key_sets
    assert ("step", "completed", "result") not in direct_key_sets
    assert ("wizardId", "cancelled") not in direct_key_sets
    assert "to_dict" not in handler_attributes
