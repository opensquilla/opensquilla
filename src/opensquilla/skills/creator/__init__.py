"""Meta-skill creator library — Pydantic slot schemas + 3 internal tools.

Tools (registered at import time): meta_skill_fill_slots,
meta_skill_assemble, simulate_meta_resolution.
"""

from opensquilla.skills.creator.proposer import (  # noqa: F401
    meta_skill_assemble,
    meta_skill_fill_slots,
    simulate_meta_resolution,
)
