"""CLI presenters for usage/cost output."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast

from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.cli.ui import console


def emit_usage_cost(
    payload: dict[str, Any],
    *,
    by_model: bool,
    json_output: bool,
) -> None:
    """Emit usage/cost rows."""

    rows = cast(list[dict[str, Any]], payload.get("breakdown", []))
    if by_model:
        _emit_usage_cost_by_model(rows, payload=payload, json_output=json_output)
        return

    if json_output:
        print_json(payload)
        return

    table = Table(title="Cost", show_header=True, header_style="bold cyan")
    table.add_column("Session")
    table.add_column("Model")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("session") or row.get("sessionKey") or ""),
            str(row.get("model") or ""),
            f"{int(row.get('input_tokens') or row.get('inputTokens') or 0):,}",
            f"{int(row.get('output_tokens') or row.get('outputTokens') or 0):,}",
            f"${float(row.get('cost_usd') or row.get('costUsd') or 0.0):.6f}",
        )
    console.print(table)
    console.print(f"[dim]total: ${float(payload.get('totalCostUsd') or 0.0):.6f}[/dim]")


def _emit_usage_cost_by_model(
    rows: list[dict[str, Any]],
    *,
    payload: dict[str, Any],
    json_output: bool,
) -> None:
    grouped: dict[str, dict[str, float]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cost": 0.0}
    )
    for row in rows:
        model = row.get("model") or "unknown"
        grouped[model]["input"] += int(row.get("input_tokens") or row.get("inputTokens") or 0)
        grouped[model]["output"] += int(row.get("output_tokens") or row.get("outputTokens") or 0)
        grouped[model]["cost"] += float(row.get("cost_usd") or row.get("costUsd") or 0.0)

    if json_output:
        print_json(
            {
                "byModel": [
                    {
                        "model": model,
                        "inputTokens": int(data["input"]),
                        "outputTokens": int(data["output"]),
                        "costUsd": data["cost"],
                    }
                    for model, data in sorted(grouped.items())
                ],
                "totalCostUsd": payload.get("totalCostUsd"),
            }
        )
        return

    table = Table(title="Cost by Model", show_header=True, header_style="bold cyan")
    table.add_column("Model")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right")
    for model, data in sorted(grouped.items()):
        table.add_row(
            model,
            f"{int(data['input']):,}",
            f"{int(data['output']):,}",
            f"${data['cost']:.6f}",
        )
    console.print(table)
