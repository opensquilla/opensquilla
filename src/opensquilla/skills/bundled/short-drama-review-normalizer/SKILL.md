---
name: short-drama-review-normalizer
description: "Internal deterministic consent gate for meta-short-drama. Normalizes one free-form script-review reply and fails closed before external image/video generation."
user-invocable: false
disable-model-invocation: true
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  requires:
    anyBins: ["python", "python3"]
  opensquilla:
    risk: low
    capabilities: []
entrypoint:
  command: python {baseDir}/scripts/normalize.py
  stdin: "{{ with.payload | tojson }}"
  parse: text
  timeout: 30
---

# short-drama-review-normalizer

Internal, deterministic consent boundary used by `meta-short-drama` after its
single free-form review pause and before any image/video provider call.

The helper accepts the verbatim `review` string and emits a bounded decision
block. Explicit approval proceeds without overrides. A recognizable,
short-drama-specific adjustment also proceeds and is preserved verbatim as
`NEW_NOTES`; an explicit cancellation cancels. Empty, placeholder, ambiguous,
or off-topic replies produce `DECISION: hold` and therefore cannot trigger
external media generation.

Explicit external-transfer restrictions also hold, even when the same reply
contains an otherwise valid adjustment. This includes negated transfer verbs,
requirements that content remain on-device or local-only, and prohibitions on
an external recipient seeing, accessing, or receiving the content. Ordinary
local edits to a character, scene, shot, lighting, or style are not treated as
privacy restrictions without one of those explicit constraints.

This helper does not call a model or the network. Its `DECISION` output is the
sole authority for downstream paid media conditions; a language model never
gets to promote an unclear reply to consent.
