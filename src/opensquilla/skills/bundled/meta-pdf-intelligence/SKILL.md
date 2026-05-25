---
name: meta-pdf-intelligence
description: "Use when the user asks to analyze, digest, compare, or query one or more PDF documents with traceable file/page evidence."
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
    - id: intake
      kind: agent
      skill: sub-agent
      with:
        task: |
          Parse the PDF request into a document-analysis contract. Determine
          whether this is a single-PDF summary, multi-PDF comparison, or a
          targeted question-answer task. Preserve every file path or URL the
          user mentioned.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Return exactly:
          MODE: <single_summary|multi_compare|question_answer>
          DOCUMENTS:
            - <path or URL>
          QUESTION: <specific question or empty>
          OUTPUT_LANGUAGE: <language>
    - id: extract
      skill: pdf-toolkit
      depends_on: [intake]
      with:
        task: "Extract text, tables, page numbers, headings, and document names for this PDF analysis contract:\n{{ outputs.intake | truncate(2000) }}"
    - id: per_document_digest
      skill: summarize
      depends_on: [extract]
      with:
        text: "Intake:\n{{ outputs.intake }}\n\nExtracted PDF content:\n{{ outputs.extract }}"
        style: pdf_per_document_digest
        max_words: 2500
    - id: cross_document_synthesis
      kind: agent
      skill: sub-agent
      depends_on: [per_document_digest]
      with:
        task: |
          Synthesize the PDF analysis according to the intake mode. For
          single_summary, produce a structured summary. For multi_compare,
          compare agreements, conflicts, and unique claims. For question_answer,
          answer the question directly first.

          Requirements:
          - cite file names and page numbers whenever available
          - never merge evidence from different documents without naming them
          - list open questions or extraction limits

          Intake:
          {{ outputs.intake | truncate(2000) }}

          Per-document digest:
          {{ outputs.per_document_digest | truncate(8000) }}
    - id: traceable_index
      kind: agent
      skill: sub-agent
      depends_on: [cross_document_synthesis]
      with:
        task: |
          Build a compact memory index for later recall. Use structured fields:
          documents, key_facts, page_refs, tables, open_questions.

          Analysis:
          {{ outputs.cross_document_synthesis | truncate(6000) }}
    - id: memorize
      skill: memory
      depends_on: [traceable_index]
      with:
        action: save
        topic: "pdf-intel"
        content: "{{ outputs.traceable_index }}"
---

# PDF Intelligence (Meta-Skill)

Process one or more PDFs into a traceable analysis entry. The workflow first
classifies the request, preserves file/page evidence, synthesizes across
documents when needed, and stores a structured memory index.

## Fallback

LLM should manually run `pdf-toolkit` scripts then summarize and
`memory_save`.
