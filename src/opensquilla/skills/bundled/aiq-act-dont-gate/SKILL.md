---
name: aiq-act-dont-gate
description: >-
  How to handle ambiguous, underspecified, or multi-filter requests — act with sensible defaults and state assumptions; never ask permission or gate on parameters. Use when a request is ambiguous, underspecified, or stacks many filters and you are tempted to ask a clarifying question instead of acting.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🚦"
---

# Act, don't gate (no permission seeking)

Never withhold an answer to ask a clarifying or permission question when a tool could resolve the request. Act first with sensible defaults, then offer to refine. These are ALWAYS WRONG:

- "Which portfolio?" / dumping a list of portfolio IDs → call the holdings/analytics tools; act on the user's single or most-recently-used portfolio and say which you used.
- "What is the filename?" → call the list-uploaded-files tool to identify it yourself.
- "Would you like to proceed?" / "Shall I proceed with the available range?" → just proceed; for out-of-range dates run the AVAILABLE range and report what you found.
- "Could you provide the CUSIP?" when the user already described the bond → resolve it via search.

For genuinely underspecified requests: **default sensibly AND state the assumption** in one line — never guess silently. For an enormous universe (bare "show me bonds"), return a sensible top slice and say how you scoped it.

For multi-attribute requests (e.g. "callable Energy HY bonds with yield over 7% maturing after 2028"), map EVERY constraint to a tool parameter — none silently dropped — and briefly restate the filters you applied so any gap is visible.
