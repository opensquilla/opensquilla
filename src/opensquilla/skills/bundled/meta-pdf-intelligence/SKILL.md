---
name: meta-pdf-intelligence
description: "Extract text/tables from a batch of PDFs, summarize each document, and persist the digest to long-term memory for later recall."
kind: meta
meta_priority: 55
always: false
triggers:
  - "处理 PDF"
  - "PDF 抽要"
  - "PDF intelligence"
  - "pdf digest"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: extract
      skill: pdf-toolkit
      with:
        task: "Extract text and tables from the PDF(s) referenced by this user request: {{ inputs.user_message | xml_escape | truncate(512) }}"
    - id: digest
      skill: summarize
      depends_on: [extract]
      with:
        text: "{{ outputs.extract }}"
        style: structured
        max_words: 1500
    - id: memorize
      skill: memory
      depends_on: [digest]
      with:
        action: save
        topic: "pdf-intel"
        content: "{{ outputs.digest }}"
---

# PDF Intelligence (Meta-Skill)

Process a batch of PDFs into a queryable knowledge entry: extract →
summarize → persist. Subsequent turns can `memory_search` the
`pdf-intel` topic to recover any document's key facts.

## Fallback

LLM should manually run `pdf-toolkit` scripts then summarize and
`memory_save`.
