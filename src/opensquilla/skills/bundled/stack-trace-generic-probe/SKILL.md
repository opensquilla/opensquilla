---
name: stack-trace-generic-probe
description: "Internal helper for meta-stack-trace-investigator. Use when a stack trace language is unknown and the workflow needs language-neutral failure-contract checks, reproducer guidance, and patch targets."
user-invocable: false
disable-model-invocation: true
provenance:
  origin: opensquilla-original
  license: Apache-2.0
---

# Stack Trace Generic Probe

Return only:

```
LANGUAGE_PROBE: generic
CHECKS:
  - <schema/contract check>
  - <boundary check>
REPRODUCER:
  - <minimal language-neutral reproduction shape>
PATCH_TARGETS:
  - <defensive parsing / null handling / error propagation target>
VERIFY:
  - <safe command or manual check>
```

Base every item on the parsed trace supplied by the caller. Do not invent
files or dependencies that are not present in the request.
