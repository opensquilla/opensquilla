"""Pattern registry for meta-skill-creator."""

from opensquilla.skills.creator.patterns.schemas import (
    FanOutMergeSlots,
    SequentialSlots,
)

PATTERN_SLOT_SCHEMA: dict[str, type] = {
    "p1_sequential": SequentialSlots,
    "p2_fan_out_merge": FanOutMergeSlots,
}
