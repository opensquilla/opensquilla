---
name: text-file-read
description: "Read a UTF-8 text file and emit its raw content on stdout. Tiny helper for meta-skills that need to round-trip an artefact through disk so the user can hand-edit it between steps (e.g. tweak script.txt during a review pause). Unlike the builtin read_file tool — which returns line-numbered output for model display — this returns bytes verbatim, suitable for downstream parsers."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: low
    capabilities: [filesystem-read]
    requires:
      anyBins: ["python", "python3"]
entrypoint:
  command: python {baseDir}/scripts/read.py
  args:
    - --input
    - "{{ with.input }}"
    - --max-bytes
    - "{{ with.max_bytes | default(200000) }}"
  parse: text
  timeout: 10
---

# text-file-read

Reads a UTF-8 text file and prints its contents verbatim to stdout
(no line numbers, no decoration). Use this when a meta-skill needs
to round-trip an artefact through disk between steps so the user can
hand-edit the file during a clarify pause.

This skill exists alongside OpenSquilla's builtin `read_file` tool
on purpose: `read_file` is designed for LLM display and prepends a
`lineno\t` prefix to every line, which corrupts structured files
(scripts, SRT, YAML) when piped back into downstream parsers. This
skill returns the bytes unmodified.

## Inputs (`with:`)

| key | required | default | notes |
|---|---|---|---|
| `input` | yes | — | Absolute path of the file to read. |
| `max_bytes` | no | `200000` | Refuse to read files larger than this. Guards against accidental binary reads. |

## Output

The file's UTF-8 content on stdout. No trailing newline added or stripped.

## Failure modes

- Path missing → exit 1, stderr explains.
- File exceeds `max_bytes` → exit 1, stderr carries the actual size.
- Decode error → exit 1 (file isn't valid UTF-8).
