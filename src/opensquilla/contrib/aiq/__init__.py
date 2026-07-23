"""AIQ market-data agent bridge (contrib).

Bridges the AIQ fixed-income agent surface — FINRA TRACE prints, securities
screening, MarketAxess CP+, portfolio construction/CRUD, bond math, and the
long-tail ``search_tools``/``call_tool`` registry pair — into native
OpenSquilla tools, plus an ``aiq`` agent persona ported from AIQ's
TraceAgent.

Importing this package registers the bridged tools into the default tool
registry (the same import-side-effect convention as
``opensquilla.tools.builtin``). The tools are hidden by default
(``exposed_by_default=False``) and surfaced through the ``aiq`` agent's tool
allowlist. AIQ implementations are imported lazily at tool-call time from the
configured repo path; without the repo or its credentials every tool degrades
to the standard failure envelope.

See ``docs/features/aiq-agent.md`` for configuration and usage.
"""

from __future__ import annotations

from opensquilla.contrib.aiq.agent import AIQ_AGENT_ID
from opensquilla.contrib.aiq.query_profiles import select_aiq_tool_surface
from opensquilla.contrib.aiq.tools import aiq_tool_names, register_aiq_tools
from opensquilla.engine.tool_surface import register_tool_surface_selector

register_aiq_tools()
register_tool_surface_selector(AIQ_AGENT_ID, select_aiq_tool_surface)

__all__ = ["aiq_tool_names", "register_aiq_tools"]
