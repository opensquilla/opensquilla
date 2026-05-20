"""Meta-skill creator library.

Importing this package registers `meta_skill_assemble` and
`meta_skill_fill_slots` as tools in the default ToolRegistry. The
orchestrator's `tool_invoker` picks them up automatically.
"""

# Side-effect: registers tools via @tool decorators in proposer.py
from opensquilla.skills.creator import proposer  # noqa: F401
from opensquilla.skills.creator.proposer import (  # noqa: F401
    meta_skill_assemble,
    meta_skill_fill_slots,
    simulate_meta_resolution,
)
