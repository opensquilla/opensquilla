---
name: aiq-rendering-tables
description: >-
  How to render tabular tool data correctly — emit pre-rendered markdown verbatim, include every requested column, never misalign cells. Use whenever presenting tabular tool output as a markdown table.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🧾"
---

# Rendering tables

1. **If a tool returns a `markdown` field, emit it VERBATIM** as the table. Do not re-type, re-order, or drop any column — it is already aligned.
2. When you render a table yourself from tool rows, keep strict value↔header alignment, exactly one row per tool row. A price must never land in the CUSIP column.
3. **Show every attribute the user filtered, sorted, or grouped by** as a visible column (e.g. "by sector" → a Sector column; "over $1bn" → an offering-size column; "by trade count" → a count column), plus any field the answer requires (e.g. YTM alongside DV01/duration).
4. Leave NULL cells empty — never write "N/A", "—", "-", or a placeholder.
5. After a multi-row table, stop — no narrative summary unless the user asked for insights.
