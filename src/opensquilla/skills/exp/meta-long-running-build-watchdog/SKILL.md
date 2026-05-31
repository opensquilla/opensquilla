---
name: meta-long-running-build-watchdog
description: "Launch a long-running build/training task in tmux, inspect its pane output, and let sub-agent diagnose and propose a heal."
kind: meta
meta_priority: 30
always: false
triggers:
  - "build watchdog"
  - "build 监控"
  - "长任务 tmux"
  - "watchdog build"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
composition:
  steps:
    - id: launch
      skill: tmux
      with:
        task: "Start a detached tmux session running the command described in: {{ inputs.user_message | xml_escape | truncate(512) }}"
    - id: inspect
      skill: tmux
      depends_on: [launch]
      with:
        task: "After a short interval, scrape the pane output of the session started above and report any error or warning lines."
    - id: heal
      skill: sub-agent
      depends_on: [inspect]
      with:
        task: "Diagnose the captured logs and propose / apply a fix. Logs: {{ outputs.inspect }}"
    - id: memorize
      skill: memory
      depends_on: [heal]
      with:
        action: save
        topic: "build-watchdog"
        content: "{{ outputs.heal }}"
---

# Long-Running Build Watchdog (Meta-Skill)

Watches a long-running command via tmux, lets `sub-agent` diagnose
failures and propose a fix, and records the diagnosis to memory.
Designed for overnight model fine-tunes, CI image builds, or repeated
regression suites that may fail intermittently.

## Fallback

Manually start a tmux session, scrape output, ask the LLM to diagnose,
record the resolution.
