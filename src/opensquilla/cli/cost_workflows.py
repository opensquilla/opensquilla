"""CLI workflows for usage/cost commands."""

from __future__ import annotations

from opensquilla.cli.cost_gateway_queries import load_usage_cost_from_gateway
from opensquilla.cli.cost_presenters import emit_usage_cost


def show_usage_cost_for_cli(*, by_model: bool, json_output: bool) -> None:
    """Load and emit aggregate usage/cost data for the CLI."""

    payload = load_usage_cost_from_gateway(json_output=json_output)
    emit_usage_cost(payload, by_model=by_model, json_output=json_output)
