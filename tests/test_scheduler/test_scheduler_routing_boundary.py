from __future__ import annotations

from pathlib import Path


def test_gateway_routing_imports_stay_behind_scheduler_adapter() -> None:
    scheduler_routing = Path("src/opensquilla/scheduler/routing.py")
    routing_source = scheduler_routing.read_text(encoding="utf-8")

    assert "from opensquilla.runtime import routing as runtime_routing" in routing_source
    assert "opensquilla.gateway.routing" not in routing_source

    scheduler_root = scheduler_routing.parent
    offenders = []
    for path in scheduler_root.glob("*.py"):
        if path == scheduler_routing:
            continue
        if "opensquilla.gateway.routing" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))

    assert offenders == []
