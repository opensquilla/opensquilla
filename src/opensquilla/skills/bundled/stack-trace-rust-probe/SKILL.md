---
name: stack-trace-rust-probe
description: "Internal helper for meta-stack-trace-investigator. Use when a Rust panic or backtrace needs Rust-specific Result/Option checks, cargo test guidance, and patch targets."
user-invocable: false
disable-model-invocation: true
provenance:
  origin: opensquilla-original
  license: Apache-2.0
---

# Stack Trace Rust Probe

Return only:

```
LANGUAGE_PROBE: rust
CHECKS:
  - <panic/unwrap/expect/Option/Result handling check>
  - <trait/lifetime/thread boundary check if relevant>
REPRODUCER:
  - <minimal cargo test command or snippet>
PATCH_TARGETS:
  - <replace unwrap/expect / map_err / explicit Result propagation target>
VERIFY:
  - <cargo test command>
```

Prefer narrow `cargo test <name>` commands when the trace exposes a symbol.
Do not recommend unsafe broad rewrites.
