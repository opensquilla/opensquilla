---
name: text-file-read
description: "Read a UTF-8 text file and emit its content on stdout. Tiny helper for meta-skills that need to round-trip an artefact through disk so the user can hand-edit it between steps (e.g. tweak script.txt during a review pause)."
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

Reads a UTF-8 text file and prints its contents to stdout. Pair with
`text-file-write` to let a user hand-edit an artefact during a meta-
skill review pause: write before the pause, read after, downstream
steps consume the (possibly edited) re-read content.

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
