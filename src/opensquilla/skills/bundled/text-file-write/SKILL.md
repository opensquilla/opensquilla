---
name: text-file-write
description: "Write a stdin-supplied UTF-8 text blob to a path. Tiny helper for meta-skills that need to persist an LLM-produced artefact (script, contract, transcript) to the run workspace without authoring a dedicated CLI wrapper per use case."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: low
    capabilities: [filesystem-write]
    requires:
      anyBins: ["python", "python3"]
entrypoint:
  command: python {baseDir}/scripts/write.py
  args:
    - --output
    - "{{ with.output }}"
    - --mode
    - "{{ with.mode | default('w') }}"
  stdin: "{{ with.text }}"
  parse: text
  timeout: 15
---

# text-file-write

Persists a text blob (passed via `with.text` → stdin) to disk as UTF-8.

## Inputs (`with:`)

| key | required | default | notes |
|---|---|---|---|
| `text` | yes | — | The text to write. Piped to the script via stdin. |
| `output` | yes | — | Absolute path of the output file. Parent dir auto-created. |
| `mode` | no | `w` | `w` overwrite, `a` append. |

## Output

Prints the absolute path of the written file on stdout.

## Failure modes

- Empty stdin → exit 1 (refuses to write a zero-byte file silently).
- OS permission failure → exit 1, stderr carries the cause.
