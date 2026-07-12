# Architecture Diagrams

This page collects the long-form architecture diagram source files shipped with
OpenSquilla. The two source files below are kept under
`src/opensquilla/skills/meta/` next to the meta-skill subsystem they describe;
they are reproduced here as fenced source blocks so contributors can preview
them in the docs site even without a PlantUML or draw.io renderer.

If you have a renderer installed, the canonical commands are:

```sh
# PlantUML -> SVG (Java + plantuml.jar)
plantuml -tsvg src/opensquilla/skills/meta/architecture.puml

# drawio -> SVG (drawio CLI)
drawio --export --format=svg \
  src/opensquilla/skills/meta/architecture.drawio \
  --output docs/diagrams/architecture-drawio.svg
```

If no renderer is available, the fenced source blocks below are still useful as
the source of truth — open them in any PlantUML / draw.io editor to render.

## Meta-Skill Subsystem (PlantUML source)

`src/opensquilla/skills/meta/architecture.puml`

```plantuml
@startuml meta-skill-architecture
skinparam packageStyle rectangle
skinparam backgroundColor #FEFEFE
skinparam shadowing false

title Meta-Skill Subsystem Architecture
caption src/opensquilla/skills/meta/

' ===== Package declarations =====

package "meta" #LightBlue {
  [__init__.py] as init_py
  [types.py] as types_py
  [events.py] as events_py
  [orchestrator.py] as orch_py
  [parser.py] as parser_py
  [scheduler.py] as sched_py
  [templating.py] as templ_py
  [sop_compiler.py] as sop_py

  package "executors" #LightYellow {
    [__init__.py] as exec_init
    [agent.py] as exec_agent
    [llm_classify.py] as exec_llm
    [skill_exec.py] as exec_shell
    [tool_call.py] as exec_tool
  }
}

' ===== External packages (stubs) =====
package "engine" as ext_engine #LightGray {
  [types]
  [agent]
}
package "provider" as ext_prov #LightGray {
  [protocol]
  [types]
}
package "persistence" as ext_pers #LightGray {
  [meta_run_writer]
}
package "tool_boundary" as ext_tb #LightGray {
  [ToolCall]
}
package "skills" as ext_skills #LightGray {
  [types]
}

' ===== External libraries =====
rectangle "jinja2" as lib_jinja #PaleGreen
rectangle "asyncio" as lib_async #PaleGreen
rectangle "graphlib" as lib_graph #PaleGreen
rectangle "yaml" as lib_yaml #PaleGreen
rectangle "structlog" as lib_log #PaleGreen

' ===== Data flow =====

types_py --> parser_py : exports dataclasses
types_py --> orch_py
types_py --> sched_py
types_py --> templ_py
types_py --> exec_agent
types_py --> exec_llm
types_py --> exec_shell
types_py --> exec_tool

parser_py --> sched_py : topological_order

templ_py --> exec_agent : format_step_prompt, render_with_args
templ_py --> exec_llm : _coerce_to_choice, _format_classify_prompt
templ_py --> exec_shell : _JINJA_ENV, render_with_args
templ_py --> exec_tool : render_with_args
templ_py --> sched_py : resolve_route
templ_py --> orch_py : re-exports

events_py --> exec_agent : _StepDone
events_py --> exec_llm : _StepDone
events_py --> sched_py : _StepDone, _FailoverTriggered, yield_skill_view_preface
events_py --> orch_py : yield_skill_view_preface

sched_py --> orch_py : run_dag
exec_agent --> sched_py : step events
exec_llm --> sched_py
exec_shell --> sched_py
exec_tool --> sched_py

sop_py --> parser_py : raises MetaPlanError
sop_py --> ext_skills : uses SkillLoader

orch_py --> ext_engine : AgentEvent, AgentConfig, TextDeltaEvent
orch_py --> ext_prov : LLMProvider, ChatConfig
orch_py --> ext_pers : MetaRunWriter
orch_py --> ext_tb : ToolCall
orch_py --> ext_skills : SkillSpec

templ_py --> lib_jinja
sched_py --> lib_async
sched_py --> lib_log
sop_py --> lib_yaml
parser_py --> lib_graph

exec_tool --> exec_llm : _drain_agent_runner

init_py --> types_py : __all__ from types
init_py --> parser_py : parse_meta_plan, topological_order

legend right
  **Hotspots (90d)**
  orchestrator.py  19 commits
  sop_compiler.py   9
  scheduler.py      6
  events.py         3
  skill_exec.py     3
  types.py          2
  parser.py         2
end legend

@enduml
```

## Meta-Skill Subsystem (drawio source)

`src/opensquilla/skills/meta/architecture.drawio`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" modified="2026-05-23T06:32:00.000Z" agent="opensquilla" version="24.2.5">
  <diagram id="meta-skill-arch" name="Meta-Skill Architecture">
    <!-- See src/opensquilla/skills/meta/architecture.drawio for the full source. -->
  </diagram>
</mxfile>
```

For the full drawio payload (including the gzipped diagram body), open
`src/opensquilla/skills/meta/architecture.drawio` directly in the draw.io
desktop app or at <https://app.diagrams.net>.